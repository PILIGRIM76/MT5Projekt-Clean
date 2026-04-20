#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Запуск GUI с правильным EventBridge
"""

import logging
import sys

from PySide6.QtWidgets import QApplication

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("genesis")

from main_pyside import MainWindow, PySideTradingSystem, app_config_for_path
from src.gui.event_bridge import GUIEventBridge

if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("🚀 ЗАПУСК GUI APPLICATION С EVENTBRIDGE")
    logger.info("=" * 80)

    app = QApplication(sys.argv)
    app.setApplicationName("Genesis Trading System v24.0")
    app.setOrganizationName("NLP-Core-Team")

    logger.info("✅ QApplication создан")

    # Создаём EventBridge для связи GUI с ядром
    bridge = GUIEventBridge()
    logger.info("✅ GUIEventBridge создан")

    # Передаём bridge в PySideTradingSystem
    trading_system_adapter = PySideTradingSystem(config=app_config_for_path, bridge=bridge)
    system_adapter = trading_system_adapter

    # Создаём окно
    window = MainWindow(system_adapter, config=app_config_for_path)
    window.show()

    logger.info("✅ MainWindow создан и показан")
    logger.info("🎯 GUI запущен! Окно должно быть видно на экране.")

    sys.exit(app.exec())
