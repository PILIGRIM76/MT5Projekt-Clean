# -*- coding: utf-8 -*-
"""
Unit тесты для событий (events.py).

Тестирует:
- EventType Enum
- Event dataclass
- TradeEvent dataclass
"""

from datetime import datetime

import pytest

from src.core.events import Event, EventType, TradeEvent


class TestEventType:
    """Тесты для EventType Enum."""

    def test_event_type_values(self):
        """Проверка значений типов событий."""
        assert EventType.TRADE_OPENED.value == "trade_opened"
        assert EventType.TRADE_CLOSED.value == "trade_closed"
        assert EventType.TRADE_REJECTED.value == "trade_rejected"

    def test_event_type_trade_events(self):
        """Проверка торговых событий."""
        trade_events = [
            EventType.TRADE_OPENED,
            EventType.TRADE_CLOSED,
            EventType.TRADE_REJECTED,
            EventType.TRADE_MODIFIED,
            EventType.PARTIAL_CLOSED,
        ]

        for event in trade_events:
            assert isinstance(event.value, str)

    def test_event_type_risk_events(self):
        """Проверка событий риска."""
        risk_events = [
            EventType.RISK_CHECK_PASSED,
            EventType.RISK_CHECK_FAILED,
            EventType.DRAWDOWN_LIMIT_APPROACHED,
            EventType.DRAWDOWN_LIMIT_EXCEEDED,
        ]

        for event in risk_events:
            assert isinstance(event.value, str)

    def test_event_type_ml_events(self):
        """Проверка ML событий."""
        ml_events = [
            EventType.MODEL_LOADED,
            EventType.MODEL_RETRAINED,
            EventType.MODEL_TRAINING_STARTED,
            EventType.MODEL_TRAINING_COMPLETED,
            EventType.MODEL_TRAINING_FAILED,
        ]

        for event in ml_events:
            assert isinstance(event.value, str)

    def test_event_type_market_events(self):
        """Проверка рыночных событий."""
        market_events = [
            EventType.MARKET_REGIME_CHANGED,
            EventType.NEWS_PUBLISHED,
            EventType.ECONOMIC_EVENT,
            EventType.PRICE_ALERT,
        ]

        for event in market_events:
            assert isinstance(event.value, str)

    def test_event_type_system_events(self):
        """Проверка системных событий."""
        system_events = [
            EventType.SYSTEM_STARTED,
            EventType.SYSTEM_STOPPED,
            EventType.SYSTEM_ERROR,
        ]

        for event in system_events:
            assert isinstance(event.value, str)

    def test_event_type_string_comparison(self):
        """Проверка сравнения строк."""
        assert EventType.TRADE_OPENED == "trade_opened"
        assert EventType.TRADE_OPENED.value == "trade_opened"

    def test_event_type_in_list(self):
        """Проверка наличия в списке."""
        events_list = ["trade_opened", "trade_closed", "model_loaded"]

        assert EventType.TRADE_OPENED.value in events_list
        assert EventType.MODEL_LOADED.value in events_list


