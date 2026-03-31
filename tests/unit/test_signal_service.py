"""
Тесты для SignalService
"""

from unittest.mock import MagicMock, Mock, PropertyMock, patch

import numpy as np
import pandas as pd
import pytest
import torch

from src.core.services.signal_service import SignalService
from src.data_models import SignalType, TradeSignal


@pytest.fixture
def mock_config():
    """Фикстура для конфигурации"""
    config = Mock()
    config.INPUT_LAYER_SIZE = 10
    config.ENTRY_THRESHOLD = 0.01
    config.STRATEGY_MIN_WIN_RATE_THRESHOLD = 0.5
    config.STRATEGY_REGIME_MAPPING = {
        "Default": "MovingAverageCrossoverStrategy",
        "Trend": "MovingAverageCrossoverStrategy",
        "Ranging": "MeanReversionStrategy",
        "Volatile": "BreakoutStrategy",
    }
    config.STRATEGY_WEIGHTS = {
        "MovingAverageCrossoverStrategy": 1.0,
        "MeanReversionStrategy": 1.0,
        "BreakoutStrategy": 1.0,
    }
    config.FEATURES_TO_USE = ["open", "high", "low", "close", "volume"]
    config.asset_types = {"BTCUSD": "CRYPTO", "EURUSD": "FOREX"}
    config.IMPORTANT_NEWS_ENTITIES = ["FED", "ECB", "NFP"]
    return config


@pytest.fixture
def mock_market_regime_manager():
    """Фикстура для MarketRegimeManager"""
    manager = Mock()
    manager.get_regime = Mock(return_value="Trend")
    return manager


@pytest.fixture
def mock_strategies():
    """Фикстура для стратегий"""
    strategies = []
    for strategy_name in ["MovingAverageCrossoverStrategy", "MeanReversionStrategy", "BreakoutStrategy"]:
        strategy = Mock()
        strategy.__class__.__name__ = strategy_name
        strategy.check_entry_conditions = Mock(return_value=None)
        strategies.append(strategy)
    return strategies


@pytest.fixture
def mock_models():
    """Фикстура для моделей"""
    return {"BTCUSD": {}}


@pytest.fixture
def mock_scalers():
    """Фикстура для скалеров"""
    return {"BTCUSD": Mock()}


@pytest.fixture
def mock_consensus_engine():
    """Фикстура для ConsensusEngine"""
    engine = Mock()
    engine.calculate_multifactor_consensus = Mock(return_value=(SignalType.HOLD, 0.0))
    engine.calculate_on_chain_score = Mock(return_value=0.5)
    engine.get_historical_context_sentiment = Mock(return_value=0.3)
    return engine


@pytest.fixture
def mock_trading_system():
    """Фикстура для TradingSystem"""
    ts = Mock()
    ts.device = "cpu"
    return ts


@pytest.fixture
def sample_dataframe():
    """Фикстура для тестового DataFrame"""
    dates = pd.date_range(start="2024-01-01", periods=100, freq="h")
    df = pd.DataFrame(
        {
            "open": np.random.randn(100).cumsum() + 100,
            "high": np.random.randn(100).cumsum() + 101,
            "low": np.random.randn(100).cumsum() + 99,
            "close": np.random.randn(100).cumsum() + 100,
            "volume": np.random.randint(1000, 10000, 100),
        },
        index=dates,
    )
    return df


@pytest.fixture
def signal_service(
    mock_config,
    mock_market_regime_manager,
    mock_strategies,
    mock_models,
    mock_scalers,
    mock_consensus_engine,
    mock_trading_system,
):
    """Фикстура для SignalService"""
    return SignalService(
        config=mock_config,
        market_regime_manager=mock_market_regime_manager,
        strategies=mock_strategies,
        models=mock_models,
        x_scalers=mock_scalers,
        y_scalers=mock_scalers,
        strategy_performance={},
        consensus_engine=mock_consensus_engine,
        trading_system_ref=mock_trading_system,
    )


class TestSignalServiceInitialization:
    """Тесты инициализации SignalService"""

    def test_init(self, signal_service, mock_config):
        """Тест инициализации сервиса"""
        assert signal_service.config == mock_config
        assert signal_service.n_steps == mock_config.INPUT_LAYER_SIZE

    def test_init_with_empty_strategies(
        self, mock_config, mock_market_regime_manager, mock_consensus_engine, mock_trading_system
    ):
        """Тест инициализации с пустым списком стратегий"""
        service = SignalService(
            config=mock_config,
            market_regime_manager=mock_market_regime_manager,
            strategies=[],
            models={},
            x_scalers={},
            y_scalers={},
            strategy_performance={},
            consensus_engine=mock_consensus_engine,
            trading_system_ref=mock_trading_system,
        )
        assert service.strategies == []


