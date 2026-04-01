# -*- coding: utf-8 -*-
"""
Единый виджет настроек торговли и риск-менеджмента.
Объединяет режимы торговли и ручные настройки с автоматической синхронизацией.
"""

import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .trading_modes_widget import TRADING_MODES, TradingModesWidget

logger = logging.getLogger(__name__)


class UnifiedTradingSettingsWidget(QWidget):
    """
    Единый виджет настроек торговли с синхронизацией всех элементов.

    Особенности:
    - Автоматическая синхронизация между слайдером и spinbox
    - Панель итоговых параметров в реальном времени
    - Предупреждения о конфликтах
    - Блокировка ручных настроек при выборе пресета
    """

    # Сигналы для отправки изменений
    settings_changed = Signal(dict)  # Отправляет dict с новыми настройками
    mode_changed = Signal(str, dict)  # mode_id, settings
    mode_enabled_changed = Signal(bool)  # enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_mode = "standard"
        self.mode_enabled = False
        self.custom_settings = {}

        # Флаг блокировки рекурсивных обновлений
        self._updating = False

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        # === 1. ЗАГОЛОВОК ===
        header = QLabel("⚙️ Настройки Торговли и Риск-менеджмента")
        header.setFont(QFont("Arial", 16, QFont.Bold))
        header.setStyleSheet("color: #f8f8f2; padding: 10px;")
        layout.addWidget(header)

        # === 2. ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМОВ ===
        modes_group = self._create_modes_group()
        layout.addWidget(modes_group)

        # === 3. ПАНЕЛЬ ИТОГОВЫХ ПАРАМЕТРОВ (всегда видна) ===
        self.summary_panel = self._create_summary_panel()
        layout.addWidget(self.summary_panel)

        # === 4. РАЗДЕЛИТЕЛЬ ===
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("background-color: #3e4451;")
        layout.addWidget(separator)

        # === 5. РУЧНЫЕ НАСТРОЙКИ (с блокировкой при пресете) ===
        manual_group = self._create_manual_settings_group()
        layout.addWidget(manual_group)

        # === 6. ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ ===
        advanced_group = self._create_advanced_settings_group()
        layout.addWidget(advanced_group)

        # === 7. КНОПКИ ПРИМЕНЕНИЯ ===
        buttons_layout = self._create_buttons_layout()
        layout.addLayout(buttons_layout)

        # Инициализация текущими значениями
        self._update_summary_panel()

    def _create_modes_group(self) -> QGroupBox:
        """Группа выбора режима торговли."""
        from PySide6.QtWidgets import QGroupBox

        group = QGroupBox("📊 Режимы Торговли")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #f8f8f2;
                margin-top: 10px;
                padding-top: 10px;
                border: 1px solid #3e4451;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(group)

        # Переключатель вкл/выкл режимов
        toggle_layout = QHBoxLayout()
        toggle_layout.setSpacing(10)

        off_label = QLabel("⛔ Выкл")
        off_label.setStyleSheet("color: #95a5a6; font-weight: bold; font-size: 13px;")

        self.enable_checkbox = QCheckBox()
        self.enable_checkbox.setChecked(False)
        self.enable_checkbox.setCursor(Qt.PointingHandCursor)
        self.enable_checkbox.setStyleSheet("""
            QCheckBox {
                spacing: 0px;
            }
            QCheckBox::indicator {
                width: 60px;
                height: 30px;
                border-radius: 15px;
                background-color: #34495e;
            }
            QCheckBox::indicator:checked {
                background-color: #27ae60;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #27ae60;
            }
            QCheckBox::indicator:unchecked:hover {
                border: 2px solid #95a5a6;
            }
        """)
        self.enable_checkbox.stateChanged.connect(self._on_mode_enabled_changed)

        on_label = QLabel("✅ Вкл")
        on_label.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 13px;")

        toggle_layout.addWidget(off_label)
        toggle_layout.addWidget(self.enable_checkbox)
        toggle_layout.addWidget(on_label)
        layout.addLayout(toggle_layout)

        # Описание
        desc = QLabel(
            "Выберите готовый режим для автоматической настройки риск-менеджмента.\n"
            "При выборе режима ручные настройки блокируются."
        )
        desc.setStyleSheet("color: #bdc3c7; padding: 5px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # TradingModesWidget (карточки режимов)
        self.modes_widget = TradingModesWidget()
        self.modes_widget.mode_changed.connect(self._on_mode_selected)
        self.modes_widget.open_settings_requested.connect(self._on_custom_selected)
        layout.addWidget(self.modes_widget)

        return group

    def _create_summary_panel(self) -> QFrame:
        """Панель итоговых параметров в реальном времени."""
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        panel.setStyleSheet("""
            QFrame {
                background-color: #282a36;
                border: 2px solid #bd93f9;
                border-radius: 10px;
                padding: 15px;
            }
        """)

        layout = QVBoxLayout(panel)

        # Заголовок
        title = QLabel("📈 Итоговые Параметры (применяются к системе)")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        title.setStyleSheet("color: #bd93f9;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Сетка параметров
        grid = QGridLayout()
        grid.setSpacing(10)

        # Риск на сделку
        grid.addWidget(QLabel("🎯 Риск на сделку:"), 0, 0)
        self.summary_risk_label = QLabel("0.50%")
        self.summary_risk_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.summary_risk_label.setStyleSheet("color: #50fa7b;")
        self.summary_risk_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self.summary_risk_label, 0, 1)

        # Max позиций
        grid.addWidget(QLabel("📊 Max позиций:"), 1, 0)
        self.summary_positions_label = QLabel("5")
        self.summary_positions_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.summary_positions_label.setStyleSheet("color: #8be9fd;")
        self.summary_positions_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self.summary_positions_label, 1, 1)

        # Max дневная просадка
        grid.addWidget(QLabel("📉 Max дневная просадка:"), 2, 0)
        self.summary_drawdown_label = QLabel("5.00%")
        self.summary_drawdown_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.summary_drawdown_label.setStyleSheet("color: #ff5555;")
        self.summary_drawdown_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self.summary_drawdown_label, 2, 1)

        # Stop Loss
        grid.addWidget(QLabel("🛑 Stop Loss:"), 3, 0)
        self.summary_sl_label = QLabel("3.0x ATR")
        self.summary_sl_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.summary_sl_label.setStyleSheet("color: #ffb86c;")
        self.summary_sl_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self.summary_sl_label, 3, 1)

        # Take Profit
        grid.addWidget(QLabel("✅ Take Profit:"), 4, 0)
        self.summary_tp_label = QLabel("2.5x RR")
        self.summary_tp_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.summary_tp_label.setStyleSheet("color: #50fa7b;")
        self.summary_tp_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self.summary_tp_label, 4, 1)

        # Статус режима
        grid.addWidget(QLabel("🏷️ Активный режим:"), 5, 0)
        self.summary_mode_label = QLabel("🟡 Стандартный")
        self.summary_mode_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.summary_mode_label.setStyleSheet("color: #f1fa8c;")
        self.summary_mode_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self.summary_mode_label, 5, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        return panel

    def _create_manual_settings_group(self) -> QGroupBox:
        """Группа ручных настроек риск-менеджмента."""
        from PySide6.QtWidgets import QGroupBox

        group = QGroupBox("⚙️ Ручная Настройка Параметров")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #f8f8f2;
                margin-top: 10px;
                padding-top: 10px;
                border: 1px solid #3e4451;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(group)

        # Предупреждение
        self.manual_warning_label = QLabel("⚠️ Ручные настройки разблокированы - режим торговли отключен")
        self.manual_warning_label.setStyleSheet(
            "color: #f1fa8c; padding: 5px; background-color: #f1fa8c20; border-radius: 5px;"
        )
        self.manual_warning_label.setWordWrap(True)
        layout.addWidget(self.manual_warning_label)

        # === АГРЕССИВНОСТЬ (слайдер + spinbox синхронизированы) ===
        agg_layout = QHBoxLayout()
        agg_layout.setSpacing(15)

        # Метка
        agg_label = QLabel("📊 Агрессивность:")
        agg_label.setMinimumWidth(150)
        agg_layout.addWidget(agg_label)

        # Слайдер
        self.aggression_slider = QSlider(Qt.Horizontal)
        self.aggression_slider.setRange(0, 100)
        self.aggression_slider.setValue(0)  # Будет пересчитано
        self.aggression_slider.setToolTip("Перетаскивайте для быстрой настройки")
        self.aggression_slider.valueChanged.connect(self._on_aggression_slider_changed)
        agg_layout.addWidget(self.aggression_slider, 1)

        # SpinBox риска
        self.risk_spinbox = QDoubleSpinBox()
        self.risk_spinbox.setRange(0.1, 10.0)
        self.risk_spinbox.setSingleStep(0.1)
        self.risk_spinbox.setSuffix("%")
        self.risk_spinbox.setMinimumWidth(100)
        self.risk_spinbox.setToolTip("Точное значение риска на сделку")
        self.risk_spinbox.valueChanged.connect(self._on_risk_spinbox_changed)
        agg_layout.addWidget(self.risk_spinbox)

        layout.addLayout(agg_layout)

        # === Max позиций ===
        positions_layout = QHBoxLayout()
        positions_layout.setSpacing(15)

        positions_layout.addWidget(QLabel("📈 Max позиций:"))
        self.positions_spinbox = QSpinBox()
        self.positions_spinbox.setRange(1, 100)
        self.positions_spinbox.setToolTip("Максимальное количество одновременных позиций")
        self.positions_spinbox.valueChanged.connect(self._on_positions_changed)
        positions_layout.addWidget(self.positions_spinbox)
        positions_layout.addStretch()
        layout.addLayout(positions_layout)

        # === Max дневная просадка ===
        drawdown_layout = QHBoxLayout()
        drawdown_layout.setSpacing(15)

        drawdown_layout.addWidget(QLabel("📉 Max дневная просадка:"))
        self.drawdown_spinbox = QDoubleSpinBox()
        self.drawdown_spinbox.setRange(1.0, 50.0)
        self.drawdown_spinbox.setSingleStep(0.5)
        self.drawdown_spinbox.setSuffix("%")
        self.drawdown_spinbox.setToolTip("Максимальная дневная просадка в %")
        self.drawdown_spinbox.valueChanged.connect(self._on_drawdown_changed)
        drawdown_layout.addWidget(self.drawdown_spinbox)
        drawdown_layout.addStretch()
        layout.addLayout(drawdown_layout)

        # === Stop Loss и Take Profit ===
        sl_tp_layout = QGridLayout()
        sl_tp_layout.setSpacing(15)

        # Stop Loss
        sl_tp_layout.addWidget(QLabel("🛑 Stop Loss (ATR множитель):"), 0, 0)
        self.sl_spinbox = QDoubleSpinBox()
        self.sl_spinbox.setRange(0.5, 10.0)
        self.sl_spinbox.setSingleStep(0.5)
        self.sl_spinbox.setToolTip("Множитель ATR для установки Stop Loss")
        self.sl_spinbox.valueChanged.connect(self._on_sl_changed)
        sl_tp_layout.addWidget(self.sl_spinbox, 0, 1)

        # Take Profit
        sl_tp_layout.addWidget(QLabel("✅ Take Profit (RR множитель):"), 1, 0)
        self.tp_spinbox = QDoubleSpinBox()
        self.tp_spinbox.setRange(0.5, 10.0)
        self.tp_spinbox.setSingleStep(0.5)
        self.tp_spinbox.setToolTip("Соотношение прибыль/риск для Take Profit")
        self.tp_spinbox.valueChanged.connect(self._on_tp_changed)
        sl_tp_layout.addWidget(self.tp_spinbox, 1, 1)

        layout.addLayout(sl_tp_layout)

        # === Чекбокс проверки рисков ===
        self.risk_checks_checkbox = QCheckBox("✅ Включить все проверки риск-менеджмента")
        self.risk_checks_checkbox.setChecked(True)
        self.risk_checks_checkbox.stateChanged.connect(self._on_risk_checks_changed)
        layout.addWidget(self.risk_checks_checkbox)

        return group

    def _create_advanced_settings_group(self) -> QGroupBox:
        """Группа дополнительных настроек."""
        from PySide6.QtWidgets import QGroupBox

        group = QGroupBox("🔧 Дополнительные Настройки")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #f8f8f2;
                margin-top: 10px;
                padding-top: 10px;
                border: 1px solid #3e4451;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        layout = QGridLayout(group)

        # Торговля на выходных
        self.weekend_trading_checkbox = QCheckBox("Разрешить торговлю на выходных (для отладки)")
        self.weekend_trading_checkbox.setToolTip(
            "Если включено, система будет торговать на выходных.\n" "Рекомендуется только для тестирования!"
        )
        self.weekend_trading_checkbox.stateChanged.connect(self._on_settings_changed_internal)
        layout.addWidget(self.weekend_trading_checkbox, 0, 0, 1, 2)

        # Whitelist символов
        layout.addWidget(QLabel("📋 Торговые символы (Whitelist):"), 1, 0)

        symbols_layout = QHBoxLayout()
        self.symbols_edit = QLineEdit()
        self.symbols_edit.setPlaceholderText("EURUSD, GBPUSD, XAUUSD...")
        self.symbols_edit.setToolTip("Введите символы через запятую")
        symbols_layout.addWidget(self.symbols_edit)

        self.symbols_apply_btn = QPushButton("Применить")
        self.symbols_apply_btn.clicked.connect(self._on_symbols_applied)
        symbols_layout.addWidget(self.symbols_apply_btn)

        layout.addLayout(symbols_layout, 2, 0, 1, 2)

        return group

    def _create_buttons_layout(self) -> QHBoxLayout:
        """Создаёт layout с кнопками применения."""
        layout = QHBoxLayout()
        layout.addStretch()

        # Кнопка сброса
        self.reset_btn = QPushButton("🔄 Сбросить к настройкам по умолчанию")
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #6272a4;
                color: #f8f8f2;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4c5a7d;
            }
        """)
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self.reset_btn)

        # Кнопка применения
        self.apply_btn = QPushButton("💾 Применить Настройки")
        self.apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #50fa7b;
                color: #282a36;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #42d669;
            }
        """)
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self.apply_btn)

        return layout

    # === МЕТОODЫ СИНХРОНИЗАЦИИ ===

    def _on_mode_enabled_changed(self, state: int):
        """Обработка включения/выключения режимов."""
        self.mode_enabled = state == Qt.Checked
        self.modes_widget.on_enabled_changed(state)
        self.mode_enabled_changed.emit(self.mode_enabled)

        if self.mode_enabled:
            self.manual_warning_label.setText("ℹ️ Ручные настройки заблокированы - активен режим торговли")
            self.manual_warning_label.setStyleSheet(
                "color: #8be9fd; padding: 5px; background-color: #8be9fd20; border-radius: 5px;"
            )
            self._set_manual_enabled(False)
        else:
            self.manual_warning_label.setText("⚠️ Ручные настройки разблокированы - режим торговли отключен")
            self.manual_warning_label.setStyleSheet(
                "color: #f1fa8c; padding: 5px; background-color: #f1fa8c20; border-radius: 5px;"
            )
            self._set_manual_enabled(True)
            self.mode_changed.emit("disabled", {})

    def _on_mode_selected(self, mode_id: str, settings: dict):
        """Обработка выбора режима торговли."""
        if self._updating:
            return

        self.current_mode = mode_id

        if mode_id != "disabled":
            # Применяем настройки режима
            self._apply_mode_settings(settings)
            self._set_manual_enabled(False)
            self.mode_changed.emit(mode_id, settings)
        else:
            # Режим отключен - разблокируем ручные настройки
            self._set_manual_enabled(True)
            self.mode_changed.emit("disabled", {})

        self._update_summary_panel()
        logger.info(f"🎯 Режим торговли установлен: {mode_id}")

    def _on_custom_selected(self):
        """Обработка выбора кастомного режима."""
        self.current_mode = "custom"
        self._set_manual_enabled(True)
        self.manual_warning_label.setText("🔧 Кастомный режим - ручная настройка параметров")
        self.manual_warning_label.setStyleSheet(
            "color: #8be9fd; padding: 5px; background-color: #8be9fd20; border-radius: 5px;"
        )
        self.mode_changed.emit("custom", {})
        self._update_summary_panel()

    def _on_aggression_slider_changed(self, value: int):
        """Синхронизация слайдера с risk spinbox."""
        if self._updating:
            return

        # Пересчитываем риск из значения слайдера
        risk = 0.5 + (value / 100.0) * 4.5
        positions = int(1 + (value / 100.0) * 17)

        self._updating = True
        self.risk_spinbox.setValue(risk)
        self.positions_spinbox.setValue(positions)
        self._updating = False

        self._update_summary_panel()
        self._on_settings_changed_internal()

    def _on_risk_spinbox_changed(self, value: float):
        """Синхронизация risk spinbox со слайдером."""
        if self._updating:
            return

        # Пересчитываем слайдер из риска
        slider_value = int(((value - 0.5) / 4.5) * 100)
        slider_value = max(0, min(100, slider_value))  # Ограничение 0-100

        positions = int(1 + (slider_value / 100.0) * 17)

        self._updating = True
        with QSignalBlocker(self.aggression_slider):
            self.aggression_slider.setValue(slider_value)
        self.positions_spinbox.setValue(positions)
        self._updating = False

        self._update_summary_panel()
        self._on_settings_changed_internal()

    def _on_positions_changed(self, value: int):
        """Обработка изменения max позиций."""
        self._update_summary_panel()
        self._on_settings_changed_internal()

    def _on_drawdown_changed(self, value: float):
        """Обработка изменения max просадки."""
        self._update_summary_panel()
        self._on_settings_changed_internal()

    def _on_sl_changed(self, value: float):
        """Обработка изменения Stop Loss."""
        self._update_summary_panel()
        self._on_settings_changed_internal()

    def _on_tp_changed(self, value: float):
        """Обработка изменения Take Profit."""
        self._update_summary_panel()
        self._on_settings_changed_internal()

    def _on_risk_checks_changed(self, state: int):
        """Обработка изменения чекбокса проверок рисков."""
        self._on_settings_changed_internal()

    def _on_settings_changed_internal(self):
        """Внутренний метод для отправки изменений."""
        # Собираем текущие настройки
        settings = self._collect_settings()
        self.settings_changed.emit(settings)

    def _on_symbols_applied(self):
        """Применение списка символов."""
        symbols_text = self.symbols_edit.text().strip()
        if not symbols_text:
            QMessageBox.warning(self, "Внимание", "Введите символы через запятую")
            return

        symbols = [s.strip().upper() for s in symbols_text.split(",") if s.strip()]
        settings = self._collect_settings()
        settings["SYMBOLS_WHITELIST"] = symbols

        self.settings_changed.emit(settings)
        QMessageBox.information(self, "Успех", f"Применено {len(symbols)} символов")

    def _on_reset_clicked(self):
        """Сброс к настройкам по умолчанию."""
        reply = QMessageBox.question(
            self,
            "Сброс настроек",
            "Вы уверены, что хотите сбросить все настройки к значениям по умолчанию?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._reset_to_defaults()
            self._on_settings_changed_internal()
            QMessageBox.information(self, "Успех", "Настройки сброшены к значениям по умолчанию")

    def _on_apply_clicked(self):
        """Применение настроек."""
        settings = self._collect_settings()

        # Проверка на конфликт
        if self.mode_enabled and self.current_mode != "custom":
            # Режим активен - показываем предупреждение
            mode_data = TRADING_MODES.get(self.current_mode, {})
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                f"Активен режим '{mode_data.get('name', self.current_mode)}'.\n\n"
                f"Параметры режима:\n"
                f"• Риск: {mode_data.get('risk_percentage', 0)}%\n"
                f"• Max DD: {mode_data.get('max_daily_drawdown', 0)}%\n\n"
                "Применить настройки?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )

            if reply != QMessageBox.Yes:
                return

        self.settings_changed.emit(settings)
        QMessageBox.information(self, "Успех", "Настройки применены!")

    # === ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ===

    def _apply_mode_settings(self, settings: dict):
        """Применяет настройки режима к элементам управления."""
        self._updating = True

        if "risk_percentage" in settings:
            self.risk_spinbox.setValue(settings["risk_percentage"])

        if "max_positions" in settings:
            self.positions_spinbox.setValue(settings["max_positions"])

        if "max_daily_drawdown" in settings:
            self.drawdown_spinbox.setValue(settings["max_daily_drawdown"])

        if "stop_loss_atr_multiplier" in settings:
            self.sl_spinbox.setValue(settings["stop_loss_atr_multiplier"])

        if "risk_reward_ratio" in settings:
            self.tp_spinbox.setValue(settings["risk_reward_ratio"])

        if "enable_all_risk_checks" in settings:
            self.risk_checks_checkbox.setChecked(settings["enable_all_risk_checks"])

        # Пересчитываем слайдер
        risk = settings.get("risk_percentage", 0.5)
        slider_value = int(((risk - 0.5) / 4.5) * 100)
        slider_value = max(0, min(100, slider_value))
        with QSignalBlocker(self.aggression_slider):
            self.aggression_slider.setValue(slider_value)

        self._updating = False
        self._update_summary_panel()

    def _set_manual_enabled(self, enabled: bool):
        """Блокирует/разблокирует ручные настройки."""
        self.risk_spinbox.setEnabled(enabled)
        self.positions_spinbox.setEnabled(enabled)
        self.drawdown_spinbox.setEnabled(enabled)
        self.sl_spinbox.setEnabled(enabled)
        self.tp_spinbox.setEnabled(enabled)
        self.risk_checks_checkbox.setEnabled(enabled)
        self.aggression_slider.setEnabled(enabled)

    def _update_summary_panel(self):
        """Обновляет панель итоговых параметров."""
        self.summary_risk_label.setText(f"{self.risk_spinbox.value():.2f}%")
        self.summary_positions_label.setText(str(self.positions_spinbox.value()))
        self.summary_drawdown_label.setText(f"{self.drawdown_spinbox.value():.2f}%")
        self.summary_sl_label.setText(f"{self.sl_spinbox.value():.1f}x ATR")
        self.summary_tp_label.setText(f"{self.tp_spinbox.value():.1f}x RR")

        # Обновляем метку режима
        if self.mode_enabled:
            if self.current_mode in TRADING_MODES:
                mode_data = TRADING_MODES[self.current_mode]
                self.summary_mode_label.setText(f"{mode_data['icon']} {mode_data['name']}")
                self.summary_mode_label.setStyleSheet(f"color: {mode_data['color']}; font-weight: bold;")
            else:
                self.summary_mode_label.setText("🔧 Кастомный")
                self.summary_mode_label.setStyleSheet("color: #8be9fd; font-weight: bold;")
        else:
            self.summary_mode_label.setText("⚙️ Ручной режим")
            self.summary_mode_label.setStyleSheet("color: #6272a4; font-weight: bold;")

    def _collect_settings(self) -> dict:
        """Собирает текущие настройки в dict."""
        return {
            "RISK_PERCENTAGE": self.risk_spinbox.value(),
            "MAX_OPEN_POSITIONS": self.positions_spinbox.value(),
            "MAX_DAILY_DRAWDOWN_PERCENT": self.drawdown_spinbox.value(),
            "STOP_LOSS_ATR_MULTIPLIER": self.sl_spinbox.value(),
            "RISK_REWARD_RATIO": self.tp_spinbox.value(),
            "ENABLE_ALL_RISK_CHECKS": self.risk_checks_checkbox.isChecked(),
            "ALLOW_WEEKEND_TRADING": self.weekend_trading_checkbox.isChecked(),
            "trading_mode": {"current_mode": self.current_mode, "enabled": self.mode_enabled},
        }

    def _reset_to_defaults(self):
        """Сбрасывает все настройки к значениям по умолчанию."""
        self._updating = True

        # Значения по умолчанию (Стандартный режим)
        self.risk_spinbox.setValue(0.5)
        self.positions_spinbox.setValue(10)
        self.drawdown_spinbox.setValue(5.0)
        self.sl_spinbox.setValue(3.0)
        self.tp_spinbox.setValue(2.5)
        self.risk_checks_checkbox.setChecked(True)
        self.weekend_trading_checkbox.setChecked(True)
        self.aggression_slider.setValue(0)

        # Сброс режима
        self.mode_enabled = False
        self.enable_checkbox.setChecked(False)
        self.current_mode = "standard"
        self.modes_widget.set_mode("standard")

        self._updating = False
        self._set_manual_enabled(True)
        self._update_summary_panel()

    # === ПУБЛИЧНЫЕ МЕТОДЫ ДЛЯ ЗАГРУЗКИ НАСТРОЕК ===

    def load_settings(self, config: Any):
        """
        Загружает настройки из конфигурации.

        Args:
            config: Объект Settings с текущими настройками
        """
        self._updating = True

        # Базовые настройки риска
        self.risk_spinbox.setValue(getattr(config, "RISK_PERCENTAGE", 0.5))
        self.positions_spinbox.setValue(getattr(config, "MAX_OPEN_POSITIONS", 5))
        self.drawdown_spinbox.setValue(getattr(config, "MAX_DAILY_DRAWDOWN_PERCENT", 5.0))
        self.sl_spinbox.setValue(getattr(config, "STOP_LOSS_ATR_MULTIPLIER", 3.0))
        self.tp_spinbox.setValue(getattr(config, "RISK_REWARD_RATIO", 2.5))

        # Дополнительные настройки
        if hasattr(config, "ALLOW_WEEKEND_TRADING"):
            self.weekend_trading_checkbox.setChecked(config.ALLOW_WEEKEND_TRADING)

        # Загрузка режима торговли
        if hasattr(config, "trading_mode"):
            trading_mode = config.trading_mode
            self.mode_enabled = trading_mode.get("enabled", False)
            self.current_mode = trading_mode.get("current_mode", "standard")

            self.enable_checkbox.setChecked(self.mode_enabled)
            self.modes_widget.set_mode(self.current_mode)

            if self.mode_enabled:
                self._set_manual_enabled(False)
                self.manual_warning_label.setText("ℹ️ Ручные настройки заблокированы - активен режим торговли")
            else:
                self._set_manual_enabled(True)
                self.manual_warning_label.setText("⚠️ Ручные настройки разблокированы - режим торговли отключен")

        self._updating = False
        self._update_summary_panel()

    def get_settings(self) -> dict:
        """Возвращает текущие настройки."""
        return self._collect_settings()
