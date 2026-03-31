# src/core/system_service_manager.py
"""
System Service Manager - Адаптер для интеграции новых сервисов в TradingSystem.

Обеспечивает плавную миграцию со старой архитектуры на новую.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.services import (
    MonitoringService,
    OrchestratorService,
    RiskService,
    ServiceManager,
    TradingService,
)

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem

logger = logging.getLogger(__name__)


class SystemServiceManager:
    """
    Менеджер сервисов TradingSystem.

    Инкапсулирует новые сервисы и обеспечивает обратную совместимость.

    Пример использования:
        # В TradingSystem.__init__
        self.service_manager = SystemServiceManager(self)

        # В start_all_threads
        self.service_manager.start_all()

        # В stop
        self.service_manager.stop_all()
    """

    def __init__(self, trading_system: "TradingSystem"):
        """
        Инициализация менеджера сервисов.

        Args:
            trading_system: Ссылка на родительскую систему
        """
        self.trading_system = trading_system
        self.service_manager = ServiceManager(name="TradingSystemServiceManager")

        # Сервисы (инициализируются позже)
        self.trading_service: Optional[TradingService] = None
        self.monitoring_service: Optional[MonitoringService] = None
        self.orchestrator_service: Optional[OrchestratorService] = None
        self.risk_service: Optional[RiskService] = None

        # Флаг использования новых сервисов
        self.use_new_services = False  # По умолчанию False для обратной совместимости

        logger.info("SystemServiceManager создан")

    def initialize_services(self) -> None:
        """
        Инициализировать и зарегистрировать сервисы.

        Вызывается после тяжелой инициализации TradingSystem.
        """
        logger.info("Инициализация сервисов...")

        # Создание сервисов
        self.trading_service = TradingService(
            self.trading_system, interval_seconds=self.trading_system.config.TRADE_INTERVAL_SECONDS
        )

        self.monitoring_service = MonitoringService(self.trading_system, interval_seconds=3.0)  # 3 секунды

        self.orchestrator_service = OrchestratorService(self.trading_system, interval_seconds=300.0)  # 5 минут

        self.risk_service = RiskService(self.trading_system, self.trading_system.risk_engine)

        # Регистрация в менеджере
        self.service_manager.register(self.trading_service)
        self.service_manager.register(self.monitoring_service)
        self.service_manager.register(self.orchestrator_service)
        self.service_manager.register(self.risk_service)

        logger.info(f"Инициализировано {len(self.service_manager.services)} сервисов")

    def start_all(self) -> Dict[str, bool]:
        """
        Запустить все сервисы.

        Returns:
            Dict[str, bool]: Результаты запуска {имя: успех}
        """
        if not self.use_new_services:
            logger.info("Используются СТАРЫЕ потоки (обратная совместимость)")
            return {}

        logger.info("Запуск новых сервисов...")
        results = self.service_manager.start_all()

        # Логирование результатов
        success_count = sum(results.values())
        logger.info(f"Запущено {success_count}/{len(results)} сервисов")

        return results

    def stop_all(self, timeout: float = 5.0) -> Dict[str, bool]:
        """
        Остановить все сервисы.

        Args:
            timeout: Таймаут для каждого сервиса

        Returns:
            Dict[str, bool]: Результаты остановки
        """
        if not self.use_new_services:
            logger.info("Используются СТАРЫЕ потоки (обратная совместимость)")
            return {}

        logger.info("Остановка новых сервисов...")
        results = self.service_manager.stop_all(timeout=timeout)

        success_count = sum(results.values())
        logger.info(f"Остановлено {success_count}/{len(results)} сервисов")

        return results

    def enable_new_services(self, enabled: bool = True) -> None:
        """
        Включить/выключить использование новых сервисов.

        Args:
            enabled: True для использования новых сервисов
        """
        self.use_new_services = enabled
        logger.info(f"Использование новых сервисов: {'ВКЛЮЧЕНО' if enabled else 'ВЫКЛЮЧЕНО'}")

    def get_status(self) -> Dict[str, Any]:
        """
        Получить статус всех сервисов.

        Returns:
            Dict[str, Any]: Статус сервисов
        """
        if self.use_new_services:
            return self.service_manager.get_status_all()
        return {"use_new_services": False}

    def health_check(self) -> Dict[str, bool]:
        """
        Проверить здоровье всех сервисов.

        Returns:
            Dict[str, bool]: Здоровье сервисов
        """
        if not self.use_new_services:
            return {"use_new_services": False}

        health_results = self.service_manager.health_check_all()
        return {name: health.is_healthy for name, health in health_results.items()}

    # Прокси-методы для доступа к сервисам

    def get_trading_service(self) -> Optional[TradingService]:
        """Получить торговый сервис"""
        return self.trading_service

    def get_monitoring_service(self) -> Optional[MonitoringService]:
        """Получить сервис мониторинга"""
        return self.monitoring_service

    def get_orchestrator_service(self) -> Optional[OrchestratorService]:
        """Получить сервис оркестратора"""
        return self.orchestrator_service

    def get_risk_service(self) -> Optional[RiskService]:
        """Получить сервис рисков"""
        return self.risk_service

    # Методы для совместимости со старым кодом

    def get_thread_status(self) -> Dict[str, str]:
        """
        Получить статус потоков (для обратной совместимости).

        Returns:
            Dict[str, str]: {имя: статус}
        """
        if self.use_new_services:
            status_map = {
                "Trading": "RUNNING" if self.trading_service and self.trading_service.is_running else "STOPPED",
                "Monitoring": "RUNNING" if self.monitoring_service and self.monitoring_service.is_running else "STOPPED",
                "Orchestrator": "RUNNING" if self.orchestrator_service and self.orchestrator_service.is_running else "STOPPED",
            }
            return status_map
        else:
            # Старый метод
            return {
                "Trading": "RUNNING" if hasattr(self.trading_system, "trading_thread") else "STOPPED",
                "Monitoring": "RUNNING" if hasattr(self.trading_system, "monitoring_thread") else "STOPPED",
                "Orchestrator": "RUNNING" if hasattr(self.trading_system, "orchestrator_thread") else "STOPPED",
            }
