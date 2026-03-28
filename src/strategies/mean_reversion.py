# src/strategies/mean_reversion.py
import pandas as pd
from typing import Optional
import json
from pathlib import Path
import logging
from src.data_models import TradeSignal, SignalType
from .StrategyInterface import BaseStrategy
# <--- ИЗМЕНЕНИЕ: Импортируем Pydantic модель
from src.core.config_models import Settings

logger = logging.getLogger(__name__)
PARAMS_FILE = Path("configs/optimized_params.json")


class MeanReversionStrategy(BaseStrategy):
    def __init__(self, config: Settings):  # <--- ИЗМЕНЕНИЕ: Тип конфига изменен на Settings
        super().__init__(config)
        strategy_name = self.__class__.__name__
        # --- ИСПРАВЛЕНИЕ: Прямой доступ к атрибутам ---
        default_params = config.strategies.mean_reversion
        self.window = default_params.window
        self.std_dev_multiplier = default_params.std_dev_multiplier
        if PARAMS_FILE.exists():
            with open(PARAMS_FILE, 'r') as f:
                try:
                    optimized_params = json.load(f)
                    if strategy_name in optimized_params:
                        self.window = optimized_params[strategy_name].get(
                            'window', self.window)
                        self.std_dev_multiplier = optimized_params[strategy_name].get('std_dev_multiplier',
                                                                                      self.std_dev_multiplier)
                        logging.info(
                            f"Стратегия '{strategy_name}' загрузила ОПТИМИЗИРОВАННЫЕ параметры: window={self.window}, std_dev={self.std_dev_multiplier}")
                except json.JSONDecodeError:
                    pass

    def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> Optional[TradeSignal]:
        if 'BBU_20_2.0' not in df.columns or 'BBL_20_2.0' not in df.columns:
            return None
        if current_index < 1:
            return None

        upper_band = df['BBU_20_2.0'].iloc[current_index]
        lower_band = df['BBL_20_2.0'].iloc[current_index]

        last_price = df['close'].iloc[current_index]
        prev_price = df['close'].iloc[current_index - 1]

        # Получение символа из DataFrame или индекса
        symbol = self._get_symbol_from_dataframe(df, current_index)
        if symbol == 'UNKNOWN':
            logger.warning(
                f"Не удалось определить символ для Mean Reversion стратегии")
            return None

        # is_buy_signal = last_price < lower_band and prev_price <= lower_band
        is_sell_signal = last_price > upper_band and prev_price >= upper_band

        # Проверка сигналов
        if last_price < lower_band:
            return TradeSignal(type=SignalType.BUY, confidence=0.8, symbol=symbol)
        elif last_price > upper_band:
            return TradeSignal(type=SignalType.SELL, confidence=0.8, symbol=symbol)

        return None
