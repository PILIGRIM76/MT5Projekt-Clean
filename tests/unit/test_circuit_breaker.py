# tests/unit/test_circuit_breaker.py
"""
Тесты для Circuit Breaker System.

Проверяет:
- Инициализацию и конфигурацию
- Проверки условий (MT5, спред, волатильность)
- Срабатывание и сброс
- Историю триггеров
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.risk.circuit_breaker import (
    CircuitBreaker, 
    CircuitBreakerState, 
    CircuitBreakerReason,
    CircuitBreakerTrip
)
from src.core.config_models import Settings


@pytest.fixture
def sample_config():
    """Фикстура с тестовой конфигурацией."""
    config = MagicMock(spec=Settings)
    
    # Используем обычный dict для circuit_breaker чтобы работал .get()
    config.circuit_breaker = {
        'enabled': True,
        'mt5_timeout_seconds': 30,
        'spread_multiplier_threshold': 5.0,
        'volatility_threshold_percent': 2.0,
        'volatility_window_minutes': 5,
        'max_consecutive_errors': 3,
        'daily_loss_threshold_percent': 5.0,
        'auto_close_positions': True,
        'cooldown_minutes': 15
    }
    
    # Общие настройки
    config.SYMBOLS_WHITELIST = ['EURUSD', 'GBPUSD']
    config.MT5_PATH = 'C:/test/mt5.exe'
    
    return config


@pytest.fixture
def mock_trading_system():
    """Фикстура с моком TradingSystem."""
    ts = MagicMock()
    ts.config.SYMBOLS_WHITELIST = ['EURUSD', 'GBPUSD']
    ts.mt5_lock = MagicMock()
    return ts


class TestCircuitBreakerInit:
    """Тесты инициализации Circuit Breaker."""
    
    def test_init_default_values(self, sample_config):
        """Тест инициализации с конфигурацией по умолчанию."""
        cb = CircuitBreaker(sample_config)
        
        assert cb.enabled is True
        assert cb.mt5_timeout_seconds == 30
        assert cb.spread_multiplier_threshold == 5.0
        assert cb.volatility_threshold_percent == 2.0
        assert cb.max_consecutive_errors == 3
        assert cb.daily_loss_threshold_percent == 5.0
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.is_trading_allowed is True
    
    def test_init_with_trading_system(self, sample_config, mock_trading_system):
        """Тест инициализации с ссылкой на TradingSystem."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        
        assert cb.trading_system is mock_trading_system
    
    def test_initialize_session(self, sample_config):
        """Тест инициализации сессии."""
        cb = CircuitBreaker(sample_config)
        cb.initialize_session(initial_balance=100000)
        
        assert cb._session_start_balance == 100000
        assert cb._session_start_time is not None
        assert cb.trip_count == 0
        assert cb.state == CircuitBreakerState.CLOSED


class TestCircuitBreakerChecks:
    """Тесты проверок условий."""
    
    def test_check_conditions_all_safe(self, sample_config, mock_trading_system):
        """Тест когда все проверки пройдены."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        cb.initialize_session(100000)
        
        # Мокаем все проверки чтобы возвращали True
        with patch.object(cb, '_check_mt5_connection', return_value=True), \
             patch.object(cb, '_check_spread_normal', return_value=True), \
             patch.object(cb, '_check_volatility_normal', return_value=True), \
             patch.object(cb, '_check_consecutive_errors', return_value=True), \
             patch.object(cb, '_check_daily_loss_limit', return_value=True):
            
            result = cb.check_conditions()
            assert result is True
    
    def test_check_conditions_mt5_lost(self, sample_config, mock_trading_system):
        """Тест потери подключения к MT5."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        
        with patch.object(cb, '_check_mt5_connection', return_value=False):
            result = cb.check_conditions()
            assert result is False
    
    def test_check_conditions_high_spread(self, sample_config, mock_trading_system):
        """Тест аномального спреда."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        
        with patch.object(cb, '_check_spread_normal', return_value=False):
            result = cb.check_conditions()
            assert result is False
    
    def test_check_conditions_high_volatility(self, sample_config, mock_trading_system):
        """Тест высокой волатильности."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        
        with patch.object(cb, '_check_volatility_normal', return_value=False):
            result = cb.check_conditions()
            assert result is False


