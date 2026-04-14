"""
Инструментирование системы: экспорт метрик для мониторинга.
Совместимо с Prometheus, но работает и без него (fallback на logging).
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict

from src.core.event_bus import SystemEvent, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class MetricCounter:
    name: str
    value: int = 0

    def inc(self, amount: int = 1):
        self.value += amount


@dataclass
class MetricHistogram:
    name: str
    sum: float = 0.0
    count: int = 0

    def observe(self, value: float):
        self.sum += value
        self.count += 1

    @property
    def avg(self):
        return self.sum / max(1, self.count)


class SystemMetrics:
    """Централизованный сборщик метрик пайплайна"""

    def __init__(self):
        self.counters = {
            "ticks_received": MetricCounter("ticks_received"),
            "predictions_made": MetricCounter("predictions_made"),
            "signals_generated": MetricCounter("signals_generated"),
            "orders_executed": MetricCounter("orders_executed"),
            "orders_failed": MetricCounter("orders_failed"),
        }
        self.histograms = {
            "pipeline_latency_ms": MetricHistogram("pipeline_latency_ms"),
            "inference_latency_ms": MetricHistogram("inference_latency_ms"),
        }
        self._pipeline_starts: Dict[str, float] = {}
        self.event_bus = get_event_bus()

    async def start(self):
        """Подписка на события для автоматического учёта"""
        await self.event_bus.subscribe("market_tick", self._on_tick)
        await self.event_bus.subscribe("model_prediction", self._on_prediction)
        await self.event_bus.subscribe("trade_signal", self._on_signal)
        await self.event_bus.subscribe("order_executed", self._on_order_executed)
        await self.event_bus.subscribe("order_failed", self._on_order_failed)
        logger.info("SystemMetrics collector started")

    def track_pipeline_start(self, correlation_id: str):
        self._pipeline_starts[correlation_id] = time.perf_counter()

    def track_pipeline_end(self, correlation_id: str):
        start = self._pipeline_starts.pop(correlation_id, None)
        if start:
            latency = (time.perf_counter() - start) * 1000
            self.histograms["pipeline_latency_ms"].observe(latency)

    def _on_tick(self, event: SystemEvent):
        self.counters["ticks_received"].inc()
        self.track_pipeline_start(event.correlation_id)

    def _on_prediction(self, event: SystemEvent):
        self.counters["predictions_made"].inc()

    def _on_signal(self, event: SystemEvent):
        self.counters["signals_generated"].inc()

    def _on_order_executed(self, event: SystemEvent):
        self.counters["orders_executed"].inc()
        self.track_pipeline_end(event.correlation_id)

    def _on_order_failed(self, event: SystemEvent):
        self.counters["orders_failed"].inc()
        self.track_pipeline_end(event.correlation_id)

    def get_snapshot(self) -> Dict[str, Any]:
        """Снимок метрик для логирования или экспорта"""
        return {
            "counters": {k: v.value for k, v in self.counters.items()},
            "histograms": {k: {"avg_ms": round(v.avg, 2), "count": v.count} for k, v in self.histograms.items()},
        }

    def log_periodic(self, interval_sec: float = 30.0):
        """Фоновая задача: логирование метрик каждые N секунд"""

        async def _loop():
            while True:
                await asyncio.sleep(interval_sec)
                snap = self.get_snapshot()
                logger.info(f"METRICS SNAPSHOT: {snap}")

        asyncio.create_task(_loop())


# Глобальный экземпляр
metrics = SystemMetrics()
