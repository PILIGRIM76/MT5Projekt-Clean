# src/core/event_bus.py
"""
Асинхронная шина событий с приоритетами и доменной маршрутизацией.

Архитектура:
- PriorityQueue для событий с приоритетами
- Подписчики регистрируются с указанием целевого ThreadDomain
- Автоматическая диспетчеризация в соответствующие executor'ы
- Поддержка correlation_id для трассировки цепочек событий

Обратная совместимость:
- Старый API (EventBus, event_bus, EventType) сохранён полностью
- Новый API (AsyncEventBus, get_event_bus, SystemEvent) доступен отдельно
- Оба API могут сосуществовать
"""

import asyncio
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable, Dict, List, Optional, Set

from src.core.thread_domains import DomainRegistry, ExecutorType, ThreadDomain

# Импорты для обратной совместимости
from .events import Event, EventType

logger = logging.getLogger(__name__)


class EventPriority(IntEnum):
    """Приоритеты событий (чем выше число — тем важнее)"""

    CRITICAL = 10  # Риск-алерты, экстренная остановка
    HIGH = 7  # Торговые сигналы, исполнение ордеров
    MEDIUM = 5  # Обновления данных, инференс моделей
    LOW = 3  # Логирование, метрики, фоновые задачи
    BACKGROUND = 1  # Переобучение моделей, анализ


@dataclass
class SystemEvent:
    """Базовый класс системного события (новый API)"""

    type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    priority: EventPriority = EventPriority.MEDIUM
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_domain: Optional[ThreadDomain] = None
    target_domains: Set[ThreadDomain] = field(default_factory=set)

    # Для отладки и мониторинга
    _created_at: float = field(default_factory=time.time, init=False)

    def age_ms(self) -> float:
        """Возраст события в миллисекундах"""
        return (time.time() - self._created_at) * 1000

    def __lt__(self, other):
        """Для сортировки в PriorityQueue: выше приоритет = раньше"""
        if self.priority != other.priority:
            return self.priority > other.priority  # Инверсия для heapq
        return self.timestamp < other.timestamp


class EventBusError(Exception):
    """Базовое исключение EventBus"""

    pass


class SubscriberTimeoutError(EventBusError):
    """Таймаут обработчика подписчика"""

    pass


