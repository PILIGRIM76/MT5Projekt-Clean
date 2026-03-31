# -*- coding: utf-8 -*-
"""
Мосты между GUI и ядром системы.

Содержит:
- Bridge: Основной мост для связи GUI с TradingSystem
- GUIBridge: Дополнительный мост для GUI операций
"""

import pandas as pd
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QColor


class Bridge(QObject):
    """
    Основной мост для связи GUI с ядром системы.

    Сигналы используются для асинхронного обновления GUI
    из рабочих потоков ядра системы.
    """

    # Основные статусы
    status_updated = Signal(str, bool)
    thread_status_updated = Signal(str, str)
    long_task_status_updated = Signal(str, str, bool)  # task_id, message, is_finished

    # Финансы
    balance_updated = Signal(float, float)  # balance, equity
    pnl_updated = Signal(list)
    pnl_kpis_updated = Signal(dict)

    # Логирование
    log_message_added = Signal(str, QColor)

    # Позиции и история
    positions_updated = Signal(list)
    history_updated = Signal(list)
    times_updated = Signal(str, str)  # server_time, local_time

    # Обучение и модели
    training_history_updated = Signal(object)
    candle_chart_updated = Signal(pd.DataFrame, str)
    model_list_updated = Signal(list)

    # Сканер рынка
    market_scan_updated = Signal(list)
    trading_signals_updated = Signal(list)

    # Статусы
    uptime_updated = Signal(str)
    rd_progress_updated = Signal(dict)
    xai_data_ready = Signal(object, int)

    # События
    all_positions_closed = Signal()
    backtest_finished = Signal(dict, pd.DataFrame)
    market_regime_updated = Signal(str)
    update_status_changed = Signal(str, bool)

    # Инициализация
    initialization_successful = Signal(list)
    initialization_failed = Signal()
    heavy_initialization_finished = Signal()

    # Директивы и оркестратор
    directives_updated = Signal(list)
    orchestrator_allocation_updated = Signal(dict)

    # Граф знаний и векторный поиск
    knowledge_graph_updated = Signal(str)
    observer_pnl_updated = Signal(list)
    vector_db_search_results = Signal(list)

    # Concept Drift
    drift_data_updated = Signal(float, str, float, bool)  # adwin_value, regime, mean, is_drift


class GUIBridge(QObject):
    """
    Дополнительный мост для GUI операций.

    Используется для специфических GUI задач которые не относятся
    напрямую к ядру торговой системы.
    """

    # Сигналы для GUI обновлений
    gui_update_requested = Signal(str, dict)
    user_action_performed = Signal(str, dict)

    @Slot(str, dict)
    def send_gui_update(self, update_type: str, data: dict):
        """Отправка обновления GUI."""
        self.gui_update_requested.emit(update_type, data)

    @Slot(str, dict)
    def log_user_action(self, action: str, data: dict):
        """Логирование действия пользователя."""
        self.user_action_performed.emit(action, data)
