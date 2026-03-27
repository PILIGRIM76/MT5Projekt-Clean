# src/analysis/gp_rd_manager.py
import logging
import pandas as pd
from typing import Optional

from src.core.config_models import Settings
from src.data.data_provider import DataProvider
from src.ml.genetic_programming_core import GeneticProgrammingCore
from src.analysis.backtester import StrategyBacktester
from src.strategies.StrategyInterface import BaseStrategy
from src.data_models import TradeSignal, SignalType
from src.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class GPRDManager:
    """
    Управляет полным R&D циклом для генетического программирования:
    1. Разделяет данные.
    2. Запускает эволюцию.
    3. Валидирует лучшую стратегию на out-of-sample данных.
    4. Сохраняет и регистрирует успешные результаты.
    """

    def __init__(self, config: Settings, data_provider: DataProvider, db_manager: DatabaseManager):
        self.config = config
        self.data_provider = data_provider
        self.db_manager = db_manager

    def run_cycle(self, symbol: str, timeframe: int, regime: str):
        logger.warning(f"[GP R&D] Запуск полного цикла R&D для {symbol} в режиме '{regime}'...")

        # 1. Загрузка и разделение данных
        full_data = self.data_provider.get_historical_data(
            symbol, timeframe,
            pd.Timestamp.now() - pd.DateOffset(years=1),
            pd.Timestamp.now()
        )
        if full_data is None or len(full_data) < 1000:
            logger.error(f"[GP R&D] Недостаточно исторических данных для {symbol}.")
            return

        # 70% данных для обучения (эволюции), 30% для валидации
        split_point = int(len(full_data) * 0.7)
        in_sample_data = full_data.iloc[:split_point]
        out_of_sample_data = full_data.iloc[split_point:]
        logger.info(
            f"[GP R&D] Данные разделены: {len(in_sample_data)} in-sample, {len(out_of_sample_data)} out-of-sample.")

        # 2. Запуск эволюции на in-sample данных
        gp_core = GeneticProgrammingCore(in_sample_data, self.config, trading_system_ref=None)
        best_individual = gp_core.evolve()

        if not best_individual:
            logger.error("[GP R&D] Эволюция не дала результата. Цикл прерван.")
            return

        # 3. Валидация лучшей стратегии на out-of-sample данных
        logger.warning(f"[GP R&D] Валидация лучшей найденной стратегии на OOS данных...")

        class VirtualTreeStrategy(BaseStrategy):
            def __init__(self, individual: dict, config: Settings):
                super().__init__(config)
                self.buy_tree = individual.get('buy_tree')
                self.sell_tree = individual.get('sell_tree')

            def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> Optional[
                TradeSignal]:
                try:
                    symbol = df['symbol'].iloc[current_index] if 'symbol' in df.columns else 'UNKNOWN'
                    buy_signal = self.buy_tree.evaluate(df).iloc[current_index] if self.buy_tree else False
                    sell_signal = self.sell_tree.evaluate(df).iloc[current_index] if self.sell_tree else False
                    if buy_signal and not sell_signal: return TradeSignal(type=SignalType.BUY, confidence=1.0, symbol=symbol)
                    if sell_signal and not buy_signal: return TradeSignal(type=SignalType.SELL, confidence=1.0, symbol=symbol)
                except IndexError:
                    return None
                return None

        validation_strategy = VirtualTreeStrategy(best_individual, self.config)
        backtester = StrategyBacktester(strategy=validation_strategy, data=out_of_sample_data, timeframe=timeframe,
                                config=self.config)
        report = backtester.run()

        logger.info(f"[GP R&D] Результаты валидации: {report}")

        # 4. Проверка и сохранение результата
        pf_threshold = self.config.rd_cycle_config.profit_factor_threshold
        min_trades = self.config.rd_cycle_config.performance_check_trades_min

        if report.get('profit_factor', 0) > pf_threshold and report.get('total_trades', 0) > min_trades:
            logger.critical(f"[GP R&D] УСПЕХ! Новая стратегия прошла валидацию (PF={report['profit_factor']:.2f}).")

            # Сохраняем саму стратегию (дерево)
            strategy_name = gp_core.save_strategy(best_individual, f"GP_{symbol}_{regime}")

            # Регистрируем ее производительность в БД, чтобы Оркестратор мог ее найти
            if strategy_name:
                self.db_manager.update_strategy_performance(strategy_name, symbol, regime, report)
        else:
            logger.warning("[GP R&D] Новая стратегия не показала достаточной эффективности на OOS данных.")
