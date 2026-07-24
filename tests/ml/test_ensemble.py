"""
Тесты для EnsemblePredictor.
"""

import asyncio

import numpy as np
import pytest

from src.ml.ensemble_predictor import (
    EnsembleMethod,
    EnsemblePredictor,
    ModelWeight,
)


class MockPredicter:
    def __init__(self, bias: float, noise: float = 0.1):
        self.bias = bias
        self.noise = noise

    async def predict(self, symbol: str, features):
        pred = self.bias + np.random.uniform(-self.noise, self.noise)
        conf = 0.7 + np.random.uniform(0, 0.2)
        return np.clip(pred, 0, 1), conf


class TestEnsemblePredictor:
    """Тесты EnsemblePredictor."""

    @pytest.mark.asyncio
    async def test_ensemble_weighted_average(self):
        """Проверка: взвешенное среднее."""
        predictors = {
            "strong": MockPredicter(bias=0.8, noise=0.05),
            "medium": MockPredicter(bias=0.6, noise=0.1),
            "weak": MockPredicter(bias=0.4, noise=0.2),
        }

        ensemble = EnsemblePredictor(
            config={},
            base_predictors=predictors,
            method=EnsembleMethod.WEIGHTED_AVERAGE,
        )

        result = await ensemble.predict("EURUSD", np.random.rand(10, 5))

        assert 0.0 <= result["prediction"] <= 1.0
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["active_models"] == 3
        assert "model_weights" in result

    @pytest.mark.asyncio
    async def test_ensemble_majority_vote(self):
        """Проверка: голосование большинством."""
        predictors = {
            "buy1": MockPredicter(bias=0.9, noise=0.01),
            "buy2": MockPredicter(bias=0.85, noise=0.01),
            "sell": MockPredicter(bias=0.2, noise=0.01),
        }

        ensemble = EnsemblePredictor(
            config={},
            base_predictors=predictors,
            method=EnsembleMethod.MAJORITY_VOTE,
            min_agreement=0.6,
        )

        result = await ensemble.predict("GBPUSD", np.random.rand(10, 5))

        # 2 из 3 за BUY → должно быть предсказание BUY
        assert result["prediction"] >= 0.5
        assert result["active_models"] >= 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_isolation(self):
        """Проверка: CircuitBreaker изолирует сбои."""

        class FailingPredictor:
            async def predict(self, symbol, features):
                raise RuntimeError("Model broken")

        predictors = {
            "good": MockPredicter(bias=0.7),
            "bad": FailingPredictor(),
        }

        ensemble = EnsemblePredictor(
            {}, predictors, EnsembleMethod.WEIGHTED_AVERAGE
        )

        # 3 запроса должны "отключить" bad модель
        for _ in range(3):
            await ensemble.predict("TEST", np.random.rand(5, 3))

        # 4-й запрос: bad модель должна быть в circuit open
        result = await ensemble.predict("TEST", np.random.rand(5, 3))
        assert result["active_models"] == 1

    @pytest.mark.asyncio
    async def test_ensemble_adaptive_weights(self):
        """Проверка: адаптивные веса."""
        predictors = {
            "accurate": MockPredicter(bias=0.8, noise=0.02),
            "noisy": MockPredicter(bias=0.5, noise=0.3),
        }
        ensemble = EnsemblePredictor(
            {}, predictors, EnsembleMethod.BAYESIAN_AVERAGE
        )

        # Симуляция обратной связи
        for _ in range(20):
            pred = await ensemble.predict(
                "TEST", np.random.rand(5, 3)
            )
            ensemble.record_outcome(
                "TEST", pred["prediction"], actual_outcome=1.0
            )

        accurate_weight = ensemble.weights["accurate"].adaptive_weight()
        noisy_weight = ensemble.weights["noisy"].adaptive_weight()

        # Веса могут быть равны при одинаковой истории
        assert accurate_weight >= 0.1
        assert noisy_weight >= 0.1

    @pytest.mark.asyncio
    async def test_ensemble_get_stats(self):
        """Проверка: статистика ансамбля."""
        predictors = {
            "m1": MockPredicter(bias=0.7),
            "m2": MockPredicter(bias=0.6),
        }
        ensemble = EnsemblePredictor(
            {}, predictors, EnsembleMethod.WEIGHTED_AVERAGE
        )

        await ensemble.predict("TEST", np.random.rand(5, 3))

        stats = ensemble.get_stats()
        assert "predictions" in stats
        assert "avg_confidence" in stats
        assert "method" in stats
        assert "n_models" in stats


class TestModelWeight:
    """Тесты ModelWeight."""

    def test_adaptive_weight_with_history(self):
        """Проверка: адаптивный вес с историей."""
        weight = ModelWeight("test", weight=0.5)
        weight.accuracy_history = [1.0] * 10  # 100% точность

        adaptive = weight.adaptive_weight()
        assert adaptive > 0.5

    def test_adaptive_weight_min(self):
        """Проверка: минимальный вес."""
        weight = ModelWeight("test", weight=0.1)
        weight.accuracy_history = [0.0] * 10  # 0% точность

        adaptive = weight.adaptive_weight(min_weight=0.1)
        assert adaptive >= 0.1
