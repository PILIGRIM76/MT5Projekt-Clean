"""
Тесты для TradingSystem - кэширование и директивы
"""

import time
from datetime import datetime, timedelta
from unittest.mock import Mock, PropertyMock, patch

import numpy as np
import pytest

from src.core.trading_system import TradingSystem


@pytest.fixture
def mock_config():
    """Фикстура для конфигурации"""
    config = Mock()
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
    return config


@pytest.fixture
def trading_system(mock_config):
    """Фикстура для TradingSystem с минимальными моками"""
    # Мокаем только тяжелые зависимости которые импортируются
    mock_db = Mock()
    mock_db.get_all_active_directives.return_value = []  # Пустой список директив
    mock_db.save_directives.return_value = True
    mock_db.delete_directive_by_type.return_value = True

    with (
        patch("src.core.trading_system.mt5", Mock()),
        patch("src.core.trading_system.SentenceTransformer", Mock()),
        patch("src.core.trading_system.DatabaseManager", return_value=mock_db),
        patch("src.core.trading_system.VectorDBManager", Mock()),
    ):

        ts = TradingSystem(config=mock_config, gui=None, sound_manager=None, bridge=None)
        ts.db_manager = mock_db  # Явно устанавливаем мок
        return ts


class TestTradingSystemCache:
    """Тесты кэширования в TradingSystem"""

    def test_set_cached_data(self, trading_system):
        """Тест сохранения данных в кэш"""
        key = "test_key"
        data = {"price": 100.5, "volume": 1000}
        ttl = 300

        trading_system.set_cached_data(key, data, ttl)

        assert key in trading_system._data_cache
        assert trading_system._data_cache[key] == data
        assert key in trading_system._cache_timestamps
        assert key in trading_system._cache_ttl
        assert trading_system._cache_ttl[key] == ttl

    def test_get_cached_data_valid(self, trading_system):
        """Тест получения валидных данных из кэша"""
        key = "test_key"
        data = {"indicator": "RSI", "value": 0.7}
        ttl = 300

        trading_system.set_cached_data(key, data, ttl)
        cached = trading_system.get_cached_data(key, ttl)

        assert cached == data

    def test_get_cached_data_expired(self, trading_system):
        """Тест получения устаревших данных из кэша"""
        key = "test_key"
        data = {"old_data": True}
        ttl = 1  # 1 секунда

        trading_system.set_cached_data(key, data, ttl)
        time.sleep(1.1)  # Ждем истечения TTL

        cached = trading_system.get_cached_data(key, ttl)

        assert cached is None
        assert key not in trading_system._data_cache

    def test_get_cached_data_nonexistent(self, trading_system):
        """Тест получения несуществующих данных из кэша"""
        cached = trading_system.get_cached_data("nonexistent_key")

        assert cached is None

    def test_invalidate_cache_single_key(self, trading_system):
        """Тест инвалидации отдельного ключа"""
        key1 = "test_key1"
        key2 = "test_key2"
        data = {"value": 123}

        trading_system.set_cached_data(key1, data, 300)
        trading_system.set_cached_data(key2, data, 300)

        trading_system.invalidate_cache(key1)

        assert key1 not in trading_system._data_cache
        assert key1 not in trading_system._cache_timestamps
        assert key1 not in trading_system._cache_ttl
        assert key2 in trading_system._data_cache

    def test_invalidate_cache_all(self, trading_system):
        """Тест полной инвалидации кэша"""
        data = {"value": 123}

        trading_system.set_cached_data("key1", data, 300)
        trading_system.set_cached_data("key2", data, 300)
        trading_system.set_cached_data("key3", data, 300)

        trading_system.invalidate_cache()

        assert len(trading_system._data_cache) == 0
        assert len(trading_system._cache_timestamps) == 0
        assert len(trading_system._cache_ttl) == 0

    def test_cache_with_different_ttl(self, trading_system):
        """Тест кэширования с разным TTL"""
        short_ttl_data = {"short": True}
        long_ttl_data = {"long": True}

        trading_system.set_cached_data("short_key", short_ttl_data, ttl_seconds=1)
        trading_system.set_cached_data("long_key", long_ttl_data, ttl_seconds=300)

        # Оба ключа должны быть в кэше
        assert trading_system.get_cached_data("short_key", 1) == short_ttl_data
        assert trading_system.get_cached_data("long_key", 300) == long_ttl_data

        time.sleep(1.1)

        # Короткий ключ должен истечь
        assert trading_system.get_cached_data("short_key", 1) is None
        assert trading_system.get_cached_data("long_key", 300) == long_ttl_data

    def test_cache_thread_safety(self, trading_system):
        """Тест потокобезопасности кэша"""
        import threading

        results = []
        errors = []

        def set_cache(thread_id):
            try:
                for i in range(10):
                    key = f"thread_{thread_id}_key_{i}"
                    trading_system.set_cached_data(key, {"thread": thread_id, "i": i}, 300)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=set_cache, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        # Проверяем, что все данные записаны
        assert len(trading_system._data_cache) == 50  # 5 threads * 10 keys


