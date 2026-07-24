# src/data/market_feed.py
"""
Асинхронный сборщик рыночных данных для Genesis Trading System.

Архитектурный сдвиг:
- Было: Синхронный опрос MT5 в цикле, блокировка UI
- Стало: Асинхронный поллер в домене MT5_IO, публикация через EventBus

Особенности:
- Не блокирует GUI (работает в THREAD_POOL executor)
- Публикует события вместо прямой обработки
- Автоматический backoff при ошибках
- Защита MT5_ACCESS через lock_manager
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager, requires_locks
from src.core.thread_domains import ThreadDomain, run_in_domain

logger = logging.getLogger(__name__)


class MarketFeed:
    """
    Асинхронный сборщик рыночных данных.

    Публикует события:
    - market_tick: Новый тик с ценой
    - feed_error: Ошибка сбора данных
    - feed_status: Изменение статуса feed

    Использование:
        feed = MarketFeed(symbols=["EURUSD", "GBPUSD"], interval_sec=1.0)
        asyncio.create_task(feed.start_streaming())

        # Подписка на тики
        await event_bus.subscribe("market_tick", handler, domain=ThreadDomain.ML_INFERENCE)
    """

    def __init__(
        self,
        symbols: List[str],
        interval_sec: float = 1.0,
        mt5_instance=None,
    ):
        """
        Args:
            symbols: Список инструментов для мониторинга
            interval_sec: Интервал опроса в секундах
            mt5_instance: Экземпляр MT5 (None = использовать глобальный)
        """
        self.symbols = symbols
        self.interval = interval_sec
        self._mt5 = mt5_instance
        self.event_bus = get_event_bus()
        self._running = False
        self._error_count = 0
        self._tick_count = 0
        self._last_error: Optional[str] = None

        logger.info(f"MarketFeed initialized for {len(symbols)} symbols " f"(interval={interval_sec}s)")

    @property
    def mt5(self):
        """Получение экземпляра MT5"""
        if self._mt5 is None:
            import MetaTrader5 as mt5

            return mt5
        return self._mt5

    @run_in_domain(ThreadDomain.MT5_IO)
    async def start_streaming(self):
        """
        Основной цикл сбора данных.

        Запускать в фоне:
            asyncio.create_task(feed.start_streaming())
        """
        self._running = True
        logger.info(f"📡 MarketFeed started for {self.symbols}")

        # Публикуем статус
        await self.event_bus.publish(
            SystemEvent(
                type="feed_status",
                payload={
                    "status": "started",
                    "symbols": self.symbols,
                    "interval": self.interval,
                },
                priority=EventPriority.MEDIUM,
            )
        )

        while self._running:
            try:
                for symbol in self.symbols:
                    if not self._running:
                        break

                    tick = await self._fetch_latest_tick(symbol)
                    if tick:
                        self._tick_count += 1

                        # Публикация вместо прямой обработки
                        await self.event_bus.publish(
                            SystemEvent(
                                type="market_tick",
                                payload={
                                    "symbol": symbol,
                                    "bid": tick.get("bid"),
                                    "ask": tick.get("ask"),
                                    "time": tick.get("time"),
                                    "volume": tick.get("volume"),
                                },
                                priority=EventPriority.HIGH,
                                source_domain=ThreadDomain.MT5_IO,
                            )
                        )

                await asyncio.sleep(self.interval)

            except Exception as e:
                self._error_count += 1
                self._last_error = str(e)
                logger.error(f"Feed error: {e}", exc_info=True)

                # Публикуем ошибку
                await self.event_bus.publish(
                    SystemEvent(
                        type="feed_error",
                        payload={
                            "error": str(e),
                            "error_count": self._error_count,
                            "last_error_time": datetime.utcnow().isoformat(),
                        },
                        priority=EventPriority.HIGH,
                    )
                )

                # Backoff при ошибках
                await asyncio.sleep(min(5 * self._error_count, 30))

        # Публикуем остановку
        await self.event_bus.publish(
            SystemEvent(
                type="feed_status",
                payload={
                    "status": "stopped",
                    "total_ticks": self._tick_count,
                    "total_errors": self._error_count,
                },
                priority=EventPriority.MEDIUM,
            )
        )

        logger.info(f"📡 MarketFeed stopped " f"(ticks={self._tick_count}, errors={self._error_count})")

    @requires_locks(LockLevel.MT5_ACCESS)
    async def _fetch_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Безопасный вызов MT5 API с защитой локом.

        Returns:
            Dict с данными тика или None при ошибке
        """
        try:
            tick = self.mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.warning(f"No tick data for {symbol}")
                return None

            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "time": tick.time,
                "volume": tick.volume if hasattr(tick, "volume") else 0,
                "flags": tick.flags if hasattr(tick, "flags") else 0,
            }

        except Exception as e:
            logger.error(f"Failed to fetch tick for {symbol}: {e}")
            return None

    async def load_history(
        self,
        symbol: str,
        timeframe: int = 60,
        bars_count: int = 1000,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Загрузка исторических данных (не блокирует основной поток).

        Args:
            symbol: Инструмент
            timeframe: Таймфрейм в секундах
            bars_count: Количество баров

        Returns:
            Список баров или None при ошибке
        """

        @requires_locks(LockLevel.MT5_ACCESS)
        def _fetch_sync():
            try:
                rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, bars_count)
                if rates is None:
                    return None

                return [
                    {
                        "time": r[0],
                        "open": r[1],
                        "high": r[2],
                        "low": r[3],
                        "close": r[4],
                        "tick_volume": r[5],
                    }
                    for r in rates
                ]
            except Exception as e:
                logger.error(f"Failed to load history for {symbol}: {e}")
                return None

        # Запуск в thread pool (не блокирует asyncio loop)
        return await asyncio.to_thread(_fetch_sync)

    async def stop(self):
        """Остановка сбора данных"""
        self._running = False
        logger.info("MarketFeed stopping...")

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики работы feed"""
        return {
            "running": self._running,
            "symbols": self.symbols,
            "tick_count": self._tick_count,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "interval": self.interval,
        }
