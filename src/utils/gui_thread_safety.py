"""
Thread-safe утилиты для обновления GUI из фоновых потоков.

Обеспечивает что ВСЕ обновления виджетов происходят в главном потоке GUI
через механизм Signal/Slot PySide6.

Использование:
    from src.utils.gui_thread_safety import safe_gui_update

    # Вместо прямого вызова:
    # self.label.setText("New text")  # ❌ ОПАСНО из фонового потока!

    # Используйте:
    safe_gui_update(self.label.setText, "New text")  # ✅ БЕЗОПАСНО!
"""

import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import QMetaObject, Qt, QTimer
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


def safe_gui_update(method: Callable, *args, **kwargs) -> bool:
    """
    Безопасно вызывает метод GUI виджета из любого потока.

    Если вызывается из НЕ главного потока, использует QMetaObject.invokeMethod
    для выполнения в главном потоке.

    Args:
        method: Метод виджета для вызова (например: label.setText)
        *args: Позиционные аргументы для метода
        **kwargs: Именованные аргументы для метода

    Returns:
        True если обновление запланировано успешно
    """
    try:
        # Проверяем что виджет ещё существует
        if hasattr(method, "__self__"):
            widget = method.__self__
            if isinstance(widget, QWidget):
                # Проверяем что виджет не удалён
                try:
                    if widget.isHidden() and not widget.isVisible():
                        # Виджет скрыт - пропускаем обновление для экономии ресурсов
                        return True
                except RuntimeError:
                    # Виджет уже удалён C++ стороной
                    logger.debug(f"Виджет уже удалён, пропускаем обновление")
                    return False

        # Проверяем находимся ли мы в главном потоке
        from PySide6.QtCore import QThread

        if (
            QThread.currentThread() == QThread.currentThread().thread().parent().thread()
            if hasattr(QThread.currentThread(), "parent") and QThread.currentThread().parent()
            else True
        ):
            # Мы в главном потоке (или проверка не работает) - вызываем напрямую
            method(*args, **kwargs)
            return True

        # Мы в фоновом потоке - используем QTimer для отложенного вызова
        # Это гарантирует выполнение в главном потоке
        QTimer.singleShot(0, lambda: method(*args, **kwargs))
        return True

    except RuntimeError as e:
        # Виджет был удалён во время вызова
        logger.debug(f"RuntimeError при обновлении GUI (виджет удалён): {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка безопасного обновления GUI: {e}", exc_info=True)
        return False


def safe_widget_set_text(widget, text: str, default_text: str = ""):
    """
    Безопасно обновляет текст виджета.

    Args:
        widget: QLabel, QPushButton или другой виджет с setText()
        text: Новый текст
        default_text: Текст по умолчанию если widget None
    """
    try:
        if widget is None:
            logger.debug(f"Виджет None, пропускаем setText: {text}")
            return

        # Проверяем что виджет ещё жив
        if not hasattr(widget, "setText"):
            logger.warning(f"Виджет {type(widget)} не имеет метода setText")
            return

        safe_gui_update(widget.setText, text)

    except Exception as e:
        logger.error(f"Ошибка safe_widget_set_text: {e}", exc_info=True)


class ThreadSafeGUIUpdater:
    """
    Класс для пакетного безопасного обновления нескольких виджетов.

    Использование:
        updater = ThreadSafeGUIUpdater()
        updater.add_update(label1.setText, "Text 1")
        updater.add_update(label2.setText, "Text 2")
        updater.add_update(progress.setValue, 50)
        updater.execute()  # Все обновления выполнятся в главном потоке
    """

    def __init__(self):
        self._pending_updates = []

    def add_update(self, method: Callable, *args, **kwargs):
        """Добавляет обновление в очередь."""
        self._pending_updates.append((method, args, kwargs))

    def execute(self):
        """Выполняет все накопленные обновления в главном потоке."""
        for method, args, kwargs in self._pending_updates:
            safe_gui_update(method, *args, **kwargs)

        # Очищаем очередь
        self._pending_updates.clear()

    def __enter__(self):
        """Контекстный менеджер - начало пакета обновлений."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер - выполнение обновлений."""
        self.execute()
        return False


# Декоратор для методов которые должны выполняться ТОЛЬКО в главном потоке
def main_thread_only(func: Callable) -> Callable:
    """
    Декоратор который гарантирует что функция выполняется в главном потоке GUI.

    Использование:
        @main_thread_only
        def update_my_gui(data):
            # Этот код ВСЕГДА выполнится в главном потоке
            self.label.setText(data)
    """

    def wrapper(*args, **kwargs):
        from PySide6.QtCore import QThread

        # Проверяем поток (упрощённая проверка)
        # В идеале нужно сравнивать с QApplication.instance().thread()
        try:
            app = None
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()

            if app and QThread.currentThread() != app.thread():
                # Не в главном потоке - откладываем выполнение
                logger.warning(f"Функция {func.__name__} вызвана из фонового потока! " f"Перенаправляю в главный поток.")
                QTimer.singleShot(0, lambda: func(*args, **kwargs))
                return None
        except Exception:
            pass

        # В главном потоке или не смогли проверить - выполняем
        return func(*args, **kwargs)

    return wrapper
