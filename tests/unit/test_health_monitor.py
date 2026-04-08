"""
Тесты для HealthMonitor — мониторинг состояния системы.
"""

import time
import pytest
from unittest.mock import MagicMock, patch

from src.core.health_monitor import HealthMonitor
from src.core.resource_governor import ResourceGovernor, ResourceClass


class TestHealthMonitor:
    """Тесты HealthMonitor."""

    def setup_method(self):
        """Создаёт моки для зависимостей."""
        self.mock_governor = MagicMock()
        self.mock_governor.is_overloaded.return_value = False
        self.mock_governor.get_load_summary.return_value = {
            "cpu_pct": 45.0,
            "ram_used_gb": 4.0,
            "ram_total_gb": 16.0,
            "ram_pct": 25,
            "gpu_mem_gb": 0.5,
            "active_tasks": 2,
        }
        self.mock_governor.kill_low_priority_tasks.return_value = []

        self.mock_task_queue = MagicMock()
        self.mock_task_queue.get_stats.return_value = {
            "submitted": 10,
            "completed": 8,
            "failed": 1,
            "timed_out": 1,
            "queue_size": 3,
        }

        self.mock_lock_manager = MagicMock()
        self.mock_lock_manager.get_stats.return_value = {
            "threads_holding_locks": 1,
            "total_locks_held": 2,
        }

        self.mock_trading_system = MagicMock()
        self.mock_trading_system.is_heavy_init_complete = True
        self.mock_trading_system.mt5_connection_failed = False
        self.mock_trading_system._last_positions_cache = []
        self.mock_trading_system._last_known_balance = 10000.0
        self.mock_trading_system._last_known_equity = 10050.0

        self.monitor = HealthMonitor(
            governor=self.mock_governor,
            task_queue=self.mock_task_queue,
            lock_manager=self.mock_lock_manager,
            trading_system=self.mock_trading_system,
        )

    def test_get_health_returns_dict(self):
        """Проверка: get_health возвращает dict."""
        health = self.monitor.get_health()
        assert isinstance(health, dict)
        assert "timestamp" in health
        assert "version" in health
        assert "status" in health

    def test_health_status_healthy(self):
        """Проверка: статус healthy при нормальной загрузке."""
        self.mock_governor.get_load_summary.return_value = {
            "cpu_pct": 45.0,
            "ram_pct": 25,
            "active_tasks": 2,
        }

        health = self.monitor.get_health()
        assert health["status"] == "healthy"

    def test_health_status_degraded(self):
        """Проверка: статус degraded при высокой загрузке."""
        self.mock_governor.get_load_summary.return_value = {
            "cpu_pct": 88.0,
            "ram_pct": 80,
            "active_tasks": 10,
        }
        self.mock_governor.is_overloaded.return_value = True

        health = self.monitor.get_health()
        assert health["status"] == "degraded"

    def test_health_status_overloaded(self):
        """Проверка: статус overloaded при критической загрузке."""
        self.mock_governor.get_load_summary.return_value = {
            "cpu_pct": 96.0,
            "ram_pct": 92,
            "active_tasks": 20,
        }

        health = self.monitor.get_health()
        assert health["status"] == "overloaded"

    def test_get_health_includes_load(self):
        """Проверка: health включает load данные."""
        health = self.monitor.get_health()
        assert "load" in health
        assert health["load"]["cpu_pct"] == 45.0

    def test_get_health_includes_task_stats(self):
        """Проверка: health включает статистику задач."""
        health = self.monitor.get_health()
        assert "task_stats" in health
        assert health["task_stats"]["submitted"] == 10

    def test_get_health_includes_lock_stats(self):
        """Проверка: health включает статистику блокировок."""
        health = self.monitor.get_health()
        assert "lock_stats" in health
        assert health["lock_stats"]["threads_holding_locks"] == 1

    def test_get_health_includes_trading_status(self):
        """Проверка: health включает статус торговли."""
        health = self.monitor.get_health()
        assert "trading" in health
        assert health["trading"]["running"] is True
        assert health["trading"]["mt5_connected"] is True
        assert health["trading"]["last_balance"] == 10000.0

    def test_check_and_alert_no_overload(self):
        """Проверка: нет алёрта при нормальной загрузке."""
        self.mock_governor.is_overloaded.return_value = False
        alert = self.monitor.check_and_alert()
        assert alert is None

    def test_check_and_alert_on_overload(self):
        """Проверка: алёрт при перегрузке."""
        self.mock_governor.is_overloaded.return_value = True
        self.mock_governor.get_load_summary.return_value = {
            "cpu_pct": 95.0,
            "ram_used_gb": 15.0,
            "ram_total_gb": 16.0,
            "gpu_mem_gb": 1.0,
            "active_tasks": 15,
        }

        alert = self.monitor.check_and_alert()
        assert alert is not None
        assert "ПЕРЕГРУЗКА" in alert
        assert "CPU: 95.0%" in alert

    def test_check_and_alert_cooldown(self):
        """Проверка: кулдаун между алёртами."""
        self.mock_governor.is_overloaded.return_value = True
        self.mock_governor.get_load_summary.return_value = {
            "cpu_pct": 95.0,
            "ram_used_gb": 15.0,
            "ram_total_gb": 16.0,
            "gpu_mem_gb": 1.0,
            "active_tasks": 15,
        }

        # Первый алёрт
        alert1 = self.monitor.check_and_alert()
        assert alert1 is not None

        # Второй сразу — кулдаун
        alert2 = self.monitor.check_and_alert()
        assert alert2 is None

    def test_get_summary_returns_string(self):
        """Проверка: get_summary возвращает читаемую строку."""
        summary = self.monitor.get_summary()
        assert isinstance(summary, str)
        assert "Health Dashboard" in summary
        assert "Status:" in summary
        assert "Resources:" in summary

    def test_monitor_with_none_dependencies(self):
        """Проверка: монитор работает с None зависимостями."""
        monitor = HealthMonitor()
        health = monitor.get_health()
        assert "timestamp" in health
        # Статус может отсутствовать без governor
        assert "version" in health

    def test_alert_count_increments(self):
        """Проверка: счётчик алёртов увеличивается."""
        self.mock_governor.is_overloaded.return_value = True
        self.mock_governor.get_load_summary.return_value = {
            "cpu_pct": 95.0,
            "ram_used_gb": 15.0,
            "ram_total_gb": 16.0,
            "gpu_mem_gb": 1.0,
            "active_tasks": 15,
        }

        # Обходим кулдаун
        self.monitor._last_overload_alert = 0

        self.monitor.check_and_alert()
        assert self.monitor._alert_count == 1

        self.monitor._last_overload_alert = 0  # Сброс кулдауна
        self.monitor.check_and_alert()
        assert self.monitor._alert_count == 2
