"""
Тесты для PriorityTaskQueue — приоритетная очередь задач.
"""

import time
import threading
import pytest

from src.core.task_queue import (
    PriorityTaskQueue,
    Priority,
    Task,
)


class TestPriorityTaskQueue:
    """Тесты PriorityTaskQueue."""

    def setup_method(self):
        # Reset global queue
        import src.core.task_queue as tq
        if tq._global_queue is not None:
            tq._global_queue.stop(timeout=2.0)
            tq._global_queue = None
        
        self.queue = PriorityTaskQueue(max_workers=2)
        self.queue.start()

    def teardown_method(self):
        self.queue.stop(timeout=5.0)
        # Reset global queue
        import src.core.task_queue as tq
        if tq._global_queue is not None:
            tq._global_queue.stop(timeout=2.0)
            tq._global_queue = None

    def test_submit_and_execute(self):
        """Проверка: задача выполняется."""
        results = []

        def my_task(x):
            results.append(x * 2)

        task_id = self.queue.submit(my_task, args=(5,), priority=Priority.HIGH)
        result = self.queue.get_result(task_id, timeout=10.0)

        assert result is not None, "Task result should not be None"
        assert result["success"] is True
        assert result["result"] == 10, f"Expected 10, got {result.get('result')}"
        assert results == [10]

    def test_priority_order(self):
        """Проверка: задачи с высоким приоритетом выполняются первыми."""
        execution_order = []
        lock = threading.Lock()

        def ordered_task(name):
            with lock:
                execution_order.append(name)
            time.sleep(0.05)

        # Запускаем задачи с разными приоритетами
        self.queue.submit(ordered_task, args=("low",), priority=Priority.LOW)
        self.queue.submit(ordered_task, args=("medium",), priority=Priority.MEDIUM)
        self.queue.submit(ordered_task, args=("high",), priority=Priority.HIGH)
        self.queue.submit(ordered_task, args=("urgent",), priority=Priority.URGENT)

        # Ждём выполнения
        time.sleep(0.5)

        # URGENT должен быть первым
        if len(execution_order) > 0:
            assert execution_order[0] == "urgent"

    def test_task_timeout(self):
        """Проверка: задача с таймаутом прерывается."""

        def slow_task():
            time.sleep(10)  # Дольше чем таймаут

        task_id = self.queue.submit(
            slow_task, priority=Priority.LOW, timeout=0.5
        )
        result = self.queue.get_result(task_id, timeout=2.0)

        assert result is not None
        assert result["success"] is False
        assert "Timeout" in result["error"]

    def test_task_error_handling(self):
        """Проверка: ошибка в задаче обрабатывается корректно."""

        def failing_task():
            raise ValueError("Тестовая ошибка")

        task_id = self.queue.submit(failing_task, priority=Priority.MEDIUM)
        result = self.queue.get_result(task_id, timeout=5.0)

        assert result is not None
        assert result["success"] is False
        assert "Тестовая ошибка" in result["error"]

    def test_get_result_timeout(self):
        """Проверка: get_result возвращает None при таймауте."""
        task_id = "nonexistent_task_123"
        result = self.queue.get_result(task_id, timeout=0.1)
        assert result is None

    def test_stats_tracking(self):
        """Проверка: статистика отслеживается."""

        def simple_task():
            return "done"

        def failing_task():
            raise RuntimeError("fail")

        self.queue.submit(simple_task, priority=Priority.HIGH)
        self.queue.submit(simple_task, priority=Priority.HIGH)
        self.queue.submit(failing_task, priority=Priority.HIGH)

        time.sleep(0.5)
        stats = self.queue.get_stats()

        assert stats["submitted"] == 3
        assert stats["completed"] == 2
        assert stats["failed"] == 1

    def test_clear_queue(self):
        """Проверка: очистка очереди."""

        def slow_task():
            time.sleep(5)

        # Заполняем очередь
        for i in range(10):
            self.queue.submit(slow_task, priority=Priority.LOW, timeout=10)

        stats = self.queue.get_stats()
        assert stats["queue_size"] >= 10

        # Очищаем
        self.queue.clear()
        stats = self.queue.get_stats()
        assert stats["queue_size"] == 0

    def test_task_with_kwargs(self):
        """Проверка: задача с именованными аргументами."""

        def task_with_kwargs(a, b, c=0):
            return a + b + c

        task_id = self.queue.submit(
            task_with_kwargs, args=(1, 2), kwargs={"c": 3}, priority=Priority.HIGH
        )
        result = self.queue.get_result(task_id, timeout=5.0)

        assert result["success"] is True
        assert result["result"] == 6

    def test_custom_task_id(self):
        """Проверка: пользовательский ID задачи."""
        task_id = self.queue.submit(
            lambda: "ok", priority=Priority.HIGH, task_id="my_custom_id"
        )
        assert task_id == "my_custom_id"


class TestPriorityEnum:
    """Тесты Priority enum."""

    def test_ordering(self):
        """Проверка: приоритеты упорядочены правильно."""
        assert Priority.URGENT < Priority.HIGH
        assert Priority.HIGH < Priority.MEDIUM
        assert Priority.MEDIUM < Priority.LOW

    def test_values(self):
        """Проверка: значения приоритетов."""
        assert Priority.URGENT.value == 0
        assert Priority.HIGH.value == 1
        assert Priority.MEDIUM.value == 2
        assert Priority.LOW.value == 3


class TestTaskDataclass:
    """Тесты Task dataclass."""

    def test_task_ordering(self):
        """Проверка: задачи сортируются по приоритету."""
        import heapq

        tasks = [
            Task(priority=Priority.LOW, sort_key=1.0, task_id="t1", func=lambda: None),
            Task(
                priority=Priority.URGENT, sort_key=2.0, task_id="t2", func=lambda: None
            ),
            Task(priority=Priority.HIGH, sort_key=3.0, task_id="t3", func=lambda: None),
        ]

        heapq.heapify(tasks)
        first = heapq.heappop(tasks)
        assert first.priority == Priority.URGENT
