# src/core/services/base_service.py
"""
Базовый класс для всех сервисов системы.

Предоставляет:
- Стандартизированный интерфейс (start, stop, health_check)
- Встроенное логирование
- Мониторинг состояния
- Обработку ошибок
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceState(Enum):
    """Состояние сервиса"""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthStatus:
    """Статус здоровья сервиса"""

    is_healthy: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    last_check: Optional[datetime] = None
    message: str = ""


@dataclass
class ServiceMetrics:
    """Метрики сервиса"""

    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None
    uptime_seconds: float = 0.0
    operations_count: int = 0
    errors_count: int = 0
    last_operation_time: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    custom_metrics: Dict[str, float] = field(default_factory=dict)


class BaseService(ABC):
    """
    Абстрактный базовый класс для всех сервисов.

    Все сервисы должны реализовать:
    - _on_start(): Логика запуска
    - _on_stop(): Логика остановки
    - _health_check(): Проверка здоровья
    - name: Уникальное имя сервиса
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self.state = ServiceState.CREATED
        self.metrics = ServiceMetrics()
        self._health_checks: List[callable] = []
        self._logger = logging.getLogger(f"{__name__}.{name}")

        self._logger.info(f"Сервис '{name}' создан")

    @property
    def is_running(self) -> bool:
        """Проверить, запущен ли сервис"""
        return self.state == ServiceState.RUNNING

    @property
    def is_healthy(self) -> bool:
        """Проверить здоровье сервиса"""
        if self.state != ServiceState.RUNNING:
            return False
        health = self.health_check()
        return health.is_healthy

    def start(self) -> bool:
        """
        Запустить сервис.

        Returns:
            bool: True если запуск успешен
        """
        if self.state == ServiceState.RUNNING:
            self._logger.warning("Сервис уже запущен")
            return True

        if self.state == ServiceState.STARTING:
            self._logger.warning("Сервис уже в процессе запуска")
            return False

        self._logger.info("Запуск сервиса...")
        self.state = ServiceState.STARTING

        try:
            self._on_start()
            self.state = ServiceState.RUNNING
            self.metrics.start_time = datetime.now()
            self._logger.info("Сервис успешно запущен")
            return True
        except Exception as e:
            self._logger.error(f"Ошибка при запуске: {e}", exc_info=True)
            self.state = ServiceState.ERROR
            self.metrics.errors_count += 1
            self.metrics.last_error = str(e)
            self.metrics.last_error_time = datetime.now()
            return False

    def stop(self, timeout: float = 5.0) -> bool:
        """
        Остановить сервис.

        Args:
            timeout: Максимальное время ожидания остановки (сек)

        Returns:
            bool: True если остановка успешна
        """
        if self.state not in (ServiceState.RUNNING, ServiceState.STARTING):
            self._logger.info("Сервис не запущен")
            return True

        self._logger.info("Остановка сервиса...")
        self.state = ServiceState.STOPPING

        try:
            self._on_stop()
            self.state = ServiceState.STOPPED
            self.metrics.stop_time = datetime.now()

            if self.metrics.start_time:
                self.metrics.uptime_seconds = (self.metrics.stop_time - self.metrics.start_time).total_seconds()

            self._logger.info("Сервис успешно остановлен")
            return True
        except Exception as e:
            self._logger.error(f"Ошибка при остановке: {e}", exc_info=True)
            self.state = ServiceState.ERROR
            self.metrics.errors_count += 1
            self.metrics.last_error = str(e)
            self.metrics.last_error_time = datetime.now()
            return False

    def restart(self, timeout: float = 5.0) -> bool:
        """Перезапустить сервис"""
        self._logger.info("Перезапуск сервиса...")
        if self.is_running:
            if not self.stop(timeout=timeout):
                return False
        return self.start()

    @abstractmethod
    def _on_start(self) -> None:
        """
        Логика запуска сервиса.

        Должен быть реализован в подклассе.
        """
        pass

    @abstractmethod
    def _on_stop(self) -> None:
        """
        Логика остановки сервиса.

        Должен быть реализован в подклассе.
        """
        pass

    @abstractmethod
    def _health_check(self) -> HealthStatus:
        """
        Проверка здоровья сервиса.

        Должен быть реализован в подклассе.

        Returns:
            HealthStatus: Статус здоровья
        """
        pass

    def health_check(self) -> HealthStatus:
        """
        Публичная проверка здоровья с обновлением метрик.

        Returns:
            HealthStatus: Статус здоровья
        """
        try:
            health = self._health_check()
            health.last_check = datetime.now()

            if not health.is_healthy:
                self.state = ServiceState.UNHEALTHY
                self._logger.warning(f"Сервис нездоров: {health.message}")

            return health
        except Exception as e:
            self._logger.error(f"Ошибка проверки здоровья: {e}", exc_info=True)
            return HealthStatus(is_healthy=False, message=f"Ошибка проверки здоровья: {e}")

    def register_health_check(self, check_func: callable) -> None:
        """Зарегистрировать дополнительную проверку здоровья"""
        self._health_checks.append(check_func)
        self._logger.debug(f"Зарегистрирована проверка здоровья: {check_func.__name__}")

    def get_metrics(self) -> ServiceMetrics:
        """Получить метрики сервиса"""
        if self.state == ServiceState.RUNNING and self.metrics.start_time:
            self.metrics.uptime_seconds = (datetime.now() - self.metrics.start_time).total_seconds()
        return self.metrics

    def get_status(self) -> Dict[str, Any]:
        """Получить полный статус сервиса"""
        return {
            "name": self.name,
            "state": self.state.value,
            "is_running": self.is_running,
            "is_healthy": self.is_healthy,
            "metrics": {
                "uptime_seconds": self.metrics.uptime_seconds,
                "operations_count": self.metrics.operations_count,
                "errors_count": self.metrics.errors_count,
                "last_error": self.metrics.last_error,
            },
            "health": self.health_check().__dict__,
        }

    def increment_operations(self, count: int = 1) -> None:
        """Увеличить счетчик операций"""
        self.metrics.operations_count += count
        self.metrics.last_operation_time = datetime.now()

    def record_error(self, error: str) -> None:
        """Записать ошибку"""
        self.metrics.errors_count += 1
        self.metrics.last_error = error
        self.metrics.last_error_time = datetime.now()
        self._logger.error(f"Записана ошибка: {error}")

    def record_metric(self, name: str, value: float) -> None:
        """Записать пользовательскую метрику"""
        self.metrics.custom_metrics[name] = value
        self._logger.debug(f"Метрика '{name}': {value}")


