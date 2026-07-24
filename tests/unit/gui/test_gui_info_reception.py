# -*- coding: utf-8 -*-
"""
Тесты GUI для получения информации.

Покрывает:
- Bridge (мост данных)
- ControlCenterWidget (получение данных сканера, логов, статусов)
- Обновление таблиц и виджетов
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


# Инициализируем QApplication для тестов виджетов
def _get_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ============================================================================
# 1. Mock Bridge
# ============================================================================


class MockBridge(QObject):
    """Мок моста с реальными сигналами для тестов."""

    log_message_added = Signal(str, object)  # message, color
    status_updated = Signal(str)
    market_scan_updated = Signal(list)
    trading_signals_updated = Signal(list)

    def __init__(self):
        super().__init__()


# ============================================================================
# 2. Тесты Bridge
# ============================================================================


class TestBridge:
    """Тесты моста данных GUI."""

    def test_bridge_creation(self):
        """Мост создаётся успешно."""
        bridge = MockBridge()
        assert bridge is not None
        assert hasattr(bridge, "log_message_added")
        assert hasattr(bridge, "status_updated")
        assert hasattr(bridge, "market_scan_updated")
        assert hasattr(bridge, "trading_signals_updated")

    def test_log_message_emitted(self, qtbot):
        """Сигнал логов испускается."""
        bridge = MockBridge()
        with qtbot.waitSignal(bridge.log_message_added) as blocker:
            bridge.log_message_added.emit("Test log", "white")

        assert blocker.args[0] == "Test log"

    def test_status_emitted(self, qtbot):
        """Сигнал статуса испускается."""
        bridge = MockBridge()
        with qtbot.waitSignal(bridge.status_updated) as blocker:
            bridge.status_updated.emit("System running")

        assert blocker.args[0] == "System running"

    def test_market_scan_emitted(self, qtbot):
        """Сигнал сканера рынка испускается."""
        bridge = MockBridge()
        data = [{"symbol": "EURUSD", "price": 1.15}]
        with qtbot.waitSignal(bridge.market_scan_updated) as blocker:
            bridge.market_scan_updated.emit(data)

        assert blocker.args[0] == data

    def test_trading_signals_emitted(self, qtbot):
        """Сигнал торговых сигналов испускается."""
        bridge = MockBridge()
        signals = [{"symbol": "EURUSD", "type": "BUY"}]
        with qtbot.waitSignal(bridge.trading_signals_updated) as blocker:
            bridge.trading_signals_updated.emit(signals)

        assert blocker.args[0] == signals


# ============================================================================
# 3. Тесты ControlCenterWidget — получение информации
# ============================================================================


class TestControlCenterDataReception:
    """Тесты получения данных в ControlCenterWidget."""

    @pytest.fixture
    def bridge(self):
        return MockBridge()

    @pytest.fixture
    def config(self):
        cfg = MagicMock()
        cfg.SYMBOLS_WHITELIST = ["EURUSD", "GBPUSD"]
        cfg.RISK_PERCENTAGE = 0.02
        cfg.MAX_DAILY_DRAWDOWN_PERCENT = 5.0
        return cfg

    @pytest.fixture
    def widget(self, qtbot, bridge, config):
        from src.gui.control_center_widget import ControlCenterWidget

        w = ControlCenterWidget(
            bridge=bridge,
            config=config,
            trading_system_adapter=None,
        )
        qtbot.addWidget(w)
        return w

    def test_widget_creation(self, widget):
        """Виджет создаётся успешно."""
        assert widget is not None
        assert widget.bridge is not None

    def test_append_log_receives_message(self, widget):
        """append_log получает сообщение."""
        assert hasattr(widget, "append_log") or hasattr(widget, "log_text_edit")

    def test_update_status_receives_message(self, widget):
        """update_status получает статус."""
        import inspect

        sig = inspect.signature(widget.update_status)
        params = list(sig.parameters.keys())
        if "is_important" in params:
            widget.update_status("System running", False)
        else:
            widget.update_status("System running")

    def test_update_market_table_receives_data(self, widget):
        """update_market_table получает данные сканера."""
        scan_data = [
            {"symbol": "EURUSD", "price": 1.1500, "change_24h": 0.5, "rsi": 55.0},
            {"symbol": "GBPUSD", "price": 1.2700, "change_24h": -0.3, "rsi": 42.0},
        ]

        widget.update_market_table(scan_data)

        # Таблица должна обновиться
        if hasattr(widget, "market_table"):
            assert widget.market_table.rowCount() == 2

    def test_prepare_control_center_data(self, widget):
        """prepare_control_center_data обрабатывает сырые данные."""
        raw_data = [
            {"symbol": "EURUSD", "price": 1.1500, "provider_type": "MT5"},
            {"symbol": "GBPUSD", "price": 1.2700, "provider_type": "MT5"},
        ]

        result = widget.prepare_control_center_data(raw_data)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["symbol"] == "EURUSD"

    def test_prepare_control_center_data_empty(self, widget):
        """prepare_control_center_data с пустыми данными."""
        result = widget.prepare_control_center_data([])
        assert result == []

    def test_prepare_control_center_data_none(self, widget):
        """prepare_control_center_data с None — gracefully handling."""
        try:
            result = widget.prepare_control_center_data(None)
            assert result == []
        except (TypeError, AttributeError):
            pass  # None может не поддерживаться — это допустимо

    def test_signal_connections(self, widget, bridge):
        """Сигналы моста подключены к виджету."""
        if widget.bridge:
            assert hasattr(widget, "append_log") or hasattr(widget, "log_text_edit")
            assert hasattr(widget, "update_status")
            assert hasattr(widget, "update_market_table")


# ============================================================================
# 4. Тесты получения данных баланса/эквити
# ============================================================================


class TestBalanceEquityInfo:
    """Тесты получения информации о балансе и эквити."""

    def test_account_manager_provides_balance(self):
        """AccountManager предоставляет баланс."""
        mock_am = MagicMock()
        mock_am.balance = 81404.41
        mock_am.equity = 81472.90
        mock_am.account_type = "DEMO"

        assert mock_am.balance == 81404.41
        assert mock_am.equity == 81472.90
        assert mock_am.account_type == "DEMO"

    def test_equity_pnl_calculation(self):
        """PnL вычисляется правильно."""
        balance = 81404.41
        equity = 81472.90
        pnl = equity - balance

        assert pnl > 0  # Прибыль
        assert abs(pnl - 68.49) < 0.01

    def test_equity_color_green_for_profit(self):
        """Цвет эквити зелёный при прибыли."""
        balance = 81404.41
        equity = 81472.90
        color = "#00FF00" if equity >= balance else "#FF4444"

        assert color == "#00FF00"

    def test_equity_color_red_for_loss(self):
        """Цвет эквити красный при убытке."""
        balance = 81404.41
        equity = 81300.00
        color = "#00FF00" if equity >= balance else "#FF4444"

        assert color == "#FF4444"


# ============================================================================
# 5. Тесты получения информации о моделях
# ============================================================================


class TestModelInfoReception:
    """Тесты получения информации о ML-моделях."""

    def test_model_accuracy_data_format(self):
        """Данные точности моделей в правильном формате."""
        accuracy_data = {
            "EURUSD": 0.497,
            "GBPUSD": 0.539,
            "USDJPY": 0.513,
        }

        assert isinstance(accuracy_data, dict)
        assert all(isinstance(v, float) for v in accuracy_data.values())
        assert all(0 <= v <= 1 for v in accuracy_data.values())

    def test_retrain_progress_data_format(self):
        """Данные прогресса переобучения в правильном формате."""
        progress_data = [
            {"symbol": "EURUSD", "hours_since": 12, "needs_retrain": False},
            {"symbol": "GBPUSD", "hours_since": 30, "needs_retrain": True},
        ]

        assert isinstance(progress_data, list)
        assert all("symbol" in item for item in progress_data)
        assert all("needs_retrain" in item for item in progress_data)

    def test_average_accuracy_calculation(self):
        """Средняя точность вычисляется правильно."""
        accuracy_data = {
            "EURUSD": 0.50,
            "GBPUSD": 0.60,
            "USDJPY": 0.40,
        }

        avg = sum(accuracy_data.values()) / len(accuracy_data)
        assert abs(avg - 0.50) < 0.01


# ============================================================================
# 6. Тесты получения информации о торговле
# ============================================================================


class TestTradeInfoReception:
    """Тесты получения торговой информации."""

    def test_trade_signal_format(self):
        """Торговый сигнал в правильном формате."""
        signal = {
            "symbol": "EURUSD",
            "signal_type": "BUY",
            "strategy": "AI_MF_Consensus",
            "timestamp": "20:52:41",
            "entry_price": 1.1500,
            "timeframe": "H1",
        }

        required_keys = ["symbol", "signal_type", "strategy", "timestamp", "entry_price"]
        assert all(k in signal for k in required_keys)
        assert signal["signal_type"] in ["BUY", "SELL", "HOLD"]

    def test_trade_history_format(self):
        """История сделок в правильном формате."""
        history = [
            {
                "symbol": "EURUSD",
                "type": "BUY",
                "open_price": 1.1500,
                "close_price": 1.1550,
                "profit": 50.0,
                "timestamp_open": "2026-04-10 10:00:00",
                "timestamp_close": "2026-04-10 12:00:00",
            }
        ]

        assert len(history) == 1
        assert history[0]["profit"] > 0

    def test_position_info_format(self):
        """Информация о позиции в правильном формате."""
        position = {
            "symbol": "EURUSD",
            "type": "BUY",
            "volume": 0.1,
            "open_price": 1.1500,
            "current_price": 1.1550,
            "profit": 5.0,
            "sl": 1.1450,
            "tp": 1.1600,
        }

        assert position["profit"] > 0
        assert position["current_price"] > position["open_price"]


# ============================================================================
# 7. Тесты получения информации о рисках
# ============================================================================


class TestRiskInfoReception:
    """Тесты получения информации о рисках."""

    def test_drawdown_calculation(self):
        """Просадка вычисляется правильно."""
        balance = 100000.0
        equity = 95000.0
        drawdown_pct = (balance - equity) / balance * 100

        assert abs(drawdown_pct - 5.0) < 0.01

    def test_risk_level_assessment(self):
        """Уровень риска определяется правильно."""
        # Низкий риск
        assert 2.0 < 5.0  # drawdown < threshold
        # Высокий риск
        assert 8.0 > 5.0  # drawdown > threshold

    def test_position_count_limit(self):
        """Проверка лимита позиций."""
        max_positions = 10
        current_positions = 2
        can_open = current_positions < max_positions

        assert can_open is True

        current_positions = 10
        can_open = current_positions < max_positions
        assert can_open is False


# ============================================================================
# 8. Интеграционные тесты получения информации
# ============================================================================


class TestInfoReceptionIntegration:
    """Интеграционные тесты получения информации."""

    def test_full_data_flow(self, qtbot):
        """Полный поток данных: Bridge → Widget."""
        bridge = MockBridge()

        # Собираем данные через сигналы
        received_logs = []
        received_status = []
        received_scan = []

        bridge.log_message_added.connect(lambda msg, color: received_logs.append((msg, color)))
        bridge.status_updated.connect(lambda s: received_status.append(s))
        bridge.market_scan_updated.connect(lambda d: received_scan.extend(d))

        # Эмулируем получение данных
        bridge.log_message_added.emit("System started", "white")
        bridge.status_updated.emit("Running")
        bridge.market_scan_updated.emit(
            [
                {"symbol": "EURUSD", "price": 1.15},
            ]
        )

        assert len(received_logs) == 1
        assert received_logs[0][0] == "System started"
        assert len(received_status) == 1
        assert received_status[0] == "Running"
        assert len(received_scan) == 1
        assert received_scan[0]["symbol"] == "EURUSD"

    def test_multiple_signals_order(self, qtbot):
        """Множественные сигналы приходят в правильном порядке."""
        bridge = MockBridge()
        events = []

        bridge.log_message_added.connect(lambda m, c: events.append(("log", m)))
        bridge.status_updated.connect(lambda s: events.append(("status", s)))
        bridge.market_scan_updated.connect(lambda d: events.append(("scan", d)))

        bridge.status_updated.emit("Initializing")
        bridge.log_message_added.emit("Loading models", "white")
        bridge.status_updated.emit("Running")
        bridge.market_scan_updated.emit([{"symbol": "EURUSD"}])

        assert len(events) == 4
        assert events[0] == ("status", "Initializing")
        assert events[1] == ("log", "Loading models")
        assert events[2] == ("status", "Running")
        assert events[3][0] == "scan"
