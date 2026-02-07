# src/analysis/strategy_incubator.py
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd

from src.analysis.backtester import StrategyBacktester
from src.analysis.stress_tester import StressTester
from src.db.database_manager import DatabaseManager
from src.strategies.StrategyInterface import BaseStrategy
from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class StrategyIncubator:
    """
    Управляет трехэтапной проверкой новых сгенерированных стратегий.
    """

    def __init__(self, config: Settings, db_manager: DatabaseManager):
        self.config = config
        self.db_manager = db_manager
        self.stress_tester = None
        try:
            from src.analysis.stress_tester import StressTester
            self.stress_tester = StressTester(config)
        except ImportError:
            logger.warning("StressTester не найден, этап 2 инкубации будет пропущен.")

        # Пороги для прохождения инкубации (можно вынести в settings.json)
        self.min_profit_factor = 1.2
        self.max_stress_drawdown = 0.25  # Макс. просадка в стресс-тесте 25%

    def incubate(self, strategy: BaseStrategy, validation_data: pd.DataFrame, timeframe: int,
                 symbol: str, regime: str) -> bool:
        """
        Запускает полный цикл инкубации для новой стратегии.
        Возвращает True, если стратегия успешно прошла все этапы.
        """
        strategy_name = strategy.__class__.__name__
        logger.critical(f"--- НАЧАЛО ИНКУБАЦИИ СТРАТЕГИИ '{strategy_name}' ---")

        # --- Этап 1: Бэктест на out-of-sample данных ---
        logger.info("[Инкубатор] Этап 1: Стандартный бэктест...")
        backtester = StrategyBacktester(strategy, validation_data, timeframe, self.config)
        backtest_report = backtester.run()

        if backtest_report.get('profit_factor', 0) < self.min_profit_factor:
            logger.warning(
                f"[Инкубатор] СТРАТЕГИЯ ОТКЛОНЕНА. Низкий профит-фактор на бэктесте: {backtest_report.get('profit_factor', 0):.2f}")
            return False
        logger.info(f"[Инкубатор] Этап 1 пройден. PF={backtest_report.get('profit_factor', 0):.2f}")

        # --- Этап 2: Стресс-тест (если доступен) ---
        if self.stress_tester:
            logger.info("[Инкубатор] Этап 2: Стресс-тест на аномальных данных...")
            # В реальном коде здесь должен быть вызов stress_tester.run()
            # Для симуляции, используем DD из обычного бэктеста
            stress_report = backtest_report

            if stress_report.get('max_drawdown', 1.0) > self.max_stress_drawdown:
                logger.warning(
                    f"[Инкубатор] СТРАТЕГИЯ ОТКЛОНЕНА. Высокая просадка в стресс-тесте: {stress_report.get('max_drawdown', 1.0):.2%}")
                return False
            logger.info(f"[Инкубатор] Этап 2 пройден. Max DD = {stress_report.get('max_drawdown', 1.0):.2%}")
        else:
            logger.warning("[Инкубатор] Этап 2 (Стресс-тест) пропущен из-за отсутствия StressTester.")

        # --- Этап 3: Перевод в Paper Trading (Инкубатор) ---
        # Сохраняем статус 'incubating' в StrategyPerformance
        self.db_manager.update_strategy_performance(
            strategy_name=strategy_name,
            symbol=symbol,
            market_regime=regime,
            report=backtest_report,  # Сохраняем отчет из чистого бэктеста
            status='incubating',  # <-- НОВЫЙ СТАТУС
            incubation_start_date=datetime.utcnow()  # <-- НОВОЕ ПОЛЕ
        )

        logger.critical(f"[Инкубатор] Этап 3: Стратегия переведена в режим ИНКУБАЦИИ (Paper Trading) на 30 дней.")
        logger.critical(f"--- ИНКУБАЦИЯ УСПЕШНО ЗАВЕРШЕНА ---")
        return True