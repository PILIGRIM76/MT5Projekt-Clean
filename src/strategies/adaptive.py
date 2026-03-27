# src/strategies/adaptive.py
import logging
from typing import Optional
import pandas as pd
from src.data_models import TradeSignal, SignalType
from src.core.config_models import Settings
from .StrategyInterface import BaseStrategy
from .breakout import BreakoutStrategy
from .mean_reversion import MeanReversionStrategy

logger = logging.getLogger(__name__)

class AdaptiveStrategy(BaseStrategy):
    def __init__(self, config: Settings):
        super().__init__(config)
        self.strategies = {
            'breakout': BreakoutStrategy(config),
            'mean_reversion': MeanReversionStrategy(config)
        }
        self.weights = {'breakout': 0.5, 'mean_reversion': 0.5}

    # --- НАЧАЛО ИЗМЕНЕНИЙ (ИСПРАВЛЕНИЕ ОШИБКИ) ---
    def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> Optional[TradeSignal]:
        # Передаем все аргументы в дочерние стратегии
        breakout_signal = self.strategies['breakout'].check_entry_conditions(df, current_index, timeframe)
        reversion_signal = self.strategies['mean_reversion'].check_entry_conditions(df, current_index, timeframe)

        symbol = df['symbol'].iloc[current_index] if 'symbol' in df.columns else 'UNKNOWN'
        if breakout_signal and reversion_signal and breakout_signal.type == SignalType.BUY and reversion_signal.type == SignalType.BUY:
            logger.debug("AdaptiveStrategy: Консенсус на ПОКУПКУ.")
            return TradeSignal(type=SignalType.BUY, confidence=0.9, symbol=symbol)

        if breakout_signal and reversion_signal and breakout_signal.type == SignalType.SELL and reversion_signal.type == SignalType.SELL:
            logger.debug("AdaptiveStrategy: Консенсус на ПРОДАЖУ.")
            return TradeSignal(type=SignalType.SELL, confidence=0.9, symbol=symbol)

        return None