# tests/unit/test_cache_manager.py
"""
Unit тесты для менеджера кэширования.

Проверяет:
- LRU кэш с TTL
- Декораторы кэширования
- Статистику хитов/миссов
- Очистку истекших элементов
"""

import pytest
import time
import asyncio
from src.utils.cache_manager import (
    LRUCache, CacheEntry, cache_result,
    market_regime_cache, cleanup_all_caches, get_all_cache_stats
)


class TestCacheEntry:
    """Тесты для CacheEntry."""
    
    def test_create_entry_no_ttl(self):
        """Создание элемента без TTL."""
        entry = CacheEntry(value="test")
        
        assert entry.value == "test"
        assert entry.ttl is None
        assert entry.is_expired() is False
        assert entry.access_count == 0
    
    def test_create_entry_with_ttl(self):
        """Создание элемента с TTL."""
        entry = CacheEntry(value="test", ttl=10)
        
        assert entry.value == "test"
        assert entry.ttl == 10
        assert entry.is_expired() is False
    
    def test_entry_expiration(self):
        """Истечение TTL."""
        entry = CacheEntry(value="test", ttl=0.1)  # 100ms
        
        assert entry.is_expired() is False
        time.sleep(0.15)
        assert entry.is_expired() is True
    
    def test_entry_access(self):
        """Обновление доступа."""
        entry = CacheEntry(value="test")
        
        initial_access = entry.last_accessed
        time.sleep(0.01)
        
        entry.access()
        
        assert entry.access_count == 1
        assert entry.last_accessed > initial_access


class TestLRUCache:
    """Тесты для LRU кэша."""
    
    @pytest.fixture
    def cache(self):
        """Фикстура с кэшем."""
        return LRUCache(max_size=5, name="TestCache")
    
    def test_put_and_get(self, cache):
        """Поместить и получить."""
        cache.put("key1", "value1")
        
        result = cache.get("key1")
        assert result == "value1"
    
    def test_get_missing_key(self, cache):
        """Получение отсутствующего ключа."""
        result = cache.get("nonexistent")
        assert result is None
    
    def test_cache_miss_increments(self, cache):
        """Подсчет миссов."""
        cache.get("missing")
        
        stats = cache.stats()
        assert stats['misses'] == 1
    
    def test_cache_hit_increments(self, cache):
        """Подсчет хитов."""
        cache.put("key1", "value1")
        cache.get("key1")
        cache.get("key1")
        
        stats = cache.stats()
        assert stats['hits'] == 2
    
    def test_lru_eviction(self, cache):
        """Вытеснение LRU."""
        # Заполняем кэш
        for i in range(5):
            cache.put(f"key{i}", f"value{i}")
        
        # Добавляем новый (должен вытеснить key0)
        cache.put("key_new", "value_new")
        
        # key0 должен быть вытеснен
        assert cache.get("key0") is None
        assert cache.get("key_new") == "value_new"
        
        # Остальные должны остаться
        assert cache.get("key1") == "value1"
    
    def test_lru_order_update(self, cache):
        """Обновление LRU порядка."""
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        
        # Обращаемся к key1 (теперь он наиболее используемый)
        cache.get("key1")
        
        # Добавляем еще 2 (должны вытеснить key2 или key3, но не key1)
        cache.put("key4", "value4")
        cache.put("key5", "value5")
        
        # key1 должен остаться (был недавно использован)
        assert cache.get("key1") == "value1"
        # key2 или key3 должны быть вытеснены
        # (зависит от реализации, проверяем что размер корректен)
        assert len(cache) == 5
    
    def test_ttl_expiration(self, cache):
        """Истечение TTL."""
        cache.put("key1", "value1", ttl=0.1)  # 100ms
        
        assert cache.get("key1") == "value1"
        time.sleep(0.15)
        assert cache.get("key1") is None
        
        stats = cache.stats()
        assert stats['expirations'] == 1
    
    def test_delete(self, cache):
        """Удаление ключа."""
        cache.put("key1", "value1")
        
        result = cache.delete("key1")
        assert result is True
        assert cache.get("key1") is None
    
    def test_delete_missing(self, cache):
        """Удаление отсутствующего ключа."""
        result = cache.delete("nonexistent")
        assert result is False
    
    def test_clear(self, cache):
        """Очистка кэша."""
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.get("key1")  # hits = 1
        
        cache.clear()
        
        assert len(cache) == 0
        stats = cache.stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 0
    
    def test_cleanup_expired(self, cache):
        """Очистка истекших."""
        cache.put("key1", "value1", ttl=0.1)
        cache.put("key2", "value2", ttl=10)  # Долгоживущий
        cache.put("key3", "value3", ttl=0.1)
        
        time.sleep(0.15)
        
        cleaned = cache.cleanup_expired()
        assert cleaned == 2
        assert len(cache) == 1
        assert cache.get("key2") == "value2"
    
    def test_stats(self, cache):
        """Статистика."""
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.get("key1")
        cache.get("key1")
        cache.get("missing")
        
        stats = cache.stats()
        
        assert stats['name'] == "TestCache"
        assert stats['size'] == 2
        assert stats['max_size'] == 5
        assert stats['hits'] == 2
        assert stats['misses'] == 1
        assert 'hit_rate' in stats
        assert 'utilization' in stats
    
    def test_len(self, cache):
        """Длина кэша."""
        assert len(cache) == 0
        
        cache.put("key1", "value1")
        assert len(cache) == 1
        
        cache.put("key2", "value2")
        assert len(cache) == 2
    
    def test_keys(self, cache):
        """Получение ключей."""
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        keys = cache.keys()
        assert "key1" in keys
        assert "key2" in keys
        assert len(keys) == 2
    
    def test_repr(self, cache):
        """Строковое представление."""
        cache.put("key1", "value1")
        repr_str = repr(cache)
        
        assert "TestCache" in repr_str
        assert "size=1" in repr_str


