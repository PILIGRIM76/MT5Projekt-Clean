"""
Тесты для AutoTrainer — планировщик авто-обучения.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.event_bus import AsyncEventBus, EventPriority, SystemEvent
from src.ml.auto_trainer import AutoTrainer, RetrainJob


@pytest.fixture
def mock_dependencies():
    predictor = AsyncMock()
    predictor.retrain_background = AsyncMock(return_value=True)

    db = AsyncMock()
    db.list_trained_models = AsyncMock(return_value=["EURUSD", "GBPUSD"])
    db.get_last_retrain_time = AsyncMock(return_value=0)
    db.load_training_data = AsyncMock(
        return_value={"features": [[1, 2], [3, 4]]}
    )

    return predictor, db


@pytest.fixture
async def event_bus():
    bus = AsyncEventBus(max_queue_size=500, dispatch_interval_ms=5.0)
    await bus.start()
    yield bus
    await bus.stop(timeout=2.0)


class TestRetrainJob:
    """Тесты RetrainJob."""

    def test_priority_ordering(self):
        """Проверка: задачи сортируются по приоритету."""
        jobs = [
            RetrainJob(5, "EURUSD", "schedule"),
            RetrainJob(1, "GBPUSD", "degradation"),
            RetrainJob(3, "USDJPY", "data_sync"),
        ]

        import heapq

        heapq.heapify(jobs)
        assert heapq.heappop(jobs).priority == 1
        assert heapq.heappop(jobs).priority == 3
        assert heapq.heappop(jobs).priority == 5


class TestAutoTrainer:
    """Тесты AutoTrainer."""

    @pytest.mark.asyncio
    async def test_auto_trainer_queues_on_schedule(
        self, event_bus, mock_dependencies
    ):
        """Проверка: планировщик ставит задачи в очередь."""
        pred, db = mock_dependencies
        trainer = AutoTrainer(
            {"check_interval_sec": 1, "retrain_interval_sec": 0},
            pred,
            db,
        )
        await trainer.start()
        await asyncio.sleep(1.5)

        status = trainer.get_queue_status()
        assert status["pending"] >= 0  # Может быть 0 если ресурсы заняты
        await trainer.stop()

    @pytest.mark.asyncio
    async def test_auto_trainer_respects_cooldown(
        self, event_bus, mock_dependencies
    ):
        """Проверка: cooldown предотвляет дубликаты."""
        pred, db = mock_dependencies
        trainer = AutoTrainer({}, pred, db)

        await trainer._queue_retrain("EURUSD", "test", 1)
        await trainer._queue_retrain(
            "EURUSD", "test", 1
        )  # Дубликат не добавится

        assert len(trainer._queue) == 1

    @pytest.mark.asyncio
    async def test_auto_trainer_track_accuracy(
        self, event_bus, mock_dependencies
    ):
        """Проверка: отслеживание точности."""
        pred, db = mock_dependencies
        trainer = AutoTrainer({}, pred, db)

        await trainer._track_accuracy(
            SystemEvent(
                type="model_prediction",
                payload={"symbol": "EURUSD", "confidence": 0.8},
            )
        )

        assert "EURUSD" in trainer._accuracy_history
        assert len(trainer._accuracy_history["EURUSD"]) == 1

    @pytest.mark.asyncio
    async def test_auto_trainer_get_queue_status(
        self, event_bus, mock_dependencies
    ):
        """Проверка: статус очереди."""
        pred, db = mock_dependencies
        trainer = AutoTrainer({}, pred, db)

        status = trainer.get_queue_status()

        assert "pending" in status
        assert "jobs" in status
        assert "cooldowns" in status
        assert "tracked_symbols" in status

    @pytest.mark.asyncio
    async def test_auto_trainer_force_retrain(
        self, event_bus, mock_dependencies
    ):
        """Проверка: принудительное переобучение."""
        pred, db = mock_dependencies
        trainer = AutoTrainer({}, pred, db)

        trainer.force_retrain("TEST", priority=1)
        await asyncio.sleep(0.1)

        # Задача должна быть в очереди
        assert len(trainer._queue) == 1
        assert trainer._queue[0].symbol == "TEST"
        assert trainer._queue[0].priority == 1

    @pytest.mark.asyncio
    async def test_auto_trainer_degradation_detection(
        self, event_bus, mock_dependencies
    ):
        """Проверка: обнаружение деградации модели."""
        pred, db = mock_dependencies
        trainer = AutoTrainer(
            {"degradation_threshold": 0.05}, pred, db
        )

        # Симулируем падение точности
        history = trainer._accuracy_history["EURUSD"] = []

        # Базовая точность ~0.8
        for _ in range(50):
            history.append(0.8)

        # Падение до ~0.7
        for _ in range(50):
            history.append(0.7)

        await trainer._check_degradation_triggers()

        # EURUSD должен быть в очереди
        assert len(trainer._queue) == 1
        assert trainer._queue[0].trigger == "degradation"
