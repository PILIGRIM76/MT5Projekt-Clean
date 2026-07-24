"""
Автоматический планировщик переобучения моделей.
Архитектура: мониторинг точности → приоритетная очередь → ResourceGovernor →
ML_TRAINING domain → EventBus уведомления.
Не блокирует инференс и трейдинг.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import heapq

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager
from src.core.resource_governor import ResourceBudget, get_governor
from src.core.thread_domains import ThreadDomain, run_in_domain

logger = logging.getLogger(__name__)


@dataclass(order=True)
class RetrainJob:
    priority: int
    symbol: str = field(compare=False)
    trigger: str = field(compare=False)
    timestamp: float = field(default_factory=time.time, compare=False)


class AutoTrainer:
    """
    Планировщик фоновых переобучений.
    Триггеры: расписание, падение точности, поступление новых данных.
    """

    def __init__(self, config: Dict, predictor, db_manager):
        self.config = config
        self.predictor = predictor
        self.db = db_manager
        self.event_bus = get_event_bus()
        self.resource_gov = get_governor()

        self._queue: List[RetrainJob] = []
        self._running = False
        self._cooldowns: Dict[str, float] = {}
        self._accuracy_history: Dict[str, List[float]] = {}

        # Настройки из конфига
        self.check_interval = config.get("check_interval_sec", 300)
        self.retrain_interval_sec = config.get("retrain_interval_sec", 86400)
        self.degradation_threshold = config.get("degradation_threshold", 0.05)
        self.min_bars_for_retrain = config.get("min_bars_for_retrain", 200)

    async def start(self):
        self._running = True
        logger.info("AutoTrainer started")

        # Подписка на события
        await self.event_bus.subscribe(
            "model_prediction", self._track_accuracy
        )
        await self.event_bus.subscribe("data_synced", self._on_data_synced)

        # Запуск цикла планирования
        asyncio.create_task(self._scheduler_loop())

    async def stop(self):
        self._running = False
        logger.info("AutoTrainer stopped")

    async def _scheduler_loop(self):
        """Периодическая проверка деградации + расписания"""
        while self._running:
            try:
                await self._check_schedule_triggers()
                await self._check_degradation_triggers()
                await self._process_queue()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"AutoTrainer loop error: {e}", exc_info=True
                )
                await asyncio.sleep(30)

    async def _track_accuracy(self, event: SystemEvent):
        """Сбор статистики точности для расчёта деградации"""
        sym = event.payload.get("symbol")
        acc = event.payload.get("confidence")
        if not sym or not acc:
            return

        if sym not in self._accuracy_history:
            self._accuracy_history[sym] = []

        self._accuracy_history[sym].append(acc)
        # Храним последние 1000 значений
        if len(self._accuracy_history[sym]) > 1000:
            self._accuracy_history[sym] = self._accuracy_history[sym][-500:]

    async def _on_data_synced(self, event: SystemEvent):
        """Новые данные → проверить, нужно ли переобучить"""
        sym = event.payload.get("symbol")
        count = event.payload.get("count", 0)
        if sym and count >= self.min_bars_for_retrain:
            await self._queue_retrain(
                sym, trigger="data_sync", priority=3
            )

    async def _check_schedule_triggers(self):
        """Проверка: прошло ли время с последнего обучения символа"""
        try:
            if hasattr(self.db, "list_trained_models"):
                symbols = await self.db.list_trained_models()
            else:
                symbols = []

            now = time.time()
            for sym in symbols:
                if hasattr(self.db, "get_last_retrain_time"):
                    last_train = await self.db.get_last_retrain_time(sym)
                    if last_train and (
                        now - last_train
                    ) >= self.retrain_interval_sec:
                        await self._queue_retrain(
                            sym, trigger="schedule", priority=5
                        )
        except Exception as e:
            logger.debug(f"Schedule check failed: {e}")

    async def _check_degradation_triggers(self):
        """Проверка: упала ли точность ниже порога"""
        for sym, history in self._accuracy_history.items():
            if len(history) < 100:
                continue

            recent_avg = sum(history[-50:]) / 50
            baseline_avg = (
                sum(history[:50]) / 50 if len(history) >= 50 else recent_avg
            )

            drop = (
                (baseline_avg - recent_avg) / baseline_avg
                if baseline_avg > 0
                else 0
            )
            if drop >= self.degradation_threshold:
                await self._queue_retrain(
                    sym, trigger="degradation", priority=1
                )

    async def _queue_retrain(
        self, symbol: str, trigger: str, priority: int
    ):
        """Добавление задачи в очередь с проверкой cooldown"""
        now = time.time()
        if symbol in self._cooldowns and (now - self._cooldowns[symbol]) < 3600:
            return  # Не чаще раза в час для одного символа

        # Удаляем дубликаты из очереди
        self._queue = [j for j in self._queue if j.symbol != symbol]
        heapq.heappush(self._queue, RetrainJob(priority, symbol, trigger))
        logger.info(
            f"Queued retrain: {symbol} ({trigger}, priority={priority})"
        )

        await self.event_bus.publish(
            SystemEvent(
                type="retrain_queued",
                payload={
                    "symbol": symbol,
                    "trigger": trigger,
                    "queue_size": len(self._queue),
                },
                priority=EventPriority.MEDIUM,
            )
        )

    async def _process_queue(self):
        """Обработка очереди: берём top-задачу → проверяем ресурсы → запускаем"""
        if not self._queue:
            return

        # Проверяем ресурсы
        if self.resource_gov.can_start("auto_retrain", ResourceBudget):
            job = heapq.heappop(self._queue)
            self._cooldowns[job.symbol] = time.time()

            logger.info(
                f"Starting retrain: {job.symbol} (trigger={job.trigger})"
            )

            # Запускаем в фоне
            if self.predictor:
                asyncio.create_task(
                    self._execute_retrain(job.symbol, job.trigger)
                )
            else:
                logger.warning(
                    f"Predictor not available, skipping retrain for "
                    f"{job.symbol}"
                )
                self.resource_gov.task_finished("auto_retrain")

    @run_in_domain(ThreadDomain.ML_TRAINING)
    async def _execute_retrain(self, symbol: str, trigger: str):
        """Выполнение переобучения в ML_TRAINING домене"""
        try:
            # Загрузка данных
            if hasattr(self.db, "load_training_data"):
                data = await self.db.load_training_data(symbol)
            else:
                data = {"features": []}

            # Запуск переобучения
            success = await self.predictor.retrain_background(symbol, data)

            if success:
                await self.event_bus.publish(
                    SystemEvent(
                        type="model_retrained",
                        payload={
                            "symbol": symbol,
                            "trigger": trigger,
                        },
                        priority=EventPriority.HIGH,
                    )
                )
                logger.info(f"Model retrained successfully for {symbol}")
            else:
                logger.warning(f"Retrain failed for {symbol}")

        except Exception as e:
            logger.error(
                f"Retrain execution failed for {symbol}: {e}",
                exc_info=True,
            )
        finally:
            self.resource_gov.task_finished("auto_retrain")

    def get_queue_status(self) -> Dict[str, Any]:
        """Статус очереди для мониторинга"""
        return {
            "pending": len(self._queue),
            "jobs": [
                {
                    "symbol": j.symbol,
                    "trigger": j.trigger,
                    "priority": j.priority,
                }
                for j in sorted(self._queue, key=lambda x: x.priority)[:10]
            ],
            "cooldowns": {
                sym: f"{time.time() - ts:.0f}s ago"
                for sym, ts in self._cooldowns.items()
            },
            "tracked_symbols": len(self._accuracy_history),
        }

    def force_retrain(self, symbol: str, priority: int = 1):
        """Принудительное добавление в очередь (высокий приоритет)"""
        asyncio.create_task(
            self._queue_retrain(symbol, trigger="manual", priority=priority)
        )