class TestCreateSequencesForShap:
    """Тесты создания последовательностей для SHAP"""

    def test_create_sequences_success(self, signal_service):
        """Тест успешного создания последовательностей"""
        data = np.random.randn(20, 5)
        n_steps = 10
        sequences = signal_service._create_sequences_for_shap(data, n_steps)

        assert sequences is not None
        assert len(sequences) == 11  # 20 - 10 + 1
        assert sequences.shape[1:] == (n_steps, 5)

    def test_create_sequences_insufficient_data(self, signal_service):
        """Тест создания последовательностей при недостаточных данных"""
        data = np.random.randn(5, 5)
        n_steps = 10
        sequences = signal_service._create_sequences_for_shap(data, n_steps)

        assert sequences is None

    def test_create_sequences_exact_minimum(self, signal_service):
        """Тест создания последовательностей при минимальном количестве данных"""
        data = np.random.randn(11, 5)  # Нужно минимум n_steps + 1
        n_steps = 10
        sequences = signal_service._create_sequences_for_shap(data, n_steps)

        assert sequences is not None
        assert len(sequences) == 2  # 11 - 10 + 1 = 2


class TestGetClassicSignals:
    """Тесты получения классических сигналов"""

    def test_get_classic_signals_no_strategies(self, signal_service, sample_dataframe):
        """Тест получения сигналов без стратегий"""
        signal_service.strategies = []
        signals = signal_service._get_classic_signals(sample_dataframe, 60, "Trend", "BTCUSD")

        assert signals == []

    def test_get_classic_signals_with_relevant_strategy(self, signal_service, sample_dataframe, mock_config, mock_strategies):
        """Тест получения сигналов с релевантной стратегией"""
        # Настраиваем стратегию на возврат BUY сигнала
        buy_signal = TradeSignal(type="BUY", confidence=0.8, symbol="BTCUSD")
        mock_strategies[0].check_entry_conditions = Mock(return_value=buy_signal)

        signals = signal_service._get_classic_signals(sample_dataframe, 60, "Trend", "BTCUSD")

        assert len(signals) == 1
        assert signals[0].type == "BUY"  # type может быть строкой
        assert signals[0].confidence == 0.8

    def test_get_classic_signals_with_hold_signal(self, signal_service, sample_dataframe, mock_strategies):
        """Тест получения сигналов с HOLD сигналом"""
        hold_signal = TradeSignal(type="HOLD", confidence=0.5, symbol="BTCUSD")
        mock_strategies[0].check_entry_conditions = Mock(return_value=hold_signal)

        signals = signal_service._get_classic_signals(sample_dataframe, 60, "Trend", "BTCUSD")

        # HOLD сигналы добавляются в список, но фильтруются позже
        # Проверяем, что сигнал возвращен
        assert len(signals) == 1
        assert signals[0].type == "HOLD"

    def test_get_classic_signals_multiple_strategies(self, signal_service, sample_dataframe, mock_strategies):
        """Тест получения сигналов от нескольких стратегий"""
        buy_signal = TradeSignal(type="BUY", confidence=0.7, symbol="BTCUSD")
        sell_signal = TradeSignal(type="SELL", confidence=0.6, symbol="BTCUSD")

        mock_strategies[0].check_entry_conditions = Mock(return_value=buy_signal)
        # MeanReversionStrategy не релевантна для режима Trend, поэтому используем BreakoutStrategy
        mock_strategies[2].check_entry_conditions = Mock(return_value=sell_signal)

        signals = signal_service._get_classic_signals(sample_dataframe, 60, "Trend", "BTCUSD")

        # Только релевантные стратегии (Trend -> MovingAverageCrossoverStrategy)
        assert len(signals) >= 1


