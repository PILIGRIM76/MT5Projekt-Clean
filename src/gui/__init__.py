# -*- coding: utf-8 -*-
"""
src/gui — Модули графического интерфейса Genesis Trading System
"""

from src.gui.animation_manager import AnimationManager
from src.gui.custom_title_bar import CustomTitleBar
from src.gui.styles import DARK_STYLE, LIGHT_STYLE, get_light_theme_qss, load_qss_file

__all__ = [
    "AnimationManager",
    "CustomTitleBar",
    "DARK_STYLE",
    "LIGHT_STYLE",
    "get_light_theme_qss",
    "load_qss_file",
]
