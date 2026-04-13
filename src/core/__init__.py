"""
Core модули системы трейдинга.

Центральные компоненты:
- Управление событиями (EventBus)
- Блокировки (LockManager)
- Ресурсы (ResourceGovernor)
- Circuit Breakers
- Домены потоков (ThreadDomains)
- Система торговли (TradingSystem)
"""

# CircuitBreaker
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    circuit_breaker_registry,
    create_circuit_breaker,
    get_circuit_breaker,
)

# EventBus
from .event_bus import (  # Новый API
    AsyncEventBus,
    EventBus,
    EventBusError,
    EventPriority,
    SubscriberTimeoutError,
    SystemEvent,
    event_bus,
    get_event_bus,
    on_event,
    on_event_async,
)

# Events
from .events import (
    Event,
    EventFactory,
    EventType,
    MarketRegimeEvent,
    ModelEvent,
    OrchestratorEvent,
    RiskEvent,
)
from .events import SystemEvent as LegacySystemEvent
from .events import (
    TradeEvent,
)

# LockManager
from .lock_manager import (
    DeadlockDetector,
    LockHierarchy,
    LockLevel,
    db_write_protected,
    lock_manager,
    mt5_protected,
    requires_locks,
)

# ResourceGovernor
from .resource_governor import (  # Новый API
    DEFAULT_LIMITS,
    AdaptiveResourceGovernor,
    ResourceBudget,
    ResourceClass,
    ResourceGovernor,
    get_governor,
)

# ThreadDomains
from .thread_domains import (
    DEFAULT_DOMAIN_CONFIG,
    DomainRegistry,
    ExecutorType,
    ResourceLimits,
    ThreadDomain,
    run_in_domain,
)

__all__ = [
    # EventBus (legacy)
    "EventBus",
    "event_bus",
    "on_event",
    "on_event_async",
    # EventBus (new)
    "AsyncEventBus",
    "get_event_bus",
    "EventPriority",
    "EventBusError",
    "SubscriberTimeoutError",
    # Events
    "Event",
    "EventType",
    "TradeEvent",
    "RiskEvent",
    "MarketRegimeEvent",
    "ModelEvent",
    "LegacySystemEvent",
    "OrchestratorEvent",
    "EventFactory",
    # LockManager
    "LockHierarchy",
    "LockLevel",
    "lock_manager",
    "mt5_protected",
    "db_write_protected",
    "requires_locks",
    "DeadlockDetector",
    # ResourceGovernor
    "ResourceGovernor",
    "ResourceClass",
    "get_governor",
    "DEFAULT_LIMITS",
    "AdaptiveResourceGovernor",
    "ResourceBudget",
    # CircuitBreaker
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerError",
    "CircuitOpenError",
    "CircuitBreakerRegistry",
    "circuit_breaker_registry",
    "get_circuit_breaker",
    "create_circuit_breaker",
    # ThreadDomains
    "ThreadDomain",
    "ExecutorType",
    "ResourceLimits",
    "DomainRegistry",
    "run_in_domain",
    "DEFAULT_DOMAIN_CONFIG",
]
