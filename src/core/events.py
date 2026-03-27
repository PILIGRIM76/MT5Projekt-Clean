# src/core/events.py
"""
События для Event Bus.

Определяет типы событий и структуры данных для межкомпонентного общения.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List


# ===========================================
# Event Types
# ===========================================

class EventType(str, Enum):
    """Типы событий в системе."""
    
    # --- Торговые события ---
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    TRADE_REJECTED = "trade_rejected"
    TRADE_MODIFIED = "trade_modified"
    PARTIAL_CLOSED = "partial_closed"
    
    # --- События риска ---
    RISK_CHECK_PASSED = "risk_check_passed"
    RISK_CHECK_FAILED = "risk_check_failed"
    DRAWDOWN_LIMIT_APPROACHED = "drawdown_limit_approached"
    DRAWDOWN_LIMIT_EXCEEDED = "drawdown_limit_exceeded"
    VAR_LIMIT_EXCEEDED = "var_limit_exceeded"
    CORRELATION_WARNING = "correlation_warning"
    
    # --- ML события ---
    MODEL_LOADED = "model_loaded"
    MODEL_RETRAINED = "model_retrained"
    MODEL_TRAINING_STARTED = "model_training_started"
    MODEL_TRAINING_COMPLETED = "model_training_completed"
    MODEL_TRAINING_FAILED = "model_training_failed"
    CONCEPT_DRIFT_DETECTED = "concept_drift_detected"
    ANOMALY_DETECTED = "anomaly_detected"
    
    # --- События рынка ---
    MARKET_REGIME_CHANGED = "market_regime_changed"
    NEWS_PUBLISHED = "news_published"
    ECONOMIC_EVENT = "economic_event"
    PRICE_ALERT = "price_alert"
    VOLATILITY_SPIKE = "volatility_spike"
    
    # --- События системы ---
    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPED = "system_stopped"
    SYSTEM_ERROR = "system_error"
    SERVICE_STARTED = "service_started"
    SERVICE_STOPPED = "service_stopped"
    
    # --- События оркестратора ---
    ORCHESTRATOR_CYCLE_STARTED = "orchestrator_cycle_started"
    ORCHESTRATOR_CYCLE_COMPLETED = "orchestrator_cycle_completed"
    CAPITAL_REALLOCATED = "capital_reallocated"
    STRATEGY_HIRED = "strategy_hired"
    STRATEGY_FIRED = "strategy_fired"
    
    # --- События GUI ---
    GUI_UPDATE_REQUESTED = "gui_update_requested"
    USER_ACTION_PERFORMED = "user_action_performed"


# ===========================================
# Event Data Classes
# ===========================================

@dataclass
class Event:
    """Базовый класс события."""
    
    type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None  # Компонент-источник


@dataclass
class TradeEvent(Event):
    """Событие торговли."""
    
    symbol: str = ""
    lot: float = 0.0
    order_type: str = ""
    price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_name: str = ""
    pnl: Optional[float] = None
    ticket: Optional[int] = None
    reason: Optional[str] = None


@dataclass
class RiskEvent(Event):
    """Событие риска."""
    
    risk_type: str = ""
    current_value: float = 0.0
    threshold: float = 0.0
    action_taken: str = ""
    affected_symbols: List[str] = field(default_factory=list)


@dataclass
class MarketRegimeEvent(Event):
    """Событие смены режима рынка."""
    
    old_regime: str = ""
    new_regime: str = ""
    confidence: float = 0.0
    adx_value: Optional[float] = None
    volatility_percentile: Optional[float] = None


@dataclass
class ModelEvent(Event):
    """Событие ML модели."""
    
    model_type: str = ""
    symbol: str = ""
    timeframe: int = 0
    accuracy: Optional[float] = None
    loss: Optional[float] = None
    training_samples: int = 0


@dataclass
class SystemEvent(Event):
    """Системное событие."""
    
    component: str = ""
    status: str = ""
    message: str = ""
    error_details: Optional[str] = None


@dataclass
class OrchestratorEvent(Event):
    """Событие оркестратора."""
    
    cycle_id: str = ""
    regime: str = ""
    allocation_changes: Dict[str, float] = field(default_factory=dict)
    performance_metrics: Dict[str, Any] = field(default_factory=dict)


# ===========================================
# Event Factory
# ===========================================

class EventFactory:
    """Фабрика для создания событий."""
    
    @staticmethod
    def create_trade_opened(
        symbol: str,
        lot: float,
        order_type: str,
        price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        strategy_name: str,
        ticket: int,
        source: str = "TradeExecutor"
    ) -> TradeEvent:
        """Создание события об открытии сделки."""
        return TradeEvent(
            type=EventType.TRADE_OPENED,
            source=source,
            symbol=symbol,
            lot=lot,
            order_type=order_type,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            ticket=ticket
        )
    
    @staticmethod
    def create_trade_closed(
        ticket: int,
        symbol: str,
        pnl: float,
        close_reason: str,
        source: str = "TradeExecutor"
    ) -> TradeEvent:
        """Создание события о закрытии сделки."""
        return TradeEvent(
            type=EventType.TRADE_CLOSED,
            source=source,
            ticket=ticket,
            symbol=symbol,
            pnl=pnl,
            reason=close_reason
        )
    
    @staticmethod
    def create_trade_rejected(
        symbol: str,
        strategy_name: str,
        rejection_reason: str,
        source: str = "RiskEngine"
    ) -> TradeEvent:
        """Создание события об отклонении сделки."""
        return TradeEvent(
            type=EventType.TRADE_REJECTED,
            source=source,
            symbol=symbol,
            strategy_name=strategy_name,
            reason=rejection_reason
        )
    
    @staticmethod
    def create_system_error(
        component: str,
        message: str,
        error_details: Optional[str] = None,
        source: str = "System"
    ) -> SystemEvent:
        """Создание события об ошибке системы."""
        return SystemEvent(
            type=EventType.SYSTEM_ERROR,
            source=source,
            component=component,
            status="error",
            message=message,
            error_details=error_details
        )
