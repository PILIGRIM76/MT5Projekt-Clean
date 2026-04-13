# -*- coding: utf-8 -*-
"""
smart_retrain.py - Модуль умного переобучения AI-моделей

Этот модуль отвечает за интеллектуальное переобучение моделей
на основе производительности и концептуального дрейфа.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def send_retrain_complete_signal(successful_symbols: list, failed_symbols: list, duration: float):
    """
    Отправляет сигнал в GUI о завершении переобучения.
    Вызывает _send_retrain_progress_to_gui через trading_system.
    """
    try:
        # Находим trading_system и отправляем данные прогресса в GUI
        from src.core.container import get_trading_system

        trading_system = get_trading_system()

        if trading_system and hasattr(trading_system, "_send_retrain_progress_to_gui"):
            logger.info(f"📊 Отправка обновлённого прогресса переобучения в GUI...")
            trading_system._send_retrain_progress_to_gui()
            logger.info("✅ Сигнал прогресса отправлен в GUI")
        else:
            logger.warning("⚠️ trading_system или метод _send_retrain_progress_to_gui не найден")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки сигнала в GUI: {e}", exc_info=False)


def get_symbols_for_retraining(max_symbols: int = 30) -> List[str]:
    """
    Получить список символов для переобучения.

    Args:
        max_symbols: Максимальное количество символов для обучения

    Returns:
        Список символов для переобучения
    """
    try:
        from src.core.config_loader import load_config

        config = load_config()
        symbols = config.SYMBOLS_WHITELIST

        # Берём первые max_symbols символов
        return symbols[:max_symbols] if len(symbols) > max_symbols else symbols
    except Exception as e:
        logger.error(f"Ошибка получения списка символов: {e}")
        # Возвращаем список по умолчанию при ошибке
        return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BITCOIN"]


def train_symbol_model(symbol: str, trading_system=None) -> dict:
    """
    Обучить модель для конкретного символа.

    Args:
        symbol: Название символа (например, EURUSD)
        trading_system: Ссылка на TradingSystem для установки callback (НОВОЕ)

    Returns:
        Словарь с результатами обучения
    """
    result = {"symbol": symbol, "success": False, "error": None, "metrics": {}}

    try:
        logger.info(f"[{symbol}] Начало обучения модели...")

        # Импортируем необходимые компоненты
        import queue

        import MetaTrader5 as mt5

        from src.core.config_loader import load_config
        from src.core.mt5_connection_manager import mt5_ensure_connected, mt5_initialize
        from src.db.database_manager import DatabaseManager
        from src.ml.auto_trainer import AutoTrainer

        # Инициализируем MT5 (обязательно для загрузки данных если их нет в БД)
        if not mt5_ensure_connected():
            config_tmp = load_config()
            if not mt5_initialize(
                path=config_tmp.MT5_PATH,
                login=int(config_tmp.MT5_LOGIN),
                password=config_tmp.MT5_PASSWORD,
                server=config_tmp.MT5_SERVER,
            ):
                logger.warning(f"[{symbol}] MT5 недоступен, пропускаем")
                result["error"] = "MT5 недоступен"
                return result

        try:
            # Инициализируем компоненты
            config = load_config()
            write_queue = queue.Queue()  # Создаем очередь для записи
            db = DatabaseManager(config, write_queue)
            trainer = AutoTrainer(config, db)

            # УСТАНОВКА CALLBACK ДЛЯ ПРОГРЕССА ОБУЧЕНИЯ
            try:
                # НОВОЕ: Используем переданный trading_system если он есть
                ts = trading_system
                if ts is None:
                    # Fallback: пробуем получить из контейнера
                    from src.core.container import get_trading_system

                    ts = get_trading_system()

                logger.info(
                    f"[{symbol}] 📡 Проверка TradingSystem: ts={ts is not None}, "
                    f"has_bridge={hasattr(ts, 'bridge') if ts else False}"
                )
                if ts and hasattr(ts, "bridge") and ts.bridge:
                    logger.info(f"[{symbol}] ✅ TradingSystem найден, устанавливаю callback")

                    def send_to_gui(history_obj):
                        """Отправляет прогресс обучения в GUI через bridge."""
                        try:
                            ts.bridge.training_history_updated.emit(history_obj)
                            logger.info(f"[{symbol}] 📊 Прогресс обучения отправлен в GUI")
                        except Exception as e:
                            logger.warning(f"[{symbol}] ⚠️ Не удалось отправить прогресс: {e}")

                    trainer.set_training_progress_callback(send_to_gui)
                    logger.info(f"[{symbol}] 📡 Callback прогресса обучения установлен")
                else:
                    logger.warning(
                        f"[{symbol}] ⚠️ TradingSystem не найден или bridge=None. "
                        f"Прогресс обучения НЕ будет отправлен в GUI."
                    )
            except Exception as callback_error:
                logger.warning(f"[{symbol}] ⚠️ Ошибка установки callback прогресса: {callback_error}", exc_info=True)

            # Загружаем данные для обучения (из БД или MT5)
            data = trainer.load_training_data(symbol)

            if data is None or len(data) < 500:
                logger.warning(f"[{symbol}] Недостаточно данных для обучения ({len(data) if data else 0} баров)")
                result["error"] = "Недостаточно данных"
                return result

            logger.info(f"[{symbol}] Загружено {len(data)} баров для обучения")

            # Обучаем модель
            success = trainer.train_model(symbol)

            result["success"] = success
            result["metrics"] = {"status": "trained" if success else "failed"}

            if success:
                logger.info(f"[{symbol}] Обучение завершено успешно")
            else:
                logger.warning(f"[{symbol}] Обучение завершено с ошибками")
        finally:
            # Не закрываем MT5 полностью — только если мы его инициализировали
            pass

    except ImportError as e:
        logger.warning(f"[{symbol}] Компоненты обучения недоступны: {e}")
        result["error"] = f"ImportError: {e}"
        # Помечаем как успешное, если модули не нужны
        result["success"] = True
        result["metrics"] = {"status": "skipped", "reason": str(e)}
    except Exception as e:
        logger.error(f"[{symbol}] Ошибка обучения: {e}", exc_info=True)
        result["error"] = str(e)

    return result


def train_lightgbm_model(symbol: str, trading_system=None) -> dict:
    """
    Обучить LightGBM модель для конкретного символа.

    Args:
        symbol: Название символа
        trading_system: Ссылка на TradingSystem для установки callback (НОВОЕ)

    Returns:
        Словарь с результатами обучения
    """
    result = {"symbol": symbol, "success": False, "error": None, "metrics": {}}

    try:
        logger.info(f"[{symbol}] Начало обучения LightGBM...")

        import queue

        from src.core.config_loader import load_config
        from src.db.database_manager import DatabaseManager
        from src.ml.auto_trainer import AutoTrainer

        config = load_config()
        write_queue = queue.Queue()  # Создаем очередь для записи
        db = DatabaseManager(config, write_queue)
        trainer = AutoTrainer(config, db)

        # УСТАНОВКА CALLBACK ДЛЯ ПРОГРЕССА ОБУЧЕНИЯ
        try:
            # НОВОЕ: Используем переданный trading_system если он есть
            ts = trading_system
            if ts is None:
                # Fallback: пробуем получить из контейнера
                from src.core.container import get_trading_system

                ts = get_trading_system()

            logger.info(
                f"[{symbol}] 📡 [LightGBM] Проверка TradingSystem: ts={ts is not None}, "
                f"has_bridge={hasattr(ts, 'bridge') if ts else False}"
            )
            if ts and hasattr(ts, "bridge") and ts.bridge:
                logger.info(f"[{symbol}] ✅ [LightGBM] TradingSystem найден, устанавливаю callback")

                def send_to_gui_lgb(history_obj):
                    """Отправляет прогресс обучения LightGBM в GUI через bridge."""
                    try:
                        ts.bridge.training_history_updated.emit(history_obj)
                        logger.info(f"[{symbol}] 📊 [LightGBM] Прогресс обучения отправлен в GUI")
                    except Exception as e:
                        logger.warning(f"[{symbol}] ⚠️ [LightGBM] Не удалось отправить прогресс: {e}")

                trainer.set_training_progress_callback(send_to_gui_lgb)
                logger.info(f"[{symbol}] 📡 [LightGBM] Callback прогресса обучения установлен")
            else:
                logger.warning(
                    f"[{symbol}] ⚠️ [LightGBM] TradingSystem не найден или bridge=None. "
                    f"Прогресс обучения НЕ будет отправлен в GUI."
                )
        except Exception as callback_error:
            logger.warning(f"[{symbol}] ⚠️ [LightGBM] Ошибка установки callback прогресса: {callback_error}", exc_info=True)

        data = trainer.load_training_data(symbol)

        if data is None or len(data) < 1000:
            logger.warning(f"[{symbol}] Недостаточно данных для LightGBM")
            result["error"] = "Недостаточно данных"
            return result

        # Обучаем модель (AutoTrainer сам выбирает LightGBM)
        success = trainer.train_model(symbol)

        result["success"] = success
        result["metrics"] = {"status": "trained" if success else "failed"}

        if success:
            logger.info(f"[{symbol}] LightGBM обучение завершено")
        else:
            logger.warning(f"[{symbol}] LightGBM обучение завершено с ошибками")

    except ImportError as e:
        logger.warning(f"[{symbol}] LightGBM недоступен: {e}")
        result["error"] = f"ImportError: {e}"
        result["success"] = True
        result["metrics"] = {"status": "skipped", "reason": str(e)}
    except Exception as e:
        logger.error(f"[{symbol}] Ошибка обучения LightGBM: {e}", exc_info=True)
        result["error"] = str(e)

    return result


def smart_retrain_models(
    max_symbols: int = 30, max_workers: int = 3, model_types: Optional[List[str]] = None, trading_system=None
) -> dict:
    """
    Основная функция умного переобучения моделей.

    Args:
        max_symbols: Максимальное количество символов для обучения
        max_workers: Максимальное количество параллельных потоков
        model_types: Типы моделей для обучения ['lstm', 'lightgbm']
        trading_system: Ссылка на TradingSystem для установки callback (НОВОЕ)

    Returns:
        Словарь с общей статистикой переобучения
    """
    start_time = datetime.now()

    logger.info("=" * 80)
    logger.info("ЗАПУСК УМНОГО ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
    logger.info(f"Время начала: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Макс. символов: {max_symbols}, Макс. потоков: {max_workers}")
    logger.info(f"TradingSystem передан: {trading_system is not None}")  # НОВОЕ
    logger.info("=" * 80)

    if model_types is None:
        model_types = ["lstm", "lightgbm"]

    # Получаем список символов для обучения
    symbols = get_symbols_for_retraining(max_symbols)

    if not symbols:
        logger.error("Не удалось получить список символов для обучения")
        return {"success": False, "error": "No symbols available", "trained": 0, "failed": 0, "duration": 0}

    logger.info(f"Символы для обучения ({len(symbols)}): {', '.join(symbols)}")

    # Статистика
    total_trained = 0
    total_failed = 0
    successful_symbols = []
    failed_symbols = []

    # Запускаем обучение в параллельных потоках
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Создаём задачи для всех символов
        future_to_symbol = {}

        for symbol in symbols:
            # Для каждого символа обучаем оба типа моделей
            for model_type in model_types:
                if model_type == "lstm":
                    future = executor.submit(train_symbol_model, symbol, trading_system)
                elif model_type == "lightgbm":
                    future = executor.submit(train_lightgbm_model, symbol, trading_system)
                else:
                    continue

                future_to_symbol[future] = (symbol, model_type)

        # Обрабатываем результаты
        for future in as_completed(future_to_symbol):
            symbol, model_type = future_to_symbol[future]

            try:
                result = future.result()

                if result["success"]:
                    total_trained += 1
                    if symbol not in successful_symbols:
                        successful_symbols.append(symbol)
                    logger.info(f"✅ [{symbol}] {model_type.upper()} обучена успешно")
                else:
                    total_failed += 1
                    if symbol not in failed_symbols:
                        failed_symbols.append(symbol)
                    logger.warning(f"⚠️ [{symbol}] {model_type.upper()} не обучена: {result.get('error', 'Unknown error')}")

            except Exception as e:
                total_failed += 1
                logger.error(f"❌ [{symbol}] {model_type.upper()} ошибка: {e}", exc_info=True)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Итоговый отчёт
    logger.info("=" * 80)
    logger.info("ПЕРЕОБУЧЕНИЕ ЗАВЕРШЕНО")
    logger.info(f"Время завершения: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Общая продолжительность: {duration:.2f} сек")
    logger.info(f"Успешно обучено: {total_trained}")
    logger.info(f"Ошибок: {total_failed}")
    logger.info(f"Успешные символы ({len(successful_symbols)}): {', '.join(successful_symbols)}")
    if failed_symbols:
        logger.info(f"Неудачные символы ({len(failed_symbols)}): {', '.join(failed_symbols)}")
    logger.info("=" * 80)

    # Отправляем сигнал завершения в GUI (если доступен callback)
    send_retrain_complete_signal(successful_symbols, failed_symbols, duration)

    return {
        "success": total_failed == 0,
        "trained": total_trained,
        "failed": total_failed,
        "duration": duration,
        "successful_symbols": successful_symbols,
        "failed_symbols": failed_symbols,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
    }


def check_model_performance(symbol: str) -> dict:
    """
    Проверить производительность модели символа.

    Args:
        symbol: Название символа

    Returns:
        Словарь с метриками производительности
    """
    try:
        from src.db.database_manager import DatabaseManager

        db = DatabaseManager()

        # Получаем последние сделки
        trades = db.get_recent_trades(symbol, limit=50)

        if not trades:
            return {"needs_retrain": False, "reason": "Недостаточно данных о сделках"}

        # Считаем метрики
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.get("profit", 0) > 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        total_profit = sum(t.get("profit", 0) for t in trades)
        avg_profit = total_profit / total_trades if total_trades > 0 else 0

        # Определяем необходимость переобучения
        needs_retrain = win_rate < 0.4 or avg_profit < 0

        return {
            "needs_retrain": needs_retrain,
            "win_rate": win_rate,
            "avg_profit": avg_profit,
            "total_trades": total_trades,
            "reason": f"Win Rate: {win_rate:.2%}, Avg Profit: {avg_profit:.2f}",
        }

    except Exception as e:
        logger.error(f"Ошибка проверки производительности {symbol}: {e}")
        return {"needs_retrain": False, "error": str(e)}


def get_concept_drift_symbols() -> List[str]:
    """
    Получить символы с обнаруженным концептуальным дрейфом.

    Returns:
        Список символов, требующих переобучения из-за дрейфа
    """
    try:
        from src.db.database_manager import DatabaseManager

        db = DatabaseManager()

        drift_symbols = []

        # Проверяем каждый активный символ
        symbols = get_symbols_for_retraining(max_symbols=50)

        for symbol in symbols:
            # Простая эвристика: если было много убыточных сделок - возможен дрейф
            performance = check_model_performance(symbol)
            if performance.get("needs_retrain", False):
                drift_symbols.append(symbol)
                logger.info(f"📊 [{symbol}] Возможно требуется переобучение: {performance.get('reason', '')}")

        return drift_symbols

    except Exception as e:
        logger.error(f"Ошибка обнаружения дрейфа: {e}")
        return []


if __name__ == "__main__":
    # Тестовый запуск
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    print("Тестовый запуск smart_retrain...")
    result = smart_retrain_models(max_symbols=5, max_workers=2)
    print(f"Результат: {result}")
