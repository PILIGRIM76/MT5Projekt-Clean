# tests/unit/test_event_bus.py
"""
Unit тесты для Event Bus.

Проверяет:
- Подписку и публикацию событий
- Фильтрацию по типам
- Историю событий
- Обработку ошибок
"""

import pytest
from datetime import datetime, timedelta
from src.core.events import Event, EventType, TradeEvent, SystemEvent
from src.core.event_bus import EventBus, event_bus, on_event, on_event_async


class TestEventBus:
    """Тесты для Event Bus."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Настройка перед каждым тестом."""
        self.bus = EventBus()
        self.bus.clear_history()
        # Отписываем всех подписчиков
        for event_type in EventType:
            self.bus.unsubscribe_all(event_type)
    
    def test_subscribe_and_publish(self):
        """Подписка и публикация."""
        received_events = []
        
        def handler(event):
            received_events.append(event)
        
        self.bus.subscribe(EventType.TRADE_OPENED, handler)
        
        # Публикация
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            lot=0.1,
            ticket=12345
        )
        self.bus.publish(event)
        
        assert len(received_events) == 1
        assert received_events[0].symbol == "EURUSD"
        assert received_events[0].ticket == 12345
    
    def test_publish_event_helper(self):
        """Публикация через publish_event."""
        received_events = []
        
        def handler(event):
            received_events.append(event)
        
        self.bus.subscribe(EventType.SYSTEM_STARTED, handler)
        
        self.bus.publish_event(
            event_type=EventType.SYSTEM_STARTED,
            data={"version": "13.0"},
            source="TestSystem"
        )
        
        assert len(received_events) == 1
        assert received_events[0].data["version"] == "13.0"
        assert received_events[0].source == "TestSystem"
    
    def test_unsubscribe(self):
        """Отписка от событий."""
        received_events = []
        
        def handler(event):
            received_events.append(event)
        
        self.bus.subscribe(EventType.TRADE_CLOSED, handler)
        self.bus.unsubscribe(EventType.TRADE_CLOSED, handler)
        
        # После отписки события не должны приходить
        self.bus.publish_event(EventType.TRADE_CLOSED, {})
        
        assert len(received_events) == 0
    
    def test_multiple_subscribers(self):
        """Несколько подписчиков."""
        received_1 = []
        received_2 = []
        
        def handler_1(event):
            received_1.append(event)
        
        def handler_2(event):
            received_2.append(event)
        
        self.bus.subscribe(EventType.MARKET_REGIME_CHANGED, handler_1)
        self.bus.subscribe(EventType.MARKET_REGIME_CHANGED, handler_2)
        
        self.bus.publish_event(
            EventType.MARKET_REGIME_CHANGED,
            {"new_regime": "Strong Trend"}
        )
        
        assert len(received_1) == 1
        assert len(received_2) == 1
    
    def test_event_history(self):
        """История событий."""
        # Публикация нескольких событий
        for i in range(10):
            self.bus.publish_event(
                EventType.TRADE_OPENED,
                {"ticket": i}
            )
        
        history = self.bus.get_history(limit=5)
        assert len(history) == 5
        
        # Последние 5 событий
        assert history[-1].data["ticket"] == 9
    
    def test_event_history_filter_by_type(self):
        """Фильтрация истории по типу."""
        self.bus.publish_event(EventType.TRADE_OPENED, {"ticket": 1})
        self.bus.publish_event(EventType.TRADE_CLOSED, {"ticket": 1})
        self.bus.publish_event(EventType.TRADE_OPENED, {"ticket": 2})
        
        history = self.bus.get_history(event_type=EventType.TRADE_OPENED)
        
        assert len(history) == 2
        assert all(e.type == EventType.TRADE_OPENED for e in history)
    
    def test_event_history_filter_by_time(self):
        """Фильтрация истории по времени."""
        now = datetime.utcnow()
        
        self.bus.publish_event(EventType.SYSTEM_STARTED, {})
        
        # Фильтр по времени после
        history = self.bus.get_history(start_time=now - timedelta(minutes=1))
        assert len(history) == 1
        
        # Фильтр по времени до (в прошлом)
        history = self.bus.get_history(start_time=now + timedelta(hours=1))
        assert len(history) == 0
    
    def test_get_statistics(self):
        """Получение статистики."""
        def handler1(event): pass
        def handler2(event): pass
        
        self.bus.subscribe(EventType.TRADE_OPENED, handler1)
        self.bus.subscribe(EventType.TRADE_OPENED, handler2)
        self.bus.subscribe(EventType.TRADE_CLOSED, handler1)
        
        stats = self.bus.get_statistics()
        
        assert stats["total_sync_subscribers"] == 3
        assert "history_size" in stats
        assert "max_history_size" in stats
    
    def test_get_subscriber_count(self):
        """Подсчет подписчиков."""
        def handler(event): pass
        
        self.bus.subscribe(EventType.TRADE_OPENED, handler)
        self.bus.subscribe(EventType.TRADE_OPENED, handler)  # Еще один
        
        count = self.bus.get_subscriber_count(EventType.TRADE_OPENED)
        assert count == 2
        
        count = self.bus.get_subscriber_count(EventType.TRADE_CLOSED)
        assert count == 0
    
    def test_error_in_handler(self):
        """Ошибка в обработчике не ломает шину."""
        def bad_handler(event):
            raise ValueError("Test error")
        
        good_received = []
        
        def good_handler(event):
            good_received.append(event)
        
        self.bus.subscribe(EventType.TRADE_OPENED, bad_handler)
        self.bus.subscribe(EventType.TRADE_OPENED, good_handler)
        
        # Несмотря на ошибку в bad_handler, good_handler должен сработать
        self.bus.publish_event(EventType.TRADE_OPENED, {})
        
        assert len(good_received) == 1
    
    def test_clear_history(self):
        """Очистка истории."""
        for _ in range(5):
            self.bus.publish_event(EventType.TRADE_OPENED, {})
        
        self.bus.clear_history()
        
        history = self.bus.get_history()
        assert len(history) == 0