class TestTradingSystemPerformanceTimer:
    """Тесты таймера производительности"""

    def test_start_performance_timer(self, trading_system):
        """Тест запуска таймера производительности"""
        operation = "test_operation"

        trading_system.start_performance_timer(operation)

        assert operation in trading_system.performance_metrics
        assert "start_time" in trading_system.performance_metrics[operation]


class TestTradingSystemActiveDirectives:
    """Тесты активных директив"""

    def test_add_to_blacklist(self, trading_system):
        """Тест добавления символа в черный список"""
        symbol = "BTCUSD"

        trading_system.add_to_blacklist(symbol)

        directive_key = f"BLOCK_SYMBOL_{symbol}"
        assert directive_key in trading_system.active_directives

        directive = trading_system.active_directives[directive_key]
        assert directive.directive_type == directive_key
        assert directive.value == "true"
        assert "Manually blacklisted" in directive.reason
        # Проверяем, что срок действия ~365 дней
        assert directive.expires_at > datetime.utcnow() + timedelta(days=364)

    def test_active_directives_initially_empty(self, trading_system):
        """Тест что директивы изначально пусты"""
        assert len(trading_system.active_directives) == 0

    def test_directive_structure(self, trading_system):
        """Тест структуры директивы"""
        # Добавляем директиву напрямую в active_directives
        from src.db.database_manager import ActiveDirective

        directive = ActiveDirective(
            directive_type="TEST_DIRECTIVE",
            value="test_value",
            reason="Test reason",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )

        trading_system.active_directives["TEST_DIRECTIVE"] = directive

        assert "TEST_DIRECTIVE" in trading_system.active_directives
        assert directive.value == "test_value"
        assert directive.reason == "Test reason"


class TestTradingSystemCreateSequences:
    """Тесты создания последовательностей"""

    def test_create_sequences_success(self, trading_system):
        """Тест успешного создания последовательностей"""
        data = np.random.randn(100, 5)
        n_steps = 10

        X, y = trading_system._create_sequences(data, n_steps)

        assert X is not None
        assert y is not None
        assert X.shape == (90, 10, 5)  # (len(data) - n_steps, n_steps, features)
        # y может быть 2D для многомерных данных
        assert y.shape[0] == 90

    def test_create_sequences_insufficient_data(self, trading_system):
        """Тест создания последовательностей при недостаточных данных"""
        data = np.random.randn(5, 5)
        n_steps = 10

        X, y = trading_system._create_sequences(data, n_steps)

        assert X is None
        assert y is None

    def test_create_sequences_exact_minimum(self, trading_system):
        """Тест создания последовательностей при минимальном количестве данных"""
        data = np.random.randn(10, 5)
        n_steps = 10

        X, y = trading_system._create_sequences(data, n_steps)

        assert X is None  # Нужно больше чем n_steps
        assert y is None

    def test_create_sequences_single_feature(self, trading_system):
        """Тест создания последовательностей с одним признаком"""
        data = np.random.randn(50, 1)
        n_steps = 5

        X, y = trading_system._create_sequences(data, n_steps)

        assert X is not None
        assert X.shape == (45, 5, 1)
        assert y is not None

    def test_create_sequences_1d_data(self, trading_system):
        """Тест создания последовательностей с 1D данными"""
        data = np.random.randn(50)
        n_steps = 5

        X, y = trading_system._create_sequences(data, n_steps)

        # 1D данные должны быть обработаны
        assert X is not None
        assert X.shape == (45, 5)
        assert y is not None


class TestTradingSystemXaiCache:
    """Тесты кэширования XAI данных"""

    def test_get_xai_data_for_trade_cached(self, trading_system):
        """Тест получения XAI данных из кэша"""
        ticket = 12345
        xai_data = {"shap_values": {"feature1": 0.5}, "base_value": 100.0}

        # Сохраняем в кэш
        cache_key = f"xai_data_{ticket}"
        trading_system.set_cached_data(cache_key, xai_data, ttl_seconds=600)

        # Получаем из кэша
        result = trading_system.get_xai_data_for_trade(ticket)

        assert result == xai_data
