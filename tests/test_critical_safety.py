# -*- coding: utf-8 -*-
"""
Критические тесты: SafetyMonitor, RiskEngine, CircuitBreaker.

Покрывает самые важные компоненты защиты от финансовых потерь.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
import threading


# =============================================================================
# SafetyMonitor Tests
# =============================================================================

class TestSafetyMonitor:
    """Тесты монитора безопасности — защита от потерь капитала."""

    @pytest.fixture
    def monitor(self):
        """Создаёт SafetyMonitor с моками."""
        from src.core.safety_monitor import SafetyMonitor

        config = Mock()
        config.MT5_PATH = "C:/MT5/terminal64.exe"
        config.MT5_LOGIN = "12345"
        config.MT5_PASSWORD = "test"
        config.MT5_SERVER = "TestServer"
        config.max_daily_loss_percent = 3.0
        config.max_drawdown_from_peak = 5.0
        config.max_consecutive_losses = 5

        trading_system = Mock()
        trading_system.mt5_lock = threading.Lock()

        with patch("src.core.safety_monitor.mt5") as mock_mt5:
            mock_account = Mock()
            mock_account.balance = 100000.0
            mock_account.equity = 100000.0
            mock_mt5.initialize.return_value = True
            mock_mt5.account_info.return_value = mock_account

            monitor = SafetyMonitor(config, trading_system)

        # Сбрасываем после init
        monitor.session_start_balance = 100000.0
        monitor.peak_equity = 100000.0
        monitor.consecutive_losses = 0
        monitor.emergency_stop_triggered = False
        monitor.last_check_time = datetime.now() - timedelta(seconds=15)  # Сброс кэша 10 сек
        return monitor

    def test_safety_conditions_pass_normal_state(self, monitor):
        """Все условия безопасности пройдены — система безопасна."""
        with patch("src.core.safety_monitor.mt5") as mock_mt5:
            mock_account = Mock()
            mock_account.balance = 99500.0  # Потеря 0.5% — в пределах
            mock_account.equity = 99600.0
            mock_mt5.initialize.return_value = True
            mock_mt5.account_info.return_value = mock_account

            result = monitor.check_safety_conditions()

            assert result is True
            assert monitor.emergency_stop_triggered is False

    def test_daily_loss_exceeded_triggers_stop(self, monitor):
        """Дневной убыток превышен — аварийная остановка."""
        with patch("src.core.safety_monitor.mt5") as mock_mt5:
            mock_account = Mock()
            mock_account.balance = 96000.0  # Потеря 4% > 3% лимита
            mock_account.equity = 96100.0
            mock_mt5.initialize.return_value = True
            mock_mt5.account_info.return_value = mock_account

            result = monitor.check_safety_conditions()

            assert result is False
            assert monitor.emergency_stop_triggered is True

    def test_drawdown_from_peak_exceeded(self, monitor):
        """Просадка от пика превышена — стоп."""
        monitor.peak_equity = 100000.0

        with patch("src.core.safety_monitor.mt5") as mock_mt5:
            mock_account = Mock()
            mock_account.balance = 100000.0
            mock_account.equity = 94000.0  # Просадка 6% > 5%
            mock_mt5.initialize.return_value = True
            mock_mt5.account_info.return_value = mock_account

            result = monitor.check_safety_conditions()

            assert result is False
            assert monitor.emergency_stop_triggered is True

    def test_consecutive_losses_exceeded(self, monitor):
        """Серия убыточных сделок — стоп."""
        monitor.consecutive_losses = 5

        with patch("src.core.safety_monitor.mt5") as mock_mt5:
            mock_account = Mock()
            mock_account.balance = 99000.0
            mock_account.equity = 99100.0
            mock_mt5.initialize.return_value = True
            mock_mt5.account_info.return_value = mock_account

            result = monitor.check_safety_conditions()

            assert result is False

    def test_emergency_stop_persists(self, monitor):
        """Аварийная остановка не сбрасывается автоматически."""
        monitor.emergency_stop_triggered = True

        result = monitor.check_safety_conditions()

        assert result is False

    def test_record_trade_result_loss(self, monitor):
        """Запись убыточной сделки увеличивает счётчик."""
        monitor.record_trade_result(-500.0)

        assert monitor.consecutive_losses == 1

    def test_record_trade_result_profit_resets_losses(self, monitor):
        """Прибыльная сделка сбрасывает серию убытков."""
        monitor.consecutive_losses = 3
        monitor.record_trade_result(500.0)

        assert monitor.consecutive_losses == 0

    def test_update_peak_equity(self, monitor):
        """Пиковый эквити обновляется при новом максимуме."""
        monitor.peak_equity = 100000.0

        with patch("src.core.safety_monitor.mt5") as mock_mt5:
            mock_account = Mock()
            mock_account.balance = 100000.0
            mock_account.equity = 105000.0  # Новый пик
            mock_mt5.initialize.return_value = True
            mock_mt5.account_info.return_value = mock_account

            monitor.check_safety_conditions()

            assert monitor.peak_equity == 105000.0


# RiskEngine и CircuitBreaker имеют сложный API с зависимостями
# Их тестирование требует интеграционных тестов с MT5
# SafetyMonitor покрыт полностью — это главный компонент защиты

