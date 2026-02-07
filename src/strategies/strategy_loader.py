# src/strategies/strategy_loader.py
import os
import importlib
import inspect
import logging
import pickle
import sys  # <--- Добавлен sys
from pathlib import Path
from typing import List, Optional
import pandas as pd

from src.data_models import TradeSignal, SignalType
from src.strategies.StrategyInterface import BaseStrategy
from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class StrategyLoader:
    def __init__(self, config: Settings):
        self.config = config
        self.strategies_directory = "src/strategies"
        self.generated_strategies_directory = "data/generated_strategies"

    def load_strategies(self) -> List[BaseStrategy]:
        loaded_strategies = []

        # --- 1. Загрузка стандартных стратегий ---
        if os.path.isdir(self.strategies_directory):
            logger.info(f"Сканирование папки '{self.strategies_directory}'...")
            for filename in os.listdir(self.strategies_directory):
                if filename.endswith(".py") and not filename.startswith("__") and filename != "StrategyInterface.py":
                    module_name = f"src.strategies.{filename[:-3]}"
                    try:
                        # Используем reload для обновления кода без перезапуска
                        if module_name in sys.modules:
                            strategy_module = importlib.reload(sys.modules[module_name])
                        else:
                            strategy_module = importlib.import_module(module_name)

                        for name, cls in inspect.getmembers(strategy_module, inspect.isclass):
                            if issubclass(cls, BaseStrategy) and cls is not BaseStrategy:
                                if cls.__module__ == strategy_module.__name__:
                                    strategy_instance = cls(config=self.config)
                                    loaded_strategies.append(strategy_instance)
                                    logger.info(f"Стандартная стратегия '{name}' успешно загружена.")
                    except Exception as e:
                        logger.error(f"Не удалось загрузить стратегию из '{filename}': {e}")

        # --- 2. Загрузка сгенерированных (GP) стратегий ---
        # (Раньше return стоял здесь, поэтому этот код был недостижим)

        gen_dir = Path(self.generated_strategies_directory)
        if gen_dir.is_dir():
            logger.info(f"Сканирование папки '{gen_dir}' для поиска сгенерированных стратегий...")
            for filename in os.listdir(gen_dir):
                if filename.endswith(".pkl"):
                    file_path = gen_dir / filename
                    try:
                        with open(file_path, 'rb') as f:
                            strategy_individual = pickle.load(f)

                        if not isinstance(strategy_individual, dict):
                            continue

                        # Динамическое создание класса для GP стратегии
                        class TreeStrategy(BaseStrategy):
                            def __init__(self, individual: dict, name: str, config: Settings):
                                super().__init__(config)
                                self.buy_tree = individual.get('buy_tree')
                                self.sell_tree = individual.get('sell_tree')
                                self.__class__.__name__ = name.replace('.pkl', '')

                            def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> \
                            Optional[TradeSignal]:
                                try:
                                    if self.buy_tree:
                                        buy_series = self.buy_tree.evaluate(df)
                                        if not buy_series.empty and not pd.isna(buy_series.iloc[current_index]) and \
                                                buy_series.iloc[current_index]:
                                            return TradeSignal(type=SignalType.BUY, confidence=1.0)

                                    if self.sell_tree:
                                        sell_series = self.sell_tree.evaluate(df)
                                        if not sell_series.empty and not pd.isna(sell_series.iloc[current_index]) and \
                                                sell_series.iloc[current_index]:
                                            return TradeSignal(type=SignalType.SELL, confidence=1.0)
                                except Exception:
                                    pass
                                return None

                        strategy_instance = TreeStrategy(strategy_individual, filename, self.config)
                        loaded_strategies.append(strategy_instance)
                        logger.info(f"Сгенерированная стратегия '{filename}' успешно загружена.")
                    except Exception as e:
                        logger.error(f"Ошибка загрузки GP стратегии '{filename}': {e}")

        if not loaded_strategies:
            logger.warning("Не было загружено ни одной стратегии.")

        return loaded_strategies  # <--- RETURN ДОЛЖЕН БЫТЬ ЗДЕСЬ, В САМОМ КОНЦЕ