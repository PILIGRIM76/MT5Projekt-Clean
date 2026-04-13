# src/gui/event_bridge.py
"""
Мост между asyncio EventBus и Qt сигналами для Genesis Trading System.

Архитектурный сдвиг:
- Было: Прямые вызовы mt5.* или db.* из слотов, блокировка UI
- Стало: Только подписка на EventBus, реактивное обновление через сигналы

Особенности:
- Все обновления GUI в главном потоке Qt (через Signal)
- Блокирующие операции в background потоках
- Автоматический маршалинг между потоками
"""

import logging
from typing import Any, Dict

from PySide6.QtCore import QObject, Signal

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.thread_domains import ThreadDomain

logger = logging.getLogger(__name__)


class GUIEventBridge(QObject):
    """
    Безопасный мост между asyncio EventBus и Qt сигналами.

    Сигналы:
    - market_tick_received: Новый тик рынка
    - prediction_updated: Обновление предсказания
    - trade_executed: Исполнение ордера
    - system_status: Статус системы
    - system_alert: Системный алерт

    Использование:
        bridge = GUIEventBridge()
        bridge.market_tick_received.connect(on_tick)
        bridge.prediction_updated.connect(on_prediction)

        await bridge.start_listening()
    """

    # Signals для отправки в GUI
    market_tick_received = Signal(dict)
    prediction_updated = Signal(dict)
    trade_executed = Signal(dict)
    system_status = Signal(str)
    system_alert = Signal(str)
    feed_status = Signal(dict)
    model_updated = Signal(dict)

    def __init__(self):
        super().__init__()
        self.event_bus = get_event_bus()
        self._subscribed = False

        logger.info("GUIEventBridge initialized")

    async def start_listening(self):
        """
        Подписка на события для GUI.

        Вызывать один раз при старте приложения.
        """
        if self._subscribed:
            logger.warning("GUIEventBridge already subscribed")
            return

        # Market ticks
        await self.event_bus.subscribe(
            "market_tick",
            self._on_market_tick,
            domain=ThreadDomain.GUI,
            priority=EventPriority.MEDIUM,
        )

        # Predictions
        await self.event_bus.subscribe(
            "model_prediction",
            self._on_prediction,
            domain=ThreadDomain.GUI,
            priority=EventPriority.MEDIUM,
        )

        # Trade executions
        await self.event_bus.subscribe(
            "trade_executed",
            self._on_trade,
            domain=ThreadDomain.GUI,
            priority=EventPriority.HIGH,
        )

        # System status
        await self.event_bus.subscribe(
            "system_status",
            self._on_status,
            domain=ThreadDomain.GUI,
            priority=EventPriority.LOW,
        )

        # Alerts
        await self.event_bus.subscribe(
            "feed_error",
            self._on_alert,
            domain=ThreadDomain.GUI,
            priority=EventPriority.HIGH,
        )

        # Feed status
        await self.event_bus.subscribe(
            "feed_status",
            self._on_feed_status,
            domain=ThreadDomain.GUI,
        )

        # Model updates
        await self.event_bus.subscribe(
            "model_updated",
            self._on_model_updated,
            domain=ThreadDomain.GUI,
        )

        self._subscribed = True
        logger.info("GUIEventBridge started listening")

    def _on_market_tick(self, event: SystemEvent):
        """Обработка тика рынка"""
        self.market_tick_received.emit(event.payload)

    def _on_prediction(self, event: SystemEvent):
        """Обработка предсказания"""
        self.prediction_updated.emit(event.payload)

    def _on_trade(self, event: SystemEvent):
        """Обработка исполнения ордера"""
        self.trade_executed.emit(event.payload)

    def _on_status(self, event: SystemEvent):
        """Обработка статуса системы"""
        message = event.payload.get("message", "Status updated")
        self.system_status.emit(message)

    def _on_alert(self, event: SystemEvent):
        """Обработка системного алерта"""
        error = event.payload.get("error", "Unknown error")
        error_count = event.payload.get("error_count", 0)
        message = f"⚠️ {error} (count: {error_count})"
        self.system_alert.emit(message)

    def _on_feed_status(self, event: SystemEvent):
        """Обработка статуса feed"""
        self.feed_status.emit(event.payload)

    def _on_model_updated(self, event: SystemEvent):
        """Обработка обновления модели"""
        self.model_updated.emit(event.payload)
