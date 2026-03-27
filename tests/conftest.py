# tests/conftest.py
"""
Фикстуры pytest для Genesis Trading System.

Содержит:
- Общие фикстуры для всех тестов
- Моки для внешних зависимостей
- Тестовые данные
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock
from typing import Dict, Any, List


# ===========================================
# Общие фикстуры
# ===========================================

@pytest.fixture
def sample_market_data() -> pd.DataFrame:
    """
    Пример рыночных данных для тестов.
    
    Returns:
        DataFrame с OHLCV данными
    """
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=500, freq='H')
    
    return pd.DataFrame({
        'open': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001),
        'high': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001) + 0.0005,
        'low': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001) - 0.0005,
        'close': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001),
        'tick_volume': np.random.randint(100, 1000, 500)
    }, index=dates)


@pytest.fixture
def sample_trade_data() -> Dict[str, Any]:
    """
    Пример данных сделки для тестов.
    
    Returns:
        Словарь с данными сделки
    """
    return {
        'ticket': 12345,
        'symbol': 'EURUSD',
        'strategy': 'BreakoutStrategy',
        'trade_type': 'BUY',
        'volume': 0.1,
        'price_open': 1.1000,
        'price_close': 1.1050,
        'time_open': datetime.now() - timedelta(hours=2),
        'time_close': datetime.now(),
        'profit': 50.0,
        'timeframe': 'H1'
    }


@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """
    Пример конфигурации для тестов.
    
    Returns:
        Словарь с конфигурацией
    """
    return {
        'RISK_PERCENTAGE': 0.5,
        'MAX_OPEN_POSITIONS': 5,
        'SYMBOLS_WHITELIST': ['EURUSD', 'GBPUSD', 'USDJPY'],
        'MT5_LOGIN': '12345678',
        'MT5_PASSWORD': 'test_password',
        'MT5_SERVER': 'Test-Demo'
    }


# ===========================================
# Моки для внешних зависимостей
# ===========================================

@pytest.fixture
def mock_mt5():
    """
    Мок для MetaTrader5.
    
    Использование:
        def test_something(mock_mt5):
            # MetaTrader5 автоматически замокан
            ...
    """
    with pytest.MonkeyPatch.context() as mp:
        mt5_mock = MagicMock()
        mt5_mock.initialize.return_value = True
        mt5_mock.last_error.return_value = (0, '')
        mt5_mock.account_info.return_value = MagicMock(
            balance=100000,
            equity=100500,
            margin=0,
            margin_free=100000,
            margin_level=0
        )
        mt5_mock.positions_get.return_value = []
        mt5_mock.orders_get.return_value = []
        mt5_mock.symbol_get.return_value = MagicMock(
            spread=10,
            volume_min=0.01,
            volume_max=100,
            volume_step=0.01
        )
        mp.setattr('MetaTrader5', mt5_mock)
        yield mt5_mock


@pytest.fixture
def mock_db_manager():
    """
    Мок для DatabaseManager.
    
    Returns:
        MagicMock с методами DB
    """
    db_mock = MagicMock()
    db_mock.Session = MagicMock()
    db_mock.save_trade.return_value = 1
    db_mock.get_trade_history.return_value = []
    db_mock.get_open_positions.return_value = []
    return db_mock


@pytest.fixture
def mock_risk_engine():
    """
    Мок для RiskEngine.
    
    Returns:
        MagicMock с методами RiskEngine
    """
    risk_mock = MagicMock()
    risk_mock.calculate_position_size.return_value = (0.1, 0.0050)
    risk_mock.is_trade_safe.return_value = True
    risk_mock.check_daily_drawdown.return_value = True
    risk_mock.check_correlation.return_value = True
    risk_mock.calculate_portfolio_var.return_value = 0.01
    return risk_mock


@pytest.fixture
def mock_data_provider():
    """
    Мок для DataProvider.
    
    Returns:
        MagicMock с методами DataProvider
    """
    data_mock = MagicMock()
    data_mock.get_historical_data.return_value = pd.DataFrame({
        'open': [1.1000] * 100,
        'high': [1.1010] * 100,
        'low': [1.0990] * 100,
        'close': [1.1005] * 100,
        'tick_volume': [500] * 100
    })
    data_mock.get_realtime_quotes.return_value = {
        'EURUSD': {'bid': 1.1000, 'ask': 1.1002}
    }
    data_mock.get_news.return_value = []
    return data_mock


@pytest.fixture
def mock_event_bus():
    """
    Мок для Event Bus.
    
    Returns:
        MagicMock с методами EventBus
    """
    event_mock = MagicMock()
    event_mock.subscribe = MagicMock()
    event_mock.publish = MagicMock()
    event_mock.unsubscribe = MagicMock()
    return event_mock


# ===========================================
# Фикстуры для компонентов
# ===========================================

@pytest.fixture
def mock_trading_system():
    """
    Мок для TradingSystem.
    
    Returns:
        MagicMock с методами TradingSystem
    """
    ts_mock = MagicMock()
    ts_mock.running = False
    ts_mock.observer_mode = False
    ts_mock.start = MagicMock()
    ts_mock.stop = MagicMock()
    ts_mock.execute_trade = MagicMock(return_value=True)
    ts_mock.close_position = MagicMock(return_value=True)
    ts_mock.get_account_info = MagicMock(return_value={
        'balance': 100000,
        'equity': 100500
    })
    return ts_mock


@pytest.fixture
def mock_strategy():
    """
    Мок для стратегии.
    
    Returns:
        MagicMock с методами IStrategy
    """
    strategy_mock = MagicMock()
    strategy_mock.name = "TestStrategy"
    strategy_mock.generate_signal.return_value = {
        'type': 'BUY',
        'symbol': 'EURUSD',
        'confidence': 0.75,
        'lot': 0.1
    }
    strategy_mock.get_parameters.return_value = {}
    strategy_mock.set_parameters = MagicMock()
    return strategy_mock


# ===========================================
# Фикстуры для тестов с БД
# ===========================================

@pytest.fixture
def test_db_path(tmp_path) -> str:
    """
    Путь к тестовой БД.
    
    Args:
        tmp_path: Временная директоря pytest
        
    Returns:
        Путь к тестовой БД
    """
    return str(tmp_path / "test_trading.db")


@pytest.fixture
def clean_db_session(test_db_path):
    """
    Чистая сессия БД для тестов.
    
    Использование:
        def test_with_db(clean_db_session):
            # Работа с чистой БД
            ...
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(f"sqlite:///{test_db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        yield session
    finally:
        session.close()


# ===========================================
# Фикстуры для асинхронных тестов
# ===========================================

@pytest.fixture
def mock_async_websocket():
    """
    Мок для асинхронного WebSocket.
    
    Returns:
        AsyncMock для WebSocket
    """
    ws_mock = AsyncMock()
    ws_mock.accept = AsyncMock()
    ws_mock.send_json = AsyncMock()
    ws_mock.receive_json = AsyncMock()
    ws_mock.receive_text = AsyncMock()
    ws_mock.close = AsyncMock()
    return ws_mock


# ===========================================
# Утилиты для тестов
# ===========================================

@pytest.fixture
def test_logger():
    """
    Тестовый логгер.
    
    Returns:
        Настроенный логгер
    """
    import logging
    
    logger = logging.getLogger('test_logger')
    logger.setLevel(logging.DEBUG)
    
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger
