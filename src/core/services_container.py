# src/core/services_container.py
"""
Dependency Injection контейнер для сервисов Genesis Trading System.

Версия 3.0: Поддержка сервисов с управляемым жизненным циклом.

Сервисы:
- DataService: Управление данными (кэширование, MT5)
- MLService: Машинное обучение (признаки, модели)
- ExecutionService: Исполнение ордеров

Пример использования:
    from src.core.services_container import get_data_service, get_ml_service

    data_service = get_data_service()
    await data_service.start()

    ml_service = get_ml_service()
    predictions = await ml_service.predict(df, symbol)
"""

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Импорты компонентов
from src.core.config_loader import load_config
from src.core.config_models import Settings

# ===========================================
# Global Components (Lazy Initialization)
# ===========================================

_config: Optional[Settings] = None
_db_manager: Any = None
_data_service: Any = None
_ml_service: Any = None
_execution_service: Any = None


def get_config() -> Settings:
    """Получение конфигурации (Singleton)."""
    global _config
    if _config is None:
        _config = load_config()
        logger.info("Конфигурация загружена (Singleton)")
    return _config


def get_db_manager():
    """Получение менеджера БД (Singleton)."""
    global _db_manager
    if _db_manager is None:
        from src.db.database_manager import DatabaseManager

        _db_manager = DatabaseManager(get_config())
        logger.info("DatabaseManager инициализирован (Singleton)")
    return _db_manager


# ===========================================
# Сервисы (Версия 3.0)
# ===========================================


def get_data_service() -> Any:
    """Получение сервиса данных (Singleton)."""
    global _data_service
    if _data_service is None:
        from src.core.services.data_service import DataService

        _data_service = DataService(config=get_config())
        logger.info("DataService инициализирован (Singleton)")
    return _data_service


def get_ml_service() -> Any:
    """Получение ML сервиса (Singleton)."""
    global _ml_service
    if _ml_service is None:
        from src.core.services.ml_service import MLService

        _ml_service = MLService(
            config=get_config(),
            db_manager=get_db_manager(),
        )
        logger.info("MLService инициализирован (Singleton)")
    return _ml_service


def get_execution_service() -> Any:
    """Получение сервиса исполнения (Singleton)."""
    global _execution_service
    if _execution_service is None:
        import threading

        from src.core.services.execution_service import ExecutionService

        _execution_service = ExecutionService(
            config=get_config(),
            db_manager=get_db_manager(),
            mt5_lock=threading.Lock(),
        )
        logger.info("ExecutionService инициализирован (Singleton)")
    return _execution_service


async def start_all_services() -> None:
    """Запуск всех сервисов."""
    logger.info("Запуск всех сервисов...")

    services = [
        ("DataService", get_data_service()),
        ("MLService", get_ml_service()),
        ("ExecutionService", get_execution_service()),
    ]

    for name, service in services:
        try:
            await service.start()
            logger.info(f"{name}: ✅ Запущен")
        except Exception as e:
            logger.error(f"{name}: ❌ Ошибка запуска: {e}")
            raise


async def stop_all_services() -> None:
    """Остановка всех сервисов."""
    logger.info("Остановка всех сервисов...")

    services = [
        ("DataService", get_data_service()),
        ("MLService", get_ml_service()),
        ("ExecutionService", get_execution_service()),
    ]

    for name, service in services:
        try:
            await service.stop()
            logger.info(f"{name}: ✅ Остановлен")
        except Exception as e:
            logger.error(f"{name}: ❌ Ошибка остановки: {e}")


def get_all_health_checks() -> Dict[str, Any]:
    """Получение статуса здоровья всех сервисов."""
    health_status = {}

    services = [
        ("DataService", get_data_service()),
        ("MLService", get_ml_service()),
        ("ExecutionService", get_execution_service()),
    ]

    for name, service in services:
        try:
            health_status[name] = service.health_check()
        except Exception as e:
            health_status[name] = {"status": "error", "error": str(e)}

    return health_status
