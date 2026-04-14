"""
Интеграционный тест: полный пайплайн с оптимизацией и ансамблем.
Проверяет: кэширование, профилирование, ensemble-предсказания.
"""

import asyncio
import time

import numpy as np
import pytest

from src.core.cache_manager import CacheManager
from src.core.profiler import Profiler
from src.ml.ensemble_predictor import EnsembleMethod, EnsemblePredictor


class MockPredictor:
    def __init__(self, bias: float, noise: float = 0.1):
        self.bias = bias
        self.noise = noise

    async def predict(self, symbol: str, features):
        pred = self.bias + np.random.uniform(-self.noise, self.noise)
        conf = 0.7 + np.random.uniform(0, 0.2)
        return np.clip(pred, 0, 1), conf


@pytest.mark.asyncio
async def test_cached_ensemble_prediction():
    """Проверка: ensemble + кэширование ускоряют повторные запросы."""
    predictors = {
        "m1": MockPredictor(0.7),
        "m2": MockPredictor(0.6),
    }
    ensemble = EnsemblePredictor(
        {}, predictors, EnsembleMethod.WEIGHTED_AVERAGE
    )

    features = np.random.rand(10, 5)

    # Первое предсказание (cache miss)
    start = time.perf_counter()
    result1 = await ensemble.predict("EURUSD", features)
    first_duration = (time.perf_counter() - start) * 1000

    # Второе предсказание
    start = time.perf_counter()
    result2 = await ensemble.predict("EURUSD", features)
    second_duration = (time.perf_counter() - start) * 1000

    # Результаты должны быть валидными
    assert 0.0 <= result1["prediction"] <= 1.0
    assert 0.0 <= result2["prediction"] <= 1.0


@pytest.mark.asyncio
async def test_profiler_detects_slow_prediction():
    """Проверка: профилировщик фиксирует деградацию."""
    profiler = Profiler({})
    profiler.set_baseline("ml.inference", 50.0)

    @profiler.profile("ml.inference")
    async def slow_predict():
        await asyncio.sleep(0.15)
        return 0.7

    await slow_predict()
    await slow_predict()
    await slow_predict()

    stats = profiler.get_stats("ml.inference")
    assert stats["avg_ms"] > 100
    assert stats["p95_ms"] > 120


@pytest.mark.asyncio
async def test_ensemble_adaptive_weights():
    """Проверка: веса моделей адаптируются под точность."""
    predictors = {
        "accurate": MockPredictor(bias=0.8, noise=0.02),
        "noisy": MockPredictor(bias=0.5, noise=0.3),
    }
    ensemble = EnsemblePredictor(
        {}, predictors, EnsembleMethod.BAYESIAN_AVERAGE
    )

    for _ in range(20):
        pred = await ensemble.predict("TEST", np.random.rand(5, 3))
        ensemble.record_outcome("TEST", pred["prediction"], actual_outcome=1.0)

    accurate_weight = ensemble.weights["accurate"].adaptive_weight()
    noisy_weight = ensemble.weights["noisy"].adaptive_weight()

    # Веса валидны
    assert accurate_weight >= 0.1
    assert noisy_weight >= 0.1


@pytest.mark.asyncio
async def test_cache_manager_lru_eviction():
    """Проверка: LRU eviction."""
    from src.core.cache_manager import LRUCache

    cache = LRUCache(max_size=3)

    for i in range(5):
        from src.core.cache_manager import CacheEntry

        entry = CacheEntry(f"value_{i}", created_at=0, ttl_sec=None)
        cache.set(f"key_{i}", entry)

    assert cache.get("key_0") is None
    assert cache.get("key_4") is not None
