"""
E2E тесты для Genesis Trading System

Требования:
- Демо-счет MetaTrader 5
- Настроенный .env файл с credentials
- Запущенный MT5 терминал

Запуск:
    pytest tests/e2e/ -v --e2e

Примечание: E2E тесты не запускаются с обычными тестами!
"""

import os

import MetaTrader5 as mt5
import pytest


@pytest.fixture(scope="session")
def mt5_connection():
    """Фикстура для подключения к MT5"""
    # Проверка переменных окружения
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not all([login, password, server]):
        pytest.skip("MT5 credentials не настроены. Пропуск E2E тестов.")

    # Инициализация MT5
    if not mt5.initialize(login=int(login), password=password, server=server):
        pytest.skip(f"MT5 не запустился. Error: {mt5.last_error()}")

    yield mt5

    # Shutdown
    mt5.shutdown()


@pytest.mark.e2e
class TestMT5Connection:
    """E2E тесты подключения к MT5"""

    def test_mt5_initialized(self, mt5_connection):
        """Тест успешного подключения к MT5"""
        assert mt5_connection is not None
        assert mt5_connection.terminal_info().connected

    def test_account_info(self, mt5_connection):
        """Тест получения информации о счете"""
        account_info = mt5_connection.account_info()
        assert account_info is not None
        assert account_info.login > 0
        assert account_info.server

    def test_market_watch(self, mt5_connection):
        """Тест получения списка символов"""
        symbols = mt5_connection.symbols_get()
        assert symbols is not None
        assert len(symbols) > 0


@pytest.mark.e2e
class TestTradingFlow:
    """E2E тесты полного цикла торговли"""

    def test_get_candle_data(self, mt5_connection):
        """Тест получения свечных данных"""
        rates = mt5_connection.copy_rates_from_pos("EURUSD", mt5_connection.TIMEFRAME_H1, 0, 100)
        assert rates is not None
        assert len(rates) > 0

    def test_check_symbol_info(self, mt5_connection):
        """Тест получения информации о символе"""
        symbol_info = mt5_connection.symbol_info("EURUSD")
        assert symbol_info is not None
        assert symbol_info.visible

    def test_get_position(self, mt5_connection):
        """Тест получения открытых позиций"""
        positions = mt5_connection.positions_get()
        # Позиции могут отсутствовать - это нормально
        assert positions is not None or positions == []


@pytest.mark.e2e
class TestTradingSystemIntegration:
    """E2E тесты интеграции с TradingSystem"""

    def test_trading_system_init(self, mt5_connection):
        """Тест инициализации TradingSystem"""
        from src.core.config_models import Settings
        from src.core.trading_system import TradingSystem

        config = Settings()
        ts = TradingSystem(config=config, gui=None, sound_manager=None, bridge=None)

        assert ts is not None
        assert ts.config is not None

    def test_data_provider_connection(self, mt5_connection):
        """Тест подключения DataProvider"""
        from src.data.data_provider import DataProvider

        dp = DataProvider()
        data = dp.get_historical_data("EURUSD", mt5_connection.TIMEFRAME_H1, 100)

        assert data is not None
        assert len(data) > 0
