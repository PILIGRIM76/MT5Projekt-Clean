#!/usr/bin/env python3
"""
Тесты для каждого режима бэктеста.
Проверяет что каждый тип бэктеста возвращает корректные данные.
"""

import asyncio
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.backtester import StrategyBacktester
from src.analysis.event_driven_backtester import EventDrivenBacktester
from src.analysis.system_backtester import SystemBacktester
from src.core.config_models import Settings
from src.strategies.mean_reversion import MeanReversionStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def sample_config():
    """Загружает реальную конфигурацию из configs/settings.json."""
    settings_path = PROJECT_ROOT / "configs" / "settings.json"
    if settings_path.exists():
        config = Settings(_env_file=settings_path)
    else:
        config = Settings(
            MT5_LOGIN="52565344",
            MT5_PASSWORD="test",
            MT5_SERVER="Alpari-MT5-Demo",
            MT5_PATH="C:/Program Files/MetaTrader 5/terminal64.exe",
            DATABASE_FOLDER=str(PROJECT_ROOT / "database"),
            DATABASE_NAME="trading_system.db",
            SYMBOLS_WHITELIST=["EURUSD"],
        )
    return config


@pytest.fixture(scope="module")
def sample_historical_data():
    """Создаёт тестовые исторические данные."""
    dates = pd.date_range(start="2026-03-01", periods=1000, freq="h")
    np.random.seed(42)

    # Генерируем реалистичные OHLCV данные
    base_price = 1.1500
    price_changes = np.random.randn(1000) * 0.001
    prices = base_price + np.cumsum(price_changes)

    df = pd.DataFrame(
        {
            "time": dates,
            "open": prices,
            "high": prices + np.abs(np.random.randn(1000) * 0.0005),
            "low": prices - np.abs(np.random.randn(1000) * 0.0005),
            "close": prices + np.random.randn(1000) * 0.0003,
            "tick_volume": np.random.randint(100, 5000, 1000),
        }
    )

    # Убеждаемся что high >= close >= low
    df["high"] = df[["high", "close"]].max(axis=1)
    df["low"] = df[["low", "close"]].min(axis=1)

    return df


class TestEventDrivenBacktest:
    """Тесты для Event-Driven Backtest."""

    def test_event_driven_returns_report_and_equity(self, sample_config, sample_historical_data):
        """Event-Driven бэктест должен возвращать отчёт и кривую капитала."""
        backtester = EventDrivenBacktester(sample_config, sample_historical_data)

        # Запускаем бэктест
        report, equity_df = asyncio.run(backtester.run())

        # Проверяем отчёт
        assert isinstance(report, dict), "Отчёт должен быть словарём"
        assert "total_trades" in report, "Отчёт должен содержать total_trades"
        assert "win_rate" in report, "Отчёт должен содержать win_rate"
        assert "profit_factor" in report, "Отчёт должен содержать profit_factor"
        assert "max_drawdown" in report, "Отчёт должен содержать max_drawdown"
        assert "net_pnl" in report, "Отчёт должен содержать net_pnl"

        # Проверяем кривую капитала
        assert isinstance(equity_df, pd.DataFrame), "Кривая капитала должна быть DataFrame"
        assert "equity" in equity_df.columns, "Кривая капитала должна содержать колонку 'equity'"
        assert len(equity_df) > 0, "Кривая капитала не должна быть пустой"

        logger.info(f"✅ Event-Driven: {report.get('total_trades', 'N/A')} сделок, PnL: {report.get('net_pnl', 'N/A')}")


