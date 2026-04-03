# src/db/adapters/__init__.py
"""
Адаптеры для внешних баз данных.
Поддержка: QuestDB, TimescaleDB, Qdrant, Redis
"""

from .qdrant_adapter import QdrantAdapter
from .questdb_adapter import QuestDBAdapter
from .redis_adapter import RedisAdapter
from .timescaledb_adapter import TimescaleDBAdapter

__all__ = [
    "QuestDBAdapter",
    "TimescaleDBAdapter",
    "QdrantAdapter",
    "RedisAdapter",
]
