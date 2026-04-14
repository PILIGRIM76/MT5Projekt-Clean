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
from src.gui.animation_manager import AnimationManager
from src.gui.custom_title_bar import CustomTitleBar
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
        self.sound_manager = getattr(self.trading_system, "sound_manager", None)
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
        self.settings_window.theme_preview_requested.connect(self._on_theme_preview_requested)

        self.setGeometry(100, 100, 1600, 900)

        # --- Менеджер анимаций ---
        self.animation_manager = AnimationManager(cpu_monitor=self._get_cpu_percent)
        logger.info("[MainWindow] AnimationManager инициализирован")

        # --- Always on Top (из конфига) ---
        self._always_on_top = getattr(config, "ALWAYS_ON_TOP", False)
        if self._always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            logger.info("[MainWindow] Always on Top включён")

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

    def show_notification(
        self,
        message: str,
        duration_ms: int = 3000,
        level: str = "info",  # info, success, warning, error
    ):
        """
        Отображает уведомление в нижней панели с анимацией.

        Args:
            message: Текст уведомления
            duration_ms: Время показа (мс)
            level: Уровень (info/success/warning/error)
        """
        self.notification_label.setText(message)

        # Стилизация по уровню
        self.notification_bar.setObjectName("NotificationBar")
        level_styles = {
            "success": ("#ECFDF5", "#065F46", "#A7F3D0"),
            "warning": ("#FFFBEB", "#92400E", "#FDE68A"),
            "error": ("#FEF2F2", "#991B1B", "#FECACA"),
            "info": ("#EFF6FF", "#1E40AF", "#BFDBFE"),
        }
        bg_color, text_color, border_color = level_styles.get(level, level_styles["info"])
        self.notification_bar.setStyleSheet(
            f"background-color: {bg_color}; border: 1px solid {border_color}; " f"border-radius: 6px; padding: 4px;"
        )
        self.notification_label.setStyleSheet(f"color: {text_color}; font-weight: 500; padding: 4px 12px;")

        # Показываем с анимацией
        if self.animation_manager.enabled:
            self.animation_manager.animate_notification(
                self.notification_bar,
                show_duration=AnimationManager.DURATION_NOTIFICATION,
                auto_hide_ms=duration_ms,
            )
        else:
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
                # Новая архитектура: heavy инициализация через адаптер
                ts = self.callback.__self__.trading_system
                if hasattr(ts, "initialize_heavy_components"):
                    ts.initialize_heavy_components()
                logger.info("Тяжелая инициализация завершена.")
                logger.info("Начало запуска всех фоновых сервисов...")
                # Запуск через адаптер
                if hasattr(ts, "start_all_background_services"):
                    ts.start_all_background_services(self.callback.__self__.threadpool)
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

        if hasattr(self, "defi_widget"):
            logger.info("[DeFi] Подключение к БД...")
            db_mgr = getattr(self.trading_system, "db_manager", None)
            if db_mgr:
                self.defi_widget.set_db_manager(db_mgr)

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

    # ========================================================================
    # CPU мониторинг для AnimationManager
    # ========================================================================

    def _get_cpu_percent(self) -> float:
        """Возвращает текущую загрузку CPU в процентах."""
        try:
            import psutil

            return psutil.cpu_percent(interval=0.1)
        except Exception:
            # Fallback: читаем из /proc/stat на Linux или используем 0
            try:
                import os

                if hasattr(os, "getloadavg"):
                    load1, _, _ = os.getloadavg()
                    import multiprocessing

                    cpu_count = multiprocessing.cpu_count()
                    return min(100.0, (load1 / cpu_count) * 100.0)
            except Exception:
                pass
            return 0.0

    # ========================================================================
    # Кастомная рамка окна (Title Bar)
    # ========================================================================

    def setup_custom_title_bar(self) -> None:
        """
        Устанавливает кастомную рамку окна.
        Вызывать ПОСЛЕ show() или в конце инициализации.
        """
        # Проверяем, есть ли уже title bar
        if hasattr(self, "_custom_title_bar"):
            return

        # Убираем системную рамку
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # Создаём кастомный title bar
        self._custom_title_bar = CustomTitleBar(
            title="Genesis v24.0: Reflexive Core",
            parent=self,
        )

        # Подключаем сигналы
        self._custom_title_bar.minimize_requested.connect(self.showMinimized)
        self._custom_title_bar.maximize_requested.connect(self._toggle_maximize)
        self._custom_title_bar.close_requested.connect(self.close)

        # Обновляем заголовок при изменении состояния окна
        self._custom_title_bar.attach_to_window(self)

        logger.info("[MainWindow] Кастомная рамка окна установлена")

    def _toggle_maximize(self) -> None:
        """Переключает режим развернуть/восстановить."""
        if self.isMaximized():
            self.showNormal()
            if hasattr(self, "_custom_title_bar"):
                self._custom_title_bar.max_btn.setText("□")
                self._custom_title_bar.max_btn.setToolTip("Развернуть")
        else:
            self.showMaximized()
            if hasattr(self, "_custom_title_bar"):
                self._custom_title_bar.max_btn.setText("❐")
                self._custom_title_bar.max_btn.setToolTip("Восстановить")

    # ========================================================================
    # Always on Top — переключение
    # ========================================================================

    def toggle_always_on_top(self) -> None:
        """Переключает режим Always on Top."""
        self._always_on_top = not self._always_on_top
        if self._always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            logger.info("[MainWindow] Always on Top ВКЛЮЧЁН")
        else:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            logger.info("[MainWindow] Always on Top ОТКЛЮЧЁН")
        # Перерисовка окна
        self.show()

    def set_always_on_top(self, enabled: bool) -> None:
        """Устанавливает режим Always on Top."""
        if self._always_on_top == enabled:
            return
        self.toggle_always_on_top()

    # ========================================================================
    # Предпросмотр темы из настроек
    # ========================================================================

    @Slot(str)
    def _on_theme_preview_requested(self, theme_name: str) -> None:
        """Применяет выбранную тему в режиме предпросмотра."""
        logger.info(f"[MainWindow] Предпросмотр темы: {theme_name}")
        self.apply_style(theme_name)
