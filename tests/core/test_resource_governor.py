"""
Тесты для ResourceGovernor — контроль CPU/RAM/GPU.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.core.resource_governor import (
    DEFAULT_LIMITS,
    AdaptiveResourceGovernor,
    ResourceBudget,
    ResourceClass,
    ResourceGovernor,
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

        # Задачи могут быть отклонены из-за RAM лимитов
        task1_started = gov.can_start("task_1", ResourceClass.HIGH)
        task2_started = gov.can_start("task_2", ResourceClass.MEDIUM)

        summary = gov.get_load_summary()
        expected_tasks = sum([task1_started, task2_started])
        assert summary["active_tasks"] == expected_tasks

        if task1_started:
            gov.task_finished("task_1")
            summary = gov.get_load_summary()
            assert summary["active_tasks"] == (1 if task2_started else 0)

        if task2_started:
            gov.task_finished("task_2")
            summary = gov.get_load_summary()
            assert summary["active_tasks"] == 0

    def test_task_finished_returns_duration(self):
        """Проверка: task_finished возвращает время выполнения."""
        gov = ResourceGovernor()
        # Используем HIGH класс с менее строгими лимитами RAM
        if gov.can_start("timed_task", ResourceClass.HIGH):
            time.sleep(0.1)
            duration = gov.task_finished("timed_task")
            assert duration is not None
            assert duration >= 0.1
        else:
            pytest.skip("Task rejected due to system resource constraints")

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
        # LOW задачи могут быть отклонены из-за RAM лимитов
        low1_started = gov.can_start("low_task_1", ResourceClass.LOW)
        low2_started = gov.can_start("low_task_2", ResourceClass.LOW)

        killed = gov.kill_low_priority_tasks(ResourceClass.LOW)

        # Проверяем только реально запущенные задачи
        expected_killed = sum([low1_started, low2_started])
        assert len(killed) == expected_killed
        if low1_started:
            assert "low_task_1" in killed
        if low2_started:
            assert "low_task_2" in killed

        # CRITICAL и MEDIUM не тронуты
        summary = gov.get_load_summary()
        assert summary["active_tasks"] == 2 + expected_killed - len(killed)

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
            assert "ram_free_min_gb" in DEFAULT_LIMITS[rclass]
            assert "gpu_mem_gb" in DEFAULT_LIMITS[rclass]


class TestAdaptiveResourceGovernor:
    """Тесты AdaptiveResourceGovernor."""

    def test_initialization(self):
        """Проверка инициализации."""
        gov = AdaptiveResourceGovernor(total_cpu_cores=4, total_memory_gb=8.0)

        report = gov.get_usage_report()
        assert report["total_cpu_cores"] == 4
        assert report["total_memory_gb"] == 8.0
        assert report["active_components"] == 0

    @pytest.mark.asyncio
    async def test_acquire_and_release_resources(self):
        """Проверка выделения и освобождения ресурсов."""
        gov = AdaptiveResourceGovernor()

        budget = ResourceBudget(cpu_percent_max=50.0, memory_mb_max=1024)

        # Выделение
        result = await gov.acquire_resources("test_component", budget)
        assert result is True

        # Освобождение
        result = gov.release_resources("test_component")
        assert result is True

        # Проверка что компонент удалён
        report = gov.get_usage_report()
        assert report["active_components"] == 0

    @pytest.mark.asyncio
    async def test_duplicate_acquire_fails(self):
        """Проверка что повторное выделение fails."""
        gov = AdaptiveResourceGovernor()
        budget = ResourceBudget()

        result1 = await gov.acquire_resources("comp1", budget)
        assert result1 is True

        result2 = await gov.acquire_resources("comp1", budget)
        assert result2 is False  # Duplicate должен fail

        gov.release_resources("comp1")

    @pytest.mark.asyncio
    async def test_release_non_existent(self):
        """Проверка освобождения несуществующего компонента."""
        gov = AdaptiveResourceGovernor()
        result = gov.release_resources("non_existent")
        assert result is False

    def test_throttle_component(self):
        """Проверка throttling компонента."""
        import asyncio

        async def run_test():
            gov = AdaptiveResourceGovernor()
            budget = ResourceBudget(cpu_percent_max=80.0, memory_mb_max=2048)

            await gov.acquire_resources("throttle_test", budget)

            # Throttle на 50%
            result = gov.throttle_component("throttle_test", factor=0.5)
            assert result is True

            report = gov.get_usage_report()
            comp = report["components"]["throttle_test"]
            assert comp["budget"]["cpu_percent"] == 40.0  # 80 * 0.5
            assert comp["is_throttled"] is True

            gov.release_resources("throttle_test")

        asyncio.run(run_test())

    def test_unthrottle_component(self):
        """Проверка unthrottle компонента."""
        import asyncio

        async def run_test():
            gov = AdaptiveResourceGovernor()
            budget = ResourceBudget()

            await gov.acquire_resources("unthrottle_test", budget)
            gov.throttle_component("unthrottle_test")

            # Unthrottle
            result = gov.unthrottle_component("unthrottle_test")
            assert result is True

            report = gov.get_usage_report()
            comp = report["components"]["unthrottle_test"]
            assert comp["is_throttled"] is False

            gov.release_resources("unthrottle_test")

        asyncio.run(run_test())

    def test_throttle_non_existent(self):
        """Проверка throttling несуществующего компонента."""
        gov = AdaptiveResourceGovernor()
        result = gov.throttle_component("non_existent")
        assert result is False

    def test_usage_report_structure(self):
        """Проверка структуры отчёта."""
        gov = AdaptiveResourceGovernor()
        report = gov.get_usage_report()

        assert "active_components" in report
        assert "total_cpu_cores" in report
        assert "total_memory_gb" in report
        assert "components" in report
        assert isinstance(report["components"], dict)


class TestResourceBudget:
    """Тесты ResourceBudget."""

    def test_default_values(self):
        """Проверка значений по умолчанию."""
        budget = ResourceBudget()

        assert budget.cpu_percent_max == 50.0
        assert budget.memory_mb_max == 1024
        assert budget.timeout_seconds is None

    def test_custom_values(self):
        """Проверка кастомных значений."""
        budget = ResourceBudget(cpu_percent_max=80.0, memory_mb_max=4096, timeout_seconds=60.0)

        assert budget.cpu_percent_max == 80.0
        assert budget.memory_mb_max == 4096
        assert budget.timeout_seconds == 60.0
