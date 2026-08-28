"""Unit-тесты для RiskEngine и RiskService. 
Покрывают: drawdown, VaR, позиции, Circuit Breaker."""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd


class TestRiskServiceDrawdown:
    """Тесты проверки дневной просадки через RiskService."""

    @pytest.fixture
    def setup_risk_service(self):
        """Создаёт RiskService с мок-зависимостями."""
        from src.core.services.risk_service import RiskService
        from src.risk.risk_engine import RiskEngine
        
        config = MagicMock()
        config.MAX_PORTFOLIO_VAR_PERCENT = 3.0
        config.MAX_DAILY_DRAWDOWN_PERCENT = 15.0
        config.RISK_PERCENTAGE = 0.5
        
        risk_engine = RiskEngine(config=config)
        trading_system = MagicMock()
        trading_system.config = config
        trading_system.running = True
        
        # Создаём сервис, но не вызываем __init__ (т.к. есть abstract methods)
        # Вместо этого тестируем методы напрямую через мок
        service = MagicMock()
        service._check_drawdown_limits = RiskService._check_drawdown_limits.__get__(service, RiskService)
        service._last_drawdown_check = 0.0
        service.trading_system = trading_system
        service._logger = MagicMock()
        
        return service

    def test_blocks_trade_when_drawdown_exceeds_15_percent(self):
        """Критический тест: торговля блокируется при просадке >= 15%."""
        from src.core.services.risk_service import RiskService
        
        trading_system = MagicMock()
        trading_system.config.MAX_DAILY_DRAWDOWN_PERCENT = 15.0
        trading_system.config.MAX_PORTFOLIO_VAR_PERCENT = 3.0
        trading_system.running = True
        
        # Мокаем MT5 account_info
        # balance=10000, equity=8000 -> drawdown = 20%
        account_info = MagicMock()
        account_info.balance = 10000.0
        account_info.equity = 8000.0  # drawdown = 20%, превышает лимит 15%
        
        service = MagicMock()
        service._check_drawdown_limits = RiskService._check_drawdown_limits.__get__(service, RiskService)
        service.trading_system = trading_system
        service._logger = MagicMock()
        
        # Патчим mt5.account_info
        with patch('src.core.services.risk_service.mt5.account_info', return_value=account_info):
            result = service._check_drawdown_limits()
            assert result is False, "Сделка должна быть отклонена при drawdown >= 15%"

    def test_allows_trade_when_drawdown_normal(self):
        """Торговля разрешена при нормальной просадке."""
        from src.core.services.risk_service import RiskService
        
        trading_system = MagicMock()
        trading_system.config.MAX_DAILY_DRAWDOWN_PERCENT = 15.0
        trading_system.config.MAX_PORTFOLIO_VAR_PERCENT = 3.0
        trading_system.running = True
        
        # Мокаем MT5 account_info
        account_info = MagicMock()
        account_info.balance = 10000.0
        account_info.equity = 9500.0  # drawdown = 5%
        
        service = MagicMock()
        service._check_drawdown_limits = RiskService._check_drawdown_limits.__get__(service, RiskService)
        service.trading_system = trading_system
        service._logger = MagicMock()
        
        with patch('src.core.services.risk_service.mt5.account_info', return_value=account_info):
            result = service._check_drawdown_limits()
            assert result is True, "Сделка разрешена при нормальной просадке"

    def test_allows_trade_at_limit_drawdown(self):
        """Торговля разрешена при drawdown = лимит."""
        from src.core.services.risk_service import RiskService
        
        trading_system = MagicMock()
        trading_system.config.MAX_DAILY_DRAWDOWN_PERCENT = 15.0
        
        account_info = MagicMock()
        account_info.balance = 10000.0
        account_info.equity = 8500.0  # drawdown = 15% (ровно на лимит)
        
        service = MagicMock()
        service._check_drawdown_limits = RiskService._check_drawdown_limits.__get__(service, RiskService)
        service.trading_system = trading_system
        service._logger = MagicMock()
        
        with patch('src.core.services.risk_service.mt5.account_info', return_value=account_info):
            result = service._check_drawdown_limits()
            assert result is True, "Сделка разрешена при drawdown = лимит"


