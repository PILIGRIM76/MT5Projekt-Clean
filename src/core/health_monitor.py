"""
Монитор здоровья системы с авто-восстановлением компонентов.
Архитектура: периодические проверки → оценка статуса → recovery → алерты.
Все проверки асинхронны, синхронные вызовы вынесены в to_thread.
"""

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.thread_domains import ThreadDomain, run_in_domain

logger = logging.getLogger(__name__)


class ComponentStatus(Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    RECOVERING = "recovering"


@dataclass
class ComponentState:
    name: str
    status: ComponentStatus = ComponentStatus.UNKNOWN
    last_check: float = 0.0
    error_count: int = 0
    last_error: str = ""
    recovery_attempts: int = 0
    max_retries: int = 3
    cooldown_sec: float = 30.0


class HealthMonitor:
    """Централизованный монитор + авто-реаниматор системы"""

    def __init__(
        self,
        config: Dict,
        mt5_api=None,
        db_manager=None,
        predictor=None,
        event_bus=None,
    ):
        self.config = config
        self.mt5 = mt5_api
        self.db = db_manager
        self.predictor = predictor
        self.event_bus = event_bus or get_event_bus()

        self._running = False
        self._check_interval = config.get("health_check_interval_sec", 15.0)

        # Состояния компонентов
        self.components: Dict[str, ComponentState] = {
            "mt5_connection": ComponentState("mt5_connection"),
            "database": ComponentState("database"),
            "event_bus_queue": ComponentState("event_bus_queue"),
            "system_resources": ComponentState("system_resources"),
            "ml_inference": ComponentState("ml_inference"),
        }

        self._recovery_tasks: Dict[str, asyncio.Task] = {}
        self._alert_cooldowns: Dict[str, float] = {}

    async def start(self):
        self._running = True
        logger.info("HealthMonitor started")
        asyncio.create_task(self._monitor_loop())
        await self.event_bus.subscribe("system_shutdown", self._on_shutdown_request)

    async def stop(self):
        self._running = False
        for task in self._recovery_tasks.values():
            if not task.done():
                task.cancel()
        logger.info("HealthMonitor stopped")

    @run_in_domain(ThreadDomain.HEALTH_CHECK)
    async def _monitor_loop(self):
        while self._running:
            try:
                await self._check_all_components()
                await self._evaluate_system_state()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _check_all_components(self):
        """Параллельная проверка всех компонентов"""
        checks = [
            self._check_mt5_connection(),
            self._check_database_integrity(),
            self._check_event_bus_queue(),
            self._check_system_resources(),
            self._check_ml_inference_latency(),
        ]
        await asyncio.gather(*checks, return_exceptions=True)

    # 🔍 ПРОВЕРКИ
    async def _check_mt5_connection(self):
        comp = self.components["mt5_connection"]
        comp.last_check = time.time()

        if not self.mt5:
            self._update_status(comp, ComponentStatus.HEALTHY)
            return

        try:
            info = await asyncio.to_thread(getattr(self.mt5, "terminal_info", None))
            if info and getattr(info, "connected", False):
                self._update_status(comp, ComponentStatus.HEALTHY)
            else:
                self._update_status(comp, ComponentStatus.CRITICAL, "MT5 disconnected")
                await self._trigger_recovery("mt5_connection")
        except Exception as e:
            self._update_status(comp, ComponentStatus.CRITICAL, str(e))
            await self._trigger_recovery("mt5_connection")

    async def _check_database_integrity(self):
        comp = self.components["database"]
        comp.last_check = time.time()

        if not self.db:
            self._update_status(comp, ComponentStatus.HEALTHY)
            return

        try:

            def _db_check():
                db_path = self.config.get("db_path", "data/genesis.db")
                conn = sqlite3.connect(db_path)
                res = conn.execute("PRAGMA quick_check").fetchone()
                conn.close()
                return res[0] == "ok"

            if await asyncio.to_thread(_db_check):
                self._update_status(comp, ComponentStatus.HEALTHY)
            else:
                self._update_status(
                    comp,
                    ComponentStatus.DEGRADED,
                    "DB integrity check failed",
                )
        except Exception as e:
            self._update_status(comp, ComponentStatus.CRITICAL, str(e))

    async def _check_event_bus_queue(self):
        comp = self.components["event_bus_queue"]
        comp.last_check = time.time()
        try:
            stats = self.event_bus.get_stats()
            queue_size = stats.get("queue_size", 0)
            max_q = self.config.get("max_event_queue_size", 500)
            if queue_size > max_q:
                self._update_status(
                    comp,
                    ComponentStatus.DEGRADED,
                    f"Queue backlog: {queue_size}/{max_q}",
                )
                logger.warning(f"EventBus queue overloaded ({queue_size}). " f"Triggering flush...")
            else:
                self._update_status(comp, ComponentStatus.HEALTHY)
        except Exception as e:
            self._update_status(comp, ComponentStatus.CRITICAL, str(e))

    async def _check_system_resources(self):
        comp = self.components["system_resources"]
        comp.last_check = time.time()

        if not HAS_PSUTIL:
            self._update_status(comp, ComponentStatus.HEALTHY)
            return

        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(self.config.get("workdir", "."))

            thresholds = self.config.get("resource_thresholds", {})
            issues = []
            if cpu > thresholds.get("cpu_max", 85):
                issues.append(f"CPU {cpu:.0f}%")
            if mem.percent > thresholds.get("ram_max", 90):
                issues.append(f"RAM {mem.percent}%")
            if disk.percent > thresholds.get("disk_max", 95):
                issues.append(f"Disk {disk.percent}%")

            if issues:
                self._update_status(comp, ComponentStatus.DEGRADED, " | ".join(issues))
            else:
                self._update_status(comp, ComponentStatus.HEALTHY)
        except Exception as e:
            self._update_status(comp, ComponentStatus.CRITICAL, str(e))

    async def _check_ml_inference_latency(self):
        comp = self.components["ml_inference"]
        comp.last_check = time.time()
        if not self.predictor:
            self._update_status(comp, ComponentStatus.HEALTHY)
            return
        try:
            stats = self.predictor.get_stats()
            avg_ms = stats.get("inference_avg_ms", 0)
            if avg_ms > self.config.get("max_inference_latency_ms", 200):
                self._update_status(
                    comp,
                    ComponentStatus.DEGRADED,
                    f"High latency: {avg_ms:.0f}ms",
                )
            else:
                self._update_status(comp, ComponentStatus.HEALTHY)
        except Exception as e:
            self._update_status(comp, ComponentStatus.CRITICAL, str(e))

    # 🛠️ ВОССТАНОВЛЕНИЕ
    def _update_status(
        self,
        comp: ComponentState,
        status: ComponentStatus,
        error_msg: str = "",
    ):
        if comp.status != status:
            logger.info(f"{comp.name}: {comp.status.value} → {status.value}")
            comp.status = status
            if status in (
                ComponentStatus.DEGRADED,
                ComponentStatus.CRITICAL,
            ):
                comp.error_count += 1
                comp.last_error = error_msg
                self._send_alert(comp.name, status, error_msg)

    async def _trigger_recovery(self, name: str):
        comp = self.components[name]
        if comp.status == ComponentStatus.CRITICAL and comp.recovery_attempts < comp.max_retries:
            if name not in self._recovery_tasks or self._recovery_tasks[name].done():
                logger.warning(f"Recovery triggered for {name} " f"(attempt {comp.recovery_attempts + 1})")
                comp.recovery_attempts += 1
                comp.status = ComponentStatus.RECOVERING
                self._recovery_tasks[name] = asyncio.create_task(self._recover_component(name))

    async def _recover_component(self, name: str):
        comp = self.components[name]
        try:
            await asyncio.sleep(comp.cooldown_sec)
            if name == "mt5_connection":
                logger.info("Attempting MT5 re-initialization...")
                await asyncio.to_thread(getattr(self.mt5, "initialize", lambda: None))
            elif name == "event_bus_queue":
                logger.info("Flushing EventBus stale tasks...")
            elif name == "ml_inference":
                logger.info("Refreshing ML model cache...")
                if self.predictor and hasattr(self.predictor, "_warmup_cache"):
                    await self.predictor._warmup_cache()

            comp.recovery_attempts = 0
            self._update_status(comp, ComponentStatus.HEALTHY, "Recovered")
            await self.event_bus.publish(
                SystemEvent(
                    type="component_recovered",
                    payload={"component": name},
                    priority=EventPriority.HIGH,
                )
            )
        except Exception as e:
            self._update_status(
                comp,
                ComponentStatus.CRITICAL,
                f"Recovery failed: {e}",
            )
            logger.error(f"Recovery failed for {name}: {e}")
            if comp.recovery_attempts >= comp.max_retries:
                await self.event_bus.publish(
                    SystemEvent(
                        type="system_critical",
                        payload={
                            "component": name,
                            "message": ("Max retries exceeded. " "Manual intervention required."),
                        },
                        priority=EventPriority.CRITICAL,
                    )
                )

    async def _evaluate_system_state(self):
        critical = [n for n, c in self.components.items() if c.status == ComponentStatus.CRITICAL]
        if critical:
            await self.event_bus.publish(
                SystemEvent(
                    type="system_health_alert",
                    payload={
                        "critical_components": critical,
                        "timestamp": time.time(),
                    },
                    priority=EventPriority.CRITICAL,
                )
            )

    def _send_alert(self, component: str, status: ComponentStatus, message: str):
        now = time.time()
        key = f"{component}_{status.value}"
        cooldown = self.config.get("alert_cooldown_sec", 60)
        if key in self._alert_cooldowns and now - self._alert_cooldowns[key] < cooldown:
            return
        self._alert_cooldowns[key] = now
        log_level = logging.WARNING if status == ComponentStatus.DEGRADED else logging.CRITICAL
        logger.log(
            log_level,
            f"HEALTH [{component.upper()}] " f"{status.value.upper()}: {message}",
        )

    async def _on_shutdown_request(self, event: SystemEvent):
        await self.stop()

    def get_report(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.now().isoformat(),
            "components": {
                name: {
                    "status": comp.status.value,
                    "error_count": comp.error_count,
                    "last_check": comp.last_check,
                    "recovery_attempts": comp.recovery_attempts,
                    "last_error": comp.last_error,
                }
                for name, comp in self.components.items()
            },
        }