class ServiceManager:
    """
    Менеджер сервисов - управляет жизненным циклом группы сервисов.

    Пример использования:
        manager = ServiceManager()
        manager.register(service1)
        manager.register(service2)
        manager.start_all()
        ...
        manager.stop_all()
    """

    def __init__(self, name: str = "ServiceManager"):
        self.name = name
        self.services: Dict[str, BaseService] = {}
        self._logger = logging.getLogger(f"{__name__}.{name}")
        self._logger.info(f"Менеджер сервисов '{name}' создан")

    def register(self, service: BaseService) -> None:
        """Зарегистрировать сервис"""
        if service.name in self.services:
            self._logger.warning(f"Сервис '{service.name}' уже зарегистрирован")
        self.services[service.name] = service
        self._logger.info(f"Зарегистрирован сервис: {service.name}")

    def unregister(self, service_name: str) -> Optional[BaseService]:
        """Отрегистрировать сервис"""
        service = self.services.pop(service_name, None)
        if service:
            self._logger.info(f"Отрегистрирован сервис: {service_name}")
        return service

    def get_service(self, name: str) -> Optional[BaseService]:
        """Получить сервис по имени"""
        return self.services.get(name)

    def start_all(self) -> Dict[str, bool]:
        """
        Запустить все сервисы.

        Returns:
            Dict[str, bool]: Результаты запуска {name: success}
        """
        self._logger.info("Запуск всех сервисов...")
        results = {}

        for name, service in self.services.items():
            results[name] = service.start()
            if not results[name]:
                self._logger.error(f"Не удалось запустить сервис: {name}")

        success_count = sum(results.values())
        self._logger.info(f"Запущено {success_count}/{len(results)} сервисов")
        return results

    def stop_all(self, timeout: float = 5.0, reverse_order: bool = True) -> Dict[str, bool]:
        """
        Остановить все сервисы.

        Args:
            timeout: Таймаут для каждого сервиса
            reverse_order: Останавливать в обратном порядке

        Returns:
            Dict[str, bool]: Результаты остановки {name: success}
        """
        self._logger.info("Остановка всех сервисов...")

        services = list(self.services.values())
        if reverse_order:
            services.reverse()

        results = {}
        for service in services:
            results[service.name] = service.stop(timeout=timeout)
            if not results[service.name]:
                self._logger.error(f"Не удалось остановить сервис: {service.name}")

        success_count = sum(results.values())
        self._logger.info(f"Остановлено {success_count}/{len(results)} сервисов")
        return results

    def restart_all(self, timeout: float = 5.0) -> Dict[str, bool]:
        """Перезапустить все сервисы"""
        self._logger.info("Перезапуск всех сервисов...")
        self.stop_all(timeout=timeout)
        time.sleep(1)  # Пауза перед перезапуском
        return self.start_all()

    def health_check_all(self) -> Dict[str, HealthStatus]:
        """Проверить здоровье всех сервисов"""
        results = {}
        all_healthy = True

        for name, service in self.services.items():
            health = service.health_check()
            results[name] = health
            if not health.is_healthy:
                all_healthy = False

        status = "здоровы" if all_healthy else "есть проблемы"
        self._logger.info(f"Проверка здоровья: все сервисы {status}")
        return results

    def get_status_all(self) -> Dict[str, Dict[str, Any]]:
        """Получить статус всех сервисов"""
        return {name: service.get_status() for name, service in self.services.items()}

    def get_running_count(self) -> int:
        """Получить количество запущенных сервисов"""
        return sum(1 for s in self.services.values() if s.is_running)

    def get_healthy_count(self) -> int:
        """Получить количество здоровых сервисов"""
        return sum(1 for s in self.services.values() if s.is_healthy)
