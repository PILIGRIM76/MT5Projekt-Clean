# -*- coding: utf-8 -*-
"""Графические виджеты для GUI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush


class GraphBackend(QObject):
    """Мост между JavaScript и Python для графиков."""
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
        self.data = candles
        self.data_loaded.emit(candles)

    def clear_data(self) -> None:
        self.data = []
        self.data_loaded.emit([])

    def add_indicator(self, indicator_data: Dict[str, Any]) -> None:
        self.indicators_loaded.emit(indicator_data)


class CustomCandlestickItem(pg.GraphicsObject):
    """
    Свечной график.
   paint() получает QPainter с уже настроенной трансформацией ViewBox,
    поэтому рисуем прямо в координатах данных.
    """

    def __init__(self) -> None:
        pg.GraphicsObject.__init__(self)
        self.candle_data: Optional[np.ndarray] = None
        self.bull_color = QColor("#00C853")
        self.bear_color = QColor("#FF1744")

    def setData(self, data: Optional[np.ndarray]) -> None:
        self.candle_data = data
        self.prepareGeometryChange()
        self.update()

    def paint(self, p: QPainter, *args: Any) -> None:
        if self.candle_data is None or len(self.candle_data) == 0:
            return

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        n = len(self.candle_data)
        if n < 2:
            return

        # Получаем ViewBox через parent chain
        vb = None
        item = self.parentItem()
        while item is not None:
            if hasattr(item, 'viewRect') and hasattr(item, 'size'):
                vb = item
                break
            item = item.parentItem()
        if vb is None:
            return

        vr = vb.viewRect()  # видимый диапазон в data coords
        vr_size = vb.size()  # размер viewport в пикселях
        if vr.width() <= 0 or vr.height() <= 0 or vr_size.width() <= 0 or vr_size.height() <= 0:
            return

        # Масштаб: data units → pixels
        sx = vr_size.width() / vr.width()
        sy = vr_size.height() / vr.height()

        # Ширина свечи
        step = float(self.candle_data[1, 0] - self.candle_data[0, 0])
        half_w = max(step * 0.3, 0.1) if step > 0 else 0.1

        for i in range(n):
            t = float(self.candle_data[i, 0])
            o = float(self.candle_data[i, 1])
            h = float(self.candle_data[i, 2])
            l = float(self.candle_data[i, 3])
            c = float(self.candle_data[i, 4])

            is_bull = c >= o
            color = self.bull_color if is_bull else self.bear_color

            # Конвертируем data coords → pixel coords
            px_t = (t - vr.left()) * sx
            px_h = (vr.top() - h) * sy  # Y инвертирован в экранных координатах
            px_l = (vr.top() - l) * sy
            px_o = (vr.top() - o) * sy
            px_c = (vr.top() - c) * sy
            px_hw = half_w * sx

            # Фитиль
            p.setPen(QPen(color, 1))
            p.setBrush(QBrush())
            p.drawLine(QPointF(px_t, px_h), QPointF(px_t, px_l))

            # Тело
            body_top_y = min(px_o, px_c)
            body_bot_y = max(px_o, px_c)
            body_h = body_bot_y - body_top_y

            if body_h >= 1:
                p.setPen(QPen(color, 1))
                p.setBrush(QBrush(color))
                p.drawRect(QRectF(px_t - px_hw, body_top_y, px_hw * 2, body_h))
            else:
                p.setPen(QPen(color, 2))
                p.setBrush(QBrush())
                p.drawLine(QPointF(px_t - px_hw, px_o), QPointF(px_t + px_hw, px_o))

    def boundingRect(self) -> QRectF:
        if self.candle_data is None or len(self.candle_data) == 0:
            return QRectF()

        x_min = float(self.candle_data[0, 0])
        x_max = float(self.candle_data[-1, 0])
        y_min = float(np.min(self.candle_data[:, 3]))
        y_max = float(np.max(self.candle_data[:, 2]))

        dx = (x_max - x_min) * 0.05 if x_max > x_min else 1.0
        dy = (y_max - y_min) * 0.05 if y_max > y_min else 0.001
        return QRectF(x_min - dx, y_min - dy, (x_max - x_min) + 2 * dx, (y_max - y_min) + 2 * dy)
