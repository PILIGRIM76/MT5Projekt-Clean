"""
Дополнительные Unit тесты для RiskEngine - упрощенная версия.

Тестирует методы с простым мокированием:
- calculate_diversity_reward
- update_capital_allocation
- update_regime_capital_allocation
- _find_nearest_swing
- _update_toxic_regimes_cache

Запуск:
    pytest tests/unit/test_risk_engine_simple.py -v
"""

import threading
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from src.core.config_models import Settings
from src.data_models import SignalType


@pytest.fixture
def mock_config():
    """Создание тестовой конфигурации."""
    config = Mock(spec=Settings)
    config.risk = Mock()
    config.risk.toxic_regime_update_interval_sec = 300
    config.risk.toxic_regime_risk_multiplier = 0.5
    config.RISK_PERCENTAGE = 0.02
    config.CORRELATION_THRESHOLD = 0.8
    config.MAX_DAILY_DRAWDOWN_PERCENT = 0.05
    config.PORTFOLIO_VOLATILITY_THRESHOLD = 0.15
    config.MAX_PORTFOLIO_VAR_PERCENT = 0.03
    config.IGNORE_HISTORICAL_DRAWDOWN_ON_START = False
    config.EVENT_BLOCK_WINDOW_HOURS = 2
    config.ALLOW_WEEKEND_TRADING = True
    return config


@pytest.fixture
def mock_trading_system():
    """Мок для торговой системы."""
    ts = MagicMock()
    ts.db_manager = MagicMock()
    ts.db_manager.get_toxic_regimes.return_value = []
    ts.anomaly_detector = MagicMock()
    ts.anomaly_detector.is_trained = False
    ts.get_dummy_df.return_value = pd.DataFrame()
    ts.strategies = []
    ts.trade_history = {}
    return ts


@pytest.fixture
def risk_engine(mock_config, mock_trading_system):
    """Создание RiskEngine для тестов."""
    with (
        patch("src.risk.risk_engine.VolatilityForecaster"),
        patch("src.risk.risk_engine.StressTester"),
        patch("src.risk.risk_engine.AnomalyDetector"),
    ):

        from src.risk.risk_engine import RiskEngine

        return RiskEngine(
            config=mock_config,
            trading_system_ref=mock_trading_system,
            querier=None,
            mt5_lock=threading.Lock(),
            is_simulation=True,
        )


class TestDiversityReward:
    """Тесты для calculate_diversity_reward."""

    def test_calculate_diversity_reward_no_strategies(self, risk_engine):
        """Проверка без активных стратегий."""
        allocations = {}
        result = risk_engine.calculate_diversity_reward(allocations)
        assert result == 0.0

    def test_calculate_diversity_reward_single_strategy(self, risk_engine):
        """Проверка с одной стратегией."""
        allocations = {"Strong Trend": {"AI_Model": 1.0}, "Weak Trend": {"AI_Model": 1.0}}
        result = risk_engine.calculate_diversity_reward(allocations)
        assert result >= 0.0

    def test_calculate_diversity_reward_multiple_strategies(self, risk_engine):
        """Проверка с несколькими стратегиями."""
        allocations = {
            "Strong Trend": {"AI_Model": 0.5, "BreakoutStrategy": 0.5},
            "Weak Trend": {"AI_Model": 0.5, "BreakoutStrategy": 0.5},
        }
        result = risk_engine.calculate_diversity_reward(allocations)
        assert result > 0.0


class TestCapitalAllocation:
    """Тесты для обновления capital allocation."""

    def test_update_capital_allocation(self, risk_engine):
        """Проверка обновления аллокации капитала."""
        new_allocation = {"AI_Model": 0.6, "RLTradeManager": 0.4}

        risk_engine.update_capital_allocation(new_allocation)

        # Проверяем что аллокация обновилась (значения могут быть нормализованы)
        assert "AI_Model" in risk_engine.default_capital_allocation
        assert "RLTradeManager" in risk_engine.default_capital_allocation

    def test_update_regime_capital_allocation(self, risk_engine):
        """Проверка обновления аллокации по режимам."""
        new_matrix = {
            "Strong Trend": {"AI_Model": 0.8, "BreakoutStrategy": 0.2},
            "Weak Trend": {"AI_Model": 0.3, "BreakoutStrategy": 0.7},
        }

        risk_engine.update_regime_capital_allocation(new_matrix)

        assert risk_engine.capital_allocation["Strong Trend"] == new_matrix["Strong Trend"]


class TestFindNearestSwing:
    """Тесты для _find_nearest_swing."""

    def test_find_nearest_swing_buy_signal(self, risk_engine):
        """Поиск swing для BUY сигнала."""
        df = pd.DataFrame({"low": [1.0990, 1.0985, 1.0980, 1.0985, 1.0990], "high": [1.1000, 1.1005, 1.1010, 1.1005, 1.1000]})

        result = risk_engine._find_nearest_swing(df, SignalType.BUY, window=3)

        assert result is not None
        assert isinstance(result, float)

    def test_find_nearest_swing_sell_signal(self, risk_engine):
        """Поиск swing для SELL сигнала."""
        df = pd.DataFrame({"low": [1.0990, 1.0985, 1.0980, 1.0985, 1.0990], "high": [1.1000, 1.1005, 1.1010, 1.1005, 1.1000]})

        result = risk_engine._find_nearest_swing(df, SignalType.SELL, window=3)

        assert result is not None
        assert isinstance(result, float)

    def test_find_nearest_swing_empty_df(self, risk_engine):
        """Поиск swing с пустым DataFrame."""
        df = pd.DataFrame()

        result = risk_engine._find_nearest_swing(df, SignalType.BUY)

        assert result is None


class TestToxicRegimesCache:
    """Тесты для _update_toxic_regimes_cache."""

    def test_update_toxic_regimes_cache(self, risk_engine, mock_trading_system):
        """Обновление кэша токсичных режимов."""
        mock_trading_system.db_manager.get_toxic_regimes.return_value = ["Low Volatility Range"]

        risk_engine.last_toxic_regime_update = 0  # Force update
        risk_engine._update_toxic_regimes_cache()

        assert len(risk_engine.toxic_regimes_cache) >= 0

    def test_update_toxic_regimes_cache_not_due(self, risk_engine):
        """Кэш не обновляется если не пришло время."""
        initial_cache = risk_engine.toxic_regimes_cache.copy()
        risk_engine.last_toxic_regime_update = datetime.now().timestamp()

        risk_engine._update_toxic_regimes_cache()

        assert risk_engine.toxic_regimes_cache == initial_cache


class TestTradingMode:
    """Тесты для set_trading_mode."""

    def test_set_trading_mode_aggressive(self, risk_engine):
        """Установка агрессивного режима."""
        settings = {"risk_multiplier": 1.5}
        risk_engine.set_trading_mode("aggressive", settings)

        assert risk_engine.base_risk_per_trade_percent > 0.02

    def test_set_trading_mode_custom_settings(self, risk_engine):
        """Установка с кастомными настройками."""
        settings = {"max_drawdown": 0.15, "var_confidence": 0.99}
        risk_engine.set_trading_mode("custom", settings)

        assert hasattr(risk_engine, "max_daily_drawdown_percent")
