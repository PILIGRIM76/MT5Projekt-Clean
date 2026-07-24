# src/core/circuit_breaker.py
"""
Circuit Breaker — защита от каскадных сбоев в системе трейдинга.

Архитектура:
- Отслеживание ошибок по компонентам/сервисам
- Три состояния: CLOSED (норма), OPEN (сбой), HALF_OPEN (проверка)
- Автоматическое восстановление через таймаут
- Graceful degradation при сбоях
- Метрики для мониторинга здоровья

Пример использования:
    breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=30.0,
        name="mt5_service"
    )

    @breaker.protect
    def fetch_prices(symbol: str) -> list:
        return mt5.symbol_info_tick(symbol)

    # Или вручную:
    if breaker.is_open():
        return cached_prices  # Fallback
    try:
        prices = fetch_prices(symbol)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        raise
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Состояния circuit breaker"""

    CLOSED = auto()  # Нормальная работа, запросы проходят
    OPEN = auto()  # Сбой, запросы блокируются
    HALF_OPEN = auto()  # Проверка восстановления, один запрос разрешён


class CircuitBreakerError(Exception):
    """Базовое исключение Circuit Breaker"""

    pass


class CircuitOpenError(CircuitBreakerError):
    """Вызывается когда circuit breaker открыт (сбой)"""

    def __init__(self, breaker_name: str, remaining_timeout: float):
        self.breaker_name = breaker_name
        self.remaining_timeout = remaining_timeout
        super().__init__(f"Circuit breaker '{breaker_name}' is OPEN. " f"Retry after {remaining_timeout:.1f}s")


@dataclass
class CircuitMetrics:
    """Метрики circuit breaker"""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Отклонены из-за OPEN состояния
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.time)
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100

    @property
    def failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100


class CircuitBreaker:
    """
    Circuit breaker для защиты от каскадных сбоев.

    Паттерн:
    1. CLOSED: нормальная работа, считаем ошибки
    2. OPEN: при достижении порога ошибок, блокируем запросы
    3. HALF_OPEN: после таймаута, пропускаем один тестовый запрос
    4. При успехе → CLOSED, при ошибке → OPEN

    Использование:
        breaker = CircuitBreaker(
            failure_threshold=5,      # 5 ошибок подряд = OPEN
            recovery_timeout=30.0,    # Ждём 30 сек перед HALF_OPEN
            name="mt5_api"
        )

        # Декоратор
        @breaker.protect
        def call_mt5_api(): ...

        # Ручное использование
        if breaker.is_open():
            return fallback_value
        try:
            result = call_mt5_api()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure()
            raise
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        name: str = "unnamed",
    ):
        """
        Args:
            failure_threshold: Количество ошибок для перехода в OPEN
            recovery_timeout: Время ожидания перед HALF_OPEN (секунды)
            half_open_max_calls: Максимум тестовых запросов в HALF_OPEN
            name: Имя breaker для логирования
        """
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        self._name = name

        self._opened_at: Optional[float] = None
        self._half_open_calls = 0

        self.metrics = CircuitMetrics()

        logger.info(f"CircuitBreaker '{name}' initialized: " f"threshold={failure_threshold}, timeout={recovery_timeout}s")

    @property
    def state(self) -> CircuitState:
        """Получить текущее состояние (с автоматическим переходом)"""
        with self._lock:
            self._check_state_transition()
            return self._state

    @property
    def name(self) -> str:
        return self._name

    def is_closed(self) -> bool:
        """Проверка: breaker закрыт (нормальная работа)"""
        return self.state == CircuitState.CLOSED

    def is_open(self) -> bool:
        """Проверка: breaker открыт (сбой, запросы блокируются)"""
        return self.state == CircuitState.OPEN

    def is_half_open(self) -> bool:
        """Проверка: breaker в состоянии проверки"""
        return self.state == CircuitState.HALF_OPEN

    def can_execute(self) -> bool:
        """Можно ли выполнить запрос сейчас"""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.OPEN:
            return False
        else:  # HALF_OPEN
            with self._lock:
                return self._half_open_calls < self._half_open_max_calls

    def record_success(self):
        """Записать успешное выполнение"""
        with self._lock:
            self.metrics.total_calls += 1
            self.metrics.successful_calls += 1
            self.metrics.consecutive_successes += 1
            self.metrics.consecutive_failures = 0

            # HALF_OPEN → CLOSED при успехе
            if self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.CLOSED)
                logger.info(f"CircuitBreaker '{self._name}' CLOSED after successful " f"recovery test")

    def record_failure(self):
        """Записать ошибку выполнения"""
        with self._lock:
            self.metrics.total_calls += 1
            self.metrics.failed_calls += 1
            self.metrics.consecutive_failures += 1
            self.metrics.consecutive_successes = 0
            self.metrics.last_failure_time = time.time()

            # CLOSED → OPEN при достижении порога
            if self._state == CircuitState.CLOSED and self.metrics.consecutive_failures >= self._failure_threshold:
                self._transition_to(CircuitState.OPEN)
                logger.warning(
                    f"CircuitBreaker '{self._name}' OPENED after " f"{self.metrics.consecutive_failures} consecutive failures"
                )

            # HALF_OPEN → OPEN при ошибке
            elif self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
                logger.warning(f"CircuitBreaker '{self._name}' re-OPENED after " f"failed recovery test")

    def allow_request(self) -> bool:
        """
        Проверить можно ли выполнить запрос.

        Returns:
            True если запрос разрешён, False если breaker OPEN

        Raises:
            CircuitOpenError: Если breaker OPEN (для явной обработки)
        """
        state = self.state

        if state == CircuitState.CLOSED:
            return True

        elif state == CircuitState.OPEN:
            with self._lock:
                remaining = self._get_remaining_timeout()
                self.metrics.rejected_calls += 1
                logger.debug(f"CircuitBreaker '{self._name}' rejecting request " f"({remaining:.1f}s until retry)")
            raise CircuitOpenError(self._name, remaining)

        else:  # HALF_OPEN
            with self._lock:
                if self._half_open_calls < self._half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                else:
                    self.metrics.rejected_calls += 1
                    return False

    def protect(self, func: Callable) -> Callable:
        """
        Декоратор для автоматической защиты функции.

        Пример:
            @breaker.protect
            def call_api():
                return requests.get(url)
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.can_execute():
                self.metrics.rejected_calls += 1
                raise CircuitOpenError(self._name, self._get_remaining_timeout())

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise

        # Добавляем ссылку на breaker для мониторинга
        wrapper.__circuit_breaker__ = self
        return wrapper

    def reset(self):
        """Сбросить breaker в CLOSED (для тестов или ручного восстановления)"""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            logger.info(f"CircuitBreaker '{self._name}' manually reset to CLOSED")

    def get_metrics(self) -> Dict[str, Any]:
        """Получить метрики для мониторинга"""
        with self._lock:
            return {
                "name": self._name,
                "state": self._state.name,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
                "metrics": {
                    "total_calls": self.metrics.total_calls,
                    "successful_calls": self.metrics.successful_calls,
                    "failed_calls": self.metrics.failed_calls,
                    "rejected_calls": self.metrics.rejected_calls,
                    "success_rate": self.metrics.success_rate,
                    "failure_rate": self.metrics.failure_rate,
                    "consecutive_failures": self.metrics.consecutive_failures,
                    "last_failure_time": self.metrics.last_failure_time,
                },
                "opened_at": self._opened_at,
                "remaining_timeout": (self._get_remaining_timeout() if self._state == CircuitState.OPEN else 0),
            }

    def _check_state_transition(self):
        """Проверить нужен ли переход OPEN → HALF_OPEN"""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.time() - self._opened_at
            if elapsed >= self._recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
                self._half_open_calls = 0
                logger.info(f"CircuitBreaker '{self._name}' transitioned to HALF_OPEN " f"(testing recovery)")

    def _transition_to(self, new_state: CircuitState):
        """Переход в новое состояние"""
        old_state = self._state
        self._state = new_state
        self.metrics.last_state_change = time.time()

        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
        elif new_state == CircuitState.CLOSED:
            self._opened_at = None
            self.metrics.consecutive_failures = 0
            self._half_open_calls = 0

    def _get_remaining_timeout(self) -> float:
        """Оставшееся время до HALF_OPEN"""
        if self._opened_at is None:
            return 0.0
        elapsed = time.time() - self._opened_at
        remaining = self._recovery_timeout - elapsed
        return max(0.0, remaining)


