# -*- coding: utf-8 -*-
"""
Диагностический запуск main_pyside.py с полным перехватом исключений.
"""

import ctypes
import sys
import traceback

# Установка режима полного трейсбека
sys._enablelegacyfswarning()


# Перехват всех необработанных исключений
def global_exception_handler(exctype, value, tb):
    print("\n" + "=" * 80, file=sys.stderr)
    print("КРИТИЧЕСКАЯ ОШИБКА В ПРИЛОЖЕНИИ", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"Тип: {exctype.__name__}", file=sys.stderr)
    print(f"Значение: {value}", file=sys.stderr)
    print("\nПолный стек вызовов:", file=sys.stderr)
    print("".join(traceback.format_exception(exctype, value, tb)), file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    # Записываем в файл
    with open("crash_dump.txt", "w", encoding="utf-8") as f:
        f.write(f"Тип: {exctype.__name__}\n")
        f.write(f"Значение: {value}\n\n")
        f.write("Полный стек вызовов:\n")
        f.write("".join(traceback.format_exception(exctype, value, tb)))

    # Показываем окно с ошибкой
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("КРИТИЧЕСКАЯ ОШИБКА")
        msg.setText(f"Произошла критическая ошибка: {exctype.__name__}")
        msg.setDetailedText("".join(traceback.format_exception(exctype, value, tb)))
        msg.exec()
    except:
        pass

    sys.exit(1)


sys.excepthook = global_exception_handler

# Теперь импортируем и запускаем main
print("=" * 60)
print("ДИАГНОСТИЧЕСКИЙ ЗАПУСК")
print("=" * 60)
print(f"Python: {sys.version}")
print(f"Platform: {sys.platform}")
print()

try:
    from main_pyside import main

    print("Запуск main()...")
    main()
except Exception as e:
    print(f"\nОшибка при запуске main(): {e}")
    traceback.print_exc()
    input("\nНажмите Enter для выхода...")