class TestCircuitBreakerTrip:
    """Тесты срабатывания Circuit Breaker."""
    
    def test_trip_opens_circuit(self, sample_config, mock_trading_system):
        """Тест срабатывания Circuit Breaker."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        cb.initialize_session(100000)
        
        cb.trip(CircuitBreakerReason.MT5_CONNECTION_LOST)
        
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.trip_count == 1
        assert cb.last_trip_time is not None
        assert cb.is_trading_allowed is False
    
    def test_trip_records_history(self, sample_config, mock_trading_system):
        """Тест записи в историю срабатываний."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        
        cb.trip(CircuitBreakerReason.ABNORMAL_SPREAD, context={'spread': 50})
        
        assert len(cb.trip_history) == 1
        assert cb.trip_history[0].reason == CircuitBreakerReason.ABNORMAL_SPREAD
        assert cb.trip_history[0].context == {'spread': 50}
    
    def test_trip_closes_positions(self, sample_config, mock_trading_system):
        """Тест автоматического закрытия позиций."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        cb.auto_close_positions = True
        
        # Мокаем метод закрытия позиций
        with patch.object(cb, '_close_all_positions') as mock_close:
            cb.trip(CircuitBreakerReason.DAILY_LOSS_LIMIT)
            mock_close.assert_called_once()
    
    def test_triple_trip_emergency_shutdown(self, sample_config, mock_trading_system):
        """Тест тройного срабатывания — аварийная остановка."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        
        # Три срабатывания
        cb.trip(CircuitBreakerReason.MT5_CONNECTION_LOST)
        cb.trip(CircuitBreakerReason.ABNORMAL_SPREAD)
        cb.trip(CircuitBreakerReason.HIGH_VOLATILITY)
        
        # TradingSystem должен быть остановлен
        assert mock_trading_system.running is False
    
    def test_reset_closes_circuit(self, sample_config, mock_trading_system):
        """Тест сброса Circuit Breaker."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        cb.trip(CircuitBreakerReason.MT5_CONNECTION_LOST)
        
        assert cb.state == CircuitBreakerState.OPEN
        
        cb.reset()
        
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.is_trading_allowed is True
    
    def test_get_status(self, sample_config, mock_trading_system):
        """Тест получения статуса."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        cb.initialize_session(100000)
        cb.trip(CircuitBreakerReason.MT5_CONNECTION_LOST)
        
        status = cb.get_status()
        
        assert status['state'] == 'OPEN'
        assert status['trip_count'] == 1
        assert status['is_trading_allowed'] is False
        assert 'last_trip_time' in status


class TestCircuitBreakerErrors:
    """Тесты обработки ошибок."""
    
    def test_record_error_increments_counter(self, sample_config):
        """Тест записи ошибки."""
        cb = CircuitBreaker(sample_config)
        
        cb.record_error()
        assert cb.consecutive_errors == 1
        
        cb.record_error()
        assert cb.consecutive_errors == 2
    
    def test_record_error_trips_at_threshold(self, sample_config, mock_trading_system):
        """Тест срабатывания при превышении лимита ошибок."""
        cb = CircuitBreaker(sample_config, mock_trading_system)
        
        # 3 ошибки должны вызвать срабатывание
        cb.record_error()
        cb.record_error()
        cb.record_error()
        
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.trip_history[-1].reason == CircuitBreakerReason.CONSECUTIVE_ERRORS
    
    def test_error_counter_resets_after_timeout(self, sample_config):
        """Тест сброса счётчика ошибок после таймаута."""
        cb = CircuitBreaker(sample_config)
        
        cb.record_error()
        cb.record_error()
        assert cb.consecutive_errors == 2
        
        # Имитируем прошедшее время (больше 60 секунд)
        cb.last_error_time = datetime.now() - timedelta(seconds=61)
        
        # Следующая проверка должна сбросить счётчик
        result = cb._check_consecutive_errors()
        assert cb.consecutive_errors == 0


class TestCircuitBreakerSpreadHistory:
    """Тесты истории спредов."""
    
    def test_update_spread_history(self, sample_config):
        """Тест обновления истории спредов."""
        cb = CircuitBreaker(sample_config)
        
        cb._update_spread_history(1.0)
        cb._update_spread_history(2.0)
        cb._update_spread_history(3.0)
        
        assert len(cb._spread_history) == 3
        assert cb._spread_history == [1.0, 2.0, 3.0]
    
    def test_spread_history_limited(self, sample_config):
        """Тест ограничения размера истории спредов."""
        cb = CircuitBreaker(sample_config)
        
        # Добавляем больше чем максимум
        for i in range(1500):
            cb._update_spread_history(float(i))
        
        # История должна быть ограничена
        assert len(cb._spread_history) <= cb._spread_history_max


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
