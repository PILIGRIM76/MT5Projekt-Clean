# src/core/services/base_service.py
"""
Абстрактный базовый класс для всех сервисов Genesis Trading System.

Обеспечивает:
- Единообразный жизненный цикл (start/stop)
- Health check для мониторинга
- Базовое логирование
- Обработку ошибок
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, NamedTuple, Optional

from src.core.config_models import Settings


class HealthStatus(NamedTuple):
    """Статус здоровья сервиса."""

    healthy: bool
    message: str
    details: Optional[Dict[str, Any]] = None


logger = logging.getLogger(__name__)


class BaseService(ABC):
    """
    Абстрактный базовый класс для всех сервисов.

    Атрибуты:
        config: Конфигурация системы
        name: Имя сервиса (для логирования)
        _running: Флаг работы сервиса
        _healthy: Флаг здоровья сервиса
    """

    def __init__(self, config: Settings, name: str = "BaseService"):
        """
        Инициализация сервиса.

        Args:
            config: Конфигурация системы
            name: Имя сервиса
        """
        self.config = config
        self.name = name
        self._running = False
        self._healthy = False
        self._db_write_queue = None  # Опциональная очередь для записи в БД

        logger.info(f"{self.name} инициализирован")

    @abstractmethod
    async def start(self) -> None:
        """
        Запуск сервиса.

        Должен быть реализован в наследниках.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Остановка сервиса.

        Должен быть реализован в наследниках.
        """
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья сервиса.

        Returns:
            Словарь с информацией о состоянии:
            - status: "healthy" | "unhealthy" | "degraded"
            - details: Дополнительная информация
        """
        pass

    def set_db_write_queue(self, queue: asyncio.Queue) -> None:
        """
        Установка очереди для записи в БД.

        Args:
            queue: Асинхронная очередь
        """
        self._db_write_queue = queue
        logger.debug(f"{self.name}: DB write queue установлен")

    async def _safe_execute(self, coro: asyncio.coroutine, operation: str) -> Optional[Any]:
        """
        Безопасное выполнение асинхронной операции с обработкой ошибок.

        Args:
            coro: Корутина для выполнения
            operation: Название операции (для логирования)

        Returns:
            Результат выполнения или None при ошибке
        """
        try:
            return await coro
        except asyncio.CancelledError:
            logger.warning(f"{self.name}: Операция '{operation}' отменена")
            raise
        except Exception as e:
            logger.error(f"{self.name}: Ошибка при выполнении '{operation}': {e}", exc_info=True)
            self._healthy = False
            return None

    def _sync_safe_execute(self, func: callable, operation: str) -> Optional[Any]:
        """
        Безопасное выполнение синхронной операции с обработкой ошибок.

        Args:
            func: Функция для выполнения
            operation: Название операции (для логирования)

        Returns:
            Результат выполнения или None при ошибке
        """
        try:
            return func()
        except Exception as e:
            logger.error(f"{self.name}: Ошибка при выполнении '{operation}': {e}", exc_info=True)
            self._healthy = False
            return None

    @property
    def is_running(self) -> bool:
        """Проверка, запущен ли сервис."""
        return self._running

    @property
    def is_healthy(self) -> bool:
        """Проверка здоровья сервиса."""
        return self._healthy

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, running={self._running}, healthy={self._healthy})"
