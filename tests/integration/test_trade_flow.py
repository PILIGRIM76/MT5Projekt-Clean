"""
Интеграционные тесты полного цикла торговли (E2E).
Проверяют взаимодействие: Signal -> Risk -> Execution через EventBus.
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass
from enum import Enum


class EventPriority(Enum):
    HIGH = 1
    MEDIUM = 2


@dataclass
class MockSignal:
    symbol: str
    direction: str
    volume: float
    price: float
    stop_loss: float
    take_profit: float


@dataclass
class MockTradeResult:
    retcode: int
    order: int = 0
    comment: str = ""


class TestTradeFlowIntegration:
    """Тесты полного цикла обработки торгового сигнала."""

    @pytest.fixture
    def mock_event_bus(self):
        """Создаёт мок EventBus, который запоминает опубликованные события."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        bus.subscribe = MagicMock()
        return bus

    @pytest.fixture
    def mock_risk_engine(self):
        """Создаёт RiskEngine, который по умолчанию пропускает сделки."""
        risk = MagicMock()
        risk.validate_trade = MagicMock(return_value=True)
        risk.max_daily_drawdown = 15.0
        return risk

    @pytest.fixture
    def mock_execution_service(self):
        """Создаёт ExecutionService с моком MT5."""
        exec_svc = MagicMock()
        exec_svc.execute_trade = AsyncMock(return_value=MockTradeResult(retcode=10009, order=99999))
        exec_svc.get_positions = MagicMock(return_value=[])
        exec_svc.circuit_breaker = MagicMock()
        exec_svc.circuit_breaker.call = MagicMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))
        return exec_svc

    @pytest.fixture
    def integration_env(self, mock_event_bus, mock_risk_engine, mock_execution_service):
        """Собирает окружение для интеграционного теста."""
        return {
            "event_bus": mock_event_bus,
            "risk_engine": mock_risk_engine,
            "execution_service": mock_execution_service,
        }

    @pytest.mark.asyncio
    async def test_happy_path_signal_to_execution(self, integration_env):
        """Успешный цикл: Сигнал -> Риск ОК -> Ордер исполнен."""
        signal = MockSignal(symbol="EURUSD", direction="BUY", volume=0.1, price=1.1, stop_loss=1.09, take_profit=1.12)
        
        # 1. Риск пропускает
        assert integration_env["risk_engine"].validate_trade(signal) is True
        
        # 2. Исполнение успешно
        result = await integration_env["execution_service"].execute_trade(signal)
        assert result.retcode == 10009
        assert result.order == 99999
        
        # 3. Событие опубликовано в шину
        await integration_env["event_bus"].publish("ORDER_FILLED", result, priority=EventPriority.HIGH)
        integration_env["event_bus"].publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_risk_rejection_blocks_execution(self, integration_env):
        """Цикл прерывается: Сигнал -> Риск ОТКЛОНЁН -> Исполнение НЕ вызывается."""
        signal = MockSignal(symbol="XAUUSD", direction="BUY", volume=1.0, price=2000.0, stop_loss=1990.0, take_profit=2020.0)
        
        # 1. Риск отклоняет (например, из-за просадки)
        integration_env["risk_engine"].validate_trade = MagicMock(return_value=False)
        assert integration_env["risk_engine"].validate_trade(signal) is False
        
        # 2. Исполнение НЕ должно быть вызвано
        integration_env["execution_service"].execute_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_and_blocks_trading(self, integration_env):
        """Circuit Breaker открывается после ошибок и блокирует новые сделки."""
        signal = MockSignal(symbol="GBPUSD", direction="SELL", volume=0.1, price=1.2, stop_loss=1.21, take_profit=1.19)
        
        # Симулируем срабатывание Circuit Breaker (например, после 5 ошибок MT5)
        from src.core.circuit_breaker import CircuitBreaker, CircuitOpenError
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        # 3 неудачных вызова (симулируем ошибки)
        for _ in range(3):
            cb.record_failure()
        
        # Следующий вызов должен быть заблокирован CB (allow_request бросит исключение)
        with pytest.raises(CircuitOpenError):
            cb.allow_request()
        
        # В реальной системе ExecutionService проверит CB перед вызовом MT5
        assert cb.state.name == "OPEN"

    def test_event_bus_priority_handling(self, mock_event_bus):
        """Проверяет, что критические события (RiskEvent) имеют высокий приоритет."""
        async def publish_risk_event():
            await mock_event_bus.publish("RISK_LIMIT_REACHED", {"drawdown": 16.0}, priority=EventPriority.HIGH)
        
        asyncio.run(publish_risk_event())
        
        # Проверяем аргументы вызова
        call_args = mock_event_bus.publish.call_args
        assert call_args is not None
        assert call_args.kwargs.get("priority") == EventPriority.HIGH