class TestEventDecorators:
    """Тесты для декораторов событий."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Настройка."""
        self.bus = EventBus()
        for event_type in EventType:
            self.bus.unsubscribe_all(event_type)
    
    def test_on_event_decorator(self):
        """Декоратор on_event."""
        received = []
        
        @on_event(EventType.TRADE_OPENED)
        def handler(event):
            received.append(event)
        
        self.bus.publish_event(EventType.TRADE_OPENED, {"ticket": 1})
        
        assert len(received) == 1
        assert received[0].data["ticket"] == 1


class TestTradeEvent:
    """Тесты для TradeEvent."""
    
    def test_create_trade_event(self):
        """Создание TradeEvent."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            lot=0.1,
            order_type="BUY",
            price=1.1000,
            ticket=12345
        )
        
        assert event.type == EventType.TRADE_OPENED
        assert event.symbol == "EURUSD"
        assert event.lot == 0.1
        assert event.ticket == 12345
    
    def test_create_trade_closed_event(self):
        """Создание события закрытия."""
        event = TradeEvent(
            type=EventType.TRADE_CLOSED,
            ticket=12345,
            symbol="EURUSD",
            pnl=50.0,
            reason="TP"
        )
        
        assert event.type == EventType.TRADE_CLOSED
        assert event.pnl == 50.0
        assert event.reason == "TP"


class TestSystemEvent:
    """Тесты для SystemEvent."""
    
    def test_create_system_event(self):
        """Создание системного события."""
        event = SystemEvent(
            type=EventType.SYSTEM_ERROR,
            component="TradingSystem",
            status="error",
            message="Test error message"
        )
        
        assert event.type == EventType.SYSTEM_ERROR
        assert event.component == "TradingSystem"
        assert event.message == "Test error message"
