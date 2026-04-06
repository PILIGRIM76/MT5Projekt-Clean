# src/core/system_service_manager.py
"""
System Service Manager - Адаптер для интеграции новых сервисов в TradingSystem.

Обеспечивает плавную миграцию со старой архитектуры на новую.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict

from src.core.services_container import (
    get_all_health_checks,
    get_data_service,
    get_execution_service,
    get_ml_service,
    start_all_services,
    stop_all_services,
)

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem

logger = logging.getLogger(__name__)


class SystemServiceManager:
    """
    Менеджер сервисов TradingSystem.

    Инкапсулирует новые сервисы и обеспечивает обратную совместимость.
    """

    def __init__(self, trading_system: "TradingSystem"):
        """
        Инициализация менеджера сервисов.

        Args:
            trading_system: Ссылка на родительскую систему
        """
        self.trading_system = trading_system

        # Получаем сервисы из контейнера
        self.data_service = get_data_service()
        self.ml_service = get_ml_service()
        self.execution_service = get_execution_service()

        # Устанавливаем ссылку на TradingSystem для ExecutionService
        self.execution_service.set_trading_system_ref(trading_system)

        logger.info("SystemServiceManager инициализирован")

    async def initialize_services(self) -> None:
        """
        Инициализировать и запустить сервисы.

        Вызывается после тяжелой инициализации TradingSystem.
        """
        logger.info("Инициализация сервисов...")

        try:
            await start_all_services()
            logger.info("Все сервисы запущены успешно")
        except Exception as e:
            logger.error(f"Ошибка запуска сервисов: {e}")
            raise

    def start_all(self) -> Dict[str, bool]:
        """
        Запустить все сервисы (синхронная обёртка).

        Returns:
            Dict[str, bool]: Результаты запуска {имя: успех}
        """
        logger.info("Запуск сервисов...")

        try:
            # Используем asyncio.run для создания event loop в текущем потоке (Python 3.7+)
            # Это решает ошибку "There is no current event loop" в фоновых потоках
            asyncio.run(start_all_services())

            return {
                "DataService": True,
                "MLService": True,
                "ExecutionService": True,
            }
        except Exception as e:
            logger.error(f"Ошибка запуска: {e}")
            return {
                "DataService": False,
                "MLService": False,
                "ExecutionService": False,
            }

    def stop_all(self, timeout: float = 5.0) -> Dict[str, bool]:
        """
        Остановить все сервисы.

        Args:
            timeout: Таймаут для каждого сервиса

        Returns:
            Dict[str, bool]: Результаты остановки
        """
        logger.info("Остановка сервисов...")

        try:
            # Используем asyncio.run для безопасного создания event loop в любом потоке
            asyncio.run(stop_all_services())

            return {
                "DataService": True,
                "MLService": True,
                "ExecutionService": True,
            }
        except Exception as e:
            logger.error(f"Ошибка остановки: {e}")
            return {
                "DataService": False,
                "MLService": False,
                "ExecutionService": False,
            }

    def get_status(self) -> Dict[str, Any]:
        """
        Получить статус всех сервисов.

        Returns:
            Dict[str, Any]: Статус сервисов
        """
        return {
            "data_service": {
                "running": self.data_service.is_running,
                "healthy": self.data_service.is_healthy,
            },
            "ml_service": {
                "running": self.ml_service.is_running,
                "healthy": self.ml_service.is_healthy,
            },
            "execution_service": {
                "running": self.execution_service.is_running,
                "healthy": self.execution_service.is_healthy,
            },
        }

    def health_check(self) -> Dict[str, bool]:
        """
        Проверить здоровье всех сервисов.

        Returns:
            Dict[str, bool]: Здоровье сервисов
        """
        health_checks = get_all_health_checks()

        return {name: check.get("status") == "healthy" for name, check in health_checks.items()}

    # Прокси-методы для доступа к сервисам

    def get_data_service(self):
        """Получить сервис данных."""
        return self.data_service

    def get_ml_service(self):
        """Получить ML сервис."""
        return self.ml_service

    def get_execution_service(self):
        """Получить сервис исполнения."""
        return self.execution_service

    # Методы для совместимости со старым кодом

    def get_thread_status(self) -> Dict[str, str]:
        """
        Получить статус потоков (для обратной совместимости).

        Returns:
            Dict[str, str]: {имя: статус}
        """
        return {
            "Data": "RUNNING" if self.data_service.is_running else "STOPPED",
            "ML": "RUNNING" if self.ml_service.is_running else "STOPPED",
            "Execution": "RUNNING" if self.execution_service.is_running else "STOPPED",
        }
