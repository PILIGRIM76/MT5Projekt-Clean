# -*- coding: utf-8 -*-
"""Миксины для MainWindow — вынесенные панели, графики, сигналы."""

from src.gui.main_window_parts.panels import PanelsMixin
from src.gui.main_window_parts.charts import ChartsMixin
from src.gui.main_window_parts.signals import SignalsMixin

__all__ = ["PanelsMixin", "ChartsMixin", "SignalsMixin"]
