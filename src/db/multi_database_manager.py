# src/db/multi_database_manager.py
"""
Multi-Database Manager для Genesis Trading System.
Централизованное управление подключениями к различным базам данных:
- PostgreSQL (реляционные данные: позиции, аудит, конфигурация)
- TimescaleDB/QuestDB (временные ряды: свечи, тики)
- Qdrant (векторный поиск: RAG, семантический поиск)
- Redis (кэш, pub/sub)
- Neo4j (граф знаний)
- SQLite (локальное хранилище, обратная совместимость)
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .adapters.qdrant_adapter import QdrantAdapter
from .adapters.questdb_adapter import QuestDBAdapter
from .adapters.redis_adapter import RedisAdapter
from .adapters.timescaledb_adapter import TimescaleDBAdapter

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Конфигурация подключений к базам данных."""

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "trading"
    postgres_user: str = "trading_user"
    postgres_password: str = "secure_password"

    # TimescaleDB
    timescaledb_host: str = "localhost"
    timescaledb_port: int = 5433
    timescaledb_db: str = "trading_ts"
    timescaledb_user: str = "trading_user"
    timescaledb_password: str = "secure_password"

    # QuestDB
    questdb_host: str = "localhost"
    questdb_port: int = 9000
    questdb_user: str = "admin"
    questdb_password: str = "quest"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_collection: str = "trading_rag"
    qdrant_vector_size: int = 384
    qdrant_path: Optional[str] = None  # Для локального режима

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # SQLite (для обратной совместимости)
    sqlite_path: str = "database/trading_system.db"

    # Флаги включения/выключения
    enable_postgres: bool = False  # Отключено по умолчанию (требует Docker)
    enable_timescaledb: bool = False  # Отключено по умолчанию (требует Docker)
    enable_questdb: bool = False  # Альтернатива TimescaleDB
    enable_qdrant: bool = True  # Включено (Qdrant сервер доступен)
    enable_redis: bool = False  # Отключено по умолчанию (требует установку)
    enable_neo4j: bool = False  # Отключено по умолчанию (требует установку)
    enable_sqlite: bool = True  # Основной режим


