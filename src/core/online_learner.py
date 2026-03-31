# src/core/online_learner.py
import logging

import numpy as np
import torch
import torch.nn as nn

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class OnlineLearner:
    """
    Отвечает за дообучение моделей на основе результатов реальных сделок.
    Версия адаптирована для PyTorch.
    """

    def __init__(self, config: Settings):
        self.config_online = config.online_learning
        self.enabled = self.config_online.enabled
        self.learning_rate = self.config_online.learning_rate
        self.adjustment_factor = self.config_online.adjustment_factor
        self.max_expected_profit = self.config_online.max_expected_profit
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        if self.enabled:
            logger.info(f"Модуль онлайн-обучения (PyTorch) АКТИВИРОВАН. Устройство: {self.device}")
        else:
            logger.info("Модуль онлайн-обучения ОТКЛЮЧЕН в конфигурации.")

    def update(self, model, y_scaler, sequence: np.ndarray, entry_price: float, trade_profit: float):
        """
        Выполняет один шаг дообучения (backpropagation) для PyTorch модели.
        """
        if not self.enabled or trade_profit == 0 or not isinstance(model, nn.Module):
            if not isinstance(model, nn.Module):
                logger.warning("Онлайн-обучение пропущено: модель не является PyTorch моделью.")
            return

        try:
            logger.info(f"Запуск онлайн-обучения. Результат сделки: {trade_profit:.2f}")

            model.eval()  # Переключаем модель в режим оценки для получения прогноза
            sequence_tensor = torch.from_numpy(sequence).float().to(self.device)

            with torch.no_grad():
                last_prediction_scaled = model(sequence_tensor)
                last_prediction_unscaled = y_scaler.inverse_transform(last_prediction_scaled.cpu().numpy())[0][0]

            # --- Логика корректировки цели остается прежней ---
            new_target = last_prediction_unscaled
            if trade_profit > 0:
                win_ratio = min(trade_profit / self.max_expected_profit, 1.0)
                adjustment = (last_prediction_unscaled - entry_price) * self.adjustment_factor * (1 + win_ratio)
                new_target = last_prediction_unscaled + adjustment
                logger.info(f"Сделка прибыльная. Цель скорректирована с {last_prediction_unscaled:.5f} на {new_target:.5f}")
            else:
                loss_ratio = min(abs(trade_profit) / self.max_expected_profit, 1.0)
                new_target = last_prediction_unscaled * (1 - loss_ratio) + entry_price * loss_ratio
                logger.info(f"Сделка убыточная. Цель скорректирована с {last_prediction_unscaled:.5f} на {new_target:.5f}")

            # --- Логика дообучения для PyTorch ---
            y_target_scaled = y_scaler.transform(np.array([[new_target]]))
            y_target_tensor = torch.FloatTensor(y_target_scaled).to(self.device)

            model.train()  # Переключаем модель в режим обучения

            # Создаем оптимизатор с нужной скоростью обучения
            optimizer = torch.optim.Adam(model.parameters(), lr=self.learning_rate)
            criterion = nn.MSELoss()  # Используем MSE для дообучения

            # Один шаг градиентного спуска
            optimizer.zero_grad()
            output = model(sequence_tensor)
            loss = criterion(output, y_target_tensor)
            loss.backward()
            optimizer.step()

            logger.info(f"Шаг онлайн-обучения успешно завершен. Loss: {loss.item():.6f}")

        except Exception as e:
            logger.error(f"Ошибка в процессе онлайн-обучения (PyTorch): {e}", exc_info=True)
        finally:
            if isinstance(model, nn.Module):
                model.eval()  # Возвращаем модель в режим оценки после дообучения
