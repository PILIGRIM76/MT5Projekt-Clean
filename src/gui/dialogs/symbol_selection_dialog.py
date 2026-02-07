# src/gui/dialogs/symbol_selection_dialog.py
from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QPushButton, QLabel, QHBoxLayout, QCheckBox, \
    QListWidgetItem
from PySide6.QtCore import Qt
from typing import List

class SymbolSelectionDialog(QDialog):
    def __init__(self, symbols: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выберите символы для торговли")
        self.setModal(True)
        self.symbols = symbols

        layout = QVBoxLayout(self)

        label = QLabel("Доступные символы в MT5:")
        layout.addWidget(label)

        self.list_widget = QListWidget()
        for symbol in symbols:
            item = QListWidgetItem(symbol)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        button_layout = QHBoxLayout()
        self.selectAll_button = QPushButton("Выбрать все")
        self.deselectAll_button = QPushButton("Снять выбор")
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Отмена")

        button_layout.addWidget(self.selectAll_button)
        button_layout.addWidget(self.deselectAll_button)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        # Сигналы
        self.selectAll_button.clicked.connect(self._select_all)
        self.deselectAll_button.clicked.connect(self._deselect_all)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def _select_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setCheckState(Qt.Checked)

    def _deselect_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setCheckState(Qt.Unchecked)

    def get_selected_symbols(self) -> List[str]:
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected