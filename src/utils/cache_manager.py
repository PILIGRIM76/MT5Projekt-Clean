# src/utils/cache_manager.py
"""
Менеджер кэширования для Genesis Trading System.

Реализует:
- LRU (Least Recently Used) кэш
- TTL (Time To Live) для элементов
- Декораторы для кэширования функций
- Статистику хитов/миссов

Пример использования:
    from src.utils.cache_manager import cache_result, LRUCache

    # Глобальный кэш
    market_data_cache = LRUCache(max_size=100)

    # Кэширование функции
    @cache_result(market_data_cache, ttl=60)
    def get_market_data(symbol: str) -> pd.DataFrame:
        # Тяжелые вычисления...
        return data
"""

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ===========================================
# Cache Entry
# ===========================================


class CacheEntry:
    """
    Элемент кэша с TTL поддержкой.
    """

    def __init__(self, value: Any, ttl: Optional[float] = None):
        """
        Инициализация элемента кэша.

        Args:
            value: Значение для кэширования
            ttl: Время жизни в секундах (None = бесконечно)
        """
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.access_count = 0
        self.last_accessed = self.created_at

    def is_expired(self) -> bool:
        """
        Проверка истечения TTL.

        Returns:
            True если элемент истек
        """
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl

    def access(self) -> None:
        """
        Обновление времени последнего доступа.
        """
        self.access_count += 1
        self.last_accessed = time.time()

    def __repr__(self) -> str:
        age = time.time() - self.created_at
        return f"<CacheEntry age={age:.1f}s ttl={self.ttl} accesses={self.access_count}>"


# ===========================================
# LRU Cache
# ===========================================


