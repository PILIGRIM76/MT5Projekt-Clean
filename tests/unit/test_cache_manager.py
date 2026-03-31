# tests/unit/test_cache_manager.py
"""
Unit тесты для Cache Manager (LRUCache).

Проверяет:
- LRU кэширование
- TTL (time-to-live)
- Лимиты размера
- Статистику hits/misses
"""

import pytest
import time
from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.cache_manager import LRUCache, CacheEntry


class TestCacheEntry:
    """Тесты для CacheEntry."""

    def test_cache_entry_creation(self):
        """Создание элемента кэша."""
        entry = CacheEntry("value1")
        
        assert entry.value == "value1"
        assert entry.ttl is None
        assert entry.access_count == 0

    def test_cache_entry_with_ttl(self):
        """Создание элемента с TTL."""
        entry = CacheEntry("value1", ttl=60)
        
        assert entry.ttl == 60
        assert entry.is_expired() is False

    def test_cache_entry_expiration(self):
        """Проверка истечения TTL."""
        entry = CacheEntry("value1", ttl=1)
        
        assert entry.is_expired() is False
        
        time.sleep(1.5)
        
        assert entry.is_expired() is True

    def test_cache_entry_access(self):
        """Проверка доступа к элементу."""
        entry = CacheEntry("value1")
        
        entry.access()
        assert entry.access_count == 1
        
        entry.access()
        assert entry.access_count == 2

    def test_cache_entry_repr(self):
        """Проверка строкового представления."""
        entry = CacheEntry("value1")
        repr_str = repr(entry)
        
        assert "CacheEntry" in repr_str
        assert "age=" in repr_str


class TestLRUCacheInit:
    """Тесты инициализации LRUCache."""

    def test_init_default_values(self):
        """Инициализация с параметрами по умолчанию."""
        cache = LRUCache()
        
        assert cache.max_size == 1000

    def test_init_custom_values(self):
        """Инициализация с пользовательскими параметрами."""
        cache = LRUCache(max_size=500, name="TestCache")
        
        assert cache.max_size == 500
        assert cache.name == "TestCache"


class TestLRUCacheOperations:
    """Тесты операций кэша."""

    @pytest.fixture
    def cache(self):
        """Фикстура с пустым кэшем."""
        return LRUCache(max_size=100)

    def test_set_and_get(self, cache):
        """Установка и получение значения."""
        cache.put("key1", "value1")

        assert cache.get("key1") == "value1"

    def test_get_non_existent_key(self, cache):
        """Получение несуществующего ключа."""
        result = cache.get("non_existent")

        assert result is None

    def test_overwrite_existing_key(self, cache):
        """Перезапись существующего ключа."""
        cache.put("key1", "value1")
        cache.put("key1", "value2")

        assert cache.get("key1") == "value2"

    def test_delete_key(self, cache):
        """Удаление ключа."""
        cache.put("key1", "value1")
        cache.delete("key1")

        assert cache.get("key1") is None

    def test_delete_non_existent_key(self, cache):
        """Удаление несуществующего ключа."""
        cache.delete("non_existent")  # Не должно вызвать ошибку

    def test_clear_cache(self, cache):
        """Очистка кэша."""
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.get("key3") is None

    def test_cache_size(self, cache):
        """Размер кэша."""
        assert len(cache) == 0

        cache.put("key1", "value1")
        assert len(cache) == 1

        cache.put("key2", "value2")
        assert len(cache) == 2

        cache.delete("key1")
        assert len(cache) == 1

    def test_contains(self, cache):
        """Проверка оператора in."""
        cache.put("key1", "value1")

        assert "key1" in cache
        assert "key2" not in cache


class TestLRUCacheTTL:
    """Тесты TTL."""

    def test_ttl_expiration(self):
        """Истечение TTL."""
        cache = LRUCache(max_size=100)
        
        cache.put("key1", "value1", ttl=1)
        assert cache.get("key1") == "value1"
        
        time.sleep(1.5)
        
        assert cache.get("key1") is None

    def test_ttl_no_expiration(self):
        """Значение не истекает раньше времени."""
        cache = LRUCache(max_size=100)
        
        cache.put("key1", "value1", ttl=60)
        
        time.sleep(0.5)
        
        assert cache.get("key1") == "value1"


class TestLRUCacheMaxSize:
    """Тесты максимального размера."""

    def test_max_size_limit(self):
        """Ограничение максимального размера."""
        cache = LRUCache(max_size=3)
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        
        assert len(cache) == 3
        
        cache.put("key4", "value4")
        
        assert len(cache) == 3

    def test_lru_eviction(self):
        """Вытеснение наименее используемых элементов."""
        cache = LRUCache(max_size=3)
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        
        cache.get("key1")  # Делаем key1 недавно использованным
        
        cache.put("key4", "value4")
        
        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None  # Вытеснен
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"


class TestLRUCacheStatistics:
    """Тесты статистики."""

    def test_cache_statistics(self):
        """Получение статистики кэша."""
        cache = LRUCache(max_size=100)
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.get("key1")  # hit
        cache.get("key2")  # hit
        cache.get("non_existent")  # miss
        
        stats = cache.stats()
        
        assert "hits" in stats
        assert "misses" in stats
        assert "size" in stats
        assert stats["size"] == 2
        assert stats["hits"] == 2
        assert stats["misses"] == 1

    def test_hit_rate_calculation(self):
        """Расчет процента попаданий."""
        cache = LRUCache(max_size=100)
        
        cache.put("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key1")  # hit
        cache.get("key2")  # miss
        cache.get("key1")  # hit
        
        stats = cache.stats()
        
        # 3 hits, 1 miss = 4 total, hit rate = 75%
        assert stats["hits"] == 3
        assert stats["misses"] == 1
        assert stats["hit_rate"] == "75.00%"

    def test_miss_rate_calculation(self):
        """Расчет процента промахов."""
        cache = LRUCache(max_size=100)
        
        cache.get("key1")  # miss
        cache.get("key2")  # miss
        cache.put("key3", "value3")
        cache.get("key3")  # hit
        
        stats = cache.stats()
        
        # 2 miss, 1 hit = 3 total
        assert stats["misses"] == 2
        assert stats["hits"] == 1
        # Miss rate = 2/3 = 66.67%
        assert stats["miss_rate"] == "66.67%"
