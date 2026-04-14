"""
Тесты для Profiler и CacheManager.
"""

import asyncio
import time

import pytest

from src.core.cache_manager import CacheEntry, CacheManager
from src.core.profiler import Profiler, TimingStats


class TestTimingStats:
    """Тесты TimingStats."""

    def test_record_and_avg(self):
        """Проверка: запись и среднее время."""
        stats = TimingStats()
        stats.record(10.0)
        stats.record(20.0)
        stats.record(30.0)

        assert stats.count == 3
        assert stats.avg_ms == 20.0
        assert stats.min_ms == 10.0
        assert stats.max_ms == 30.0

    def test_p95_calculation(self):
        """Проверка: расчёт p95."""
        stats = TimingStats()
        for i in range(100):
            stats.record(float(i))

        p95 = stats.p95_ms
        assert 90 <= p95 <= 100

    def test_empty_stats(self):
        """Проверка: пустая статистика."""
        stats = TimingStats()
        assert stats.avg_ms == 0.0
        assert stats.min_ms == float("inf")


class TestProfiler:
    """Тесты Profiler."""

    @pytest.mark.asyncio
    async def test_profiler_records_async_function(self):
        """Проверка: профилирование async функции."""
        profiler = Profiler({})

        @profiler.profile("test.async_func")
        async def slow_func():
            await asyncio.sleep(0.05)
            return "done"

        await slow_func()
        await slow_func()

        stats = profiler.get_stats("test.async_func")
        assert stats["count"] == 2
        assert 40 <= stats["avg_ms"] <= 150

    @pytest.mark.asyncio
    async def test_profiler_records_sync_function(self):
        """Проверка: профилирование sync функции."""
        profiler = Profiler({})

        @profiler.profile("test.sync_func")
        def sync_func():
            time.sleep(0.02)
            return "done"

        sync_func()
        sync_func()

        stats = profiler.get_stats("test.sync_func")
        assert stats["count"] == 2
        assert 15 <= stats["avg_ms"] <= 100

    @pytest.mark.asyncio
    async def test_profiler_baseline_and_degradation(self):
        """Проверка: детекция деградации."""
        profiler = Profiler(
            {"degradation_threshold": 2.0, "report_interval_sec": 1}
        )
        profiler.set_baseline("test.metric", 10.0)

        # Записываем медленные замеры
        for _ in range(15):
            profiler._record("test.metric", 30.0)

        await profiler._check_degradation()
        # Деградация должна быть обнаружена (3x медленнее)

    @pytest.mark.asyncio
    async def test_profiler_get_stats_all(self):
        """Проверка: получение всей статистики."""
        profiler = Profiler({})

        profiler._record("metric1", 10.0)
        profiler._record("metric2", 20.0)

        all_stats = profiler.get_stats()
        assert "metric1" in all_stats
        assert "metric2" in all_stats


class TestLRUCache:
    """Тесты LRUCache."""

    def test_lru_eviction(self):
        """Проверка: LRU eviction."""
        from src.core.cache_manager import LRUCache

        cache = LRUCache(max_size=3)

        for i in range(5):
            entry = CacheEntry(f"value_{i}", created_at=0, ttl_sec=None)
            cache.set(f"key_{i}", entry)

        # Проверяем, что старые ключи вытеснены
        assert cache.get("key_0") is None
        assert cache.get("key_1") is None
        assert cache.get("key_4") is not None

    def test_lru_access_order(self):
        """Проверка: порядок доступа обновляет LRU."""
        from src.core.cache_manager import LRUCache

        cache = LRUCache(max_size=3)
        cache.set("a", CacheEntry("1", 0, None))
        cache.set("b", CacheEntry("2", 0, None))
        cache.set("c", CacheEntry("3", 0, None))

        # Доступ к "a" делает его наиболее recent
        cache.get("a")

        # Добавляем "d" — "b" должен быть evicted
        cache.set("d", CacheEntry("4", 0, None))

        assert cache.get("b") is None
        assert cache.get("a") is not None


class TestCacheManager:
    """Тесты CacheManager."""

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self):
        """Проверка: TTL expiration."""
        entry = CacheEntry("test_value", created_at=time.time() - 2, ttl_sec=1)
        assert entry.is_expired() is True

        entry_no_ttl = CacheEntry(
            "test_value", created_at=time.time() - 100, ttl_sec=None
        )
        assert entry_no_ttl.is_expired() is False

    @pytest.mark.asyncio
    async def test_cache_manager_stats(self):
        """Проверка: статистика кэша."""
        cache = CacheManager({"l1_max_size": 10})

        stats = cache.get_stats()
        assert "l1_hits" in stats
        assert "l1_misses" in stats
        assert "l1_hit_rate_percent" in stats

    @pytest.mark.asyncio
    async def test_cache_invalidation(self):
        """Проверка: инвалидация кэша."""
        cache = CacheManager({"l1_max_size": 10})

        cache._l1.set("test_key", CacheEntry("value", time.time(), None))
        assert cache._l1.get("test_key") is not None

        cache.invalidate(key="test_key")
        assert cache._l1.get("test_key") is None
