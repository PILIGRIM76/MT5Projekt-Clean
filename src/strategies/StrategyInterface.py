# src/strategies/StrategyInterface.py
from abc import ABC, abstractmethod
import pandas as pd
from typing import Optional

# +++ НАЧАЛО ИЗМЕНЕНИЙ +++
from src.core.config_models import Settings
# --- КОНЕЦ ИЗМЕНЕНИЙ ---
from src.data_models import TradeSignal


class BaseStrategy(ABC):

    def __init__(self, config: Settings):

        self.config = config

    @abstractmethod
    def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> Optional[TradeSignal]:
        """
        Основной метод, который должна реализовать каждая стратегия.
        Анализирует DataFrame и возвращает TradeSignal для свечи с индексом current_index.
        """
        pass

    def _get_symbol_from_dataframe(self, df: pd.DataFrame, current_index: int) -> str:
        """
        Универсальный метод для получения символа из DataFrame.

        Args:
            df: DataFrame с данными
            current_index: Индекс текущей свечи

        Returns:
            Символ или 'UNKNOWN' если не удалось определить
        """
        # Проверка колонки symbol
        if 'symbol' in df.columns:
            symbol_val = df['symbol'].iloc[current_index]
            if pd.notna(symbol_val) and symbol_val != 'UNKNOWN':
                return str(symbol_val)

        # Проверка мультииндекса (если есть)
        if isinstance(df.index, pd.MultiIndex):
            symbol_val = df.index.get_level_values('symbol')[current_index]
            if pd.notna(symbol_val) and str(symbol_val) != 'nan':
                return str(symbol_val)

        return 'UNKNOWN'
