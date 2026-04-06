# -*- coding: utf-8 -*-
"""
Тесты для Trading Engine — ядро торговой логики.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.core.trading.trading_engine import TradingEngine


class TestTradingEngine:
    """Тесты TradingEngine."""

    @pytest.fixture
    def trading_system_mock(self):
        """Создаёт мок TradingSystem."""
        ts = Mock()
        ts.stop_event = Mock()
        ts.stop_event.is_set.return_value = False
        ts.is_heavy_init_complete = True
        ts.update_pending = False
        ts.mt5_lock = Mock()
        ts.mt5_lock.acquire.return_value = True
        ts.command_queue = Mock()
        ts.command_queue.empty.return_value = True
        ts.command_queue.get_nowait.side_effect = Exception("Queue empty")
        ts.config = Mock()
        ts.config.TOP_N_SYMBOLS = 10
        ts.config.SYMBOLS_WHITELIST = ["EURUSD", "GBPUSD", "USDJPY"]
        ts.latest_ranked_list = []
        return ts

    @pytest.fixture
    def engine(self, trading_system_mock):
        """Создаёт TradingEngine с моком."""
        return TradingEngine(trading_system_mock)

    def test_can_trade_when_ready(self, engine):
        """can_trade возвращает True когда система готова."""
        assert engine.can_trade() is True

    def test_can_trade_when_stopped(self, engine):
        """can_trade возвращает False когда система остановлена."""
        engine.trading_system.stop_event.is_set.return_value = True
        assert engine.can_trade() is False

    def test_can_trade_when_not_initialized(self, engine):
        """can_trade возвращает False когда не инициализировано."""
        engine.trading_system.is_heavy_init_complete = False
        assert engine.can_trade() is False

    def test_can_trade_when_update_pending(self, engine):
        """can_trade возвращает False когда обновление в процессе."""
        engine.trading_system.update_pending = True
        assert engine.can_trade() is False

    def test_get_available_symbols_from_scanner(self, engine):
        """get_available_symbols использует данные сканера."""
        engine.trading_system.latest_ranked_list = [
            {"symbol": "EURUSD", "score": 0.9},
            {"symbol": "GBPUSD", "score": 0.8},
            {"symbol": "USDJPY", "score": 0.7},
        ]

        symbols = engine.get_available_symbols()

        assert symbols == ["EURUSD", "GBPUSD", "USDJPY"]
        assert len(symbols) == 3

    def test_get_available_symbols_fallback(self, engine):
        """get_available_symbols fallback на whitelist."""
        engine.trading_system.latest_ranked_list = []

        symbols = engine.get_available_symbols()

        assert symbols == ["EURUSD", "GBPUSD", "USDJPY"]

    def test_get_timeframe_returns_h1(self, engine):
        """get_timeframe_for_trading возвращает H1."""
        import MetaTrader5 as mt5
        assert engine.get_timeframe_for_trading() == mt5.TIMEFRAME_H1

    def test_safe_gui_update_respects_rate_limit(self, engine):
        """safe_gui_update соблюдает rate limiting."""
        import time

        engine._last_gui_updates = {"test_method": time.time() - 0.1}  # 0.1 сек назад
        engine._min_gui_interval = 0.3  # Мин. 0.3 сек

        # Должно быть заблокировано rate limiting
        result = engine.safe_gui_update("test_method", "data")
        assert result is False

    def test_safe_gui_update_uses_coordinator(self, engine):
        """safe_gui_update использует GUI Coordinator."""
        import time

        engine._last_gui_updates = {}  # Нет ограничений
        engine.trading_system._gui_coordinator = Mock()
        engine.trading_system._gui_coordinator.safe_gui_update.return_value = True

        result = engine.safe_gui_update("update_balance", 1000.0, 1001.0)

        assert result is True
        engine.trading_system._gui_coordinator.safe_gui_update.assert_called_once()

    def test_process_commands_handles_empty_queue(self, engine):
        """process_commands обрабатывает пустую очередь."""
        engine.process_commands()  # Не должно вызывать ошибок
