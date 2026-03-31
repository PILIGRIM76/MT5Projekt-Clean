"""
Глобальные фикстуры и конфигурация pytest.

Предоставляет:
- Базовые фикстуры для тестов
- Моки для внешних зависимостей
- Утилиты для тестирования
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, Mock, patch

import pytest

# Добавляем src в path для импортов
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config_models import Settings
from src.core.event_bus import EventBus, event_bus

# Импорты компонентов
from src.core.events import Event, EventFactory, EventType

# ===========================================
# Logging Configuration
# ===========================================


@pytest.fixture(autouse=True)
def setup_logging() -> None:
    """Настройка логирования для всех тестов."""
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# ===========================================
# Event Bus Fixtures
# ===========================================


@pytest.fixture
def clean_event_bus() -> Generator[EventBus, None, None]:
    """
    Фикстура для очистки Event Bus между тестами.

    Usage:
        def test_something(clean_event_bus):
            clean_event_bus.publish(...)
    """
    # Очищаем подписчиков и историю
    event_bus._subscribers.clear()
    event_bus._async_subscribers.clear()
    event_bus._event_history.clear()

    yield event_bus

    # Cleanup после теста
    event_bus._subscribers.clear()
    event_bus._async_subscribers.clear()
    event_bus._event_history.clear()


@pytest.fixture
def event_bus_with_subscribers(clean_event_bus) -> EventBus:
    """Event Bus с тестовыми подписчиками."""

    def dummy_handler(event: Event):
        pass

    clean_event_bus.subscribe(EventType.TRADE_OPENED, dummy_handler)
    clean_event_bus.subscribe(EventType.SYSTEM_ERROR, dummy_handler)

    return clean_event_bus


# ===========================================
# Event Fixtures
# ===========================================


@pytest.fixture
def sample_trade_event() -> Event:
    """Пример события торговли."""
    return Event(
        type=EventType.TRADE_OPENED,
        timestamp=datetime(2026, 3, 31, 12, 0, 0),
        data={"symbol": "EURUSD", "lot": 0.1, "price": 1.1000, "ticket": 12345},
        source="TestTrader",
    )


@pytest.fixture
def sample_risk_event() -> Event:
    """Пример события риска."""
    return Event(
        type=EventType.RISK_CHECK_FAILED,
        timestamp=datetime(2026, 3, 31, 12, 0, 0),
        data={"reason": "Drawdown limit exceeded", "current_drawdown": 0.15, "max_drawdown": 0.10},
        source="RiskEngine",
    )


@pytest.fixture
def sample_system_event() -> Event:
    """Пример системного события."""
    return Event(
        type=EventType.SYSTEM_STARTED,
        timestamp=datetime(2026, 3, 31, 12, 0, 0),
        data={"version": "13.0.0", "mode": "backtest"},
        source="TradingSystem",
    )


# ===========================================
# Config Fixtures
# ===========================================


@pytest.fixture
def minimal_config() -> Settings:
    """Минимальная конфигурация для тестов."""
    from src.core.config_models import (
        AnomalyDetectorSettings,
        ConsensusWeights,
        OnlineLearningSettings,
        RDCycleSettings,
        StrategiesParams,
    )

    return Settings(
        MT5_LOGIN="test_login",
        MT5_PASSWORD="test_password",
        MT5_SERVER="test_server",
        MT5_PATH="C:\\test\\terminal64.exe",
        FINNHUB_API_KEY="test",
        ALPHA_VANTAGE_API_KEY="test",
        NEWS_API_KEY="test",
        POLYGON_API_KEY="test",
        TWELVE_DATA_API_KEY="test",
        FCS_API_KEY="test",
        TELEGRAM_API_ID="test",
        TELEGRAM_API_HASH="test",
        TWITTER_BEARER_TOKEN="test",
        SANTIMENT_API_KEY="test",
        NEO4J_URI="bolt://localhost:7687",
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD="test",
        FRED_API_KEY="test",
        SYMBOLS_WHITELIST=["EURUSD"],
        FEATURES_TO_USE=["feature1"],
        GP_POPULATION_SIZE=50,
        GP_GENERATIONS=20,
        GP_MUTATION_RATE=0.1,
        GP_CROSSOVER_RATE=0.8,
        GP_ELITISM_SIZE=5,
        GP_TOURNAMENT_SIZE=10,
        GP_TRIGGER_WIN_RATE=0.55,
        GP_MIN_TRADES_SAMPLE=30,
        ENTRY_THRESHOLD=0.001,
        CONSENSUS_THRESHOLD=0.6,
        SENTIMENT_THRESHOLD=0.5,
        DIVERGENCE_BLOCK_MINUTES=5,
        RISK_PERCENTAGE=0.02,
        DYNAMIC_RISK_MIN_PERCENT=0.01,
        STOP_LOSS_ATR_MULTIPLIER=2.0,
        RISK_REWARD_RATIO=2.0,
        MAX_DAILY_DRAWDOWN_PERCENT=0.05,
        MAX_OPEN_POSITIONS=5,
        CORRELATION_THRESHOLD=0.8,
        INPUT_LAYER_SIZE=60,
        TRAINING_DATA_POINTS=1000,
        PREDICTION_DATA_POINTS=100,
        CONSENSUS_WEIGHTS=ConsensusWeights(ai_forecast=0.5, classic_strategies=0.3, sentiment_kg=0.1, on_chain_data=0.1),
        # Добавляем недостающие поля
        STRATEGY_REGIME_MAPPING={"Default": "AI_Model"},
        STRATEGY_WEIGHTS={"AI_Model": 1.0},
        NEWS_CACHE_DURATION_MINUTES=60,
        trading_sessions={"session1": ["09:00", "17:00"]},
        asset_types={"EURUSD": "forex"},
        DATABASE_FOLDER="test_db",
        DATABASE_NAME="test.db",
        TRADE_INTERVAL_SECONDS=1,
        TRAINING_INTERVAL_SECONDS=300,
        EXCLUDED_SYMBOLS=[],
        rd_cycle_config=RDCycleSettings(),
        online_learning=OnlineLearningSettings(),
        anomaly_detector=AnomalyDetectorSettings(),
        EVENT_BLOCK_WINDOW_HOURS=2,
        ALLOW_WEEKEND_TRADING=True,
        strategies=StrategiesParams(),
    )


@pytest.fixture
def full_config() -> Settings:
    """Полная конфигурация для тестов."""
    from src.core.config_models import ConsensusWeights

    return Settings(
        MT5_LOGIN="test_login",
        MT5_PASSWORD="test_password",
        MT5_SERVER="test_server",
        MT5_PATH="C:\\test\\terminal64.exe",
        FINNHUB_API_KEY="test",
        ALPHA_VANTAGE_API_KEY="test",
        NEWS_API_KEY="test",
        POLYGON_API_KEY="test",
        TWELVE_DATA_API_KEY="test",
        FCS_API_KEY="test",
        TELEGRAM_API_ID="test",
        TELEGRAM_API_HASH="test",
        TWITTER_BEARER_TOKEN="test",
        SANTIMENT_API_KEY="test",
        NEO4J_URI="bolt://localhost:7687",
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD="test",
        FRED_API_KEY="test",
        SYMBOLS_WHITELIST=["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
        FEATURES_TO_USE=["feature1", "feature2"],
        GP_POPULATION_SIZE=100,
        GP_GENERATIONS=50,
        GP_MUTATION_RATE=0.1,
        GP_CROSSOVER_RATE=0.8,
        GP_ELITISM_SIZE=10,
        GP_TOURNAMENT_SIZE=20,
        GP_TRIGGER_WIN_RATE=0.55,
        GP_MIN_TRADES_SAMPLE=50,
        ENTRY_THRESHOLD=0.001,
        CONSENSUS_THRESHOLD=0.6,
        SENTIMENT_THRESHOLD=0.5,
        DIVERGENCE_BLOCK_MINUTES=10,
        RISK_PERCENTAGE=0.02,
        DYNAMIC_RISK_MIN_PERCENT=0.01,
        STOP_LOSS_ATR_MULTIPLIER=3.0,
        RISK_REWARD_RATIO=2.5,
        MAX_DAILY_DRAWDOWN_PERCENT=0.05,
        MAX_OPEN_POSITIONS=10,
        CORRELATION_THRESHOLD=0.8,
        MAX_PORTFOLIO_VAR_PERCENT=0.03,
        PORTFOLIO_VOLATILITY_THRESHOLD=0.05,
        INPUT_LAYER_SIZE=60,
        TRAINING_DATA_POINTS=2000,
        PREDICTION_DATA_POINTS=300,
        CONSENSUS_WEIGHTS=ConsensusWeights(ai_forecast=0.5, classic_strategies=0.3, sentiment_kg=0.1, on_chain_data=0.1),
    )


# ===========================================
# Mock Fixtures
# ===========================================


@pytest.fixture
def mock_mt5() -> MagicMock:
    """Мок для MetaTrader5."""
    mt5 = MagicMock()

    # Мокирование основных методов MT5
    mt5.initialize.return_value = True
    mt5.last_error.return_value = (0, "Success")
    mt5.positions_get.return_value = []
    mt5.orders_get.return_value = []
    mt5.symbol_select.return_value = True
    mt5.symbol_info_tick.return_value = Mock(ask=1.1000, bid=1.0998, time=datetime.utcnow())
    mt5.order_send.return_value = Mock(retcode=10009, deal=12345, order=12345)

    return mt5


@pytest.fixture
def mock_database_manager() -> MagicMock:
    """Мок для DatabaseManager."""
    db_manager = MagicMock()
    db_manager.Session = MagicMock()
    db_manager.get_session.return_value = MagicMock()
    db_manager.init_models.return_value = True
    return db_manager


@pytest.fixture
def mock_vector_db_manager() -> MagicMock:
    """Мок для VectorDBManager."""
    vector_db = MagicMock()
    vector_db.is_ready.return_value = True
    vector_db.search.return_value = []
    vector_db.add.return_value = True
    vector_db.query_similar.return_value = {"ids": [["doc1", "doc2"]], "distances": [[0.1, 0.2]]}
    return vector_db


@pytest.fixture
def mock_embedding_model() -> MagicMock:
    """Мок для embedding модели."""
    import numpy as np

    model = MagicMock()
    model.encode.return_value = np.array([0.1, 0.2, 0.3])
    return model


@pytest.fixture
def mock_data_provider() -> MagicMock:
    """Мок для DataProvider."""
    provider = MagicMock()
    provider.get_historical_data.return_value = Mock()
    provider.get_real_time_data.return_value = Mock()
    return provider


@pytest.fixture
def mock_model_factory() -> MagicMock:
    """Мок для ModelFactory."""
    factory = MagicMock()
    factory.load_model.return_value = Mock()
    factory.train_model.return_value = Mock()
    factory.predict.return_value = 0.5
    return factory


@pytest.fixture
def mock_risk_engine() -> MagicMock:
    """Мок для RiskEngine."""
    engine = MagicMock()
    engine.check_trade.return_value = True
    engine.calculate_var.return_value = 0.01
    engine.calculate_drawdown.return_value = 0.05
    return engine


@pytest.fixture
def mock_trading_system() -> MagicMock:
    """Мок для TradingSystem."""
    system = MagicMock()
    system.is_connected.return_value = True
    system.get_balance.return_value = 10000.0
    system.get_equity.return_value = 10050.0
    system.open_position.return_value = True
    system.close_position.return_value = True
    return system


# ===========================================
# Async Fixtures
# ===========================================


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Создание event loop для асинхронных тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def async_event_bus() -> Generator[EventBus, None, None]:
    """Асинхронный Event Bus для тестов."""
    event_bus._subscribers.clear()
    event_bus._async_subscribers.clear()
    event_bus._event_history.clear()

    yield event_bus

    event_bus._subscribers.clear()
    event_bus._async_subscribers.clear()
    event_bus._event_history.clear()


# ===========================================
# Utility Fixtures
# ===========================================


@pytest.fixture
def temp_directory(tmp_path: Path) -> Path:
    """Временная директория для тестов."""
    test_dir = tmp_path / "genesis_test"
    test_dir.mkdir()
    return test_dir


@pytest.fixture
def sample_market_data() -> Dict[str, Any]:
    """Пример рыночных данных."""
    return {
        "symbol": "EURUSD",
        "timeframe": 60,
        "data": {
            "open": [1.0990, 1.0995, 1.1000, 1.1005, 1.1010],
            "high": [1.0998, 1.1003, 1.1008, 1.1013, 1.1018],
            "low": [1.0985, 1.0990, 1.0995, 1.1000, 1.1005],
            "close": [1.0995, 1.1000, 1.1005, 1.1010, 1.1015],
            "tick_volume": [100, 150, 200, 250, 300],
        },
        "timestamp": datetime.utcnow(),
    }


@pytest.fixture
def sample_portfolio() -> Dict[str, Any]:
    """Пример портфеля."""
    return {
        "balance": 10000.0,
        "equity": 10150.0,
        "positions": [
            {"symbol": "EURUSD", "type": "BUY", "lots": 0.1, "price_open": 1.0950, "price_current": 1.1000, "pnl": 50.0}
        ],
        "daily_pnl": 150.0,
        "drawdown": 0.02,
    }


# ===========================================
# Event Factory Fixtures
# ===========================================


@pytest.fixture
def event_factory() -> EventFactory:
    """Фабрика событий для тестов."""
    return EventFactory()


@pytest.fixture
def trade_opened_event(event_factory) -> Event:
    """Событие открытия сделки."""
    return event_factory.create_trade_opened(
        symbol="EURUSD",
        lot=0.1,
        order_type="BUY",
        price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        strategy_name="TestStrategy",
        ticket=12345,
    )


@pytest.fixture
def trade_closed_event(event_factory) -> Event:
    """Событие закрытия сделки."""
    return event_factory.create_trade_closed(ticket=12345, symbol="EURUSD", pnl=50.0, close_reason="TP")


@pytest.fixture
def system_error_event(event_factory) -> Event:
    """Событие системной ошибки."""
    return event_factory.create_system_error(
        component="TestComponent", message="Test error message", error_details="Detailed error information"
    )


# ===========================================
# Risk Engine Fixtures
# ===========================================


@pytest.fixture
def mock_kg_querier() -> MagicMock:
    """Мок для Knowledge Graph Querier."""
    kg = MagicMock()
    kg.find_events_affecting_entities.return_value = []
    return kg


@pytest.fixture
def mock_config() -> Settings:
    """Мок конфигурации для ML тестов."""
    config = MagicMock(spec=Settings)
    config.CONSENSUS_WEIGHTS = MagicMock()
    config.CONSENSUS_WEIGHTS.ai_forecast = 0.5
    config.CONSENSUS_WEIGHTS.classic_strategies = 0.3
    config.CONSENSUS_WEIGHTS.sentiment_kg = 0.1
    config.CONSENSUS_WEIGHTS.on_chain_data = 0.1
    config.CONSENSUS_THRESHOLD = 0.6
    config.vector_db = MagicMock()
    config.vector_db.enabled = True
    config.vector_db.embedding_model = "test-model"
    config.vector_db.path = "test_path"
    config.db_manager = MagicMock()
    return config


@pytest.fixture
def mock_settings() -> Settings:
    """
    Универсальный мок Settings для всех тестов.

    Используется когда не нужна полная конфигурация.
    """
    settings = MagicMock(spec=Settings)

    # Risk settings
    settings.risk = MagicMock()
    settings.risk.max_drawdown = 0.10
    settings.risk.max_daily_loss = 0.05
    settings.risk.var_confidence = 0.95
    settings.risk.max_var = 0.02
    settings.risk.confidence_risk_map = {0.9: 0.02, 0.7: 0.015, 0.5: 0.01}
    settings.risk.toxic_regime_update_interval_sec = 300
    settings.risk.toxic_regime_risk_multiplier = 0.5
    settings.risk.recent_trades_for_dynamic_risk = 10
    settings.risk.drawdown_sensitivity_threshold = 5.0

    # General settings
    settings.RISK_PERCENTAGE = 0.02
    settings.DYNAMIC_RISK_MIN_PERCENT = 0.01
    settings.CORRELATION_THRESHOLD = 0.8
    settings.MAX_DAILY_DRAWDOWN_PERCENT = 0.05
    settings.PORTFOLIO_VOLATILITY_THRESHOLD = 0.15
    settings.MAX_PORTFOLIO_VAR_PERCENT = 0.03
    settings.IGNORE_HISTORICAL_DRAWDOWN_ON_START = False
    settings.EVENT_BLOCK_WINDOW_HOURS = 2
    settings.ALLOW_WEEKEND_TRADING = True

    # ML settings
    settings.CONSENSUS_WEIGHTS = MagicMock()
    settings.CONSENSUS_WEIGHTS.ai_forecast = 0.5
    settings.CONSENSUS_WEIGHTS.classic_strategies = 0.3
    settings.CONSENSUS_WEIGHTS.sentiment_kg = 0.1
    settings.CONSENSUS_WEIGHTS.on_chain_data = 0.1
    settings.CONSENSUS_THRESHOLD = 0.6

    settings.vector_db = MagicMock()
    settings.vector_db.enabled = True
    settings.vector_db.embedding_model = "test-model"
    settings.vector_db.path = "test_path"

    # Alerting settings
    settings.alerting = MagicMock()
    settings.alerting.enabled = True
    settings.alerting.channels = MagicMock()
    settings.alerting.channels.telegram = MagicMock()
    settings.alerting.channels.telegram.enabled = False
    settings.alerting.channels.telegram.chat_id = "test_chat_id"
    # Настраиваем .get() для telegram_config чтобы возвращал строки
    telegram_config = MagicMock()
    telegram_config.enabled = False
    telegram_config.chat_id = "test_chat_id"
    telegram_config.get.side_effect = lambda key, default=None: {
        "bot_token_env": "TELEGRAM_BOT_TOKEN",
        "chat_id_env": "TELEGRAM_CHAT_ID",
        "enabled": False,
    }.get(key, default)
    settings.alerting.channels.telegram = telegram_config

    settings.alerting.channels.email = MagicMock()
    settings.alerting.channels.email.enabled = False
    settings.alerting.channels.email.address = "test@example.com"
    settings.alerting.channels.push = MagicMock()
    settings.alerting.channels.push.enabled = False
    settings.alerting.rate_limit = MagicMock()
    settings.alerting.rate_limit.max_per_minute = 10
    settings.alerting.rate_limit.cooldown_seconds = 60
    settings.alerting.quiet_hours = MagicMock()
    settings.alerting.quiet_hours.enabled = False
    settings.alerting.quiet_hours.start = "22:00"
    settings.alerting.quiet_hours.end = "08:00"
    settings.alerting.quiet_hours.timezone = "UTC"
    settings.alerting.daily_digest = MagicMock()
    settings.alerting.daily_digest.enabled = True
    settings.alerting.daily_digest.time = "20:00"
    settings.alerting.daily_digest.timezone = "UTC"

    return settings


@pytest.fixture
def consensus_engine(mock_config, mock_db_manager, mock_vector_db_manager, mock_embedding_model):
    """Фикстура для создания ConsensusEngine."""
    from src.ml.consensus_engine import ConsensusEngine

    engine = ConsensusEngine(config=mock_config, db_manager=mock_db_manager, vector_db_manager=mock_vector_db_manager)
    engine.embedding_model = mock_embedding_model

    # Мокаем sentiment pipeline
    engine.sentiment_pipeline = MagicMock()
    engine.sentiment_pipeline.return_value = [{"label": "positive", "score": 0.9}]

    return engine


@pytest.fixture
def risk_engine(minimal_config, mock_trading_system, mock_kg_querier):
    """
    Фикстура для создания RiskEngine.

    Usage:
        def test_something(risk_engine):
            risk_engine.check_trade(...)
    """
    with patch("src.risk.risk_engine.VolatilityForecaster"):
        with patch("src.risk.risk_engine.StressTester"):
            with patch("src.risk.risk_engine.AnomalyDetector"):
                from src.risk.risk_engine import RiskEngine

                return RiskEngine(
                    config=minimal_config,
                    trading_system_ref=mock_trading_system,
                    querier=mock_kg_querier,
                    mt5_lock=MagicMock(),
                    is_simulation=True,
                )


@pytest.fixture
def mock_bridge():
    """
    Фикстура для создания мок объекта Bridge.

    Используется для тестов TradingSystem и других компонентов,
    требующих bridge для связи с GUI.

    Usage:
        def test_something(mock_bridge):
            ts = TradingSystem(config, bridge=mock_bridge)
    """
    bridge = MagicMock()

    # Настраиваем основные сигналы bridge
    bridge.status_updated = MagicMock()
    bridge.balance_updated = MagicMock()
    bridge.log_message_added = MagicMock()
    bridge.positions_updated = MagicMock()
    bridge.history_updated = MagicMock()
    bridge.training_history_updated = MagicMock()
    bridge.candle_chart_updated = MagicMock()
    bridge.pnl_updated = MagicMock()
    bridge.market_scan_updated = MagicMock()
    bridge.trading_signals_updated = MagicMock()
    bridge.uptime_updated = MagicMock()
    bridge.rd_progress_updated = MagicMock()
    bridge.xai_data_ready = MagicMock()
    bridge.all_positions_closed = MagicMock()
    bridge.backtest_finished = MagicMock()
    bridge.market_regime_updated = MagicMock()
    bridge.update_status_changed = MagicMock()
    bridge.initialization_successful = MagicMock()
    bridge.initialization_failed = MagicMock()
    bridge.directives_updated = MagicMock()
    bridge.times_updated = MagicMock()
    bridge.model_list_updated = MagicMock()
    bridge.orchestrator_allocation_updated = MagicMock()
    bridge.knowledge_graph_updated = MagicMock()
    bridge.observer_pnl_updated = MagicMock()
    bridge.vector_db_search_results = MagicMock()
    bridge.thread_status_updated = MagicMock()
    bridge.long_task_status_updated = MagicMock()
    bridge.heavy_initialization_finished = MagicMock()
    bridge.drift_data_updated = MagicMock()
    bridge.pnl_kpis_updated = MagicMock()

    return bridge
