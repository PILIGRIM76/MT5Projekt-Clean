"""
Тесты для ThreadDomains — типизация доменов потоков.
"""

import pytest

from src.core.thread_domains import (
    DEFAULT_DOMAIN_CONFIG,
    DomainRegistry,
    ExecutorType,
    ResourceLimits,
    ThreadDomain,
    run_in_domain,
)


class TestThreadDomain:
    """Тесты ThreadDomain enum."""

    def test_all_domains_defined(self):
        """Проверка: все домены определены."""
        domains = [
            ThreadDomain.GUI,
            ThreadDomain.MT5_IO,
            ThreadDomain.DATA_INGEST,
            ThreadDomain.PERSISTENCE,
            ThreadDomain.ML_INFERENCE,
            ThreadDomain.ML_TRAINING,
            ThreadDomain.FEATURE_ENGINEERING,
            ThreadDomain.STRATEGY_ENGINE,
            ThreadDomain.RISK_ENGINE,
            ThreadDomain.ORCHESTRATOR,
            ThreadDomain.LOGGING,
            ThreadDomain.HEALTH_CHECK,
        ]
        assert len(domains) == 12

    def test_domain_uniqueness(self):
        """Проверка: все домены уникальны."""
        domains = list(ThreadDomain)
        values = [d.value for d in domains]
        assert len(values) == len(set(values))


class TestExecutorType:
    """Тесты ExecutorType enum."""

    def test_all_executor_types(self):
        """Проверка: все типы executor определены."""
        assert ExecutorType.SINGLE_THREAD.value == 1
        assert ExecutorType.THREAD_POOL.value == 2
        assert ExecutorType.PROCESS_POOL.value == 3
        assert ExecutorType.ASYNC_LOOP.value == 4


class TestResourceLimits:
    """Тесты ResourceLimits dataclass."""

    def test_default_values(self):
        """Проверка значений по умолчанию."""
        limits = ResourceLimits()

        assert limits.cpu_percent_max == 100.0
        assert limits.memory_mb_max is None
        assert limits.max_concurrent_tasks == 1
        assert limits.timeout_seconds is None

    def test_custom_values(self):
        """Проверка кастомных значений."""
        limits = ResourceLimits(
            cpu_percent_max=80.0,
            memory_mb_max=4096,
            max_concurrent_tasks=4,
            timeout_seconds=30.0,
        )

        assert limits.cpu_percent_max == 80.0
        assert limits.memory_mb_max == 4096
        assert limits.max_concurrent_tasks == 4
        assert limits.timeout_seconds == 30.0

    def test_invalid_cpu_percent(self):
        """Проверка: недопустимое значение CPU."""
        with pytest.raises(ValueError, match="cpu_percent_max"):
            ResourceLimits(cpu_percent_max=0)

        with pytest.raises(ValueError, match="cpu_percent_max"):
            ResourceLimits(cpu_percent_max=150)

    def test_invalid_concurrent_tasks(self):
        """Проверка: недопустимое количество задач."""
        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            ResourceLimits(max_concurrent_tasks=0)

        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            ResourceLimits(max_concurrent_tasks=-1)

    def test_frozen_dataclass(self):
        """Проверка: ResourceLimits неизменяем."""
        limits = ResourceLimits()
        with pytest.raises(Exception):  # FrozenInstanceError
            limits.cpu_percent_max = 50.0


class TestDomainRegistry:
    """Тесты DomainRegistry."""

    def setup_method(self):
        """Сброс реестра перед каждым тестом."""
        # Восстанавливаем оригинальный конфиг из глобальной константы
        from src.core.thread_domains import DEFAULT_DOMAIN_CONFIG as GLOBAL_DEFAULT

        DomainRegistry._config = {k: {kk: vv for kk, vv in v.items()} for k, v in GLOBAL_DEFAULT.items()}
        DomainRegistry._executors.clear()

    def teardown_method(self):
        """Очистка после теста."""
        DomainRegistry.reset()

    def test_get_config_existing(self):
        """Проверка: получение конфигурации существующего домена."""
        config = DomainRegistry.get_config(ThreadDomain.GUI)

        assert "executor_type" in config
        assert "resources" in config
        assert "priority" in config
        assert config["priority"] == 10  # GUI имеет высший приоритет

    def test_get_config_nonexistent_uses_default(self):
        """Проверка: несуществующий домен использует default."""
        # Все домены в конфиге должны быть
        for domain in ThreadDomain:
            config = DomainRegistry.get_config(domain)
            assert config is not None
            assert "executor_type" in config

    def test_override_config(self):
        """Проверка: переопределение конфигурации."""
        # Переопределяем
        DomainRegistry.override_config(
            ThreadDomain.GUI,
            priority=5,
        )

        # Проверяем
        config = DomainRegistry.get_config(ThreadDomain.GUI)
        assert config["priority"] == 5

    def test_register_executor(self):
        """Проверка: регистрация кастомного executor."""
        from concurrent.futures import ThreadPoolExecutor

        custom_executor = ThreadPoolExecutor(max_workers=2)
        DomainRegistry.register_executor(ExecutorType.THREAD_POOL, custom_executor)

        retrieved = DomainRegistry.get_executor(ExecutorType.THREAD_POOL)
        assert retrieved is custom_executor

        custom_executor.shutdown(wait=False)

    def test_reset_clears_overrides(self):
        """Проверка: reset очищает переопределения."""
        # Сначала переопределяем
        DomainRegistry.override_config(ThreadDomain.GUI, priority=1)
        config_before = DomainRegistry.get_config(ThreadDomain.GUI)
        assert config_before["priority"] == 1

        # Теперь сбрасываем
        DomainRegistry.reset()

        # После reset priority должен вернуться к 10
        config_after = DomainRegistry.get_config(ThreadDomain.GUI)
        assert config_after["priority"] == 10, f"Expected 10, got {config_after['priority']}"


