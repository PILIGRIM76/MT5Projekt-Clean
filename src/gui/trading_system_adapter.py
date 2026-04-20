# src/gui/trading_system_adapter.py
"""
Адаптор для интеграции trading system с GUI.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import MetaTrader5 as mt5
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


@dataclass
class _HistoryDeal:
    """Минимальная структура сделки для GUI-таблицы истории."""

    ticket: int
    symbol: str
    strategy: str
    trade_type: str
    volume: float
    price_close: float
    time_close: datetime
    profit: float
    timeframe: str


class PySideTradingSystem(QObject):
    """Адаптор для запуска trading system в PySide GUI."""

    # Сигналы для GUI
    status_changed = Signal(str)
    error_occurred = Signal(str)
    metrics_updated = Signal(dict)

    def __init__(self, config=None, bridge=None, sound_manager=None, event_bus=None):
        super().__init__()
        self.config = config
        self.bridge = bridge
        self.sound_manager = sound_manager
        self.event_bus = event_bus
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._gui_sync_thread: Optional[threading.Thread] = None
        self._news_collector = None
        self._pending_observer_mode: Optional[bool] = None
        self.core_system = None  # Для совместимости с main_pyside.py
        self.system = None  # TradingSystem instance

    def set_event_bridge(self, event_bridge):
        """Устанавливает event bridge для связи с GUI."""
        self.bridge = event_bridge
        if hasattr(event_bridge, "event_bus"):
            self.event_bus = event_bridge.event_bus
        logger.info(f"Event bridge set: {event_bridge}")

    def set_observer_mode(self, mode: bool):
        """Устанавливает режим наблюдателя (для совместимости)."""
        target_system = self.system or self.core_system
        if target_system and hasattr(target_system, "set_observer_mode"):
            self.system = target_system
            self.core_system = target_system
            self.system.set_observer_mode(mode)
            logger.info(f"Observer mode set to: {mode}")
            return None
        self._pending_observer_mode = mode
        logger.warning(f"set_observer_mode delayed until system ready, mode={mode}")
        return None

    async def get_vector_db_stats(self):
        """Получает статистику VectorDB (для совместимости)."""
        if self.system and hasattr(self.system, "core"):
            # Пытаемся получить статистику из ядра
            try:
                if hasattr(self.system.core, "get_vector_db_stats"):
                    result = self.system.core.get_vector_db_stats()
                    # Если метод async, ждём результат
                    if hasattr(result, "__await__"):
                        return await result
                    return result
            except Exception as e:
                logger.warning(f"get_vector_db_stats failed: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "not_ready", "message": "System not initialized"}

    def start(self):
        """Запускает trading system в фоновом потоке."""
        if self._running:
            logger.warning("System already running")
            return

        self._running = True
        self.status_changed.emit("Starting trading system...")

        # Импортируем здесь, чтобы избежать циклических импортов
        from unittest.mock import Mock

        from src.core.trading_system import TradingSystem
        from src.data.news_collector import NewsCollector

        try:
            # Используем переданный config или загружаем из services_container
            if not self.config:
                from src.core.services_container import get_config

                self.config = get_config()

            # Создаём мок для db_manager
            db_manager = Mock()
            db_manager.Session = Mock()
            db_manager.engine = Mock()

            # Инициализируем NewsCollector если включён в конфиге
            news_enabled = getattr(self.config, "NEWS_COLLECTION_ENABLED", True)
            if news_enabled:
                self._news_collector = NewsCollector(config=self.config, db_manager=db_manager)
                logger.info("NewsCollector initialized")

            # TradingSystem ожидает dict-like config с .get(...)
            if hasattr(self.config, "model_dump"):
                core_config = self.config.model_dump()
            elif isinstance(self.config, dict):
                core_config = self.config
            else:
                core_config = vars(self.config)

            # Создаём trading system с обязательными зависимостями
            mt5_api = Mock()
            predictor = Mock()
            self.system = TradingSystem(config=core_config, mt5_api=mt5_api, db_manager=db_manager, predictor=predictor)
            self.core_system = self.system

            # Если observer mode был выставлен до запуска, применяем его сейчас
            if self._pending_observer_mode is not None and hasattr(self.system, "set_observer_mode"):
                self.system.set_observer_mode(self._pending_observer_mode)
                self._pending_observer_mode = None

            # Запускаем в отдельном потоке
            self._thread = threading.Thread(target=self._run_system, daemon=True)
            self._thread.start()
            self._start_gui_sync_loop()

            self.status_changed.emit("Trading system started")
            logger.info("Trading system started in background thread")

        except Exception as e:
            logger.error(f"Failed to start trading system: {e}", exc_info=True)
            self.error_occurred.emit(f"Failed to start: {e}")
            self._running = False

    def _start_gui_sync_loop(self):
        """Периодически отправляет в GUI баланс/позиции/историю из MT5."""
        if self._gui_sync_thread and self._gui_sync_thread.is_alive():
            return

        self._gui_sync_thread = threading.Thread(target=self._gui_sync_worker, daemon=True)
        self._gui_sync_thread.start()
        logger.info("GUI sync loop started")

    def _gui_sync_worker(self):
        last_history_sync = 0.0
        while self._running:
            try:
                if not mt5.initialize():
                    time.sleep(2.0)
                    continue

                account = mt5.account_info()
                if account and self.bridge and hasattr(self.bridge, "balance_updated"):
                    self.bridge.balance_updated.emit(float(account.balance), float(account.equity))

                positions = mt5.positions_get() or []
                if self.bridge and hasattr(self.bridge, "positions_updated"):
                    positions_payload = [p._asdict() for p in positions]
                    self.bridge.positions_updated.emit(positions_payload)

                now_ts = time.time()
                if now_ts - last_history_sync >= 10.0 and self.bridge and hasattr(self.bridge, "history_updated"):
                    utc_to = datetime.utcnow()
                    utc_from = utc_to - timedelta(days=14)
                    deals = mt5.history_deals_get(utc_from, utc_to) or []
                    history_payload = []
                    for d in deals:
                        dd = d._asdict()
                        # DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1
                        deal_type = "BUY" if dd.get("type") == 0 else "SELL"
                        history_payload.append(
                            _HistoryDeal(
                                ticket=int(dd.get("ticket", 0)),
                                symbol=str(dd.get("symbol", "")),
                                strategy="MT5",
                                trade_type=deal_type,
                                volume=float(dd.get("volume", 0.0)),
                                price_close=float(dd.get("price", 0.0)),
                                time_close=datetime.fromtimestamp(int(dd.get("time", 0))),
                                profit=float(dd.get("profit", 0.0)),
                                timeframe="N/A",
                            )
                        )
                    self.bridge.history_updated.emit(history_payload)
                    if hasattr(self.bridge, "pnl_updated"):
                        self.bridge.pnl_updated.emit(history_payload)
                    last_history_sync = now_ts
            except Exception as e:
                logger.warning(f"GUI sync worker error: {e}", exc_info=True)

            time.sleep(2.0)

    def _run_system(self):
        """Основной цикл trading system."""
        try:
            if self._news_collector and self.config:
                # Запускаем первичный сбор новостей
                import asyncio

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    news_list = loop.run_until_complete(self._news_collector.fetch_all_news())
                    self._news_collector.save_to_database(news_list)
                    logger.info(f"Initial news collection: {len(news_list)} news")
                    self.status_changed.emit(f"News collected: {len(news_list)} articles")
                finally:
                    loop.close()

            # Запускаем trading system
            import inspect

            start_result = self.system.start()
            if inspect.isawaitable(start_result):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(start_result)
                finally:
                    loop.close()

        except Exception as e:
            logger.error(f"Error in trading system thread: {e}", exc_info=True)
            self.error_occurred.emit(f"System error: {e}")
        finally:
            self._running = False

    def stop(self):
        """Останавливает trading system."""
        if not self._running:
            return

        logger.info("Stopping trading system...")
        self.status_changed.emit("Stopping trading system...")

        if hasattr(self, "system"):
            self.system.stop()

        self._running = False
        self.status_changed.emit("Trading system stopped")
        logger.info("Trading system stopped")

    def is_running(self):
        """Проверяет, запущена ли система."""
        return self._running

    async def start_all_threads(self):
        """Совместимость с async запуском из main_pyside."""
        if not self._running:
            self.start()
        return self.system is not None

    async def _on_system_restart(self, event=None):
        """Совместимость с async перезапуском через EventBus."""
        try:
            self.stop()
            self.start()
            return self.system is not None
        except Exception as e:
            logger.error(f"System restart failed: {e}", exc_info=True)
            return False
