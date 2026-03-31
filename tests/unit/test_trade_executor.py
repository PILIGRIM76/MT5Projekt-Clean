"""
Unit тесты для TradeExecutor.

Тестирует:
- Инициализацию TradeExecutor
- Проверку открытия рынка (_is_market_open)
- Расчет спреда (_calculate_fair_value_spread)
- Расчет адаптивного оффсета
- Отслеживание результата сделок

Запуск:
    pytest tests/unit/test_trade_executor.py -v
    pytest tests/unit/test_trade_executor.py -v --cov=src.core.services.trade_executor
"""

import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from src.core.config_models import Settings


class TestTradeExecutorInit:
    """Тесты инициализации TradeExecutor."""

    @pytest.fixture(autouse=True)
    def setup(self, minimal_config):
        """Фикстура для настройки тестов."""
        self.config = minimal_config
        self.mock_risk_engine = Mock()
        self.mock_portfolio_service = Mock()
        self.mt5_lock = threading.Lock()

        from src.core.services.trade_executor import TradeExecutor

        self.executor = TradeExecutor(
            config=self.config,
            risk_engine=self.mock_risk_engine,
            portfolio_service=self.mock_portfolio_service,
            mt5_lock=self.mt5_lock,
        )

        yield

    def test_trade_executor_initialization(self):
        """Проверка инициализации TradeExecutor."""
        assert self.executor.config is self.config
        assert self.executor.risk_engine is self.mock_risk_engine
        assert self.executor.portfolio_service is self.mock_portfolio_service
        assert isinstance(self.executor.mt5_lock, type(threading.Lock()))
        assert self.executor.use_limit_entry is True
        assert self.executor.limit_wait_seconds == 30
        assert self.executor.min_lot_for_twap == 5.0

    def test_filling_type_cache_initialized(self):
        """Проверка инициализации кэша filling_type."""
        assert self.executor.filling_type_cache == {}


class TestMarketOpenCheck:
    """Тесты проверки открытия рынка."""

    @pytest.fixture(autouse=True)
    def setup(self, minimal_config):
        """Фикстура для настройки тестов."""
        self.config = minimal_config
        self.mock_risk_engine = Mock()
        self.mock_portfolio_service = Mock()
        self.mt5_lock = threading.Lock()

        # Настройка session_manager
        self.mock_session_manager = Mock()
        self.mock_session_manager.is_trading_hours.return_value = True

        self.mock_trading_system = Mock()
        self.mock_trading_system.session_manager = self.mock_session_manager
        self.mock_trading_system.config = self.config

        self.mock_risk_engine.trading_system = self.mock_trading_system

        from src.core.services.trade_executor import TradeExecutor

        self.executor = TradeExecutor(
            config=self.config,
            risk_engine=self.mock_risk_engine,
            portfolio_service=self.mock_portfolio_service,
            mt5_lock=self.mt5_lock,
        )

        yield

    def test_market_closed_trade_mode_disabled(self):
        """Проверка что рынок закрыт если trade_mode=0."""
        symbol_info = Mock(trade_mode=0, point=0.00001)  # Disabled

        result = self.executor._is_market_open("EURUSD", symbol_info)

        assert result is False

    def test_market_closed_trade_mode_close_only(self):
        """Проверка что рынок закрыт для новых сделок если trade_mode=3."""
        symbol_info = Mock(trade_mode=3, point=0.00001)  # Close only

        result = self.executor._is_market_open("EURUSD", symbol_info)

        assert result is False

    def test_market_outside_trading_hours(self):
        """Проверка что рынок закрыт вне торговых часов."""
        self.mock_session_manager.is_trading_hours.return_value = False
        symbol_info = Mock(trade_mode=4, point=0.00001)

        with patch("src.core.services.trade_executor.mt5") as mock_mt5:
            mock_mt5.symbol_info_tick.return_value = Mock(time=datetime.now().timestamp(), ask=1.1000, bid=1.0998)

            result = self.executor._is_market_open("EURUSD", symbol_info)

            assert result is False
            self.mock_session_manager.is_trading_hours.assert_called_once()


