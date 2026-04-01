# -*- coding: utf-8 -*-
"""Графические виджеты для GUI."""

from typing import Any, Dict, List, Optional

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, Signal
from PySide6.QtGui import QColor


class GraphBackend(QObject):
    """
    Мост между JavaScript и Python для интерактивных графиков.
    Обрабатывает запросы от TradingView Lightweight Charts.
    """

    # Сигналы для отправки данных в JS
    data_loaded = Signal(object)  # Данные свечей
    indicators_loaded = Signal(object)  # Индикаторы

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.chart = None
        self.histogram_series = None
        self.data = []

    def load_data(self, candles: List[Dict[str, Any]]):
        """Загружает данные свечей в график."""
        self.data = candles
        self.data_loaded.emit(candles)

    def clear_data(self):
        """Очищает данные графика."""
        self.data = []
        self.data_loaded.emit([])

    def add_indicator(self, indicator_data: Dict[str, Any]):
        """Добавляет индикатор на график."""
        self.indicators_loaded.emit(indicator_data)


class CustomCandlestickItem(pg.GraphicsObject):
    """
    Пользовательский элемент для отрисовки свечей на графике pyqtgraph.
    """

    def __init__(self):
        pg.GraphicsObject.__init__(self)
        self.data = None

    def setData(self, data: Optional[List[tuple]]):
        """Устанавливает данные для отрисовки."""
        self.data = data
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def paint(self, p, *args):
        if self.data is None or len(self.data) < 2:
            return

        # Вычисляем ширину свечи адаптивно (фиксированный процент от шага)
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

            p.setPen(pen)
            p.setBrush(brush)

            body_top = max(o, c)
            body_bottom = min(o, c)
            body_height = body_top - body_bottom

            # Рисуем верхнюю тень (от high до верха тела)
            p.drawLine(QPointF(t, h), QPointF(t, body_top))
            # Рисуем нижнюю тень (от low до низа тела)
            p.drawLine(QPointF(t, l), QPointF(t, body_bottom))

            # Рисуем тело с ограниченной шириной
            if body_height > 0:
                p.drawRect(QRectF(t - w, body_bottom, w * 2, body_height))
            else:
                # Если open == close, рисуем горизонтальную линию
                p.drawLine(QPointF(t - w, o), QPointF(t + w, o))

    def boundingRect(self):
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