# ===========================================
# Circuit Breaker Registry
# ===========================================


class CircuitBreakerRegistry:
    """
    Реестр circuit breaker для управления всеми компонентами.

    Использование:
        registry = CircuitBreakerRegistry()

        # Регистрация
        registry.register("mt5_api", failure_threshold=5)
        registry.register("db_service", failure_threshold=3)

        # Получение
        breaker = registry.get("mt5_api")

        # Проверка здоровья
        health = registry.get_health_report()
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> CircuitBreaker:
        """Зарегистрировать новый circuit breaker"""
        with self._lock:
            if name in self._breakers:
                logger.warning(f"CircuitBreaker '{name}' already exists, replacing")

            breaker = CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                name=name,
            )
            self._breakers[name] = breaker
            logger.info(f"Registered CircuitBreaker '{name}'")
            return breaker

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Получить circuit breaker по имени"""
        with self._lock:
            return self._breakers.get(name)

    def unregister(self, name: str) -> bool:
        """Удалить circuit breaker"""
        with self._lock:
            return self._breakers.pop(name, None) is not None

    def get_all(self) -> Dict[str, CircuitBreaker]:
        """Получить все circuit breaker'ы"""
        with self._lock:
            return self._breakers.copy()

    def get_health_report(self) -> Dict[str, Any]:
        """Получить отчёт о здоровье всех компонентов"""
        with self._lock:
            report = {
                "total_breakers": len(self._breakers),
                "open_circuits": 0,
                "healthy_circuits": 0,
                "components": {},
            }

            for name, breaker in self._breakers.items():
                metrics = breaker.get_metrics()
                report["components"][name] = metrics

                if breaker.is_open():
                    report["open_circuits"] += 1
                else:
                    report["healthy_circuits"] += 1

            report["overall_health"] = "critical" if report["open_circuits"] > 0 else "healthy"

            return report

    def reset_all(self):
        """Сбросить все circuit breaker'ы"""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()
            logger.info("All CircuitBreakers reset")


# Глобальный реестр
circuit_breaker_registry = CircuitBreakerRegistry()


def get_circuit_breaker(name: str) -> Optional[CircuitBreaker]:
    """Получить circuit breaker из глобального реестра"""
    return circuit_breaker_registry.get(name)


def create_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> CircuitBreaker:
    """Создать и зарегистрировать circuit breaker"""
    return circuit_breaker_registry.register(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )
