# -*- coding: utf-8 -*-
"""
src/gui/main_window.py — Главный MainWindow Genesis Trading System

Ответственность:
- Сборка UI из панелей
- Обработка сигналов от торговой системы
- Координация между виджетами

НЕ должен содержать:
- Бизнес-логику
- Прямые вызовы MT5
- Тяжёлые вычисления
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from PySide6.QtCore import QEvent, Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.config_models import Settings
from src.gui.log_utils import setup_qt_logging
from src.gui.settings_window import SettingsWindow
from src.gui.sound_manager import SoundManager
from src.gui.styles import DARK_STYLE, LIGHT_STYLE
from src.gui.widgets import Bridge, GUIBridge
from src.gui.widgets.defi_widget import DeFiWidget
from src.utils.scheduler_manager import SchedulerManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Главное окно Genesis Trading System."""

    def __init__(self, trading_system_adapter, config: Settings):
        super().__init__()
        self.setWindowTitle("Genesis v24.0: Reflexive Core")

        logger.info("=== НАЧАЛО ИНИЦИАЛИЗАЦИИ MainWindow ===")

        # --- Основные объекты ---
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(10)
        logger.info(f"QThreadPool инициализирован с макс. {self.threadpool.maxThreadCount()} потоками.")

        self.config = config
        self.trading_system = trading_system_adapter
        self.bridge = self.trading_system.bridge
        self.sound_manager = self.trading_system.core_system.sound_manager
        self.chart_trade_history = []
        self.temp_html_file = None

        self.drift_data_points = []
        self.drift_alert_points = []

        # Словари для статусов
        self.thread_status_labels: Dict[str, QLabel] = {}
        self.scheduler_status_labels: Dict[str, QLabel] = {}

        # --- Иконка ---
        project_root = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(project_root, "..", "assets", "icon.ico.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logger.warning(f"Файл иконки не найден по пути: {icon_path}")

        # --- Панель уведомлений ---
        self.notification_bar = QFrame()
        self.notification_bar.setObjectName("NotificationBar")
        self.notification_bar.setLayout(QHBoxLayout())
        self.notification_label = QLabel("")
        self.notification_bar.layout().addWidget(self.notification_label)
        self.notification_bar.setVisible(False)

        self.notification_timer = QTimer(self)
        self.notification_timer.setSingleShot(True)
        self.notification_timer.timeout.connect(lambda: self.notification_bar.setVisible(False))

        # --- Состояние ---
        self.is_graph_ready = False
        self.graph_data_queue = []
        self.scheduler_manager = SchedulerManager()
        self.settings_window = SettingsWindow(self.scheduler_manager, self.config, self)
        self.settings_window.scheduler_status_updated.connect(self.update_thread_status_widget)

        self.setGeometry(100, 100, 1600, 900)

        # --- Временный виджет загрузки ---
        self.loading_label = QLabel("Загрузка ядра Genesis v24.0... Пожалуйста, подождите (AI, DB, NLP).")
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.addWidget(self.loading_label)
        self.setCentralWidget(self.loading_widget)

        # --- Лёгкая инициализация GUI ---
        self._init_widgets()
        self.connect_signals()
        self.apply_style("Темная")

        # Таймер статуса
        self.status_update_timer = QTimer(self)
        self.status_update_timer.timeout.connect(self.update_scheduler_status_display)
        self.status_update_timer.start(60 * 1000)

        self.update_scheduler_status_display()
        self.kg_enabled_checkbox.setChecked(self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION)
        self.on_kg_toggle()

        # --- Тяжёлая инициализация в фоне ---
        self.start_heavy_initialization()

    # ========================================================================
    # Уведомления
    # ========================================================================

    def show_notification(self, message: str, duration_ms: int = 3000):
        """Отображает уведомление в нижней панели."""
        self.notification_label.setText(message)
        self.notification_bar.setVisible(True)
        if duration_ms > 0:
            self.notification_timer.start(duration_ms)
        else:
            self.notification_timer.stop()

    # ========================================================================
    # Инициализация
    # ========================================================================

    def start_heavy_initialization(self):
        """Запускает тяжёлую инициализацию в фоновом потоке."""
        from PySide6.QtCore import QObject, QRunnable, Signal

        class InitWorker(QRunnable):
            def __init__(self, callback, error_callback):
                super().__init__()
                self.callback = callback
                self.error_callback = error_callback

            def run(self):
                try:
                    result = self._do_work()
                    QTimer.singleShot(0, lambda: self.callback(result))
                except Exception as e:
                    import traceback

                    error_info = (type(e), e, traceback.format_exc())
                    QTimer.singleShot(0, lambda: self.error_callback(error_info))

            def _do_work(self):
                logger.info("Начало тяжелой инициализации компонентов (DB, AI, NLP)...")
                self.callback.__self__.trading_system.core_system.initialize_heavy_components()
                logger.info("Тяжелая инициализация завершена.")
                logger.info("Начало запуска всех фоновых сервисов...")
                self.callback.__self__.trading_system.start_all_background_services(self.callback.__self__.threadpool)
                logger.info("Все фоновые сервисы запущены.")
                return True

        worker = InitWorker(
            self.on_heavy_initialization_finished,
            self.on_heavy_initialization_error,
        )
        self.threadpool.start(worker)

    @Slot(object)
    def on_heavy_initialization_finished(self, result):
        """Слот после успешной инициализации."""
        logger.info("Система Genesis v24.0 полностью активна. Переключение на основной GUI.")
        self.setCentralWidget(self.main_central_widget)

        self.status_update_timer = QTimer(self)
        self.status_update_timer.timeout.connect(self.update_scheduler_status_display)
        self.status_update_timer.start(60 * 1000)
        self.update_scheduler_status_display()
        self.kg_enabled_checkbox.setChecked(self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION)
        self.on_kg_toggle()

        if hasattr(self, "defi_widget") and hasattr(self.core_system, "db_manager"):
            logger.info("[DeFi] Подключение к БД...")
            self.defi_widget.set_db_manager(self.core_system.db_manager)

        if hasattr(self, "control_center_tab"):
            self.control_center_tab.load_initial_settings()

        self.show_notification("Система Genesis v24.0 полностью активна.", 5000)

    @Slot(tuple)
    def on_heavy_initialization_error(self, error_info):
        """Слот для обработки ошибок инициализации."""
        exctype, value, traceback_str = error_info
        logger.critical(f"Критическая ошибка при запуске сервисов: {value}\n{traceback_str}")
        self.show_notification(f"КРИТИЧЕСКАЯ ОШИБКА: {value}", 0)
        self.loading_label.setText(f"КРИТИЧЕСКАЯ ОШИБКА: {value}. См. логи.")
        self.loading_label.setStyleSheet("color: red;")
