# tests/unit/test_paper_trading_engine.py
"""
Тесты для Paper Trading Engine.

Проверяет:
- Инициализацию и конфигурацию
- Открытие и закрытие позиций
- Расчёт PnL
- Симуляцию проскальзывания и комиссий
- Статистику и экспорт
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Добавляем корень проекта в path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.config_models import Settings
from src.core.paper_trading_engine import OrderExecutionState, PaperTradingEngine, SignalType, VirtualOrder, VirtualPosition


@pytest.fixture
def sample_config():
    """Фикстура с тестовой конфигурацией."""
    config = MagicMock(spec=Settings)

    # Создаем MagicMock для paper_trading с правильными значениями
    paper_trading_mock = MagicMock()
    paper_trading_mock.enabled = True
    paper_trading_mock.initial_balance = 100000
    paper_trading_mock.currency = "USD"
    paper_trading_mock.auto_close_on_exit = False

    # Мок для simulation с конкретными значениями
    simulation_mock = MagicMock()
    simulation_mock.slippage_model = "volatility_based"
    simulation_mock.slippage_max_pips = 3
    simulation_mock.spread_source = "real_time"
    simulation_mock.commission_per_lot = 7.0
    simulation_mock.execution_delay_ms = {"market": 100, "limit": 500, "stop": 200}

    # Настраиваем .get() для simulation_mock
    def simulation_get(key, default=None):
        mapping = {
            "slippage_model": "volatility_based",
            "slippage_max_pips": 3,
            "spread_source": "real_time",
            "commission_per_lot": 7.0,
            "execution_delay_ms": {"market": 100, "limit": 500, "stop": 200},
        }
        return mapping.get(key, default)

    simulation_mock.get.side_effect = simulation_get

    # Настраиваем .get() для paper_trading_mock
    def paper_trading_get(key, default=None):
        if key == "simulation":
            return simulation_mock
        if key == "enabled":
            return True
        if key == "initial_balance":
            return 100000
        if key == "currency":
            return "USD"
        if key == "auto_close_on_exit":
            return False
        return getattr(paper_trading_mock, key, default)

    paper_trading_mock.get.side_effect = paper_trading_get
    config.paper_trading = paper_trading_mock

    return config


@pytest.fixture
def mock_trading_system():
    """Фикстура с моком TradingSystem."""
    ts = MagicMock()
    ts.mt5_lock = MagicMock()
    return ts


class TestPaperTradingInit:
    """Тесты инициализации Paper Trading Engine."""

    def test_init_default_values(self, sample_config):
        """Тест инициализации с конфигурацией по умолчанию."""
        pt = PaperTradingEngine(sample_config)

        assert pt.enabled is True
        assert pt.initial_balance == 100000
        assert pt.current_balance == 100000
        assert pt.current_equity == 100000
        assert pt.currency == "USD"
        assert pt.commission_per_lot == 7.0

    def test_init_with_trading_system(self, sample_config, mock_trading_system):
        """Тест инициализации с ссылкой на TradingSystem."""
        pt = PaperTradingEngine(sample_config, mock_trading_system)

        assert pt.trading_system is mock_trading_system

    def test_init_statistics(self, sample_config):
        """Тест инициализации статистики."""
        pt = PaperTradingEngine(sample_config)

        stats = pt.get_statistics()
        assert stats["total_trades"] == 0
        assert stats["winning_trades"] == 0
        assert stats["losing_trades"] == 0
        assert stats["total_pnl"] == 0.0
        assert stats["peak_equity"] == 100000

    def test_reset(self, sample_config):
        """Тест сброса Paper Trading Engine."""
        pt = PaperTradingEngine(sample_config)

        # Имитируем торговлю
        pt.current_balance = 150000
        pt.stats["total_trades"] = 10

        pt.reset()

        assert pt.current_balance == 100000
        assert pt.stats["total_trades"] == 0
        assert len(pt.positions) == 0


class TestVirtualPosition:
    """Тесты VirtualPosition."""

    def test_unrealized_pnl_buy(self):
        """Тест расчёта нереализованного PnL для BUY."""
        position = VirtualPosition(
            ticket="PT_TEST1", symbol="EURUSD", type=SignalType.BUY, lot=0.1, entry_price=1.1000, entry_time=datetime.now()
        )

        # Цена выросла на 10 pips (0.0010)
        pnl = position.unrealized_pnl(1.1010)
        assert pnl > 0
        # PnL = (1.1010 - 1.1000) * 0.1 * 100000 = ~10 USD (без комиссий)
        assert pnl > 5.0  # Хотя бы больше 5 USD

    def test_unrealized_pnl_sell(self):
        """Тест расчёта нереализованного PnL для SELL."""
        position = VirtualPosition(
            ticket="PT_TEST2", symbol="EURUSD", type=SignalType.SELL, lot=0.1, entry_price=1.1000, entry_time=datetime.now()
        )

        # Цена упала на 10 pips (0.0010)
        pnl = position.unrealized_pnl(1.0990)
        assert pnl > 0
        # PnL = (1.1000 - 1.0990) * 0.1 * 100000 = ~10 USD (без комиссий)
        assert pnl > 5.0  # Хотя бы больше 5 USD

    def test_unrealized_pnl_includes_costs(self):
        """Тест что PnL включает комиссии и спред."""
        position = VirtualPosition(
            ticket="PT_TEST3",
            symbol="EURUSD",
            type=SignalType.BUY,
            lot=0.1,
            entry_price=1.1000,
            entry_time=datetime.now(),
            commission=5.0,
            spread_cost=2.0,
        )

        # Цена не изменилась
        pnl = position.unrealized_pnl(1.1000)
        assert pnl < 0  # Убыток на комиссиях
        assert abs(pnl - (-7.0)) < 0.1  # commission + spread

    def test_to_dict(self):
        """Тест конвертации в словарь."""
        position = VirtualPosition(
            ticket="PT_TEST4",
            symbol="EURUSD",
            type=SignalType.BUY,
            lot=0.1,
            entry_price=1.1000,
            entry_time=datetime(2026, 3, 28, 12, 0, 0),
        )

        data = position.to_dict()

        assert data["ticket"] == "PT_TEST4"
        assert data["symbol"] == "EURUSD"
        assert data["lot"] == 0.1
        assert data["entry_price"] == 1.1000
        assert data["entry_time"] == "2026-03-28T12:00:00"


class TestExecuteTrade:
    """Тесты исполнения сделок."""

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_execute_trade_buy(self, mock_tick, sample_config, mock_trading_system):
        """Тест исполнения BUY сделки."""
        # Мокаем тик
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"

        ticket = pt.execute_trade(signal, lot_size=0.1)

        assert ticket is not None
        assert ticket.startswith("PT_")
        assert ticket in pt.positions

        position = pt.positions[ticket]
        assert position.type == SignalType.BUY
        assert position.lot == 0.1
        assert position.entry_price > 1.1000  # С учётом спреда и проскальзывания

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_execute_trade_sell(self, mock_tick, sample_config, mock_trading_system):
        """Тест исполнения SELL сделки."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        signal = MagicMock()
        signal.type = SignalType.SELL
        signal.symbol = "EURUSD"

        ticket = pt.execute_trade(signal, lot_size=0.1)

        assert ticket is not None
        position = pt.positions[ticket]
        assert position.type == SignalType.SELL

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_execute_trade_disabled(self, mock_tick, sample_config):
        """Тест исполнения при отключенном Paper Trading."""
        sample_config.paper_trading.enabled = False
        pt = PaperTradingEngine(sample_config)

        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"

        ticket = pt.execute_trade(signal)

        assert ticket is None

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_execute_trade_updates_stats(self, mock_tick, sample_config, mock_trading_system):
        """Тест обновления статистики при сделке."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"

        pt.execute_trade(signal, lot_size=0.1)

        stats = pt.get_statistics()
        assert stats["total_trades"] == 1
        assert stats["total_commission"] > 0


class TestClosePosition:
    """Тесты закрытия позиций."""

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_close_position_profit(self, mock_tick, sample_config, mock_trading_system):
        """Тест закрытия позиции с прибылью."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        # Открываем BUY
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)

        # Цена выросла на 20 pips
        mock_tick.return_value = MagicMock(bid=1.1020, ask=1.1022)

        # Закрываем
        result = pt.close_position(ticket, reason="MANUAL")

        assert result is True
        assert ticket not in pt.positions
        assert len(pt.closed_positions) == 1

        closed = pt.closed_positions[0]
        assert closed.pnl > 0  # Прибыль
        assert closed.close_reason == "MANUAL"

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_close_position_loss(self, mock_tick, sample_config, mock_trading_system):
        """Тест закрытия позиции с убытком."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        # Открываем BUY
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)

        # Цена упала на 20 pips
        mock_tick.return_value = MagicMock(bid=1.0980, ask=1.0982)

        # Закрываем
        result = pt.close_position(ticket, reason="STOP_LOSS")

        assert result is True
        closed = pt.closed_positions[0]
        assert closed.pnl < 0  # Убыток
        assert closed.close_reason == "STOP_LOSS"

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_close_position_updates_balance(self, mock_tick, sample_config, mock_trading_system):
        """Тест обновления баланса при закрытии."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        initial_balance = pt.current_balance

        # Открываем и закрываем с прибылью
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)

        mock_tick.return_value = MagicMock(bid=1.1050, ask=1.1052)
        pt.close_position(ticket)

        assert pt.current_balance > initial_balance


