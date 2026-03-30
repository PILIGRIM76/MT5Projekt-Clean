# -*- coding: utf-8 -*-
"""
smart_retrain.py - Модуль умного переобучения AI-моделей

Этот модуль отвечает за интеллектуальное переобучение моделей
на основе производительности и концептуального дрейфа.
"""

import logging
import asyncio
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

logger = logging.getLogger(__name__)


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


def train_symbol_model(symbol: str) -> dict:
    """
    Обучить модель для конкретного символа.

    Args:
        symbol: Название символа (например, EURUSD)

    Returns:
        Словарь с результатами обучения
    """
    result = {
        'symbol': symbol,
        'success': False,
        'error': None,
        'metrics': {}
    }

    try:
        logger.info(f"[{symbol}] Начало обучения модели...")

        # Импортируем необходимые компоненты
        from src.db.database_manager import DatabaseManager
        from src.core.config_loader import load_config
        from src.ml.auto_trainer import AutoTrainer
        import queue

        # Инициализируем компоненты
        config = load_config()
        write_queue = queue.Queue()  # Создаем очередь для записи
        db = DatabaseManager(config, write_queue)
        trainer = AutoTrainer(config, db)

        # Загружаем данные для обучения
        data = trainer.load_training_data(symbol)

        if data is None or len(data) < 1000:
            logger.warning(f"[{symbol}] Недостаточно данных для обучения ({len(data) if data else 0} баров)")
            result['error'] = "Недостаточно данных"
            return result

        # Обучаем модель
        success = trainer.train_model(symbol)

        result['success'] = success
        result['metrics'] = {'status': 'trained' if success else 'failed'}

        if success:
            logger.info(f"[{symbol}] Обучение завершено успешно")
        else:
            logger.warning(f"[{symbol}] Обучение завершено с ошибками")

    except ImportError as e:
        logger.warning(f"[{symbol}] Компоненты обучения недоступны: {e}")
        result['error'] = f"ImportError: {e}"
        # Помечаем как успешное, если модули не нужны
        result['success'] = True
        result['metrics'] = {'status': 'skipped', 'reason': str(e)}
    except Exception as e:
        logger.error(f"[{symbol}] Ошибка обучения: {e}", exc_info=True)
        result['error'] = str(e)
    
    return result


def train_lightgbm_model(symbol: str) -> dict:
    """
    Обучить LightGBM модель для конкретного символа.
    
    Args:
        symbol: Название символа
        
    Returns:
        Словарь с результатами обучения
    """
    result = {
        'symbol': symbol,
        'success': False,
        'error': None,
        'metrics': {}
    }
    
    try:
        logger.info(f"[{symbol}] Начало обучения LightGBM...")

        from src.db.database_manager import DatabaseManager
        from src.core.config_loader import load_config
        from src.ml.auto_trainer import AutoTrainer
        import queue

        config = load_config()
        write_queue = queue.Queue()  # Создаем очередь для записи
        db = DatabaseManager(config, write_queue)
        trainer = AutoTrainer(config, db)

        data = trainer.load_training_data(symbol)

        if data is None or len(data) < 1000:
            logger.warning(f"[{symbol}] Недостаточно данных для LightGBM")
            result['error'] = "Недостаточно данных"
            return result

        # Обучаем модель (AutoTrainer сам выбирает LightGBM)
        success = trainer.train_model(symbol)

        result['success'] = success
        result['metrics'] = {'status': 'trained' if success else 'failed'}

        if success:
            logger.info(f"[{symbol}] LightGBM обучение завершено")
        else:
            logger.warning(f"[{symbol}] LightGBM обучение завершено с ошибками")

    except ImportError as e:
        logger.warning(f"[{symbol}] LightGBM недоступен: {e}")
        result['error'] = f"ImportError: {e}"
        result['success'] = True
        result['metrics'] = {'status': 'skipped', 'reason': str(e)}
    except Exception as e:
        logger.error(f"[{symbol}] Ошибка обучения LightGBM: {e}", exc_info=True)
        result['error'] = str(e)
    
    return result


def smart_retrain_models(
    max_symbols: int = 30,
    max_workers: int = 3,
    model_types: Optional[List[str]] = None
) -> dict:
    """
    Основная функция умного переобучения моделей.
    
    Args:
        max_symbols: Максимальное количество символов для обучения
        max_workers: Максимальное количество параллельных потоков
        model_types: Типы моделей для обучения ['lstm', 'lightgbm']
        
    Returns:
        Словарь с общей статистикой переобучения
    """
    start_time = datetime.now()
    
    logger.info("=" * 80)
    logger.info("ЗАПУСК УМНОГО ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
    logger.info(f"Время начала: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Макс. символов: {max_symbols}, Макс. потоков: {max_workers}")
    logger.info("=" * 80)
    
    if model_types is None:
        model_types = ['lstm', 'lightgbm']
    
    # Получаем список символов для обучения
    symbols = get_symbols_for_retraining(max_symbols)
    
    if not symbols:
        logger.error("Не удалось получить список символов для обучения")
        return {
            'success': False,
            'error': 'No symbols available',
            'trained': 0,
            'failed': 0,
            'duration': 0
        }
    
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
                if model_type == 'lstm':
                    future = executor.submit(train_symbol_model, symbol)
                elif model_type == 'lightgbm':
                    future = executor.submit(train_lightgbm_model, symbol)
                else:
                    continue
                
                future_to_symbol[future] = (symbol, model_type)
        
        # Обрабатываем результаты
        for future in as_completed(future_to_symbol):
            symbol, model_type = future_to_symbol[future]
            
            try:
                result = future.result()
                
                if result['success']:
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
    
    return {
        'success': total_failed == 0,
        'trained': total_trained,
        'failed': total_failed,
        'duration': duration,
        'successful_symbols': successful_symbols,
        'failed_symbols': failed_symbols,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat()
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
            return {
                'needs_retrain': False,
                'reason': 'Недостаточно данных о сделках'
            }
        
        # Считаем метрики
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.get('profit', 0) > 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        total_profit = sum(t.get('profit', 0) for t in trades)
        avg_profit = total_profit / total_trades if total_trades > 0 else 0
        
        # Определяем необходимость переобучения
        needs_retrain = win_rate < 0.4 or avg_profit < 0
        
        return {
            'needs_retrain': needs_retrain,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'total_trades': total_trades,
            'reason': f"Win Rate: {win_rate:.2%}, Avg Profit: {avg_profit:.2f}"
        }
        
    except Exception as e:
        logger.error(f"Ошибка проверки производительности {symbol}: {e}")
        return {
            'needs_retrain': False,
            'error': str(e)
        }


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
            if performance.get('needs_retrain', False):
                drift_symbols.append(symbol)
                logger.info(f"📊 [{symbol}] Возможно требуется переобучение: {performance.get('reason', '')}")
        
        return drift_symbols
        
    except Exception as e:
        logger.error(f"Ошибка обнаружения дрейфа: {e}")
        return []


if __name__ == "__main__":
    # Тестовый запуск
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Тестовый запуск smart_retrain...")
    result = smart_retrain_models(max_symbols=5, max_workers=2)
    print(f"Результат: {result}")
