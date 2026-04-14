"""
Многоуровневый кэш с TTL, LRU-эвикцией и событийной инвалидацией.
Уровни: L1 (in-memory dict) → L2 (SQLite)
"""

import asyncio
import hashlib
import logging
import pickle
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.core.event_bus import SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    value: Any
    created_at: float
    ttl_sec: Optional[float] = None

    def is_expired(self) -> bool:
        if self.ttl_sec is None:
            return False
        return time.time() - self.created_at > self.ttl_sec


class LRUCache:
    """In-memory LRU кэш с ограничением по размеру"""

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Optional[CacheEntry]:
        if key not in self._cache:
            return None
        entry = self._cache.pop(key)
        if entry.is_expired():
            return None
        self._cache[key] = entry
        return entry

    def set(self, key: str, entry: CacheEntry):
        if key in self._cache:
            self._cache.pop(key)
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        self._cache[key] = entry

    def invalidate(self, key: str):
        self._cache.pop(key, None)

    def clear(self):
        self._cache.clear()


class CacheManager:
    """Многоуровневый менеджер кэша"""

    def __init__(self, config: Dict, db_path: Optional[str] = None):
        self.config = config
        self.event_bus = get_event_bus()

        # L1: In-memory LRU
        self._l1 = LRUCache(max_size=config.get("l1_max_size", 1000))

        # L2: SQLite (опционально)
        self._db_path = db_path or config.get("cache_db_path")
        self._db_conn: Optional[sqlite3.Connection] = None
        if self._db_path:
            self._init_db()

        # Статистика
        self._stats = {
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "writes": 0,
            "invalidations": 0,
        }

    def _init_db(self):
        """Инициализация SQLite для L2 кэша"""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_conn = sqlite3.connect(
            self._db_path, check_same_thread=False
        )
        self._db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value BLOB,
                created_at REAL,
                ttl_sec REAL,
                accessed_at REAL
            )
        """
        )
        self._db_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_accessed ON cache(accessed_at)"
        )
        self._db_conn.commit()

    def _hash_key(self, prefix: str, args: tuple, kwargs: dict) -> str:
        """Генерация уникального ключа кэша"""
        key_data = f"{prefix}:{args}:{sorted(kwargs.items())}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    def cached(
        self,
        prefix: str,
        ttl_sec: Optional[float] = 3600,
        key_func: Optional[Callable] = None,
        invalidate_on: Optional[str] = None,
    ):
        """Декоратор для кэширования результатов функций"""

        def decorator(func: Callable) -> Callable:

            import functools

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                key = (
                    key_func(prefix, args, kwargs)
                    if key_func
                    else self._hash_key(prefix, args, kwargs)
                )

                # L1 lookup
                entry = self._l1.get(key)
                if entry:
                    self._stats["l1_hits"] += 1
                    return entry.value

                # L2 lookup
                if self._db_conn:
                    async with lock_manager.acquire(
                        LockLevel.CACHE, timeout=1.0
                    ):
                        row = self._db_conn.execute(
                            "SELECT value, created_at, ttl_sec FROM cache WHERE key = ?",
                            (key,),
                        ).fetchone()
                        if row:
                            value, created_at, ttl = row
                            entry = CacheEntry(
                                pickle.loads(value), created_at, ttl
                            )
                            if not entry.is_expired():
                                self._stats["l2_hits"] += 1
                                self._l1.set(key, entry)
                                return entry.value
                            else:
                                self._db_conn.execute(
                                    "DELETE FROM cache WHERE key = ?", (key,)
                                )
                                self._db_conn.commit()
                    self._stats["l2_misses"] += 1

                self._stats["l1_misses"] += 1

                # Cache miss: execute function
                result = await func(*args, **kwargs)
                entry = CacheEntry(result, time.time(), ttl_sec)

                # Write to L1
                self._l1.set(key, entry)

                # Write to L2 (async, non-blocking)
                if self._db_conn:
                    asyncio.create_task(self._write_l2_async(key, entry))

                self._stats["writes"] += 1
                return result

            return async_wrapper

        return decorator

    async def _write_l2_async(self, key: str, entry: CacheEntry):
        """Асинхронная запись в L2 кэш"""
        try:
            async with lock_manager.acquire(LockLevel.CACHE, timeout=2.0):
                self._db_conn.execute(
                    "INSERT OR REPLACE INTO cache "
                    "(key, value, created_at, ttl_sec, accessed_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        key,
                        pickle.dumps(entry.value),
                        entry.created_at,
                        entry.ttl_sec,
                        time.time(),
                    ),
                )
                self._db_conn.commit()
        except Exception as e:
            logger.warning(f"L2 cache write failed: {e}")

    def invalidate(self, prefix: Optional[str] = None, key: Optional[str] = None):
        """Инвалидация кэша"""
        if key:
            self._l1.invalidate(key)
            if self._db_conn:
                self._db_conn.execute(
                    "DELETE FROM cache WHERE key = ?", (key,)
                )
                self._db_conn.commit()
        elif prefix:
            keys_to_remove = [
                k for k in self._l1._cache.keys() if k.startswith(prefix)
            ]
            for k in keys_to_remove:
                self._l1.invalidate(k)
            self._stats["invalidations"] += len(keys_to_remove)

        # Publish invalidation event for cross-process sync
        asyncio.create_task(
            self.event_bus.publish(
                SystemEvent(
                    type="cache_invalidated",
                    payload={"prefix": prefix, "key": key},
                )
            )
        )

    def get_stats(self) -> Dict:
        """Статистика кэша"""
        total_reads = self._stats["l1_hits"] + self._stats["l1_misses"]
        hit_rate = self._stats["l1_hits"] / max(1, total_reads) * 100
        return {
            **self._stats,
            "l1_hit_rate_percent": round(hit_rate, 2),
            "l1_size": len(self._l1._cache),
        }

    def clear_all(self):
        """Полная очистка кэша"""
        self._l1.clear()
        if self._db_conn:
            self._db_conn.execute("DELETE FROM cache")
            self._db_conn.commit()
        self._stats = {k: 0 for k in self._stats}
        logger.info("Cache cleared")


# Глобальный экземпляр
cache_manager = CacheManager({})
