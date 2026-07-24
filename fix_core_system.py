"""Скрипт для исправления всех обращений к core_system в main_pyside.py"""

import re

with open("main_pyside.py", "r", encoding="utf-8") as f:
    content = f.read()

# Паттерн 1: self.trading_system.core_system.XXX
# Заменяем на безопасный getattr
content = re.sub(
    r"self\.trading_system\.core_system\.(\w+)",
    r'getattr(getattr(self.trading_system, "core_system", None), "\1", None)',
    content,
)

# Паттерн 2: self.core_system.XXX (внутри классов)
content = re.sub(
    r"self\.core_system\.(\w+)",
    r'getattr(getattr(self, "core_system", None), "\1", None)',
    content,
)

# Паттерн 3: adapter.core_system.XXX
content = re.sub(
    r"adapter\.core_system\.(\w+)",
    r'getattr(getattr(adapter, "core_system", None), "\1", None)',
    content,
)

with open("main_pyside.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ Все обращения к core_system исправлены")
