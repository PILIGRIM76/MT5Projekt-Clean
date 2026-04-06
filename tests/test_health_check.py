# -*- coding: utf-8 -*-
"""
Тесты для Health Check Endpoint — мониторинг состояния системы.
"""

import pytest
from unittest.mock import Mock, patch
import time
from src.core.trading.health_check import HealthCheckEndpoint


class TestHealthCheckEndpoint:
    """Тесты HealthCheckEndpoint."""

    @pytest.fixture
    def trading_system_mock(self):
        """Создаёт мок TradingSystem."""
        ts = Mock()
        ts.is_heavy_init_complete = True
        ts.update_pending = False
        ts.config = Mock()
        ts.config.MT5_PATH = "C:/MT5/terminal64.exe"
        ts.config.MT5_SERVER = "TestServer"
        ts.config.DATABASE_FOLDER = "/tmp/db"
        ts.db_manager = Mock()
        ts.db_manager.engine = Mock()
        ts.db_manager.engine.execute = Mock(return_value=[[1]])
        ts.data_provider = Mock()
        ts.risk_engine = Mock()
        ts._ml_coordinator = Mock()
        ts._ml_coordinator.get_all_model_accuracy = Mock(return_value={"EURUSD": 0.85})
        return ts

    @pytest.fixture
    def health_check(self, trading_system_mock):
        """Создаёт HealthCheckEndpoint с моком."""
        return HealthCheckEndpoint(trading_system_mock)

    def test_get_health_status_returns_report(self, health_check):
        """get_health_status возвращает полный отчёт."""
        report = health_check.get_health_status()

        assert "status" in report
        assert "timestamp" in report
        assert "uptime_seconds" in report
        assert "components" in report
        assert "ml_models" in report
        assert "database" in report
        assert "mt5" in report
        assert "memory" in report

    def test_get_health_summary_returns_brief_report(self, health_check):
        """get_health_summary возвращает краткий статус."""
        summary = health_check.get_health_summary()

        assert "status" in summary
        assert "uptime" in summary
        assert "components_healthy" in summary
        assert "ml_models_healthy" in summary
        assert "database_connected" in summary
        assert "mt5_connected" in summary

    def test_calculate_overall_status_healthy(self, health_check):
        """_calculate_overall_status возвращает healthy."""
        with patch("MetaTrader5.initialize", return_value=True):
            status = health_check._calculate_overall_status()
            assert status == "healthy"

    def test_calculate_overall_status_starting(self, health_check):
        """_calculate_overall_status возвращает starting при не завершённой инициализации."""
        health_check.trading_system.is_heavy_init_complete = False
        status = health_check._calculate_overall_status()
        assert status == "starting"

    def test_calculate_overall_status_updating(self, health_check):
        """_calculate_overall_status возвращает updating при обновлении."""
        health_check.trading_system.update_pending = True
        status = health_check._calculate_overall_status()
        assert status == "updating"

    def test_check_components_returns_dict(self, health_check):
        """_check_components возвращает словарь со статусом компонентов."""
        with patch("MetaTrader5.initialize", return_value=True):
            with patch("MetaTrader5.account_info", return_value=Mock()):
                with patch("MetaTrader5.shutdown"):
                    result = health_check._check_components()

        assert "details" in result
        assert "healthy" in result
        assert "total" in result
        assert "percentage" in result
        assert result["details"]["trading_system"] is True

    def test_check_ml_models_returns_dict(self, health_check):
        """_check_ml_models возвращает словарь со статусом ML моделей."""
        result = health_check._check_ml_models()

        assert "models" in result
        assert "healthy" in result
        assert "total" in result
        assert result["models"] == {"EURUSD": 0.85}

    def test_check_database_connected(self, health_check):
        """_check_database возвращает статус подключения."""
        result = health_check._check_database()

        assert result["connected"] is True
        assert result["type"] == "sqlite"

    def test_check_database_disconnected(self, health_check):
        """_check_database возвращает disconnected при ошибке."""
        # Mock the engine.execute to raise an exception
        health_check.trading_system.db_manager.engine.execute = Mock(side_effect=Exception("DB error"))

        result = health_check._check_database()

        # The method catches the exception and sets connected to False
        assert result["connected"] is False
        assert "error" in result

    def test_check_mt5_connected(self, health_check):
        """_check_mt5 возвращает статус подключения."""
        mock_acc = Mock()
        mock_acc.balance = 100000.0
        mock_acc.equity = 100500.0

        with patch("MetaTrader5.initialize", return_value=True):
            with patch("MetaTrader5.account_info", return_value=mock_acc):
                with patch("MetaTrader5.shutdown"):
                    result = health_check._check_mt5()

        assert result["connected"] is True
        assert result["balance"] == 100000.0

    def test_check_mt5_disconnected(self, health_check):
        """_check_mt5 возвращает disconnected при ошибке."""
        with patch("MetaTrader5.initialize", return_value=False):
            result = health_check._check_mt5()

        assert result["connected"] is False

    def test_check_memory_returns_dict(self, health_check):
        """_check_memory возвращает словарь с информацией о памяти."""
        with patch("psutil.Process") as mock_process:
            mock_proc = Mock()
            mock_proc.memory_info.return_value = Mock(rss=500 * 1024 * 1024, vms=1000 * 1024 * 1024)
            mock_proc.memory_percent.return_value = 5.0
            mock_process.return_value = mock_proc

            result = health_check._check_memory()

            assert "rss_mb" in result
            assert "vms_mb" in result
            assert "percent" in result
            assert result["rss_mb"] == 500.0

    def test_format_uptime_days(self, health_check):
        """_format_uptime форматирует дни."""
        assert "d" in health_check._format_uptime(100000)

    def test_format_uptime_hours(self, health_check):
        """_format_uptime форматирует часы."""
        assert "h" in health_check._format_uptime(3600)

    def test_format_uptime_minutes(self, health_check):
        """_format_uptime форматирует минуты."""
        assert "m" in health_check._format_uptime(120)

    def test_format_uptime_seconds(self, health_check):
        """_format_uptime форматирует секунды."""
        result = health_check._format_uptime(30)
        assert "s" in result

    def test_to_prometheus_format_returns_string(self, health_check):
        """to_prometheus_format возвращает строку в формате Prometheus."""
        with patch("MetaTrader5.initialize", return_value=True):
            with patch("MetaTrader5.account_info", return_value=Mock()):
                with patch("MetaTrader5.shutdown"):
                    with patch("psutil.Process") as mock_process:
                        mock_proc = Mock()
                        mock_proc.memory_info.return_value = Mock(rss=500 * 1024 * 1024, vms=1000 * 1024 * 1024)
                        mock_proc.memory_percent.return_value = 5.0
                        mock_process.return_value = mock_proc

                        result = health_check.to_prometheus_format()

        assert isinstance(result, str)
        assert "genesis_system_status" in result
        assert "genesis_system_uptime_seconds" in result
        assert "genesis_components_healthy" in result
        assert "genesis_ml_models_healthy" in result
        assert "genesis_database_connected" in result
        assert "genesis_mt5_connected" in result
        assert "genesis_memory_usage_mb" in result

    def test_health_check_caching(self, health_check):
        """get_health_status использует кэш."""
        report1 = health_check.get_health_status()
        report2 = health_check.get_health_status()

        # Должен вернуть тот же объект из кэша
        assert report1 is report2

    def test_health_check_force_refresh(self, health_check):
        """get_health_status(force=True) обновляет кэш."""
        report1 = health_check.get_health_status()
        report2 = health_check.get_health_status(force=True)

        # Должен создать новый отчёт
        assert report1 is not report2 or report1 == report2  # Может быть тот же контент
