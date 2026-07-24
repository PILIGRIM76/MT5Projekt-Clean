# src/analysis/anomaly_detector.py
import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
from torch.utils.data import DataLoader, TensorDataset

from src.core.config_models import Settings
from src.utils.torch_utils import get_torch_device

logger = logging.getLogger(__name__)


# --- 1. Определяем архитектуру автоэнкодера на PyTorch ---
class Autoencoder(nn.Module):
    """PyTorch реализация автоэнкодера."""

    def __init__(self, input_dim: int):
        super(Autoencoder, self).__init__()
        # Encoder
        self.encoder = nn.Sequential(nn.Linear(input_dim, 32), nn.ReLU(), nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 8))
        # Decoder
        self.decoder = nn.Sequential(
            nn.Linear(8, 16),
            nn.ReLU(),
            nn.Linear(16, 32),
            nn.ReLU(),
            nn.Linear(32, input_dim),
            nn.Sigmoid(),  # Sigmoid на выходе, т.к. данные нормализованы в [0, 1]
        )

    def forward(self, x):
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded


class AnomalyDetector:
    """
    Обнаруживает аномалии в рыночных данных с помощью PyTorch Autoencoder.
    """

    def __init__(self, config: Settings):
        self.config = config.anomaly_detector
        self.model: Optional[Autoencoder] = None
        self.scaler = MinMaxScaler()
        self.threshold = np.inf
        self.is_trained = False
        self.features = self.config.features
        self.device = torch.device(get_torch_device())
        logger.info(f"Детектор аномалий будет использовать устройство: {self.device}")

    def _build_model(self, input_dim: int):
        """Инициализирует модель и перемещает ее на нужное устройство."""
        self.model = Autoencoder(input_dim=input_dim).to(self.device)
        logger.info(f"Модель Autoencoder (PyTorch) построена с размерностью входа: {input_dim}")

    def train(self, df: pd.DataFrame):
        """
        Обучает автоэнкодер на "нормальных" данных и вычисляет порог аномалии.
        """
        if not self.config.enabled:
            logger.info("Детектор аномалий отключен. Обучение пропущено.")
            return

        logger.info("Начало обучения детектора аномалий (PyTorch)...")

        # Проверка наличия признаков
        if not all(feat in df.columns for feat in self.features):
            missing = [feat for feat in self.features if feat not in df.columns]
            logger.error(f"Невозможно обучить детектор аномалий. Отсутствуют признаки: {missing}")
            return

        train_data = df[self.features].dropna()
        if len(train_data) < 100:
            logger.error("Недостаточно данных для обучения детектора аномалий.")
            return

        # Подготовка данных
        scaled_data = self.scaler.fit_transform(train_data)
        train_tensor = torch.FloatTensor(scaled_data).to(self.device)
        dataset = TensorDataset(train_tensor, train_tensor)
        dataloader = DataLoader(dataset, batch_size=self.config.batch_size, shuffle=True)

        # Инициализация модели и оптимизатора
        self._build_model(input_dim=scaled_data.shape[1])
        criterion = nn.L1Loss()  # MAE Loss
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)

        # Логика EarlyStopping
        best_loss = np.inf
        patience_counter = 0
        patience = 5

        # Цикл обучения
        for epoch in range(self.config.epochs):
            for data_batch, _ in dataloader:
                recon = self.model(data_batch)
                loss = criterion(recon, data_batch)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            # # Валидация и EarlyStopping (УДАЛЕНО)
            # val_loss = loss.item()
            # if val_loss < best_loss:
            #     best_loss = val_loss
            #     patience_counter = 0
            # else:
            #     patience_counter += 1
            #
            # if patience_counter >= patience:
            #     logger.info(f"EarlyStopping сработал на эпохе {epoch + 1}")
            #     break

        # Вычисление порога
        self.model.eval()
        with torch.no_grad():
            predictions_tensor = self.model(train_tensor)
            errors_tensor = torch.mean(torch.abs(predictions_tensor - train_tensor), dim=1)
            mae = errors_tensor.cpu().numpy()

        self.threshold = np.mean(mae) + self.config.threshold_std_multiplier * np.std(mae)
        self.is_trained = True
        logger.info(f"Детектор аномалий успешно обучен. Порог ошибки восстановления: {self.threshold:.6f}")

    def predict(self, df_slice: pd.DataFrame) -> Tuple[bool, float]:
        """
        Проверяет последнюю точку данных на аномальность.
        """
        if not self.is_trained or not self.config.enabled:
            return False, 0.0

        if not all(feat in df_slice.columns for feat in self.features):
            return False, 0.0

        last_data_point = df_slice[self.features].tail(1)
        if last_data_point.isnull().values.any():
            return False, 0.0

        try:
            self.model.eval()
            with torch.no_grad():
                scaled_point = self.scaler.transform(last_data_point)
                point_tensor = torch.FloatTensor(scaled_point).to(self.device)
                prediction_tensor = self.model(point_tensor)
                error_tensor = torch.mean(torch.abs(prediction_tensor - point_tensor), dim=1)
                error = error_tensor.cpu().numpy()[0]

            is_anomaly = error > self.threshold
            if is_anomaly:
                logger.warning(f"!!! АНОМАЛИЯ ОБНАРУЖЕНА !!! Ошибка восстановления: {error:.6f} (Порог: {self.threshold:.6f})")

            return is_anomaly, float(error)

        except Exception as e:
            logger.error(f"Ошибка при предсказании аномалии: {e}")
            return False, 0.0
