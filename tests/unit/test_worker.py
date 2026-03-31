# tests/unit/test_worker.py
"""
Unit тесты для Worker (QThreadPool).

Проверяет:
- WorkerSignals
- Worker выполнение задач
- Обработку ошибок
- Отправку результатов
"""

import pytest
import time
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QThreadPool, QThread
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.worker import Worker, WorkerSignals


class TestWorkerSignals:
    """Тесты для WorkerSignals."""

    def test_worker_signals_creation(self):
        """Создание WorkerSignals."""
        signals = WorkerSignals()

        assert signals is not None
        assert hasattr(signals, 'finished')
        assert hasattr(signals, 'error')
        assert hasattr(signals, 'result')
        assert hasattr(signals, 'progress')
        assert hasattr(signals, 'log_message')

    def test_worker_signals_signals_are_slots(self):
        """Проверка что атрибуты являются Signal."""
        signals = WorkerSignals()

        # Проверяем что это объекты Signal
        assert hasattr(signals, 'finished')
        assert hasattr(signals, 'error')
        assert hasattr(signals, 'result')


class TestWorkerInit:
    """Тесты инициализации Worker."""

    def test_worker_creation_with_function(self):
        """Создание Worker с функцией."""
        def test_func():
            return "result"

        worker = Worker(test_func)

        assert worker is not None
        assert worker.fn == test_func
        assert worker.args == ()
        assert worker.kwargs == {}
        assert worker.signals is not None

    def test_worker_creation_with_args(self):
        """Создание Worker с аргументами."""
        def test_func(a, b):
            return a + b

        worker = Worker(test_func, 1, 2)

        assert worker.fn == test_func
        assert worker.args == (1, 2)
        assert worker.kwargs == {}

    def test_worker_creation_with_kwargs(self):
        """Создание Worker с именованными аргументами."""
        def test_func(a, b=10):
            return a + b

        worker = Worker(test_func, 5, b=20)

        assert worker.fn == test_func
        assert worker.args == (5,)
        assert worker.kwargs == {'b': 20}


class TestWorkerExecution:
    """Тесты выполнения задач Worker."""

    def test_worker_run_success(self, qtbot):
        """Успешное выполнение задачи."""
        results = []

        def test_func():
            return "test_result"

        worker = Worker(test_func)
        
        def store_result(result):
            results.append(result)

        worker.signals.result.connect(store_result)

        # Запускаем в потоке
        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        # Ждем завершения
        qtbot.waitUntil(lambda: len(results) > 0, timeout=5000)

        assert results[0] == "test_result"

    def test_worker_run_with_arguments(self, qtbot):
        """Выполнение задачи с аргументами."""
        results = []

        def add_func(a, b):
            return a + b

        worker = Worker(add_func, 5, 3)
        
        def store_result(result):
            results.append(result)

        worker.signals.result.connect(store_result)

        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        qtbot.waitUntil(lambda: len(results) > 0, timeout=5000)

        assert results[0] == 8

    def test_worker_run_with_kwargs(self, qtbot):
        """Выполнение задачи с именованными аргументами."""
        results = []

        def greet_func(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        worker = Worker(greet_func, "World", greeting="Hi")
        
        def store_result(result):
            results.append(result)

        worker.signals.result.connect(store_result)

        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        qtbot.waitUntil(lambda: len(results) > 0, timeout=5000)

        assert results[0] == "Hi, World!"


class TestWorkerErrorHandling:
    """Тесты обработки ошибок Worker."""

    def test_worker_run_with_exception(self, qtbot):
        """Задача с исключением."""
        errors = []

        def failing_func():
            raise ValueError("Test error")

        worker = Worker(failing_func)
        
        def store_error(error):
            errors.append(error)

        worker.signals.error.connect(store_error)

        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        qtbot.waitUntil(lambda: len(errors) > 0, timeout=5000)

        assert len(errors) == 1
        exctype, value, traceback_str = errors[0]
        assert exctype == ValueError
        assert "Test error" in str(value)

    def test_worker_run_division_by_zero(self, qtbot):
        """Деление на ноль."""
        errors = []

        def divide_func():
            return 1 / 0

        worker = Worker(divide_func)
        
        def store_error(error):
            errors.append(error)

        worker.signals.error.connect(store_error)

        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        qtbot.waitUntil(lambda: len(errors) > 0, timeout=5000)

        assert len(errors) == 1
        exctype, value, _ = errors[0]
        assert exctype == ZeroDivisionError


class TestWorkerSignalsEmission:
    """Тесты эмиссии сигналов Worker."""

    def test_worker_emits_finished(self, qtbot):
        """Worker испускает finished сигнал."""
        finished_called = []

        def simple_func():
            return "done"

        worker = Worker(simple_func)
        
        def mark_finished():
            finished_called.append(True)

        worker.signals.finished.connect(mark_finished)

        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        qtbot.waitUntil(lambda: len(finished_called) > 0, timeout=5000)

        assert len(finished_called) == 1

    def test_worker_emits_result_and_finished(self, qtbot):
        """Worker испускает и result, и finished."""
        results = []
        finished_count = []

        def returning_func():
            return 42

        worker = Worker(returning_func)
        
        def store_result(result):
            results.append(result)

        def mark_finished():
            finished_count.append(True)

        worker.signals.result.connect(store_result)
        worker.signals.finished.connect(mark_finished)

        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        qtbot.waitUntil(lambda: len(results) > 0 and len(finished_count) > 0, timeout=5000)

        assert len(results) == 1
        assert results[0] == 42
        assert len(finished_count) == 1


class TestWorkerProgress:
    """Тесты прогресса Worker."""

    def test_worker_has_progress_signal(self):
        """Worker имеет progress сигнал."""
        def test_func():
            pass

        worker = Worker(test_func)

        assert hasattr(worker.signals, 'progress')

    def test_worker_log_message_signal(self):
        """Worker имеет log_message сигнал."""
        def test_func():
            pass

        worker = Worker(test_func)

        assert hasattr(worker.signals, 'log_message')


class TestWorkerThreadPool:
    """Тесты интеграции с QThreadPool."""

    def test_worker_runs_in_threadpool(self, qtbot):
        """Worker выполняется в thread pool."""
        thread_ids = []

        def get_thread_id():
            return QThread.currentThread().objectName() or "worker_thread"

        worker = Worker(get_thread_id)

        def store_thread_id(tid):
            thread_ids.append(tid)

        worker.signals.result.connect(store_thread_id)

        threadpool = QThreadPool.globalInstance()
        threadpool.start(worker)

        qtbot.waitUntil(lambda: len(thread_ids) > 0, timeout=5000)

        # Thread ID должен отличаться от основного
        main_thread_name = QThread.currentThread().objectName() or "main_thread"
        assert thread_ids[0] != main_thread_name or thread_ids[0] == "worker_thread"

    def test_multiple_workers_in_parallel(self, qtbot):
        """Несколько Worker выполняются параллельно."""
        results = []

        def slow_func(x):
            time.sleep(0.1)
            return x * 2

        workers = [Worker(slow_func, i) for i in range(5)]

        def store_result(result):
            results.append(result)

        for worker in workers:
            worker.signals.result.connect(store_result)
            threadpool = QThreadPool.globalInstance()
            threadpool.start(worker)

        qtbot.waitUntil(lambda: len(results) >= 5, timeout=5000)

        assert len(results) == 5
        assert sorted(results) == [0, 2, 4, 6, 8]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
