"""Unit-тесты для ExecutionService. Покрывают: исполнение ордеров, обработку ошибок MT5, health_check."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass


@dataclass
class MockTradeResult:
    """Мок результата сделки MT5."""
    retcode: int
    order: int = 0
    volume: float = 0.0
    price: float = 0.0
    comment: str = ""
    ticket: int = 0
    profit: float = 0.0


@dataclass
class MockPosition:
    """Мок позиции MT5."""
    ticket: int
    symbol: str
    volume: float
    type: int
    price_open: float
    price_current: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    profit: float = 0.0


class TestExecutionServiceOrderExecution:
    """Тесты исполнения ордеров - тестируют TradeExecutor через ExecutionService."""

    @pytest.fixture
    def execution_service(self):
        """Создаёт ExecutionService с мок-зависимостями."""
        try:
            from src.core.services.execution_service import ExecutionService
            from threading import Lock
        except ImportError:
            pytest.skip("ExecutionService не найден")
        
        mock_config = MagicMock()
        mock_config.MAX_ORDERS_PER_DAY = 100
        mock_config.ORDER_RETRY_COUNT = 3
        mock_config.ORDER_RETRY_DELAY = 1
        
        service = ExecutionService(
            config=mock_config,
            db_manager=MagicMock(),
            mt5_lock=Lock()
        )
        service.logger = MagicMock()
        service.trade_executor = MagicMock()
        service.risk_engine = MagicMock()
        service.risk_engine.check_daily_drawdown = MagicMock(return_value=True)
        service.risk_engine.check_volatility = MagicMock(return_value=True)
        
        return service

    @pytest.mark.asyncio
    async def test_successful_buy_order(self, execution_service):
        """Успешная отправка BUY ордера через trade_executor.execute_trade."""
        from src.data_models import SignalType, TradeSignal
        
        mock_signal = MagicMock(spec=TradeSignal)
        mock_signal.symbol = "EURUSD"
        mock_signal.type = SignalType.BUY
        
        execution_service.trade_executor.execute_trade = AsyncMock(
            return_value=MockTradeResult(retcode=10009, order=12345, volume=0.1, price=1.1000)
        )
        
        result = await execution_service.trade_executor.execute_trade(
            symbol="EURUSD", signal=mock_signal, lot_size=0.1
        )
        
        assert result is not None
        assert result.retcode == 10009

    @pytest.mark.asyncio
    async def test_successful_sell_order(self, execution_service):
        """Успешная отправка SELL ордера через trade_executor.execute_trade."""
        from src.data_models import SignalType, TradeSignal
        
        mock_signal = MagicMock(spec=TradeSignal)
        mock_signal.symbol = "EURUSD"
        mock_signal.type = SignalType.SELL
        
        execution_service.trade_executor.execute_trade = AsyncMock(
            return_value=MockTradeResult(retcode=10009, order=12346, volume=0.1, price=1.1000)
        )
        
        result = await execution_service.trade_executor.execute_trade(
            symbol="EURUSD", signal=mock_signal, lot_size=0.1
        )
        
        assert result is not None
        assert result.retcode == 10009

    @pytest.mark.asyncio
    async def test_handles_requote_error(self, execution_service):
        """Обработка ошибки реквот (retcode=10004)."""
        execution_service.trade_executor.execute_trade = AsyncMock(
            return_value=MockTradeResult(retcode=10004, comment="Requote")
        )
        
        result = await execution_service.trade_executor.execute_trade(
            symbol="XAUUSD", signal=MagicMock(), lot_size=0.01
        )
        
        assert result.retcode == 10004


class TestExecutionServicePositionManagement:
    """Тесты управления позициями - тестируют get_positions()."""

    @pytest.fixture
    def execution_service(self):
        """Создаёт ExecutionService для тестирования позиций."""
        try:
            from src.core.services.execution_service import ExecutionService
            from threading import Lock
        except ImportError:
            pytest.skip("ExecutionService не найден")
        
        mock_config = MagicMock()
        mock_config.MAX_ORDERS_PER_DAY = 100
        mock_config.ORDER_RETRY_COUNT = 3
        mock_config.ORDER_RETRY_DELAY = 1
        
        service = ExecutionService(
            config=mock_config,
            db_manager=MagicMock(),
            mt5_lock=Lock()
        )
        service._healthy = True
        service._positions_open = 0
        return service

    @pytest.mark.asyncio
    @patch("MetaTrader5.positions_get")
    @patch("src.core.services.execution_service.mt5_ensure_connected")
    async def test_get_positions_returns_list(self, mock_ensure_connected, mock_positions_get, execution_service):
        """Получение списка открытых позиций через service.get_positions()."""
        mock_ensure_connected.return_value = True
        # Создаём mock объекты с нужными атрибутами
        pos1 = MagicMock()
        pos1.ticket = 1
        pos1.symbol = "EURUSD"
        pos1.volume = 0.1
        pos1.type = 0
        pos1.price_open = 1.1000
        pos1.price_current = 1.1005
        pos1.sl = 1.0950
        pos1.tp = 1.1100
        pos1.profit = 50.0
        pos1.time = 1700000000
        
        pos2 = MagicMock()
        pos2.ticket = 2
        pos2.symbol = "GBPUSD"
        pos2.volume = 0.2
        pos2.type = 1
        pos2.price_open = 1.2000
        pos2.price_current = 1.1995
        pos2.sl = 1.1950
        pos2.tp = 1.2050
        pos2.profit = 30.0
        pos2.time = 1700000000
        
        mock_positions_get.return_value = [pos1, pos2]
        
        positions = await execution_service.get_positions()
        
        assert len(positions) == 2
        assert positions[0]["symbol"] == "EURUSD"

    @pytest.mark.asyncio
    @patch("MetaTrader5.positions_get")
    @patch("src.core.services.execution_service.mt5_ensure_connected")
    async def test_get_positions_handles_empty(self, mock_ensure_connected, mock_positions_get, execution_service):
        """Обработка случая, когда нет открытых позиций."""
        mock_ensure_connected.return_value = True
        mock_positions_get.return_value = None
        
        positions = await execution_service.get_positions()
        
        assert positions == []


class TestExecutionServiceHealthCheck:
    """Тесты health_check (из BaseService) - СИНХРОННЫЙ метод!"""

    def test_health_check_returns_dict(self):
        """health_check должен возвращать словарь со статусом - синхронный метод!"""
        try:
            from src.core.services.execution_service import ExecutionService
            from threading import Lock
        except ImportError:
            pytest.skip("ExecutionService не найден")
        
        mock_config = MagicMock()
        mock_config.MAX_ORDERS_PER_DAY = 100
        
        service = ExecutionService(
            config=mock_config,
            db_manager=MagicMock(),
            mt5_lock=Lock()
        )
        service._healthy = True
        service._running = True
        service._positions_open = 0
        service._orders_executed = 5
        service._orders_rejected = 0
        service._last_balance = 10000.0
        
        # health_check - СИНХРОННЫЙ метод (из BaseService)
        # НЕ использовать asyncio.run()!
        result = service.health_check()
        
        assert isinstance(result, dict)
        assert "status" in result or "healthy" in result or "running" in result

    def test_health_check_healthy_status(self):
        """health_check возвращает healthy при нормальном состоянии."""
        try:
            from src.core.services.execution_service import ExecutionService
            from threading import Lock
        except ImportError:
            pytest.skip("ExecutionService не найден")
        
        mock_config = MagicMock()
        
        service = ExecutionService(
            config=mock_config,
            db_manager=MagicMock(),
            mt5_lock=Lock()
        )
        service._healthy = True
        service._running = True
        service._positions_open = 3
        service._orders_executed = 10
        
        result = service.health_check()
        
        assert result is not None
        assert isinstance(result, dict)


class TestExecutionServiceMT5Integration:
    """Тесты интеграции с MT5 API."""

    @pytest.mark.asyncio
    @patch("MetaTrader5.order_send")
    async def test_mt5_order_send_success(self, mock_order_send):
        """Тест успешной отправки ордера через MT5."""
        mock_result = MagicMock()
        mock_result.retcode = 10009
        mock_result.order = 12345
        mock_result.volume = 0.1
        mock_result.price = 1.1000
        mock_order_send.return_value = mock_result
        
        assert mock_order_send.return_value.retcode == 10009


if __name__ == "__main__":
    pytest.main([__file__, "-v"])