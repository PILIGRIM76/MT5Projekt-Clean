# -*- coding: utf-8 -*-
"""
src/ml/predictors/lstm_predictor.py — Адаптер для PyTorch LSTM моделей

Оборачивает SimpleLSTM архитектуры в унифицированный интерфейс BasePredictor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import torch

from src.ml.predictors.base import BasePredictor, PredictionResult

logger = logging.getLogger(__name__)


class LSTMPredictor(BasePredictor):
    """
    Предиктор для LSTM моделей (PyTorch).

    Поддерживает:
    - Загрузку .pt/.pth файлов
    - Автоматическое определение device (cuda/cpu)
    - Постобработку: сигнал по порогу, confidence из sigmoid
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        scaler_path: Optional[Path] = None,
        metadata_path: Optional[Path] = None,
        device: str = "auto",
        threshold: float = 0.5,
        sequence_length: int = 60,
    ):
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        super().__init__(
            model_path=model_path,
            scaler_path=scaler_path,
            metadata_path=metadata_path,
            device=device,
        )
        self.threshold = threshold
        self.sequence_length = sequence_length

    @property
    def model_type(self) -> str:
        return "LSTM"

    def _load_model(self) -> None:
        """Загружает LSTM модель из .pt файла."""
        if not self.model_path or not self.model_path.exists():
            raise FileNotFoundError(f"LSTM модель не найдена: {self.model_path}")

        checkpoint = torch.load(self.model_path, map_location=self.device, weights_only=False)

        # Поддержка разных форматов сохранения
        if isinstance(checkpoint, dict):
            # Формат: {'model_state_dict': ..., 'input_dim': ..., ...}
            state_dict = checkpoint.get("model_state_dict", checkpoint)
            input_dim = checkpoint.get("input_dim")
            hidden_dim = checkpoint.get("hidden_dim", 64)
            num_layers = checkpoint.get("num_layers", 2)

            # Пытаемся импортировать архитектуру
            try:
                from src.ml.architectures import SimpleLSTM

                self.model = SimpleLSTM(
                    input_dim=input_dim or self.metadata.get("input_dim", 20),
                    hidden_dim=hidden_dim,
                    num_layers=num_layers,
                    output_dim=1,
                )
            except ImportError:
                logger.warning("[LSTM] Не удалось импортировать SimpleLSTM, создаём минимальную модель")
                self.model = self._create_minimal_lstm(input_dim or 20)

            self.model.load_state_dict(state_dict)
        else:
            # Прямой state_dict
            self.model = self._create_minimal_lstm(20)
            self.model.load_state_dict(checkpoint)

        self.model.to(self.device)
        self.model.eval()
        logger.info(f"[LSTM] Модель загружена на {self.device}")

    def _create_minimal_lstm(self, input_dim: int) -> torch.nn.Module:
        """Создаёт минимальную LSTM для загрузки state_dict."""
        import torch.nn as nn

        class MinimalLSTM(nn.Module):
            def __init__(self, inp_dim: int):
                super().__init__()
                self.lstm = nn.LSTM(input_size=inp_dim, hidden_size=64, num_layers=2, batch_first=True)
                self.dropout = nn.Dropout(0.1)
                self.fc = nn.Linear(64, 1)

            def forward(self, x):
                # Clamp input
                x = torch.clamp(x, -10, 10)
                h_lstm, _ = self.lstm(x)
                # Берём последний временной шаг
                last_hidden = h_lstm[:, -1, :]
                out = self.dropout(last_hidden)
                out = self.fc(out)
                return torch.sigmoid(out)

        return MinimalLSTM(input_dim)

    def predict(self, data: np.ndarray) -> PredictionResult:
        """
        Предсказание LSTM.

        Args:
            data: Входные данные формы (seq_len, n_features) или (1, seq_len, n_features)

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

        # Подготовка данных
        data = self._preprocess(data)

        # Инференс
        with torch.inference_mode():
            tensor = torch.FloatTensor(data).unsqueeze(0).to(self.device)  # (1, seq_len, features)
            output = self.model(tensor)
            raw_value = output.squeeze().cpu().item()

        # Постобработка
        signal, confidence = self._postprocess(raw_value)

        return PredictionResult(
            signal=signal,
            confidence=confidence,
            probability={"BUY": max(raw_value, 0.0), "SELL": max(1.0 - raw_value, 0.0)},
            raw_output=raw_value,
            model_type=self.model_type,
            metadata={
                "device": self.device,
                "input_shape": data.shape,
            },
        )

    def _preprocess(self, data: np.ndarray) -> np.ndarray:
        """Предобработка: масштабирование и проверка формы."""
        # Скалирование
        if self.scaler is not None and data.ndim == 2:
            data = self.scaler.transform(data)

        # Добавляем batch dimension если нужно
        if data.ndim == 1:
            data = data.reshape(1, -1)
        if data.ndim == 2 and data.shape[0] < self.sequence_length:
            # Padding если последовательность короче
            pad_len = self.sequence_length - data.shape[0]
            data = np.pad(data, ((pad_len, 0), (0, 0)), mode="edge")

        return data

    def _postprocess(self, raw_value: float) -> tuple[int, float]:
        """Преобразует сырой вывод в сигнал и confidence."""
        # raw_value уже в [0, 1] (sigmoid)
        if raw_value > self.threshold + 0.1:
            signal = 1  # BUY
            confidence = min((raw_value - self.threshold) * 5, 1.0)
        elif raw_value < self.threshold - 0.1:
            signal = -1  # SELL
            confidence = min((self.threshold - raw_value) * 5, 1.0)
        else:
            signal = 0  # HOLD
            confidence = 1.0 - abs(raw_value - self.threshold) * 5

        confidence = max(0.0, min(1.0, confidence))
        return signal, confidence

    def _save_model(self, path: Path) -> None:
        """Сохраняет модель."""
        if self.model is None:
            raise ValueError("Модель не загружена")
        torch.save(
            {
                "model_state_dict": self.model.state_dict(),
                "threshold": self.threshold,
                "sequence_length": self.sequence_length,
            },
            path,
        )
