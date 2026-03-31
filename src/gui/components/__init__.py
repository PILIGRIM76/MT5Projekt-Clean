# -*- coding: utf-8 -*-
"""
GUI компоненты для Genesis Trading System.

Модули:
- models: Модели данных для Qt (QAbstractTableModel)
- bridges: Мосты между GUI и ядром (Bridge, GUIBridge)
- backtest: Компоненты для бэктестинга
- charts: Графические компоненты (CustomCandlestickItem, GraphBackend)
"""

from .models import (
    DictTableModel,
    GenericTableModel,
    RDTableModel
)

from .bridges import (
    Bridge,
    GUIBridge
)

from .backtest import (
    run_backtest_process,
    DirectiveDialog
)

from .charts import (
    CustomCandlestickItem,
    GraphBackend
)

__all__ = [
    # Models
    'DictTableModel',
    'GenericTableModel',
    'RDTableModel',
    
    # Bridges
    'Bridge',
    'GUIBridge',
    
    # Backtest
    'run_backtest_process',
    'DirectiveDialog',
    
    # Charts
    'CustomCandlestickItem',
    'GraphBackend',
]
