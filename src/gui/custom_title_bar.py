# -*- coding: utf-8 -*-
"""
src/gui/custom_title_bar.py — Кастомная рамка (title bar) для главного окна

Отвечает за:
- Перетаскивание окна (drag)
- Кнопки: свернуть / развернуть / закрыть
- Анимации при наведении
- Отображение заголовка
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class CustomTitleBar(QWidget):
    """Кастомная панель заголовка окна с кнопками управления."""

    # Сигналы для родительского окна
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    # Размеры
    TITLE_BAR_HEIGHT = 36
    BUTTON_SIZE = 36

    def __init__(
        self,
        title: str = "Genesis Trading System",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("CustomTitleBar")
        self.setFixedHeight(self.TITLE_BAR_HEIGHT)
        self.setMinimumHeight(self.TITLE_BAR_HEIGHT)
        self.setMaximumHeight(self.TITLE_BAR_HEIGHT)

        # Состояние перетаскивания
        self._drag_pos: QPointF | None = None
        self._is_dragging = False

        # Ссылка на родительское окно (для move/resize)
        self._parent_window = parent

        self._build_ui(title)
        self._connect_signals()

    # ===================================================================
    # Построение UI
    # ===================================================================

    def _build_ui(self, title: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Заголовок (левая часть) ---
        self.title_label = QLabel(title)
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.title_label.setContentsMargins(12, 0, 0, 0)
        self.title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #1A1D23; padding-left: 12px;")
        layout.addWidget(self.title_label, stretch=1)

        layout.addStretch()

        # --- Кнопки управления (правая часть) ---
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(0)

        # Свернуть
        self.min_btn = self._create_button("—", "Свернуть")
        self.min_btn.setObjectName("TitleMinimizeButton")
        self.min_btn.clicked.connect(self._on_minimize)
        btn_layout.addWidget(self.min_btn)

        # Развернуть / Восстановить
        self.max_btn = self._create_button("□", "Развернуть")
        self.max_btn.setObjectName("TitleMaximizeButton")
        self.max_btn.clicked.connect(self._on_maximize)
        btn_layout.addWidget(self.max_btn)

        # Закрыть
        self.close_btn = self._create_button("✕", "Закрыть")
        self.close_btn.setObjectName("TitleCloseButton")
        self.close_btn.clicked.connect(self._on_close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _create_button(self, text: str, tooltip: str) -> QPushButton:
        """Создаёт стандартную кнопку title bar."""
        btn = QPushButton(text)
        btn.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Normal))
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return btn

    def _connect_signals(self) -> None:
        pass  # Подключение внешних сигналов — по необходимости

    # ===================================================================
    # Обработчики кнопок
    # ===================================================================

    @Slot()
    def _on_minimize(self) -> None:
        self.minimize_requested.emit()

    @Slot()
    def _on_maximize(self) -> None:
        self.maximize_requested.emit()

    @Slot()
    def _on_close(self) -> None:
        self.close_requested.emit()

    # ===================================================================
    # Перетаскивание окна (drag)
    # ===================================================================

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition()
            self._is_dragging = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging and self._drag_pos is not None and self._parent_window is not None:
            delta = event.globalPosition() - self._drag_pos
            new_x = int(self._parent_window.x() + delta.x())
            new_y = int(self._parent_window.y() + delta.y())
            self._parent_window.move(new_x, new_y)
            self._drag_pos = event.globalPosition()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._is_dragging = False
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Двойной клик по title bar — развернуть/восстановить."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_maximize()
        super().mouseDoubleClickEvent(event)

    # ===================================================================
    # Публичные API
    # ===================================================================

    def set_title(self, text: str) -> None:
        """Обновить текст заголовка."""
        self.title_label.setText(text)

    def attach_to_window(self, parent_window) -> None:
        """Привязать к родительскому окну для управления."""
        self._parent_window = parent_window
