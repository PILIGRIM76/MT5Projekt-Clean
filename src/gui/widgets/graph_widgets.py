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
        """Вычисляет ширину одного бара на основе расстояния между барами.

        Работает как с секундами, так и с миллисекундами.
        """
        if self.data is None or len(self.data) < 2:
            return 3600000.0  # 1 час в миллисекундах по умолчанию

        # Расстояние между барами в координатах X (мс или секунды)
        step = float(self.data[1][0] - self.data[0][0])

        if step <= 0:
            return 3600000.0  # 1 час fallback

        # Тело занимает body_ratio (70%) от шага
        return step * self.body_ratio

    def paint(self, p: QPainter, *args: Any) -> None:
        """Отрисовка свечей в стиле MT5."""
        if self.data is None or len(self.data) == 0:
            return

        bar_width = self._calculate_bar_width()
        half_width = bar_width / 2.0

        # Включаем сглаживание для лучшего качества
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for t, o, h, l, c in self.data:
            # Определяем тип свечи
            is_bullish = c >= o

            if is_bullish:
                # Бычья свеча (цена выросла) - MT5 зелёный
                pen_color = self.bull_color
                brush_color = self.bull_color
            else:
                # Медвежья свеча (цена упала) - MT5 красный
                pen_color = self.bear_color
                brush_color = self.bear_color

            # Рисуем фитиль (high-low) - тонкая линия 1px
            wick_pen = pg.mkPen(pen_color, width=self.wick_width)
            p.setPen(wick_pen)
            p.drawLine(QPointF(t, h), QPointF(t, l))

            # Рисуем тело свечи
            body_top = max(o, c)
            body_bottom = min(o, c)
            body_height = body_top - body_bottom

            if body_height > 0.0001:  # Не Doji — есть тело
                # Граница тела тонкая
                body_pen = pg.mkPen(pen_color, width=1)
                body_brush = pg.mkBrush(brush_color)

                p.setPen(body_pen)
                p.setBrush(body_brush)

                # Прямоугольник тела
                body_rect = QRectF(t - half_width, body_bottom, bar_width, body_height)
                p.drawRect(body_rect)
            else:
                # Doji (open ≈ close) — горизонтальная линия
                doji_pen = pg.mkPen(pen_color, width=2)
                p.setPen(doji_pen)
                p.drawLine(QPointF(t - half_width, o), QPointF(t + half_width, o))

    def boundingRect(self) -> QRectF:
        """Вычисляет ограничивающий прямоугольник для всех свечей."""
        if self.data is None or len(self.data) == 0:
            return QRectF()

        times = [d[0] for d in self.data]
        highs = [d[2] for d in self.data]
        lows = [d[3] for d in self.data]

        min_time = min(times)
        max_time = max(times)
        min_price = min(lows)
        max_price = max(highs)

        # Добавляем небольшой отступ
        bar_width = self._calculate_bar_width()
        padding = bar_width / 2.0

        return QRectF(min_time - padding, min_price, max_time - min_time + bar_width, max_price - min_price)
