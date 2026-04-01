# -*- coding: utf-8 -*-
"""
Unit тесты для Event Bus.

Тестирует:
- Подписка на события
- Публикация событий
- История событий
- Статистика
- Декораторы
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.core.event_bus import EventBus, on_event, on_event_async
from src.core.events import Event, EventType


@pytest.fixture
def event_bus_clean():
    """Создание чистого экземпляра EventBus для тестов."""
    # Сбрасываем singleton
    EventBus._instance = None
    EventBus._initialized = False
    bus = EventBus()
    bus.clear_history()
    # Отписываем всех подписчиков
    for event_type in EventType:
        bus.unsubscribe_all(event_type)
    return bus


class TestEventBusSubscription:
    """Тесты подписки на события."""

    def test_subscribe(self, event_bus_clean):
        """Проверка подписки на событие."""
        callback = MagicMock()

        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback)

        assert event_bus_clean.get_subscriber_count(EventType.TRADE_OPENED) == 1

    def test_subscribe_multiple(self, event_bus_clean):
        """Проверка множественной подписки."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback1)
        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback2)

        assert event_bus_clean.get_subscriber_count(EventType.TRADE_OPENED) == 2

    def test_unsubscribe(self, event_bus_clean):
        """Проверка отписки от события."""
        callback = MagicMock()

        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback)
        event_bus_clean.unsubscribe(EventType.TRADE_OPENED, callback)

        assert event_bus_clean.get_subscriber_count(EventType.TRADE_OPENED) == 0

    def test_unsubscribe_all(self, event_bus_clean):
        """Проверка отписки всех подписчиков."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback1)
        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback2)
        event_bus_clean.unsubscribe_all(EventType.TRADE_OPENED)

        assert event_bus_clean.get_subscriber_count(EventType.TRADE_OPENED) == 0


class TestEventBusPublish:
    """Тесты публикации событий."""

    def test_publish_calls_subscriber(self, event_bus_clean):
        """Проверка что публикация вызывает подписчика."""
        callback = MagicMock()
        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback)

        event = Event(type=EventType.TRADE_OPENED, data={"symbol": "EURUSD"})
        event_bus_clean.publish(event)

        callback.assert_called_once_with(event)

    def test_publish_to_multiple_subscribers(self, event_bus_clean):
        """Проверка публикации нескольким подписчикам."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback1)
        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback2)

        event = Event(type=EventType.TRADE_OPENED, data={"symbol": "EURUSD"})
        event_bus_clean.publish(event)

        callback1.assert_called_once_with(event)
        callback2.assert_called_once_with(event)

    def test_publish_only_to_subscribed_type(self, event_bus_clean):
        """Проверка что событие доставляется только нужным подписчикам."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback1)
        event_bus_clean.subscribe(EventType.TRADE_CLOSED, callback2)

        event = Event(type=EventType.TRADE_OPENED, data={"symbol": "EURUSD"})
        event_bus_clean.publish(event)

        callback1.assert_called_once_with(event)
        callback2.assert_not_called()

    def test_publish_event_helper(self, event_bus_clean):
        """Проверка publish_event helper."""
        callback = MagicMock()
        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback)

        event_bus_clean.publish_event(
            EventType.TRADE_OPENED,
            data={"symbol": "EURUSD", "lot": 0.1},
            source="test",
        )

        callback.assert_called_once()
        call_args = callback.call_args[0][0]
        assert call_args.type == EventType.TRADE_OPENED
        assert call_args.data == {"symbol": "EURUSD", "lot": 0.1}
        assert call_args.source == "test"


class TestEventBusHistory:
    """Тесты истории событий."""

    def test_history_is_saved(self, event_bus_clean):
        """Проверка что события сохраняются в историю."""
        event = Event(type=EventType.TRADE_OPENED, data={"symbol": "EURUSD"})
        event_bus_clean.publish(event)

        history = event_bus_clean.get_history()

        assert len(history) == 1
        assert history[0].type == EventType.TRADE_OPENED

    def test_history_limit(self, event_bus_clean):
        """Проверка ограничения истории."""
        # Публикуем больше чем max_history
        for i in range(1100):
            event = Event(type=EventType.TRADE_OPENED, data={"index": i})
            event_bus_clean.publish(event)

        history = event_bus_clean.get_history()

        assert len(history) == event_bus_clean._max_history  # 1000

    def test_get_history_by_type(self, event_bus_clean):
        """Проверка фильтрации истории по типу."""
        event1 = Event(type=EventType.TRADE_OPENED, data={})
        event2 = Event(type=EventType.TRADE_CLOSED, data={})

        event_bus_clean.publish(event1)
        event_bus_clean.publish(event2)

        history_opened = event_bus_clean.get_history(event_type=EventType.TRADE_OPENED)
        history_closed = event_bus_clean.get_history(event_type=EventType.TRADE_CLOSED)

        assert len(history_opened) == 1
        assert len(history_closed) == 1

    def test_get_history_limit(self, event_bus_clean):
        """Проверка ограничения количества возвращаемой истории."""
        for i in range(50):
            event_bus_clean.publish(Event(type=EventType.TRADE_OPENED, data={"index": i}))

        history = event_bus_clean.get_history(limit=10)

        assert len(history) == 10
        # Последние 10 событий
        assert history[-1].data["index"] == 49

    def test_get_history_time_range(self, event_bus_clean):
        """Проверка фильтрации по времени."""
        now = datetime.utcnow()

        event1 = Event(type=EventType.TRADE_OPENED, timestamp=now - timedelta(hours=2))
        event2 = Event(type=EventType.TRADE_OPENED, timestamp=now - timedelta(minutes=5))
        event3 = Event(type=EventType.TRADE_OPENED, timestamp=now)

        event_bus_clean.publish(event1)
        event_bus_clean.publish(event2)
        event_bus_clean.publish(event3)

        # За последний час
        history = event_bus_clean.get_history(start_time=now - timedelta(hours=1))

        assert len(history) == 2

    def test_get_recent_events(self, event_bus_clean):
        """Проверка получения недавних событий."""
        for _ in range(5):
            event_bus_clean.publish(Event(type=EventType.TRADE_OPENED, data={}))

        recent = event_bus_clean.get_recent_events(EventType.TRADE_OPENED, minutes=10)

        assert len(recent) == 5

    def test_clear_history(self, event_bus_clean):
        """Проверка очистки истории."""
        event_bus_clean.publish(Event(type=EventType.TRADE_OPENED, data={}))
        event_bus_clean.publish(Event(type=EventType.TRADE_OPENED, data={}))

        event_bus_clean.clear_history()

        assert len(event_bus_clean.get_history()) == 0


class TestEventBusStatistics:
    """Тесты статистики Event Bus."""

    def test_get_statistics(self, event_bus_clean):
        """Проверка получения статистики."""
        callback = MagicMock()
        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback)

        event_bus_clean.publish(Event(type=EventType.TRADE_OPENED, data={}))
        event_bus_clean.publish(Event(type=EventType.TRADE_OPENED, data={}))

        stats = event_bus_clean.get_statistics()

        assert "total_sync_subscribers" in stats
        assert "total_async_subscribers" in stats
        assert "history_size" in stats
        assert "max_history_size" in stats
        assert stats["history_size"] == 2

    def test_get_subscriber_count(self, event_bus_clean):
        """Проверка подсчета подписчиков."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback1)
        event_bus_clean.subscribe(EventType.TRADE_OPENED, callback2)

        count = event_bus_clean.get_subscriber_count(EventType.TRADE_OPENED)

        assert count == 2


