# src/gui/risk_management_widget.py
"""
Прокручиваемый виджет управления рисками - третья вкладка.

Содержит:
- Параметры позиционирования
- Лимиты просадки
- Динамическое управление
- Меры безопасности
- Быстрые действия
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class RiskManagementWidget(QWidget):
    """Прокручиваемый виджет управления рисками."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Создаем прокручиваемую область
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background: #34495e;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #bd93f9;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: #282a36;
            }
        """)

        # Виджет содержимого
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        scroll_layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        header_label = QLabel("🛡️ Управление Рисками")
        header_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #ff5555;
                padding: 15px;
                background-color: #282a36;
                border-radius: 10px;
            }
        """)
        scroll_layout.addWidget(header_label)

        # Группы параметров риска
        risk_groups = [
            (
                "💰 Параметры Позиционирования",
                [
                    "Размер позиции (% от депозита)",
                    "Максимальное количество позиций",
                    "Минимальный интервал между сделками",
                    "Коэффициент масштабирования риска",
                ],
            ),
            (
                "📉 Лимиты Просадки",
                [
                    "Максимальная дневная просадка (%)",
                    "Максимальная недельная просадка (%)",
                    "Максимальная месячная просадка (%)",
                    "Аварийная остановка при просадке",
                ],
            ),
            (
                "⚡ Динамическое Управление",
                [
                    "Адаптация размера позиции к волатильности",
                    "Корректировка стоп-лоссов",
                    "Динамический тейк-профит",
                    "Trailing Stop настройки",
                ],
            ),
            (
                "🔒 Меры Безопасности",
                [
                    "Circuit Breaker активация",
                    "Максимальный спред для входа",
                    "Ограничение торговли в новости",
                    "Блокировка при аномалиях рынка",
                ],
            ),
        ]

        for title, items in risk_groups:
            group = self._create_risk_group(title, items)
            scroll_layout.addWidget(group)

        # Кнопки действий
        actions_group = QGroupBox("⚡ Быстрые Действия")
        actions_layout = QHBoxLayout()

        reset_btn = QPushButton("🔄 Сбросить Настройки")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #6272a4;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)

        export_btn = QPushButton("📁 Экспорт Настроек")
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)

        import_btn = QPushButton("📂 Импорт Настроек")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #bd93f9;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        """)

        actions_layout.addWidget(reset_btn)
        actions_layout.addWidget(export_btn)
        actions_layout.addWidget(import_btn)

        actions_group.setLayout(actions_layout)
        scroll_layout.addWidget(actions_group)

        scroll_layout.addStretch()

        # Устанавливаем виджет в scroll area
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

    def _create_risk_group(self, title: str, items: list) -> QGroupBox:
        """Создает группу параметров риска."""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #f8f8f2;
                border: 2px solid #6272a4;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(8)

        for item in items:
            item_label = QLabel(f"• {item}")
            item_label.setWordWrap(True)
            item_label.setStyleSheet("padding: 5px 0; color: #f8f8f2; font-size: 13px;")
            layout.addWidget(item_label)

        group.setLayout(layout)
        return group
