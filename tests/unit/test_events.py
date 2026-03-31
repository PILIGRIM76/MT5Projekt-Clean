"""
Unit тесты для модуля events.py.

Тестирует:
- Создание событий различных типов
- EventFactory
- EventType enum
"""

import pytest
from datetime import datetime
from src.core.events import (
    EventType,
    Event,
    TradeEvent,
    RiskEvent,
    MarketRegimeEvent,
    ModelEvent,
    SystemEvent,
    OrchestratorEvent,
    EventFactory
)


class TestEventType:
    """Тесты для Enum EventType."""

    def test_trade_events_exist(self):
        """Проверка существования торговых событий."""
        assert EventType.TRADE_OPENED.value == "trade_opened"
        assert EventType.TRADE_CLOSED.value == "trade_closed"
        assert EventType.TRADE_REJECTED.value == "trade_rejected"
        assert EventType.TRADE_MODIFIED.value == "trade_modified"
        assert EventType.PARTIAL_CLOSED.value == "partial_closed"

    def test_risk_events_exist(self):
        """Проверка существования событий риска."""
        assert EventType.RISK_CHECK_PASSED.value == "risk_check_passed"
        assert EventType.RISK_CHECK_FAILED.value == "risk_check_failed"
        assert EventType.DRAWDOWN_LIMIT_APPROACHED.value == "drawdown_limit_approached"
        assert EventType.DRAWDOWN_LIMIT_EXCEEDED.value == "drawdown_limit_exceeded"

    def test_ml_events_exist(self):
        """Проверка существования ML событий."""
        assert EventType.MODEL_LOADED.value == "model_loaded"
        assert EventType.MODEL_RETRAINED.value == "model_retrained"
        assert EventType.CONCEPT_DRIFT_DETECTED.value == "concept_drift_detected"

    def test_event_type_is_string_enum(self):
        """Проверка что EventType это строковый enum."""
        assert isinstance(EventType.TRADE_OPENED, str)
        assert EventType.TRADE_OPENED == "trade_opened"

    def test_event_type_comparison(self):
        """Проверка сравнения типов событий."""
        event_type = EventType.TRADE_OPENED
        assert event_type == EventType.TRADE_OPENED
        assert event_type != EventType.TRADE_CLOSED
        assert event_type in EventType


class TestEvent:
    """Тесты для базового класса Event."""

    def test_create_basic_event(self):
        """Создание базового события."""
        event = Event(
            type=EventType.SYSTEM_STARTED,
            data={"key": "value"},
            source="TestComponent"
        )
        
        assert event.type == EventType.SYSTEM_STARTED
        assert event.data == {"key": "value"}
        assert event.source == "TestComponent"
        assert isinstance(event.timestamp, datetime)

    def test_event_default_timestamp(self):
        """Проверка что timestamp устанавливается автоматически."""
        before = datetime.utcnow()
        event = Event(type=EventType.SYSTEM_STARTED)
        after = datetime.utcnow()
        
        assert before <= event.timestamp <= after

    def test_event_default_data(self):
        """Проверка что data по умолчанию пустой dict."""
        event = Event(type=EventType.SYSTEM_STARTED)
        assert event.data == {}

    def test_event_default_source(self):
        """Проверка что source по умолчанию None."""
        event = Event(type=EventType.SYSTEM_STARTED)
        assert event.source is None

    def test_event_with_all_fields(self):
        """Создание события со всеми полями."""
        timestamp = datetime(2026, 3, 31, 12, 0, 0)
        event = Event(
            type=EventType.TRADE_OPENED,
            timestamp=timestamp,
            data={"symbol": "EURUSD"},
            source="TradingSystem"
        )
        
        assert event.type == EventType.TRADE_OPENED
        assert event.timestamp == timestamp
        assert event.data == {"symbol": "EURUSD"}
        assert event.source == "TradingSystem"


