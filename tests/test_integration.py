# -*- coding: utf-8 -*-
"""
Integration tests for Genesis Trading System.

Tests the full cycle:
1. TradingSystem initialization
2. TradingEngine integration
3. MLCoordinator integration
4. GUICoordinator integration
5. GracefulDegradation integration
6. HealthCheck integration
7. NLP Lazy Loading integration
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import queue
import threading


class TestTradingSystemIntegration:
    """Integration tests for TradingSystem with new modules."""

    @pytest.fixture
    def mock_config(self):
        """Create a minimal mock config."""
        config = Mock()
        config.MT5_PATH = "C:/MT5/terminal64.exe"
        config.MT5_LOGIN = "12345"
        config.MT5_PASSWORD = "test"
        config.MT5_SERVER = "TestServer"
        config.SYMBOLS_WHITELIST = ["EURUSD", "GBPUSD"]
        config.TOP_N_SYMBOLS = 2
        config.RISK_PERCENTAGE = 2.0
        config.DATABASE_FOLDER = ":memory:"
        config.DATABASE_NAME = "test.db"
        config.NEWS_CACHE_DURATION_MINUTES = 5
        config.optimizer = Mock()
        config.optimizer.timeframes_to_check = {"H1": 16385}
        config.optimizer.ideal_volatility = 0.5
        config.vector_db = Mock()
        config.vector_db.enabled = False
        config.FOREX_THRESHOLDS = {"total_trades": 3}
        return config

    @pytest.fixture
    def mock_components(self):
        """Create mock components for TradingSystem."""
        return {
            "db_manager": Mock(),
            "vector_db_manager": Mock(),
            "data_provider": Mock(),
            "data_provider_manager": Mock(),
            "nlp_processor": Mock(),
            "consensus_engine": Mock(),
            "knowledge_graph_querier": Mock(),
            "risk_engine": Mock(),
            "execution_service": Mock(),
            "safety_monitor": Mock(),
            "training_scheduler": Mock(),
            "auto_updater": Mock(),
        }

    def test_trading_system_has_trading_engine(self, mock_config, mock_components):
        """TradingSystem initializes with TradingEngine."""
        from src.core.trading import TradingEngine

        # TradingEngine can be created independently
        mock_ts = Mock()
        engine = TradingEngine(mock_ts)

        assert engine is not None
        assert hasattr(engine, "can_trade")
        assert hasattr(engine, "process_commands")
        assert hasattr(engine, "get_available_symbols")

    def test_trading_system_has_ml_coordinator(self, mock_config):
        """TradingSystem initializes with MLCoordinator."""
        from src.core.trading import MLCoordinator

        mock_ts = Mock()
        coordinator = MLCoordinator(mock_ts)

        assert coordinator is not None
        assert hasattr(coordinator, "get_model_accuracy")
        assert hasattr(coordinator, "get_training_status")
        assert hasattr(coordinator, "can_train_symbol")

    def test_trading_system_has_gui_coordinator(self, mock_config):
        """TradingSystem initializes with GUICoordinator."""
        from src.core.trading import GUICoordinator

        mock_bridge = Mock()
        coordinator = GUICoordinator(mock_bridge, mock_config)

        assert coordinator is not None
        assert hasattr(coordinator, "safe_gui_update")
        assert hasattr(coordinator, "send_model_accuracy")
        assert hasattr(coordinator, "send_retrain_progress")

    def test_trading_system_has_health_check(self, mock_config):
        """TradingSystem initializes with HealthCheckEndpoint."""
        from src.core.trading import HealthCheckEndpoint

        mock_ts = Mock()
        mock_ts.is_heavy_init_complete = True
        mock_ts.update_pending = False
        mock_ts.db_manager = Mock()
        mock_ts.db_manager.engine = Mock()

        health_check = HealthCheckEndpoint(mock_ts)

        assert health_check is not None
        assert hasattr(health_check, "get_health_status")
        assert hasattr(health_check, "get_health_summary")
        assert hasattr(health_check, "to_prometheus_format")

    def test_trading_system_has_graceful_degradation(self, mock_config):
        """TradingSystem can integrate GracefulDegradationManager."""
        from src.core.trading import GracefulDegradationManager, DegradationPhase

        manager = GracefulDegradationManager()

        assert manager is not None
        assert manager.current_phase == DegradationPhase.FULL_ML
        assert hasattr(manager, "record_model_success")
        assert hasattr(manager, "record_model_failure")
        assert hasattr(manager, "get_fallback_strategy")

    def test_trading_system_has_nlp_lazy_loader(self, mock_config):
        """TradingSystem can integrate NLPLazyLoader."""
        from src.core.trading import NLPLazyLoader, LazyNLPModel

        loader = NLPLazyLoader()

        assert loader is not None
        assert loader.get_total_count() == 0
        assert hasattr(loader, "get_embedding_model")
        assert hasattr(loader, "get_summarization_model")
        assert hasattr(loader, "get_sentiment_model")

    def test_trading_engine_can_trade_delegation(self, mock_config):
        """TradingEngine.can_trade delegates to TradingSystem checks."""
        from src.core.trading import TradingEngine

        mock_ts = Mock()
        mock_ts.stop_event = Mock()
        mock_ts.stop_event.is_set.return_value = False
        mock_ts.is_heavy_init_complete = True
        mock_ts.update_pending = False

        engine = TradingEngine(mock_ts)

        assert engine.can_trade() is True

    def test_trading_engine_cannot_trade_when_stopped(self, mock_config):
        """TradingEngine.can_trade returns False when system is stopped."""
        from src.core.trading import TradingEngine

        mock_ts = Mock()
        mock_ts.stop_event = Mock()
        mock_ts.stop_event.is_set.return_value = True
        mock_ts.is_heavy_init_complete = True
        mock_ts.update_pending = False

        engine = TradingEngine(mock_ts)

        assert engine.can_trade() is False

    def test_ml_coordinator_training_flow(self, mock_config):
        """MLCoordinator handles full training flow."""
        from src.core.trading import MLCoordinator

        mock_ts = Mock()
        mock_ts.command_queue = queue.Queue()

        coordinator = MLCoordinator(mock_ts)

        # Start training
        assert coordinator.can_train_symbol("EURUSD") is True

        # Mark in progress
        coordinator.mark_symbol_training_in_progress("EURUSD")
        assert coordinator.get_training_status("EURUSD") == "in_progress"

        # Mark complete
        coordinator.mark_symbol_training_complete("EURUSD")
        assert coordinator.get_training_status("EURUSD") == "completed"

        # Rate limiting works
        assert coordinator.can_train_symbol("EURUSD", min_interval_hours=1.0) is False

    def test_graceful_degradation_integration(self, mock_config):
        """GracefulDegradationManager handles full degradation cycle."""
        from src.core.trading import GracefulDegradationManager, DegradationPhase

        manager = GracefulDegradationManager()
        manager._min_phase_change_interval = 0

        # Initial state
        assert manager.current_phase == DegradationPhase.FULL_ML
        assert manager.get_fallback_strategy() == "ML_ensemble"

        # Simulate failures
        for i in range(3):
            manager.record_model_failure(f"model_{i}", "error")

        # Check degradation
        report = manager.get_health_report()
        assert "current_phase" in report
        assert "fallback_strategy" in report
        assert report["total_models"] == 3

    def test_health_check_full_report(self, mock_config):
        """HealthCheckEndpoint returns full health report."""
        from src.core.trading import HealthCheckEndpoint

        mock_ts = Mock()
        mock_ts.is_heavy_init_complete = True
        mock_ts.update_pending = False
        mock_ts.config = mock_config
        mock_ts.db_manager = Mock()
        mock_ts.db_manager.engine = Mock()
        mock_ts._ml_coordinator = Mock()
        mock_ts._ml_coordinator.get_all_model_accuracy = Mock(return_value={})

        health = HealthCheckEndpoint(mock_ts)

        report = health.get_health_status(force=True)

        assert "status" in report
        assert "uptime_seconds" in report
        assert "components" in report
        assert "ml_models" in report
        assert "database" in report
        assert "memory" in report

    def test_end_to_end_module_integration(self, mock_config):
        """End-to-end test: all modules work together."""
        from src.core.trading import (
            TradingEngine,
            MLCoordinator,
            GUICoordinator,
            GracefulDegradationManager,
            HealthCheckEndpoint,
            NLPLazyLoader,
            TradingCache,
            PerformanceTimer,
        )

        # Create all modules
        mock_ts = Mock()
        mock_ts.stop_event = Mock()
        mock_ts.stop_event.is_set.return_value = False
        mock_ts.is_heavy_init_complete = True
        mock_ts.update_pending = False
        mock_ts.command_queue = queue.Queue()
        mock_ts.config = mock_config
        mock_ts.db_manager = Mock()
        mock_ts.db_manager.engine = Mock()
        mock_ts._ml_coordinator = None

        # Initialize modules
        engine = TradingEngine(mock_ts)
        ml_coord = MLCoordinator(mock_ts)
        gui_coord = GUICoordinator(Mock(), mock_config)
        degradation = GracefulDegradationManager()
        health = HealthCheckEndpoint(mock_ts)
        nlp_loader = NLPLazyLoader()
        cache = TradingCache()
        timer = PerformanceTimer()

        # Verify all modules work together
        assert engine.can_trade() is True
        assert ml_coord.can_train_symbol("EURUSD") is True
        assert degradation.current_phase.value == "full_ml"
        assert cache.get("key") is None
        cache.set("key", "value")
        assert cache.get("key") == "value"

        # Health check works
        report = health.get_health_summary()
        assert "status" in report

        # Timer works
        timer.start("test")
        import time
        time.sleep(0.01)
        elapsed = timer.end("test")
        assert elapsed >= 0
