# src/gui/event_bridge.py
"""
Исправленный мост: безопасная доставка событий между Qt и EventBus.
"""

import asyncio
import logging
import time

from PySide6.QtCore import QObject, Signal, Slot

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.thread_domains import ThreadDomain

logger = logging.getLogger(__name__)


class GUIEventBridge(QObject):
    """Исправленный мост: безопасная доставка событий между Qt и EventBus"""

    # Сигналы в GUI-поток
    prediction_received = Signal(dict)
    signal_generated = Signal(dict)
    order_executed = Signal(dict)
    accuracy_updated = Signal(dict)
    model_accuracy_updated = Signal(dict)  # Для графиков точности
    retrain_progress_updated = Signal(dict)  # Для прогресса переобучения
    pnl_kpis_updated = Signal(dict)  # Для PnL KPI
    system_alert = Signal(str)
    trading_started = Signal(bool)
    trading_stopped = Signal(bool)
    system_restart_requested = Signal()  # НОВОЕ: запрос перезапуска
    system_restart_completed = Signal(bool)  # НОВОЕ: подтверждение
    news_batch_received = Signal(dict)  # НОВОЕ: новости из EventBus

    # Сигналы для ControlCenterWidget
    log_message_added = Signal(str)  # Для лога
    status_updated = Signal(str, bool)  # message, is_error
    heavy_initialization_finished = Signal()  # Для завершения инициализации

    # Сигналы для VectorDB
    vector_db_search_results = Signal(list)

    # Сигналы для Market Scanner
    market_scan_updated = Signal(dict)  # Для сканера рынка

    def __init__(self, parent=None):
        super().__init__(parent)
        self._event_bus = None
        self._subscribed = False

    @property
    def event_bus(self):
        return self._event_bus

    def set_event_bus(self, bus):
        """Явная привязка к EventBus (вызывать до show())"""
        self._event_bus = bus
        logger.info("🔗 GUIEventBridge привязан к EventBus")

    async def start_listening(self):
        """Безопасная подписка на события бэкенда"""
        if not self._event_bus or self._subscribed:
            return
        try:
            await self._event_bus.subscribe("model_prediction", self._on_prediction, domain=ThreadDomain.GUI)
            await self._event_bus.subscribe("trade_signal", self._on_signal, domain=ThreadDomain.GUI)
            await self._event_bus.subscribe("order_executed", self._on_order, domain=ThreadDomain.GUI)
            await self._event_bus.subscribe("system_health", self._on_health, domain=ThreadDomain.GUI)
            await self._event_bus.subscribe("trading_started", self._on_trading_started, domain=ThreadDomain.GUI)
            await self._event_bus.subscribe("trading_stopped", self._on_trading_stopped, domain=ThreadDomain.GUI)
            await self._event_bus.subscribe("system_restart_completed", self._on_restart_completed, domain=ThreadDomain.GUI)

            # 🔧 Подписка на события обучения для GUI
            await self._event_bus.subscribe("model_updated", self._on_model_updated, domain=ThreadDomain.GUI)
            await self._event_bus.subscribe("retrain_progress", self._on_retrain_progress, domain=ThreadDomain.GUI)

            # 📰 Подписка на новости
            await self._event_bus.subscribe("news_batch_processed", self._on_news_batch, domain=ThreadDomain.GUI)

            self._subscribed = True
            logger.info("✅ GUIEventBridge активен")
        except Exception as e:
            logger.error(f"❌ Ошибка подписки GUIEventBridge: {e}", exc_info=True)

    async def publish_from_gui(self, event_type: str, payload: dict, priority=EventPriority.MEDIUM):
        """Отправка событий ИЗ GUI в бэкенд (для кнопок)"""
        if not self._event_bus:
            logger.warning("⚠️ EventBus не привязан, событие отклонено")
            return False
        try:
            await self._event_bus.publish(
                SystemEvent(
                    type=event_type,
                    payload=payload,
                    priority=priority,
                    source_domain=ThreadDomain.GUI,
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Не удалось опубликовать событие из GUI: {e}")
            return False

    async def request_system_restart(self):
        """Публикация запроса на перезапуск системы"""
        return await self.publish_from_gui(
            event_type="system_restart_requested",
            payload={"timestamp": time.time(), "user_initiated": True},
            priority=EventPriority.CRITICAL,
        )

    # === Внутренние обработчики (вызываются в потоке EventBus) ===

    def _safe_emit(self, signal, data):
        try:
            signal.emit(data)
        except RuntimeError as e:
            if "already deleted" in str(e) or "Internal C++ object" in str(e):
                logger.debug(f"⚠️ Виджет удалён, сигнал пропущен")
            else:
                raise

    @Slot(dict)
    def _on_prediction(self, event: SystemEvent):
        self._safe_emit(
            self.prediction_received,
            {
                "symbol": event.payload.get("symbol"),
                "prediction": event.payload.get("prediction"),
                "confidence": event.payload.get("confidence"),
            },
        )

    @Slot(dict)
    def _on_signal(self, event: SystemEvent):
        self._safe_emit(
            self.signal_generated,
            {
                "symbol": event.payload.get("symbol"),
                "action": event.payload.get("action"),
                "volume": event.payload.get("volume"),
            },
        )

    @Slot(dict)
    def _on_order(self, event: SystemEvent):
        self._safe_emit(
            self.order_executed,
            {
                "symbol": event.payload.get("signal", {}).get("symbol"),
                "success": event.payload.get("execution", {}).get("success", False),
                "message": event.payload.get("execution", {}).get("message", ""),
            },
        )

    @Slot(dict)
    def _on_health(self, event: SystemEvent):
        self._safe_emit(self.system_alert, event.payload.get("message", "System alert"))

    @Slot(dict)
    def _on_trading_started(self, event: SystemEvent):
        logger.info(f"📥 GUIEventBridge получил trading_started: {event.payload}")
        self._safe_emit(self.trading_started, True)

    @Slot(dict)
    def _on_trading_stopped(self, event: SystemEvent):
        self._safe_emit(self.trading_stopped, True)

    @Slot(dict)
    def _on_restart_completed(self, event: SystemEvent):
        """Обработка подтверждения перезапуска от ядра"""
        success = event.payload.get("success", False)
        error = event.payload.get("error", "")

        if success:
            logger.info("✅ GUI получил подтверждение успешного перезапуска")
        else:
            logger.error(f"❌ Перезапуск не удался: {error}")

        # Эмитим сигнал для обновления UI
        self._safe_emit(self.system_restart_completed, success)

    @Slot(dict)
    def _on_model_updated(self, event: SystemEvent):
        """Обработка события обновления модели - для графиков"""
        payload = event.payload
        logger.debug(f"📈 Model updated: {payload.get('symbol')} acc={payload.get('accuracy')}")
        self._safe_emit(
            self.model_accuracy_updated,
            {
                "symbol": payload.get("symbol"),
                "accuracy": payload.get("accuracy", 0),
                "version": payload.get("version", 0),
                "timestamp": time.time(),
            },
        )

    @Slot(dict)
    def _on_retrain_progress(self, event: SystemEvent):
        """Обработка прогресса переобучения - для индикатора прогресса"""
        payload = event.payload
        logger.debug(f"🔄 Retrain progress: {payload.get('symbol')} {payload.get('progress', 0):.0%}")
        self._safe_emit(
            self.retrain_progress_updated,
            {
                "symbol": payload.get("symbol"),
                "progress": payload.get("progress", 0),
                "stage": payload.get("stage", "unknown"),
                "message": payload.get("message", ""),
            },
        )

    @Slot(dict)
    def _on_news_batch(self, event: SystemEvent):
        """Обработка батча новостей из EventBus"""
        payload = event.payload
        logger.debug(
            f"📰 News batch received: {payload.get('count', 0)} articles, sentiment={payload.get('avg_sentiment', 0):.2f}"
        )
        self._safe_emit(
            self.news_batch_received,
            {
                "articles": payload.get("articles", []),
                "count": payload.get("count", 0),
                "avg_sentiment": payload.get("avg_sentiment", 0.0),
                "sources": payload.get("sources", []),
                "timestamp": time.time(),
            },
        )
