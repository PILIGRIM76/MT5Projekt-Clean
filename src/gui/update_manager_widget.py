#!/usr/bin/env python3
"""
Виджет управления обновлениями для Genesis Trading System.
Позволяет проверять и применять обновления без перезапуска.
"""

import logging
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class UpdateManagerWidget(QWidget):
    """
    Виджет для управления горячими обновлениями.

    Показывает:
    - Текущую версию (коммит)
    - Статус мониторинга
    - Кнопки проверки и применения обновлений
    """

    # Сигналы
    check_updates_requested = Signal()
    apply_update_requested = Signal()
    toggle_monitoring_requested = Signal()

    def __init__(self, trading_system=None, parent=None):
        super().__init__(parent)
        self.trading_system = trading_system
        self.update_status_label = None
        self.current_version_label = None
        self.monitoring_status_label = None
        self.check_updates_button = None
        self.apply_update_button = None
        self.toggle_monitoring_button = None
        self.last_check_label = None

        self._init_ui()
        self._start_status_timer()

    def _init_ui(self):
        """Инициализация UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Заголовок
        title = QLabel("🔄 Управление обновлениями")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # Фрейм статуса
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        status_layout = QVBoxLayout(status_frame)

        # Текущая версия
        version_layout = QHBoxLayout()
        version_layout.addWidget(QLabel("📦 Текущая версия:"))
        self.current_version_label = QLabel("Загрузка...")
        self.current_version_label.setFont(QFont("Consolas", 10))
        self.current_version_label.setStyleSheet("color: #50fa7b;")
        version_layout.addWidget(self.current_version_label)
        status_layout.addLayout(version_layout)

        # Статус обновления
        update_status_layout = QHBoxLayout()
        update_status_layout.addWidget(QLabel("📢 Статус:"))
        self.update_status_label = QLabel("Нет обновлений")
        self.update_status_label.setFont(QFont("Arial", 10))
        self.update_status_label.setStyleSheet("color: #f8f8f2;")
        update_status_layout.addWidget(self.update_status_label)
        status_layout.addLayout(update_status_layout)

        # Статус мониторинга
        monitoring_layout = QHBoxLayout()
        monitoring_layout.addWidget(QLabel("👁️ Мониторинг:"))
        self.monitoring_status_label = QLabel("Не активен")
        self.monitoring_status_label.setFont(QFont("Arial", 10))
        self.monitoring_status_label.setStyleSheet("color: #ffb86c;")
        monitoring_layout.addWidget(self.monitoring_status_label)
        status_layout.addLayout(monitoring_layout)

        # Последняя проверка
        last_check_layout = QHBoxLayout()
        last_check_layout.addWidget(QLabel("⏰ Последняя проверка:"))
        self.last_check_label = QLabel("Н/Д")
        self.last_check_label.setFont(QFont("Arial", 9))
        self.last_check_label.setStyleSheet("color: #888;")
        last_check_layout.addWidget(self.last_check_label)
        status_layout.addLayout(last_check_layout)

        main_layout.addWidget(status_frame)

        # Кнопки управления
        buttons_layout = QVBoxLayout()

        # Кнопка проверки обновлений
        self.check_updates_button = QPushButton("🔍 Проверить обновления")
        self.check_updates_button.clicked.connect(self._on_check_updates)
        self.check_updates_button.setStyleSheet("""
            QPushButton {
                background-color: #44475a;
                color: #f8f8f2;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6272a4;
            }
            QPushButton:pressed {
                background-color: #44475a;
            }
        """)
        buttons_layout.addWidget(self.check_updates_button)

        # Кнопка применения обновления
        self.apply_update_button = QPushButton("⬇️ Применить обновление")
        self.apply_update_button.clicked.connect(self._on_apply_update)
        self.apply_update_button.setEnabled(False)
        self.apply_update_button.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #282a36;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #69ff94;
            }
            QPushButton:pressed {
                background-color: #50fa7b;
            }
            QPushButton:disabled {
                background-color: #44475a;
                color: #6272a4;
            }
        """)
        buttons_layout.addWidget(self.apply_update_button)

        # Кнопка включения/выключения мониторинга
        self.toggle_monitoring_button = QPushButton("▶️ Включить мониторинг")
        self.toggle_monitoring_button.clicked.connect(self._on_toggle_monitoring)
        self.toggle_monitoring_button.setStyleSheet("""
            QPushButton {
                background-color: #bd93f9;
                color: #f8f8f2;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d6acff;
            }
            QPushButton:pressed {
                background-color: #bd93f9;
            }
        """)
        buttons_layout.addWidget(self.toggle_monitoring_button)

        main_layout.addLayout(buttons_layout)

        # Растяжка
        main_layout.addStretch()

    def _start_status_timer(self):
        """Запуск таймера обновления статуса."""
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(5000)  # Обновление каждые 5 секунд

    def _update_status(self):
        """Обновление статуса."""
        if not self.trading_system:
            return

        # Получаем hot_reload_manager через core_system
        manager = None
        if hasattr(self.trading_system, "core_system") and self.trading_system.core_system:
            manager = self.trading_system.core_system.hot_reload_manager
        elif hasattr(self.trading_system, "hot_reload_manager"):
            manager = self.trading_system.hot_reload_manager

        if not manager:
            return

        try:
            status = manager.get_update_status()

            # Обновляем текущую версию
            if status.get("local_commit"):
                short_commit = status["local_commit"][:8]
                self.current_version_label.setText(short_commit)

            # Обновляем статус мониторинга
            if status.get("monitoring"):
                self.monitoring_status_label.setText("✅ Активен")
                self.monitoring_status_label.setStyleSheet("color: #50fa7b;")
                self.toggle_monitoring_button.setText("⏹️ Выключить мониторинг")
            else:
                self.monitoring_status_label.setText("❌ Не активен")
                self.monitoring_status_label.setStyleSheet("color: #ff5555;")
                self.toggle_monitoring_button.setText("▶️ Включить мониторинг")

            # Обновляем время последней проверки
            if status.get("last_check"):
                last_check = datetime.fromtimestamp(status["last_check"])
                self.last_check_label.setText(last_check.strftime("%H:%M:%S"))
            else:
                self.last_check_label.setText("Н/Д")

            # Проверяем наличие обновлений
            if status.get("has_updates"):
                self.update_status_label.setText("🔔 Доступна новая версия!")
                self.update_status_label.setStyleSheet("color: #ffb86c; font-weight: bold;")
                self.apply_update_button.setEnabled(True)
            else:
                self.update_status_label.setText("✅ Нет обновлений")
                self.update_status_label.setStyleSheet("color: #50fa7b;")
                self.apply_update_button.setEnabled(False)

        except Exception as e:
            logger.error(f"[UpdateManager] Ошибка: {e}")

    def _on_check_updates(self):
        """Обработчик кнопки проверки обновлений."""
        logger.info("🔍 Запрос проверки обновлений")
        self.check_updates_requested.emit()

        # Показываем индикатор загрузки
        self.check_updates_button.setText("⏳ Проверка...")
        self.check_updates_button.setEnabled(False)

        # Возвращаем кнопку через 2 секунды
        QTimer.singleShot(2000, lambda: self.check_updates_button.setText("🔍 Проверить обновления"))
        QTimer.singleShot(2000, lambda: self.check_updates_button.setEnabled(True))

    def _on_apply_update(self):
        """Обработчик кнопки применения обновления."""
        logger.info("⬇️ Запрос применения обновления")

        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Подтверждение обновления",
            "Применить обновление системы?\n\n"
            "• Будут загружены последние изменения из GitHub\n"
            "• Модули будут перезагружены\n"
            "• Активные позиции НЕ будут затронуты\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.apply_update_requested.emit()
            self.apply_update_button.setText("⏳ Применение...")
            self.apply_update_button.setEnabled(False)

    def _on_toggle_monitoring(self):
        """Обработчик кнопки переключения мониторинга."""
        logger.info("🔄 Запрос переключения мониторинга")
        self.toggle_monitoring_requested.emit()

    def set_update_status(self, message: str, color: str = "#f8f8f2"):
        """Установка статуса обновления."""
        self.update_status_label.setText(message)
        self.update_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def set_current_version(self, version: str):
        """Установка текущей версии."""
        self.current_version_label.setText(version)
