# src/analysis/market_regime_manager.py
import logging

import numpy as np
import pandas as pd

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class MarketRegimeManager:
    def __init__(self, config: Settings):
        # Используем параметры из новой модели конфигурации
        self.config = config.market_regime
        self.adx_threshold = self.config.adx_threshold
        self.volatility_threshold_high = self.config.volatility_high_percentile
        self.volatility_threshold_low = self.config.volatility_low_percentile
        self.ema_slope_threshold = self.config.ema_slope_threshold
        self.volatility_rank_window = self.config.volatility_rank_window

    def get_regime(self, df: pd.DataFrame) -> str:
        if df is None or len(df) < self.volatility_rank_window:
            logger.warning("Недостаточно данных для определения режима рынка.")
            return "Low Volatility Range"

        required_cols = ["BBU_20_2.0", "BBL_20_2.0", "BBM_20_2.0", "ATR_14", "ADX_14", "EMA_50", "close"]
        if not all(col in df.columns for col in required_cols):
            missing = [col for col in required_cols if col not in df.columns]
            logger.warning(f"Отсутствуют необходимые колонки для определения режима: {missing}")
            return "Low Volatility Range"

        try:
            last_row = df.iloc[-1]

            # --- 1. ИСПРАВЛЕННЫЙ РАСЧЕТ ВОЛАТИЛЬНОСТИ ---
            # Рассчитываем метрики как серии, а не как одно число
            bb_width_series = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]
            normalized_atr_series = df["ATR_14"] / df["close"]

            # Усредняем метрики, чтобы получить единый показатель волатильности
            combined_volatility = (bb_width_series + normalized_atr_series) / 2

            # Рассчитываем ранг последнего значения относительно `volatility_rank_window` прошлых значений
            volatility_percentile = (
                combined_volatility.rolling(window=self.volatility_rank_window)
                .apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
                .iloc[-1]
            )
            # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

            # --- 2. Расчет метрик силы тренда ---
            adx = last_row["ADX_14"]

            # Используем срез последних 5 точек для расчета наклона
            y = df["EMA_50"].iloc[-5:].values
            x = np.arange(len(y))
            ema_slope = np.polyfit(x, y, 1)[0]

            # --- 3. Логика принятия решения ---
            is_trending = adx > self.adx_threshold and abs(ema_slope) > self.ema_slope_threshold
            is_high_volatility = volatility_percentile > self.volatility_threshold_high
            is_low_volatility = volatility_percentile < self.volatility_threshold_low

            if is_trending:
                return "Strong Trend" if not is_high_volatility else "Weak Trend"
            else:
                if is_high_volatility:
                    return "High Volatility Range"
                else:
                    return "Low Volatility Range"

        except Exception as e:
            logger.error(f"Ошибка при определении режима рынка: {e}", exc_info=True)
            return "Low Volatility Range"
