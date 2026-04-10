# -*- coding: utf-8 -*-
"""
src/ml/predictors/base.py — Базовый абстрактный класс предиктора

Определяет единый интерфейс predict() для всех типов моделей.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """
    Унифицированный результат предсказания.

    Attributes:
        signal: Основной сигнал — 1 (BUY), -1 (SELL), 0 (HOLD)
        confidence: Уверенность модели [0.0, 1.0]
        probability: Распределение вероятностей {класс: вероятность}
        raw_output: Сырой вывод модели (до постобработки)
        model_type: Тип модели (LSTM, Transformer, LightGBM, ...)
        metadata: Дополнительные метаданные (время, версия, и т.д.)
    """

    signal: int  # 1=BUY, -1=SELL, 0=HOLD
    confidence: float  # [0.0, 1.0]
    probability: Dict[str, float] = field(default_factory=dict)
    raw_output: Any = None
    model_type: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_buy(self) -> bool:
        return self.signal == 1

    @property
    def is_sell(self) -> bool:
        return self.signal == -1

    @property
    def is_hold(self) -> bool:
        return self.signal == 0

    @property
    def signal_name(self) -> str:
        return {1: "BUY", -1: "SELL", 0: "HOLD"}.get(self.signal, "UNKNOWN")

    def __repr__(self) -> str:
        return (
            f"PredictionResult(signal={self.signal_name}, " f"confidence={self.confidence:.3f}, " f"model={self.model_type})"
        )


class BasePredictor(ABC):
    """
    Абстрактный базовый класс для всех предикторов.

    Все модели (LSTM, Transformer, LightGBM, RL, ...) должны
    наследовать этот класс и реализовать predict().
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        metadata_path: Optional[Path] = None,
        device: str = "cpu",
    ):
        self.model_path = model_path
        self.scaler_path = scaler_path
        self.metadata_path = metadata_path
        self.device = device
        self.model = None
        self.scaler = None
        self.metadata: Dict[str, Any] = {}
        self._is_loaded = False

    @abstractmethod
    def predict(self, data: np.ndarray) -> PredictionResult:
        """
        Выполняет предсказание.

        Args:
            data: Входные данные формы (seq_len, n_features) или (n_samples, n_features)

        Returns:
            PredictionResult — унифицированный результат
        """
        ...

    def predict_batch(self, data_batch: np.ndarray) -> list[PredictionResult]:
        """
        Выполняет пакетное предсказание.

        Args:
            data_batch: Массив формы (batch_size, seq_len, n_features) или (batch_size, n_features)

        Returns:
            Список PredictionResult для каждого сэмпла
        """
        results = []
        for i in range(len(data_batch)):
            result = self.predict(data_batch[i])
            results.append(result)
        return results

    def load(self) -> bool:
        """
        Загружает модель, скалер и метаданные.

        Returns:
            True если загрузка успешна
        """
        if self._is_loaded:
            return True

        try:
            self._load_model()
            self._load_scaler()
            self._load_metadata()
            self._is_loaded = True
            logger.info(f"[{self.model_type}] Модель загружена: {self.model_path}")
            return True
        except Exception as e:
            logger.error(f"[{self.model_type}] Ошибка загрузки: {e}")
            return False

    def unload(self) -> None:
        """Выгружает модель из памяти."""
        if self.model is not None:
            del self.model
            self.model = None
        if self.scaler is not None:
            del self.scaler
            self.scaler = None
        self._is_loaded = False
        logger.info(f"[{self.model_type}] Модель выгружена")

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @property
    @abstractmethod
    def model_type(self) -> str:
        """Возвращает тип модели (строка)."""
        ...

    @abstractmethod
    def _load_model(self) -> None:
        """Загружает модель из файла."""
        ...

    def _load_scaler(self) -> None:
        """Загружает скалер (если существует)."""
        if self.scaler_path and self.scaler_path.exists():
            try:
                import joblib

                self.scaler = joblib.load(self.scaler_path)
                logger.debug(f"[{self.model_type}] Скалер загружен: {self.scaler_path}")
            except Exception as e:
                logger.warning(f"[{self.model_type}] Не удалось загрузить скалер: {e}")
                self.scaler = None

    def _load_metadata(self) -> None:
        """Загружает метаданные модели (если существуют)."""
        if self.metadata_path and self.metadata_path.exists():
            try:
                import json

                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                logger.debug(f"[{self.model_type}] Метаданные загружены: {self.metadata_path}")
            except Exception as e:
                logger.warning(f"[{self.model_type}] Не удалось загрузить метаданные: {e}")
                self.metadata = {}

    def save(self, path: Path) -> None:
        """
        Сохраняет модель.

        Args:
            path: Путь для сохранения
        """
        self._save_model(path)
        logger.info(f"[{self.model_type}] Модель сохранена: {path}")

    @abstractmethod
    def _save_model(self, path: Path) -> None:
        """Сохраняет модель в файл."""
        ...

    def get_feature_names(self) -> list[str]:
        """Возвращает список имён признаков из метаданных."""
        return self.metadata.get("feature_names", [])

    def get_input_shape(self) -> Optional[tuple]:
        """Возвращает ожидаемую форму входных данных."""
        if "input_shape" in self.metadata:
            return tuple(self.metadata["input_shape"])
        return None

    def __repr__(self) -> str:
        status = "loaded" if self._is_loaded else "not loaded"
        return f"{self.__class__.__name__}(path={self.model_path}, status={status})"
