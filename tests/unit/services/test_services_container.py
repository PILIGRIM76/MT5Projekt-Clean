# -*- coding: utf-8 -*-
"""
Тесты для services_container.

Проверяет:
- Singleton инициализацию
- start_all_services / stop_all_services
- get_all_health_checks
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config_models import Settings
from src.core.services_container import (
    get_all_health_checks,
    get_config,
    get_data_service,
    get_db_manager,
    get_execution_service,
    get_ml_service,
    start_all_services,
    stop_all_services,
)

# ===========================================
# Фикстуры
# ===========================================


@pytest.fixture
def config(minimal_config):
    """Фикстура конфигурации (использует global minimal_config)."""
    return minimal_config


@pytest.fixture(autouse=True)
def reset_container():
    """Сброс контейнера между тестами."""
    import src.core.services_container as container

    # Сохраняем старые значения
    old_config = container._config
    old_db = container._db_manager
    old_data = container._data_service
    old_ml = container._ml_service
    old_exec = container._execution_service

    yield

    # Восстанавливаем
    container._config = old_config
    container._db_manager = old_db
    container._data_service = old_data
    container._ml_service = old_ml
    container._execution_service = old_exec


# ===========================================
# Тесты get_config
# ===========================================


class TestGetConfig:
    """Тесты get_config."""

    def test_get_config_singleton(self, config):
        """Тест singleton get_config."""
        with patch("src.core.services_container.load_config", return_value=config):
            config1 = get_config()
            config2 = get_config()

            assert config1 is config2

    def test_get_config_loads_once(self, config):
        """Тест загрузки конфигурации один раз."""
        with patch("src.core.services_container.load_config", return_value=config) as mock_load:
            get_config()
            get_config()

            mock_load.assert_called_once()


# ===========================================
# Тесты get_db_manager
# ===========================================


class TestGetDBManager:
    """Тесты get_db_manager."""

    def test_get_db_manager_singleton(self, config):
        """Тест singleton get_db_manager."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.db.database_manager.DatabaseManager") as MockDB:
                mock_db_instance = MagicMock()
                MockDB.return_value = mock_db_instance

                db1 = get_db_manager()
                db2 = get_db_manager()

                assert db1 is db2
                MockDB.assert_called_once()


# ===========================================
# Тесты get_data_service
# ===========================================


class TestGetDataService:
    """Тесты get_data_service."""

    def test_get_data_service_singleton(self, config):
        """Тест singleton get_data_service."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services.data_service.DataService") as MockService:
                mock_instance = MagicMock()
                MockService.return_value = mock_instance

                service1 = get_data_service()
                service2 = get_data_service()

                assert service1 is service2
                MockService.assert_called_once()


# ===========================================
# Тесты get_ml_service
# ===========================================


class TestGetMLService:
    """Тесты get_ml_service."""

    def test_get_ml_service_singleton(self, config):
        """Тест singleton get_ml_service."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services.ml_service.MLService") as MockService:
                with patch("src.core.services_container.get_db_manager"):
                    mock_instance = MagicMock()
                    MockService.return_value = mock_instance

                    service1 = get_ml_service()
                    service2 = get_ml_service()

                    assert service1 is service2


# ===========================================
# Тесты get_execution_service
# ===========================================


