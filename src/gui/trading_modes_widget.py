"""
Виджет выбора режимов торговли.
Предоставляет предустановленные режимы риск-менеджмента.
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# Пресеты режимов торговли
TRADING_MODES = {
    "conservative": {
        "name": "Консервативный",
        "icon": "🟢",
        "risk_percentage": 0.25,
        "max_positions": 3,
        "max_daily_drawdown": 2.0,
        "stop_loss_atr_multiplier": 2.0,
        "risk_reward_ratio": 1.5,
        "enable_all_risk_checks": True,
        "description": "Минимальный риск, максимальная защита капитала",
        "color": "#27ae60",
    },
    "standard": {
        "name": "Стандартный",
        "icon": "🟡",
        "risk_percentage": 0.5,
        "max_positions": 10,
        "max_daily_drawdown": 5.0,
        "stop_loss_atr_multiplier": 3.0,
        "risk_reward_ratio": 2.5,
        "enable_all_risk_checks": True,
        "description": "Баланс между риском и доходностью",
        "color": "#f39c12",
    },
    "aggressive": {
        "name": "Агрессивный",
        "icon": "🔴",
        "risk_percentage": 2.0,
        "max_positions": 25,
        "max_daily_drawdown": 15.0,
        "stop_loss_atr_multiplier": 4.0,
        "risk_reward_ratio": 4.0,
        "enable_all_risk_checks": False,
        "description": "Высокий риск для максимальной прибыли",
        "color": "#e74c3c",
    },
    "yolo": {
        "name": "YOLO",
        "icon": "⚫",
        "risk_percentage": 10.0,
        "max_positions": 50,
        "max_daily_drawdown": 30.0,
        "stop_loss_atr_multiplier": 5.0,
        "risk_reward_ratio": 10.0,
        "enable_all_risk_checks": False,
        "requires_confirmation": True,
        "warning_message": "Вы готовы потерять ВЕСЬ депозит?",
        "description": "YOU ONLY LIVE ONCE - максимальный риск!",
        "color": "#2c3e50",
    },
}


class YoloConfirmationDialog(QDialog):
    """Диалог подтверждения для YOLO режима."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️ Подтверждение YOLO режима")
        self.setMinimumWidth(500)
        self.setModal(True)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        title = QLabel("⚠️ ВЫ ВЫБИРАЕТЕ YOLO РЕЖИМ!")
        title.setFont(QFont("Arial", 16, 70))  # 70 = QFont.Weight.Bold
        title.setStyleSheet("color: #e74c3c;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Предупреждение
        warning = QLabel("Вы готовы потерять весь депозит?\n" "Это деньги, которые не жалко?")
        warning.setFont(QFont("Arial", 12))
        warning.setStyleSheet("color: #c0392b; padding: 10px;")
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warning.setWordWrap(True)
        layout.addWidget(warning)

        # Список рисков
        risks_frame = QFrame()
        risks_frame.setStyleSheet("""
            QFrame {
                background-color: #fadbd8;
                border-radius: 10px;
                padding: 15px;
            }
        """)
        risks_layout = QVBoxLayout(risks_frame)

        risks = [
            "🔴 Высокая вероятность потери всего депозита",
            "🔴 Отсутствие защитных механизмов",
            "🔴 Максимальное кредитное плечо",
            "🔴 Возможность маржин-колла за минуты",
        ]

        for risk in risks:
            risk_label = QLabel(risk)
            risk_label.setStyleSheet("color: #c0392b; font-size: 11px;")
            risks_layout.addWidget(risk_label)

        layout.addWidget(risks_frame)

        # Чекбоксы
        self.checkbox1 = QCheckBox("Я понимаю все риски")
        self.checkbox1.setStyleSheet("font-size: 12px; padding: 5px;")
        layout.addWidget(self.checkbox1)

        self.checkbox2 = QCheckBox("Готов потерять 100% депозита")
        self.checkbox2.setStyleSheet("font-size: 12px; padding: 5px;")
        layout.addWidget(self.checkbox2)

        layout.addStretch()

        # Кнопки
        button_box = QDialogButtonBox()
        self.cancel_btn = QPushButton("❌ Отмена")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)

        self.confirm_btn = QPushButton("✅ Подтвердить")
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.confirm_btn.setEnabled(False)

        button_box.addButton(self.cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        button_box.addButton(self.confirm_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        layout.addWidget(button_box)

        # Сигналы
        self.checkbox1.stateChanged.connect(self.validate_checkboxes)
        self.checkbox2.stateChanged.connect(self.validate_checkboxes)
        self.cancel_btn.clicked.connect(self.reject)
        self.confirm_btn.clicked.connect(self.accept)

    def validate_checkboxes(self):
        """Проверка состояния чекбоксов."""
        enabled = self.checkbox1.isChecked() and self.checkbox2.isChecked()
        self.confirm_btn.setEnabled(enabled)


class ModeCard(QFrame):
    """Карточка режима торговли."""

    def __init__(self, mode_id: str, mode_data: dict, parent=None):
        super().__init__(parent)
        self.mode_id = mode_id
        self.mode_data = mode_data
        self.selected = False

        self.setup_ui()

    def setup_ui(self):
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Включаем обработку мышиных событий
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

        # Основной layout
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)

        # Заголовок с иконкой
        header_layout = QHBoxLayout()

        icon_label = QLabel(self.mode_data["icon"])
        icon_label.setFont(QFont("Segoe UI Emoji", 24))
        header_layout.addWidget(icon_label)

        name_label = QLabel(self.mode_data["name"])
        name_label.setFont(QFont("Arial", 14, 70))
        name_label.setStyleSheet(f"color: {self.mode_data['color']};")
        header_layout.addWidget(name_label)

        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Описание
        desc_label = QLabel(self.mode_data["description"])
        desc_label.setFont(QFont("Arial", 10))
        desc_label.setStyleSheet("color: #7f8c8d;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Параметры
        params_layout = QGridLayout()
        params_layout.setSpacing(5)

        params = [
            ("Risk:", f"{self.mode_data['risk_percentage']}%"),
            ("Max позиций:", str(self.mode_data["max_positions"])),
            ("Max DD:", f"{self.mode_data['max_daily_drawdown']}%"),
            ("Stop Loss:", f"{self.mode_data['stop_loss_atr_multiplier']}x ATR"),
            ("Take Profit:", f"{self.mode_data['risk_reward_ratio']}x RR"),
        ]

        for i, (label, value) in enumerate(params):
            label_widget = QLabel(label)
            label_widget.setFont(QFont("Arial", 9))
            label_widget.setStyleSheet("color: #95a5a6;")

            value_widget = QLabel(value)
            value_widget.setFont(QFont("Arial", 10, 70))
            value_widget.setStyleSheet(f"color: {self.mode_data['color']};")

            params_layout.addWidget(label_widget, i // 2, i % 2 * 2)
            params_layout.addWidget(value_widget, i // 2, i % 2 * 2 + 1)

        layout.addLayout(params_layout)

        # Индикатор выбора
        self.indicator = QLabel("●")
        self.indicator.setFont(QFont("Arial", 16))
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.indicator.setStyleSheet("color: transparent;")
        layout.addWidget(self.indicator)

        self.update_style()

    def set_selected(self, selected: bool):
        """Установка состояния выбора."""
        self.selected = selected
        self.update_style()

    def update_style(self):
        """Обновление стиля карточки."""
        if self.selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {self.mode_data['color']}20;
                    border: 2px solid {self.mode_data['color']};
                    border-radius: 10px;
                }}
            """)
            self.indicator.setStyleSheet(f"color: {self.mode_data['color']};")
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #f8f9fa;
                    border: 2px solid #e0e0e0;
                    border-radius: 10px;
                }
                QFrame:hover {
                    border: 2px solid #bdc3c7;
                }
            """)
            self.indicator.setStyleSheet("color: transparent;")

    def mousePressEvent(self, event):
        """Обработка нажатия мыши."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Находим родительский TradingModesWidget и вызываем on_mode_selected
            parent = self.parent()
            while parent:
                if isinstance(parent, TradingModesWidget):
                    # Если режимы выключены, сначала включаем их
                    if not parent.enabled:
                        parent.enabled = True
                        parent.modes_container.setEnabled(True)
                        parent.enabled_changed.emit(True)
                        logger.info("🎯 Режимы торговли автоматически ВКЛЮЧЕНЫ")

                    parent.on_mode_selected(self.mode_id)
                    break
                parent = parent.parent()
        super().mousePressEvent(event)


class TradingModesWidget(QWidget):
    """Виджет выбора режимов торговли."""

    mode_changed = Signal(str, dict)
    enabled_changed = Signal(bool)
    open_settings_requested = Signal()  # Сигнал для открытия настроек

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_mode = "standard"
        self.custom_settings = {}
        self.enabled = False  # Флаг включения режимов (по умолчанию выключен)

        # Устанавливаем политику размеров для корректной прокрутки
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Контейнер для карточек (будет блокироваться при отключении)
        self.modes_container = QWidget()
        modes_layout = QVBoxLayout(self.modes_container)
        modes_layout.setContentsMargins(0, 0, 0, 0)
        modes_layout.setSpacing(10)

        # Устанавливаем политику размеров для контейнера
        self.modes_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Заголовок
        header = QLabel("📊 Режимы Торговли")
        header.setFont(QFont("Arial", 16, 70))
        header.setStyleSheet("color: #2c3e50; padding: 10px;")
        modes_layout.addWidget(header)

        # Описание
        description = QLabel("Выберите режим торговли для автоматической настройки риск-менеджмента")
        description.setStyleSheet("color: #7f8c8d; padding: 0 10px 10px;")
        description.setWordWrap(True)
        modes_layout.addWidget(description)

        # Скролл для карточек
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(400)  # Минимальная высота для прокрутки
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                width: 8px;
                background: #f0f0f0;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #bdc3c7;
                border-radius: 4px;
            }
        """)

        # Контейнер для карточек
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(15)
        container_layout.setContentsMargins(10, 10, 10, 10)

        # Сетка для карточек режимов (2 в ряд)
        grid_layout = QGridLayout()
        grid_layout.setSpacing(15)

        # Карточки режимов
        self.mode_cards = {}
        row, col = 0, 0
        for mode_id, mode_data in TRADING_MODES.items():
            card = ModeCard(mode_id, mode_data)
            # Устанавливаем курсор
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mode_cards[mode_id] = card
            grid_layout.addWidget(card, row, col)

            col += 1
            if col >= 2:  # 2 карточки в ряд
                col = 0
                row += 1

        container_layout.addLayout(grid_layout)

        # Кастомный режим
        custom_frame = QFrame()
        custom_frame.setStyleSheet("""
            QFrame {
                background-color: #ecf0f1;
                border: 2px dashed #bdc3c7;
                border-radius: 10px;
            }
        """)
        custom_layout = QVBoxLayout(custom_frame)
        custom_layout.setSpacing(10)
        custom_layout.setContentsMargins(15, 15, 15, 15)

        custom_header = QLabel("🔧 Кастомный режим")
        custom_header.setFont(QFont("Arial", 14, 70))
        custom_layout.addWidget(custom_header)

        custom_desc = QLabel("Ручная настройка параметров риск-менеджмента.\n" "Прокрутите вниз для настройки параметров.")
        custom_desc.setStyleSheet("color: #7f8c8d;")
        custom_desc.setWordWrap(True)
        custom_layout.addWidget(custom_desc)

        self.custom_btn = QPushButton("Выбрать кастомный режим ↓")
        self.custom_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 8px 15px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.custom_btn.setToolTip("Выбирает кастомный режим и прокручивает к настройкам риск-менеджмента")
        self.custom_btn.clicked.connect(self.on_custom_selected)
        custom_layout.addWidget(self.custom_btn)

        container_layout.addWidget(custom_frame)

        container_layout.addStretch()

        scroll.setWidget(container)
        modes_layout.addWidget(scroll)
        layout.addWidget(self.modes_container)

        # Индикатор текущего режима
        self.current_mode_label = QLabel("Текущий режим: 🟡 Стандартный")
        self.current_mode_label.setFont(QFont("Arial", 11))
        self.current_mode_label.setStyleSheet("""
            background-color: #f39c1220;
            color: #f39c12;
            padding: 10px;
            border-radius: 5px;
            font-weight: bold;
        """)
        self.current_mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.current_mode_label)

        # Установка режима по умолчанию
        self.set_mode("standard")

    def on_enabled_changed(self, state):
        """Обработка изменения состояния переключателя."""
        # Проверяем состояние (может быть int или Qt.CheckState)
        if isinstance(state, int):
            self.enabled = state == 2  # Qt.CheckState.Checked = 2
        else:
            self.enabled = state == Qt.CheckState.Checked

        # Блокировка/разблокировка контейнера с карточками
        self.modes_container.setEnabled(self.enabled)

        # Отправка сигнала
        self.enabled_changed.emit(self.enabled)

        if self.enabled:
            logger.info("🎯 Режимы торговли ВКЛЮЧЕНЫ")
            # Применяем текущий режим
            if self.current_mode in TRADING_MODES:
                self.on_mode_selected(self.current_mode)
        else:
            logger.info("⚙️ Режимы торговли ОТКЛЮЧЕНЫ - система использует базовые настройки")
            # Отправляем сигнал об отключении
            self.mode_changed.emit("disabled", {})

    def on_mode_selected(self, mode_id: str):
        """Обработка выбора режима."""
        # Проверка YOLO режима
        if mode_id == "yolo":
            dialog = YoloConfirmationDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

        # Сброс выделения со всех карточек
        for card in self.mode_cards.values():
            card.set_selected(False)

        # Выделение выбранной карточки
        if mode_id in self.mode_cards:
            self.mode_cards[mode_id].set_selected(True)

        # Обновление текущего режима
        self.current_mode = mode_id
        mode_data = TRADING_MODES[mode_id]

        # Обновление индикатора
        self.current_mode_label.setText(f"Текущий режим: {mode_data['icon']} {mode_data['name']}")
        self.current_mode_label.setStyleSheet(f"""
            background-color: {mode_data['color']}20;
            color: {mode_data['color']};
            padding: 10px;
            border-radius: 5px;
            font-weight: bold;
        """)

        # Подготовка настроек
        settings = {
            "risk_percentage": mode_data["risk_percentage"],
            "max_positions": mode_data["max_positions"],
            "max_daily_drawdown": mode_data["max_daily_drawdown"],
            "stop_loss_atr_multiplier": mode_data["stop_loss_atr_multiplier"],
            "risk_reward_ratio": mode_data["risk_reward_ratio"],
            "enable_all_risk_checks": mode_data["enable_all_risk_checks"],
        }

        # Отправка сигнала
        self.mode_changed.emit(mode_id, settings)

    def on_custom_selected(self):
        """Обработка выбора кастомного режима."""
        # Сброс выделения со всех карточек
        for card in self.mode_cards.values():
            card.set_selected(False)

        self.current_mode = "custom"

        self.current_mode_label.setText("Текущий режим: 🔧 Кастомный")
        self.current_mode_label.setStyleSheet("""
            background-color: #3498db20;
            color: #3498db;
            padding: 10px;
            border-radius: 5px;
            font-weight: bold;
        """)

        # Отправляем сигнал для открытия настроек
        self.open_settings_requested.emit()

        # Отправляем сигнал с пустыми настройками (будут настроены вручную)
        self.mode_changed.emit("custom", {})

    def get_current_mode(self) -> str:
        """Получение текущего режима."""
        return self.current_mode

    def set_mode(self, mode_id: str):
        """Установка режима программно."""
        if mode_id in self.mode_cards:
            self.on_mode_selected(mode_id)