class TestGetTradeSignal:
    """Тесты основного метода get_trade_signal"""

    def test_get_trade_signal_empty_dataframe(self, signal_service):
        """Тест получения сигнала с пустым DataFrame"""
        result = signal_service.get_trade_signal("BTCUSD", pd.DataFrame(), 60, Mock())

        assert result is None

    def test_get_trade_signal_none_dataframe(self, signal_service):
        """Тест получения сигнала с None DataFrame"""
        result = signal_service.get_trade_signal("BTCUSD", None, 60, Mock())

        assert result is None

    def test_get_trade_signal_important_news_blocking(
        self, signal_service, sample_dataframe, mock_consensus_engine, mock_config
    ):
        """Тест блокировки сигнала из-за важных новостей"""
        consensus_result = Mock()
        consensus_result.relations = [{"subject": "FED", "relation": "announces", "object": "rate_decision"}]

        result = signal_service.get_trade_signal("BTCUSD", sample_dataframe, 60, consensus_result)

        assert result is None

    def test_get_trade_signal_no_ai_no_classic(
        self, signal_service, sample_dataframe, mock_consensus_engine, mock_market_regime_manager
    ):
        """Тест отсутствия сигнала при недоступности AI и классических стратегий"""
        mock_consensus_engine.calculate_multifactor_consensus = Mock(return_value=(SignalType.HOLD, 0.0))
        mock_market_regime_manager.get_regime = Mock(return_value="Trend")

        consensus_result = Mock()
        consensus_result.relations = []

        result = signal_service.get_trade_signal("BTCUSD", sample_dataframe, 60, consensus_result)

        assert result is None


class TestGetAiSignal:
    """Тесты получения AI сигнала"""

    def test_get_ai_signal_no_model(self, signal_service, sample_dataframe):
        """Тест получения AI сигнала без модели"""
        signal, pred_input, entry_price = signal_service._get_ai_signal("BTCUSD", sample_dataframe)

        assert signal is None
        assert pred_input is None
        assert entry_price is None

    def test_get_ai_signal_empty_committee(self, signal_service, sample_dataframe):
        """Тест получения AI сигнала с пустым комитетом"""
        signal_service.models["BTCUSD"] = {}

        signal, pred_input, entry_price = signal_service._get_ai_signal("BTCUSD", sample_dataframe)

        assert signal is None
        assert pred_input is None
        assert entry_price is None

    def test_get_ai_signal_with_model(self, signal_service, sample_dataframe):
        """Тест получения AI сигнала с моделью"""
        import torch.nn as nn

        # Создаем мок модель
        mock_model = Mock(spec=nn.Module)
        mock_model.return_value = torch.tensor([[0.5]])
        mock_model.eval = Mock()

        # Создаем мок скалеры
        mock_x_scaler = Mock()
        mock_x_scaler.transform = Mock(return_value=np.random.randn(10, 5))
        type(mock_x_scaler).n_features_in_ = PropertyMock(return_value=5)

        mock_y_scaler = Mock()
        mock_y_scaler.inverse_transform = Mock(return_value=np.array([[105.0]]))

        signal_service.models["BTCUSD"] = {
            "LSTM": {
                "model": mock_model,
                "features": ["open", "high", "low", "close", "volume"],
                "x_scaler": mock_x_scaler,  # Скалеры в model_data
                "y_scaler": mock_y_scaler,
            }
        }

        signal, pred_input, entry_price = signal_service._get_ai_signal("BTCUSD", sample_dataframe)

        # Проверяем, что модель была вызвана
        assert mock_model.eval.called
        # Проверяем, что скалеры были использованы
        assert mock_x_scaler.transform.called


class TestFindBestConfirmingStrategy:
    """Тесты поиска лучшей подтверждающей стратегии"""

    def test_find_best_confirming_strategy_no_match(self, signal_service, sample_dataframe, mock_strategies):
        """Тест поиска без совпадений"""
        ai_signal = TradeSignal(type=SignalType.BUY, confidence=0.8, symbol="BTCUSD")

        # Все стратегии возвращают HOLD или не совпадают
        for strategy in mock_strategies:
            strategy.check_entry_conditions = Mock(return_value=None)

        best_strategy, score = signal_service._find_best_confirming_strategy(ai_signal, sample_dataframe, "Trend", 60)

        assert best_strategy is None
        assert score == -1.0

    def test_find_best_confirming_strategy_with_match(self, signal_service, sample_dataframe, mock_strategies):
        """Тест поиска с совпадением"""
        ai_signal = TradeSignal(type=SignalType.BUY, confidence=0.8, symbol="BTCUSD")
        confirm_signal = TradeSignal(type=SignalType.BUY, confidence=0.7, symbol="BTCUSD")

        mock_strategies[0].check_entry_conditions = Mock(return_value=confirm_signal)

        signal_service.strategy_performance = {"MovingAverageCrossoverStrategy": {"total_trades": 10, "wins": 7}}

        best_strategy, score = signal_service._find_best_confirming_strategy(ai_signal, sample_dataframe, "Trend", 60)

        assert best_strategy is not None
        assert score > 0


