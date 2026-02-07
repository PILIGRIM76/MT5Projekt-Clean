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