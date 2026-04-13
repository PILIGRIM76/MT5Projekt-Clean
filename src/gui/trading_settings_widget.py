# src/gui/trading_settings_widget.py
"""
Виджет настроек торговли - первая боковая вкладка.

Содержит:
- Режимы торговли
- Текущие параметры
- Кнопка открытия настроек
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class TradingSettingsWidget(QWidget):
    """Виджет настроек торговли с информацией о режимах и текущих параметрах."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Группа настроек торговли
        trading_group = QGroupBox("⚙️ Параметры Торговли")
        trading_layout = QVBoxLayout()

        # Режимы торговли
        mode_label = QLabel("**Режимы торговли:**")
        mode_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #f8f8f2;")
        trading_layout.addWidget(mode_label)

        modes_info = QLabel("""
        • 🟢 **Консервативный** - минимальный риск
        • 🟡 **Стандартный** - баланс риск/доходность
        • 🔴 **Агрессивный** - высокий риск
        • ⚫ **YOLO** - максимальный риск
        • 🔧 **Кастомный** - ручная настройка
        """)
        modes_info.setWordWrap(True)
        modes_info.setStyleSheet("color: #f8f8f2; padding: 5px;")
        trading_layout.addWidget(modes_info)

        # Кнопка открытия настроек
        open_settings_btn = QPushButton("⚙️ Открыть Настройки Торговли")
        open_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #bd93f9;
                color: #282a36;
                padding: 12px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #a37df5;
            }
            QPushButton:pressed {
                background-color: #8e44ad;
            }
        """)
        open_settings_btn.clicked.connect(self._open_settings_requested)
        trading_layout.addWidget(open_settings_btn)

        trading_group.setLayout(trading_layout)
        layout.addWidget(trading_group)

        # Текущие параметры
        params_group = QGroupBox("📊 Текущие Параметры")
        params_layout = QVBoxLayout()

        self.params_info = QLabel("""
        **Риск на сделку:** 0.50%
        **Max позиций:** 5
        **Max дневная просадка:** 5.00%
        **Активный режим:** 🟡 Стандартный
        """)
        self.params_info.setStyleSheet(
            "font-family: monospace; font-size: 13px; color: #f8f8f2; padding: 10px; background-color: #282a36; border-radius: 5px;"
        )
        self.params_info.setWordWrap(True)
        params_layout.addWidget(self.params_info)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        layout.addStretch()

    def update_current_params(self, risk: float, max_positions: int, max_drawdown: float, mode: str):
        """Обновляет текущие параметры торговли."""
        mode_emoji = {"conservative": "🟢", "standard": "🟡", "aggressive": "🔴", "yolo": "⚫", "custom": "🔧"}.get(mode, "🟡")
        mode_name = {
            "conservative": "Консервативный",
            "standard": "Стандартный",
            "aggressive": "Агрессивный",
            "yolo": "YOLO",
            "custom": "Кастомный",
        }.get(mode, "Стандартный")

        self.params_info.setText(f"""
        **Риск на сделку:** {risk:.2f}%
        **Max позиций:** {max_positions}
        **Max дневная просадка:** {max_drawdown:.2f}%
        **Активный режим:** {mode_emoji} {mode_name}
        """)
        logger.info(f"[TradingSettings] Параметры обновлены: risk={risk}%, mode={mode_name}")

    def _open_settings_requested(self):
        """Сигнал для открытия окна настроек."""
        parent = self.parent()
        while parent:
            if hasattr(parent, "open_settings_window"):
                parent.open_settings_window()
                return
            if hasattr(parent, "parent") and callable(parent.parent):
                parent = parent.parent()
            else:
                break

        logger.warning("[TradingSettings] Не удалось найти метод open_settings_window()")