class MultiDatabaseManager:
    """
    Централизованный менеджер для работы с несколькими базами данных.
    Предоставляет единый интерфейс для доступа к различным БД.
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._adapters: Dict[str, Any] = {}
        self._initialized = False

        logger.info("MultiDatabaseManager инициализация...")
        self._initialize_adapters()

    def _initialize_adapters(self):
        """Инициализация всех адаптеров баз данных."""

        # ========== PostgreSQL ==========
        if self.config.enable_postgres:
            try:
                from sqlalchemy import create_engine, text
                from sqlalchemy.orm import sessionmaker

                connection_url = (
                    f"postgresql://{self.config.postgres_user}:"
                    f"{self.config.postgres_password}@{self.config.postgres_host}:"
                    f"{self.config.postgres_port}/{self.config.postgres_db}"
                )

                engine = create_engine(
                    connection_url,
                    pool_size=20,
                    max_overflow=40,
                    pool_pre_ping=True,
                    echo=False,
                )

                # Проверка подключения
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))

                self._adapters["postgres"] = {
                    "engine": engine,
                    "session_factory": sessionmaker(bind=engine),
                }
                logger.info(f"✓ PostgreSQL подключен: {self.config.postgres_host}:{self.config.postgres_port}")

            except Exception as e:
                logger.error(f"✗ PostgreSQL ошибка подключения: {e}")
                if self.config.enable_sqlite:
                    logger.warning("→ Будет использован SQLite как резервный вариант")

        # ========== TimescaleDB ==========
        if self.config.enable_timescaledb:
            try:
                ts_adapter = TimescaleDBAdapter(
                    host=self.config.timescaledb_host,
                    port=self.config.timescaledb_port,
                    database=self.config.timescaledb_db,
                    user=self.config.timescaledb_user,
                    password=self.config.timescaledb_password,
                    enabled=True,
                )

                if ts_adapter.enabled:
                    self._adapters["timescaledb"] = ts_adapter
                    logger.info(f"✓ TimescaleDB подключен: {self.config.timescaledb_host}:{self.config.timescaledb_port}")
                else:
                    logger.warning("TimescaleDB не доступен")

            except Exception as e:
                logger.error(f"TimescaleDB ошибка инициализации: {e}")

        # ========== QuestDB ==========
        if self.config.enable_questdb and not self.config.enable_timescaledb:
            try:
                questdb_adapter = QuestDBAdapter(
                    host=self.config.questdb_host,
                    port=self.config.questdb_port,
                    database="questdb",
                    user=self.config.questdb_user,
                    password=self.config.questdb_password,
                    enabled=True,
                )

                if questdb_adapter.enabled:
                    self._adapters["questdb"] = questdb_adapter
                    logger.info(f"✓ QuestDB подключен: {self.config.questdb_host}:{self.config.questdb_port}")
                else:
                    logger.warning("QuestDB не доступен")

            except Exception as e:
                logger.error(f"QuestDB ошибка инициализации: {e}")

        # ========== Qdrant ==========
        if self.config.enable_qdrant:
            try:
                qdrant_adapter = QdrantAdapter(
                    host=self.config.qdrant_host,
                    port=self.config.qdrant_port,
                    grpc_port=self.config.qdrant_grpc_port,
                    collection_name=self.config.qdrant_collection,
                    vector_size=self.config.qdrant_vector_size,
                    db_path=self.config.qdrant_path,
                    enabled=True,
                )

                if qdrant_adapter.enabled:
                    # Создаем коллекцию если не существует
                    qdrant_adapter.create_collection()
                    self._adapters["qdrant"] = qdrant_adapter
                    logger.info(f"✓ Qdrant подключен: {self.config.qdrant_host}:{self.config.qdrant_port}")
                else:
                    logger.warning("Qdrant не доступен, будет использован локальный FAISS")

            except Exception as e:
                logger.error(f"Qdrant ошибка инициализации: {e}")

        # ========== Redis ==========
        if self.config.enable_redis:
            try:
                redis_adapter = RedisAdapter(
                    host=self.config.redis_host,
                    port=self.config.redis_port,
                    db=self.config.redis_db,
                    password=self.config.redis_password,
                    enabled=True,
                )

                if redis_adapter.enabled and redis_adapter.ping():
                    self._adapters["redis"] = redis_adapter
                    logger.info(f"✓ Redis подключен: {self.config.redis_host}:{self.config.redis_port}")
                else:
                    logger.warning("Redis не доступен")

            except Exception as e:
                logger.error(f"Redis ошибка инициализации: {e}")

        # ========== Neo4j ==========
        if self.config.enable_neo4j:
            try:
                from neo4j import GraphDatabase

                driver = GraphDatabase.driver(
                    self.config.neo4j_uri,
                    auth=(self.config.neo4j_user, self.config.neo4j_password),
                    max_connection_pool_size=50,
                )

                # Проверка подключения
                driver.verify_connectivity()

                self._adapters["neo4j"] = driver
                logger.info(f"✓ Neo4j подключен: {self.config.neo4j_uri}")

            except Exception as e:
                logger.error(f"Neo4j ошибка подключения: {e}")

        self._initialized = True
        logger.info(f"MultiDatabaseManager инициализирован. Активных адаптеров: {len(self._adapters)}")

    # ========== PUBLIC INTERFACE ==========

    def get_postgres_session(self):
        """Получение сессии PostgreSQL."""
        if "postgres" not in self._adapters:
            raise RuntimeError("PostgreSQL не подключен")
        return self._adapters["postgres"]["session_factory"]()

    def get_postgres_engine(self):
        """Получение SQLAlchemy engine для PostgreSQL."""
        if "postgres" not in self._adapters:
            raise RuntimeError("PostgreSQL не подключен")
        return self._adapters["postgres"]["engine"]

    def get_timescaledb(self) -> TimescaleDBAdapter:
        """Получение адаптера TimescaleDB."""
        if "timescaledb" not in self._adapters:
            raise RuntimeError("TimescaleDB не подключен")
        return self._adapters["timescaledb"]

    def get_questdb(self) -> QuestDBAdapter:
        """Получение адаптера QuestDB."""
        if "questdb" not in self._adapters:
            raise RuntimeError("QuestDB не подключен")
        return self._adapters["questdb"]

    def get_qdrant(self) -> QdrantAdapter:
        """Получение адаптера Qdrant."""
        if "qdrant" not in self._adapters:
            raise RuntimeError("Qdrant не подключен")
        return self._adapters["qdrant"]

    def get_redis(self) -> RedisAdapter:
        """Получение адаптера Redis."""
        if "redis" not in self._adapters:
            raise RuntimeError("Redis не подключен")
        return self._adapters["redis"]

    def get_neo4j_driver(self):
        """Получение драйвера Neo4j."""
        if "neo4j" not in self._adapters:
            raise RuntimeError("Neo4j не подключен")
        return self._adapters["neo4j"]

    def get_time_series_adapter(self):
        """
        Получение адаптера для временных рядов.
        Приоритет: QuestDB → TimescaleDB → PostgreSQL
        """
        if "questdb" in self._adapters:
            return self._adapters["questdb"]
        elif "timescaledb" in self._adapters:
            return self._adapters["timescaledb"]
        elif "postgres" in self._adapters:
            return self._adapters["postgres"]
        else:
            raise RuntimeError("Ни один адаптер временных рядов не подключен")

    def get_vector_adapter(self):
        """
        Получение векторного адаптера.
        Приоритет: Qdrant → FAISS (локальный)
        """
        if "qdrant" in self._adapters:
            return self._adapters["qdrant"]
        else:
            # Возвращаем None, будет использован локальный FAISS
            logger.warning("Векторный адаптер не подключен, используется локальный FAISS")
            return None

    def is_available(self, db_name: str) -> bool:
        """Проверка доступности базы данных."""
        return db_name in self._adapters

    def get_status(self) -> Dict[str, bool]:
        """Получение статуса всех подключений."""
        return {
            "postgres": "postgres" in self._adapters,
            "timescaledb": "timescaledb" in self._adapters,
            "questdb": "questdb" in self._adapters,
            "qdrant": "qdrant" in self._adapters,
            "redis": "redis" in self._adapters,
            "neo4j": "neo4j" in self._adapters,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики по всем подключениям."""
        stats = {}

        if "postgres" in self._adapters:
            stats["postgres"] = "connected"

        if "timescaledb" in self._adapters:
            try:
                stats["timescaledb"] = self._adapters["timescaledb"].get_table_stats("candle_data")
            except:
                stats["timescaledb"] = "connected"

        if "qdrant" in self._adapters:
            try:
                stats["qdrant"] = self._adapters["qdrant"].get_collection_stats()
            except:
                stats["qdrant"] = "connected"

        if "redis" in self._adapters:
            try:
                stats["redis"] = self._adapters["redis"].get_stats()
            except:
                stats["redis"] = "connected"

        if "neo4j" in self._adapters:
            stats["neo4j"] = "connected"

        return stats

    def close_all(self):
        """Закрытие всех подключений."""
        logger.info("Закрытие всех подключений к базам данных...")

        for name, adapter in self._adapters.items():
            try:
                if name == "postgres":
                    adapter["engine"].dispose()
                elif name == "neo4j":
                    adapter.close()
                elif hasattr(adapter, "close"):
                    adapter.close()
                logger.info(f"✓ {name} закрыт")
            except Exception as e:
                logger.error(f"✗ {name} ошибка закрытия: {e}")

        self._adapters.clear()
        self._initialized = False
        logger.info("Все подключения закрыты")

    @classmethod
    def from_env(cls) -> "MultiDatabaseManager":
        """
        Создание менеджера из переменных окружения.
        Удобно для Docker/production развертывания.
        """
        config = DatabaseConfig(
            # PostgreSQL
            postgres_host=os.getenv("POSTGRES_HOST", "db"),
            postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
            postgres_db=os.getenv("POSTGRES_DB", "trading"),
            postgres_user=os.getenv("POSTGRES_USER", "trading_user"),
            postgres_password=os.getenv("POSTGRES_PASSWORD", "secure_password"),
            # TimescaleDB
            timescaledb_host=os.getenv("TIMESCALEDB_HOST", "timescaledb"),
            timescaledb_port=int(os.getenv("TIMESCALEDB_PORT", "5432")),
            timescaledb_db=os.getenv("TIMESCALEDB_DB", "trading_ts"),
            timescaledb_user=os.getenv("TIMESCALEDB_USER", "trading_user"),
            timescaledb_password=os.getenv("TIMESCALEDB_PASSWORD", "secure_password"),
            # QuestDB
            questdb_host=os.getenv("QUESTDB_HOST", "questdb"),
            questdb_port=int(os.getenv("QUESTDB_PORT", "9000")),
            # Qdrant
            qdrant_host=os.getenv("QDRANT_HOST", "qdrant"),
            qdrant_port=int(os.getenv("QDRANT_PORT", "6333")),
            # Redis
            redis_host=os.getenv("REDIS_HOST", "redis"),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            # Neo4j
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        )

        return cls(config)
