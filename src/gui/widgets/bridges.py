# -*- coding: utf-8 -*-
"""Сигналы для связи между потоками GUI."""

from __future__ import annotations

from typing import Any, Dict, List

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
    long_task_status_updated = Signal(str, str, bool)
    social_status_updated = Signal(str)  # НОВОЕ: Статус социальной торговли
    heavy_initialization_finished = Signal()
    drift_data_updated = Signal(float, str, float, bool)
    pnl_kpis_updated = Signal(dict)
    model_accuracy_updated = Signal(dict)
    retrain_progress_updated = Signal(dict)


class GUIBridge(QObject):
    """
    Мост для передачи сигналов из фоновых потоков (TradingSystem) в GUI.
    """

    log_message = Signal(object)
    update_status_changed = Signal(str, bool)
    market_data_updated = Signal(object)
    positions_updated = Signal(object)
    graph_data_updated = Signal(object)
