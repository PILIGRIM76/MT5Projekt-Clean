# src/core/event_bus.py
"""
Event Bus для межкомпонентного общения.

Реализует паттерн Publish-Subscribe для слабой связанности компонентов.

Пример использования:
    from src.core.event_bus import event_bus, EventType
    
    # Подписка
    event_bus.subscribe(EventType.TRADE_OPENED, on_trade_opened)
    
    # Публикация
    event_bus.publish(EventType.TRADE_OPENED, {
        "symbol": "EURUSD",
        "lot": 0.1,
        "price": 1.1000
    })
"""

import asyncio
import logging
from typing import Callable, Dict, List, Optional, Any
from collections import defaultdict
from datetime import datetime, timedelta

from .events import Event, EventType

logger = logging.getLogger(__name__)


# ===========================================
# Event Bus Implementation
# ===========================================

class EventBus:
    """
    Центральная шина событий.
    
    Реализует:
    - Синхронные и асинхронные подписчики
    - Историю событий
    - Фильтрацию по типам
    - Обработку ошибок в подписчиках
    """
    
    _instance: Optional['EventBus'] = None
    
    def __new__(cls) -> 'EventBus':
        """Singleton паттерн."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._async_subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_history: List[Event] = []
        self._max_history = 1000
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        
        logger.info("EventBus инициализирован")
    
    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Установка event loop для асинхронных операций."""
        self._event_loop = loop
        logger.debug("EventBus event loop установлен")
    
    # ===========================================
    # Subscription Methods
    # ===========================================
    
    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], None]
    ) -> None:
        """
        Подписка на событие (синхронная).
        
        Args:
            event_type: Тип события
            callback: Функция обратного вызова
        """
        self._subscribers[event_type].append(callback)
        logger.debug(f"Подписчик добавлен на {event_type.value}")
    
    def subscribe_async(
        self,
        event_type: EventType,
        callback: Callable[[Event], Any]
    ) -> None:
        """Подписка на событие (асинхронная)."""
        self._async_subscribers[event_type].append(callback)
        logger.debug(f"Async подписчик добавлен на {event_type.value}")
    
    def unsubscribe(
        self,
        event_type: EventType,
        callback: Callable
    ) -> None:
        """Отписка от события."""
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
        
        if callback in self._async_subscribers[event_type]:
            self._async_subscribers[event_type].remove(callback)
    
    def unsubscribe_all(self, event_type: EventType) -> None:
        """Отписка всех подписчиков от события."""
        self._subscribers[event_type].clear()
        self._async_subscribers[event_type].clear()
    
    # ===========================================
    # Publish Methods
    # ===========================================
    
    def publish(self, event: Event) -> None:
        """
        Публикация события.
        
        Args:
            event: Событие для публикации
        """
        # Сохранение в историю
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        logger.debug(f"Публикация события: {event.type.value}")
        
        # Синхронные подписчики
        for callback in self._subscribers[event.type]:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Ошибка в подписчике {callback.__name__}: {e}", exc_info=True)
        
        # Асинхронные подписчики
        if self._async_subscribers[event.type]:
            self._publish_async(event)
    
    def _publish_async(self, event: Event) -> None:
        """Асинхронная публикация события."""
        async def call_async_subscribers():
            for callback in self._async_subscribers[event.type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"Ошибка в async подписчике {callback.__name__}: {e}", exc_info=True)
        
        if self._event_loop and not self._event_loop.is_closed():
            self._event_loop.call_soon_threadsafe(
                lambda: asyncio.create_task(call_async_subscribers())
            )
        else:
            try:
                asyncio.create_task(call_async_subscribers())
            except RuntimeError:
                logger.warning("Нет активного event loop для async subscribers")
    
    def publish_event(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        source: Optional[str] = None
    ) -> None:
        """Публикация события с данными."""
        event = Event(type=event_type, data=data, source=source)
        self.publish(event)
    
    # ===========================================
    # History Methods
    # ===========================================
    
    def get_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Event]:
        """Получение истории событий."""
        filtered = self._event_history
        
        if event_type:
            filtered = [e for e in filtered if e.type == event_type]
        
        if start_time:
            filtered = [e for e in filtered if e.timestamp >= start_time]
        
        if end_time:
            filtered = [e for e in filtered if e.timestamp <= end_time]
        
        return filtered[-limit:]
    
    def get_recent_events(
        self,
        event_type: EventType,
        minutes: int = 5
    ) -> List[Event]:
        """Получение недавних событий за период."""
        start_time = datetime.utcnow() - timedelta(minutes=minutes)
        return self.get_history(
            event_type=event_type,
            start_time=start_time,
            limit=1000
        )
    
    def clear_history(self) -> None:
        """Очистка истории событий."""
        self._event_history.clear()
    
    # ===========================================
    # Statistics
    # ===========================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики Event Bus."""
        sync_count = sum(len(subs) for subs in self._subscribers.values())
        async_count = sum(len(subs) for subs in self._async_subscribers.values())
        
        return {
            "total_sync_subscribers": sync_count,
            "total_async_subscribers": async_count,
            "history_size": len(self._event_history),
            "max_history_size": self._max_history,
            "event_types_subscribed": len([
                et for et in EventType
                if self._subscribers[et] or self._async_subscribers[et]
            ])
        }
    
    def get_subscriber_count(self, event_type: EventType) -> int:
        """Получение количества подписчиков на событие."""
        return (
            len(self._subscribers[event_type]) +
            len(self._async_subscribers[event_type])
        )


# ===========================================
# Global Instance
# ===========================================

event_bus = EventBus()
"""Глобальный экземпляр Event Bus"""


# ===========================================
# Decorators
# ===========================================

def on_event(event_type: EventType):
    """
    Декоратор для подписки на событие.
    
    Example:
        @on_event(EventType.TRADE_OPENED)
        def handle_trade_opened(event):
            logger.info(f"Сделка: {event.symbol}")
    """
    def decorator(callback: Callable) -> Callable:
        event_bus.subscribe(event_type, callback)
        return callback
    return decorator


def on_event_async(event_type: EventType):
    """
    Декоратор для асинхронной подписки на событие.
    
    Example:
        @on_event_async(EventType.MODEL_LOADED)
        async def handle_model_loaded(event):
            await process_model(event)
    """
    def decorator(callback: Callable) -> Callable:
        event_bus.subscribe_async(event_type, callback)
        return callback
    return decorator