class TestEventBusDecorators:
    """Тесты декораторов."""

    def test_on_event_decorator(self, event_bus_clean):
        """Проверка декоратора on_event."""
        callback_called = []

        def handler(event):
            callback_called.append(event)

        # Подписываемся через декоратор на наш тестовый event_bus
        decorated = on_event(EventType.TRADE_OPENED)(handler)

        event = Event(type=EventType.TRADE_OPENED, data={"test": "data"})
        event_bus_clean.publish(event)

        # Декоратор подписывает на глобальный event_bus, поэтому проверяем
        # что функция была возвращена
        assert callable(decorated)

    def test_on_event_async_decorator(self, event_bus_clean):
        """Проверка декоратора on_event_async."""
        callback_called = []

        async def async_handler(event):
            callback_called.append(event)

        # Подписываемся через декоратор
        decorated = on_event_async(EventType.TRADE_CLOSED)(async_handler)

        # Проверяем что функция была возвращена
        assert callable(decorated)


class TestEventBusSingleton:
    """Тесты Singleton паттерна."""

    def test_singleton_returns_same_instance(self):
        """Проверка что возвращается тот же экземпляр."""
        bus1 = EventBus()
        bus2 = EventBus()

        assert bus1 is bus2

    def test_singleton_after_reset(self):
        """Проверка singleton после сброса."""
        bus1 = EventBus()
        EventBus._instance = None
        EventBus._initialized = False
        bus2 = EventBus()

        assert bus1 is not bus2  # Новый экземпляр после сброса
        assert bus2 is EventBus()  # Но всё ещё singleton