class TestTradeEvent:
    """Тесты для TradeEvent."""

    def test_create_trade_event(self):
        """Создание события торговли."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            lot=0.1,
            order_type="BUY",
            price=1.1000,
            strategy_name="TestStrategy"
        )
        
        assert event.symbol == "EURUSD"
        assert event.lot == 0.1
        assert event.order_type == "BUY"
        assert event.price == 1.1000
        assert event.strategy_name == "TestStrategy"

    def test_trade_event_defaults(self):
        """Проверка значений по умолчанию."""
        event = TradeEvent(type=EventType.TRADE_OPENED)
        
        assert event.symbol == ""
        assert event.lot == 0.0
        assert event.order_type == ""
        assert event.price == 0.0
        assert event.stop_loss is None
        assert event.take_profit is None
        assert event.pnl is None
        assert event.ticket is None

    def test_trade_event_with_sl_tp(self):
        """Создание события с Stop Loss и Take Profit."""
        event = TradeEvent(
            type=EventType.TRADE_OPENED,
            symbol="EURUSD",
            stop_loss=1.0950,
            take_profit=1.1100
        )
        
        assert event.stop_loss == 1.0950
        assert event.take_profit == 1.1100

    def test_trade_event_with_pnl(self):
        """Создание события с PnL."""
        event = TradeEvent(
            type=EventType.TRADE_CLOSED,
            symbol="EURUSD",
            pnl=50.0,
            reason="TP"
        )
        
        assert event.pnl == 50.0
        assert event.reason == "TP"


class TestRiskEvent:
    """Тесты для RiskEvent."""

    def test_create_risk_event(self):
        """Создание события риска."""
        event = RiskEvent(
            type=EventType.RISK_CHECK_FAILED,
            risk_type="drawdown",
            current_value=0.15,
            threshold=0.10,
            action_taken="reject_trade"
        )
        
        assert event.risk_type == "drawdown"
        assert event.current_value == 0.15
        assert event.threshold == 0.10
        assert event.action_taken == "reject_trade"

    def test_risk_event_with_affected_symbols(self):
        """Создание события с затронутыми символами."""
        event = RiskEvent(
            type=EventType.CORRELATION_WARNING,
            affected_symbols=["EURUSD", "GBPUSD", "USDCHF"]
        )
        
        assert event.affected_symbols == ["EURUSD", "GBPUSD", "USDCHF"]


class TestMarketRegimeEvent:
    """Тесты для MarketRegimeEvent."""

    def test_create_regime_event(self):
        """Создание события смены режима рынка."""
        event = MarketRegimeEvent(
            type=EventType.MARKET_REGIME_CHANGED,
            old_regime="ranging",
            new_regime="trending_up",
            confidence=0.85,
            adx_value=35.0
        )
        
        assert event.old_regime == "ranging"
        assert event.new_regime == "trending_up"
        assert event.confidence == 0.85
        assert event.adx_value == 35.0


class TestModelEvent:
    """Тесты для ModelEvent."""

    def test_create_model_event(self):
        """Создание ML события."""
        event = ModelEvent(
            type=EventType.MODEL_RETRAINED,
            model_type="LSTM",
            symbol="EURUSD",
            timeframe=60,
            accuracy=0.75,
            loss=0.025,
            training_samples=10000
        )
        
        assert event.model_type == "LSTM"
        assert event.symbol == "EURUSD"
        assert event.timeframe == 60
        assert event.accuracy == 0.75
        assert event.loss == 0.025
        assert event.training_samples == 10000


class TestSystemEvent:
    """Тесты для SystemEvent."""

    def test_create_system_event(self):
        """Создание системного события."""
        event = SystemEvent(
            type=EventType.SYSTEM_ERROR,
            component="DatabaseManager",
            status="error",
            message="Connection failed",
            error_details="Timeout after 30s"
        )
        
        assert event.component == "DatabaseManager"
        assert event.status == "error"
        assert event.message == "Connection failed"
        assert event.error_details == "Timeout after 30s"


class TestOrchestratorEvent:
    """Тесты для OrchestratorEvent."""

    def test_create_orchestrator_event(self):
        """Создание события оркестратора."""
        event = OrchestratorEvent(
            type=EventType.CAPITAL_REALLOCATED,
            cycle_id="cycle_123",
            regime="trending",
            allocation_changes={"StrategyA": 0.1, "StrategyB": -0.05},
            performance_metrics={"sharpe": 1.5, "drawdown": 0.08}
        )
        
        assert event.cycle_id == "cycle_123"
        assert event.regime == "trending"
        assert event.allocation_changes == {"StrategyA": 0.1, "StrategyB": -0.05}
        assert event.performance_metrics == {"sharpe": 1.5, "drawdown": 0.08}


class TestEventFactory:
    """Тесты для EventFactory."""

    def test_create_trade_opened(self):
        """Создание события открытия сделки."""
        factory = EventFactory()
        event = factory.create_trade_opened(
            symbol="EURUSD",
            lot=0.1,
            order_type="BUY",
            price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            strategy_name="TrendStrategy",
            ticket=12345
        )
        
        assert isinstance(event, TradeEvent)
        assert event.type == EventType.TRADE_OPENED
        assert event.symbol == "EURUSD"
        assert event.lot == 0.1
        assert event.order_type == "BUY"
        assert event.price == 1.1000
        assert event.stop_loss == 1.0950
        assert event.take_profit == 1.1100
        assert event.strategy_name == "TrendStrategy"
        assert event.ticket == 12345
        assert event.source == "TradeExecutor"

    def test_create_trade_closed(self):
        """Создание события закрытия сделки."""
        factory = EventFactory()
        event = factory.create_trade_closed(
            ticket=12345,
            symbol="EURUSD",
            pnl=50.0,
            close_reason="TP"
        )
        
        assert isinstance(event, TradeEvent)
        assert event.type == EventType.TRADE_CLOSED
        assert event.ticket == 12345
        assert event.symbol == "EURUSD"
        assert event.pnl == 50.0
        assert event.reason == "TP"
        assert event.source == "TradeExecutor"

    def test_create_trade_rejected(self):
        """Создание события отклонения сделки."""
        factory = EventFactory()
        event = factory.create_trade_rejected(
            symbol="EURUSD",
            strategy_name="BreakoutStrategy",
            rejection_reason="Insufficient margin"
        )
        
        assert isinstance(event, TradeEvent)
        assert event.type == EventType.TRADE_REJECTED
        assert event.symbol == "EURUSD"
        assert event.strategy_name == "BreakoutStrategy"
        assert event.reason == "Insufficient margin"
        assert event.source == "RiskEngine"

    def test_create_system_error(self):
        """Создание события системной ошибки."""
        factory = EventFactory()
        event = factory.create_system_error(
            component="DataProvider",
            message="API rate limit exceeded",
            error_details="429 Too Many Requests"
        )
        
        assert isinstance(event, SystemEvent)
        assert event.type == EventType.SYSTEM_ERROR
        assert event.component == "DataProvider"
        assert event.message == "API rate limit exceeded"
        assert event.error_details == "429 Too Many Requests"
        assert event.source == "System"

    def test_factory_creates_independent_events(self):
        """Проверка что фабрика создаёт независимые события."""
        factory = EventFactory()
        
        event1 = factory.create_trade_opened(
            symbol="EURUSD", lot=0.1, order_type="BUY",
            price=1.1000, stop_loss=None, take_profit=None,
            strategy_name="Test", ticket=1
        )
        
        event2 = factory.create_trade_opened(
            symbol="GBPUSD", lot=0.2, order_type="SELL",
            price=1.2500, stop_loss=None, take_profit=None,
            strategy_name="Test", ticket=2
        )
        
        assert event1.symbol != event2.symbol
        assert event1.lot != event2.lot
        assert event1.ticket != event2.ticket
        assert event1.data is not event2.data


class TestEventInheritance:
    """Тесты для проверки наследования событий."""

    def test_trade_event_is_event(self):
        """TradeEvent является подклассом Event."""
        event = TradeEvent(type=EventType.TRADE_OPENED)
        assert isinstance(event, Event)
        assert hasattr(event, 'type')
        assert hasattr(event, 'timestamp')
        assert hasattr(event, 'data')
        assert hasattr(event, 'source')

    def test_risk_event_is_event(self):
        """RiskEvent является подклассом Event."""
        event = RiskEvent(type=EventType.RISK_CHECK_FAILED)
        assert isinstance(event, Event)

    def test_model_event_is_event(self):
        """ModelEvent является подклассом Event."""
        event = ModelEvent(type=EventType.MODEL_LOADED)
        assert isinstance(event, Event)

    def test_system_event_is_event(self):
        """SystemEvent является подклассом Event."""
        event = SystemEvent(type=EventType.SYSTEM_ERROR)
        assert isinstance(event, Event)
