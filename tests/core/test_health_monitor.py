"""
Тесты для HealthMonitor — мониторинг и авто-восстановление.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from src.core.event_bus import AsyncEventBus, EventPriority, SystemEvent
from src.core.health_monitor import ComponentState, ComponentStatus, HealthMonitor


@pytest.fixture
def mock_mt5():
    mt5 = MagicMock()
    mt5.terminal_info = MagicMock(return_value=MagicMock(connected=True))
    return mt5


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_predictor():
    pred = MagicMock()
    pred.get_stats = MagicMock(return_value={"inference_avg_ms": 45})
    return pred


@pytest.fixture
async def event_bus():
    bus = AsyncEventBus(max_queue_size=500, dispatch_interval_ms=5.0)
    await bus.start()
    yield bus
    await bus.stop(timeout=2.0)


class TestComponentState:
    """Тесты ComponentState."""

    def test_default_values(self):
        """Проверка значений по умолчанию."""
        comp = ComponentState("test")
        assert comp.status == ComponentStatus.UNKNOWN
        assert comp.error_count == 0
        assert comp.recovery_attempts == 0
        assert comp.max_retries == 3


class TestHealthMonitor:
    """Тесты HealthMonitor."""

    @pytest.mark.asyncio
    async def test_health_monitor_detects_healthy(self, event_bus, mock_mt5, mock_db, mock_predictor):
        """Проверка: все компоненты healthy."""
        config = {
            "health_check_interval_sec": 0.5,
            "resource_thresholds": {
                "cpu_max": 90,
                "ram_max": 95,
                "disk_max": 95,
            },
        }
        monitor = HealthMonitor(config, mock_mt5, mock_db, mock_predictor, event_bus)
        await monitor.start()
        await asyncio.sleep(0.5)

        report = monitor.get_report()
        assert report["components"]["mt5_connection"]["status"] == "healthy"

        await monitor.stop()

    @pytest.mark.asyncio
    async def test_health_monitor_triggers_recovery(self, event_bus):
        """Проверка: восстановление при сбое MT5."""
        mt5 = MagicMock()
        mt5.terminal_info = MagicMock(side_effect=ConnectionError("Disconnected"))

        config = {"health_check_interval_sec": 1.0}
        monitor = HealthMonitor(config, mt5, MagicMock(), None, event_bus)

        await monitor._check_mt5_connection()
        comp = monitor.components["mt5_connection"]
        # Статус может быть CRITICAL или RECOVERING (если recovery запущен)
        assert comp.status in (
            ComponentStatus.CRITICAL,
            ComponentStatus.RECOVERING,
        )
        assert len(monitor._recovery_tasks) > 0

    @pytest.mark.asyncio
    async def test_health_monitor_handles_no_mt5(self, event_bus):
        """Проверка: работает без MT5."""
        config = {"health_check_interval_sec": 0.5}
        monitor = HealthMonitor(config, None, MagicMock(), None, event_bus)

        await monitor._check_mt5_connection()
        comp = monitor.components["mt5_connection"]
        assert comp.status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_monitor_handles_no_predictor(self, event_bus):
        """Проверка: работает без predictor."""
        config = {"health_check_interval_sec": 0.5}
        monitor = HealthMonitor(config, MagicMock(), MagicMock(), None, event_bus)

        await monitor._check_ml_inference_latency()
        comp = monitor.components["ml_inference"]
        assert comp.status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_monitor_get_report(self, event_bus):
        """Проверка: отчёт о состоянии."""
        config = {"health_check_interval_sec": 0.5}
        monitor = HealthMonitor(config, MagicMock(), MagicMock(), MagicMock(), event_bus)

        report = monitor.get_report()

        assert "timestamp" in report
        assert "components" in report
        assert "mt5_connection" in report["components"]
        assert "database" in report["components"]
        assert "event_bus_queue" in report["components"]

    @pytest.mark.asyncio
    async def test_health_monitor_send_alert(self, event_bus):
        """Проверка: отправка алертов."""
        config = {
            "health_check_interval_sec": 0.5,
            "alert_cooldown_sec": 1,
        }
        monitor = HealthMonitor(config, MagicMock(), MagicMock(), None, event_bus)

        comp = monitor.components["mt5_connection"]
        monitor._send_alert("mt5_connection", ComponentStatus.CRITICAL, "Test alert")

        assert comp.last_error == ""  # Alert cooldown logic
        assert "mt5_connection_critical" in monitor._alert_cooldowns
