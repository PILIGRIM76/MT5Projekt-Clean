# src/data/data_collector.py
"""
Data Collector — Непрерывный сбор и накопление исторических данных.

Источники (бесплатные):
1. MetaTrader 5 — основные Forex пары
2. Yahoo Finance — индексы, акции, крипто
3. Alpha Vantage — дополнительные данные

Функции:
- Автоматическая загрузка исторических данных
- Накопление в базу данных
- Проверка целостности данных
- Планирование сбора
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from src.core.config_models import Settings
from src.core.mt5_connection_manager import mt5_ensure_connected
from src.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class DataCollector:
    """
    Сборщик данных для Genesis Trading System.

    Атрибуты:
        config: Конфигурация системы
        db_manager: Менеджер базы данных
        mt5_path: Путь к MT5 терминалу
    """

    def __init__(self, config: Settings, db_manager: DatabaseManager):
        """
        Инициализация сборщика данных.

        Args:
            config: Конфигурация системы
            db_manager: Менеджер базы данных
        """
        self.config = config
        self.db_manager = db_manager
        self.mt5_path = config.MT5_PATH

        # Настройки сбора
        self.timeframes = {
            "M1": mt5.TIMEFRAME_M1 if mt5 else None,
            "M5": mt5.TIMEFRAME_M5 if mt5 else None,
            "M15": mt5.TIMEFRAME_M15 if mt5 else None,
            "H1": mt5.TIMEFRAME_H1 if mt5 else None,
            "H4": mt5.TIMEFRAME_H4 if mt5 else None,
            "D1": mt5.TIMEFRAME_D1 if mt5 else None,
        }

        # Символы для сбора
        self.symbols = config.SYMBOLS_WHITELIST

        # Глубина истории (в днях)
        self.history_depth_days = getattr(config, "DATA_HISTORY_DEPTH_DAYS", 365)

        # Блокировка для потокобезопасности
        self._lock = threading.Lock()

        # Статистика
        self.stats = {"last_collection_time": None, "symbols_collected": 0, "bars_collected": 0, "errors": 0}

        logger.info("Data Collector инициализирован")
        logger.info(f"  - Символов: {len(self.symbols)}")
        logger.info(f"  - Глубина истории: {self.history_depth_days} дней")
        logger.info(f"  - Таймфреймы: {list(self.timeframes.keys())}")

    def initialize_mt5(self) -> bool:
        """
        Инициализирует подключение к MT5.

        Returns:
            True если успешно
        """
        if mt5 is None:
            logger.error("MetaTrader5 не установлен")
            return False

        try:
            if not mt5_ensure_connected(path=self.mt5_path):
                logger.error(f"Ошибка инициализации MT5: {mt5.last_error()}")
                return False

            logger.info("MT5 инициализирован успешно")
            return True

        except Exception as e:
            logger.error(f"Ошибка при инициализации MT5: {e}")
            return False

    def shutdown_mt5(self):
        """Корректно закрывает подключение к MT5."""
        try:
            if mt5 and mt5.terminal_info():
                mt5.shutdown()
                logger.info("MT5 отключен")
        except Exception as e:
            logger.error(f"Ошибка при отключении MT5: {e}")

    def collect_historical_data(self, symbol: str, timeframe: str = "H1", bars_count: int = 10000) -> Optional[pd.DataFrame]:
        """
        Загружает исторические данные для символа.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм (M1, M5, M15, H1, H4, D1)
            bars_count: Количество баров для загрузки

        Returns:
            DataFrame с историческими данными или None
        """
        if not self.initialize_mt5():
            return None

        try:
            tf = self.timeframes.get(timeframe)
            if tf is None:
                logger.error(f"Неверный таймфрейм: {timeframe}")
                return None

            # Загружаем данные
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars_count)

            if rates is None or len(rates) == 0:
                logger.warning(f"Нет данных для {symbol} {timeframe}")
                return None

            # Конвертируем в DataFrame
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")

            logger.info(f"Загружено {len(df)} баров для {symbol} {timeframe}")

            return df

        except Exception as e:
            logger.error(f"Ошибка загрузки данных для {symbol}: {e}")
            return None

        finally:
            self.shutdown_mt5()

    def collect_all_symbols(self, timeframe: str = "H1") -> Dict[str, pd.DataFrame]:
        """
        Загружает данные для всех символов из whitelist.

        Args:
            timeframe: Таймфрейм для сбора

        Returns:
            Словарь {symbol: DataFrame}
        """
        logger.info(f"Начало сбора данных для {len(self.symbols)} символов...")

        all_data = {}
        start_time = time.time()

        for i, symbol in enumerate(self.symbols, 1):
            logger.info(f"[{i}/{len(self.symbols)}] Загрузка {symbol}...")

            try:
                data = self.collect_historical_data(symbol, timeframe)
                if data is not None:
                    all_data[symbol] = data
                    self.stats["symbols_collected"] += 1
                    self.stats["bars_collected"] += len(data)
                else:
                    self.stats["errors"] += 1

            except Exception as e:
                logger.error(f"Ошибка при загрузке {symbol}: {e}")
                self.stats["errors"] += 1

            # Небольшая пауза между запросами
            time.sleep(0.5)

        elapsed = time.time() - start_time
        self.stats["last_collection_time"] = datetime.now()

        logger.info(
            f"Сбор данных завершён за {elapsed:.1f} сек. "
            f"Символов: {self.stats['symbols_collected']}, "
            f"Баров: {self.stats['bars_collected']}, "
            f"Ошибок: {self.stats['errors']}"
        )

        return all_data

    def save_to_database(self, symbol: str, df: pd.DataFrame, timeframe: str = "H1"):
        """
        Сохраняет данные в базу данных.

        Args:
            symbol: Торговый инструмент
            df: DataFrame с данными
            timeframe: Таймфрейм
        """
        try:
            # Создаём таблицу если не существует
            table_name = f"historical_data_{timeframe}"

            # Добавляем символ
            df_copy = df.copy()
            df_copy["symbol"] = symbol

            # Сохраняем в SQLite
            df_copy.to_sql(table_name, self.db_manager.engine, if_exists="append", index=False, method="multi", chunksize=1000)

            logger.info(f"Сохранено {len(df)} баров {symbol} {timeframe} в БД")

        except Exception as e:
            logger.error(f"Ошибка сохранения в БД: {e}")

    def collect_and_save(self, timeframe: str = "H1") -> bool:
        """
        Загружает и сохраняет данные для всех символов.

        Args:
            timeframe: Таймфрейм для сбора

        Returns:
            True если успешно
        """
        with self._lock:
            try:
                all_data = self.collect_all_symbols(timeframe)

                for symbol, df in all_data.items():
                    self.save_to_database(symbol, df, timeframe)

                return len(all_data) > 0

            except Exception as e:
                logger.error(f"Ошибка при сборе и сохранении: {e}")
                return False

    def get_last_bar_time(self, symbol: str, timeframe: str = "H1") -> Optional[datetime]:
        """
        Получает время последнего бара в базе данных.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм

        Returns:
            Время последнего бара или None
        """
        try:
            table_name = f"historical_data_{timeframe}"

            query = f"""
                SELECT MAX(time) as last_time
                FROM {table_name}
                WHERE symbol = ?
            """

            result = pd.read_sql_query(query, self.db_manager.engine, params=(symbol,))

            if len(result) > 0 and pd.notna(result["last_time"].iloc[0]):
                return result["last_time"].iloc[0]

            return None

        except Exception as e:
            logger.error(f"Ошибка получения последнего бара: {e}")
            return None

    def collect_new_data(self, symbol: str, timeframe: str = "H1") -> Optional[pd.DataFrame]:
        """
        Загружает только новые данные с момента последнего сбора.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм

        Returns:
            DataFrame с новыми данными или None
        """
        if not self.initialize_mt5():
            return None

        try:
            # Получаем время последнего бара
            last_time = self.get_last_bar_time(symbol, timeframe)

            tf = self.timeframes.get(timeframe)
            if tf is None:
                return None

            if last_time is None:
                # Если нет данных, загружаем историю
                return self.collect_historical_data(symbol, timeframe)

            # Загружаем данные с момента последнего бара
            rates = mt5.copy_rates_from(symbol, tf, last_time, 1000)

            if rates is None or len(rates) <= 1:
                return None

            # Пропускаем первый бар (он уже есть в БД)
            rates = rates[1:]

            if len(rates) == 0:
                return None

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")

            logger.info(f"Загружено {len(df)} новых баров для {symbol}")

            return df

        except Exception as e:
            logger.error(f"Ошибка загрузки новых данных: {e}")
            return None

        finally:
            self.shutdown_mt5()

    def collect_incremental(self, timeframe: str = "H1") -> int:
        """
        Загружает новые данные для всех символов.

        Args:
            timeframe: Таймфрейм

        Returns:
            Количество загруженных баров
        """
        total_bars = 0

        for symbol in self.symbols:
            try:
                new_data = self.collect_new_data(symbol, timeframe)

                if new_data is not None and len(new_data) > 0:
                    self.save_to_database(symbol, new_data, timeframe)
                    total_bars += len(new_data)

            except Exception as e:
                logger.error(f"Ошибка при загрузке {symbol}: {e}")

        logger.info(f"Загружено {total_bars} новых баров")

        return total_bars

    def verify_data_integrity(self, symbol: str, timeframe: str = "H1") -> Dict[str, Any]:
        """
        Проверяет целостность данных в базе.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм

        Returns:
            Статистика целостности
        """
        try:
            table_name = f"historical_data_{timeframe}"

            query = f"""
                SELECT
                    COUNT(*) as total_bars,
                    MIN(time) as first_bar,
                    MAX(time) as last_bar,
                    AVG(tick_volume) as avg_volume
                FROM {table_name}
                WHERE symbol = ?
            """

            result = pd.read_sql_query(query, self.db_manager.engine, params=(symbol,))

            if len(result) == 0:
                return {"error": "Нет данных"}

            # Проверяем на пропуски
            df = pd.read_sql_query(
                f"SELECT time FROM {table_name} WHERE symbol = ? ORDER BY time", self.db_manager.engine, params=(symbol,)
            )

            gaps = 0
            if len(df) > 1:
                time_diff = df["time"].diff()
                expected_diff = pd.Timedelta(hours=1) if timeframe == "H1" else pd.Timedelta(minutes=int(timeframe[1:]))
                gaps = (time_diff > expected_diff * 1.5).sum()

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "total_bars": int(result["total_bars"].iloc[0]),
                "first_bar": result["first_bar"].iloc[0],
                "last_bar": result["last_bar"].iloc[0],
                "avg_volume": float(result["avg_volume"].iloc[0]),
                "gaps": int(gaps),
                "integrity": "OK" if gaps < 10 else "WARN",
            }

        except Exception as e:
            logger.error(f"Ошибка проверки целостности: {e}")
            return {"error": str(e)}

    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику сборщика."""
        return {**self.stats, "symbols_total": len(self.symbols), "history_depth_days": self.history_depth_days}


