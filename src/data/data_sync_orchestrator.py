# src/data/data_sync_orchestrator.py
"""
Асинхронный синхронизатор данных для Genesis Trading System.

Решаемые проблемы:
- Блокирующий polling → асинхронный событийный цикл
- Отсутствие persistence → автоматическое сохранение в БД
- Нет debounce/cache → проверка last_update_time и инкрементальное обновление

Архитектура:
- Параллельная синхронизация всех символов (asyncio.gather)
- Инкрементальное обновление после порога 500 баров
- Публикация событий через EventBus
- Защита MT5 вызовов через lock_manager
- Автоматический debounce (60 сек между запросами на символ)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager
from src.core.thread_domains import ThreadDomain

logger = logging.getLogger(__name__)


class DataSyncOrchestrator:
    """
    Асинхронный синхронизатор данных.

    Заменяет блокирующий polling на событийный цикл с кэшированием.

    Использование:
        syncer = DataSyncOrchestrator(
            symbols=["EURUSD", "GBPUSD"],
            mt5_api=mt5,
            db_manager=db
        )
        await syncer.start(interval_sec=10.0)
    """

    def __init__(
        self,
        symbols: List[str],
        mt5_api,
        db_manager,
        min_bars_threshold: int = 500,
        debounce_sec: int = 60,
    ):
        """
        Args:
            symbols: Список инструментов для синхронизации
            mt5_api: Экземпляр MT5 API wrapper
            db_manager: Экземпляр DatabaseManager
            min_bars_threshold: Минимум баров для перехода в инкрементальный режим
            debounce_sec: Минимальный интервал между запросами на символ (сек)
        """
        self.symbols = symbols
        self.mt5 = mt5_api
        self.db = db_manager
        self.event_bus = get_event_bus()
        self._running = False
        self._last_sync: Dict[str, datetime] = {}
        self._min_bars_threshold = min_bars_threshold
        self._debounce_sec = debounce_sec

        # Статистика
        self._sync_count = 0
        self._error_count = 0
        self._total_bars_saved = 0

        logger.info(
            f"DataSyncOrchestrator initialized: "
            f"{len(symbols)} symbols, threshold={min_bars_threshold} bars, "
            f"debounce={debounce_sec}s"
        )

    async def start(self, interval_sec: float = 10.0):
        """
        Запуск цикла синхронизации.

        Args:
            interval_sec: Базовый интервал между циклами (сек)
        """
        self._running = True
        logger.info(f"DataSyncOrchestrator started for {len(self.symbols)} symbols " f"(interval={interval_sec}s)")

        asyncio.create_task(self._polling_loop(interval_sec))

    async def stop(self):
        """Остановка синхронизатора"""
        self._running = False
        logger.info(
            f"DataSyncOrchestrator stopped "
            f"(syncs={self._sync_count}, errors={self._error_count}, "
            f"bars_saved={self._total_bars_saved})"
        )

    async def _polling_loop(self, interval: float):
        """Основной цикл синхронизации"""
        while self._running:
            loop_start = asyncio.get_event_loop().time()

            try:
                # Параллельная синхронизация всех символов
                tasks = [self._sync_symbol(sym) for sym in self.symbols]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Логирование ошибок
                for sym, result in zip(self.symbols, results):
                    if isinstance(result, Exception):
                        logger.error(f"Sync failed for {sym}: {result}")

            except Exception as e:
                logger.error(f"Polling loop error: {e}", exc_info=True)
                self._error_count += 1

            # Адаптивный sleep (учитываем время выполнения)
            elapsed = asyncio.get_event_loop().time() - loop_start
            await asyncio.sleep(max(0.1, interval - elapsed))

    async def _sync_symbol(self, symbol: str):
        """Синхронизация одного символа"""
        try:
            # 1. Проверка кэша (debounce)
            last = self._last_sync.get(symbol)
            if last and (datetime.now() - last).total_seconds() < self._debounce_sec:
                logger.debug(f"Skipping {symbol}: debounce active")
                return

            # 2. Проверка БД
            db_count = await self._get_bar_count(symbol)

            if db_count >= self._min_bars_threshold:
                # Инкрементальное обновление: только новые бары
                mode = "incremental"
                last_bar_time = await self._get_last_bar_time(symbol)
                bars = await self._fetch_mt5_incremental(symbol, last_bar_time)
            else:
                # Первая загрузка: полные 1000 баров
                mode = "full"
                bars = await self._fetch_mt5_full(symbol)

            if not bars:
                logger.debug(f"No new bars for {symbol}")
                return

            # 3. Публикация события для AsyncDBWriter (полностью асинхронная запись)
            await self.event_bus.publish(
                SystemEvent(
                    type="bars_to_save",
                    payload={
                        "symbol": symbol,
                        "bars": bars,
                        "mode": mode,
                    },
                    priority=EventPriority.MEDIUM,
                    source_domain=ThreadDomain.DATA_INGEST,
                )
            )

            saved = len(bars)
            self._last_sync[symbol] = datetime.now()
            self._sync_count += 1
            self._total_bars_saved += saved

            logger.debug(f"Queued {saved} bars for {symbol} to DB " f"(mode={mode}, total_in_db={db_count + saved})")

            # 4. Уведомление системы о синхронизации
            await self.event_bus.publish(
                SystemEvent(
                    type="data_synced",
                    payload={
                        "symbol": symbol,
                        "count": saved,
                        "mode": mode,
                        "total_bars": db_count + saved,
                    },
                    priority=EventPriority.MEDIUM,
                    source_domain=ThreadDomain.DATA_INGEST,
                )
            )

        except Exception as e:
            self._error_count += 1
            logger.error(f"Sync failed for {symbol}: {e}", exc_info=True)

            await self.event_bus.publish(
                SystemEvent(
                    type="sync_error",
                    payload={
                        "symbol": symbol,
                        "error": str(e),
                        "error_count": self._error_count,
                    },
                    priority=EventPriority.HIGH,
                )
            )

    async def _fetch_mt5_full(self, symbol: str) -> List[Dict[str, Any]]:
        """Полная загрузка 1000 баров с защитой локом."""

        def _fetch_sync():
            with lock_manager._locks[LockLevel.MT5_ACCESS]:
                import MetaTrader5 as mt5

                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1000)
                if rates is None:
                    return []

                return [
                    {
                        "time": datetime.fromtimestamp(r[0]),
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                        "tick_volume": int(r[5]),
                        "spread": int(r[6]) if len(r) > 6 else 0,
                        "real_volume": int(r[7]) if len(r) > 7 else 0,
                    }
                    for r in rates
                ]

        try:
            return await asyncio.to_thread(_fetch_sync)
        except Exception as e:
            logger.error(f"Failed to fetch full bars for {symbol}: {e}")
            return []

    async def _fetch_mt5_incremental(self, symbol: str, from_time: datetime) -> List[Dict[str, Any]]:
        """
        Загрузка только новых баров с момента последней синхронизации.

        Args:
            symbol: Инструмент
            from_time: Время последнего бара в БД

        Returns:
            Список новых баров
        """

        def _fetch_sync():
            with lock_manager._locks[LockLevel.MT5_ACCESS]:
                import MetaTrader5 as mt5

                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
                if rates is None:
                    return []

                bars = []
                for r in rates:
                    bar_time = datetime.fromtimestamp(r[0])
                    if bar_time > from_time:
                        bars.append(
                            {
                                "time": bar_time,
                                "open": float(r[1]),
                                "high": float(r[2]),
                                "low": float(r[3]),
                                "close": float(r[4]),
                                "tick_volume": int(r[5]),
                                "spread": int(r[6]) if len(r) > 6 else 0,
                                "real_volume": int(r[7]) if len(r) > 7 else 0,
                            }
                        )
                return bars

        try:
            return await asyncio.to_thread(_fetch_sync)
        except Exception as e:
            logger.error(f"Failed to fetch incremental bars for {symbol}: {e}")
            return []

    async def _get_bar_count(self, symbol: str) -> int:
        """Получение количества баров в БД"""
        if hasattr(self.db, "get_bar_count"):
            return await self.db.get_bar_count(symbol)
        return 0

    async def _get_last_bar_time(self, symbol: str) -> datetime:
        """Получение времени последнего бара в БД"""
        if hasattr(self.db, "get_last_bar_time"):
            return await self.db.get_last_bar_time(symbol)
        # Fallback: возвращаем старую дату
        return datetime.now() - timedelta(days=365)

    async def _upsert_bars(self, symbol: str, bars: List[Dict]) -> int:
        """Сохранение баров в БД"""
        if hasattr(self.db, "upsert_bars"):
            return await self.db.upsert_bars(symbol, bars)
        elif hasattr(self.db, "insert_bars"):
            return await self.db.insert_bars(symbol, bars)
        logger.warning(f"DB has no upsert_bars method, bars not saved")
        return 0

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики синхронизатора"""
        return {
            "running": self._running,
            "symbols": self.symbols,
            "sync_count": self._sync_count,
            "error_count": self._error_count,
            "total_bars_saved": self._total_bars_saved,
            "last_sync": {sym: last.isoformat() for sym, last in self._last_sync.items()},
            "debounce_sec": self._debounce_sec,
            "min_bars_threshold": self._min_bars_threshold,
        }
