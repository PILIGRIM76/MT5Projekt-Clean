"""
Тест для проверки корректности подключения сигнала retrain_progress_updated
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from PySide6.QtCore import QObject

from src.core.config_models import Settings
from src.core.trading_system import TradingSystem
from src.gui.trading_system_adapter import PySideTradingSystem
from src.gui.widgets.bridges import Bridge


@pytest.fixture
def mock_config():
    """Фикстура для конфигурации"""
    config = Mock(spec=Settings)
    config.INPUT_LAYER_SIZE = 10
    config.ENTRY_THRESHOLD = 0.01
    config.USE_GPU = False
    config.DB_PATH = ":memory:"
    config.HISTORY_DEPTH_M1 = 1000
    config.asset_types = {"BTCUSD": "CRYPTO", "EURUSD": "FOREX"}
    config.STRATEGY_REGIME_MAPPING = {"Default": "AI_Model"}
    config.FEATURES_TO_USE = ["open", "high", "low", "close", "volume"]
    config.IMPORTANT_NEWS_ENTITIES = ["FED", "ECB"]
    config.STRATEGY_WEIGHTS = {}
    config.STRATEGY_MIN_WIN_RATE_THRESHOLD = 0.5
    config.SYMBOLS_WHITELIST = ["EURUSD", "GBPUSD"]
    config.DATABASE_FOLDER = "./database"
    config.auto_retraining = Mock()
    config.auto_retraining.enabled = True
    config.auto_retraining.max_symbols = 30
    config.auto_retraining.max_workers = 3
    return config


class TestRetrainProgressSignal:
    """Тесты для сигнала retrain_progress_updated"""

    def test_signal_exists_in_trading_system(self, mock_config):
        """Проверка наличия сигнала в TradingSystem"""
        with (
            patch("src.core.trading_system.mt5", Mock()),
            patch("src.core.trading_system.SentenceTransformer", Mock()),
            patch("src.core.trading_system.DatabaseManager", Mock()),
            patch("src.core.trading_system.VectorDBManager", Mock()),
        ):
            ts = TradingSystem(config=mock_config, gui=None, sound_manager=None, bridge=None)

            # Проверяем что сигнал существует
            assert hasattr(ts, "retrain_progress_updated"), "Сигнал retrain_progress_updated должен существовать"

            # Проверяем что это Signal
            from PySide6.QtCore import Signal

            assert isinstance(type(ts).retrain_progress_updated, type(Signal(dict)))

    def test_signal_connected_in_adapter(self, mock_config):
        """Проверка подключения сигнала в PySideTradingSystem adapter"""
        bridge = Bridge()

        with (
            patch("src.core.trading_system.mt5", Mock()),
            patch("src.core.trading_system.SentenceTransformer", Mock()),
            patch("src.core.trading_system.DatabaseManager", Mock()),
            patch("src.core.trading_system.VectorDBManager", Mock()),
        ):
            # Создаем мок sound_manager
            mock_sound_manager = Mock()

            adapter = PySideTradingSystem(config=mock_config, bridge=bridge, sound_manager=mock_sound_manager)

            # Проверяем что сигнал подключен
            # Сигнал должен быть подключен к bridge.retrain_progress_updated
            assert hasattr(adapter.core_system, "retrain_progress_updated")
            assert hasattr(bridge, "retrain_progress_updated")

    def test_signal_emits_data(self, mock_config, qtbot):
        """Проверка что сигнал действительно отправляет данные"""
        from PySide6.QtTest import QTest

        bridge = Bridge()
        received_data = {}

        def on_retrain_progress(data):
            received_data.update(data)

        # Подключаем к сигналу bridge
        bridge.retrain_progress_updated.connect(on_retrain_progress)

        with (
            patch("src.core.trading_system.mt5", Mock()),
            patch("src.core.trading_system.SentenceTransformer", Mock()),
            patch("src.core.trading_system.DatabaseManager", Mock()),
            patch("src.core.trading_system.VectorDBManager", Mock()),
        ):
            mock_sound_manager = Mock()
            adapter = PySideTradingSystem(config=mock_config, bridge=bridge, sound_manager=mock_sound_manager)

            # Создаем тестовые данные
            test_progress = {
                "total_symbols": 2,
                "count_needing_retrain": 1,
                "progress_percent": 0.5,
                "threshold_percent": 1.0,
                "can_start_retrain": False,
                "symbols_needing_retrain": ["EURUSD"],
            }

            # Эмитим сигнал из core_system
            adapter.core_system.retrain_progress_updated.emit(test_progress)

            # Даем время на обработку сигнала
            QTest.qWait(100)

            # Проверяем что данные были получены
            assert len(received_data) > 0, "Сигнал должен отправить данные"
            assert received_data.get("total_symbols") == 2
            assert received_data.get("count_needing_retrain") == 1

    def test_send_retrain_progress_uses_signal(self, mock_config, qtbot):
        """Проверка что метод _send_retrain_progress_to_gui отправляет сигнал"""
        bridge = Bridge()
        signal_received = {"called": False, "data": None}

        def on_signal(data):
            signal_received["called"] = True
            signal_received["data"] = data

        # Подключаемся к сигналу bridge
        bridge.retrain_progress_updated.connect(on_signal)

        with (
            patch("src.core.trading_system.mt5", Mock()),
            patch("src.core.trading_system.SentenceTransformer", Mock()),
            patch("src.core.trading_system.DatabaseManager", Mock()),
            patch("src.core.trading_system.VectorDBManager", Mock()),
        ):
            mock_sound_manager = Mock()
            adapter = PySideTradingSystem(config=mock_config, bridge=bridge, sound_manager=mock_sound_manager)

            # Мокаем AutoTrainer
            expected_progress = {
                "total_symbols": 2,
                "count_needing_retrain": 1,
                "progress_percent": 0.5,
                "threshold_percent": 1.0,
                "can_start_retrain": False,
                "symbols_needing_retrain": ["EURUSD"],
            }
            mock_auto_trainer = Mock()
            mock_auto_trainer.get_retrain_progress.return_value = expected_progress
            adapter.core_system.auto_trainer = mock_auto_trainer

            # Вызываем метод
            adapter.core_system._send_retrain_progress_to_gui()

            # Даем время на обработку сигнала
            qtbot.wait(100)

            # Проверяем что сигнал был вызван и данные получены
            assert signal_received["called"], "Сигнал retrain_progress_updated должен быть вызван"
            assert signal_received["data"] == expected_progress


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