class TestStatistics:
    """Тесты статистики."""

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_win_rate_calculation(self, mock_tick, sample_config, mock_trading_system):
        """Тест расчёта win rate."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        # 1 выигрышная сделка
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)
        # Движение цены на 200 pips для выигрыша
        mock_tick.return_value = MagicMock(bid=1.1200, ask=1.1202)
        pt.close_position(ticket)

        # 1 проигрышная сделка
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)
        # Движение цены на 200 pips для убытка
        mock_tick.return_value = MagicMock(bid=1.0800, ask=1.0802)
        pt.close_position(ticket)

        stats = pt.get_statistics()

        assert stats["winning_trades"] == 1
        assert stats["losing_trades"] == 1
        # Win rate = 1/2 = 50%
        assert stats["win_rate"] == pytest.approx(50.0, rel=0.5)

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_profit_factor_calculation(self, mock_tick, sample_config, mock_trading_system):
        """Тест расчёта profit factor."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        # Выигрышная сделка (большое движение)
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)
        mock_tick.return_value = MagicMock(bid=1.1200, ask=1.1202)
        pt.close_position(ticket)

        # Проигрышная сделка (меньшее движение)
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)
        mock_tick.return_value = MagicMock(bid=1.0950, ask=1.0952)
        pt.close_position(ticket)

        stats = pt.get_statistics()

        assert stats["gross_profit"] > 0
        assert stats["gross_loss"] > 0
        # Profit factor = gross_profit / gross_loss
        # Допускаем что комиссии могут влиять на соотношение
        assert stats["profit_factor"] > 0.5  # Хотя бы больше 0.5


class TestExport:
    """Тесты экспорта."""

    @patch("src.core.paper_trading_engine.mt5.symbol_info_tick")
    def test_export_to_csv(self, mock_tick, sample_config, mock_trading_system):
        """Тест экспорта в CSV."""
        mock_tick.return_value = MagicMock(bid=1.1000, ask=1.1002)

        pt = PaperTradingEngine(sample_config, mock_trading_system)

        # Открываем и закрываем сделку
        signal = MagicMock()
        signal.type = SignalType.BUY
        signal.symbol = "EURUSD"
        ticket = pt.execute_trade(signal, lot_size=0.1)
        mock_tick.return_value = MagicMock(bid=1.1050, ask=1.1052)
        pt.close_position(ticket)

        # Экспортируем
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as f:
            filepath = f.name

        result = pt.export_to_csv(filepath)

        assert result is True

        # Проверяем файл
        with open(filepath, "r") as f:
            content = f.read()
            assert "Ticket" in content
            assert "EURUSD" in content
            assert "PT_" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