class TestEvent:
    """Тесты для базового Event."""

    def test_event_creation_minimal(self):
        """Создание минимального события."""
        event = Event(type=EventType.TRADE_OPENED)

        assert event.type == EventType.TRADE_OPENED
        assert event.data == {}
        assert event.source is None
        assert isinstance(event.timestamp, datetime)

    def test_event_creation_full(self):
        """Создание полного события."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        event = Event(
            type=EventType.TRADE_OPENED,
            timestamp=timestamp,
            data={"symbol": "EURUSD", "lot": 0.1},
            source="test_strategy",
        )

        assert event.type == EventType.TRADE_OPENED
        assert event.timestamp == timestamp
        assert event.data == {"symbol": "EURUSD", "lot": 0.1}
        assert event.source == "test_strategy"

    def test_event_default_timestamp(self):
        """Проверка timestamp по умолчанию."""
        event = Event(type=EventType.TRADE_OPENED)

        # Timestamp должен быть близок к текущему времени
        now = datetime.utcnow()
        time_diff = abs((now - event.timestamp).total_seconds())

        assert time_diff < 1  # Разница меньше 1 секунды

    def test_event_data_modification(self):
        """Проверка модификации данных."""
        event = Event(type=EventType.TRADE_OPENED)

        event.data["symbol"] = "EURUSD"
        event.data["lot"] = 0.1

        assert event.data["symbol"] == "EURUSD"
        assert event.data["lot"] == 0.1

    def test_event_with_complex_data(self):
        """Проверка со сложными данными."""
        complex_data = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "none": None,
            "bool": True,
        }

        event = Event(type=EventType.TRADE_OPENED, data=complex_data)

        assert event.data == complex_data


class TestTradeEvent:
    """Тесты для TradeEvent."""

    def test_trade_event_creation(self):
        """Создание торгового события."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            lot=0.1,
            order_type="buy",
            price=1.1000,
        )

        assert event.symbol == "EURUSD"
        assert event.lot == 0.1
        assert event.order_type == "buy"
        assert event.price == 1.1000

    def test_trade_event_defaults(self):
        """Значения по умолчанию."""
        event = TradeEvent(type=EventType.TRADE_OPENED)

        assert event.symbol == ""
        assert event.lot == 0.0
        assert event.order_type == ""
        assert event.price == 0.0
        assert event.stop_loss is None
        assert event.take_profit is None
        assert event.strategy_name == ""
        assert event.pnl is None
        assert event.ticket is None
        assert event.reason is None

    def test_trade_event_with_sl_tp(self):
        """Событие с stop loss и take profit."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            lot=0.1,
            order_type="buy",
            price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )

        assert event.stop_loss == 1.0950
        assert event.take_profit == 1.1100

    def test_trade_event_with_pnl(self):
        """Событие с PnL."""
        event = TradeEvent(
            type=EventType.TRADE_CLOSED,
            symbol="EURUSD",
            pnl=50.0,
            ticket=12345,
        )

        assert event.pnl == 50.0
        assert event.ticket == 12345

    def test_trade_event_inherits_from_event(self):
        """Проверка наследования от Event."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
        )

        # Должны быть унаследованные атрибуты
        assert hasattr(event, "type")
        assert hasattr(event, "timestamp")
        assert hasattr(event, "data")
        assert hasattr(event, "source")

    def test_trade_event_with_strategy_name(self):
        """Событие с именем стратегии."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            strategy_name="BreakoutStrategy_v1",
        )

        assert event.strategy_name == "BreakoutStrategy_v1"

    def test_trade_event_with_reason(self):
        """Событие с причиной."""
        event = TradeEvent(
            type=EventType.TRADE_REJECTED,
            symbol="EURUSD",
            reason="Insufficient margin",
        )

        assert event.reason == "Insufficient margin"


class TestEventSerialization:
    """Тесты сериализации событий."""

    def test_event_to_dict(self):
        """Преобразование события в dict."""
        event = Event(
            type=EventType.TRADE_OPENED,
            data={"symbol": "EURUSD"},
            source="test",
        )

        event_dict = {
            "type": event.type,
            "timestamp": event.timestamp,
            "data": event.data,
            "source": event.source,
        }

        assert event_dict["type"] == EventType.TRADE_OPENED
        assert event_dict["data"] == {"symbol": "EURUSD"}
        assert event_dict["source"] == "test"

    def test_trade_event_to_dict(self):
        """Преобразование TradeEvent в dict."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            lot=0.1,
        )

        event_dict = {
            "type": event.type,
            "symbol": event.symbol,
            "lot": event.lot,
            "order_type": event.order_type,
            "price": event.price,
        }

        assert event_dict["symbol"] == "EURUSD"
        assert event_dict["lot"] == 0.1

    def test_event_repr(self):
        """Проверка string представления."""
        event = Event(type=EventType.TRADE_OPENED, data={"test": "data"})

        repr_str = repr(event)

        assert "Event" in repr_str
        assert "TRADE_OPENED" in repr_str