class TestCacheDecorator:
    """Тесты для декоратора кэширования."""
    
    @pytest.fixture
    def test_cache(self):
        """Фикстура с кэшем."""
        return LRUCache(max_size=100, name="DecoratorTestCache")
    
    def test_sync_function_caching(self, test_cache):
        """Кэширование синхронной функции."""
        call_count = [0]
        
        @cache_result(test_cache, ttl=60)
        def expensive_function(x, y):
            call_count[0] += 1
            return x + y
        
        # Первый вызов (miss)
        result1 = expensive_function(2, 3)
        assert result1 == 5
        assert call_count[0] == 1
        
        # Второй вызов (hit)
        result2 = expensive_function(2, 3)
        assert result2 == 5
        assert call_count[0] == 1  # Не увеличился
        
        # Вызов с другими аргументами (miss)
        result3 = expensive_function(5, 5)
        assert result3 == 10
        assert call_count[0] == 2
    
    @pytest.mark.asyncio
    async def test_async_function_caching(self, test_cache):
        """Кэширование асинхронной функции."""
        call_count = [0]
        
        @cache_result(test_cache, ttl=60)
        async def async_expensive_function(x):
            call_count[0] += 1
            await asyncio.sleep(0.01)
            return x * 2
        
        # Первый вызов (miss)
        result1 = await async_expensive_function(5)
        assert result1 == 10
        assert call_count[0] == 1
        
        # Второй вызов (hit)
        result2 = await async_expensive_function(5)
        assert result2 == 10
        assert call_count[0] == 1
    
    def test_cache_key_prefix(self, test_cache):
        """Префикс ключа кэша."""
        call_count = [0]
        
        @cache_result(test_cache, ttl=60, key_prefix="prefix1:")
        def func1(x):
            call_count[0] += 1
            return x
        
        @cache_result(test_cache, ttl=60, key_prefix="prefix2:")
        def func2(x):
            call_count[0] += 1
            return x
        
        func1(5)
        func2(5)
        
        # Оба должны быть вызваны (разные префиксы)
        assert call_count[0] == 2
        
        # Повторные вызовы
        func1(5)
        func2(5)
        
        # Не должны были вызваться снова
        assert call_count[0] == 2


class TestGlobalCaches:
    """Тесты для глобальных кэшей."""
    
    def test_global_cache_instances(self):
        """Глобальные экземпляры кэшей."""
        from src.utils.cache_manager import (
            market_regime_cache,
            pre_mortem_cache,
            vector_search_cache,
            quotes_cache,
            news_cache
        )
        
        assert market_regime_cache is not None
        assert pre_mortem_cache is not None
        assert vector_search_cache is not None
        assert quotes_cache is not None
        assert news_cache is not None
        
        # Все должны быть LRUCache
        assert isinstance(market_regime_cache, LRUCache)
        assert isinstance(pre_mortem_cache, LRUCache)
    
    def test_cleanup_all_caches(self):
        """Очистка всех кэшей."""
        # Добавляем данные
        market_regime_cache.put("test", "data", ttl=0.1)
        
        time.sleep(0.15)
        
        results = cleanup_all_caches()
        
        assert 'MarketRegimeCache' in results
    
    def test_get_all_cache_stats(self):
        """Получение статистики всех кэшей."""
        stats = get_all_cache_stats()
        
        assert 'MarketRegimeCache' in stats
        assert 'PreMortemCache' in stats
        assert 'VectorSearchCache' in stats
        assert 'QuotesCache' in stats
        assert 'NewsCache' in stats
        
        for name, cache_stats in stats.items():
            assert 'size' in cache_stats
            assert 'max_size' in cache_stats
            assert 'hit_rate' in cache_stats