class TestCalculateShapValues:
    """Тесты расчета SHAP значений"""

    def test_calculate_shap_values_no_model(self, signal_service, sample_dataframe):
        """Тест расчета SHAP без модели"""
        result = signal_service.calculate_shap_values(
            symbol="BTCUSD",
            prediction_input=np.random.randn(1, 10, 5),
            df_for_background=sample_dataframe,
        )

        assert result is None

    def test_calculate_shap_values_no_scaler(self, signal_service, sample_dataframe):
        """Тест расчета SHAP без скалера"""
        signal_service.models["BTCUSD"] = {"LSTM": {"model": Mock(), "features": ["close"]}}
        signal_service.x_scalers = {}

        result = signal_service.calculate_shap_values(
            symbol="BTCUSD",
            prediction_input=np.random.randn(1, 10, 5),
            df_for_background=sample_dataframe,
        )

        assert result is None


class TestGetPrimarySignal:
    """Тесты получения первичного сигнала"""

    def test_get_primary_signal_ai_model(self, signal_service, sample_dataframe, mock_config):
        """Тест получения сигнала от AI модели"""
        # Устанавливаем AI_Model как основную стратегию
        mock_config.STRATEGY_REGIME_MAPPING["Trend"] = "AI_Model"
        signal_service.models["BTCUSD"] = {}

        signal, name, _, pred_input, entry_price = signal_service.get_primary_signal("BTCUSD", sample_dataframe, 60, "Trend")

        # Нет реальной модели, поэтому сигнал None
        assert signal is None

    def test_get_primary_signal_classic_strategy(self, signal_service, sample_dataframe, mock_strategies):
        """Тест получения сигнала от классической стратегии"""
        buy_signal = TradeSignal(type="BUY", confidence=0.8, symbol="BTCUSD")
        mock_strategies[0].check_entry_conditions = Mock(return_value=buy_signal)

        signal, name, _, pred_input, entry_price = signal_service.get_primary_signal("BTCUSD", sample_dataframe, 60, "Trend")

        assert signal is not None
        assert signal.type == "BUY"  # type может быть строкой
        assert name == "MovingAverageCrossoverStrategy"


class TestGetConfirmedSignal:
    """Тесты получения подтвержденного сигнала"""

    def test_get_confirmed_signal_ai_confirmed(self, signal_service, sample_dataframe):
        """Тест получения подтвержденного AI сигнала"""
        ai_signal = TradeSignal(type=SignalType.BUY, confidence=0.8, symbol="BTCUSD")

        # Настраиваем поиск подтверждающей стратегии
        with patch.object(signal_service, "_find_best_confirming_strategy") as mock_find:
            confirm_strategy = Mock()
            confirm_strategy.__class__.__name__ = "MovingAverageCrossoverStrategy"
            mock_find.return_value = (confirm_strategy, 0.7)

            confirmed_signal, strategy_name, xai_data = signal_service.get_confirmed_signal(
                symbol="BTCUSD",
                df=sample_dataframe,
                timeframe=60,
                primary_signal=ai_signal,
                primary_strategy="AI_Model",
                xai_data=None,
            )

            assert confirmed_signal is not None
            assert "AI_Model_Confirmed_by" in strategy_name

    def test_get_confirmed_signal_classic_confirmed(self, signal_service, sample_dataframe):
        """Тест получения подтвержденного классического сигнала"""
        classic_signal = TradeSignal(type=SignalType.BUY, confidence=0.7, symbol="BTCUSD")

        # Настраиваем AI на подтверждение
        with patch.object(signal_service, "_get_ai_signal") as mock_ai:
            ai_signal = TradeSignal(type=SignalType.BUY, confidence=0.8, symbol="BTCUSD")
            mock_ai.return_value = (ai_signal, None, None)

            confirmed_signal, strategy_name, xai_data = signal_service.get_confirmed_signal(
                symbol="BTCUSD",
                df=sample_dataframe,
                timeframe=60,
                primary_signal=classic_signal,
                primary_strategy="MovingAverageCrossoverStrategy",
                xai_data=None,
            )

            assert confirmed_signal is not None
            assert "Confirmed_by_AI" in strategy_name
