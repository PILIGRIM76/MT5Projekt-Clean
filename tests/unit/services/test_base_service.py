# -*- coding: utf-8 -*-
"""
Тесты для BaseService.

Проверяет:
- Инициализацию сервиса
- Жизненный цикл (start/stop)
- Health check
- Обработку ошибок
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.services.base_service import BaseService

# ===========================================
# Фикстуры
# ===========================================


@pytest.fixture
def config(minimal_config):
    """Фикстура конфигурации (использует global minimal_config)."""
    return minimal_config


@pytest.fixture
def concrete_service(config):
    """Конкретная реализация BaseService для тестирования."""

    class TestService(BaseService):
        async def start(self) -> None:
            self._running = True
            self._healthy = True

        async def stop(self) -> None:
            self._running = False
            self._healthy = False

        def health_check(self):
            return {
                "status": "healthy" if self._healthy else "unhealthy",
                "name": self.name,
            }

    return TestService(config=config, name="TestService")


# ===========================================
# Тесты инициализации
# ===========================================


class TestBaseServiceInitialization:
    """Тесты инициализации BaseService."""

    def test_init_default_values(self, concrete_service):
        """Тест инициализации с значениями по умолчанию."""
        assert concrete_service.config is not None
        assert concrete_service.name == "TestService"
        assert concrete_service._running is False
        assert concrete_service._healthy is False
        assert concrete_service._db_write_queue is None

    def test_init_with_custom_name(self, concrete_service):
        """Тест инициализации с кастомным именем."""
        assert concrete_service.name == "TestService"

    def test_repr(self, concrete_service):
        """Тест строкового представления."""
        repr_str = repr(concrete_service)
        assert "TestService" in repr_str
        assert "running=False" in repr_str
        assert "healthy=False" in repr_str


# ===========================================
# Тесты жизненного цикла
# ===========================================


class TestServiceLifecycle:
    """Тесты жизненного цикла сервиса."""

    @pytest.mark.asyncio
    async def test_start(self, concrete_service):
        """Тест запуска сервиса."""
        assert concrete_service._running is False

        await concrete_service.start()

        assert concrete_service._running is True
        assert concrete_service._healthy is True

    @pytest.mark.asyncio
    async def test_stop(self, concrete_service):
        """Тест остановки сервиса."""
        # Сначала запускаем
        await concrete_service.start()
        assert concrete_service._running is True

        # Останавливаем
        await concrete_service.stop()

        assert concrete_service._running is False
        assert concrete_service._healthy is False

    @pytest.mark.asyncio
    async def test_start_stop_sequence(self, concrete_service):
        """Тест последовательности запуск/остановка."""
        # Начальное состояние
        assert concrete_service._running is False

        # Запуск
        await concrete_service.start()
        assert concrete_service._running is True

        # Остановка
        await concrete_service.stop()
        assert concrete_service._running is False


# ===========================================
# Тесты health check
# ===========================================


class TestHealthCheck:
    """Тесты проверки здоровья сервиса."""

    def test_health_check_initial_state(self, concrete_service):
        """Тест health check в начальном состоянии."""
        health = concrete_service.health_check()

        assert "status" in health
        assert health["status"] == "unhealthy"  # До запуска
        assert health["name"] == "TestService"

    @pytest.mark.asyncio
    async def test_health_check_after_start(self, concrete_service):
        """Тест health check после запуска."""
        await concrete_service.start()

        health = concrete_service.health_check()
        assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_after_stop(self, concrete_service):
        """Тест health check после остановки."""
        await concrete_service.start()
        await concrete_service.stop()

        health = concrete_service.health_check()
        assert health["status"] == "unhealthy"


# ===========================================
# Тесты обработки ошибок
# ===========================================


class TestErrorHandling:
    """Тесты обработки ошибок."""

    @pytest.mark.asyncio
    async def test_safe_execute_success(self, concrete_service):
        """Тест успешного выполнения операции."""
        # Запускаем сервис сначала
        await concrete_service.start()

        async def successful_operation():
            return "success"

        result = await concrete_service._safe_execute(successful_operation(), "Test operation")

        assert result == "success"
        assert concrete_service._healthy is True

    @pytest.mark.asyncio
    async def test_safe_execute_exception(self, concrete_service):
        """Тест выполнения операции с исключением."""
        # Запускаем сервис
        await concrete_service.start()
        assert concrete_service._healthy is True

        async def failing_operation():
            raise ValueError("Test error")

        result = await concrete_service._safe_execute(failing_operation(), "Failing operation")

        assert result is None
        assert concrete_service._healthy is False

    @pytest.mark.asyncio
    async def test_safe_execute_cancelled_error(self, concrete_service):
        """Тест отменённой операции."""

        async def cancelled_operation():
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await concrete_service._safe_execute(cancelled_operation(), "Cancelled operation")

    def test_sync_safe_execute_success(self, concrete_service):
        """Тест успешного синхронного выполнения."""
        # Запускаем сервис
        asyncio.run(concrete_service.start())

        def successful_function():
            return 42

        result = concrete_service._sync_safe_execute(successful_function, "Sync operation")

        assert result == 42
        assert concrete_service._healthy is True

    def test_sync_safe_execute_exception(self, concrete_service):
        """Тест синхронного выполнения с исключением."""
        # Запускаем сервис
        asyncio.run(concrete_service.start())
        assert concrete_service._healthy is True

        def failing_function():
            raise RuntimeError("Sync error")

        result = concrete_service._sync_safe_execute(failing_function, "Failing sync operation")

        assert result is None
        assert concrete_service._healthy is False


# ===========================================
# Тесты свойств
# ===========================================


class TestProperties:
    """Тесты свойств сервиса."""

    def test_is_running_initial(self, concrete_service):
        """Тест is_running в начальном состоянии."""
        assert concrete_service.is_running is False

    def test_is_running_after_start(self, concrete_service):
        """Тест is_running после запуска."""
        asyncio.run(concrete_service.start())
        assert concrete_service.is_running is True

    def test_is_healthy_initial(self, concrete_service):
        """Тест is_healthy в начальном состоянии."""
        assert concrete_service.is_healthy is False

    def test_is_healthy_after_start(self, concrete_service):
        """Тест is_healthy после запуска."""
        asyncio.run(concrete_service.start())
        assert concrete_service.is_healthy is True


# ===========================================
# Тесты DB write queue
# ===========================================


class TestDBWriteQueue:
    """Тесты очереди записи в БД."""

    def test_set_db_write_queue(self, concrete_service):
        """Тест установки очереди."""
        queue = asyncio.Queue()

        concrete_service.set_db_write_queue(queue)

        assert concrete_service._db_write_queue == queue

    def test_set_db_write_queue_none(self, concrete_service):
        """Тест установки None очереди."""
        concrete_service.set_db_write_queue(None)

        assert concrete_service._db_write_queue is None


# ===========================================
# Интеграционные тесты
# ===========================================


class TestIntegration:
    """Интеграционные тесты BaseService."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, concrete_service):
        """Тест полного жизненного цикла."""
        # Начальное состояние
        assert concrete_service.is_running is False
        assert concrete_service.is_healthy is False

        # Запуск
        await concrete_service.start()
        assert concrete_service.is_running is True
        assert concrete_service.is_healthy is True

        # Проверка здоровья
        health = concrete_service.health_check()
        assert health["status"] == "healthy"

        # Остановка
        await concrete_service.stop()
        assert concrete_service.is_running is False
        assert concrete_service.is_healthy is False

        # Финальная проверка
        health = concrete_service.health_check()
        assert health["status"] == "unhealthy"
