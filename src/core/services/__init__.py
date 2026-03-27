# src/core/services/__init__.py
"""
Пакет сервисов для TradingSystem.

Сервисы инкапсулируют отдельные функции системы:
- Торговля
- Мониторинг
- Оркестратор
- Риск-менеджмент
- Исполнение ордеров
"""

from src.core.services.base_service import (
    BaseService,
    ServiceManager,
    ServiceState,
    HealthStatus,
    ServiceMetrics,
)

from src.core.services.trading_service import TradingService
from src.core.services.monitoring_service import MonitoringService
from src.core.services.orchestrator_service import OrchestratorService
from src.core.services.risk_service import RiskService

__all__ = [
    # Базовые классы
    'BaseService',
    'ServiceManager',
    'ServiceState',
    'HealthStatus',
    'ServiceMetrics',
    
    # Конкретные сервисы
    'TradingService',
    'MonitoringService',
    'OrchestratorService',
    'RiskService',
]
