"""
Простой синхронный MarketFeed для тестирования.
Запускается в отдельном потоке и публикует тики в EventBus.
"""

import asyncio
import logging
import threading
import time

import MetaTrader5 as mt5

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.thread_domains import ThreadDomain

logger = logging.getLogger(__name__)


class SimpleMarketFeed:
    """Простой синхронный MarketFeed для запуска из GUI потока."""

    # Класс-переменная для хранения asyncio loop
    _asyncio_loop = None

    def __init__(self, symbols=None, interval_sec=1.0):
        self.symbols = symbols or ["EURUSD", "GBPUSD", "USDJPY"]
        self.interval = interval_sec
        self._running = False
        self._thread = None
        self._tick_count = 0
        self.event_bus = get_event_bus()

    @classmethod
    def set_asyncio_loop(cls, loop):
        """Установить asyncio loop для публикации событий."""
        cls._asyncio_loop = loop
        logger.info(f"[SimpleFeed] Asyncio loop установлен: {loop}")

    def start(self):
        """Запуск в отдельном потоке."""
        if self._running:
            logger.warning("SimpleMarketFeed уже запущен")
            return

        logger.info(f"📡 SimpleMarketFeed STARTED для {len(self.symbols)} символов")
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self):
        """Основной цикл опроса MT5."""
        # Инициализация MT5 в этом потоке
        if not mt5.initialize():
            logger.error("SimpleMarketFeed: не удалось инициализировать MT5")
            return

        logger.info(f"SimpleMarketFeed: MT5 инициализирован в потоке")

        while self._running:
            try:
                for symbol in self.symbols:
                    if not self._running:
                        break

                    tick = mt5.symbol_info_tick(symbol)
                    if tick:
                        self._tick_count += 1

                        # Публикация в EventBus
                        if self._asyncio_loop and self._asyncio_loop.is_running():
                            try:
                                # 🔧 ИСПРАВЛЕНИЕ: Используем SystemEvent для AsyncEventBus
                                event = SystemEvent(
                                    type="market_tick",
                                    payload={
                                        "symbol": symbol,
                                        "bid": float(tick.bid),
                                        "ask": float(tick.ask),
                                        "last": float(tick.last),
                                        "time": int(tick.time),
                                    },
                                    priority=EventPriority.HIGH,
                                    source_domain=ThreadDomain.MT5_IO,
                                )

                                # 🔧 ИСПРАВЛЕНИЕ: Получаем AsyncEventBus и публикуем
                                async_event_bus = get_event_bus()

                                # Планируем публикацию в asyncio loop
                                future = asyncio.run_coroutine_threadsafe(async_event_bus.publish(event), self._asyncio_loop)

                                # Логируем каждый 10-й тик
                                if self._tick_count % 10 == 1:
                                    logger.info(
                                        f"TICK #{self._tick_count}: {symbol} | Bid: {tick.bid:.5f} | Ask: {tick.ask:.5f} | Published: {future.done()}"
                                    )

                            except Exception as e:
                                logger.error(f"[SimpleFeed] Ошибка публикации тика: {e}", exc_info=True)

                time.sleep(self.interval)

            except Exception as e:
                logger.error(f"SimpleMarketFeed error: {e}")
                time.sleep(2.0)

        mt5.shutdown()
        logger.info(f"SimpleMarketFeed STOPPED. Всего тиков: {self._tick_count}")

    def stop(self):
        """Остановка."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("SimpleMarketFeed остановлен")
