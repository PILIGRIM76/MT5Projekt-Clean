# -*- coding: utf-8 -*-
"""
src/ml/predictive_engine.py — Унифицированный движок предсказаний

Управляет всеми типами моделей (LSTM, Transformer, LightGBM) через
единый интерфейс predict(). Автоматически выбирает лучшую модель
и обеспечивает fallback при ошибках.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from src.core.config_models import Settings
from src.ml.model_paths import ModelPathConfig
from src.ml.predictors.base import PredictionResult
from src.ml.predictors.lightgbm_predictor import LightGBMPredictor
from src.ml.predictors.lstm_predictor import LSTMPredictor
from src.ml.predictors.transformer_predictor import TransformerPredictor

logger = logging.getLogger(__name__)

# Маппинг форматов моделей → классы предикторов
PREDICTOR_REGISTRY = {
    "pytorch": {"lstm": LSTMPredictor, "transformer": TransformerPredictor},
    "keras": {},  # Можно добавить Keras адапптер
    "onnx": {},  # Можно добавить ONNX адаптер
    "joblib": {"lightgbm": LightGBMPredictor},
}


class PredictiveEngine:
    """
    Центральный движок предсказаний.

    Поддерживает:
    - Множественные модели на символ (LSTM + Transformer + LightGBM)
    - Автоматический выбор лучшей модели
    - Fallback цепочку при ошибках
    - Ensembled predictions (взвешенное голосование)
    """

    def __init__(self, config: Settings):
        self.config = config
        self.paths = ModelPathConfig(config)

        # Активные предикторы: {symbol: {model_type: Predictor}}
        self._predictors: Dict[str, Dict[str, Any]] = {}

        # Веса для ensemble: {model_type: weight}
        self._ensemble_weights = {
            "LSTM": 0.35,
            "Transformer": 0.35,
            "LightGBM": 0.30,
        }

        # Порог для HOLD
        self._hold_threshold = getattr(config, "ENTRY_THRESHOLD", 0.01)

        logger.info(f"[PredictiveEngine] Инициализирован. Модель: {self.paths.model_dir}")

    # ===================================================================
    # Управление моделями
    # ===================================================================

    def load_model_for_symbol(
        self,
        symbol: str,
        model_types: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """
        Загружает модели для символа.

        Args:
            symbol: Торговый символ
            model_types: Список типов ['LSTM', 'Transformer', 'LightGBM'].
                         Если None — загружает все доступные.

        Returns:
            {model_type: success}
        """
        if model_types is None:
            model_types = list(self._ensemble_weights.keys())

        if symbol not in self._predictors:
            self._predictors[symbol] = {}

        results = {}
        for mt in model_types:
            try:
                predictor = self._create_predictor(symbol, mt)
                if predictor and predictor.load():
                    self._predictors[symbol][mt] = predictor
                    results[mt] = True
                    logger.info(f"[PredictiveEngine] {mt} для {symbol} загружена")
                else:
                    results[mt] = False
                    logger.warning(f"[PredictiveEngine] {mt} для {symbol} не загружена")
            except Exception as e:
                results[mt] = False
                logger.error(f"[PredictiveEngine] Ошибка загрузки {mt} для {symbol}: {e}")

        return results

    def unload_all(self) -> None:
        """Выгружает все модели."""
        for symbol, predictors in self._predictors.items():
            for mt, pred in predictors.items():
                try:
                    pred.unload()
                except Exception as e:
                    logger.debug(f"[PredictiveEngine] Ошибка выгрузки {mt}/{symbol}: {e}")
        self._predictors.clear()
        logger.info("[PredictiveEngine] Все модели выгружены")

    # ===================================================================
    # Предсказание
    # ===================================================================

    def predict(
        self,
        symbol: str,
        data: np.ndarray,
        strategy: str = "ensemble",  # ensemble, best, lightgbm, lstm, transformer
    ) -> PredictionResult:
        """
        Выполняет предсказание.

        Args:
            symbol: Торговый символ
            data: Входные данные (seq_len, n_features) или (n_features,)
            strategy:
                - 'ensemble': Взвешенное голосование всех моделей
                - 'best': Лучшая модель по весу
                - 'lightgbm'/'lstm'/'transformer': Конкретная модель

        Returns:
            PredictionResult
        """
        if symbol not in self._predictors or not self._predictors[symbol]:
            # Fallback: загружаем LightGBM
            logger.info(f"[PredictiveEngine] Автозагрузка LightGBM для {symbol}")
            self.load_model_for_symbol(symbol, ["LightGBM"])

        if symbol not in self._predictors or not self._predictors[symbol]:
            return PredictionResult(
                signal=0,
                confidence=0.0,
                model_type="none",
                metadata={"error": f"No models for {symbol}"},
            )

        if strategy == "ensemble":
            return self._predict_ensemble(symbol, data)
        elif strategy == "best":
            return self._predict_best(symbol, data)
        elif strategy in self._predictors.get(symbol, {}):
            return self._predict_single(symbol, strategy, data)
        else:
            # Fallback на первую доступную
            first_type = list(self._predictors[symbol].keys())[0]
            logger.warning(f"[PredictiveEngine] Fallback на {first_type}")
            return self._predict_single(symbol, first_type, data)

    def _predict_ensemble(self, symbol: str, data: np.ndarray) -> PredictionResult:
        """Взвешенное голосование моделей."""
        predictors = self._predictors.get(symbol, {})
        if not predictors:
            return PredictionResult(signal=0, confidence=0.0, model_type="ensemble")

        weighted_signal = 0.0
        total_weight = 0.0
        individual_results = {}

        for mt, predictor in predictors.items():
            try:
                result = predictor.predict(data)
                weight = self._ensemble_weights.get(mt, 0.2)
                weighted_signal += result.signal * result.confidence * weight
                total_weight += result.confidence * weight
                individual_results[mt] = result
            except Exception as e:
                logger.warning(f"[PredictiveEngine] {mt} ошибка в ensemble: {e}")

        if total_weight > 0:
            avg_signal = weighted_signal / total_weight
        else:
            avg_signal = 0.0

        # Определяем финальный сигнал
        if avg_signal > self._hold_threshold:
            final_signal = 1
        elif avg_signal < -self._hold_threshold:
            final_signal = -1
        else:
            final_signal = 0

        confidence = min(abs(avg_signal) * 3, 1.0)

        return PredictionResult(
            signal=final_signal,
            confidence=confidence,
            probability={"BUY": max(avg_signal, 0.0), "SELL": max(-avg_signal, 0.0)},
            raw_output=avg_signal,
            model_type=f"ensemble({'+'.join(predictors.keys())})",
            metadata={
                "individual_results": {k: str(v) for k, v in individual_results.items()},
                "total_weight": total_weight,
            },
        )

    def _predict_best(self, symbol: str, data: np.ndarray) -> PredictionResult:
        """Предсказание лучшей моделью по весу."""
        predictors = self._predictors.get(symbol, {})
        if not predictors:
            return PredictionResult(signal=0, confidence=0.0, model_type="best")

        best_type = max(predictors.keys(), key=lambda mt: self._ensemble_weights.get(mt, 0))
        return self._predict_single(symbol, best_type, data)

    def _predict_single(self, symbol: str, model_type: str, data: np.ndarray) -> PredictionResult:
        """Предсказание одной моделью."""
        predictor = self._predictors.get(symbol, {}).get(model_type)
        if predictor is None:
            return PredictionResult(
                signal=0,
                confidence=0.0,
                model_type=model_type,
                metadata={"error": f"Predictor {model_type} not found for {symbol}"},
            )

        try:
            return predictor.predict(data)
        except Exception as e:
            logger.error(f"[PredictiveEngine] Ошибка {model_type}.predict: {e}")
            return PredictionResult(
                signal=0,
                confidence=0.0,
                model_type=model_type,
                metadata={"error": str(e)},
            )

    # ===================================================================
    # Управление весами
    # ===================================================================

    def set_weight(self, model_type: str, weight: float) -> None:
        """Устанавливает вес модели для ensemble."""
        if model_type in self._ensemble_weights:
            self._ensemble_weights[model_type] = weight
            logger.info(f"[PredictiveEngine] Вес {model_type} = {weight}")

    def get_weights(self) -> Dict[str, float]:
        return dict(self._ensemble_weights)

    # ===================================================================
    # Утилиты
    # ===================================================================

    def _create_predictor(self, symbol: str, model_type: str):
        """Создаёт предиктор нужного типа."""
        model_path = self.paths.get_model_path(symbol)
        scaler_path = self.paths.get_scaler_path(symbol)
        meta_path = self.paths.get_metadata_path(symbol)

        if model_type == "LSTM":
            return LSTMPredictor(
                model_path=model_path.with_suffix(".pt"),
                scaler_path=scaler_path,
                metadata_path=meta_path,
            )
        elif model_type == "Transformer":
            return TransformerPredictor(
                model_path=model_path.with_suffix(".pt"),
                scaler_path=scaler_path,
                metadata_path=meta_path,
            )
        elif model_type == "LightGBM":
            return LightGBMPredictor(
                model_path=model_path.with_suffix(".joblib"),
                scaler_path=scaler_path,
                metadata_path=meta_path,
            )
        else:
            logger.warning(f"[PredictiveEngine] Неизвестный тип модели: {model_type}")
            return None

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус загруженных моделей."""
        status = {}
        for symbol, predictors in self._predictors.items():
            status[symbol] = {
                mt: {
                    "loaded": pred.is_loaded,
                    "metadata": pred.metadata,
                }
                for mt, pred in predictors.items()
            }
        return status

    def __repr__(self) -> str:
        n_symbols = len(self._predictors)
        n_models = sum(len(p) for p in self._predictors.values())
        return f"PredictiveEngine(symbols={n_symbols}, models={n_models})"