class LRUCache:
    """
    LRU (Least Recently Used) кэш с TTL поддержкой.

    Особенности:
    - Автоматическое удаление старых элементов
    - Поддержка TTL для каждого элемента
    - Статистика хитов/миссов
    - Потокобезопасность (опционально)
    """

    def __init__(self, max_size: int = 1000, name: str = "LRUCache"):
        """
        Инициализация LRU кэша.

        Args:
            max_size: Максимальный размер кэша
            name: Имя кэша для логирования
        """
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size
        self.name = name
        self.hits = 0
        self.misses = 0
        self.expirations = 0

        logger.info(f"{name} инициализирован (max_size={max_size})")

    def get(self, key: str) -> Optional[Any]:
        """
        Получение значения из кэша.

        Args:
            key: Ключ кэша

        Returns:
            Значение или None если не найдено/истекло
        """
        if key not in self.cache:
            self.misses += 1
            logger.debug(f"{self.name} miss: {key}")
            return None

        entry = self.cache[key]

        # Проверка TTL
        if entry.is_expired():
            del self.cache[key]
            self.expirations += 1
            self.misses += 1
            logger.debug(f"{self.name} expired: {key}")
            return None

        # Перемещение в конец (использовалось недавно)
        self.cache.move_to_end(key)
        entry.access()
        self.hits += 1

        logger.debug(f"{self.name} hit: {key}")
        return entry.value

    def put(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """
        Установка значения в кэш.

        Args:
            key: Ключ кэша
            value: Значение
            ttl: Время жизни в секундах
        """
        if key in self.cache:
            # Обновление существующего
            self.cache.move_to_end(key)
            self.cache[key] = CacheEntry(value, ttl)
        else:
            # Добавление нового
            if len(self.cache) >= self.max_size:
                # Удаление наименее используемого
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                logger.debug(f"{self.name} evicted: {oldest_key}")

            self.cache[key] = CacheEntry(value, ttl)

        logger.debug(f"{self.name} put: {key} (ttl={ttl})")

    def delete(self, key: str) -> bool:
        """
        Удаление значения из кэша.

        Args:
            key: Ключ кэша

        Returns:
            True если удалено
        """
        if key in self.cache:
            del self.cache[key]
            logger.debug(f"{self.name} delete: {key}")
            return True
        return False

    def clear(self) -> None:
        """
        Очистка всего кэша.
        """
        self.cache.clear()
        self.hits = 0
        self.misses = 0
        self.expirations = 0
        logger.info(f"{self.name} cleared")

    def cleanup_expired(self) -> int:
        """
        Очистка истекших элементов.

        Returns:
            Количество удаленных элементов
        """
        expired_keys = [key for key, entry in self.cache.items() if entry.is_expired()]

        for key in expired_keys:
            del self.cache[key]
            self.expirations += 1

        if expired_keys:
            logger.debug(f"{self.name} cleaned up {len(expired_keys)} expired entries")

        return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        """
        Получение статистики кэша.

        Returns:
            Словарь со статистикой
        """
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        miss_rate = (self.misses / total * 100) if total > 0 else 0

        return {
            "name": self.name,
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "expirations": self.expirations,
            "hit_rate": f"{hit_rate:.2f}%",
            "miss_rate": f"{miss_rate:.2f}%",
            "utilization": f"{len(self.cache) / self.max_size * 100:.1f}%",
        }

    def keys(self) -> List[str]:
        """
        Получение всех ключей.

        Returns:
            Список ключей
        """
        return list(self.cache.keys())

    def __contains__(self, key: str) -> bool:
        """
        Проверка наличия ключа в кэше.

        Args:
            key: Ключ для проверки

        Returns:
            True если ключ существует и не истек
        """
        if key not in self.cache:
            return False
        entry = self.cache[key]
        return not entry.is_expired()

    def __len__(self) -> int:
        """
        Размер кэша.

        Returns:
            Количество элементов
        """
        return len(self.cache)

    def __repr__(self) -> str:
        stats = self.stats()
        return f"<{self.name} size={stats['size']}/{stats['max_size']} hit_rate={stats['hit_rate']}>"


# ===========================================
# Global Cache Instances
# ===========================================

# Кэш режимов рынка (кэш на 1 минуту)
market_regime_cache = LRUCache(max_size=50, name="MarketRegimeCache")

# Кэш Pre-Mortem анализа (кэш на 5 минут)
pre_mortem_cache = LRUCache(max_size=100, name="PreMortemCache")

# Кэш векторного поиска (кэш на 10 минут)
vector_search_cache = LRUCache(max_size=200, name="VectorSearchCache")

# Кэш котировок (кэш на 30 секунд)
quotes_cache = LRUCache(max_size=500, name="QuotesCache")

# Кэш новостей (кэш на 5 минут)
news_cache = LRUCache(max_size=100, name="NewsCache")


# ===========================================
# Cache Decorators
# ===========================================


def cache_result(cache: LRUCache, ttl: Optional[float] = None, key_prefix: str = ""):
    """
    Декоратор для кэширования результатов функций.

    Args:
        cache: Экземпляр кэша для использования
        ttl: Время жизни кэша в секундах
        key_prefix: Префикс для ключа кэша

    Returns:
        Декоратор

    Example:
        @cache_result(market_regime_cache, ttl=60)
        def get_market_regime(symbol: str, df: pd.DataFrame) -> str:
            # Тяжелые вычисления...
            return regime
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Генерация ключа кэша
            cache_key = _generate_cache_key(func, args, kwargs, key_prefix)

            # Проверка кэша
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_value

            # Вызов функции
            logger.debug(f"Cache miss for {func.__name__}")
            result = await func(*args, **kwargs)

            # Сохранение в кэш
            cache.put(cache_key, result, ttl)
            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Генерация ключа кэша
            cache_key = _generate_cache_key(func, args, kwargs, key_prefix)

            # Проверка кэша
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_value

            # Вызов функции
            logger.debug(f"Cache miss for {func.__name__}")
            result = func(*args, **kwargs)

            # Сохранение в кэш
            cache.put(cache_key, result, ttl)
            return result

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


def _generate_cache_key(func: Callable, args: tuple, kwargs: dict, prefix: str) -> str:
    """
    Генерация уникального ключа кэша.

    Args:
        func: Функция
        args: Позиционные аргументы
        kwargs: Именованные аргументы
        prefix: Префикс ключа

    Returns:
        Уникальный ключ кэша
    """
    # Сериализация аргументов
    key_data = {"func": func.__name__, "args": args, "kwargs": kwargs}

    # JSON сериализация с сортировкой ключей
    key_str = json.dumps(key_data, sort_keys=True, default=str)

    # MD5 хэш
    key_hash = hashlib.md5(key_str.encode()).hexdigest()

    return f"{prefix}{func.__name__}:{key_hash}" if prefix else f"{func.__name__}:{key_hash}"


# ===========================================
# Cache Management Functions
# ===========================================


def cleanup_all_caches() -> Dict[str, int]:
    """
    Очистка всех глобальных кэшей.

    Returns:
        Словарь {имя_кэша: количество_удаленных}
    """
    global_caches = [market_regime_cache, pre_mortem_cache, vector_search_cache, quotes_cache, news_cache]

    results = {}
    for cache in global_caches:
        cleaned = cache.cleanup_expired()
        results[cache.name] = cleaned

    logger.info(f"Cleanup all caches: {results}")
    return results


def get_all_cache_stats() -> Dict[str, Dict[str, Any]]:
    """
    Получение статистики всех глобальных кэшей.

    Returns:
        Словарь {имя_кэша: статистика}
    """
    global_caches = [market_regime_cache, pre_mortem_cache, vector_search_cache, quotes_cache, news_cache]

    return {cache.name: cache.stats() for cache in global_caches}


def print_cache_stats() -> None:
    """
    Вывод статистики всех кэшей в лог.
    """
    stats = get_all_cache_stats()

    logger.info("=" * 60)
    logger.info("CACHE STATISTICS")
    logger.info("=" * 60)

    for name, cache_stats in stats.items():
        logger.info(f"{name}:")
        logger.info(f"  Size: {cache_stats['size']}/{cache_stats['max_size']} ({cache_stats['utilization']})")
        logger.info(f"  Hits: {cache_stats['hits']}, Misses: {cache_stats['misses']}")
        logger.info(f"  Hit Rate: {cache_stats['hit_rate']}")
        logger.info(f"  Expirations: {cache_stats['expirations']}")
        logger.info("-" * 60)
