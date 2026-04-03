# -*- coding: utf-8 -*-
"""
Genesis Trading System - Minimal Test Version
Запускается без GUI для проверки импортов
"""

import os
import sys

# Удаляем прокси
for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(proxy_var, None)

print("=" * 60)
print("  Genesis Trading System - Проверка импортов")
print("=" * 60)
print()

# Проверка основных модулей
modules_to_check = ["numpy", "pandas", "matplotlib", "pyqtgraph", "pydantic", "MetaTrader5", "dotenv", "cryptography"]

print("Проверка модулей:")
for module in modules_to_check:
    try:
        __import__(module)
        print(f"  ✓ {module}")
    except ImportError as e:
        print(f"  ✗ {module}: {e}")

print()

# Проверка модулей проекта
print("Проверка модулей проекта:")
try:
    from src.core import config_loader, trading_system

    print("  ✓ src.core.config_loader")
    print("  ✓ src.core.trading_system")
except ImportError as e:
    print(f"  ✗ Ошибка: {e}")

try:
    from src.data import data_provider

    print("  ✓ src.data.data_provider")
except ImportError as e:
    print(f"  ✗ {e}")

try:
    from src.ml import consensus_engine

    print("  ✓ src.ml.consensus_engine")
except ImportError as e:
    print(f"  ✗ {e}")

print()
print("=" * 60)
print("  Проверка завершена!")
print("=" * 60)
print()
print("Примечание: PySide6 всё ещё загружается.")
print("Полноценный GUI будет доступен после его установки.")
print()
print("Для продолжения загрузки PySide6 выполните:")
print("  pip install PySide6")
