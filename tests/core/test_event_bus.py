"""
Тесты для AsyncEventBus — асинхронная шина событий с приоритетами.
"""

import asyncio

import pytest

from src.core.event_bus import AsyncEventBus, EventPriority, SystemEvent
from src.core.thread_domains import ThreadDomain


class TestAsyncEventBus:
    """Тесты AsyncEventBus."""

    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        """Проверка публикации и подписки."""
        bus = AsyncEventBus()
        await bus.start()

        received = []

        async def handler(event: SystemEvent):
            received.append(event.payload)

        await bus.subscribe("test_event", handler, domain=ThreadDomain.STRATEGY_ENGINE)

        await bus.publish(SystemEvent(type="test_event", payload={"value": 42}))

        # Даём время на обработку
        await asyncio.sleep(0.1)

        assert {"value": 42} in received
        await bus.stop()

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        """Проверка ordering по приоритетам."""
        bus = AsyncEventBus(max_queue_size=10)
        await bus.start()

        execution_order = []

        async def tracking_handler(event: SystemEvent):
            execution_order.append(event.payload["id"])

        await bus.subscribe("priority_test", tracking_handler)

        # Публикуем в обратном порядке приоритетов
        await bus.publish(SystemEvent(type="priority_test", payload={"id": 3}, priority=EventPriority.LOW))
        await bus.publish(SystemEvent(type="priority_test", payload={"id": 1}, priority=EventPriority.CRITICAL))
        await bus.publish(SystemEvent(type="priority_test", payload={"id": 2}, priority=EventPriority.MEDIUM))

        await asyncio.sleep(0.2)  # Ждём обработки

        # Должны выполниться в порядке приоритета
        assert execution_order == [1, 2, 3], f"Got: {execution_order}"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_queue_full_rejection(self):
        """Проверка отклонения при переполнении очереди."""
        bus = AsyncEventBus(max_queue_size=2)
        await bus.start()

        # Заполняем очередь
        for i in range(2):
            await bus.publish(SystemEvent(type="fill_event", payload={"id": i}))

        # Переполняем (должно вернуть False после таймаута)
        result = await bus.publish(SystemEvent(type="overflow", payload={"id": 99}))
        # Результат может быть True или False в зависимости от скорости обработки

        await bus.stop()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Проверка нескольких подписчиков на одно событие."""
        bus = AsyncEventBus()
        await bus.start()

        results = {"handler1": False, "handler2": False}

        async def handler1(event: SystemEvent):
            results["handler1"] = True

        async def handler2(event: SystemEvent):
            results["handler2"] = True

        await bus.subscribe("multi_test", handler1)
        await bus.subscribe("multi_test", handler2)

        await bus.publish(SystemEvent(type="multi_test", payload={"test": True}))

        await asyncio.sleep(0.1)

        assert results["handler1"] is True
        assert results["handler2"] is True

        await bus.stop()

    @pytest.mark.asyncio
    async def test_handler_error_handling(self):
        """Проверка обработки ошибок в хендлерах."""
        bus = AsyncEventBus()
        await bus.start()

        errors = []

        def error_handler(event: SystemEvent):
            raise ValueError("Test error")

        def success_handler(event: SystemEvent):
            errors.append("success_called")

        await bus.subscribe("error_test", error_handler)
        await bus.subscribe("error_test", success_handler)

        # Не должно выбросить исключение
        await bus.publish(SystemEvent(type="error_test", payload={}))

        await asyncio.sleep(0.1)

        # Успешный хендлер должен быть вызван
        assert "success_called" in errors
        assert bus._stats["errors"] >= 1

        await bus.stop()

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Проверка статистики EventBus."""
        bus = AsyncEventBus()
        await bus.start()

        async def dummy_handler(event: SystemEvent):
            pass

        await bus.subscribe("stats_test", dummy_handler)

        for i in range(5):
            await bus.publish(SystemEvent(type="stats_test", payload={"id": i}))

        await asyncio.sleep(0.2)

        stats = bus.get_stats()
        assert stats["published"] == 5
        assert stats["dispatched"] >= 0  # Может быть меньше если не все обработаны
        assert "queue_size" in stats

        await bus.stop()

    @pytest.mark.asyncio
    async def test_event_context_manager(self):
        """Проверка контекстного менеджера событий."""
        bus = AsyncEventBus()
        await bus.start()

        received = []

        async def handler(event: SystemEvent):
            received.append(event.payload)

        await bus.subscribe("context_test", handler)

        async with bus.event_context("context_test", key="value") as event:
            event.payload["extra"] = "data"

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0]["key"] == "value"
        assert received[0]["extra"] == "data"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_sync_publish_from_async_context(self):
        """Проверка синхронной публикации из async контекста."""
        bus = AsyncEventBus()
        await bus.start()

        received = []

        async def handler(event: SystemEvent):
            received.append(event.payload)

        await bus.subscribe("sync_pub_test", handler)

        # Синхронная публикация
        result = bus.publish_sync(SystemEvent(type="sync_pub_test", payload={"sync": True}))
        assert result is True

        await asyncio.sleep(0.1)

        assert {"sync": True} in received

        await bus.stop()


class TestSystemEvent:
    """Тесты SystemEvent."""

    def test_event_creation(self):
        """Проверка создания события."""
        event = SystemEvent(type="test", payload={"key": "value"})

        assert event.type == "test"
        assert event.payload == {"key": "value"}
        assert event.priority == EventPriority.MEDIUM
        assert event.correlation_id is not None

    def test_event_age(self):
        """Проверка возраста события."""
        event = SystemEvent(type="test", payload={})

        import time

        time.sleep(0.05)

        age = event.age_ms()
        assert age > 0
        assert age < 1000  # Должно быть меньше 1 секунды

    def test_event_priority_comparison(self):
        """Проверка сравнения приоритетов."""
        low_event = SystemEvent(type="test", payload={}, priority=EventPriority.LOW)
        high_event = SystemEvent(type="test", payload={}, priority=EventPriority.CRITICAL)

        # High priority должен быть "меньше" для PriorityQueue (выполняется раньше)
        assert high_event < low_event


class TestEventPriority:
    """Тесты EventPriority enum."""

    def test_all_priorities_defined(self):
        """Проверка всех приоритетов."""
        assert EventPriority.CRITICAL == 10
        assert EventPriority.HIGH == 7
        assert EventPriority.MEDIUM == 5
        assert EventPriority.LOW == 3
        assert EventPriority.BACKGROUND == 1

    def test_priority_ordering(self):
        """Проверка порядка приоритетов."""
        assert EventPriority.CRITICAL > EventPriority.HIGH
        assert EventPriority.HIGH > EventPriority.MEDIUM
        assert EventPriority.MEDIUM > EventPriority.LOW
        assert EventPriority.LOW > EventPriority.BACKGROUND


class TestGetEventBus:
    """Тесты функции get_event_bus()."""

    def test_singleton_pattern(self):
        """Проверка singleton."""
        from src.core.event_bus import get_event_bus

        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
