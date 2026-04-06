# src/core/trading/__init__.py
"""
Trading Core — модули ядра торговой системы.

Выделены из TradingSystem God Object (~4200 строк):
- utils: кэширование, таймеры, таймфрейм хелперы
- gui_coordinator: безопасные обновления GUI
- trading_engine: ядро торговой логики
- ml_coordinator: координация ML обучения
"""

from src.core.trading.utils import (
    TradingCache,
    PerformanceTimer,
    get_timeframe_seconds,
    get_timeframe_str,
    TIMEFRAME_MAP,
)
from src.core.trading.gui_coordinator import GUICoordinator
from src.core.trading.trading_engine import TradingEngine
from src.core.trading.ml_coordinator import MLCoordinator

__all__ = [
    "TradingCache",
    "PerformanceTimer",
    "get_timeframe_seconds",
    "get_timeframe_str",
    "TIMEFRAME_MAP",
    "GUICoordinator",
    "TradingEngine",
    "MLCoordinator",
]
