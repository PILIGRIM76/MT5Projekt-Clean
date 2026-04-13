# src/core/thread_domains.py
"""
Типизированные домены выполнения для системы трейдинга.

Каждый домен определяет:
- Тип executor (thread/process)
- Приоритет выполнения
- Лимиты ресурсов
- Политики таймаутов и повторных попыток

Обратная совместимость:
- Существующий код продолжает работать без изменений
- Декоратор @run_in_domain опционален
- DomainRegistry можно использовать постепенно
"""

import logging
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ExecutorType(Enum):
    """Типы исполнителей задач"""

    SINGLE_THREAD = auto()  # Главный поток (GUI)
    THREAD_POOL = auto()  # Легковесные задачи, I/O-bound
    PROCESS_POOL = auto()  # CPU-bound задачи (ML training)
    ASYNC_LOOP = auto()  # asyncio event loop для сетевого I/O


@dataclass(frozen=True)
class ResourceLimits:
    """Лимиты ресурсов для домена"""

    cpu_percent_max: float = 100.0  # 0-100%
    memory_mb_max: Optional[int] = None
    max_concurrent_tasks: int = 1
    timeout_seconds: Optional[float] = None

    def __post_init__(self):
        if not (0 < self.cpu_percent_max <= 100):
            raise ValueError("cpu_percent_max must be in (0, 100]")
        if self.max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be >= 1")


class ThreadDomain(Enum):
    """
    Домены выполнения с предопределёнными политиками.

    Использование:
        @run_in_domain(ThreadDomain.ML_INFERENCE)
        def predict(self, data): ...
    """

    # === GUI ДОМЕН ===
    GUI = auto()
    """Только главный поток Qt. Никогда не блокировать!"""

    # === I/O ДОМЕНЫ ===
    MT5_IO = auto()
    """Взаимодействие с MetaTrader 5 API (синхронные вызовы)"""

    DATA_INGEST = auto()
    """Загрузка данных: API, файлы, сеть — I/O bound"""

    PERSISTENCE = auto()
    """Запись в БД: SQLite, векторная БД — batched I/O"""

    # === AI/ML ДОМЕНЫ ===
    ML_INFERENCE = auto()
    """Предсказания моделей: CPU-bound, но с NumPy (GIL освобождается)"""

    ML_TRAINING = auto()
    """Обучение моделей: heavy CPU/GPU — ТОЛЬКО ProcessPool"""

    FEATURE_ENGINEERING = auto()
    """Расчёт фич: CPU-bound, можно параллелить"""

    # === БИЗНЕС-ЛОГИКА ===
    STRATEGY_ENGINE = auto()
    """Генерация торговых сигналов: критично по времени"""

    RISK_ENGINE = auto()
    """Расчёт рисков и позиций: критично, но можно кэшировать"""

    ORCHESTRATOR = auto()
    """Координация решений: лёгкие вычисления, частые вызовы"""

    # === ФОНОВЫЕ ЗАДАЧИ ===
    LOGGING = auto()
    """Асинхронная запись логов: низкий приоритет"""

    HEALTH_CHECK = auto()
    """Мониторинг системы: периодические проверки"""


