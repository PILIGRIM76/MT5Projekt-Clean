"""
Тесты для ResourceGovernor — контроль CPU/RAM/GPU.
"""

import time
import threading
import pytest
from unittest.mock import patch, MagicMock

from src.core.resource_governor import (
    ResourceGovernor,
    ResourceClass,
    DEFAULT_LIMITS,
)


class TestResourceGovernor:
    """Тесты ResourceGovernor."""

    def setup_method(self):
        """Сбрасывает singleton перед каждым тестом."""
        ResourceGovernor._instance = None
        ResourceGovernor._singleton_lock = threading.Lock()

    def test_singleton_pattern(self):
        """Проверка: только один экземпляр."""
        gov1 = ResourceGovernor()
        gov2 = ResourceGovernor()
        assert gov1 is gov2

    def test_can_start_critical_always_allowed(self):
        """Проверка: CRITICAL задачи всегда разрешены (при низких лимитах)."""
        gov = ResourceGovernor()
        assert gov.can_start("trade_cycle", ResourceClass.CRITICAL)
        gov.task_finished("trade_cycle")

    def test_task_tracking(self):
        """Проверка: отслеживание активных задач."""
        gov = ResourceGovernor()
        assert gov.can_start("task_1", ResourceClass.HIGH)
        assert gov.can_start("task_2", ResourceClass.MEDIUM)

        summary = gov.get_load_summary()
        assert summary["active_tasks"] == 2

        gov.task_finished("task_1")
        summary = gov.get_load_summary()
        assert summary["active_tasks"] == 1

        gov.task_finished("task_2")
        summary = gov.get_load_summary()
        assert summary["active_tasks"] == 0

    def test_task_finished_returns_duration(self):
        """Проверка: task_finished возвращает время выполнения."""
        gov = ResourceGovernor()
        gov.can_start("timed_task", ResourceClass.LOW)
        time.sleep(0.1)
        duration = gov.task_finished("timed_task")
        assert duration is not None
        assert duration >= 0.1

    def test_task_finished_unknown_task(self):
        """Проверка: task_finished для несуществующей задачи."""
        gov = ResourceGovernor()
        duration = gov.task_finished("unknown_task")
        assert duration is None

    @patch("src.core.resource_governor.HAS_PSUTIL", False)
    def test_without_psutil_always_allows(self):
        """Проверка: без psutil всегда разрешает задачи."""
        gov = ResourceGovernor()
        assert gov.can_start("no_psutil_task", ResourceClass.MEDIUM)
        gov.task_finished("no_psutil_task")

    def test_rejected_count_tracking(self):
        """Проверка: отслеживание отклонённых задач."""
        gov = ResourceGovernor()
        gov.can_start("task_1", ResourceClass.HIGH)
        gov.task_finished("task_1")

        summary = gov.get_load_summary()
        assert summary["rejected_tasks"] == 0
        assert summary["total_tasks"] == 1

    def test_reset_stats(self):
        """Проверка: сброс статистики."""
        gov = ResourceGovernor()
        gov.can_start("task_1", ResourceClass.HIGH)
        gov.task_finished("task_1")

        gov.reset_stats()
        summary = gov.get_load_summary()
        assert summary["total_tasks"] == 0
        assert summary["rejected_tasks"] == 0

    def test_is_overloaded_without_psutil(self):
        """Проверка: is_overloaded без psutil."""
        gov = ResourceGovernor()
        assert gov.is_overloaded() is False

    def test_kill_low_priority_tasks(self):
        """Проверка: принудительное завершение LOW задач."""
        gov = ResourceGovernor()
        gov.can_start("critical_task", ResourceClass.CRITICAL)
        gov.can_start("medium_task", ResourceClass.MEDIUM)
        gov.can_start("low_task_1", ResourceClass.LOW)
        gov.can_start("low_task_2", ResourceClass.LOW)

        killed = gov.kill_low_priority_tasks(ResourceClass.LOW)
        assert len(killed) == 2
        assert "low_task_1" in killed
        assert "low_task_2" in killed

        # CRITICAL и MEDIUM не тронуты
        summary = gov.get_load_summary()
        assert summary["active_tasks"] == 2

    def test_get_load_summary_structure(self):
        """Проверка: структура load summary."""
        gov = ResourceGovernor()
        summary = gov.get_load_summary()

        assert "active_tasks" in summary
        assert "total_tasks" in summary
        assert "rejected_tasks" in summary
        assert isinstance(summary["active_tasks"], int)


class TestResourceClass:
    """Тесты ResourceClass enum."""

    def test_all_classes_defined(self):
        """Проверка: все 4 класса определены."""
        assert ResourceClass.CRITICAL.value == 1
        assert ResourceClass.HIGH.value == 2
        assert ResourceClass.MEDIUM.value == 3
        assert ResourceClass.LOW.value == 4

    def test_limits_cover_all_classes(self):
        """Проверка: лимиты определены для всех классов."""
        for rclass in ResourceClass:
            assert rclass in DEFAULT_LIMITS
            assert "cpu_pct" in DEFAULT_LIMITS[rclass]
            assert "ram_gb" in DEFAULT_LIMITS[rclass]
            assert "gpu_mem_gb" in DEFAULT_LIMITS[rclass]
