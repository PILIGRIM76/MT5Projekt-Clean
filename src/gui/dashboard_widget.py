# src/gui/dashboard_widget.py
"""
Modern Dashboard Widget для Genesis Trading System
Отображение ключевых метрик, графиков и статуса системы.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ModernDashboardWidget(QWidget):
    """
    Современный дашборд с метриками, графиками и таблицами.
    Все обновления защищены try-except для предотвращения крашей GUI.
    """

    def __init__(self, event_bus=None, parent=None):
        super().__init__(parent)
        self.event_bus = event_bus
        self.setObjectName("ModernDashboardWidget")

        # Данные для отображения
        self.balance = 10000.0
        self.equity = 10000.0
        self.profit = 0.0
        self.positions = []
        self.signals = []

        # Инициализация таймера с parent=self для корректной очистки
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_dashboard_data)
        self.update_timer.start(1000)  # Обновление каждую секунду

        logger.info("ModernDashboardWidget initialized")

        # Создание UI
        self._init_ui()

    def _init_ui(self):
        """Инициализация пользовательского интерфейса"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # 1. Верхняя панель с ключевыми метриками
        metrics_frame = self._create_metrics_frame()
        main_layout.addWidget(metrics_frame)

        # 2. График баланса
        chart_frame = self._create_chart_frame()
        main_layout.addWidget(chart_frame)

        # 3. Таблица позиций
        positions_frame = self._create_positions_frame()
        main_layout.addWidget(positions_frame)

        # 4. Статус системы
        status_frame = self._create_status_frame()
        main_layout.addWidget(status_frame)

    def _create_metrics_frame(self) -> QFrame:
        """Создание фрейма с ключевыми метриками"""
        frame = QFrame()
        frame.setObjectName("MetricsFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QGridLayout(frame)
        layout.setSpacing(10)

        # Метрики
        metrics = [
            ("balance", "Баланс", "$10,000.00", "#50fa7b"),
            ("equity", "Эквити", "$10,000.00", "#8be9fd"),
            ("profit", "Прибыль", "$0.00", "#f1fa8c"),
            ("drawdown", "Просадка", "0.00%", "#ff5555"),
            ("positions", "Позиции", "0", "#bd93f9"),
            ("win_rate", "Win Rate", "0%", "#ffb86c"),
        ]

        self.metric_labels = {}

        for i, (key, label, value, color) in enumerate(metrics):
            row = i // 3
            col = i % 3

            label_widget = QLabel(label)
            label_widget.setObjectName("MetricLabel")
            label_widget.setStyleSheet("font-size: 10pt; color: #888;")

            value_widget = QLabel(value)
            value_widget.setObjectName("MetricValue")
            value_widget.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {color};")

            layout.addWidget(label_widget, row, col * 2)
            layout.addWidget(value_widget, row, col * 2 + 1)

            self.metric_labels[key] = value_widget

        layout.setColumnStretch(5, 1)
        return frame

    def _create_chart_frame(self) -> QFrame:
        """Создание фрейма с графиком"""
        frame = QFrame()
        frame.setObjectName("ChartFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(frame)

        # График баланса
        self.balance_chart = pg.PlotWidget()
        self.balance_chart.setTitle("Баланс / Эквити", size="12pt")
        self.balance_chart.setLabels(left="Средства ($)", bottom="Время")
        self.balance_chart.showGrid(x=True, y=True, alpha=0.3)
        self.balance_chart.setBackground("#1e1e1e")
        # ❌ УДАЛЕНО: self.balance_chart.setPen(...) - этот метод не поддерживается PlotWidget

        # Инициализация данных графика
        self.balance_data_x = []
        self.balance_data_y = []
        self.balance_curve = self.balance_chart.plot([], [], pen=pg.mkPen("#50fa7b", width=2))

        layout.addWidget(self.balance_chart)
        return frame

    def _create_positions_frame(self) -> QFrame:
        """Создание фрейма с таблицей позиций"""
        frame = QFrame()
        frame.setObjectName("PositionsFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(frame)

        # Таблица позиций
        self.positions_table = QTableWidget()
        self.positions_table.setColumnCount(7)
        self.positions_table.setHorizontalHeaderLabels(["Символ", "Тип", "Объем", "Цена входа", "SL", "TP", "Прибыль"])
        self.positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.positions_table.setAlternatingRowColors(True)
        self.positions_table.setMaximumHeight(200)

        layout.addWidget(self.positions_table)
        return frame

    def _create_status_frame(self) -> QFrame:
        """Создание фрейма со статусом системы"""
        frame = QFrame()
        frame.setObjectName("StatusFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(frame)

        # Статус системы
        self.status_label = QLabel("● Статус: Остановлен")
        self.status_label.setStyleSheet("font-size: 12pt; color: #ff5555;")
        layout.addWidget(self.status_label)

        layout.addStretch()

        # Время работы
        self.uptime_label = QLabel("Время работы: 00:00:00")
        self.uptime_label.setStyleSheet("font-size: 10pt; color: #888;")
        layout.addWidget(self.uptime_label)

        return frame

    def _update_dashboard_data(self):
        """
        Периодическое обновление данных дашборда.
        Защищено try-except для предотвращения крашей GUI.
        """
        try:
            # Обновление метрик
            if hasattr(self, "metric_labels"):
                if "balance" in self.metric_labels:
                    self.metric_labels["balance"].setText(f"${self.balance:.2f}")
                if "equity" in self.metric_labels:
                    self.metric_labels["equity"].setText(f"${self.equity:.2f}")
                if "profit" in self.metric_labels:
                    profit_color = "#50fa7b" if self.profit >= 0 else "#ff5555"
                    self.metric_labels["profit"].setText(f"${self.profit:.2f}")
                    self.metric_labels["profit"].setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {profit_color};")

            # Обновление графика (добавление точки)
            if hasattr(self, "balance_curve"):
                now = datetime.now()
                self.balance_data_x.append(now)
                self.balance_data_y.append(self.equity)

                # Ограничиваем размер графика
                if len(self.balance_data_x) > 100:
                    self.balance_data_x = self.balance_data_x[-100:]
                    self.balance_data_y = self.balance_data_y[-100:]

                # Безопасное обновление графика
                try:
                    x_arr = np.asarray(self.balance_data_x, dtype=float) if self.balance_data_x else np.array([])
                    y_arr = np.asarray(self.balance_data_y, dtype=float) if self.balance_data_y else np.array([])
                    valid = np.isfinite(x_arr) & np.isfinite(y_arr)
                    if np.any(valid):
                        self.balance_curve.setData(x_arr[valid], y_arr[valid])
                    else:
                        self.balance_curve.setData([], [])
                except Exception as e:
                    logger.debug(f"📊 Plot update skipped (invalid data types): {e}")

            # Обновление таблицы позиций
            if hasattr(self, "positions_table") and hasattr(self, "positions"):
                self.positions_table.setRowCount(len(self.positions))
                for i, pos in enumerate(self.positions):
                    self.positions_table.setItem(i, 0, QTableWidgetItem(pos.get("symbol", "")))
                    self.positions_table.setItem(i, 1, QTableWidgetItem(pos.get("type", "")))
                    self.positions_table.setItem(i, 2, QTableWidgetItem(f"{pos.get('volume', 0):.2f}"))

            # Обновление статуса
            if hasattr(self, "status_label"):
                self.status_label.setText("● Статус: Активен")
                self.status_label.setStyleSheet("font-size: 12pt; color: #50fa7b;")

        except Exception as e:
            # Логирование ошибки без краша GUI
            logger.error(f"Dashboard update error: {e}", exc_info=True)
            # Не прерываем таймер — следующее обновление сработает

    def set_data(self, data: Dict):
        """
        Установка данных для отображения (вызывается извне)
        :param data: Словарь с данными (balance, equity, profit, positions, etc.)
        """
        try:
            self.balance = data.get("balance", self.balance)
            self.equity = data.get("equity", self.equity)
            self.profit = data.get("profit", self.profit)
            self.positions = data.get("positions", self.positions)
        except Exception as e:
            logger.error(f"Error setting dashboard data: {e}", exc_info=True)

    def set_status(self, running: bool):
        """Установка статуса системы"""
        try:
            if hasattr(self, "status_label"):
                if running:
                    self.status_label.setText("● Статус: Активен")
                    self.status_label.setStyleSheet("font-size: 12pt; color: #50fa7b;")
                else:
                    self.status_label.setText("● Статус: Остановлен")
                    self.status_label.setStyleSheet("font-size: 12pt; color: #ff5555;")
        except Exception as e:
            logger.error(f"Error setting status: {e}", exc_info=True)

    def closeEvent(self, event):
        """Корректное закрытие виджета"""
        try:
            # Останавливаем таймер
            if hasattr(self, "update_timer"):
                self.update_timer.stop()
        finally:
            event.accept()
