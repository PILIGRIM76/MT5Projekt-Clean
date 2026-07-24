# -*- coding: utf-8 -*-
"""
Утилиты для стилизации pyqtgraph виджетов.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtGui import QColor

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


def apply_theme_to_plot_widget(plot_widget: pg.PlotWidget, is_light: bool) -> None:
    """
    Применяет тему к существующему PlotWidget.

    Args:
        plot_widget: Виджет графика
        is_light: True для светлой темы, False для тёмной
    """
    try:
        plot_item = plot_widget.getPlotItem()
        if plot_item is None:
            return

        if is_light:
            # Светлая тема
            plot_widget.setBackground(QColor("#FFFFFF"))

            # Цвет текста и осей
            text_color = QColor("#1A1D23")
            grid_color = QColor("#E5E7EB")
            axis_color = QColor("#374151")

            # Настройка оси X (если это DateAxis)
            for axis_pos in ["bottom", "left", "top", "right"]:
                try:
                    axis = plot_item.getAxis(axis_pos)
                    if axis is not None:
                        axis.setPen(axis_color)
                        axis.setTextPen(text_color)
                        axis.setGrid(grid_color)
                except Exception:
                    pass

            # Цвет заголовка
            if plot_item.titleLabel is not None:
                plot_item.titleLabel.setText(color=text_color)

        else:
            # Тёмная тема (Dracula)
            plot_widget.setBackground(QColor("#282a36"))

            text_color = QColor("#f8f8f2")
            grid_color = QColor("#44475a")
            axis_color = QColor("#6272a4")

            for axis_pos in ["bottom", "left", "top", "right"]:
                try:
                    axis = plot_item.getAxis(axis_pos)
                    if axis is not None:
                        axis.setPen(axis_color)
                        axis.setTextPen(text_color)
                        axis.setGrid(grid_color)
                except Exception:
                    pass

            if plot_item.titleLabel is not None:
                plot_item.titleLabel.setText(color=text_color)

    except Exception as e:
        logger.debug(f"[ChartTheme] Ошибка стилизации PlotWidget: {e}")


def apply_theme_to_all_plots(main_window, is_light: bool) -> None:
    """
    Применяет тему ко всем графикам главного окна.

    Args:
        main_window: Экземпляр MainWindow
        is_light: True для светлой темы, False для тёмной
    """
    # Список всех атрибутов с графиками
    plot_attrs = [
        # Основной график свечей
        "price_plot",
        "volume_plot",
        # Графики аналитики
        "loss_plot_widget",
        "model_accuracy_plot_widget",
        "retrain_progress_widget",
        "pnl_plot_widget",
        "observer_pnl_plot_widget",
        "drift_plot_widget",
        "orchestrator_chart_widget",
    ]

    applied_count = 0
    for attr_name in plot_attrs:
        try:
            plot_widget = getattr(main_window, attr_name, None)
            if plot_widget is not None and isinstance(plot_widget, pg.PlotWidget):
                apply_theme_to_plot_widget(plot_widget, is_light)
                applied_count += 1
        except Exception as e:
            logger.debug(f"[ChartTheme] Ошибка обработки {attr_name}: {e}")

    theme_name = "светлая" if is_light else "тёмная"
    logger.info(f"[ChartTheme] Применена {theme_name} тема к {applied_count} графикам")


def apply_theme_to_candlestick_item(candlestick_item, is_light: bool) -> None:
    """
    Обновляет цвета элемента свечей при смене темы.

    Args:
        candlestick_item: Экземпляр CustomCandlestickItem
        is_light: True для светлой темы, False для тёмной
    """
    try:
        if candlestick_item is None:
            return

        if is_light:
            # Более яркие цвета для светлой темы
            candlestick_item.bull_color = QColor("#059669")  # Изумрудный зелёный
            candlestick_item.bear_color = QColor("#DC2626")  # Яркий красный
        else:
            # Цвета для тёмной темы (MT5 стиль)
            candlestick_item.bull_color = QColor("#00C853")  # Зелёный
            candlestick_item.bear_color = QColor("#FF1744")  # Красный

        candlestick_item.update()
    except Exception as e:
        logger.debug(f"[ChartTheme] Ошибка стилизации candlestick: {e}")
