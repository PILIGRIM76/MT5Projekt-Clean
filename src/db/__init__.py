"""
База данных модуль Genesis Trading System.

Поддерживаемые базы данных:
- PostgreSQL: Реляционные данные (позиции, аудит, конфигурация)
- TimescaleDB/QuestDB: Временные ряды (свечи, тики)
- Qdrant: Векторный поиск (RAG, семантический поиск)
- Redis: Кэш и pub/sub
- Neo4j: Граф знаний
- SQLite: Локальное хранилище (резервный режим)

Пример использования:
    from src.db.multi_database_manager import MultiDatabaseManager, DatabaseConfig

    config = DatabaseConfig(
        postgres_host="localhost",
        postgres_port=5432,
        # ... другие параметры
    )

    db_manager = MultiDatabaseManager(config)

    # Получение адаптеров
    postgres_session = db_manager.get_postgres_session()
    timescaledb = db_manager.get_timescaledb()
    qdrant = db_manager.get_qdrant()
    redis = db_manager.get_redis()
"""

from .adapters import (
    QdrantAdapter,
    QuestDBAdapter,
    RedisAdapter,
    TimescaleDBAdapter,
)
from .multi_database_manager import DatabaseConfig, MultiDatabaseManager

__all__ = [
    "QuestDBAdapter",
    "TimescaleDBAdapter",
    "QdrantAdapter",
    "RedisAdapter",
    "DatabaseConfig",
    "MultiDatabaseManager",
]
