# src/analysis/strategy_optimizer.py
import json
import logging
from pathlib import Path
from typing import Any, Dict, Type

import optuna
import pandas as pd

from src.analysis.backtester import StrategyBacktester
from src.core.config_models import Settings  # <--- ИЗМЕНЕНИЕ: Импортируем Pydantic модель
from src.data.data_provider import DataProvider
from src.strategies.breakout import BreakoutStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy
from src.strategies.StrategyInterface import BaseStrategy

logger = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)

PARAMS_FILE = Path("configs/optimized_params.json")


class StrategyOptimizer:
    def __init__(self, config: Settings, data_provider: DataProvider):  # <--- ИЗМЕНЕНИЕ: Тип конфига изменен на Settings
        self.config = config
        self.data_provider = data_provider
        self.optimizable_strategies = {
            "MeanReversionStrategy": MeanReversionStrategy,
            "BreakoutStrategy": BreakoutStrategy,
            "MovingAverageCrossoverStrategy": MovingAverageCrossoverStrategy,
        }

    def _save_params(self, strategy_name: str, params: Dict[str, Any]):
        data = {}
        if PARAMS_FILE.exists():
            with open(PARAMS_FILE, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    pass
        data[strategy_name] = params
        with open(PARAMS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.warning(f"Найдены новые оптимальные параметры для '{strategy_name}': {params}. Сохранено.")

    def optimize(self, strategy_name: str, symbol: str, timeframe: int, history_days: int = 90):
        if strategy_name not in self.optimizable_strategies:
            logger.error(f"Стратегия '{strategy_name}' не найдена в списке оптимизируемых.")
            return

        strategy_class = self.optimizable_strategies[strategy_name]
        df = self.data_provider.get_historical_data(
            symbol, timeframe, pd.Timestamp.now() - pd.DateOffset(days=history_days), pd.Timestamp.now()
        )
        if df is None or df.empty:
            logger.error(f"Не удалось получить данные для оптимизации {strategy_name} на {symbol}.")
            return

        def objective(trial: optuna.trial.Trial) -> float:
            params = {}
            if strategy_name == "MeanReversionStrategy":
                params["window"] = trial.suggest_int("window", 20, 200)
                params["std_dev_multiplier"] = trial.suggest_float("std_dev_multiplier", 1.5, 3.5)
            elif strategy_name == "BreakoutStrategy":
                params["window"] = trial.suggest_int("window", 10, 100)
            elif strategy_name == "MovingAverageCrossoverStrategy":
                params["short_window"] = trial.suggest_int("short_window", 5, 50)
                params["long_window"] = trial.suggest_int("long_window", params["short_window"] + 10, 200)

            # --- ИЗМЕНЕНИЕ: Создаем временный Pydantic объект с новыми параметрами ---
            temp_config_dict = self.config.model_dump()
            strategy_key = strategy_class.__name__.replace("Strategy", "").lower()

            if strategy_name == "MovingAverageCrossoverStrategy":
                temp_config_dict["strategies"]["ma_crossover"]["timeframe_params"]["default"] = params
            else:
                temp_config_dict["strategies"][strategy_key] = params

            temp_config_obj = Settings(**temp_config_dict)
            strategy_instance = strategy_class(config=temp_config_obj)

            backtester = StrategyBacktester(strategy=strategy_instance, data=df, timeframe=timeframe, config=temp_config_obj)
            report = backtester.run()

            profit_factor = report.get("profit_factor", 0.0)
            if report["total_trades"] < 5:
                return -1.0
            return profit_factor if pd.notna(profit_factor) and profit_factor > 0 else 0.0

        logger.info(f"Начало оптимизации '{strategy_name}' на {symbol} ({history_days} дней)...")
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=100, timeout=600)

        if study.best_trial.value > 1.1:
            self._save_params(strategy_name, study.best_params)
        else:
            logger.warning(
                f"Оптимизация для '{strategy_name}' не дала результата лучше порога (PF > 1.1). "
                f"Лучший найденный PF: {study.best_trial.value:.2f}. Параметры не обновлены."
            )