# === КОНФИГУРАЦИЯ ДОМЕНОВ ПО УМОЛЧАНИЮ ===
DEFAULT_DOMAIN_CONFIG: Dict[ThreadDomain, Dict[str, Any]] = {
    ThreadDomain.GUI: {
        "executor_type": ExecutorType.SINGLE_THREAD,
        "resources": ResourceLimits(
            cpu_percent_max=30.0,  # GUI не должен грузить CPU
            max_concurrent_tasks=1,
        ),
        "priority": 10,  # Наивысший приоритет
        "allow_nested_calls": False,
    },
    ThreadDomain.MT5_IO: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=50.0,
            max_concurrent_tasks=2,  # MT5 API не полностью потокобезопасен
            timeout_seconds=30.0,
        ),
        "priority": 8,
        "lock_strategy": "per_symbol",  # Кастомная стратегия блокировки
    },
    ThreadDomain.DATA_INGEST: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=40.0,
            max_concurrent_tasks=4,
            timeout_seconds=60.0,
        ),
        "priority": 6,
    },
    ThreadDomain.PERSISTENCE: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=30.0,
            max_concurrent_tasks=2,
            timeout_seconds=15.0,
        ),
        "priority": 5,
    },
    ThreadDomain.ML_INFERENCE: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=80.0,
            max_concurrent_tasks=4,  # Параллельные предсказания
            timeout_seconds=5.0,  # Быстрый фолбэк
        ),
        "priority": 7,
        "gil_friendly": True,  # NumPy/ONNX освобождают GIL
    },
    ThreadDomain.ML_TRAINING: {
        "executor_type": ExecutorType.PROCESS_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=70.0,  # Оставляем ресурсы системе
            memory_mb_max=8192,  # 8GB лимит на обучение
            max_concurrent_tasks=1,  # Только одно обучение за раз!
            timeout_seconds=300.0,  # 5 минут максимум
        ),
        "priority": 2,  # Низкий приоритет, не мешать трейдингу
        "spawn_method": "spawn",  # Избегать 'fork' на Windows
    },
    ThreadDomain.FEATURE_ENGINEERING: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=60.0,
            max_concurrent_tasks=3,
            timeout_seconds=30.0,
        ),
        "priority": 5,
    },
    ThreadDomain.STRATEGY_ENGINE: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=60.0,
            max_concurrent_tasks=3,
            timeout_seconds=2.0,  # Сигналы должны быть быстрыми
        ),
        "priority": 9,  # Высокий приоритет для торговли
    },
    ThreadDomain.RISK_ENGINE: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=50.0,
            max_concurrent_tasks=2,
            timeout_seconds=3.0,
        ),
        "priority": 9,  # Критично для защиты капитала
    },
    ThreadDomain.ORCHESTRATOR: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=40.0,
            max_concurrent_tasks=2,
            timeout_seconds=5.0,
        ),
        "priority": 8,
    },
    ThreadDomain.LOGGING: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=20.0,
            max_concurrent_tasks=2,
            timeout_seconds=10.0,
        ),
        "priority": 3,
    },
    ThreadDomain.HEALTH_CHECK: {
        "executor_type": ExecutorType.THREAD_POOL,
        "resources": ResourceLimits(
            cpu_percent_max=15.0,
            max_concurrent_tasks=1,
            timeout_seconds=5.0,
        ),
        "priority": 4,
    },
}


class DomainRegistry:
    """Реестр конфигураций доменов с возможностью переопределения"""

    _config: Dict[ThreadDomain, Dict[str, Any]] = DEFAULT_DOMAIN_CONFIG.copy()
    _executors: Dict[ExecutorType, Any] = {}
    _lock = threading.Lock()

    @classmethod
    def register_executor(cls, exec_type: ExecutorType, executor: Any):
        """Регистрация кастомного executor (для тестов или оптимизаций)"""
        with cls._lock:
            cls._executors[exec_type] = executor
            logger.info(f"Registered custom executor for {exec_type}")

    @classmethod
    def get_config(cls, domain: ThreadDomain) -> Dict[str, Any]:
        """Получение конфигурации домена"""
        return cls._config.get(domain, DEFAULT_DOMAIN_CONFIG[ThreadDomain.STRATEGY_ENGINE])

    @classmethod
    def override_config(cls, domain: ThreadDomain, **overrides):
        """Переопределение конфигурации домена (для тестов/тюнинга)"""
        with cls._lock:
            if domain in cls._config:
                cls._config[domain].update(overrides)
                logger.info(f"Overridden config for {domain}: {overrides}")

    @classmethod
    def get_executor(cls, exec_type: ExecutorType) -> Optional[Any]:
        """Получение зарегистрированного executor"""
        with cls._lock:
            return cls._executors.get(exec_type)

    @classmethod
    def reset(cls):
        """Сброс к дефолтным конфигурациям"""
        with cls._lock:
            cls._config = DEFAULT_DOMAIN_CONFIG.copy()
            cls._executors.clear()


def run_in_domain(domain: ThreadDomain):
    """
    Декоратор для выполнения функции в указанном домене.

    Пример:
        @run_in_domain(ThreadDomain.ML_INFERENCE)
        def predict_price(self, symbol: str) -> float:
            return self.model.predict(...)

    Обратная совместимость:
        В текущей реализации просто вызывает функцию напрямую.
        В полной интеграции будет диспетчеризировать через EventBus.
    """

    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            config = DomainRegistry.get_config(domain)
            logger.debug(f"Executing {func.__name__} in domain {domain.name} " f"(priority={config['priority']})")
            return func(*args, **kwargs)

        wrapper.__domain__ = domain
        wrapper.__wrapped__ = func
        return wrapper

    return decorator
