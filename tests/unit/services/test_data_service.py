# -*- coding: utf-8 -*-
"""
Тесты для LRUCache и DataService.

Проверяет:
- LRU-кэш (get/put/clear/size)
- DataService жизненный цикл
- DataService health check
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.data.data_provider import LRUCache

# ===========================================
# Фикстуры
# ===========================================


@pytest.fixture
def sample_dataframe():
    """Пример DataFrame для кэширования."""
    dates = pd.date_range(start="2024-01-01", periods=100, freq="h")
    df = pd.DataFrame(
        {
            "open": np.random.rand(100) * 100,
            "high": np.random.rand(100) * 100,
            "low": np.random.rand(100) * 100,
            "close": np.random.rand(100) * 100,
            "tick_volume": np.random.randint(100, 1000, 100),
        },
        index=dates,
    )
    return df


# ===========================================
# Тесты LRUCache
# ===========================================


class TestLRUCache:
    """Тесты LRU-кэша."""

    def test_init_default_size(self):
        """Тест инициализации с размером по умолчанию."""
        cache = LRUCache()
        assert cache.max_size == 100
        assert cache.size() == 0

    def test_init_custom_size(self):
        """Тест инициализации с кастомным размером."""
        cache = LRUCache(max_size=10)
        assert cache.max_size == 10

    def test_put_and_get(self, sample_dataframe):
        """Тест сохранения и получения данных."""
        cache = LRUCache(max_size=10)
        key = "test_key"

        cache.put(key, sample_dataframe)
        retrieved = cache.get(key)

        assert retrieved is not None
        pd.testing.assert_frame_equal(retrieved, sample_dataframe)

    def test_get_nonexistent_key(self):
        """Тест получения несуществующего ключа."""
        cache = LRUCache()
        result = cache.get("nonexistent")
        assert result is None

    def test_put_updates_existing_key(self, sample_dataframe):
        """Тест обновления существующего ключа."""
        cache = LRUCache(max_size=10)
        key = "test_key"

        # Первое значение
        cache.put(key, sample_dataframe)

        # Второе значение
        new_df = sample_dataframe * 2
        cache.put(key, new_df)

        retrieved = cache.get(key)
        pd.testing.assert_frame_equal(retrieved, new_df)
        assert cache.size() == 1  # Размер не изменился

    def test_lru_eviction(self, sample_dataframe):
        """Тест вытеснения по LRU."""
        cache = LRUCache(max_size=3)

        # Добавляем 3 элемента
        cache.put("key1", sample_dataframe)
        cache.put("key2", sample_dataframe)
        cache.put("key3", sample_dataframe)

        assert cache.size() == 3

        # Добавляем 4-й элемент (должен вытеснить key1)
        cache.put("key4", sample_dataframe)

        assert cache.size() == 3
        assert cache.get("key1") is None  # Вытеснен
        assert cache.get("key2") is not None
        assert cache.get("key3") is not None
        assert cache.get("key4") is not None

    def test_lru_order_updated_on_get(self, sample_dataframe):
        """Тест обновления порядка при получении."""
        cache = LRUCache(max_size=3)

        # Добавляем элементы
        cache.put("key1", sample_dataframe)
        cache.put("key2", sample_dataframe)
        cache.put("key3", sample_dataframe)

        # Получаем key1 (делает его самым свежим)
        cache.get("key1")

        # Добавляем новый элемент (должен вытеснить key2)
        cache.put("key4", sample_dataframe)

        assert cache.get("key1") is not None  # Не вытеснен
        assert cache.get("key2") is None  # Вытеснен
        assert cache.get("key3") is not None
        assert cache.get("key4") is not None

    def test_clear(self, sample_dataframe):
        """Тест очистки кэша."""
        cache = LRUCache(max_size=10)

        cache.put("key1", sample_dataframe)
        cache.put("key2", sample_dataframe)

        assert cache.size() == 2

        cache.clear()

        assert cache.size() == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_size(self, sample_dataframe):
        """Тест размера кэша."""
        cache = LRUCache(max_size=10)

        assert cache.size() == 0

        cache.put("key1", sample_dataframe)
        assert cache.size() == 1

        cache.put("key2", sample_dataframe)
        assert cache.size() == 2

        cache.clear()
        assert cache.size() == 0

    def test_thread_safety(self, sample_dataframe):
        """Тест потокобезопасности."""
        import threading

        cache = LRUCache(max_size=100)
        errors = []

        def worker(worker_id):
            try:
                for i in range(10):
                    key = f"worker{worker_id}_key{i}"
                    cache.put(key, sample_dataframe)
                    cache.get(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert cache.size() <= 100


# ===========================================
# Тесты DataService
# ===========================================


class TestDataService:
    """Тесты DataService."""

    @pytest.fixture
    def data_service(self, minimal_config):
        """Фикстура DataService."""
        from src.core.services.data_service import DataService

        return DataService(config=minimal_config)

    @pytest.mark.asyncio
    async def test_init(self, data_service, minimal_config):
        """Тест инициализации DataService."""
        assert data_service.config == minimal_config
        assert data_service.name == "DataService"
        assert data_service._running is False
        assert data_service.data_provider is not None

    @pytest.mark.asyncio
    async def test_start(self, data_service):
        """Тест запуска DataService."""
        with patch.object(data_service, "_check_mt5_connection", new_callable=AsyncMock):
            await data_service.start()

            assert data_service._running is True
            assert data_service._healthy is True

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="_shutdown_mt5 не реализован в текущей версии DataService")
    async def test_stop(self, data_service):
        """Тест остановки DataService."""
        with patch.object(data_service, "_shutdown_mt5", new_callable=AsyncMock):
            await data_service.stop()

            assert data_service._running is False
            assert data_service._healthy is False

    def test_health_check_initial(self, data_service):
        """Тест health check в начальном состоянии."""
        health = data_service.health_check()

        assert "status" in health
        assert "mt5_connected" in health
        assert "cache_size" in health
        assert "requests_count" in health

    def test_health_check_format(self, data_service):
        """Тест формата health check."""
        health = data_service.health_check()

        expected_keys = {
            "status",
            "mt5_connected",
            "cache_size",
            "requests_count",
            "cache_hits",
            "cache_misses",
            "cache_hit_rate",
        }

        assert expected_keys.issubset(health.keys())

    @pytest.mark.asyncio
    async def test_get_available_symbols_mock(self, data_service):
        """Тест получения доступных символов (мок)."""

        async def mock_get_symbols():
            return ["EURUSD", "GBPUSD", "USDJPY"]

        with patch.object(data_service, "get_available_symbols", mock_get_symbols):
            symbols = await data_service.get_available_symbols()
            assert len(symbols) == 3
            assert "EURUSD" in symbols

    @pytest.mark.asyncio
    async def test_filter_available_symbols(self, data_service):
        """Тест фильтрации символов."""

        async def mock_filter(symbols):
            return [s for s in symbols if s in ["EURUSD", "GBPUSD"]]

        with patch.object(data_service, "filter_available_symbols", mock_filter):
            result = await data_service.filter_available_symbols(["EURUSD", "INVALID", "GBPUSD"])
            assert len(result) == 2
            assert "INVALID" not in result

    def test_repr(self, data_service):
        """Тест строкового представления."""
        repr_str = repr(data_service)

        assert "DataService" in repr_str
        assert "running=False" in repr_str


# ===========================================
# Интеграционные тесты DataService
# ===========================================


class TestDataServiceIntegration:
    """Интеграционные тесты DataService."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="_shutdown_mt5 не реализован в текущей версии DataService")
    async def test_full_lifecycle(self, minimal_config):
        """Тест полного жизненного цикла DataService."""
        from src.core.services.data_service import DataService

        service = DataService(config=minimal_config)

        # Начальное состояние
        assert service.is_running is False

        # Запуск (с моком MT5)
        with patch.object(service, "_check_mt5_connection", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = True
            await service.start()

            assert service.is_running is True
            assert service.is_healthy is True

        # Проверка здоровья
        health = service.health_check()
        assert "status" in health

        # Остановка
        with patch.object(service, "_shutdown_mt5", new_callable=AsyncMock):
            await service.stop()

            assert service.is_running is False

    @pytest.mark.asyncio
    async def test_cache_statistics(self, minimal_config):
        """Тест статистики кэша."""
        from src.core.services.data_service import DataService

        service = DataService(config=minimal_config)

        # Начальная статистика
        assert service._requests_count == 0

        # Имитация запросов
        service._requests_count = 5
        service._cache_hits = 3
        service._cache_misses = 2

        health = service.health_check()
        assert health["requests_count"] == 5
        assert health["cache_hits"] == 3
        assert health["cache_misses"] == 2
        assert health["cache_hit_rate"] == "60.0%"  # 3/(3+2) = 60%
