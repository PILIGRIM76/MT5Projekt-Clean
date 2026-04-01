"""
Unit тесты для модуля container.py.

Тестирует:
- Dependency Injection функции
- Singleton паттерны
- Lazy initialization
- Reset функциональность
- Потокобезопасность

ПРИМЕЧАНИЕ: Тесты используют Mock для Settings из-за сложности конфигурации.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Импорты для тестов
from src.core.container import Container, reset_all


class TestContainerClass:
    """Тесты для класса Container."""

    def test_container_creation(self):
        """Проверка создания Container."""
        container = Container()

        assert container is not None
        assert isinstance(container, Container)

    def test_container_get_instance_singleton(self):
        """Проверка что get_instance возвращает Singleton."""
        container1 = Container.get_instance()
        container2 = Container.get_instance()

        assert container1 is container2

    def test_container_get_instance_thread_safe(self):
        """Проверка потокобезопасности get_instance."""
        import threading

        containers = []

        def get_container():
            containers.append(Container.get_instance())

        threads = [threading.Thread(target=get_container) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Все потоки должны получить один и тот же экземпляр
        assert len(set(id(c) for c in containers)) == 1

    def test_container_properties_exist(self):
        """Проверка что свойства контейнера существуют."""
        container = Container()

        properties = [name for name, obj in type(container).__dict__.items() if isinstance(obj, property)]

        expected_properties = [
            "config",
            "db_manager",
            "vector_db_manager",
            "data_provider",
            "risk_engine",
            "model_factory",
            "trading_system",
            "query_manager",
            "command_manager",
            "event_bus",
        ]

        for prop in expected_properties:
            assert prop in properties, f"Property {prop} not found in Container"

    def test_container_reset_instance(self):
        """Проверка reset_instance."""
        container1 = Container.get_instance()
        Container.reset_instance()
        container2 = Container.get_instance()

        # После сброса должен быть создан новый экземпляр
        assert container1 is not container2


class TestContainerReset:
    """Тесты для функции reset_all."""

    def test_reset_all_exists(self):
        """Проверка что функция reset_all существует."""
        assert callable(reset_all)

    def test_reset_all_does_not_crash(self):
        """Проверка что reset_all не вызывает ошибок."""
        reset_all()  # Не должно вызвать исключений

    def test_reset_all_resets_container(self):
        """Проверка что reset_all сбрасывает контейнер."""
        container1 = Container.get_instance()
        reset_all()
        container2 = Container.get_instance()

        assert container1 is not container2


class TestContainerBackwardCompatibility:
    """Тесты обратной совместимости функций get_*()."""

    def test_get_config_exists(self):
        """Проверка что get_config существует."""
        from src.core.container import get_config

        assert callable(get_config)

    def test_get_db_manager_exists(self):
        """Проверка что get_db_manager существует."""
        from src.core.container import get_db_manager

        assert callable(get_db_manager)

    def test_get_risk_engine_exists(self):
        """Проверка что get_risk_engine существует."""
        from src.core.container import get_risk_engine

        assert callable(get_risk_engine)
