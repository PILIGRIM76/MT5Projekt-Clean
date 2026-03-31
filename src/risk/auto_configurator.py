# src/risk/auto_configurator.py

import logging
from typing import Optional

import pandas as pd

from src.core.config_models import Settings
from src.utils.analysis_utils import analyze_volatility

logger = logging.getLogger(__name__)


def _analyze_volatility(df: pd.DataFrame) -> Optional[float]:
    if df is None or df.empty or "ATR_14" not in df.columns:
        return None
    try:
        atr_value = df["ATR_14"].iloc[-1]
        if pd.isna(atr_value) or atr_value == 0:
            return None
        return atr_value
    except Exception as e:
        logger.error(f"Ошибка при извлечении значения ATR: {e}")
        return None


class AutoConfigurator:
    def __init__(self, base_config: Settings):
        self.base_config = base_config

    def get_dynamic_risk_settings(self, symbol: str, df: pd.DataFrame) -> dict:
        """
        Возвращает словарь с динамически скорректированными параметрами риска.
        """
        # Используем утилиту для анализа ATR
        atr = analyze_volatility(df)

        if atr is None:
            logger.warning(f"Не удалось получить ATR для {symbol}, используются базовые настройки.")
            return {}

        current_price = df["close"].iloc[-1]
        if current_price == 0:
            return {}

        # Нормализованная волатильность (в процентах)
        normalized_atr_percent = (atr / current_price) * 100

        # --- Прямой доступ к базовым атрибутам конфига ---
        base_sl_multiplier = self.base_config.STOP_LOSS_ATR_MULTIPLIER
        base_risk_percent = self.base_config.RISK_PERCENTAGE
        base_rr_ratio = self.base_config.RISK_REWARD_RATIO

        dynamic_settings = {}

        # Логика адаптации
        if normalized_atr_percent > 0.5:  # Высокая волатильность
            dynamic_settings["STOP_LOSS_ATR_MULTIPLIER"] = base_sl_multiplier * 1.2  # Расширяем SL
            dynamic_settings["RISK_PERCENTAGE"] = base_risk_percent * 0.75  # Снижаем риск
            logger.info(f"[{symbol}] Высокая волатильность ({normalized_atr_percent:.2f}%). SL расширен, риск снижен.")
        elif normalized_atr_percent < 0.1:  # Низкая волатильность
            dynamic_settings["STOP_LOSS_ATR_MULTIPLIER"] = base_sl_multiplier * 0.8  # Сужаем SL
            dynamic_settings["RISK_REWARD_RATIO"] = base_rr_ratio * 1.2  # Увеличиваем RR (для тренда)
            logger.info(f"[{symbol}] Низкая волатильность ({normalized_atr_percent:.2f}%). SL сужен, RR увеличен.")
        else:
            logger.info(f"[{symbol}] Средняя волатильность ({normalized_atr_percent:.2f}%). Используются базовые настройки.")

        return dynamic_settings
