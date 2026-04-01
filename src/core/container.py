# src/core/container.py
"""
Dependency Injection контейнер для Genesis Trading System.

Упрощенная версия для Фазы 2. Предоставляет централизованный доступ к компонентам.

Пример использования:
    from src.core.container import Container

    container = Container()
    db_manager = container.db_manager()
    risk_engine = container.risk_engine()
"""

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Импорты компонентов
from src.core.config_loader import load_config
from src.core.config_models import Settings


class Container:
    """
    DI контейнер с потокобезопасным управлением состоянием.

    Предоставляет доступ к компонентам через методы с ленивой инициализацией.
    Все компоненты инициализируются только один раз (Singleton pattern).

    Attributes:
        _instance: Единственный экземпляр контейнера
        _lock: Блокировка для потокобезопасной инициализации
        _components: Словарь компонентов
        _initialized: Флаг инициализации
    """

    _instance: Optional["Container"] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __init__(self):
        """Инициализация контейнера."""
        if Container._initialized:
            return

        self._components: Dict[str, Any] = {}
        self._config: Optional[Settings] = None
        Container._initialized = True
        logger.info("Container инициализирован")

    @classmethod
    def get_instance(cls) -> "Container":
        """
        Получение единственного экземпляра контейнера (Singleton).

        Returns:
            Экземпляр Container
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # Double-checked locking
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """
        Сброс единственного экземпляра (для тестов).
        """
        with cls._lock:
            if cls._instance:
                cls._instance._components.clear()
                cls._instance._config = None
            cls._instance = None
            cls._initialized = False
        logger.info("Container сброшен")

    def _get_or_create(self, key: str, factory) -> Any:
        """
        Получение или создание компонента.

        Args:
            key: Ключ компонента
            factory: Фабрика для создания компонента

        Returns:
            Компонент
        """
        if key not in self._components:
            with self._lock:
                if key not in self._components:  # Double-checked locking
                    self._components[key] = factory()
                    logger.info(f"{key} инициализирован")
        return self._components[key]

    @property
    def config(self) -> Settings:
        """
        Получение конфигурации (Singleton).

        Returns:
            Конфигурация системы
        """
        if self._config is None:
            self._config = load_config()
            logger.info("Конфигурация загружена")
        return self._config

    @property
    def db_manager(self):
        """
        Получение менеджера БД.

        Returns:
            DatabaseManager
        """

        def _get():
            from src.db.database_manager import DatabaseManager

            return self._get_or_create("db_manager", lambda: DatabaseManager(self.config))

        return _get

    @property
    def vector_db_manager(self):
        """
        Получение менеджера векторной БД.

        Returns:
            VectorDBManager
        """

        def _get():
            from src.db.vector_db_manager import VectorDBManager

            cfg = self.config
            return self._get_or_create(
                "vector_db_manager",
                lambda: VectorDBManager(path=cfg.vector_db.path, embedding_model=cfg.vector_db.embedding_model),
            )

        return _get

    @property
    def data_provider(self):
        """
        Получение провайдера данных.

        Returns:
            DataProvider
        """

        def _get():
            from src.data.data_provider import DataProvider

            return self._get_or_create("data_provider", lambda: DataProvider(config=self.config, db_manager=self.db_manager()))

        return _get

    @property
    def risk_engine(self):
        """
        Получение риск-движка.

        Returns:
            RiskEngine
        """

        def _get(trading_system_ref=None):
            from src.kg.knowledge_graph import KnowledgeGraphQuerier
            from src.risk.risk_engine import RiskEngine

            kg_querier = KnowledgeGraphQuerier()
            return RiskEngine(config=self.config, trading_system_ref=trading_system_ref, querier=kg_querier)

        return _get

    @property
    def model_factory(self):
        """
        Получение фабрики моделей.

        Returns:
            ModelFactory
        """

        def _get():
            from src.ml.model_factory import ModelFactory

            return self._get_or_create("model_factory", lambda: ModelFactory(config=self.config, db_manager=self.db_manager()))

        return _get

    @property
    def trading_system(self):
        """
        Получение торговой системы.

        Returns:
            TradingSystem
        """

        def _get():
            from src.core.trading_system import TradingSystem

            return self._get_or_create(
                "trading_system",
                lambda: TradingSystem(
                    config=self.config,
                    db_manager=self.db_manager(),
                    vector_db_manager=self.vector_db_manager(),
                    data_provider=self.data_provider(),
                    risk_engine=self.risk_engine(),
                    model_factory=self.model_factory(),
                ),
            )

        return _get

    @property
    def query_manager(self):
        """
        Получение Query Manager (CQRS - чтение).

        Returns:
            QueryManager
        """
        from sqlalchemy.orm import sessionmaker

        from src.db.query_manager import QueryManager

        def _get():
            db_manager = self.db_manager()
            return QueryManager(db_manager.Session)

        return _get

    @property
    def command_manager(self):
        """
        Получение Command Manager (CQRS - запись).

        Returns:
            CommandManager
        """
        from sqlalchemy.orm import sessionmaker

        from src.db.command_manager import CommandManager

        def _get():
            db_manager = self.db_manager()
            return CommandManager(db_manager.Session)

        return _get

    @property
    def event_bus(self):
        """
        Получение Event Bus.

        Returns:
            EventBus
        """
        from src.core.event_bus import event_bus

        return lambda: event_bus


# ===========================================
# Функции для обратной совместимости
# ===========================================

_container_instance: Optional[Container] = None


def _get_container() -> Container:
    """Получение контейнера (для обратной совместимости)."""
    return Container.get_instance()


def get_config() -> Settings:
    """Получение конфигурации (для обратной совместимости)."""
    return _get_container().config


def get_db_manager():
    """Получение менеджера БД (для обратной совместимости)."""
    return _get_container().db_manager()


def get_vector_db_manager():
    """Получение менеджера векторной БД (для обратной совместимости)."""
    return _get_container().vector_db_manager()


def get_data_provider():
    """Получение провайдера данных (для обратной совместимости)."""
    return _get_container().data_provider()


def get_risk_engine(trading_system_ref=None):
    """Получение риск-движка (для обратной совместимости)."""
    return _get_container().risk_engine(trading_system_ref)


def get_model_factory():
    """Получение фабрики моделей (для обратной совместимости)."""
    return _get_container().model_factory()


def get_trading_system():
    """Получение торговой системы (для обратной совместимости)."""
    return _get_container().trading_system()


def get_query_manager():
    """Получение Query Manager (для обратной совместимости)."""
    return _get_container().query_manager()


def get_command_manager():
    """Получение Command Manager (для обратной совместимости)."""
    return _get_container().command_manager()


def get_event_bus():
    """Получение Event Bus (для обратной совместимости)."""
    return _get_container().event_bus()


def reset_all() -> None:
    """Сброс всех компонентов (для тестов, для обратной совместимости)."""
    Container.reset_instance()
    logger.info("Все компоненты сброшены")
