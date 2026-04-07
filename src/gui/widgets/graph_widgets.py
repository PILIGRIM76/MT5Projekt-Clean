# -*- coding: utf-8 -*-
"""Графические виджеты для GUI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter


class GraphBackend(QObject):
    """
    Мост между JavaScript и Python для интерактивных графиков.
    Обрабатывает запросы от TradingView Lightweight Charts.
    """

    data_loaded = Signal(object)
    indicators_loaded = Signal(object)
    graphDataUpdated = Signal(dict)

    def __init__(self, view: Any) -> None:
        super().__init__()
        self.view = view
        self.chart: Optional[Any] = None
        self.histogram_series: Optional[Any] = None
        self.data: List[Dict[str, Any]] = []

    def load_data(self, candles: List[Dict[str, Any]]) -> None:
        """Загружает данные свечей в график."""
        self.data = candles
        self.data_loaded.emit(candles)

    def clear_data(self) -> None:
        """Очищает данные графика."""
        self.data = []
        self.data_loaded.emit([])

    def add_indicator(self, indicator_data: Dict[str, Any]) -> None:
        """Добавляет индикатор на график."""
        self.indicators_loaded.emit(indicator_data)


class CustomCandlestickItem(pg.GraphicsObject):
    """
    Пользовательский элемент для отрисовки свечей на графике pyqtgraph.
    """

    def __init__(self) -> None:
        pg.GraphicsObject.__init__(self)
        self.data: Optional[List[Tuple[float, float, float, float, float]]] = None

    def setData(self, data: Optional[List[Tuple[float, float, float, float, float]]]) -> None:
        """Устанавливает данные для отрисовки."""
        self.data = data
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def paint(self, p: QPainter, *args: Any) -> None:
        if self.data is None or len(self.data) < 2:
            return

        if len(self.data) > 1:
            step = float(self.data[1][0] - self.data[0][0])
            if step <= 0:
                step = 1
            w = max(min(step * 0.25, 8.0), 2.0)
        else:
            w = 2.0

        for t, o, h, l, c in self.data:
            if c >= o:
                pen = pg.mkPen("g", width=1)
                brush = pg.mkBrush("g")
            else:
                pen = pg.mkPen("r", width=1)
                brush = pg.mkBrush("r")

            p.setPen(pen)
            p.setBrush(brush)

            body_top = max(o, c)
            body_bottom = min(o, c)
            body_height = body_top - body_bottom

            p.drawLine(QPointF(t, h), QPointF(t, body_top))
            p.drawLine(QPointF(t, l), QPointF(t, body_bottom))

            if body_height > 0:
                p.drawRect(QRectF(t - w, body_bottom, w * 2, body_height))
            else:
                p.drawLine(QPointF(t - w, o), QPointF(t + w, o))

    def boundingRect(self) -> QRectF:
        if self.data is None or len(self.data) == 0:
            return QRectF()

        times = [d[0] for d in self.data]
        highs = [d[2] for d in self.data]
        lows = [d[3] for d in self.data]

        min_time = min(times)
        max_time = max(times)
        min_price = min(lows)
        max_price = max(highs)

        step = (self.data[1][0] - self.data[0][0]) if len(self.data) > 1 else 1
        w = max(min(step * 0.25, 8.0), 2.0)

        return QRectF(min_time - w, min_price, max_time - min_time + 2 * w, max_price - min_price)
