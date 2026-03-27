# src/strategies/breakout.py
import logging
from typing import Optional
import json
from pathlib import Path
import pandas as pd
from src.data_models import TradeSignal, SignalType
from .StrategyInterface import BaseStrategy
from src.core.config_models import Settings # <--- ИЗМЕНЕНИЕ: Импортируем Pydantic модель

logger = logging.getLogger(__name__)
PARAMS_FILE = Path("configs/optimized_params.json")

class BreakoutStrategy(BaseStrategy):
    def __init__(self, config: Settings): # <--- ИЗМЕНЕНИЕ: Тип конфига изменен на Settings
        super().__init__(config)
        strategy_name = self.__class__.__name__
        # --- ИСПРАВЛЕНИЕ: Прямой доступ к атрибутам ---
        default_params = config.strategies.breakout
        self.window = default_params.window
        if PARAMS_FILE.exists():
            with open(PARAMS_FILE, 'r') as f:
                try:
                    optimized_params = json.load(f)
                    if strategy_name in optimized_params:
                        self.window = optimized_params[strategy_name].get('window', self.window)
                        logging.info(
                            f"Стратегия '{strategy_name}' загрузила ОПТИМИЗИРОВАННЫЕ параметры: window={self.window}")
                except json.JSONDecodeError:
                    pass

    def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> Optional[TradeSignal]:
        if 'high' not in df.columns or 'low' not in df.columns or 'close' not in df.columns:
            return None
        if current_index < self.window + 1:
            return None
        rolling_window_highs = df['high'].iloc[current_index - self.window : current_index]
        rolling_window_lows = df['low'].iloc[current_index - self.window : current_index]
        if rolling_window_highs.empty or rolling_window_lows.empty:
            return None
        channel_high = rolling_window_highs.max()
        channel_low = rolling_window_lows.min()
        last_price = df['close'].iloc[current_index]
        prev_price = df['close'].iloc[current_index - 1]
        symbol = df['symbol'].iloc[current_index] if 'symbol' in df.columns else 'UNKNOWN'
        if last_price > channel_high and prev_price <= channel_high:
            return TradeSignal(type=SignalType.BUY, confidence=0.7, symbol=symbol)
        elif last_price < channel_low and prev_price >= channel_low:
            return TradeSignal(type=SignalType.SELL, confidence=0.7, symbol=symbol)
        return None
