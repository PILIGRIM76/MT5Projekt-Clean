# src/analysis/stress_tester.py
import logging
from typing import Any, Dict

import numpy as np
import pandas as pd
from arch import arch_model

from src.analysis.backtester import StrategyBacktester
from src.core.config_models import Settings
from src.data_models import SignalType
from src.strategies.StrategyInterface import BaseStrategy

logger = logging.getLogger(__name__)


class StressTester:
    """
    Модуль для выполнения Pre-Mortem анализа (GARCH Monte Carlo)
    перед открытием каждой сделки.
    """

    def __init__(self, config: Any):
        # Принимает полный конфиг, но использует только настройки pre_mortem
        self.config = config.risk.pre_mortem

    def run_garch_monte_carlo(self, df: pd.DataFrame, stop_loss_price: float, trade_type: SignalType) -> bool:
        """
        Выполняет симуляцию Монте-Карло (GARCH) для оценки вероятности "хвостового" риска.

        Возвращает True, если риск ниже порога, False - если сделка должна быть заблокирована.
        """
        if not self.config.enabled or len(df) < 252:
            return True

        try:
            returns = df["close"].pct_change().dropna()
            if returns.empty or returns.std() == 0:
                return True

            # 1. Обучение GARCH
            model = arch_model(returns * 100, vol="Garch", p=1, q=1, rescale=False)
            res = model.fit(disp="off", show_warning=False)
            forecast = res.forecast(horizon=1)
            predicted_volatility = np.sqrt(forecast.variance.iloc[-1, 0]) / 100.0

            # 2. Расчет параметров симуляции
            start_price = df["close"].iloc[-1]
            sl_distance = abs(start_price - stop_loss_price)

            # Цена, при которой наступает "катастрофический" убыток (X * SL)
            if trade_type == SignalType.BUY:
                catastrophic_price = start_price - (sl_distance * self.config.tail_risk_multiplier)
            else:
                catastrophic_price = start_price + (sl_distance * self.config.tail_risk_multiplier)

            drift = returns.mean()
            catastrophic_loss_count = 0

            # 3. Симуляция
            for _ in range(self.config.num_simulations):
                current_price = start_price
                for _ in range(self.config.simulation_horizon_bars):
                    random_shock = np.random.normal(0, 1)
                    price_movement = np.exp(
                        (drift - 0.5 * predicted_volatility**2) * 1 + predicted_volatility * np.sqrt(1) * random_shock
                    )
                    current_price *= price_movement

                    if (trade_type == SignalType.BUY and current_price <= catastrophic_price) or (
                        trade_type == SignalType.SELL and current_price >= catastrophic_price
                    ):
                        catastrophic_loss_count += 1
                        break

            tail_risk_probability = catastrophic_loss_count / self.config.num_simulations

            if tail_risk_probability > self.config.tail_risk_probability_threshold:
                logger.critical(f"!!! PRE-MORTEM: БЛОКИРОВКА. Риск: {tail_risk_probability:.1%}")
                return False

            logger.info(f"[Pre-mortem] Анализ пройден. Риск: {tail_risk_probability:.1%}")
            return True

        except Exception as e:
            logger.error(f"Ошибка Pre-mortem анализа: {e}", exc_info=True)
            return True
