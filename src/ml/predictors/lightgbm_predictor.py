# -*- coding: utf-8 -*-
"""
src/ml/predictors/lightgbm_predictor.py — Адаптер для LightGBM моделей

Оборачивает LightGBM (joblib) в унифицированный интерфейс BasePredictor.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from src.ml.predictors.base import BasePredictor, PredictionResult

logger = logging.getLogger(__name__)


class LightGBMPredictor(BasePredictor):
    """
    Предиктор для LightGBM моделей.

    Поддерживает:
    - Загрузку .joblib файлов (модель + скалер)
    - predict() — классификация направления
    - predict_proba() — вероятности классов
    - Автоматическое определение signal/confidence
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        metadata_path: Optional[Path] = None,
        threshold: float = 0.5,
    ):
        super().__init__(
            model_path=model_path,
            scaler_path=scaler_path,
            metadata_path=metadata_path,
        )
        self.threshold = threshold

    @property
    def model_type(self) -> str:
        return "LightGBM"

    def _load_model(self) -> None:
        """Загружает LightGBM модель из .joblib файла."""
        if not self.model_path or not self.model_path.exists():
            raise FileNotFoundError(f"LightGBM модель не найдена: {self.model_path}")

        import joblib

        self.model = joblib.load(self.model_path)

        # Проверка что модель поддерживает predict_proba
        if not hasattr(self.model, "predict_proba"):
            logger.warning("[LightGBM] Модель не поддерживает predict_proba, confidence будет снижен")

        logger.info(f"[LightGBM] Модель загружена: {self.model_path}")

    def predict(self, data: np.ndarray) -> PredictionResult:
        """
        Предсказание LightGBM.

        Args:
            data: Входные данные формы (n_features,) или (1, n_features)

        Returns:
            PredictionResult с сигналом BUY/SELL/HOLD
        """
        if not self._is_loaded:
            self.load()

        if self.model is None:
            return PredictionResult(
                signal=0,
                confidence=0.0,
                model_type=self.model_type,
                metadata={"error": "Model not loaded"},
            )

        data = self._preprocess(data)

        # ИСПРАВЛЕНИЕ: Восстанавливаем DataFrame с именами признаков для LightGBM
        # чтобы избежать предупреждения "X does not have valid feature names"
        data_for_predict = data
        try:
            # Проверяем есть ли у модели сохранённые имена признаков
            if hasattr(self.model, "feature_name_"):
                feature_names = self.model.feature_name_
            elif hasattr(self.model, "_feature_name"):
                feature_names = self.model._feature_name
            else:
                feature_names = None

            if feature_names and data.ndim == 2 and len(feature_names) == data.shape[1]:
                # Модель была обучена с именами признаков — восстанавливаем DataFrame
                import pandas as pd

                data_for_predict = pd.DataFrame(data, columns=feature_names)
                logger.debug(f"[LightGBM] ✅ DataFrame восстановлен с {len(feature_names)} признаками")
        except Exception as e:
            logger.debug(f"[LightGBM] Не удалось восстановить DataFrame (не критично): {e}")
            data_for_predict = data  # Fallback к numpy

        # Основной вывод — используем DataFrame если удалось восстановить
        raw_prediction = self.model.predict(
            data_for_predict.reshape(1, -1) if hasattr(data_for_predict, "values") else data_for_predict
        )[0]

        # Вероятности (если доступны)
        proba = None
        if hasattr(self.model, "predict_proba"):
            try:
                proba = self.model.predict_proba(
                    data_for_predict.reshape(1, -1) if hasattr(data_for_predict, "values") else data_for_predict
                )[0]
            except Exception:
                proba = None

        # Постобработка
        signal, confidence = self._postprocess(raw_prediction, proba)

        # Формируем словарь вероятностей
        probability = {}
        if proba is not None and len(proba) >= 2:
            # Для бинарной классификации: [P(class_0), P(class_1)]
            probability = {
                "BUY": float(proba[-1]),  # Вероятность класса 1 (рост)
                "SELL": float(proba[0]),  # Вероятность класса 0 (падение)
            }
        else:
            probability = {"BUY": float(max(raw_prediction, 0.0)), "SELL": float(max(1.0 - raw_prediction, 0.0))}

        return PredictionResult(
            signal=signal,
            confidence=confidence,
            probability=probability,
            raw_output=raw_prediction,
            model_type=self.model_type,
            metadata={
                "n_features": data.shape[-1] if data.ndim > 0 else 0,
            },
        )

    def _preprocess(self, data: np.ndarray) -> np.ndarray:
        """Предобработка: масштабирование, проверка NaN."""
        if self.scaler is not None:
            original_shape = data.shape
            if data.ndim == 1:
                data = data.reshape(1, -1)
            data = self.scaler.transform(data)
            if original_shape == data.shape:
                data = data.flatten()

        # Замена NaN/inf
        data = np.nan_to_num(data, nan=0.0, posinf=10.0, neginf=-10.0)
        return data

    def _postprocess(self, raw_prediction, proba) -> tuple[int, float]:
        """
        Преобразует вывод модели в сигнал и confidence.

        Для бинарной классификации:
        - raw_prediction: 0 или 1 (класс)
        - proba: [P(class_0), P(class_1)]
        """
        if proba is not None and len(proba) >= 2:
            prob_class_1 = float(proba[-1])
            if prob_class_1 > self.threshold + 0.1:
                signal = 1  # BUY
                confidence = min((prob_class_1 - self.threshold) * 5, 1.0)
            elif prob_class_1 < self.threshold - 0.1:
                signal = -1  # SELL
                confidence = min((self.threshold - prob_class_1) * 5, 1.0)
            else:
                signal = 0  # HOLD
                confidence = 1.0 - abs(prob_class_1 - self.threshold) * 5
        else:
            # Fallback: используем raw_prediction
            if raw_prediction > self.threshold:
                signal = 1
                confidence = min(abs(raw_prediction - self.threshold) * 5, 1.0)
            elif raw_prediction < (1 - self.threshold):
                signal = -1
                confidence = min(abs(raw_prediction - (1 - self.threshold)) * 5, 1.0)
            else:
                signal = 0
                confidence = 0.3

        confidence = max(0.0, min(1.0, confidence))
        return signal, confidence

    def _save_model(self, path: Path) -> None:
        """Сохраняет модель в joblib."""
        if self.model is None:
            raise ValueError("Модель не загружена")

        import joblib

        joblib.dump(self.model, path)

        # Сохраняем метаданные отдельно
        if self.metadata:
            meta_path = path.with_suffix(".metadata.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=2, ensure_ascii=False)

    def get_feature_importance(self, top_n: int = 20) -> list[tuple[str, float]]:
        """
        Возвращает важность признаков.

        Returns:
            Список (feature_name, importance) отсортированный по убыванию
        """
        if self.model is None or not hasattr(self.model, "feature_importances_"):
            return []

        importances = self.model.feature_importances_
        names = self.get_feature_names()

        if not names:
            names = [f"feature_{i}" for i in range(len(importances))]

        feature_imp = list(zip(names[: len(importances)], importances))
        feature_imp.sort(key=lambda x: x[1], reverse=True)
        return feature_imp[:top_n]