class TestFairValueSpread:
    """Тесты расчета справедливого спреда."""

    @pytest.fixture(autouse=True)
    def setup(self, minimal_config):
        """Фикстура для настройки тестов."""
        self.config = minimal_config
        self.mock_risk_engine = Mock()
        self.mock_portfolio_service = Mock()
        self.mt5_lock = threading.Lock()

        from src.core.services.trade_executor import TradeExecutor

        self.executor = TradeExecutor(
            config=self.config,
            risk_engine=self.mock_risk_engine,
            portfolio_service=self.mock_portfolio_service,
            mt5_lock=self.mt5_lock,
        )

        yield

    def test_calculate_fair_value_spread_normal(self):
        """Проверка расчета спреда с нормальными данными."""
        df = pd.DataFrame(
            {
                "close": [1.1000, 1.1010, 1.1005, 1.1015, 1.1020],
                "high": [1.1005, 1.1015, 1.1010, 1.1020, 1.1025],
                "low": [1.0995, 1.1005, 1.1000, 1.1010, 1.1015],
            }
        )

        symbol_info = Mock(point=0.00001)

        spread = self.executor._calculate_fair_value_spread(df, symbol_info)

        assert spread > 0
        assert isinstance(spread, float)

    def test_calculate_fair_value_spread_invalid_point(self):
        """Проверка расчета спреда с невалидным point."""
        df = pd.DataFrame({"close": [1.1000, 1.1010]})

        # None point
        symbol_info = Mock(point=None)
        spread = self.executor._calculate_fair_value_spread(df, symbol_info)
        assert spread == 0.0001

        # Zero point
        symbol_info = Mock(point=0)
        spread = self.executor._calculate_fair_value_spread(df, symbol_info)
        assert spread == 0.0001

        # Negative point
        symbol_info = Mock(point=-0.00001)
        spread = self.executor._calculate_fair_value_spread(df, symbol_info)
        assert spread == 0.0001

    def test_calculate_fair_value_spread_empty_df(self):
        """Проверка расчета спреда с пустым DataFrame."""
        df = pd.DataFrame()
        symbol_info = Mock(point=0.00001)

        spread = self.executor._calculate_fair_value_spread(df, symbol_info)

        assert spread == 0.0001


class TestAdaptiveOffset:
    """Тесты расчета адаптивного оффсета."""

    @pytest.fixture(autouse=True)
    def setup(self, minimal_config):
        """Фикстура для настройки тестов."""
        self.config = minimal_config
        self.mock_risk_engine = Mock()
        self.mock_portfolio_service = Mock()
        self.mt5_lock = threading.Lock()

        from src.core.services.trade_executor import TradeExecutor

        self.executor = TradeExecutor(
            config=self.config,
            risk_engine=self.mock_risk_engine,
            portfolio_service=self.mock_portfolio_service,
            mt5_lock=self.mt5_lock,
        )

        yield

    def test_calculate_adaptive_offset_normal(self):
        """Проверка расчета адаптивного оффсета."""
        df = pd.DataFrame(
            {
                "close": [1.1000, 1.1010, 1.1005, 1.1015, 1.1020],
                "high": [1.1005, 1.1015, 1.1010, 1.1020, 1.1025],
                "low": [1.0995, 1.1005, 1.1000, 1.1010, 1.1015],
            }
        )

        tick = Mock(ask=1.1000, bid=1.0998, time=datetime.now().timestamp())
        symbol_info = Mock(point=0.00001)

        offset = self.executor._calculate_adaptive_offset(df, tick, symbol_info)

        assert isinstance(offset, float)


class TestTradeOutcome:
    """Тесты отслеживания результата сделок."""

    @pytest.fixture(autouse=True)
    def setup(self, minimal_config):
        """Фикстура для настройки тестов."""
        self.config = minimal_config
        self.mock_risk_engine = Mock()
        self.mock_portfolio_service = Mock()
        self.mt5_lock = threading.Lock()

        # Создаем mock trading_system с нормальным словарем
        self.mock_trading_system = Mock()
        self.mock_trading_system.trade_history = {}
        self.mock_risk_engine.trading_system = self.mock_trading_system

        from src.core.services.trade_executor import TradeExecutor

        self.executor = TradeExecutor(
            config=self.config,
            risk_engine=self.mock_risk_engine,
            portfolio_service=self.mock_portfolio_service,
            mt5_lock=self.mt5_lock,
        )

        yield

    def test_track_trade_outcome_profit(self):
        """Проверка отслеживания прибыльной сделки."""
        self.executor._track_trade_outcome("EURUSD", profit=50.0)

        assert "EURUSD" in self.mock_trading_system.trade_history
        assert self.mock_trading_system.trade_history["EURUSD"]["last_outcome"] == "profit"

    def test_track_trade_outcome_loss(self):
        """Проверка отслеживания убыточной сделки."""
        self.executor._track_trade_outcome("EURUSD", profit=-30.0)

        assert "EURUSD" in self.mock_trading_system.trade_history
        assert self.mock_trading_system.trade_history["EURUSD"]["last_outcome"] == "loss"

    def test_track_trade_outcome_break_even(self):
        """Проверка отслеживания сделки в ноль."""
        self.executor._track_trade_outcome("EURUSD", profit=0.0)

        assert "EURUSD" in self.mock_trading_system.trade_history
        assert self.mock_trading_system.trade_history["EURUSD"]["last_outcome"] == "breakeven"
