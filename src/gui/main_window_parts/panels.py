# -*- coding: utf-8 -*-
"""
Панели MainWindow — top, left, right, KPI, thread status, vector DB.

Вынесены из main_pyside.py для уменьшения размера монолита.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QDate, Qt, QUrl, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from main_pyside import MainWindow

from src.gui.control_center_widget import ControlCenterWidget
from src.gui.widgets import CustomCandlestickItem, GraphBackend
from src.gui.widgets.defi_widget import DeFiWidget
from src.gui.models import GenericTableModel, RDTableModel
from src.strategies.strategy_loader import StrategyLoader

import MetaTrader5 as mt5
from pyqtgraph import BarGraphItem

logger = logging.getLogger(__name__)


class PanelsMixin:
    """Миксин с методами создания GUI-панелей для MainWindow."""

    # Все атрибуты (self.xxx) определены в MainWindow.
    # Этот миксин добавляет только методы.

    def _init_widgets(self: MainWindow):
        central_widget = QWidget()
        self.main_central_widget = central_widget
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        title_label = QLabel()
        title_label.setText('<font color="#FFD700">Genesis--Piligrim Evolution v10.0: The Reflexive Core</font>')
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 5px;")
        main_layout.addWidget(title_label)

        top_panel = self._create_top_panel()
        main_layout.addWidget(top_panel)
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)
        left_panel = self._create_left_panel()
        right_panel = self._create_right_panel()
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([650, 950])
        self.status_label = QLabel("Система не запущена.")
        sb = self.statusBar()
        if sb:
            sb.addWidget(self.status_label)

    def _create_top_panel(self: MainWindow):
        top_widget = QFrame()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        kpi_bar = self._create_kpi_bar()

        control_box = QFrame()
        control_layout = QHBoxLayout(control_box)
        control_layout.setAlignment(Qt.AlignTop)

        start_layout = QVBoxLayout()
        self.start_button = QPushButton("Запуск Системы")
        self.observer_checkbox = QCheckBox("Режим Наблюдателя")
        self.observer_checkbox.setChecked(True)
        start_layout.addWidget(self.start_button)
        start_layout.addWidget(self.observer_checkbox)
        start_layout.addStretch()
        control_layout.addLayout(start_layout)

        buttons_layout = QVBoxLayout()
        buttons_layout.setAlignment(Qt.AlignTop)

        self.stop_button = QPushButton("Остановка")
        self.stop_button.setEnabled(False)

        self.settings_button = QPushButton("Настройки")

        self.restart_system_button = QPushButton("Перезапустить Систему")
        self.restart_system_button.setStyleSheet("background-color: #ffb86c; color: #000;")

        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.settings_button)
        buttons_layout.addWidget(self.restart_system_button)
        control_layout.addLayout(buttons_layout)

        update_box = QFrame()
        update_layout = QVBoxLayout(update_box)

        version_layout = QHBoxLayout()
        self.update_version_label = QLabel("📦 Версия: N/A")
        self.update_version_label.setStyleSheet("color: #50fa7b; font-weight: bold;")
        version_layout.addWidget(self.update_version_label)
        version_layout.addStretch()
        update_layout.addLayout(version_layout)

        self.update_status_label = QLabel("🔄 Статус: Загрузка...")
        self.update_status_label.setStyleSheet("color: #f8f8f2;")
        update_layout.addWidget(self.update_status_label)

        self.update_monitoring_label = QLabel("👁️ Мониторинг: N/A")
        self.update_monitoring_label.setStyleSheet("color: #888;")
        update_layout.addWidget(self.update_monitoring_label)

        self.update_last_check_label = QLabel("⏰ Последняя проверка: N/A")
        self.update_last_check_label.setStyleSheet("color: #888; font-size: 11px;")
        update_layout.addWidget(self.update_last_check_label)

        self.update_button = QPushButton("⬇️ Обновить и Перезапустить")
        self.update_button.setEnabled(False)
        self.update_button.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #282a36;
                border: none;
                padding: 8px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #69ff94;
            }
            QPushButton:disabled {
                background-color: #44475a;
                color: #6272a4;
            }
        """)
        update_layout.addWidget(self.update_button)

        thread_status_box = self._create_thread_status_panel()
        thread_status_box.setObjectName("ThreadStatusBox")

        account_box = QFrame()
        account_layout = QVBoxLayout(account_box)
        self.balance_label = QLabel("Баланс: N/A")
        self.equity_label = QLabel("Эквити: N/A")
        self.uptime_label = QLabel("Время работы: -")
        self.uptime_label.setStyleSheet("font-weight: bold; color: #50fa7b;")
        self.pc_time_label = QLabel("PC Время: --:--:--")
        self.server_time_label = QLabel("Время сервера: --:--:--")

        account_layout.addWidget(self.balance_label)
        account_layout.addWidget(self.equity_label)
        account_layout.addWidget(self.uptime_label)
        account_layout.addWidget(self.pc_time_label)
        account_layout.addWidget(self.server_time_label)

        top_layout.addWidget(control_box)
        top_layout.addWidget(update_box)
        top_layout.addWidget(thread_status_box)
        top_layout.addWidget(self.notification_bar)
        top_layout.addWidget(kpi_bar)

        top_layout.addStretch()
        top_layout.addWidget(account_box)

        return top_widget

    def _create_kpi_bar(self: MainWindow) -> QGroupBox:
        group_box = QGroupBox("PnL по Периодам")
        layout = QGridLayout(group_box)

        self.pnl_day_label = QLabel("День: N/A")
        self.pnl_week_label = QLabel("Неделя: N/A")
        self.pnl_month_label = QLabel("Месяц: N/A")

        self.open_pnl_label = QLabel("N/A")
        self.open_pnl_label.setToolTip("Текущая прибыль/убыток по НЕзакрытым позициям (Equity - Balance).")
        self.open_pnl_label.setStyleSheet("font-weight: bold; color: #8be9fd;")

        self.dd_day_label = QLabel("DD День: N/A")
        self.dd_week_label = QLabel("DD Неделя: N/A")
        self.dd_month_label = QLabel("DD Месяц: N/A")

        self.pnl_day_label.setToolTip("Чистая прибыль/убыток (PnL) по закрытым сделкам с начала текущего дня (00:00 UTC).")
        self.pnl_week_label.setToolTip(
            "Чистая прибыль/убыток (PnL) по закрытым сделкам с начала текущей недели (Понедельник 00:00 UTC)."
        )
        self.pnl_month_label.setToolTip(
            "Чистая прибыль/убыток (PnL) по закрытым сделкам с начала текущего месяца (1-е число 00:00 UTC)."
        )
        self.open_pnl_label.setToolTip("Текущая прибыль/убыток по НЕзакрытым позициям (Equity - Balance).")
        self.dd_day_label.setToolTip("Максимальная просадка (Max Drawdown) по закрытым сделкам с начала текущего дня.")
        self.dd_week_label.setToolTip("Максимальная просадка (Max Drawdown) по закрытым сделкам с начала текущей недели.")
        self.dd_month_label.setToolTip("Максимальная просадка (Max Drawdown) по закрытым сделкам с начала текущего месяца.")

        self.pnl_day_label.setStyleSheet("font-weight: bold; color: #50fa7b;")
        self.dd_day_label.setStyleSheet("font-weight: bold; color: #ff5555;")

        layout.addWidget(QLabel("Прибыль (закрыто):"), 0, 0)
        layout.addWidget(self.pnl_day_label, 0, 1)
        layout.addWidget(self.pnl_week_label, 0, 2)
        layout.addWidget(self.pnl_month_label, 0, 3)

        open_pnl_col = QWidget()
        open_pnl_layout = QVBoxLayout(open_pnl_col)
        open_pnl_layout.setContentsMargins(0, 0, 0, 0)
        open_pnl_layout.setSpacing(2)
        open_pnl_layout.addWidget(QLabel("Открыто:"))
        open_pnl_layout.addWidget(self.open_pnl_label)
        layout.addWidget(open_pnl_col, 0, 4, 2, 1)

        layout.addWidget(QLabel("Max DD (%):"), 1, 0)
        layout.addWidget(self.dd_day_label, 1, 1)
        layout.addWidget(self.dd_week_label, 1, 2)
        layout.addWidget(self.dd_month_label, 1, 3)

        return group_box

    def _create_thread_status_panel(self: MainWindow) -> QGroupBox:
        group_box = QGroupBox("Статус Системы")
        layout = QGridLayout(group_box)
        layout.setColumnStretch(1, 1)

        thread_names = {
            "Trading": "Торговый:",
            "Monitoring": "Мониторинг:",
            "Training": "R&D:",
            "Orchestrator": "Оркестратор:",
            "VectorDB Cleanup": "VectorDB Cleanup:",
        }

        row = 0
        for key, name in thread_names.items():
            layout.addWidget(QLabel(name), row, 0, Qt.AlignRight)
            status_label = QLabel("STOPPED")
            status_label.setStyleSheet("font-weight: bold; color: #ff5555;")
            layout.addWidget(status_label, row, 1, 1, 2)
            self.thread_status_labels[key] = status_label
            row += 1

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator, row, 0, 1, 3)
        row += 1

        layout.addWidget(QLabel("Обслуживание:"), row, 0, Qt.AlignRight)
        maint_label = QLabel("...")
        maint_label.setStyleSheet("color: #f1fa8c;")
        layout.addWidget(maint_label, row, 1, 1, 2)
        self.scheduler_status_labels["Maintenance"] = maint_label
        row += 1

        layout.addWidget(QLabel("Оптимизация:"), row, 0, Qt.AlignRight)
        opt_label = QLabel("...")
        opt_label.setStyleSheet("color: #f1fa8c;")
        layout.addWidget(opt_label, row, 1, 1, 2)
        self.scheduler_status_labels["Optimization"] = opt_label

        return group_box

    def _create_left_panel(self: MainWindow):
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        tab_widget = QTabWidget()

        tab_widget.currentChanged.connect(lambda idx: self.on_left_tab_changed(idx, tab_widget))
        logger.info("[GUI-Init] Инициализация левой панели")

        positions_tab_widget = QWidget()
        positions_tab_layout = QVBoxLayout(positions_tab_widget)
        positions_control_layout = QHBoxLayout()
        positions_control_layout.addWidget(QLabel("<b>Открытые Позиции</b>"))
        positions_control_layout.addStretch()
        self.close_all_pos_button = QPushButton("Закрыть все")
        self.close_all_pos_button.setStyleSheet("background-color: #8B0000;")
        positions_control_layout.addWidget(self.close_all_pos_button)
        self.close_pos_button = QPushButton("Закрыть выбранную")
        positions_control_layout.addWidget(self.close_pos_button)

        self.positions_table = QTableView()
        self.positions_headers = [
            "Тикет", "Сим\nвол", "Стра\nтегия", "Тип", "Объем",
            "Цена\nоткр.", "При\nбыль", "Баров\nв сделке", "ТФ",
        ]
        self.positions_model = GenericTableModel([], self.positions_headers)
        self.positions_table.setModel(self.positions_model)
        header_pos = self.positions_table.horizontalHeader()
        header_pos.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header_pos.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_pos.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        positions_tab_layout.addLayout(positions_control_layout)
        positions_tab_layout.addWidget(self.positions_table)
        tab_widget.addTab(positions_tab_widget, "Открытые Позиции")

        self.history_table = QTableView()
        self.history_headers = [
            "Тикет", "Сим\nвол", "Стра\nтегия", "Тип", "Объем",
            "Цена\nзакр.", "Время\nзакр.", "При\nбыль", "ТФ",
        ]
        self.history_model = GenericTableModel([], self.history_headers)
        self.history_table.setModel(self.history_model)

        header_hist = self.history_table.horizontalHeader()
        header_hist.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header_hist.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header_hist.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)

        tab_widget.addTab(self.history_table, "История Сделок")

        left_layout.addWidget(tab_widget)
        log_box = QFrame()
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(QLabel("Логи Системы"))
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        log_layout.addWidget(self.log_text_edit)
        left_layout.addWidget(log_box)

        return left_widget

    def _create_right_panel(self: MainWindow, vector_db_tab=None):
        right_widget = QTabWidget()

        # --- ОСНОВНОЙ ГРАФИК ---
        self.chart_layout_widget = pg.GraphicsLayoutWidget()
        right_widget.addTab(self.chart_layout_widget, "Основной График")
        self.price_plot = self.chart_layout_widget.addPlot(row=0, col=0)
        self.price_plot.setAxisItems({"bottom": pg.DateAxisItem()})

        grid_pen = pg.mkPen(color="#888", style=Qt.DotLine)
        self.price_plot.showGrid(x=True, y=True, alpha=0.3)
        self.price_plot.getAxis("bottom").setPen(grid_pen)
        self.price_plot.getAxis("left").setPen(grid_pen)
        self.price_plot.getAxis("left").setWidth(60)
        self.price_plot.disableAutoRange()

        self.regime_region = pg.LinearRegionItem(
            values=[0, 1], orientation="vertical", movable=False, brush=QColor(0, 0, 0, 0)
        )
        self.regime_region.setZValue(-100)
        self.price_plot.addItem(self.regime_region)
        self.regime_colors = {
            "Strong Trend": QColor(0, 255, 0, 30),
            "Weak Trend": QColor(0, 255, 0, 15),
            "High Volatility Range": QColor(255, 255, 0, 30),
            "Low Volatility Range": QColor(0, 0, 255, 20),
        }

        self.chart_layout_widget.nextRow()
        self.volume_plot = self.chart_layout_widget.addPlot(row=1, col=0)
        self.volume_plot.setMaximumHeight(150)
        self.volume_plot.showGrid(x=True, y=True, alpha=0.3)
        self.volume_plot.getAxis("bottom").setPen(grid_pen)
        self.volume_plot.getAxis("left").setPen(grid_pen)
        self.volume_plot.getAxis("left").setWidth(60)
        self.volume_plot.setXLink(self.price_plot)

        self.candlestick_item = CustomCandlestickItem()
        self.price_plot.addItem(self.candlestick_item)
        self.volume_item = BarGraphItem(x=[], height=[], width=0.8, brush="#50fa7b")
        self.ema50_item = pg.PlotDataItem(pen=pg.mkPen("c", width=2))
        self.ema200_item = pg.PlotDataItem(pen=pg.mkPen("y", width=2))
        self.trade_arrows_item = pg.ScatterPlotItem()
        self.price_plot.addItem(self.ema50_item)
        self.price_plot.addItem(self.ema200_item)
        self.price_plot.addItem(self.trade_arrows_item)
        self.volume_plot.addItem(self.volume_item)

        vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("gray", style=Qt.DashLine))
        hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("gray", style=Qt.DashLine))
        self.price_plot.addItem(vLine, ignoreBounds=True)
        self.price_plot.addItem(hLine, ignoreBounds=True)
        self.crosshair_label = pg.TextItem(anchor=(0, 1))
        self.price_plot.addItem(self.crosshair_label)

        def mouse_moved(evt):
            pos = evt[0]
            if self.price_plot.sceneBoundingRect().contains(pos):
                mouse_point = self.price_plot.vb.mapSceneToView(pos)
                if np.isnan(mouse_point.x()):
                    return
                timestamp = int(mouse_point.x())
                price = mouse_point.y()
                if timestamp < 0 or timestamp > 32503680000:
                    return
                vLine.setPos(timestamp)
                hLine.setPos(price)
                try:
                    from datetime import datetime
                    time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
                    self.crosshair_label.setText(f"{time_str}, {price:.5f}")
                    view_range = self.price_plot.vb.viewRange()
                    self.crosshair_label.setPos(view_range[0][0], view_range[1][1])
                except (OSError, ValueError) as e:
                    logger.debug(f"Ошибка при обновлении позиции crosshair: {e}")

        self.proxy = pg.SignalProxy(self.price_plot.scene().sigMouseMoved, rateLimit=60, slot=mouse_moved)

        # --- ЦЕНТР УПРАВЛЕНИЯ ---
        self.control_center_tab = ControlCenterWidget(
            bridge=self.bridge, config=self.config, trading_system_adapter=self.trading_system
        )
        self.control_center_tab.load_initial_settings()
        logger.info("[GUI] ControlCenterWidget инициализирован с настройками")
        right_widget.addTab(self.control_center_tab, "Центр Управления")

        # --- АНАЛИТИКА ---
        analytics_tab_widget = QWidget()
        analytics_layout = QVBoxLayout(analytics_tab_widget)

        self.loss_plot_widget = pg.PlotWidget(title="🔄 Прогресс обучения (Loss)")
        self.loss_plot = self.loss_plot_widget.getPlotItem()
        self.loss_plot.showGrid(x=True, y=True, alpha=0.3)
        self.loss_plot.getAxis("bottom").setLabel("Эпоха обучения")
        self.loss_plot.getAxis("left").setLabel("Loss")
        self.loss_curve = self.loss_plot.plot(pen="y", symbol="o", symbolBrush="y", symbolSize=3)
        self.loss_curve.setData(x=[], y=[])

        compact_charts_widget = QWidget()
        compact_charts_layout = QHBoxLayout(compact_charts_widget)
        compact_charts_layout.setContentsMargins(0, 0, 0, 0)
        compact_charts_layout.setSpacing(5)

        self.model_accuracy_plot_widget = pg.PlotWidget(title="📊 Точность")
        self.model_accuracy_plot = self.model_accuracy_plot_widget.getPlotItem()
        self.model_accuracy_plot.showGrid(x=True, y=True, alpha=0.3)
        self.model_accuracy_plot.getAxis("bottom").setLabel("Символ")
        self.model_accuracy_plot.getAxis("left").setRange(0, 1)
        self.model_accuracy_bars = pg.BarGraphItem(x=[], height=[], width=0.5, brush="g")
        self.model_accuracy_plot.addItem(self.model_accuracy_bars)
        self.model_accuracy_plot.addItem(pg.InfiniteLine(angle=0, pos=0.5, pen=pg.mkPen("r", style=Qt.DashLine)))
        self.model_accuracy_data = {}

        self.retrain_progress_widget = pg.PlotWidget(title="⏰ До переобучения (ч)")
        self.retrain_progress_plot = self.retrain_progress_widget.getPlotItem()
        self.retrain_progress_plot.showGrid(x=True, y=True, alpha=0.3)
        self.retrain_progress_plot.getAxis("bottom").setLabel("Символ")
        self.retrain_progress_plot.getAxis("left").setRange(0, 3)
        self.retrain_progress_bars = pg.BarGraphItem(x=[], height=[], width=0.5, brush="b")
        self.retrain_progress_plot.addItem(self.retrain_progress_bars)
        self.retrain_progress_plot.addItem(pg.InfiniteLine(angle=0, pos=1.0, pen=pg.mkPen("y", style=Qt.DashLine)))
        self.retrain_progress_data = {}

        compact_charts_layout.addWidget(self.model_accuracy_plot_widget, 1)
        compact_charts_layout.addWidget(self.retrain_progress_widget, 1)

        self.pnl_plot_widget = pg.PlotWidget(title="Кривая доходности (P&L)")
        self.pnl_plot = self.pnl_plot_widget.getPlotItem()
        self.pnl_plot.showGrid(x=True, y=True, alpha=0.3)
        self.pnl_plot.getAxis("left").setLabel("Баланс", units="USD")
        self.pnl_plot.setAxisItems({"bottom": pg.DateAxisItem()})
        self.pnl_curve = self.pnl_plot.plot(pen="g")

        self.observer_pnl_plot_widget = pg.PlotWidget(title="Доходность (Режим Наблюдателя)")
        self.observer_pnl_plot = self.observer_pnl_plot_widget.getPlotItem()
        self.observer_pnl_plot.showGrid(x=True, y=True, alpha=0.3)
        self.observer_pnl_plot.getAxis("left").setLabel("Баланс (симуляция)", units="USD")
        self.observer_pnl_plot.getAxis("bottom").setLabel("Количество виртуальных сделок")
        self.observer_pnl_curve = self.observer_pnl_plot.plot(pen=pg.mkPen("c", width=2))

        self.drift_plot_widget = pg.PlotWidget(title="Ошибка предсказаний AI (Concept Drift)")
        self.drift_plot = self.drift_plot_widget.getPlotItem()
        self.drift_plot.showGrid(x=True, y=True, alpha=0.3)
        self.drift_plot.getAxis("bottom").setLabel("Время")
        self.drift_plot.getAxis("left").setLabel("Ошибка (APE)")
        self.drift_plot.setAxisItems({"bottom": pg.DateAxisItem()})

        self.drift_scatter = pg.ScatterPlotItem(size=8, pen=pg.mkPen(None), brush=pg.mkBrush("#50fa7b"), symbol="o")
        self.drift_plot.addItem(self.drift_scatter)
        self.drift_alert_scatter = pg.ScatterPlotItem(
            size=12, pen=pg.mkPen("w", width=2), brush=pg.mkBrush("#ff5555"), symbol="x"
        )
        self.drift_plot.addItem(self.drift_alert_scatter)

        self.drift_data_points = []
        self.drift_alert_points = []

        analytics_layout.addWidget(self.loss_plot_widget)
        analytics_layout.addWidget(compact_charts_widget)
        analytics_layout.addWidget(self.pnl_plot_widget)
        analytics_layout.addWidget(self.observer_pnl_plot_widget)
        analytics_layout.addWidget(self.drift_plot_widget)

        self.loss_plot_widget.setMinimumHeight(180)
        compact_charts_widget.setMinimumHeight(150)
        self.pnl_plot_widget.setMinimumHeight(150)
        self.observer_pnl_plot_widget.setMinimumHeight(150)
        self.drift_plot_widget.setMinimumHeight(150)

        analytics_subtabs = QTabWidget()

        training_charts_widget = QWidget()
        training_charts_layout = QVBoxLayout(training_charts_widget)
        training_charts_layout.addWidget(self.loss_plot_widget)
        training_charts_layout.addWidget(compact_charts_widget)
        analytics_subtabs.addTab(training_charts_widget, "📈 Обучение")

        performance_charts_widget = QWidget()
        performance_charts_layout = QVBoxLayout(performance_charts_widget)
        performance_charts_layout.addWidget(self.pnl_plot_widget)
        performance_charts_layout.addWidget(self.observer_pnl_plot_widget)
        analytics_subtabs.addTab(performance_charts_widget, "💰 Производительность")

        drift_charts_widget = QWidget()
        drift_charts_layout = QVBoxLayout(drift_charts_widget)
        drift_charts_layout.addWidget(self.drift_plot_widget)
        analytics_subtabs.addTab(drift_charts_widget, "🔍 Дрейф")

        analytics_layout.addWidget(analytics_subtabs)
        right_widget.addTab(analytics_tab_widget, "📈 Аналитика")

        # --- СКАНЕР РЫНКА ---
        scanner_widget = QWidget()
        scanner_layout = QVBoxLayout(scanner_widget)
        self.scanner_table = QTableView()
        self.scanner_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scanner_table.customContextMenuRequested.connect(self.show_scanner_context_menu)

        self.scanner_table.setAlternatingRowColors(True)
        self.scanner_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.scanner_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.scanner_table.verticalHeader().setVisible(False)

        scanner_layout.addWidget(self.scanner_table)

        self.scanner_headers = [
            "Ранг", "Символ", "Итоговая Оценка", "Оценка Вол.",
            "Норм. ATR (%)", "Тренд", "Ликвидность", "Спред (пипсы)",
        ]

        self.scanner_model = GenericTableModel([], self.scanner_headers)
        self.scanner_table.setModel(self.scanner_model)

        header = self.scanner_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        right_widget.addTab(scanner_widget, "Сканер Рынка")

        # --- ПАНЕЛЬ ОРКЕСТРАТОРА ---
        orchestrator_tab = QWidget()
        orchestrator_layout = QVBoxLayout(orchestrator_tab)
        orchestrator_layout.addWidget(QLabel("<b>Распределение капитала Оркестратором (в реальном времени)</b>"))
        self.orchestrator_chart_widget = pg.PlotWidget()
        self.orchestrator_chart_widget.showGrid(x=True, y=True, alpha=0.3)
        self.orchestrator_bar_item = pg.BarGraphItem(x=[], height=[], width=0.6, brush="g")
        self.orchestrator_chart_widget.addItem(self.orchestrator_bar_item)
        self.orchestrator_chart_widget.getAxis("left").setLabel("Доля капитала", units="%")
        self.orchestrator_chart_widget.getAxis("bottom").setTicks([[]])
        orchestrator_layout.addWidget(self.orchestrator_chart_widget)
        right_widget.addTab(orchestrator_tab, "Панель Оркестратора")

        # --- R&D ЦЕНТР ---
        rd_tab_widget = QWidget()
        rd_layout = QVBoxLayout(rd_tab_widget)
        rd_controls_layout = QHBoxLayout()
        self.force_rd_button = QPushButton("Запустить R&D цикл сейчас")
        rd_controls_layout.addWidget(self.force_rd_button)
        rd_controls_layout.addStretch()
        self.rd_table = QTableView()
        self.rd_headers = ["Поколение", "Лучший Fitness", "Конфигурация стратегии"]
        self.rd_model = RDTableModel(self.rd_headers)
        self.rd_table.setModel(self.rd_model)
        self.rd_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rd_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        rd_layout.addLayout(rd_controls_layout)
        rd_layout.addWidget(self.rd_table)
        right_widget.addTab(rd_tab_widget, "R&D Центр")

        # --- ЦЕНТР РЕФЛЕКСИИ ---
        reflexion_tab_widget = QWidget()
        reflexion_layout = QVBoxLayout(reflexion_tab_widget)
        reflexion_controls_layout = QHBoxLayout()
        self.create_directive_button = QPushButton("Создать Директиву")
        self.delete_directive_button = QPushButton("Удалить Директиву")
        self.delete_directive_button.setStyleSheet("background-color: #ff5555;")
        reflexion_controls_layout.addWidget(self.create_directive_button)
        reflexion_controls_layout.addStretch()
        reflexion_controls_layout.addWidget(self.delete_directive_button)
        self.directives_table = QTableView()
        self.directives_headers = ["Директива", "Значение", "Причина", "Действует до"]
        self.directives_model = GenericTableModel([], self.directives_headers)
        self.directives_table.setModel(self.directives_model)
        self.directives_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.directives_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        reflexion_layout.addWidget(QLabel("<b>Активные Директивы Системы</b>"))
        reflexion_layout.addLayout(reflexion_controls_layout)
        reflexion_layout.addWidget(self.directives_table)
        right_widget.addTab(reflexion_tab_widget, "Центр Рефлексии")

        # --- МЕНЕДЖЕР МОДЕЛЕЙ ---
        model_manager_tab = QWidget()
        model_manager_layout = QVBoxLayout(model_manager_tab)
        mm_controls_layout = QHBoxLayout()
        self.refresh_models_button = QPushButton("Обновить список")
        self.demote_model_button = QPushButton("Разжаловать чемпиона")
        self.demote_model_button.setStyleSheet("background-color: #8B0000;")
        mm_controls_layout.addWidget(self.refresh_models_button)
        mm_controls_layout.addStretch()
        mm_controls_layout.addWidget(self.demote_model_button)
        self.models_table = QTableView()
        self.models_headers = ["ID", "Символ", "Тип", "Версия", "Статус", "Sharpe", "Profit Factor", "Дата обучения"]
        self.models_model = GenericTableModel([], self.models_headers)
        self.models_table.setModel(self.models_model)
        self.models_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.models_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        model_manager_layout.addLayout(mm_controls_layout)
        model_manager_layout.addWidget(self.models_table)
        right_widget.addTab(model_manager_tab, "Менеджер Моделей")

        # --- DeFi МЕТРИКИ ---
        self.defi_widget = DeFiWidget()
        right_widget.addTab(self.defi_widget, "💎 DeFi Метрики")

        # --- ГРАФ ЗНАНИЙ ---
        knowledge_graph_tab = QWidget()
        kg_layout = QVBoxLayout(knowledge_graph_tab)

        kg_controls_layout = QHBoxLayout()
        self.kg_enabled_checkbox = QCheckBox("Включить/Отключить визуализацию графа")
        self.kg_enabled_checkbox.setToolTip("Включает/отключает ресурсоемкую отрисовку графа знаний в реальном времени.")
        self.kg_enabled_checkbox.setChecked(self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION)

        kg_controls_layout.addWidget(self.kg_enabled_checkbox)
        kg_controls_layout.addStretch()
        kg_layout.addLayout(kg_controls_layout)

        kg_layout.addWidget(QLabel("<b>Интерактивная карта причинно-следственных связей</b>"))

        self.knowledge_graph_view = QWebEngineView()
        self.knowledge_graph_view.page().setBackgroundColor(Qt.transparent)

        self.kg_disabled_label = QLabel("Визуализация графа знаний отключена.\nАнализ связей в фоне продолжается.")
        self.kg_disabled_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kg_disabled_label.setStyleSheet("font-size: 14px; color: gray; padding: 20px; border: 2px dashed #444;")

        kg_layout.addWidget(self.knowledge_graph_view)
        kg_layout.addWidget(self.kg_disabled_label)

        self.graph_backend = GraphBackend(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("backend", self.graph_backend)
        self.knowledge_graph_view.page().setWebChannel(self.channel)

        project_root = os.path.dirname(os.path.abspath(__file__))
        graph_html_path = os.path.join(project_root, "..", "..", "..", "assets", "graph_view.html")

        if os.path.exists(graph_html_path):
            QTimer.singleShot(100, lambda: self.knowledge_graph_view.setUrl(QUrl.fromLocalFile(graph_html_path)))
        else:
            logger.error(f"Не найден файл для визуализации графа: {graph_html_path}")
            self.knowledge_graph_view.setHtml(f"<h3 style='color:red'>Файл не найден: {graph_html_path}</h3>")

        right_widget.addTab(knowledge_graph_tab, "Граф Знаний")

        # --- ВЕКТОРНАЯ БД ---
        vector_db_tab = self._create_vector_db_tab()
        right_widget.addTab(vector_db_tab, "Векторная БД (RAG)")

        # --- XAI ---
        xai_tab_widget = QWidget()
        xai_layout = QVBoxLayout(xai_tab_widget)
        self.xai_label = QLabel("Кликните на сделку в 'Истории Сделок' для анализа")
        self.xai_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.xai_web_view = QWebEngineView()
        self.xai_web_view.setHtml(
            "<html><body style='background-color:#282a36;'><h3 style='color:#f8f8f2; text-align:center;'>Ожидание данных...</h3></body></html>"
        )
        feedback_panel = QFrame()
        feedback_layout = QHBoxLayout(feedback_panel)
        feedback_panel.setLayout(feedback_layout)
        self.good_trade_button = QPushButton("👍 Хорошее решение")
        self.good_trade_button.setStyleSheet("background-color: #50fa7b; color: #000;")
        self.good_trade_button.setEnabled(False)
        self.bad_trade_button = QPushButton("👎 Плохое решение")
        self.bad_trade_button.setStyleSheet("background-color: #ff5555;")
        self.bad_trade_button.setEnabled(False)
        feedback_layout.addStretch()
        feedback_layout.addWidget(self.good_trade_button)
        feedback_layout.addWidget(self.bad_trade_button)
        feedback_layout.addStretch()
        xai_layout.addWidget(self.xai_label)
        xai_layout.addWidget(self.xai_web_view)
        xai_layout.addWidget(feedback_panel)
        right_widget.addTab(xai_tab_widget, "Анализ Сделки (XAI)")

        # --- БЭКТЕСТЕР ---
        backtester_tab = QWidget()
        backtester_layout = QVBoxLayout(backtester_tab)
        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)
        self.bt_symbol_combo = QComboBox()
        self.bt_test_type_combo = QComboBox()

        self.bt_test_type_combo.addItems(
            ["Event-Driven Backtest", "Системный бэктест (Экосистема)", "Классическая стратегия", "AI Модель"]
        )

        self.bt_strategy_combo = QComboBox()
        self.bt_timeframe_combo = QComboBox()
        self.timeframe_map = {
            "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
        }
        self.bt_timeframe_combo.addItems(list(self.timeframe_map.keys()))
        self.bt_timeframe_combo.setCurrentText("H1")
        strategy_loader = StrategyLoader(self.trading_system.config)
        strategies = strategy_loader.load_strategies()
        for s in strategies:
            if "Strategy" in s.__class__.__name__:
                self.bt_strategy_combo.addItem(s.__class__.__name__)
        self.bt_start_date = QDateEdit(QDate.currentDate().addMonths(-3))
        self.bt_start_date.setCalendarPopup(True)
        self.bt_end_date = QDateEdit(QDate.currentDate())
        self.bt_end_date.setCalendarPopup(True)
        self.bt_run_button = QPushButton("Запустить Бэктест")
        controls_layout.addWidget(QLabel("Символ:"))
        controls_layout.addWidget(self.bt_symbol_combo)
        controls_layout.addWidget(QLabel("Тип теста:"))
        controls_layout.addWidget(self.bt_test_type_combo)
        controls_layout.addWidget(QLabel("Стратегия/Модель:"))
        controls_layout.addWidget(self.bt_strategy_combo)
        controls_layout.addWidget(QLabel("ТФ:"))
        controls_layout.addWidget(self.bt_timeframe_combo)
        controls_layout.addWidget(QLabel("С:"))
        controls_layout.addWidget(self.bt_start_date)
        controls_layout.addWidget(QLabel("По:"))
        controls_layout.addWidget(self.bt_end_date)
        controls_layout.addStretch()
        controls_layout.addWidget(self.bt_run_button)
        results_splitter = QSplitter(Qt.Orientation.Vertical)
        self.bt_report_text = QTextEdit("Здесь будет отчет по результатам бэктеста...")
        self.bt_report_text.setReadOnly(True)
        self.bt_equity_chart_widget = pg.GraphicsLayoutWidget()
        self.bt_equity_plot = self.bt_equity_chart_widget.addPlot(title="Кривая доходности (Equity)")
        self.bt_equity_curve = self.bt_equity_plot.plot(pen="g")
        results_splitter.addWidget(self.bt_report_text)
        results_splitter.addWidget(self.bt_equity_chart_widget)
        results_splitter.setSizes([200, 400])
        backtester_layout.addWidget(controls_frame)
        backtester_layout.addWidget(results_splitter)
        right_widget.addTab(backtester_tab, "Бэктестер")

        right_widget.currentChanged.connect(self.on_tab_changed)
        logger.info("[GUI-Init] Все вкладки правой панели инициализированы")

        return right_widget

    def _create_vector_db_tab(self: MainWindow):
        from PySide6.QtWidgets import QTableView

        widget = QWidget()
        layout = QVBoxLayout(widget)

        top_frame = QFrame()
        top_frame.setFrameShape(QFrame.Shape.StyledPanel)
        top_layout = QHBoxLayout(top_frame)

        stats_layout = QVBoxLayout()
        self.vdb_count_label = QLabel("Документов в индексе: --")
        self.vdb_count_label.setStyleSheet("font-size: 12pt; font-weight: bold; color: #50fa7b;")
        self.vdb_status_label = QLabel("Статус: Инициализация...")
        stats_layout.addWidget(self.vdb_count_label)
        stats_layout.addWidget(self.vdb_status_label)

        btn_layout = QVBoxLayout()
        self.vdb_refresh_btn = QPushButton("Обновить статистику")
        self.vdb_refresh_btn.clicked.connect(self._refresh_vector_db_stats)
        btn_layout.addWidget(self.vdb_refresh_btn)

        top_layout.addLayout(stats_layout)
        top_layout.addStretch()
        top_layout.addLayout(btn_layout)
        layout.addWidget(top_frame)

        search_group = QGroupBox("Семантический Поиск (RAG)")
        search_layout = QVBoxLayout(search_group)

        input_layout = QHBoxLayout()
        self.vdb_query_edit = QLineEdit()
        self.vdb_query_edit.setPlaceholderText("Введите запрос (напр. 'Inflation impact on Gold' или 'Rate hike')...")
        self.vdb_query_edit.returnPressed.connect(self._run_vector_db_search)

        self.vdb_search_button = QPushButton("Найти похожие новости")
        self.vdb_search_button.clicked.connect(self._run_vector_db_search)
        self.vdb_search_button.setStyleSheet("background-color: #bd93f9; color: #282a36; font-weight: bold;")

        input_layout.addWidget(self.vdb_query_edit)
        input_layout.addWidget(self.vdb_search_button)
        search_layout.addLayout(input_layout)
        layout.addWidget(search_group)

        self.vdb_results_table = QTableWidget()
        self.vdb_results_table.setColumnCount(4)
        self.vdb_results_table.setHorizontalHeaderLabels(["Сходство", "Источник", "Дата", "Фрагмент текста"])
        self.vdb_results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.vdb_results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.vdb_results_table.setAlternatingRowColors(True)
        self.vdb_results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.vdb_results_table)

        self.bridge.vector_db_search_results.connect(self._display_vector_db_results)

        QTimer.singleShot(2000, self._refresh_vector_db_stats)

        return widget

    def _on_backtest_type_changed(self: MainWindow):
        test_type = self.bt_test_type_combo.currentText()
        self.bt_strategy_combo.clear()
        self.bt_strategy_combo.setEnabled(True)

        if test_type == "Event-Driven Backtest":
            self.bt_strategy_combo.addItem("N/A (Вся система)")
            self.bt_strategy_combo.setEnabled(False)
        elif test_type == "Системный бэктест (Экосистема)":
            self.bt_strategy_combo.addItem("N/A (система решает сама)")
            self.bt_strategy_combo.setEnabled(False)
        elif test_type == "Классическая стратегия":
            strategy_loader = StrategyLoader(self.trading_system.config)
            strategies = strategy_loader.load_strategies()
            if not strategies:
                self.bt_strategy_combo.addItem("Стратегии не найдены")
            else:
                for s in strategies:
                    self.bt_strategy_combo.addItem(s.__class__.__name__)
        elif test_type == "AI Модель":
            all_models = self.trading_system.get_all_models()
            pytorch_models = [m for m in all_models if "PyTorch" in m.get("type", "")]
            if not pytorch_models:
                self.bt_strategy_combo.addItem("Нет совместимых PyTorch моделей")
                self.bt_strategy_combo.setEnabled(False)
            else:
                for model in pytorch_models:
                    status = model.get("status", "N/A")
                    item_text = f"ID: {model.get('id')} - {model.get('symbol')} - {model.get('type')} ({status})"
                    self.bt_strategy_combo.addItem(item_text)

    def on_kg_toggle(self: MainWindow):
        is_checked = self.kg_enabled_checkbox.isChecked()
        if hasattr(self, "trading_system") and hasattr(self.trading_system.core_system, "toggle_knowledge_graph"):
            self.trading_system.core_system.toggle_knowledge_graph(is_checked)
        if hasattr(self, "knowledge_graph_view") and hasattr(self, "kg_disabled_label"):
            self.knowledge_graph_view.setVisible(is_checked)
            self.kg_disabled_label.setVisible(not is_checked)

    def on_tab_changed(self: MainWindow, index):
        tab_widget = self.sender()
        tab_name = tab_widget.tabText(index)
        logger.debug(f"[GUI-Tab-Right] Переключение на вкладку: '{tab_name}' (индекс {index})")
        try:
            current_widget = tab_widget.widget(index)
            if current_widget:
                logger.debug(f"[GUI-Tab-Right] Виджет вкладки '{tab_name}' загружен: {type(current_widget).__name__}")
        except Exception as e:
            logger.error(f"[GUI-Tab-Right] Ошибка при переключении на вкладку '{tab_name}': {e}", exc_info=True)

    def on_left_tab_changed(self: MainWindow, index, tab_widget: QTabWidget):
        tab_name = tab_widget.tabText(index)
        logger.debug(f"[GUI-Tab-Left] Переключение на вкладку: '{tab_name}' (индекс {index})")

    def update_pnl_kpis(self: MainWindow, kpis: dict):
        def format_pnl(value):
            color = "#50fa7b" if value >= 0 else "#ff5555"
            return f"<span style='font-weight: bold; color:{color}'>{value:+.2f}</span>"

        def format_dd(value):
            color = "#ff5555"
            return f"<span style='font-weight: bold; color:{color}'>{value:.2f}%</span>"

        self.pnl_day_label.setText(format_pnl(kpis.get("day_pnl", 0)))
        self.pnl_week_label.setText(format_pnl(kpis.get("week_pnl", 0)))
        self.pnl_month_label.setText(format_pnl(kpis.get("month_pnl", 0)))
        self.dd_day_label.setText(format_dd(kpis.get("day_dd", 0)))
        self.dd_week_label.setText(format_dd(kpis.get("week_dd", 0)))
        self.dd_month_label.setText(format_dd(kpis.get("month_dd", 0)))

    def _refresh_vector_db_stats(self: MainWindow):
        logger.info("[VectorDB-GUI] Запрос статистики VectorDB")
        if hasattr(self.trading_system, "get_vector_db_stats"):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    future = asyncio.ensure_future(self.trading_system.get_vector_db_stats())
                    future.add_done_callback(self._on_vector_db_stats)
                    return
                else:
                    stats = loop.run_until_complete(self.trading_system.get_vector_db_stats())
            except RuntimeError:
                stats = {}
            if not stats:
                stats = {}
            count = stats.get("count", 0)
            ready = stats.get("is_ready", False)
            has_embedding = stats.get("has_embedding_model", False)
            reason = stats.get("reason", "")

            self.vdb_count_label.setText(f"Документов в индексе: {count}")

            if ready:
                status_text = "АКТИВНА"
                color = "#50fa7b"
            elif reason:
                status_text = f"ОШИБКА: {reason}"
                color = "#ff5555"
            elif not has_embedding:
                status_text = "НЕТ EMBEDDING МОДЕЛИ"
                color = "#ff5555"
            else:
                status_text = "НЕ ГОТОВА"
                color = "#ff5555"

            self.vdb_status_label.setText(f"Статус: {status_text}")
            self.vdb_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _on_vector_db_stats(self: MainWindow, future):
        try:
            stats = future.result()
            count = stats.get("count", 0)
            ready = stats.get("is_ready", False)
            has_embedding = stats.get("has_embedding_model", False)
            reason = stats.get("reason", "")
            self.vdb_count_label.setText(f"Документов в индексе: {count}")
            if ready:
                status_text, color = "АКТИВНА", "#50fa7b"
            elif reason:
                status_text, color = f"ОШИБКА: {reason}", "#ff5555"
            elif not has_embedding:
                status_text, color = "НЕТ EMBEDDING МОДЕЛИ", "#ff5555"
            else:
                status_text, color = "НЕ ГОТОВА", "#ff5555"
            self.vdb_status_label.setText(f"Статус: {status_text}")
            self.vdb_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        except Exception as e:
            logger.error(f"VectorDB stats error: {e}")

    def _run_vector_db_search(self: MainWindow):
        query = self.vdb_query_edit.text().strip()
        if not query:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Внимание", "Введите поисковый запрос.")
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")
            return

        logger.info(f"[VectorDB-GUI] Запуск поиска: '{query}'")

        if not hasattr(self.trading_system, "search_vector_db"):
            logger.error("[VectorDB-GUI] Метод search_vector_db не найден в trading_system")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Ошибка", "Система VectorDB не инициализирована")
            return

        self.vdb_search_button.setEnabled(False)
        self.vdb_search_button.setText("Поиск...")
        self.vdb_results_table.setRowCount(0)

        try:
            self.trading_system.search_vector_db(query)
        except Exception as e:
            logger.error(f"[VectorDB-GUI] Ошибка при вызове search_vector_db: {e}", exc_info=True)
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Ошибка", f"Ошибка при запуске поиска: {e}")
            return

        QTimer.singleShot(10000, self._restore_search_button)

    def _restore_search_button(self: MainWindow):
        if not self.vdb_search_button.isEnabled():
            logger.warning("[VectorDB-GUI] Таймаут поиска - восстановление кнопки")
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")

    def _display_vector_db_results(self: MainWindow, results: list):
        try:
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")

            if not results:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Результат", "Результаты не получены.")
                return

            if "error" in results[0]:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Ошибка поиска", results[0]["error"])
                return

            if "message" in results[0]:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Результат", results[0]["message"])
                return

            self.vdb_results_table.setRowCount(len(results))
            for i, res in enumerate(results):
                dist_val = float(res.get("distance", 0))
                self.vdb_results_table.setItem(i, 0, QTableWidgetItem(f"{dist_val:.4f}"))
                self.vdb_results_table.setItem(i, 1, QTableWidgetItem(res.get("source", "N/A")))

                ts = res.get("timestamp", "N/A")
                if "T" in ts:
                    ts = ts.split("T")[0]
                self.vdb_results_table.setItem(i, 2, QTableWidgetItem(ts))

                snippet = res.get("snippet", "Нет текста")
                item_text = QTableWidgetItem(snippet)
                item_text.setToolTip(res.get("full_text", snippet))
                self.vdb_results_table.setItem(i, 3, item_text)

        except Exception as e:
            logger.error(f"[VectorDB-GUI] Ошибка при отображении результатов: {e}", exc_info=True)
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Ошибка", f"Ошибка при отображении результатов: {e}")