class AsyncEventBus:
    """
    Неблокирующая шина событий с поддержкой приоритетов и доменов.

    Поток-безопасна: можно публиковать события из любых потоков.
    Диспетчеризация происходит в выделенном _dispatch цикле.
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        dispatch_interval_ms: float = 10.0,
        default_timeout: float = 30.0,
    ):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self._subscribers: Dict[str, List[Dict]] = defaultdict(list)
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None
        self._dispatch_interval = dispatch_interval_ms / 1000.0
        self._default_timeout = default_timeout

        # Executor'ы для разных доменов (создаются лениво)
        self._executors: Dict[ExecutorType, Any] = {}
        self._executor_lock = threading.Lock()

        # Статистика для мониторинга
        self._stats = {
            "published": 0,
            "dispatched": 0,
            "errors": 0,
            "avg_dispatch_latency_ms": 0.0,
        }
        self._latency_samples: deque = deque(maxlen=100)  # O(1) вместо O(n)

        # Callback для обработки ошибок (можно установить извне)
        self.error_handler: Optional[Callable[[SystemEvent, Exception], None]] = None

    async def start(self):
        """Запуск цикла диспетчеризации"""
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())

        # 🔧 ПРЕДВАРИТЕЛЬНОЕ СОЗДАНИЕ EXECUTOR'ОВ
        # Создаём executor'ы для всех доменов чтобы избежать warning
        with self._executor_lock:
            # THREAD_POOL для большинства доменов
            if ExecutorType.THREAD_POOL not in self._executors:
                self._executors[ExecutorType.THREAD_POOL] = ThreadPoolExecutor(
                    max_workers=8, thread_name_prefix="EventBus-Worker"
                )
                logger.info("Created ThreadPoolExecutor for THREAD_POOL domains")

            # PROCESS_POOL для ML_TRAINING
            if ExecutorType.PROCESS_POOL not in self._executors:
                try:
                    import multiprocessing as mp

                    self._executors[ExecutorType.PROCESS_POOL] = ProcessPoolExecutor(
                        max_workers=2, mp_context=mp.get_context("spawn")
                    )
                    logger.info("Created ProcessPoolExecutor for ML_TRAINING")
                except Exception as e:
                    logger.warning(f"Failed to create ProcessPoolExecutor: {e}")

        logger.info("EventBus started")

    async def stop(self, timeout: float = 10.0):
        """Остановка с ожиданием обработки очереди"""
        if not self._running:
            return
        self._running = False

        if self._dispatch_task:
            try:
                await asyncio.wait_for(self._dispatch_task, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"EventBus dispatch task didn't stop within {timeout}s")
                self._dispatch_task.cancel()

        # Закрытие executor'ов
        for exec_type, executor in self._executors.items():
            if hasattr(executor, "shutdown"):
                executor.shutdown(wait=False)

        logger.info(f"EventBus stopped. Stats: {self._stats}")

    async def publish(self, event: SystemEvent) -> bool:
        """
        Публикация события в шину.

        Returns:
            True если событие принято, False если очередь переполнена
        """
        try:
            # Добавляем метаданные
            if event.source_domain is None:
                # Пытаемся определить домен из текущего потока
                event.source_domain = self._infer_current_domain()

            await asyncio.wait_for(self._queue.put(event), timeout=1.0)  # Быстрый отказ при переполнении
            self._stats["published"] += 1
            logger.debug(f"Published event: {event.type} (priority={event.priority.name})")
            return True

        except asyncio.TimeoutError:
            logger.warning(f"EventBus queue full, dropped event: {event.type}")
            return False
        except Exception as e:
            logger.error(f"Failed to publish event {event.type}: {e}", exc_info=True)
            return False

    def publish_sync(self, event: SystemEvent) -> bool:
        """Синхронная обёртка для публикации из неблок. кода"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если event loop запущен — создаём task
                asyncio.create_task(self.publish(event))
                return True
            else:
                # Если нет — используем run_until_complete
                return loop.run_until_complete(self.publish(event))
        except RuntimeError:
            # Нет event loop в этом потоке — создаём новый (для тестов)
            return asyncio.run(self.publish(event))

    async def subscribe(
        self,
        event_type: str,
        handler: Callable[[SystemEvent], Any],
        domain: ThreadDomain = ThreadDomain.STRATEGY_ENGINE,
        priority: EventPriority = EventPriority.MEDIUM,
        timeout: Optional[float] = None,
    ):
        """
        Регистрация подписчика на событие.

        Args:
            event_type: Тип события (строка или Enum)
            handler: Функция-обработчик (может быть async)
            domain: В каком домене выполнить обработчик
            priority: Приоритет вызова этого подписчика
            timeout: Таймаут выполнения (по умолчанию global)
        """
        config = DomainRegistry.get_config(domain)

        subscriber = {
            "handler": handler,
            "domain": domain,
            "priority": priority,
            "timeout": timeout or config["resources"].timeout_seconds or self._default_timeout,
            "executor_type": config["executor_type"],
        }

        # Сортируем подписчиков по приоритету внутри типа события
        subscribers = self._subscribers[event_type]
        subscribers.append(subscriber)
        subscribers.sort(key=lambda s: s["priority"], reverse=True)

        logger.info(f"Subscribed {handler.__name__} to {event_type} in {domain.name}")

    async def _dispatch_loop(self):
        """Основной цикл диспетчеризации событий"""
        while self._running:
            try:
                # Пытаемся получить событие с таймаутом
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=self._dispatch_interval)
                except asyncio.TimeoutError:
                    continue  # Нормальная ситуация, продолжаем цикл

                dispatch_start = time.time()

                # Находим подписчиков
                subscribers = self._subscribers.get(event.type, [])
                if not subscribers:
                    logger.debug(f"No subscribers for event: {event.type}")
                    continue

                # Запускаем обработчики параллельно
                tasks = []
                for sub in subscribers:
                    task = self._dispatch_to_subscriber(event, sub)
                    tasks.append(task)

                # Ждем выполнения с агрегацией ошибок
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Обработка ошибок
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        self._stats["errors"] += 1
                        sub = subscribers[i]
                        logger.error(f"Handler {sub['handler'].__name__} failed for {event.type}: {result}", exc_info=result)
                        if self.error_handler:
                            self.error_handler(event, result)

                # Обновляем статистику
                latency = (time.time() - dispatch_start) * 1000
                self._stats["dispatched"] += len(subscribers)
                self._update_latency_stat(latency)

                self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("EventBus dispatch loop cancelled")
                break
            except Exception as e:
                logger.error(f"EventBus dispatch error: {e}", exc_info=True)
                self._stats["errors"] += 1
                await asyncio.sleep(0.1)  # Backoff при ошибках

    async def _dispatch_to_subscriber(self, event: SystemEvent, subscriber: Dict) -> Any:
        """Диспетчеризация события конкретному подписчику"""
        handler = subscriber["handler"]
        domain = subscriber["domain"]
        timeout = subscriber["timeout"]
        exec_type = subscriber["executor_type"]

        async def run_handler():
            try:
                if asyncio.iscoroutinefunction(handler):
                    return await asyncio.wait_for(handler(event), timeout=timeout)
                else:
                    # Синхронный хендлер — запускаем в executor
                    loop = asyncio.get_event_loop()
                    executor = self._get_executor(exec_type)

                    # 🔧 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Fallback если executor не создан
                    if executor is None:
                        logger.warning(
                            f"No executor for {exec_type} (domain={domain.name}), "
                            f"running handler {handler.__name__} in current loop"
                        )
                        # Запускаем в текущем loop чтобы не терять события
                        if asyncio.iscoroutinefunction(handler):
                            return await asyncio.wait_for(handler(event), timeout=timeout)
                        else:
                            return handler(event)

                    return await loop.run_in_executor(executor, lambda: handler(event))
            except asyncio.TimeoutError:
                raise SubscriberTimeoutError(f"Handler {handler.__name__} timed out after {timeout}s")

        # Для GUI домена — специальное поведение (не блокировать main loop)
        if domain == ThreadDomain.GUI:
            # В реальной системе здесь будет отправка через Qt signal
            # Для совместимости просто вызываем в текущем контексте
            return await run_handler()

        return await run_handler()

    def _get_executor(self, exec_type: ExecutorType):
        """Ленивое создание executor'ов"""
        with self._executor_lock:
            if exec_type not in self._executors:
                if exec_type == ExecutorType.THREAD_POOL:
                    self._executors[exec_type] = ThreadPoolExecutor(max_workers=8, thread_name_prefix="EventBus-Worker")
                elif exec_type == ExecutorType.PROCESS_POOL:
                    import multiprocessing

                    self._executors[exec_type] = ProcessPoolExecutor(
                        max_workers=2, mp_context=multiprocessing.get_context("spawn")
                    )  # Важно для Windows
                # SINGLE_THREAD и ASYNC_LOOP не требуют executor
                logger.info(f"Created executor for {exec_type}")
            return self._executors.get(exec_type)

    def _infer_current_domain(self) -> Optional[ThreadDomain]:
        """Эвристика для определения домена из текущего контекста"""
        thread_name = threading.current_thread().name
        if "MainThread" in thread_name or "Qt" in thread_name:
            return ThreadDomain.GUI
        elif "MT5" in thread_name:
            return ThreadDomain.MT5_IO
        elif "ML-Train" in thread_name:
            return ThreadDomain.ML_TRAINING
        # По умолчанию
        return None

    def _update_latency_stat(self, new_latency: float):
        """Обновление скользящего среднего латентности"""
        self._latency_samples.append(new_latency)
        # deque(maxlen=100) автоматически удаляет старые записи — нет O(n) pop(0)
        if self._latency_samples:
            self._stats["avg_dispatch_latency_ms"] = sum(self._latency_samples) / len(self._latency_samples)

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики для мониторинга"""
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "subscriber_counts": {event_type: len(subs) for event_type, subs in self._subscribers.items()},
        }

    @asynccontextmanager
    async def event_context(self, event_type: str, **payload):
        """
        Контекстный менеджер для создания и публикации события.

        Пример:
            async with event_bus.event_context("trade_executed", symbol="EURUSD") as event:
                event.payload["price"] = 1.0850
                # Событие автоматически опубликуется при выходе из контекста
        """
        event = SystemEvent(type=event_type, payload=payload.copy())
        try:
            yield event
        finally:
            await self.publish(event)


# Глобальный экземпляр (lazy initialization)
_event_bus: Optional[AsyncEventBus] = None


def get_event_bus() -> AsyncEventBus:
    """Получение глобального экземпляра EventBus"""
    global _event_bus
    if _event_bus is None:
        _event_bus = AsyncEventBus()
    return _event_bus


# ===========================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ: Старый API
# ===========================================
# Код ниже обеспечивает полную совместимость с существующим кодом
# который использует EventBus, event_bus, EventType и т.д.

# ===========================================
# Event Bus Implementation (Legacy API)
# ===========================================


class EventBus:
    """
    Центральная шина событий (LEGACY API).

    Реализует:
    - Синхронные и асинхронные подписчики
    - Историю событий
    - Фильтрацию по типам
    - Обработку ошибок в подписчиках

    Обратная совместимость:
    - Этот класс полностью сохранён для старого кода
    - Новый код должен использовать AsyncEventBus
    """

    _instance: Optional["EventBus"] = None
    _instance_lock: threading.Lock = threading.Lock()  # Thread-safe singleton

    def __new__(cls) -> "EventBus":
        """Singleton паттерн (thread-safe с double-checked locking)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._async_subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_history: deque = deque(maxlen=1000)  # O(1) вместо O(n) pop(0)
        self._max_history = 1000
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        logger.info("EventBus инициализирован (legacy API)")

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Установка event loop для асинхронных операций."""
        self._event_loop = loop
        logger.debug("EventBus event loop установлен")

    # ===========================================
    # Subscription Methods
    # ===========================================

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """
        Подписка на событие (синхронная).

        Args:
            event_type: Тип события
            callback: Функция обратного вызова
        """
        self._subscribers[event_type].append(callback)
        logger.debug(f"Подписчик добавлен на {event_type.value}")

    def subscribe_async(self, event_type: EventType, callback: Callable[[Event], Any]) -> None:
        """Подписка на событие (асинхронная)."""
        self._async_subscribers[event_type].append(callback)
        logger.debug(f"Async подписчик добавлен на {event_type.value}")

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """Отписка от события."""
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)

        if callback in self._async_subscribers[event_type]:
            self._async_subscribers[event_type].remove(callback)

    def unsubscribe_all(self, event_type: EventType) -> None:
        """Отписка всех подписчиков от события."""
        self._subscribers[event_type].clear()
        self._async_subscribers[event_type].clear()

    # ===========================================
    # Publish Methods
    # ===========================================

    def publish(self, event: Event) -> None:
        """
        Публикация события.

        Args:
            event: Событие для публикации
        """
        # Сохранение в историю
        self._event_history.append(event)
        # deque(maxlen=1000) автоматически удаляет старые записи — нет O(n) pop(0)

        logger.debug(f"Публикация события: {event.type.value}")

        # Синхронные подписчики
        for callback in self._subscribers[event.type]:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Ошибка в подписчике {callback.__name__}: {e}", exc_info=True)

        # Асинхронные подписчики
        if self._async_subscribers[event.type]:
            self._publish_async(event)

    def _publish_async(self, event: Event) -> None:
        """Асинхронная публикация события."""

        async def call_async_subscribers():
            for callback in self._async_subscribers[event.type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"Ошибка в async подписчике {callback.__name__}: {e}", exc_info=True)

        if self._event_loop and not self._event_loop.is_closed():
            self._event_loop.call_soon_threadsafe(lambda: asyncio.create_task(call_async_subscribers()))
        else:
            try:
                asyncio.create_task(call_async_subscribers())
            except RuntimeError:
                logger.warning("Нет активного event loop для async subscribers")

    def publish_event(self, event_type: EventType, data: Dict[str, Any], source: Optional[str] = None) -> None:
        """Публикация события с данными."""
        event = Event(type=event_type, data=data, source=source)
        self.publish(event)

    # ===========================================
    # History Methods
    # ===========================================

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100,
        start_time: Optional[Any] = None,
        end_time: Optional[Any] = None,
    ) -> List[Event]:
        """Получение истории событий."""
        filtered = self._event_history

        if event_type:
            filtered = [e for e in filtered if e.type == event_type]

        if start_time:
            filtered = [e for e in filtered if e.timestamp >= start_time]

        if end_time:
            filtered = [e for e in filtered if e.timestamp <= end_time]

        # Используем list() вместо slice для совместимости с type checkers
        result = list(filtered)[-limit:]
        return result

    def get_recent_events(self, event_type: EventType, minutes: int = 5) -> List[Event]:
        """Получение недавних событий за период."""
        from datetime import datetime, timedelta

        start_time = datetime.utcnow() - timedelta(minutes=minutes)
        return self.get_history(event_type=event_type, start_time=start_time, limit=1000)

    def clear_history(self) -> None:
        """Очистка истории событий."""
        self._event_history.clear()

    # ===========================================
    # Statistics
    # ===========================================

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики Event Bus."""
        sync_count = sum(len(subs) for subs in self._subscribers.values())
        async_count = sum(len(subs) for subs in self._async_subscribers.values())

        return {
            "total_sync_subscribers": sync_count,
            "total_async_subscribers": async_count,
            "history_size": len(self._event_history),
            "max_history_size": self._max_history,
            "event_types_subscribed": len([et for et in EventType if self._subscribers[et] or self._async_subscribers[et]]),
        }

    def get_subscriber_count(self, event_type: EventType) -> int:
        """Получение количества подписчиков на событие."""
        return len(self._subscribers[event_type]) + len(self._async_subscribers[event_type])


# ===========================================
# Global Instance (Legacy API)
# ===========================================

event_bus = EventBus()
"""Глобальный экземпляр Event Bus (legacy API)"""


# ===========================================
# Decorators (Legacy API)
# ===========================================


def on_event(event_type: EventType):
    """
    Декоратор для подписки на событие (legacy API).

    Example:
        @on_event(EventType.TRADE_OPENED)
        def handle_trade_opened(event):
            logger.info(f"Сделка: {event.symbol}")
    """

    def decorator(callback: Callable) -> Callable:
        event_bus.subscribe(event_type, callback)
        return callback

    return decorator


def on_event_async(event_type: EventType):
    """
    Декоратор для асинхронной подписки на событие (legacy API).

    Example:
        @on_event_async(EventType.MODEL_LOADED)
        async def handle_model_loaded(event):
            await process_model(event)
    """

    def decorator(callback: Callable) -> Callable:
        event_bus.subscribe_async(event_type, callback)
        return callback

    return decorator
