# tests/unit/test_position_manager.py
"""Unit-тесты для PositionManager."""

import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.core.services.position_manager import (
    ClosePositionResult,
    ModifyResult,
    OpenPositionResult,
    OrderType,
    PositionInfo,
    PositionManager,
)


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.MT5_PATH = "C:/MT5/terminal64.exe"
    return config


@pytest.fixture
def position_manager(mock_config):
    lock = threading.Lock()
    return PositionManager(config=mock_config, mt5_lock=lock)


@pytest.fixture
def mock_mt5_position():
    pos = MagicMock()
    pos.ticket = 12345
    pos.symbol = "EURUSD"
    pos.type = 0  # ORDER_TYPE_BUY
    pos.volume = 1.0
    pos.price_open = 1.1000
    pos.price_current = 1.1050
    pos.sl = 1.0950
    pos.tp = 1.1100
    pos.profit = 50.0
    pos.swap = -1.5
    pos.commission = -7.0
    pos.time = 1700000000
    pos.comment = "test"
    return pos


class TestPositionInfoFromMt5:
    def test_from_mt5_buy(self, mock_mt5_position):
        with patch("src.core.services.position_manager.mt5") as mock_mt5:
            mock_mt5.ORDER_TYPE_BUY = 0
            mock_mt5.ORDER_TYPE_SELL = 1
            info = PositionInfo.from_mt5(mock_mt5_position)

        assert info.ticket == 12345
        assert info.symbol == "EURUSD"
        assert info.order_type == OrderType.BUY
        assert info.volume == 1.0
        assert info.profit == 50.0

    def test_to_dict(self, mock_mt5_position):
        with patch("src.core.services.position_manager.mt5") as mock_mt5:
            mock_mt5.ORDER_TYPE_BUY = 0
            mock_mt5.ORDER_TYPE_SELL = 1
            info = PositionInfo.from_mt5(mock_mt5_position)
            d = info.to_dict()

        assert d["ticket"] == 12345
        assert d["type"] == "BUY"
        assert isinstance(d["time_open"], str)


class TestOpenPosition:
    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_open_buy_success(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        mock_mt5.symbol_info.return_value = MagicMock(visible=True, digits=5)
        mock_mt5.symbol_info_tick.return_value = MagicMock(ask=1.1000, bid=1.0998)
        mock_mt5.ORDER_TYPE_BUY = 0
        mock_mt5.ORDER_TYPE_SELL = 1
        mock_mt5.TRADE_ACTION_DEAL = 5
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.TRADE_RETCODE_DONE = 10009

        result_mock = MagicMock()
        result_mock.retcode = 10009
        result_mock.deal = 99999
        mock_mt5.order_send.return_value = result_mock

        res = position_manager.open_position("EURUSD", 0.1, OrderType.BUY, sl=1.0950, tp=1.1100)

        assert res.success is True
        assert res.ticket == 99999
        assert res.symbol == "EURUSD"
        assert res.order_type == OrderType.BUY

    @patch("src.core.services.position_manager.mt5_ensure_connected")
    def test_open_position_no_connection(self, mock_ensure, position_manager):
        mock_ensure.return_value = False
        res = position_manager.open_position("EURUSD", 0.1, OrderType.BUY)
        assert res.success is False
        assert "MT5" in res.message

    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_open_position_symbol_not_found(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        mock_mt5.symbol_info.return_value = None

        res = position_manager.open_position("INVALID", 0.1, OrderType.BUY)
        assert res.success is False
        assert "не найден" in res.message


class TestClosePosition:
    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_close_success(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        pos = MagicMock()
        pos.symbol = "EURUSD"
        pos.volume = 1.0
        pos.type = 0
        pos.profit = 25.0
        mock_mt5.positions_get.return_value = [pos]
        mock_mt5.symbol_info_tick.return_value = MagicMock(bid=1.1050, ask=1.1052)
        mock_mt5.ORDER_TYPE_BUY = 0
        mock_mt5.ORDER_TYPE_SELL = 1
        mock_mt5.TRADE_ACTION_DEAL = 5
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.TRADE_RETCODE_DONE = 10009

        result_mock = MagicMock()
        result_mock.retcode = 10009
        mock_mt5.order_send.return_value = result_mock

        res = position_manager.close_position(12345)
        assert res.success is True
        assert res.ticket == 12345

    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_close_not_found(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        mock_mt5.positions_get.return_value = None

        res = position_manager.close_position(99999)
        assert res.success is False


class TestModifyPosition:
    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_modify_success(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        pos = MagicMock()
        pos.symbol = "EURUSD"
        pos.sl = 1.0950
        pos.tp = 1.1100
        mock_mt5.positions_get.return_value = [pos]
        mock_mt5.symbol_info.return_value = MagicMock(digits=5)
        mock_mt5.TRADE_ACTION_SLTP = 6
        mock_mt5.TRADE_RETCODE_DONE = 10009

        result_mock = MagicMock()
        result_mock.retcode = 10009
        mock_mt5.order_send.return_value = result_mock

        res = position_manager.modify_position(12345, sl=1.0960, tp=1.1120)
        assert res.success is True
        assert res.old_sl == 1.0950
        assert res.new_sl == 1.0960

    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_modify_no_change(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        pos = MagicMock()
        pos.symbol = "EURUSD"
        pos.sl = 1.0950
        pos.tp = 1.1100
        mock_mt5.positions_get.return_value = [pos]
        mock_mt5.symbol_info.return_value = MagicMock(digits=5)

        res = position_manager.modify_position(12345, sl=1.0950, tp=1.1100)
        assert res.success is True
        assert "Без изменений" in res.message


class TestCalculateVolume:
    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_calculate_volume(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        info = MagicMock()
        info.volume_min = 0.01
        info.volume_max = 100.0
        info.volume_step = 0.01
        info.trade_tick_value = 1.0
        mock_mt5.symbol_info.return_value = info

        vol = position_manager.calculate_volume("EURUSD", risk_amount_usd=100, stop_loss_pips=50)
        assert vol >= 0.01
        assert vol <= 100.0

    @patch("src.core.services.position_manager.mt5_ensure_connected")
    def test_calculate_volume_no_connection(self, mock_ensure, position_manager):
        mock_ensure.return_value = False
        vol = position_manager.calculate_volume("EURUSD", 100, 50)
        assert vol == 0.0


class TestGetPositions:
    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_get_positions_empty(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        mock_mt5.positions_get.return_value = None
        assert position_manager.get_positions() == []

    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_get_positions_count(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        mock_mt5.positions_get.return_value = None
        assert position_manager.get_positions_count() == 0

    @patch("src.core.services.position_manager.mt5_ensure_connected")
    @patch("src.core.services.position_manager.mt5")
    def test_get_total_profit_empty(self, mock_mt5, mock_ensure, position_manager):
        mock_ensure.return_value = True
        mock_mt5.positions_get.return_value = None
        assert position_manager.get_total_profit() == 0.0
