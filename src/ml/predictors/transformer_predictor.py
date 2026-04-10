# -*- coding: utf-8 -*-
"""
src/ml/predictors/transformer_predictor.py — Адаптер для PyTorch Transformer моделей

Оборачивает TimeSeriesTransformer в унифицированный интерфейс BasePredictor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import torch

from src.ml.predictors.base import BasePredictor, PredictionResult

logger = logging.getLogger(__name__)


class TransformerPredictor(BasePredictor):
    """
    Предиктор для Transformer моделей (PyTorch).

    Поддерживает:
    - Загрузку .pt/.pth файлов
    - Автоматическое определение device
    - Positional encoding
    - Постобработку для сигналов BUY/SELL/HOLD
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
        return "Transformer"

    def _load_model(self) -> None:
        """Загружает Transformer модель из .pt файла."""
        if not self.model_path or not self.model_path.exists():
            raise FileNotFoundError(f"Transformer модель не найдена: {self.model_path}")

        checkpoint = torch.load(self.model_path, map_location=self.device, weights_only=False)

        if isinstance(checkpoint, dict):
            state_dict = checkpoint.get("model_state_dict", checkpoint)
            input_dim = checkpoint.get("input_dim")
            d_model = checkpoint.get("d_model", 64)
            nhead = checkpoint.get("nhead", 4)

            try:
                from src.ml.architectures import TimeSeriesTransformer

                self.model = TimeSeriesTransformer(
                    input_dim=input_dim or self.metadata.get("input_dim", 20),
                    d_model=d_model,
                    nhead=nhead,
                )
            except ImportError:
                logger.warning("[Transformer] Не удалось импортировать TimeSeriesTransformer")
                self.model = self._create_minimal_transformer(input_dim or 20)

            self.model.load_state_dict(state_dict)
        else:
            self.model = self._create_minimal_transformer(20)
            self.model.load_state_dict(checkpoint)

        self.model.to(self.device)
        self.model.eval()
        logger.info(f"[Transformer] Модель загружена на {self.device}")

    def _create_minimal_transformer(self, input_dim: int) -> torch.nn.Module:
        """Создаёт минимальный Transformer для загрузки state_dict."""
        import torch.nn as nn

        class PositionalEncoding(nn.Module):
            def __init__(self, d_model: int, max_len: int = 5000):
                super().__init__()
                pe = torch.zeros(max_len, d_model)
                position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
                div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
                pe[:, 0::2] = torch.sin(position * div_term)
                pe[:, 1::2] = torch.cos(position * div_term)
                self.register_buffer("pe", pe.unsqueeze(0))

            def forward(self, x):
                return x + self.pe[:, : x.size(1), :]

        class MinimalTransformer(nn.Module):
            def __init__(self, inp_dim: int):
                super().__init__()
                d_model = 64
                self.encoder = nn.Linear(inp_dim, d_model)
                self.pos_encoder = PositionalEncoding(d_model)
                encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=4, dim_feedforward=128, batch_first=True)
                self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
                self.decoder = nn.Linear(d_model, 1)

            def forward(self, x):
                x = torch.clamp(x, -10, 10)
                x = self.encoder(x) * np.sqrt(x.size(-1))
                x = self.pos_encoder(x)
                x = self.transformer_encoder(x)
                # Берём последний токен
                last_token = x[:, -1, :]
                out = self.decoder(last_token)
                return torch.sigmoid(out)

        return MinimalTransformer(input_dim)

    def predict(self, data: np.ndarray) -> PredictionResult:
        """
        Предсказание Transformer.

        Args:
            data: Входные данные формы (seq_len, n_features)

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

        with torch.inference_mode():
            tensor = torch.FloatTensor(data).unsqueeze(0).to(self.device)
            output = self.model(tensor)
            raw_value = output.squeeze().cpu().item()

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
        if self.scaler is not None and data.ndim == 2:
            data = self.scaler.transform(data)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        if data.ndim == 2 and data.shape[0] < self.sequence_length:
            pad_len = self.sequence_length - data.shape[0]
            data = np.pad(data, ((pad_len, 0), (0, 0)), mode="edge")
        return data

    def _postprocess(self, raw_value: float) -> tuple[int, float]:
        if raw_value > self.threshold + 0.1:
            signal = 1
            confidence = min((raw_value - self.threshold) * 5, 1.0)
        elif raw_value < self.threshold - 0.1:
            signal = -1
            confidence = min((self.threshold - raw_value) * 5, 1.0)
        else:
            signal = 0
            confidence = 1.0 - abs(raw_value - self.threshold) * 5
        confidence = max(0.0, min(1.0, confidence))
        return signal, confidence

    def _save_model(self, path: Path) -> None:
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