class TestDefaultDomainConfig:
    """Тесты DEFAULT_DOMAIN_CONFIG."""

    def setup_method(self):
        """Сброс перед каждым тестом."""
        DomainRegistry.reset()

    def test_all_domains_have_config(self):
        """Проверка: у всех доменов есть конфигурация."""
        for domain in ThreadDomain:
            assert domain in DEFAULT_DOMAIN_CONFIG, f"{domain} missing config"

    def test_config_structure(self):
        """Проверка: структура конфигурации корректна."""
        for domain, config in DEFAULT_DOMAIN_CONFIG.items():
            assert "executor_type" in config
            assert "resources" in config
            assert "priority" in config

            # Resources должен быть ResourceLimits
            assert isinstance(config["resources"], ResourceLimits)

            # Priority должен быть в допустимом диапазоне
            assert 0 < config["priority"] <= 10

    def test_gui_domain_config(self):
        """Проверка: конфигурация GUI домена."""
        config = DEFAULT_DOMAIN_CONFIG[ThreadDomain.GUI]

        assert config["executor_type"] == ExecutorType.SINGLE_THREAD
        assert config["resources"].max_concurrent_tasks == 1
        assert config["priority"] == 10  # Наивысший

    def test_ml_training_config(self):
        """Проверка: конфигурация ML_TRAINING домена."""
        config = DEFAULT_DOMAIN_CONFIG[ThreadDomain.ML_TRAINING]

        assert config["executor_type"] == ExecutorType.PROCESS_POOL
        assert config["resources"].max_concurrent_tasks == 1  # Только одно обучение
        assert config["priority"] == 2  # Низкий приоритет
        assert config["resources"].timeout_seconds == 300.0  # 5 минут

    def test_strategy_engine_config(self):
        """Проверка: конфигурация STRATEGY_ENGINE домена."""
        config = DEFAULT_DOMAIN_CONFIG[ThreadDomain.STRATEGY_ENGINE]

        assert config["executor_type"] == ExecutorType.THREAD_POOL
        assert config["resources"].max_concurrent_tasks == 3
        assert config["priority"] == 9  # Высокий приоритет


class TestRunInDomainDecorator:
    """Тесты декоратора @run_in_domain."""

    def test_decorator_preserves_function(self):
        """Проверка: декоратор сохраняет функцию."""

        @run_in_domain(ThreadDomain.ML_INFERENCE)
        def my_func(x, y):
            return x + y

        assert my_func(2, 3) == 5

    def test_decorator_sets_attributes(self):
        """Проверка: декоратор устанавливает атрибуты."""

        @run_in_domain(ThreadDomain.STRATEGY_ENGINE)
        def my_func():
            pass

        assert hasattr(my_func, "__domain__")
        assert hasattr(my_func, "__wrapped__")
        assert my_func.__domain__ == ThreadDomain.STRATEGY_ENGINE

    def test_decorator_with_kwargs(self):
        """Проверка: декоратор работает с kwargs."""

        @run_in_domain(ThreadDomain.DATA_INGEST)
        def my_func(a, b, c=10):
            return a + b + c

        assert my_func(1, 2) == 13
        assert my_func(1, 2, c=5) == 8

    def test_decorator_nested(self):
        """Проверка: вложенные декораторы."""

        @run_in_domain(ThreadDomain.ML_INFERENCE)
        def inner():
            return 42

        @run_in_domain(ThreadDomain.STRATEGY_ENGINE)
        def outer():
            return inner()

        assert outer() == 42


class TestDomainIntegration:
    """Интеграционные тесты доменов."""

    def setup_method(self):
        """Сброс перед каждым тестом."""
        DomainRegistry.reset()

    def test_domain_priority_ordering(self):
        """Проверка: приоритеты доменов упорядочены."""
        # Используем DEFAULT_DOMAIN_CONFIG напрямую чтобы избежать мутаций
        priorities = {
            ThreadDomain.GUI: 10,
            ThreadDomain.STRATEGY_ENGINE: 9,
            ThreadDomain.RISK_ENGINE: 9,
            ThreadDomain.MT5_IO: 8,
            ThreadDomain.ORCHESTRATOR: 8,
            ThreadDomain.ML_INFERENCE: 7,
        }

        for domain, expected_priority in priorities.items():
            config = DEFAULT_DOMAIN_CONFIG[domain]
            assert (
                config["priority"] == expected_priority
            ), f"{domain.name}: expected {expected_priority}, got {config['priority']}"

    def test_domain_resource_limits_variation(self):
        """Проверка: разные домены имеют разные лимиты."""
        gui_config = DomainRegistry.get_config(ThreadDomain.GUI)
        ml_config = DomainRegistry.get_config(ThreadDomain.ML_INFERENCE)

        # ML может использовать больше CPU
        assert ml_config["resources"].cpu_percent_max > gui_config["resources"].cpu_percent_max

        # ML может иметь больше concurrent tasks
        assert ml_config["resources"].max_concurrent_tasks >= gui_config["resources"].max_concurrent_tasks
