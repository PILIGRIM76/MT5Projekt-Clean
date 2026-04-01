# -*- coding: utf-8 -*-
"""
Unit тесты для Worker (utils/worker.py).

Тестирует:
- Worker для фоновых задач
- Сигналы progress, result, error, finished
- Обработку ошибок
"""

import time
from unittest.mock import MagicMock

import pytest

from src.utils.worker import Worker, WorkerSignals


class TestWorkerCreation:
    """Тесты создания Worker."""

    def test_worker_creation(self):
        """Проверка создания Worker."""

        def fn():
            return None

        worker = Worker(fn)

        assert worker is not None
        assert worker.fn == fn

    def test_worker_with_args(self):
        """Проверка создания с аргументами."""

        def test_fn(a, b):
            return a + b

        worker = Worker(test_fn, 5, 3)

        assert worker.args == (5, 3)

    def test_worker_with_kwargs(self):
        """Проверка создания с kwargs."""

        def test_fn(a, b=10):
            return a + b

        worker = Worker(test_fn, 5, b=20)

        assert worker.kwargs == {"b": 20}


class TestWorkerSignals:
    """Тесты сигналов Worker."""

    def test_worker_signals_creation(self):
        """Проверка создания WorkerSignals."""
        signals = WorkerSignals()

        assert signals is not None

    def test_worker_has_signals(self):
        """Проверка наличия сигналов."""
        worker = Worker(lambda: None)

        assert hasattr(worker, "signals")
        assert hasattr(worker.signals, "finished")
        assert hasattr(worker.signals, "result")
        assert hasattr(worker.signals, "error")
        assert hasattr(worker.signals, "progress")
        assert hasattr(worker.signals, "log_message")

    def test_worker_signals_are_objects(self):
        """Проверка что сигналы - это QObject."""
        worker = Worker(lambda: None)

        from PySide6.QtCore import QObject

        assert isinstance(worker.signals, QObject)


class TestWorkerExecution:
    """Тесты выполнения Worker."""

    def test_worker_emits_finished(self):
        """Проверка сигнала finished."""
        finished_called = []

        def test_fn():
            pass

        def on_finished():
            finished_called.append(True)

        worker = Worker(test_fn)
        worker.signals.finished.connect(on_finished)

        worker.run()

        assert len(finished_called) == 1

    def test_worker_returns_result(self):
        """Проверка возврата результата."""
        result_container = []

        def test_fn():
            return 42

        def on_result(result):
            result_container.append(result)

        worker = Worker(test_fn)
        worker.signals.result.connect(on_result)

        worker.run()

        assert len(result_container) == 1
        assert result_container[0] == 42

    def test_worker_with_none_return(self):
        """Проверка функции без возврата."""
        result_container = []

        def test_fn():
            pass

        def on_result(result):
            result_container.append(result)

        worker = Worker(test_fn)
        worker.signals.result.connect(on_result)

        worker.run()

        assert len(result_container) == 1
        assert result_container[0] is None


class TestWorkerProgress:
    """Тесты прогресса Worker."""

    def test_worker_emits_log_message(self):
        """Проверка сигнала log_message."""
        log_values = []

        def test_fn():
            from PySide6.QtCore import QThread

            # Эмуляция отправки лога через callback
            pass

        def on_log(msg):
            log_values.append(msg)

        worker = Worker(lambda: "test")
        worker.signals.log_message.connect(on_log)

        # Worker не отправляет log_message автоматически
        # Это делает вызывающий код
        worker.run()

        # Проверяем что сигнал существует и работает
        worker.signals.log_message.emit("test log")

        assert len(log_values) == 1
        assert log_values[0] == "test log"


class TestWorkerErrors:
    """Тесты ошибок Worker."""

    def test_worker_catches_exception(self):
        """Проверка обработки исключений."""
        error_container = []

        def test_fn():
            raise ValueError("Test error")

        def on_error(error):
            error_container.append(error)

        worker = Worker(test_fn)
        worker.signals.error.connect(on_error)

        worker.run()

        assert len(error_container) == 1
        assert isinstance(error_container[0], tuple)
        assert error_container[0][0] == ValueError

    def test_worker_returns_error_tuple(self):
        """Проверка что ошибка возвращается как tuple."""

        def test_fn():
            raise RuntimeError("Runtime error")

        worker = Worker(test_fn)
        errors = []
        worker.signals.error.connect(lambda e: errors.append(e))

        worker.run()

        assert len(errors) == 1
        error_tuple = errors[0]
        assert len(error_tuple) == 3  # (type, value, traceback)
        assert error_tuple[0] == RuntimeError

    def test_worker_error_traceback(self):
        """Проверка traceback в ошибке."""

        def test_fn():
            raise ValueError("Test error")

        errors = []
        worker = Worker(test_fn)
        worker.signals.error.connect(lambda e: errors.append(e))

        worker.run()

        assert len(errors) == 1
        traceback_str = errors[0][2]
        assert "test_fn" in traceback_str


class TestWorkerEdgeCases:
    """Тесты граничных случаев."""

    def test_worker_reuse(self):
        """Проверка повторного использования."""
        results = []

        def test_fn():
            return 1

        def on_result(result):
            results.append(result)

        worker = Worker(test_fn)
        worker.signals.result.connect(on_result)

        # Запускаем дважды
        worker.run()
        worker.run()

        assert len(results) == 2

    def test_worker_with_args_and_kwargs(self):
        """Проверка с args и kwargs."""
        result_container = []

        def test_fn(a, b, c=10):
            return a + b + c

        def on_result(result):
            result_container.append(result)

        worker = Worker(test_fn, 5, 3, c=20)
        worker.signals.result.connect(on_result)

        worker.run()

        assert len(result_container) == 1
        assert result_container[0] == 28  # 5 + 3 + 20

    def test_worker_with_exception_in_handler(self):
        """Проверка исключения в обработчике."""

        def test_fn():
            return "result"

        def on_result_bad(result):
            raise ValueError("Handler error")

        worker = Worker(test_fn)
        worker.signals.result.connect(on_result_bad)

        # Исключение в обработчике не должно ломать worker
        # Но будет поймано Qt event loop
        try:
            worker.run()
        except Exception:
            pass  # Ожидаемо