class TestVaRRiskChecks:
    """Тесты проверки VaR."""

    def test_var_within_limits(self):
        """VaR в пределах допустимого."""
        from src.core.services.risk_service import RiskService
        
        trading_system = MagicMock()
        trading_system.config.MAX_PORTFOLIO_VAR_PERCENT = 3.0
        
        service = MagicMock()
        service._check_var_limits = RiskService._check_var_limits.__get__(service, RiskService)
        service.trading_system = trading_system
        service._logger = MagicMock()
        
        # Мокаем mt5.positions_get
        with patch('src.core.services.risk_service.mt5.positions_get', return_value=[]):
            result = service._check_var_limits()
            assert result is True

    def test_var_exceeds_limit(self):
        """VaR превышает лимит."""
        from src.core.services.risk_service import RiskService
        
        trading_system = MagicMock()
        trading_system.config.MAX_PORTFOLIO_VAR_PERCENT = 3.0
        trading_system.running = True
        
        service = MagicMock()
        service._check_var_limits = RiskService._check_var_limits.__get__(service, RiskService)
        service.trading_system = trading_system
        service._last_var_check = 5.0
        service._logger = MagicMock()
        
        # Мокаем positions_get и risk_engine.calculate_portfolio_var
        mock_positions = [MagicMock()]
        service.risk_engine = MagicMock()
        service.risk_engine.calculate_portfolio_var = MagicMock(return_value=5.0)
        
        with patch('src.core.services.risk_service.mt5.positions_get', return_value=mock_positions):
            result = service._check_var_limits()
            assert result is False


class TestCircuitBreakerIntegration:
    """Тесты Circuit Breaker."""

    def test_circuit_breaker_can_execute_when_closed(self):
        """Circuit Breaker разрешает выполнение в состоянии CLOSED."""
        from src.core.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        assert cb.can_execute() is True

    def test_circuit_breaker_blocks_after_five_failures(self):
        """Circuit Breaker блокирует после 5 ошибок."""
        from src.core.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        
        # Записываем 5 ошибок
        for _ in range(5):
            try:
                raise RuntimeError("Simulated error")
            except RuntimeError:
                cb.record_failure()
        
        assert cb.is_open() is True
        assert cb.can_execute() is False

    def test_circuit_breaker_resets_after_recovery_timeout(self):
        """Circuit Breaker сбрасывается после успешного завершения в HALF_OPEN."""
        from src.core.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        
        # Вызываем 2 ошибки для перехода в OPEN
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True
        
        # Переходим в HALF_OPEN (эмулируем таймаут)
        cb._opened_at = 0  # Установим время открытия в прошлом
        assert cb.state == CircuitState.HALF_OPEN or cb.can_execute() is True
        
        # Записываем успех
        cb.record_success()
        assert cb.is_closed() is True


class TestRiskServiceLogger:
    """Тесты проверки логгера."""

    def test_risk_service_inherits_from_base_service(self):
        """RiskService наследуется от BaseService."""
        from src.core.services.risk_service import RiskService
        from src.core.services.base_service import BaseService
        assert issubclass(RiskService, BaseService)

    def test_risk_service_uses_logger_in_methods(self):
        """RiskService использует self._logger в методах."""
        from src.core.services.risk_service import RiskService
        
        # Проверяем что методы используют _logger
        import inspect
        source = inspect.getsource(RiskService._check_drawdown_limits)
        assert '_logger' in source, "Метод должен использовать _logger"
        
        source = inspect.getsource(RiskService._check_var_limits)
        assert '_logger' in source, "Метод должен использовать _logger"
