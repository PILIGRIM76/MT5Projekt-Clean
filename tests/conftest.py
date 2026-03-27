# tests/conftest.py
"""
Конфигурация и фикстуры для pytest.
"""

import pytest
import sys
from pathlib import Path

# Добавляем src в path для импортов
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


@pytest.fixture
def mock_config():
    """Фикстура для тестовой конфигурации"""
    from src.core.config_models import Settings
    
    return Settings(
        MT5_LOGIN="12345",
        MT5_PASSWORD="test_password",
        MT5_SERVER="TestServer",
        MT5_PATH="C:\\test\\mt5\\terminal64.exe",
        SYMBOLS_WHITELIST=["EURUSD", "GBPUSD"],
        FEATURES_TO_USE=["close", "ATR_14", "RSI_14"],
        RISK_PERCENTAGE=0.5,
        MAX_OPEN_POSITIONS=5,
        MAX_DAILY_DRAWDOWN_PERCENT=5.0,
        DATABASE_FOLDER="test_database",
    )


@pytest.fixture
def mock_bridge():
    """Фикстура для mock GUI bridge"""
    class MockBridge:
        def __init__(self):
            self.signals_sent = []
        
        def emit(self, *args):
            self.signals_sent.append(args)
    
    return MockBridge()


@pytest.fixture
def mock_mt5_lock():
    """Фикстура для mock MT5 lock"""
    import threading
    return threading.Lock()


@pytest.fixture
def sample_dataframe():
    """Фикстура для тестового DataFrame"""
    import pandas as pd
    import numpy as np
    
    dates = pd.date_range(start='2024-01-01', periods=100, freq='H')
    df = pd.DataFrame({
        'open': np.random.rand(100) * 100,
        'high': np.random.rand(100) * 100 + 1,
        'low': np.random.rand(100) * 100 - 1,
        'close': np.random.rand(100) * 100,
        'ATR_14': np.random.rand(100) * 0.01,
        'RSI_14': np.random.rand(100) * 100,
    }, index=dates)
    
    return df
