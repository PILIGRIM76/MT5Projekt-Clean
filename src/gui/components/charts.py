# -*- coding: utf-8 -*-
"""
Графические компоненты для отображения данных.

Содержит:
- CustomCandlestickItem: Отображение японских свечей
- GraphBackend: Мост между JS и Python для графиков
"""

from typing import Any, Dict, Optional

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, Signal, Slot
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsObject


class CustomCandlestickItem(pg.GraphicsObject):
    """
    Графический элемент для отображения японских свечей.

    Адаптивная ширина свечи, цветовая кодировка (зеленый/красный).
    """

    def __init__(self):
        super().__init__()
        self.data: Optional[list] = None

    def setData(self, data: list) -> None:
        """
        Установка данных для отрисовки.

        Args:
            data: Список кортежей (time, open, high, low, close)
        """
        self.data = data
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def paint(self, painter: QPainter, *args) -> None:
        """Отрисовка свечей."""
        if self.data is None or len(self.data) < 2:
            return

        # Вычисляем ширину свечи адаптивно
        if len(self.data) > 1:
            step = float(self.data[1][0] - self.data[0][0])
            if step <= 0:
                step = 1
            # Используем только 25% от шага, мин 2 пикселя, макс 8 пикселей
            w = max(min(step * 0.25, 8.0), 2.0)
        else:
            w = 2.0

        for t, o, h, l, c in self.data:
            # Определяем цвет свечи
            if c >= o:  # Зеленая свеча (рост)
                pen = pg.mkPen("g", width=1)
                brush = pg.mkBrush("g")
            else:  # Красная свеча (падение)
                pen = pg.mkPen("r", width=1)
                brush = pg.mkBrush("r")

            painter.setPen(pen)
            painter.setBrush(brush)

            body_top = max(o, c)
            body_bottom = min(o, c)
            body_height = body_top - body_bottom

            # Рисуем верхнюю тень (от high до верха тела)
            painter.drawLine(QPointF(t, h), QPointF(t, body_top))
            # Рисуем нижнюю тень (от low до низа тела)
            painter.drawLine(QPointF(t, l), QPointF(t, body_bottom))

            # Рисуем тело с ограниченной шириной
            if body_height > 0:
                painter.drawRect(QRectF(t - w, body_bottom, w * 2, body_height))
            else:
                # Если open == close, рисуем горизонтальную линию
                painter.drawLine(QPointF(t - w, o), QPointF(t + w, o))

    def boundingRect(self) -> QRectF:
        """Вычисление границ элемента."""
        if self.data is None or len(self.data) == 0:
            return QRectF()

        # Находим границы данных
        times = [d[0] for d in self.data]
        highs = [d[2] for d in self.data]
        lows = [d[3] for d in self.data]

        min_time = min(times)
        max_time = max(times)
        min_price = min(lows)
        max_price = max(highs)

        # Добавляем небольшой отступ (согласовано с paint методом)
        step = (self.data[1][0] - self.data[0][0]) if len(self.data) > 1 else 1
        w = max(min(step * 0.25, 8.0), 2.0)

        return QRectF(min_time - w, min_price, max_time - min_time + 2 * w, max_price - min_price)


class GraphBackend(QObject):
    """
    Мост между JavaScript (WebEngine) и Python для интерактивных графиков.

    Обрабатывает запросы от JS и перенаправляет их в родительский компонент.
    """

    graphDataUpdated = Signal(dict)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

    @Slot(str, str)
    def requestFilteredGraph(self, filter_type: str, filter_value: str) -> None:
        """
        Принимает запрос на фильтрацию из JS и перенаправляет его в ядро.

        Args:
            filter_type: Тип фильтра (например, 'symbol', 'timeframe')
            filter_value: Значение фильтра
        """
        if self.parent():
            # Предполагается что parent имеет метод on_filter_request
            if hasattr(self.parent(), "on_filter_request"):
                self.parent().on_filter_request(filter_type, filter_value)

    @Slot()
    def jsReady(self) -> None:
        """Вызывается из JS, когда страница полностью загружена."""
        if self.parent():
            # Предполагается что parent имеет метод on_js_ready
            if hasattr(self.parent(), "on_js_ready"):
                self.parent().on_js_ready()

    def update_graph_data(self, data: Dict[str, Any]) -> None:
        """
        Обновление данных графика.

        Args:
            data: Данные для отрисовки
        """
        self.graphDataUpdated.emit(data)
