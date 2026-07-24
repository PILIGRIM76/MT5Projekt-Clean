# -*- coding: utf-8 -*-
"""Диалоговые окна для GUI."""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
)


class DirectiveDialog(QDialog):
    """Диалог для создания новой директивы."""

    # Человекочитаемые названия типов директив
    DIRECTIVE_TYPE_LABELS = {
        "BLOCK_TRADING": "🚫 Блокировка торговли",
        "RISK_OFF_MODE": "🛡️ Режим пониженного риска",
        "SET_MAX_WEEKLY_DRAWDOWN": "📊 Макс. недельная просадка (%)",
    }

    # Обратное соответствие для получения ключа по индексу
    DIRECTIVE_TYPE_KEYS = list(DIRECTIVE_TYPE_LABELS.keys())

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создать новую директиву")
        layout = QGridLayout(self)

        layout.addWidget(QLabel("Тип директивы:"), 0, 0)
        self.type_combo = QComboBox()
        # Добавляем человеко-читаемые названия
        for key, label in self.DIRECTIVE_TYPE_LABELS.items():
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self.on_type_changed)
        layout.addWidget(self.type_combo, 0, 1)

        self.value_label = QLabel("Значение (%):")
        self.value_spinbox = QDoubleSpinBox()
        self.value_spinbox.setRange(1.0, 20.0)
        self.value_spinbox.setValue(3.0)
        self.value_spinbox.setSingleStep(0.5)
        layout.addWidget(self.value_label, 1, 0)
        layout.addWidget(self.value_spinbox, 1, 1)

        layout.addWidget(QLabel("Причина:"), 2, 0)
        self.reason_edit = QLineEdit("Manual override from GUI")
        layout.addWidget(self.reason_edit, 2, 1)

        layout.addWidget(QLabel("Срок действия (часы):"), 3, 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 720)
        self.duration_spin.setValue(168)
        layout.addWidget(self.duration_spin, 3, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 4, 0, 1, 2)

        self.on_type_changed(0)

    def on_type_changed(self, index: int) -> None:
        directive_key = self.type_combo.currentData()
        is_value_needed = "DRAWDOWN" in directive_key
        self.value_label.setVisible(is_value_needed)
        self.value_spinbox.setVisible(is_value_needed)

    def get_data(self) -> Dict[str, Any]:
        """Возвращает данные директивы."""
        return {
            "type": self.type_combo.currentData(),  # Возвращаем ключ, а не label
            "reason": self.reason_edit.text(),
            "duration_hours": self.duration_spin.value(),
            "value": self.value_spinbox.value(),
        }
