"""Скрипт для исправления вызовов getattr(..., None)() в main_pyside.py"""

import re

with open("main_pyside.py", "r", encoding="utf-8") as f:
    content = f.read()

# Находим все места где getattr вызывается напрямую без проверки
# Pattern: getattr(..., None)() → нужно добавить проверку

# Простой паттерн для замены
content = re.sub(
    r'getattr\(getattr\(self\.trading_system, "core_system", None\), "([^"]+)", None\)\(\)',
    r"""# Проверка перед вызовом
                _method = getattr(
                    getattr(self.trading_system, "core_system", None),
                    "\1",
                    None,
                )
                if _method:
                    _method()""",
    content,
)

with open("main_pyside.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ Исправлены вызовы getattr(..., None)()")
