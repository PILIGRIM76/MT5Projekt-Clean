# src/core/services/data_service.py
"""
Сервис данных для Genesis Trading System.

Объединяет:
- DataProvider (загрузка данных из MT5)
- Кэширование данных
- Конвертация валют

Жизненный цикл:
- start(): Инициализация кэша
- stop(): Очистка кэша
- health_check(): Проверка доступности MT5
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.config_models import Settings
from src.core.services.base_service import BaseService
from src.data.data_provider import DataProvider

logger = logging.getLogger(__name__)


class DataService(BaseService):
    """
    Сервис управления рыночными данными.

    Атрибуты:
        data_provider: Провайдер данных MT5
        mt5_lock: Блокировка для потокобезопасного доступа к MT5
    """

    def __init__(self, config: Settings):
        """
        Инициализация сервиса данных.

        Args:
            config: Конфигурация системы
        """
        super().__init__(config, name="DataService")

        # Создаём lock для потокобезопасного доступа к MT5
        self._mt5_lock = threading.Lock()

        # Инициализация DataProvider
        self.data_provider = DataProvider(config=config, mt5_lock=self._mt5_lock)

        # Статистика
        self._requests_count = 0
        self._cache_hits = 0
        self._cache_misses = 0

        self._healthy = True

    async def start(self) -> None:
        """
        Запуск сервиса данных.

        Проверяет доступность MT5 и очищает кэш.
        """
        logger.info(f"{self.name}: Запуск сервиса данных...")

        try:
            # Проверка подключения к MT5
            await self._safe_execute(self._check_mt5_connection(), "Проверка подключения к MT5")

            self._running = True
            self._healthy = True

            logger.info(f"{self.name}: Сервис запущен успешно")

        except Exception as e:
            logger.error(f"{self.name}: Ошибка при запуске: {e}", exc_info=True)
            self._healthy = False
            raise

    async def stop(self) -> None:
        """
        Остановка сервиса данных.

        Очищает кэш и закрывает соединение с MT5.
        """
        logger.info(f"{self.name}: Остановка сервиса данных...")

        try:
            # Очистка кэша
            if hasattr(self.data_provider, "_data_cache"):
                self.data_provider._data_cache.clear()

            if hasattr(self.data_provider, "_conversion_cache"):
                self.data_provider._conversion_cache.clear()

            # Закрытие MT5
            await self._safe_execute(self._shutdown_mt5(), "Закрытие MT5")

            self._running = False
            self._healthy = False

            logger.info(f"{self.name}: Сервис остановлен")

        except Exception as e:
            logger.error(f"{self.name}: Ошибка при остановке: {e}", exc_info=True)

    def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья сервиса.

        Returns:
            Словарь с информацией о состоянии:
            - status: "healthy" | "unhealthy"
            - mt5_connected: bool
            - cache_size: int
            - requests_count: int
            - cache_hit_rate: float
        """
        import MetaTrader5 as mt5

        # Проверка подключения к MT5
        mt5_connected = False
        try:
            mt5_connected = mt5.terminal_info() is not None
        except Exception:
            pass

        # Статистика кэша
        cache_size = 0
        cache_hits = 0
        cache_misses = 0

        if hasattr(self.data_provider, "_data_cache"):
            cache_size = self.data_provider._data_cache.size()

        # Расчёт hit rate
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "status": "healthy" if self._healthy and mt5_connected else "unhealthy",
            "mt5_connected": mt5_connected,
            "cache_size": cache_size,
            "requests_count": self._requests_count,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": f"{hit_rate:.1f}%",
        }

    async def _check_mt5_connection(self) -> bool:
        """Проверка подключения к MT5."""
        import MetaTrader5 as mt5

        with self._mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH, timeout=5000):
                raise ConnectionError(f"Не удалось подключиться к MT5: {mt5.last_error()}")
            mt5.shutdown()

        return True

    async def _shutdown_mt5(self) -> None:
        """Закрытие соединения с MT5."""
        import MetaTrader5 as mt5

        with self._mt5_lock:
            mt5.shutdown()

    # ===========================================
    # Публичные методы для работы с данными
    # ===========================================

    async def get_historical_data(
        self,
        symbol: str,
        timeframe: int,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """
        Получение исторических данных.

        Args:
            symbol: Символ (e.g., "EURUSD")
            timeframe: Таймфрейм (e.g., mt5.TIMEFRAME_H1)
            start_date: Дата начала
            end_date: Дата окончания

        Returns:
            DataFrame с историческими данными или None
        """
        self._requests_count += 1

        # Проверка доступности символа
        if symbol not in self.config.SYMBOLS_WHITELIST:
            logger.warning(f"{self.name}: Символ {symbol} не в whitelist")
            return None

        # Загрузка данных (синхронно, т.к. MT5 не асинхронный)
        loop = asyncio.get_event_loop()

        def _load_data():
            return self.data_provider.get_historical_data(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
            )

        df = await loop.run_in_executor(None, _load_data)

        # Обновление статистики кэша
        if df is not None:
            # Проверяем, был ли hit кэша (в DataProvider есть логирование)
            pass  # Статистика ведётся в DataProvider

        return df

    async def get_available_symbols(self) -> List[str]:
        """
        Получение списка доступных символов.

        Returns:
            Список символов
        """

        def _get_symbols():
            return self.data_provider.get_available_symbols()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_symbols)

    async def get_conversion_rate(
        self,
        from_currency: str,
        to_currency: str,
    ) -> float:
        """
        Получение курса конвертации валют.

        Args:
            from_currency: Исходная валюта
            to_currency: Целевая валюта

        Returns:
            Курс конвертации
        """

        def _get_rate():
            return self.data_provider.get_conversion_rate(from_currency, to_currency)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_rate)

    async def filter_available_symbols(
        self,
        requested_symbols: List[str],
    ) -> List[str]:
        """
        Фильтрация символов на доступность у брокера.

        Args:
            requested_symbols: Запрошенные символы

        Returns:
            Список доступных символов
        """

        def _filter():
            return self.data_provider.filter_available_symbols(requested_symbols)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _filter)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"running={self._running}, "
            f"healthy={self._healthy}, "
            f"requests={self._requests_count})"
        )
