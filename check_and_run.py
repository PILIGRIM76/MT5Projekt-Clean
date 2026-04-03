#!/usr/bin/env python3
"""
Проверка готовности системы и запуск Genesis Trading System.
"""

import subprocess
import sys
import time
from pathlib import Path


def check_venv():
    """Проверка виртуального окружения."""
    venv_python = Path("venv/Scripts/python.exe")
    if not venv_python.exists():
        print("❌ Виртуальное окружение не найдено!")
        print("   Выполните: setup.bat")
        return False
    print("✓ Виртуальное окружение найдено")
    return True


def check_dependencies():
    """Проверка основных зависимостей."""
    required = ["PySide6", "pyqtgraph", "pydantic", "numpy", "pandas", "matplotlib", "MetaTrader5"]

    missing = []
    for package in required:
        try:
            __import__(package.lower())
            print(f"✓ {package}")
        except ImportError:
            print(f"❌ {package} не установлен")
            missing.append(package)

    if missing:
        print(f"\n❌ Отсутствуют пакеты: {', '.join(missing)}")
        print("\nУстановка...")
        pip_cmd = [sys.executable, "-m", "pip", "install"] + missing
        subprocess.run(pip_cmd, check=False)
        return False

    print("\n✓ Все зависимости установлены")
    return True


def check_config():
    """Проверка конфигурации."""
    if not Path(".env").exists():
        print("⚠ Файл .env не найден")
        print("   Скопируйте .env.example в .env и заполните данными")
        return False
    print("✓ Конфигурация найдена")
    return True


def run_application():
    """Запуск приложения."""
    print("\n" + "=" * 60)
    print("  ЗАПУСК GENESIS TRADING SYSTEM")
    print("=" * 60)
    print()

    main_py = Path("main_pyside.py")
    if not main_py.exists():
        print("❌ main_pyside.py не найден!")
        return False

    subprocess.run([sys.executable, str(main_py)], check=False)
    return True


def main():
    """Главная функция."""
    print("\n" + "╔" + "═" * 59 + "╗")
    print("║     Genesis Trading System - Проверка и запуск         ║")
    print("╚" + "═" * 59 + "╝")
    print()

    # Проверки
    checks = [
        ("Виртуальное окружение", check_venv),
        ("Зависимости", check_dependencies),
        ("Конфигурация", check_config),
    ]

    passed = 0
    for name, check_func in checks:
        print(f"[1/3] Проверка: {name}...")
        if check_func():
            passed += 1
        print()
        time.sleep(0.5)

    # Итог
    print("=" * 60)
    print(f"Пройдено проверок: {passed}/{len(checks)}")
    print("=" * 60)

    if passed == len(checks):
        # Все проверки пройдены - запускаем
        run_application()
    else:
        print("\n⚠ Не все проверки пройдены")
        print("\nДля установки выполните:")
        print("  setup.bat")
        print("\nИли установите зависимости вручную:")
        print("  pip install PySide6 pyqtgraph pydantic numpy pandas matplotlib MetaTrader5")
        input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
