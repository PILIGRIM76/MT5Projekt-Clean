# src/strategies/moving_average_crossover.py
import pandas as pd
from typing import Optional
import json
from pathlib import Path
import logging
from src.data_models import TradeSignal, SignalType
from .StrategyInterface import BaseStrategy
from src.core.config_models import Settings

logger = logging.getLogger(__name__)
PARAMS_FILE = Path("configs/optimized_params.json")


class MovingAverageCrossoverStrategy(BaseStrategy):
    def __init__(self, config: Settings):
        super().__init__(config)
        strategy_name = self.__class__.__name__
        default_params = config.strategies.ma_crossover.timeframe_params['default']
        self.short_window = default_params.short_window
        self.long_window = default_params.long_window

        if PARAMS_FILE.exists():
            with open(PARAMS_FILE, 'r') as f:
                try:
                    optimized_params = json.load(f)
                    if strategy_name in optimized_params:
                        self.short_window = optimized_params[strategy_name].get('short_window', self.short_window)
                        self.long_window = optimized_params[strategy_name].get('long_window', self.long_window)
                        logging.info(
                            f"Стратегия '{strategy_name}' загрузила ОПТИМИЗИРОВАННЫЕ параметры: short={self.short_window}, long={self.long_window}")
                except json.JSONDecodeError:
                    pass

    def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> Optional[TradeSignal]:

        # Создаем явную копию DataFrame, чтобы избежать SettingWithCopyWarning
        df_copy = df.copy()
        # -------------------------

        short_ma_col = f'EMA_{self.short_window}'
        long_ma_col = f'EMA_{self.long_window}'

        # Теперь все операции выполняем с df_copy
        if short_ma_col not in df_copy.columns:
            df_copy[short_ma_col] = df_copy['close'].ewm(span=self.short_window, adjust=False).mean()
        if long_ma_col not in df_copy.columns:
            df_copy[long_ma_col] = df_copy['close'].ewm(span=self.long_window, adjust=False).mean()

        if current_index < 1 or current_index >= len(df_copy):
            return None

        short_ma = df_copy[short_ma_col].iloc[current_index]
        long_ma = df_copy[long_ma_col].iloc[current_index]
        prev_short_ma = df_copy[short_ma_col].iloc[current_index - 1]
        prev_long_ma = df_copy[long_ma_col].iloc[current_index - 1]

        if pd.isna(short_ma) or pd.isna(long_ma) or pd.isna(prev_short_ma) or pd.isna(prev_long_ma):
            return None

        symbol = df['symbol'].iloc[current_index] if 'symbol' in df.columns else 'UNKNOWN'
        if short_ma > long_ma and prev_short_ma <= prev_long_ma:
            return TradeSignal(type=SignalType.BUY, confidence=0.6, symbol=symbol)
        elif short_ma < long_ma and prev_short_ma >= prev_long_ma:
            return TradeSignal(type=SignalType.SELL, confidence=0.6, symbol=symbol)
        return None