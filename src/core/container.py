# src/core/container.py
"""
Dependency Injection контейнер для Genesis Trading System.

Упрощенная версия для Фазы 2. Предоставляет централизованный доступ к компонентам.

Пример использования:
    from src.core.container import get_db_manager, get_risk_engine

    db_manager = get_db_manager()
    risk_engine = get_risk_engine()
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Импорты компонентов
from src.core.config_loader import load_config
from src.core.config_models import Settings

# ===========================================
# Global Components (Lazy Initialization)
# ===========================================

_config: Optional[Settings] = None
_db_manager: Any = None
_vector_db_manager: Any = None
_data_provider: Any = None
_risk_engine: Any = None
_model_factory: Any = None
_trading_system: Any = None


def get_config() -> Settings:
    """
    Получение конфигурации (Singleton).

    Returns:
        Конфигурация системы
    """
    global _config
    if _config is None:
        _config = load_config()
        logger.info("Конфигурация загружена (Singleton)")
    return _config


def get_db_manager():
    """
    Получение менеджера БД (Singleton).

    Returns:
        DatabaseManager
    """
    global _db_manager
    if _db_manager is None:
        from src.db.database_manager import DatabaseManager

        _db_manager = DatabaseManager(get_config())
        logger.info("DatabaseManager инициализирован (Singleton)")
    return _db_manager


def get_vector_db_manager():
    """
    Получение менеджера векторной БД (Singleton).

    Returns:
        VectorDBManager
    """
    global _vector_db_manager
    if _vector_db_manager is None:
        from src.db.vector_db_manager import VectorDBManager

        cfg = get_config()
        _vector_db_manager = VectorDBManager(path=cfg.vector_db.path, embedding_model=cfg.vector_db.embedding_model)
        logger.info("VectorDBManager инициализирован (Singleton)")
    return _vector_db_manager


def get_data_provider():
    """
    Получение провайдера данных (Singleton).

    Returns:
        DataProvider
    """
    global _data_provider
    if _data_provider is None:
        from src.data.data_provider import DataProvider

        _data_provider = DataProvider(config=get_config(), db_manager=get_db_manager())
        logger.info("DataProvider инициализирован (Singleton)")
    return _data_provider


def get_risk_engine(trading_system_ref=None):
    """
    Получение риск-движка (Factory).

    Args:
        trading_system_ref: Ссылка на торговую систему

    Returns:
        RiskEngine
    """
    from src.kg.knowledge_graph import KnowledgeGraphQuerier
    from src.risk.risk_engine import RiskEngine

    kg_querier = KnowledgeGraphQuerier()
    risk_engine = RiskEngine(config=get_config(), trading_system_ref=trading_system_ref, querier=kg_querier)
    logger.info("RiskEngine инициализирован (Factory)")
    return risk_engine


def get_model_factory():
    """
    Получение фабрики моделей (Singleton).

    Returns:
        ModelFactory
    """
    global _model_factory
    if _model_factory is None:
        from src.ml.model_factory import ModelFactory

        _model_factory = ModelFactory(config=get_config(), db_manager=get_db_manager())
        logger.info("ModelFactory инициализирован (Singleton)")
    return _model_factory


def get_trading_system():
    """
    Получение торговой системы (Singleton).

    Returns:
        TradingSystem
    """
    global _trading_system
    if _trading_system is None:
        from src.core.trading_system import TradingSystem

        _trading_system = TradingSystem(
            config=get_config(),
            db_manager=get_db_manager(),
            vector_db_manager=get_vector_db_manager(),
            data_provider=get_data_provider(),
            risk_engine=get_risk_engine(_trading_system),
            model_factory=get_model_factory(),
        )
        logger.info("TradingSystem инициализирован (Singleton)")
    return _trading_system


def get_query_manager():
    """
    Получение Query Manager (CQRS - чтение).

    Returns:
        QueryManager
    """
    from sqlalchemy.orm import sessionmaker

    from src.db.query_manager import QueryManager

    db_manager = get_db_manager()
    return QueryManager(db_manager.Session)


def get_command_manager():
    """
    Получение Command Manager (CQRS - запись).

    Returns:
        CommandManager
    """
    from sqlalchemy.orm import sessionmaker

    from src.db.command_manager import CommandManager

    db_manager = get_db_manager()
    return CommandManager(db_manager.Session)


def get_event_bus():
    """
    Получение Event Bus (Singleton).

    Returns:
        EventBus
    """
    from src.core.event_bus import event_bus

    return event_bus


def reset_all() -> None:
    """
    Сброс всех компонентов (для тестов).
    """
    global _config, _db_manager, _vector_db_manager, _data_provider
    global _risk_engine, _model_factory, _trading_system

    _config = None
    _db_manager = None
    _vector_db_manager = None
    _data_provider = None
    _risk_engine = None
    _model_factory = None
    _trading_system = None

    logger.info("Все компоненты сброшены")


# ===========================================
# Container Class (для совместимости)
# ===========================================


class Container:
    """
    DI контейнер (упрощенная версия).

    Предоставляет доступ к компонентам через методы.
    """

    def __init__(self):
        self._config = None
        self._db_manager = None
        self._vector_db_manager = None
        self._data_provider = None
        self._risk_engine = None
        self._model_factory = None
        self._trading_system = None

    @property
    def config(self):
        if self._config is None:
            self._config = get_config()
        return self._config

    @property
    def db_manager(self):
        if self._db_manager is None:
            self._db_manager = get_db_manager()
        return lambda: self._db_manager

    @property
    def vector_db_manager(self):
        if self._vector_db_manager is None:
            self._vector_db_manager = get_vector_db_manager()
        return lambda: self._vector_db_manager

    @property
    def data_provider(self):
        if self._data_provider is None:
            self._data_provider = get_data_provider()
        return lambda: self._data_provider

    @property
    def risk_engine(self):
        return lambda: get_risk_engine(self._trading_system)

    @property
    def model_factory(self):
        if self._model_factory is None:
            self._model_factory = get_model_factory()
        return lambda: self._model_factory

    @property
    def trading_system(self):
        if self._trading_system is None:
            self._trading_system = get_trading_system()
        return lambda: self._trading_system

    @property
    def query_manager(self):
        return lambda: get_query_manager()

    @property
    def command_manager(self):
        return lambda: get_command_manager()

    @property
    def event_bus(self):
        return lambda: get_event_bus()
