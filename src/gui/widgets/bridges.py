# -*- coding: utf-8 -*-
"""Сигналы для связи между потоками GUI."""

from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


class Bridge(QObject):
    """
    Мост для передачи сигналов между TradingSystem и GUI.
    Содержит все сигналы для обновления интерфейса.
    """

    status_updated = Signal(str, bool)
    balance_updated = Signal(float, float)
    log_message_added = Signal(str, QColor)
    positions_updated = Signal(list)
    history_updated = Signal(list)
    training_history_updated = Signal(object)
    candle_chart_updated = Signal(pd.DataFrame, str)
    pnl_updated = Signal(list)
    market_scan_updated = Signal(list)
    # Отдельный сигнал для торговых сигналов
    trading_signals_updated = Signal(list)
    uptime_updated = Signal(str)
    rd_progress_updated = Signal(dict)
    xai_data_ready = Signal(object, int)
    all_positions_closed = Signal()
    backtest_finished = Signal(dict, pd.DataFrame)
    market_regime_updated = Signal(str)
    update_status_changed = Signal(str, bool)
    initialization_successful = Signal(list)
    initialization_failed = Signal()
    directives_updated = Signal(list)
    times_updated = Signal(str, str)
    model_list_updated = Signal(list)
    orchestrator_allocation_updated = Signal(dict)
    knowledge_graph_updated = Signal(str)
    observer_pnl_updated = Signal(list)
    vector_db_search_results = Signal(list)

    thread_status_updated = Signal(str, str)
    # task_id, message, is_finished
    long_task_status_updated = Signal(str, str, bool)
    heavy_initialization_finished = Signal()
    drift_data_updated = Signal(float, str, float, bool)
    pnl_kpis_updated = Signal(dict)

    # НОВЫЕ: Сигналы для визуализации переобучения
    model_accuracy_updated = Signal(dict)  # {symbol: accuracy}
    retrain_progress_updated = Signal(dict)  # {symbol: hours_since_training}


class GUIBridge(QObject):
    """
    Мост для передачи сигналов из фоновых потоков (TradingSystem) в GUI.
    Определен здесь, чтобы быть доступным при инициализации.
    """

    log_message = Signal(object)  # Сообщение лога (строка или dict)
    # Текст статуса, Важность (True=Красный)
    update_status_changed = Signal(str, bool)
    # Данные для таблицы сканера (list of dicts)
    market_data_updated = Signal(object)
    # Данные о позициях (list of dicts)
    positions_updated = Signal(object)
    graph_data_updated = Signal(object)  # Данные для графа (nodes, edges)
