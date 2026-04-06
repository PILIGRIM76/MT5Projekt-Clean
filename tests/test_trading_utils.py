# -*- coding: utf-8 -*-
"""
Тесты для Trading Core Utils — извлечённые утилиты из TradingSystem.
"""

import pytest
import time
from src.core.trading import TradingCache, PerformanceTimer, get_timeframe_seconds, get_timeframe_str


class TestTradingCache:
    """Тесты кэша торговых ядра."""

    def test_cache_get_set(self):
        """Базовое сохранение и получение."""
        cache = TradingCache(max_size=100)
        cache.set("EURUSD", {"price": 1.0850})

        result = cache.get("EURUSD")
        assert result == {"price": 1.0850}

    def test_cache_returns_none_for_missing(self):
        """Отсутствующий ключ возвращает None."""
        cache = TradingCache()
        assert cache.get("NONEXISTENT") is None

    def test_cache_evicts_oldest_when_full(self):
        """При заполнении удаляется oldest entry."""
        cache = TradingCache(max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Должен вытеснить key1

        assert cache.get("key1") is None
        assert cache.get("key2") is not None
        assert cache.get("key3") is not None

    def test_cache_invalidate_single_key(self):
        """Инвалидация конкретного ключа."""
        cache = TradingCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.invalidate("key1")

        assert cache.get("key1") is None
        assert cache.get("key2") is not None

    def test_cache_invalidate_all(self):
        """Полная очистка кэша."""
        cache = TradingCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.invalidate()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_stats(self):
        """Статистика кэша."""
        cache = TradingCache(max_size=100)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        stats = cache.stats()

        assert stats["size"] == 2
        assert stats["max_size"] == 100


class TestPerformanceTimer:
    """Тесты таймера производительности."""

    def test_timer_measures_elapsed(self):
        """Таймер измеряет прошедшее время."""
        timer = PerformanceTimer()
        timer.start("test_op")
        time.sleep(0.05)
        elapsed = timer.end("test_op")

        assert elapsed >= 0.05
        assert elapsed < 1.0

    def test_timer_returns_zero_for_unstarted(self):
        """Незапущенный таймер возвращает 0."""
        timer = PerformanceTimer()
        elapsed = timer.end("nonexistent")

        assert elapsed == 0.0

    def test_timer_removes_completed(self):
        """Завершённый таймер удаляется."""
        timer = PerformanceTimer()
        timer.start("op1")
        timer.end("op1")

        # Повторный end должен вернуть 0
        assert timer.end("op1") == 0.0


class TestTimeframeHelpers:
    """Тесты хелперов таймфреймов."""

    def test_get_timeframe_seconds_known(self):
        """Известные таймфреймы возвращают правильное значение."""
        assert get_timeframe_seconds("M1") == 60
        assert get_timeframe_seconds("M5") == 300
        assert get_timeframe_seconds("M15") == 900
        assert get_timeframe_seconds("H1") == 3600
        assert get_timeframe_seconds("H4") == 14400
        assert get_timeframe_seconds("D1") == 86400
        assert get_timeframe_seconds("W1") == 604800

    def test_get_timeframe_seconds_unknown_returns_default(self):
        """Неизвестный таймфрейм возвращает дефолт (H1)."""
        assert get_timeframe_seconds("UNKNOWN") == 3600

    def test_get_timeframe_str_known(self):
        """Коды таймфреймов конвертируются в строки."""
        assert get_timeframe_str(60) == "M1"
        assert get_timeframe_str(3600) == "H1"
        assert get_timeframe_str(86400) == "D1"

    def test_get_timeframe_str_unknown_returns_default(self):
        """Неизвестный код возвращает дефолт H1."""
        assert get_timeframe_str(999999) == "H1"
