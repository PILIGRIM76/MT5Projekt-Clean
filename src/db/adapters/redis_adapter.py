# src/db/adapters/redis_adapter.py
"""
Адаптер для Redis 7 - in-memory хранилище для кэширования и pub/sub.
Используется для кэширования рыночных данных, сессий и событий.
Производительность: <1 мс задержка, 100k+ операций/сек.
"""

import json
import logging
import pickle
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import numpy as np

from src.db.database_manager import safe_pickle_loads

logger = logging.getLogger(__name__)

try:
    import redis
    from redis import asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis не установлен. Redis адаптер отключен.")


class RedisAdapter:
    """
    Адаптер для Redis кэширования и pub/sub.
    Поддерживает строковые, JSON и бинарные данные.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        decode_responses: bool = False,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
        enabled: bool = True,
    ):
        self.enabled = enabled and REDIS_AVAILABLE
        self.host = host
        self.port = port
        self.db = db
        self.password = password

        self._client: Optional[redis.Redis] = None
        self._pubsub = None

        if self.enabled:
            try:
                self._init_client(
                    socket_timeout=socket_timeout,
                    socket_connect_timeout=socket_connect_timeout,
                    decode_responses=decode_responses,
                )
                logger.info(f"RedisAdapter инициализирован: {host}:{port}")
            except Exception as e:
                logger.error(f"Ошибка подключения к Redis: {e}")
                self.enabled = False

    def _init_client(self, **kwargs):
        """Инициализация Redis клиента."""
        self._client = redis.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password,
            **kwargs,
        )

        # Проверка подключения
        self._client.ping()
        logger.info("Redis подключение проверено (PING)")

    # ========== BASIC OPERATIONS ==========

    def get(self, key: str) -> Optional[Any]:
        """Получение значения по ключу."""
        if not self.enabled:
            return None
        try:
            return self._client.get(key)
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            return None

    def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
    ) -> bool:
        """
        Установка значения по ключу.
        ex: TTL в секундах
        px: TTL в миллисекундах
        """
        if not self.enabled:
            return False
        try:
            return self._client.set(key, value, ex=ex, px=px)
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
            return False

    def delete(self, *keys: str) -> int:
        """Удаление ключей."""
        if not self.enabled:
            return 0
        try:
            return self._client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis DELETE error: {e}")
            return 0

    def exists(self, *keys: str) -> bool:
        """Проверка существования ключей."""
        if not self.enabled:
            return False
        try:
            return self._client.exists(*keys) > 0
        except Exception as e:
            logger.error(f"Redis EXISTS error: {e}")
            return False

    def expire(self, key: str, seconds: int) -> bool:
        """Установка TTL для ключа."""
        if not self.enabled:
            return False
        try:
            return self._client.expire(key, seconds)
        except Exception as e:
            logger.error(f"Redis EXPIRE error: {e}")
            return False

    # ========== JSON OPERATIONS ==========

    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Получение JSON объекта."""
        data = self.get(key)
        if data is None:
            return None
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            return json.loads(data)
        except Exception as e:
            logger.error(f"Redis GET_JSON error: {e}")
            return None

    def set_json(
        self,
        key: str,
        data: Dict[str, Any],
        ex: Optional[int] = None,
    ) -> bool:
        """Установка JSON объекта."""
        if not self.enabled:
            return False
        try:
            json_str = json.dumps(data, ensure_ascii=False)
            return self.set(key, json_str, ex=ex)
        except Exception as e:
            logger.error(f"Redis SET_JSON error: {e}")
            return False

    # ========== PICKLE OPERATIONS ==========

    def get_pickle(self, key: str) -> Optional[Any]:
        """Получение сериализованного pickle объекта (безопасно)."""
        data = self.get(key)
        if data is None:
            return None
        try:
            return safe_pickle_loads(data)
        except Exception as e:
            logger.error(f"Redis GET_PICKLE error: {e}")
            return None

    def set_pickle(
        self,
        key: str,
        obj: Any,
        ex: Optional[int] = None,
    ) -> bool:
        """Установка сериализованного pickle объекта."""
        if not self.enabled:
            return False
        try:
            pickled = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
            return self.set(key, pickled, ex=ex)
        except Exception as e:
            logger.error(f"Redis SET_PICKLE error: {e}")
            return False

    # ========== NUMPY OPERATIONS ==========

    def get_numpy(self, key: str) -> Optional[np.ndarray]:
        """Получение numpy массива."""
        data = self.get_pickle(key)
        if data is None:
            return None
        try:
            return np.array(data)
        except Exception as e:
            logger.error(f"Redis GET_NUMPY error: {e}")
            return None

    def set_numpy(
        self,
        key: str,
        array: np.ndarray,
        ex: Optional[int] = None,
    ) -> bool:
        """Установка numpy массива."""
        if not self.enabled:
            return False
        try:
            return self.set_pickle(key, array.tolist(), ex=ex)
        except Exception as e:
            logger.error(f"Redis SET_NUMPY error: {e}")
            return False

    # ========== HASH OPERATIONS ==========

    def hget(self, name: str, key: str) -> Optional[Any]:
        """Получение значения из hash."""
        if not self.enabled:
            return None
        try:
            return self._client.hget(name, key)
        except Exception as e:
            logger.error(f"Redis HGET error: {e}")
            return None

    def hgetall(self, name: str) -> Dict[str, Any]:
        """Получение всех полей hash."""
        if not self.enabled:
            return {}
        try:
            return self._client.hgetall(name)
        except Exception as e:
            logger.error(f"Redis HGETALL error: {e}")
            return {}

    def hset(
        self,
        name: str,
        key: Optional[str] = None,
        value: Optional[Any] = None,
        mapping: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Установка значения в hash."""
        if not self.enabled:
            return 0
        try:
            return self._client.hset(name, key=key, value=value, mapping=mapping)
        except Exception as e:
            logger.error(f"Redis HSET error: {e}")
            return 0

    def hdel(self, name: str, *keys: str) -> int:
        """Удаление полей из hash."""
        if not self.enabled:
            return 0
        try:
            return self._client.hdel(name, *keys)
        except Exception as e:
            logger.error(f"Redis HDEL error: {e}")
            return 0

    # ========== LIST OPERATIONS ==========

    def lpush(self, name: str, *values: Any) -> int:
        """Добавление элементов в начало списка."""
        if not self.enabled:
            return 0
        try:
            return self._client.lpush(name, *values)
        except Exception as e:
            logger.error(f"Redis LPUSH error: {e}")
            return 0

    def rpush(self, name: str, *values: Any) -> int:
        """Добавление элементов в конец списка."""
        if not self.enabled:
            return 0
        try:
            return self._client.rpush(name, *values)
        except Exception as e:
            logger.error(f"Redis RPUSH error: {e}")
            return 0

    def lrange(
        self,
        name: str,
        start: int = 0,
        end: int = -1,
    ) -> List[Any]:
        """Получение элементов списка по диапазону."""
        if not self.enabled:
            return []
        try:
            return self._client.lrange(name, start, end)
        except Exception as e:
            logger.error(f"Redis LRANGE error: {e}")
            return []

    def llen(self, name: str) -> int:
        """Получение длины списка."""
        if not self.enabled:
            return 0
        try:
            return self._client.llen(name)
        except Exception as e:
            logger.error(f"Redis LLEN error: {e}")
            return 0

    def ltrim(self, name: str, start: int = 0, end: int = -1) -> bool:
        """Обрезка списка."""
        if not self.enabled:
            return False
        try:
            return self._client.ltrim(name, start, end)
        except Exception as e:
            logger.error(f"Redis LTRIM error: {e}")
            return False

    # ========== SET OPERATIONS ==========

    def sadd(self, name: str, *values: Any) -> int:
        """Добавление элементов в множество."""
        if not self.enabled:
            return 0
        try:
            return self._client.sadd(name, *values)
        except Exception as e:
            logger.error(f"Redis SADD error: {e}")
            return 0

    def smembers(self, name: str) -> Set[Any]:
        """Получение всех элементов множества."""
        if not self.enabled:
            return set()
        try:
            return self._client.smembers(name)
        except Exception as e:
            logger.error(f"Redis SMEMBERS error: {e}")
            return set()

    def sismember(self, name: str, value: Any) -> bool:
        """Проверка принадлежности элемента к множеству."""
        if not self.enabled:
            return False
        try:
            return self._client.sismember(name, value)
        except Exception as e:
            logger.error(f"Redis SISMEMBER error: {e}")
            return False

    # ========== CACHE OPERATIONS ==========

    def cache_market_data(
        self,
        symbol: str,
        timeframe: int,
        data: Dict[str, Any],
        ttl_seconds: int = 60,
    ) -> bool:
        """
        Кэширование рыночных данных.
        TTL по умолчанию 60 секунд (для актуальных данных).
        """
        key = f"market:{symbol}:{timeframe}:latest"
        return self.set_json(key, data, ex=ttl_seconds)

    def get_market_data(
        self,
        symbol: str,
        timeframe: int,
    ) -> Optional[Dict[str, Any]]:
        """Получение закэшированных рыночных данных."""
        key = f"market:{symbol}:{timeframe}:latest"
        return self.get_json(key)

    def cache_signal(
        self,
        symbol: str,
        signal_data: Dict[str, Any],
        ttl_seconds: int = 300,
    ) -> bool:
        """Кэширование торгового сигнала."""
        key = f"signal:{symbol}:latest"
        return self.set_json(key, signal_data, ex=ttl_seconds)

    def get_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Получение последнего сигнала."""
        key = f"signal:{symbol}:latest"
        return self.get_json(key)

    def cache_ml_prediction(
        self,
        symbol: str,
        prediction: Dict[str, Any],
        ttl_seconds: int = 3600,
    ) -> bool:
        """Кэширование ML предсказания."""
        key = f"ml:{symbol}:prediction"
        return self.set_json(key, prediction, ex=ttl_seconds)

    def get_ml_prediction(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Получение закэшированного ML предсказания."""
        key = f"ml:{symbol}:prediction"
        return self.get_json(key)

    # ========== PUB/SUB OPERATIONS ==========

    def publish(self, channel: str, message: str) -> int:
        """Публикация сообщения в канал."""
        if not self.enabled:
            return 0
        try:
            return self._client.publish(channel, message)
        except Exception as e:
            logger.error(f"Redis PUBLISH error: {e}")
            return 0

    def subscribe(self, channel: str):
        """Подписка на канал."""
        if not self.enabled:
            return None
        try:
            self._pubsub = self._client.pubsub()
            self._pubsub.subscribe(channel)
            logger.info(f"Redis: Подписка на канал '{channel}'")
            return self._pubsub
        except Exception as e:
            logger.error(f"Redis SUBSCRIBE error: {e}")
            return None

    def unsubscribe(self, channel: str):
        """Отписка от канала."""
        if not self.enabled or not self._pubsub:
            return
        try:
            self._pubsub.unsubscribe(channel)
            logger.info(f"Redis: Отписка от канала '{channel}'")
        except Exception as e:
            logger.error(f"Redis UNSUBSCRIBE error: {e}")

    def get_message(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Получение сообщения из pub/sub."""
        if not self.enabled or not self._pubsub:
            return None
        try:
            return self._pubsub.get_message(timeout=timeout)
        except Exception as e:
            logger.error(f"Redis GET_MESSAGE error: {e}")
            return None

    # ========== STATS ==========

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики Redis."""
        if not self.enabled:
            return {}
        try:
            info = self._client.info("stats")
            return {
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "N/A"),
                "total_connections_received": info.get("total_connections_received", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
            }
        except Exception as e:
            logger.error(f"Redis GET_STATS error: {e}")
            return {}

    def dbsize(self) -> int:
        """Получение количества ключей в базе."""
        if not self.enabled:
            return 0
        try:
            return self._client.dbsize()
        except Exception as e:
            logger.error(f"Redis DBSIZE error: {e}")
            return 0

    def flushdb(self):
        """Очистка текущей базы данных (ОСТОРОЖНО!)."""
        if not self.enabled:
            return
        logger.warning("Redis FLUSHDB - очистка всех данных!")
        try:
            self._client.flushdb()
        except Exception as e:
            logger.error(f"Redis FLUSHDB error: {e}")

    # ========== CONNECTION ==========

    def ping(self) -> bool:
        """Проверка подключения."""
        if not self.enabled:
            return False
        try:
            return self._client.ping()
        except Exception as e:
            logger.error(f"Redis PING error: {e}")
            return False

    def close(self):
        """Закрытие соединения."""
        if self._client:
            self._client.close()
            logger.info("Redis соединение закрыто")

        if self._pubsub:
            self._pubsub.close()
            logger.info("Redis pub/sub закрыт")
