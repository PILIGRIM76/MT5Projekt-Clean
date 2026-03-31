# src/data/alternative_data_provider.py
import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AlternativeDataProvider:
    """
    Имитирует получение альтернативных (нефинансовых) данных из внешних API.
    В реальной системе здесь были бы асинхронные запросы к платным сервисам.
    """

    def __init__(self):
        logger.info("Провайдер альтернативных данных инициализирован.")
        # Начальные значения для имитации временных рядов
        self._shipping_index = 1200.0
        self._oil_storage_fullness = 0.65

    async def get_alternative_metrics(self) -> Optional[pd.DataFrame]:
        """
        Асинхронно "запрашивает" и возвращает DataFrame с альтернативными данными.
        """
        logger.info("Запрос альтернативных данных (спутники, перевозки)...")
        try:
            # Имитация получения данных за последние 90 дней
            dates = pd.to_datetime(pd.date_range(end=pd.Timestamp.utcnow(), periods=90, freq="D"))

            # 1. Имитация индекса глобальных грузоперевозок (случайное блуждание)
            shipping_noise = np.random.normal(0, 1.5, size=90)
            shipping_trend = np.linspace(0, -5, 90)  # Небольшой нисходящий тренд
            shipping_values = self._shipping_index + np.cumsum(shipping_noise) + shipping_trend

            # 2. Имитация заполненности нефтяных хранилищ (синусоида + шум)
            days = np.arange(90)
            oil_seasonality = 0.1 * np.sin(2 * np.pi * days / 60)  # 2-месячный цикл
            oil_noise = np.random.normal(0, 0.02, size=90)
            oil_values = np.clip(self._oil_storage_fullness + oil_seasonality + oil_noise, 0.1, 0.95)

            df = pd.DataFrame({"shipping_index": shipping_values, "satellite_oil_storage": oil_values}, index=dates)

            # Обновляем последние значения для следующего вызова
            self._shipping_index = df["shipping_index"].iloc[-1]
            self._oil_storage_fullness = df["satellite_oil_storage"].iloc[-1]

            logger.info(
                f"Альтернативные данные успешно сгенерированы. Последние значения: "
                f"Shipping Index={self._shipping_index:.2f}, Oil Storage={self._oil_storage_fullness:.2%}"
            )

            return df

        except Exception as e:
            logger.error(f"Ошибка при получении альтернативных данных: {e}", exc_info=True)
            return None
