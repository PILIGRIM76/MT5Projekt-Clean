# src/utils/worker.py
import sys

from PySide6.QtCore import QThread, Signal, QRunnable, QThreadPool, QObject


class WorkerSignals(QObject):
    """
    Определяет сигналы, доступные от рабочего потока.
    """
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)
    log_message = Signal(str)

class Worker(QRunnable):
    """
    Рабочий класс для выполнения задач в QThreadPool.
    Наследуется от QRunnable, а не QThread, для использования пула потоков.
    """
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        # QObject должен быть импортирован для WorkerSignals
        self.signals = WorkerSignals()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        """
        Основная логика выполнения задачи.
        """
        try:
            # Выполняем переданную функцию
            result = self.fn(*self.args, **self.kwargs)
        except:
            # Отправляем информацию об ошибке
            import traceback
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            # Отправляем результат обратно в GUI
            self.signals.result.emit(result)
        finally:
            # Сигнал о завершении работы
            self.signals.finished.emit()

# Инициализация пула потоков в main_pyside.py
# self.threadpool = QThreadPool()
# self.threadpool.setMaxThreadCount(10) # Ограничиваем количество потоков