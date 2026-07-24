"""
Ensemble-предиктор: консенсус нескольких моделей для повышения точности.
Архитектура: взвешенное голосование / stacking / Bayesian model averaging.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.core.circuit_breaker import CircuitBreaker
from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.thread_domains import ThreadDomain, run_in_domain

logger = logging.getLogger(__name__)


class EnsembleMethod(Enum):
    """Методы агрегации предсказаний"""

    WEIGHTED_AVERAGE = auto()
    MAJORITY_VOTE = auto()
    STACKING = auto()
    BAYESIAN_AVERAGE = auto()


@dataclass
class ModelWeight:
    """Вес модели в ансамбле"""

    model_id: str
    weight: float
    accuracy_history: List[float] = field(default_factory=list)
    last_updated: float = field(default_factory=lambda: 0)

    def adaptive_weight(self, min_weight: float = 0.1) -> float:
        """Адаптивный вес на основе истории точности"""
        if len(self.accuracy_history) < 10:
            return self.weight
        recent_acc = np.mean(self.accuracy_history[-10:])
        return max(min_weight, min(1.0, (recent_acc - 0.5) * 2))


class EnsemblePredictor:
    """Ансамбль моделей с адаптивным взвешиванием"""

    def __init__(
        self,
        config: Dict,
        base_predictors: Dict[str, Any],
        method: EnsembleMethod = EnsembleMethod.WEIGHTED_AVERAGE,
        min_agreement: float = 0.6,
    ):
        self.config = config
        self.base_predictors = base_predictors
        self.method = method
        self.min_agreement = min_agreement
        self.event_bus = get_event_bus()

        # Веса моделей (инициализация равномерная)
        self.weights = {
            model_id: ModelWeight(
                model_id, weight=1.0 / len(base_predictors)
            )
            for model_id in base_predictors
        }

        # Circuit breakers для отдельных моделей
        self.circuit_breakers = {
            model_id: CircuitBreaker(
                failure_threshold=3, recovery_timeout=60.0
            )
            for model_id in base_predictors
        }

        # Статистика
        self._stats = {
            "predictions": 0,
            "ensemble_confidence": [],
            "model_contributions": {mid: 0 for mid in base_predictors},
        }

    @run_in_domain(ThreadDomain.ML_INFERENCE)
    async def predict(
        self, symbol: str, features: np.ndarray
    ) -> Dict[str, Any]:
        """
        Ensemble-предсказание с агрегацией результатов.
        """
        predictions = []
        confidences = []
        active_models = []

        # Параллельный запрос ко всем моделям
        tasks = []
        for model_id, predictor in self.base_predictors.items():
            tasks.append(
                self._predict_with_circuit(
                    model_id, predictor, symbol, features
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Обработка результатов
        for model_id, result in zip(self.base_predictors.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"Model {model_id} failed: {result}")
                continue

            pred, conf = result
            predictions.append(pred)
            confidences.append(conf)
            active_models.append(model_id)
            self._stats["model_contributions"][model_id] += 1

        if not predictions:
            return {"prediction": 0.5, "confidence": 0.0, "fallback": True}

        # Агрегация
        if self.method == EnsembleMethod.WEIGHTED_AVERAGE:
            prediction, confidence = self._weighted_average(
                predictions, confidences, active_models
            )
        elif self.method == EnsembleMethod.MAJORITY_VOTE:
            prediction, confidence = self._majority_vote(
                predictions, confidences
            )
        elif self.method == EnsembleMethod.BAYESIAN_AVERAGE:
            prediction, confidence = self._bayesian_average(
                predictions, confidences, active_models
            )
        else:  # STACKING
            prediction, confidence = await self._stacking_predict(
                predictions, confidences, symbol
            )

        # Расчёт согласия моделей
        agreement = self._calculate_agreement(predictions)

        # Статистика
        self._stats["predictions"] += 1
        self._stats["ensemble_confidence"].append(confidence)

        return {
            "prediction": float(np.clip(prediction, 0.0, 1.0)),
            "confidence": float(confidence),
            "agreement": float(agreement),
            "active_models": len(active_models),
            "model_weights": {
                mid: self.weights[mid].adaptive_weight()
                for mid in active_models
            },
        }

    async def _predict_with_circuit(
        self,
        model_id: str,
        predictor,
        symbol: str,
        features: np.ndarray,
    ) -> Tuple[float, float]:
        """Запрос к модели с CircuitBreaker защитой"""
        cb = self.circuit_breakers[model_id]

        if not cb.can_execute():
            raise RuntimeError(f"Circuit breaker open for {model_id}")

        try:
            if hasattr(predictor, "predict"):
                result = await predictor.predict(symbol, features)
                if isinstance(result, (tuple, list)):
                    return result[0], result[1] if len(result) > 1 else 0.5
                return float(result), 0.5
            else:
                result = predictor.predict(features.reshape(1, -1))[0]
                cb.record_success()
                return float(np.clip(result, 0, 1)), 0.5
        except Exception as e:
            cb.record_failure()
            raise

    def _weighted_average(
        self,
        predictions: List[float],
        confidences: List[float],
        active_models: List[str],
    ) -> Tuple[float, float]:
        """Взвешенное среднее с учётом весов моделей и их уверенности"""
        weights = np.array(
            [
                self.weights[mid].adaptive_weight() * conf
                for mid, conf in zip(active_models, confidences)
            ]
        )
        weights = weights / (weights.sum() + 1e-8)

        prediction = np.average(predictions, weights=weights)
        confidence = np.average(confidences, weights=weights)
        return prediction, confidence

    def _majority_vote(
        self, predictions: List[float], confidences: List[float]
    ) -> Tuple[float, float]:
        """Голосование большинством с порогом"""
        votes = [1 if p > 0.5 else 0 for p in predictions]
        buy_votes = sum(votes)
        total = len(votes)

        if buy_votes / total >= self.min_agreement:
            return 0.8, np.mean(
                [c for v, c in zip(votes, confidences) if v == 1]
            )
        elif (total - buy_votes) / total >= self.min_agreement:
            return 0.2, np.mean(
                [c for v, c in zip(votes, confidences) if v == 0]
            )
        else:
            return 0.5, 0.1

    def _bayesian_average(
        self,
        predictions: List[float],
        confidences: List[float],
        active_models: List[str],
    ) -> Tuple[float, float]:
        """Байесовское усреднение с учётом априорной точности моделей"""
        priors = np.array(
            [
                (
                    np.mean(self.weights[mid].accuracy_history[-20:])
                    if len(self.weights[mid].accuracy_history) >= 5
                    else 0.5
                )
                for mid in active_models
            ]
        )

        posteriors = priors * np.array(confidences)
        posteriors = posteriors / (posteriors.sum() + 1e-8)

        prediction = np.average(predictions, weights=posteriors)
        confidence = np.average(confidences, weights=posteriors)
        return prediction, confidence

    async def _stacking_predict(
        self,
        predictions: List[float],
        confidences: List[float],
        symbol: str,
    ) -> Tuple[float, float]:
        """Stacking: мета-модель на предсказаниях базовых моделей"""
        return np.mean(predictions), np.mean(confidences)

    def _calculate_agreement(self, predictions: List[float]) -> float:
        """Расчёт степени согласия моделей (0.0 ... 1.0)"""
        if len(predictions) < 2:
            return 1.0
        std = np.std(predictions)
        return max(0.0, min(1.0, 1.0 - std / 0.25))

    def record_outcome(
        self, symbol: str, predicted: float, actual_outcome: float
    ):
        """Запись фактического исхода для обучения весов"""
        correct = (predicted > 0.5) == (actual_outcome > 0)

        for model_id in self.base_predictors:
            if model_id in self.weights:
                self.weights[model_id].accuracy_history.append(
                    1.0 if correct else 0.0
                )
                if len(self.weights[model_id].accuracy_history) > 100:
                    self.weights[
                        model_id
                    ].accuracy_history = self.weights[
                        model_id
                    ].accuracy_history[
                        -50:
                    ]

    def get_stats(self) -> Dict:
        """Статистика ансамбля"""
        avg_conf = (
            np.mean(self._stats["ensemble_confidence"][-100:])
            if self._stats["ensemble_confidence"]
            else 0
        )
        return {
            **self._stats,
            "avg_confidence": round(avg_conf, 3),
            "method": self.method.name,
            "n_models": len(self.base_predictors),
        }