class TestGetExecutionService:
    """Тесты get_execution_service."""

    def test_get_execution_service_singleton(self, config):
        """Тест singleton get_execution_service."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services.execution_service.ExecutionService") as MockService:
                with patch("src.core.services_container.get_db_manager"):
                    mock_instance = MagicMock()
                    MockService.return_value = mock_instance

                    service1 = get_execution_service()
                    service2 = get_execution_service()

                    assert service1 is service2


# ===========================================
# Тесты start_all_services
# ===========================================


class TestStartAllServices:
    """Тесты start_all_services."""

    @pytest.mark.asyncio
    async def test_start_all_services_success(self, config):
        """Тест успешного запуска всех сервисов."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services_container.get_data_service") as mock_get_data:
                with patch("src.core.services_container.get_ml_service") as mock_get_ml:
                    with patch("src.core.services_container.get_execution_service") as mock_get_exec:
                        # Мок сервисов
                        mock_data = AsyncMock()
                        mock_data.start = AsyncMock()
                        mock_get_data.return_value = mock_data

                        mock_ml = AsyncMock()
                        mock_ml.start = AsyncMock()
                        mock_get_ml.return_value = mock_ml

                        mock_exec = AsyncMock()
                        mock_exec.start = AsyncMock()
                        mock_get_exec.return_value = mock_exec

                        # Запуск
                        await start_all_services()

                        # Проверка вызовов
                        mock_data.start.assert_called_once()
                        mock_ml.start.assert_called_once()
                        mock_exec.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_all_services_failure(self, config):
        """Тест неудачного запуска сервисов."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services_container.get_data_service") as mock_get_data:
                mock_data = AsyncMock()
                mock_data.start = AsyncMock(side_effect=Exception("Start failed"))
                mock_get_data.return_value = mock_data

                # Запуск должен выбросить исключение
                with pytest.raises(Exception):
                    await start_all_services()


# ===========================================
# Тесты stop_all_services
# ===========================================


class TestStopAllServices:
    """Тесты stop_all_services."""

    @pytest.mark.asyncio
    async def test_stop_all_services_success(self, config):
        """Тест успешной остановки всех сервисов."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services_container.get_data_service") as mock_get_data:
                with patch("src.core.services_container.get_ml_service") as mock_get_ml:
                    with patch("src.core.services_container.get_execution_service") as mock_get_exec:
                        # Мок сервисов
                        mock_data = AsyncMock()
                        mock_data.stop = AsyncMock()
                        mock_get_data.return_value = mock_data

                        mock_ml = AsyncMock()
                        mock_ml.stop = AsyncMock()
                        mock_get_ml.return_value = mock_ml

                        mock_exec = AsyncMock()
                        mock_exec.stop = AsyncMock()
                        mock_get_exec.return_value = mock_exec

                        # Остановка
                        await stop_all_services()

                        # Проверка вызовов
                        mock_data.stop.assert_called_once()
                        mock_ml.stop.assert_called_once()
                        mock_exec.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_all_services_handles_errors(self, config):
        """Тест обработки ошибок при остановке."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services_container.get_data_service") as mock_get_data:
                mock_data = AsyncMock()
                mock_data.stop = AsyncMock(side_effect=Exception("Stop failed"))
                mock_get_data.return_value = mock_data

                # Остановка не должна выбрасывать
                await stop_all_services()

                mock_data.stop.assert_called_once()


# ===========================================
# Тесты get_all_health_checks
# ===========================================


class TestGetAllHealthChecks:
    """Тесты get_all_health_checks."""

    def test_get_all_health_checks_success(self, config):
        """Тест успешной проверки здоровья."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services_container.get_data_service") as mock_get_data:
                with patch("src.core.services_container.get_ml_service") as mock_get_ml:
                    with patch("src.core.services_container.get_execution_service") as mock_get_exec:
                        # Мок сервисов
                        mock_data = MagicMock()
                        mock_data.health_check.return_value = {"status": "healthy"}
                        mock_get_data.return_value = mock_data

                        mock_ml = MagicMock()
                        mock_ml.health_check.return_value = {"status": "healthy"}
                        mock_get_ml.return_value = mock_ml

                        mock_exec = MagicMock()
                        mock_exec.health_check.return_value = {"status": "healthy"}
                        mock_get_exec.return_value = mock_exec

                        # Проверка
                        health = get_all_health_checks()

                        assert "DataService" in health
                        assert "MLService" in health
                        assert "ExecutionService" in health

                        assert health["DataService"]["status"] == "healthy"
                        assert health["MLService"]["status"] == "healthy"
                        assert health["ExecutionService"]["status"] == "healthy"

    def test_get_all_health_checks_error(self, config):
        """Тест проверки здоровья с ошибкой."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services_container.get_data_service") as mock_get_data:
                mock_data = MagicMock()
                mock_data.health_check.side_effect = Exception("Health check failed")
                mock_get_data.return_value = mock_data

                # Проверка
                health = get_all_health_checks()

                assert "DataService" in health
                assert health["DataService"]["status"] == "error"
                assert "error" in health["DataService"]


# ===========================================
# Интеграционные тесты
# ===========================================


class TestContainerIntegration:
    """Интеграционные тесты контейнера."""

    @pytest.mark.asyncio
    async def test_full_container_lifecycle(self, config):
        """Тест полного жизненного цикла контейнера."""
        with patch("src.core.services_container.load_config", return_value=config):
            with patch("src.core.services_container.get_data_service") as mock_get_data:
                with patch("src.core.services_container.get_ml_service") as mock_get_ml:
                    with patch("src.core.services_container.get_execution_service") as mock_get_exec:
                        # Мок сервисов
                        mock_data = AsyncMock()
                        mock_data.start = AsyncMock()
                        mock_data.stop = AsyncMock()
                        mock_data.health_check.return_value = {"status": "healthy"}
                        mock_get_data.return_value = mock_data

                        mock_ml = AsyncMock()
                        mock_ml.start = AsyncMock()
                        mock_ml.stop = AsyncMock()
                        mock_ml.health_check.return_value = {"status": "healthy"}
                        mock_get_ml.return_value = mock_ml

                        mock_exec = AsyncMock()
                        mock_exec.start = AsyncMock()
                        mock_exec.stop = AsyncMock()
                        mock_exec.health_check.return_value = {"status": "healthy"}
                        mock_get_exec.return_value = mock_exec

                        # Запуск
                        await start_all_services()

                        # Проверка здоровья
                        health = get_all_health_checks()
                        assert all(h["status"] == "healthy" for h in health.values())

                        # Остановка
                        await stop_all_services()