class TestSystemBacktest:
    """Тесты для Системного бэктеста (Экосистема)."""

    def test_system_backtest_returns_report(self, sample_config, sample_historical_data):
        """Системный бэктест должен возвращать отчёт."""
        backtester = SystemBacktester(historical_data=sample_historical_data, config=sample_config)

        # Запускаем бэктест
        report = backtester.run()

        # Проверяем отчёт
        assert isinstance(report, dict), "Отчёт должен быть словарём"
        assert len(report) > 0, "Отчёт не должен быть пустым"

        # Проверяем ключевые метрики
        expected_keys = ["total_trades", "win_rate", "profit_factor", "max_drawdown", "net_pnl"]
        for key in expected_keys:
            assert key in report, f"Отчёт должен содержать '{key}'"

        logger.info(f"✅ System Backtest: {report.get('total_trades', 'N/A')} сделок, PnL: {report.get('net_pnl', 'N/A')}")


class TestClassicStrategyBacktest:
    """Тесты для бэктеста классической стратегии."""

    def test_mean_reversion_backtest_returns_report(self, sample_config, sample_historical_data):
        """Бэктест MeanReversionStrategy должен возвращать отчёт."""
        strategy = MeanReversionStrategy()
        backtester = StrategyBacktester(
            strategy=strategy,
            data=sample_historical_data,
            timeframe="H1",
            config=sample_config,
        )

        # Запускаем бэктест
        report = backtester.run()

        # Проверяем отчёт
        assert isinstance(report, dict), "Отчёт должен быть словарём"
        assert "total_trades" in report, "Отчёт должен содержать total_trades"
        assert "win_rate" in report, "Отчёт должен содержать win_rate"
        assert report["total_trades"] >= 0, "Количество сделок должно быть >= 0"
        assert 0 <= report["win_rate"] <= 1, "Win rate должен быть в диапазоне [0, 1]"

        logger.info(f"✅ Classic Strategy (MeanReversion): {report['total_trades']} сделок, WR: {report['win_rate']:.1%}")


class TestAIBacktest:
    """Тесты для бэктеста AI модели."""

    def test_ai_backtest_structure(self):
        """AI бэктестер должен иметь правильную структуру."""
        from src.ml.ai_backtester import AIBacktester

        # Проверяем что класс существует и имеет нужные методы
        assert hasattr(AIBacktester, "__init__"), "AIBacktester должен иметь __init__"
        assert hasattr(AIBacktester, "run"), "AIBacktester должен иметь метод run()"

        logger.info("✅ AI Backtester структура корректна")


class TestBacktestModesIntegration:
    """Интеграционные тесты для всех режимов бэктеста."""

    def test_all_modes_return_consistent_structure(self, sample_config, sample_historical_data):
        """Все режимы бэктеста должны возвращать согласованную структуру отчёта."""
        results = {}

        # 1. Event-Driven
        ed_backtester = EventDrivenBacktester(sample_config, sample_historical_data)
        ed_report, _ = asyncio.run(ed_backtester.run())
        results["Event-Driven"] = ed_report

        # 2. System Backtest
        sys_backtester = SystemBacktester(historical_data=sample_historical_data, config=sample_config)
        sys_report = sys_backtester.run()
        results["System"] = sys_report

        # 3. Classic Strategy
        strategy = MeanReversionStrategy()
        classic_backtester = StrategyBacktester(
            strategy=strategy,
            data=sample_historical_data,
            timeframe="H1",
            config=sample_config,
        )
        classic_report = classic_backtester.run()
        results["Classic"] = classic_report

        # Проверяем что все отчёты имеют общую структуру
        common_keys = ["total_trades", "win_rate", "profit_factor", "max_drawdown", "net_pnl"]
        for mode_name, report in results.items():
            for key in common_keys:
                assert key in report, f"{mode_name} должен содержать '{key}'"

        # Логируем результаты
        logger.info("📊 Сравнение режимов бэктеста:")
        for mode_name, report in results.items():
            logger.info(
                f"  {mode_name}: "
                f"Trades={report.get('total_trades', 'N/A')}, "
                f"WR={report.get('win_rate', 0):.1%}, "
                f"PF={report.get('profit_factor', 0):.2f}, "
                f"PnL={report.get('net_pnl', 0):.2f}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
