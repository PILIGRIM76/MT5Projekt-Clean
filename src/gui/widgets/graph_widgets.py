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
    Пользовательский элемент для отрисовки свечей в стиле MT5.

    Особенности:
    - Бычьи свечи: зелёный (#00C853) с зелёной границей
    - Медвежьи свечи: красный (#FF1744) с красной границей
    - Фитили (high/low) тонкие (1px)
    - Тело свечи занимает ~70% ширины бара
    - Doji (open≈close) отображается как тонкая линия
    """

    def __init__(self) -> None:
        pg.GraphicsObject.__init__(self)
        self.data: Optional[List[Tuple[float, float, float, float, float]]] = None
        # MT5 цвета
        self.bull_color = QColor("#00C853")  # Зелёный для бычьих
        self.bear_color = QColor("#FF1744")  # Красный для медвежьих
        self.wick_width = 1.0  # Ширина фитиля
        self.body_ratio = 0.7  # Тело занимает 70% бара (как в MT5)

    def setData(self, data: Optional[List[Tuple[float, float, float, float, float]]]) -> None:
        """Устанавливает данные для отрисовки.

        Args:
            data: Список кортежей (timestamp, open, high, low, close)
        """
        self.data = data
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def _calculate_bar_width(self) -> float:
        """Ширина тела свечи = 50% от расстояния между барами."""
        if self.data is None or len(self.data) < 2:
            return 0.5
        step = float(self.data[1][0] - self.data[0][0])
        return step * 0.5 if step > 0 else 0.5

    def paint(self, p: QPainter, *args: Any) -> None:
        """Отрисовка свечей. Масштабирует X через viewBox transform."""
        if self.data is None or len(self.data) == 0:
            return

        bar_width = self._calculate_bar_width()
        half_width = bar_width / 2.0

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Получаем viewBox для конвертации X→пиксели
        x_scale = 1.0
        try:
            vb = self.parentItem().getViewBox()
            if vb is not None:
                vr = vb.viewRect()
                px = vb.viewport().width()
                if vr.width() > 0 and px > 0:
                    x_scale = px / vr.width()
        except Exception:
            pass

        # Y масштаб — берём из view
        y_scale = 1.0
        try:
            vr2 = vb.viewRect()
            py2 = vb.viewport().height()
            if vr2.height() > 0 and py2 > 0:
                y_scale = py2 / vr2.height()
        except Exception:
            pass

        for t, o, h, l, c in self.data:
            is_bullish = c >= o
            pen_color = self.bull_color if is_bullish else self.bear_color
            brush_color = pen_color

            # Конвертируем координаты X в пиксели
            px_t = t * x_scale

            # Рисуем фитиль (high→low)
            wick_pen = pg.mkPen(pen_color, width=self.wick_width)
            p.setPen(wick_pen)
            p.drawLine(QPointF(px_t, h * y_scale), QPointF(px_t, l * y_scale))

            # Тело свечи
            body_top = max(o, c)
            body_bottom = min(o, c)
            body_height_px = (body_top - body_bottom) * y_scale
            half_w_px = half_width * x_scale

            if body_height_px > 1:  # Минимум 1 пиксель
                body_pen = pg.mkPen(pen_color, width=1)
                body_brush = pg.mkBrush(brush_color)
                p.setPen(body_pen)
                p.setBrush(body_brush)
                body_rect = QRectF(px_t - half_w_px, body_top * y_scale, half_w_px * 2, body_height_px)
                p.drawRect(body_rect)
            else:
                # Doji — горизонтальная линия
                doji_pen = pg.mkPen(pen_color, width=2)
                p.setPen(doji_pen)
                y_mid = o * y_scale
                p.drawLine(QPointF(px_t - half_w_px, y_mid), QPointF(px_t + half_w_px, y_mid))

    def boundingRect(self) -> QRectF:
        """Ограничивающий прямоугольник для всех свечей."""
        if self.data is None or len(self.data) == 0:
            return QRectF()

        times = [d[0] for d in self.data]
        highs = [d[2] for d in self.data]
        lows = [d[3] for d in self.data]

        # Конвертируем в пиксели через view scale
        x_scale = 1.0
        y_scale = 1.0
        try:
            vb = self.parentItem().getViewBox()
            if vb is not None:
                vr = vb.viewRect()
                px = vb.viewport().width()
                py = vb.viewport().height()
                if vr.width() > 0 and px > 0:
                    x_scale = px / vr.width()
                if vr.height() > 0 and py > 0:
                    y_scale = py / vr.height()
        except Exception:
            pass

        px_times = [t * x_scale for t in times]
        py_highs = [h * y_scale for h in highs]
        py_lows = [l * y_scale for l in lows]

        min_x = min(px_times)
        max_x = max(px_times)
        min_y = min(py_lows)
        max_y = max(py_highs)

        bar_w_px = self._calculate_bar_width() * x_scale
        return QRectF(min_x - bar_w_px, min_y, max_x - min_x + bar_w_px * 2, max_y - min_y)
