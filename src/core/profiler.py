"""
Асинхронный профилировщик для выявления узких мест.
Архитектура: декораторы для замеров + периодические отчёты +
алерты при деградации.
"""

import asyncio
import functools
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.thread_domains import ThreadDomain

logger = logging.getLogger(__name__)


@dataclass
class TimingStats:
    """Статистика времени выполнения"""

    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    _samples: deque = field(default_factory=lambda: deque(maxlen=1000))

    @property
    def avg_ms(self) -> float:
        return self.total_ms / max(1, self.count)

    @property
    def p95_ms(self) -> float:
        if len(self._samples) < 20:
            return self.avg_ms
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[idx]

    def record(self, duration_ms: float):
        self.count += 1
        self.total_ms += duration_ms
        self.min_ms = min(self.min_ms, duration_ms)
        self.max_ms = max(self.max_ms, duration_ms)
        self._samples.append(duration_ms)


class Profiler:
    """Централизованный профилировщик системы"""

    def __init__(self, config: Dict, event_bus=None):
        self.config = config
        self.event_bus = event_bus or get_event_bus()
        self._stats: Dict[str, TimingStats] = defaultdict(TimingStats)
        self._baseline: Dict[str, float] = {}
        self._running = False
        self._report_interval = config.get("report_interval_sec", 60)
        self._degradation_threshold = config.get(
            "degradation_threshold", 2.0
        )

    async def start(self):
        self._running = True
        logger.info("Profiler started")
        asyncio.create_task(self._report_loop())

    async def stop(self):
        self._running = False
        await self._publish_final_report()
        logger.info("Profiler stopped")

    async def _report_loop(self):
        while self._running:
            await asyncio.sleep(self._report_interval)
            await self._publish_periodic_report()
            await self._check_degradation()

    def profile(self, name: Optional[str] = None):
        """Декоратор для профилирования функций"""

        def decorator(func: Callable) -> Callable:
            metric_name = name or f"{func.__module__}.{func.__name__}"

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    duration = (time.perf_counter() - start) * 1000
                    self._record(metric_name, duration)

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    duration = (time.perf_counter() - start) * 1000
                    self._record(metric_name, duration)

            return (
                async_wrapper
                if asyncio.iscoroutinefunction(func)
                else sync_wrapper
            )

        return decorator

    def _record(self, name: str, duration_ms: float):
        """Запись замера"""
        self._stats[name].record(duration_ms)

    def set_baseline(self, name: str, value: float):
        """Установка базовой линии для детекции деградации"""
        self._baseline[name] = value
        logger.debug(f"Baseline set for {name}: {value:.2f}ms")

    def get_stats(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Получение статистики"""
        if name:
            stats = self._stats.get(name)
            if not stats:
                return {}
            return {
                "count": stats.count,
                "avg_ms": round(stats.avg_ms, 2),
                "p95_ms": round(stats.p95_ms, 2),
                "min_ms": (
                    round(stats.min_ms, 2)
                    if stats.min_ms != float("inf")
                    else None
                ),
                "max_ms": round(stats.max_ms, 2),
            }
        return {
            n: {
                "count": s.count,
                "avg_ms": round(s.avg_ms, 2),
                "p95_ms": round(s.p95_ms, 2),
            }
            for n, s in self._stats.items()
            if s.count > 0
        }

    async def _check_degradation(self):
        """Проверка деградации производительности"""
        for name, stats in self._stats.items():
            if name in self._baseline and stats.count >= 10:
                ratio = stats.avg_ms / self._baseline[name]
                if ratio >= self._degradation_threshold:
                    await self.event_bus.publish(
                        SystemEvent(
                            type="performance_degradation",
                            payload={
                                "metric": name,
                                "current_avg_ms": round(stats.avg_ms, 2),
                                "baseline_ms": self._baseline[name],
                                "ratio": round(ratio, 2),
                            },
                            priority=EventPriority.HIGH,
                        )
                    )
                    logger.warning(
                        f"Performance degradation: {name} {ratio:.2f}x slower"
                    )

    async def _publish_periodic_report(self):
        """Публикация периодического отчёта"""
        report = {
            "timestamp": time.time(),
            "metrics": {
                name: {
                    "count": stats.count,
                    "avg_ms": round(stats.avg_ms, 2),
                    "p95_ms": round(stats.p95_ms, 2),
                    "min_ms": (
                        round(stats.min_ms, 2)
                        if stats.min_ms != float("inf")
                        else None
                    ),
                    "max_ms": round(stats.max_ms, 2),
                }
                for name, stats in self._stats.items()
                if stats.count > 0
            },
        }
        await self.event_bus.publish(
            SystemEvent(
                type="profiler_report",
                payload=report,
                priority=EventPriority.LOW,
            )
        )

    async def _publish_final_report(self):
        """Финальный отчёт при остановке"""
        await self._publish_periodic_report()
        logger.info(f"Profiler final report: {len(self._stats)} metrics tracked")


# Глобальный экземпляр
profiler = Profiler({})