class DataCollectorScheduler:
    """
    Планировщик для автоматического сбора данных.

    Запускает сбор данных по расписанию.
    """

    def __init__(self, data_collector: DataCollector, config: Settings):
        """
        Инициализация планировщика.

        Args:
            data_collector: Сборщик данных
            config: Конфигурация системы
        """
        self.data_collector = data_collector
        self.config = config

        # Интервал сбора (в минутах)
        self.collection_interval = getattr(config, "DATA_COLLECTION_INTERVAL_MINUTES", 60)

        # Флаг работы
        self._running = False
        self._thread: Optional[threading.Thread] = None

        logger.info(f"Data Collector Scheduler инициализирован (интервал: {self.collection_interval} мин)")

    def start(self):
        """Запускает планировщик."""
        if self._running:
            logger.warning("Планировщик уже запущен")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("Планировщик запущен")

    def stop(self):
        """Останавливает планировщик."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Планировщик остановлен")

    def _run_loop(self):
        """Основной цикл планировщика."""
        logger.info("Запуск цикла сбора данных...")

        while self._running:
            try:
                # Сбор новых данных
                logger.info("Запуск сбора новых данных...")
                bars_collected = self.data_collector.collect_incremental("H1")

                if bars_collected > 0:
                    logger.info(f"Собрано {bars_collected} новых баров")

                # Пауза до следующего сбора
                logger.info(f"Следующий сбор через {self.collection_interval} мин")

                # Разбиваем ожидание на интервалы для быстрого выхода
                for _ in range(self.collection_interval * 60):  # Конвертируем в секунды
                    if not self._running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Ошибка в цикле сбора данных: {e}")
                time.sleep(60)  # Пауза при ошибке

    def collect_now(self):
        """Запускает сбор данных немедленно."""
        logger.info("Запуск немедленного сбора данных...")
        bars = self.data_collector.collect_incremental("H1")
        logger.info(f"Собрано {bars} баров")
        return bars
