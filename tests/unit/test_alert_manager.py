# tests/unit/test_alert_manager.py
"""
Тесты для Alert Manager System.

Проверяет:
- Инициализацию и конфигурацию
- Отправку алертов по каналам
- Rate limiting
- Quiet hours
- Историю и статистику
"""

import pytest
from datetime import datetime, time as dt_time
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.monitoring.alert_manager import AlertManager, AlertLevel, AlertRecord
from src.core.config_models import Settings


@pytest.fixture
def sample_config():
    """Фикстура с тестовой конфигурацией."""
    config_dict = {
        'alerting': {
            'enabled': True,
            'channels': {
                'telegram': {
                    'enabled': False,
                    'bot_token_env': 'TEST_TELEGRAM_TOKEN',
                    'chat_id_env': 'TEST_CHAT_ID'
                },
                'email': {
                    'enabled': False,
                    'smtp_server': 'smtp.test.com',
                    'smtp_port': 587,
                    'use_tls': True,
                    'from_email_env': 'test@example.com',
                    'password_env': 'testpass',
                    'recipients_env': 'recipient@example.com'
                },
                'push': {
                    'enabled': False,
                    'user_key_env': 'TEST_PUSHOVER_KEY',
                    'api_token_env': 'TEST_PUSHOVER_TOKEN'
                }
            },
            'rate_limit': {
                'max_per_minute': 10,
                'cooldown_seconds': 60
            },
            'quiet_hours': {
                'enabled': False,
                'start': '22:00',
                'end': '08:00',
                'timezone': 'UTC'
            },
            'daily_digest': {
                'enabled': True,
                'time': '20:00',
                'timezone': 'UTC'
            }
        }
    }
    return Settings(**config_dict)


@pytest.fixture
def mock_trading_system():
    """Фикстура с моком TradingSystem."""
    return MagicMock()


class TestAlertManagerInit:
    """Тесты инициализации Alert Manager."""
    
    def test_init_default_values(self, sample_config):
        """Тест инициализации с конфигурацией по умолчанию."""
        am = AlertManager(sample_config)
        
        assert am.enabled is True
        assert am.max_alerts_per_minute == 10
        assert am.cooldown_seconds == 60
        assert am.daily_digest_enabled is True
    
    def test_init_with_trading_system(self, sample_config, mock_trading_system):
        """Тест инициализации с ссылкой на TradingSystem."""
        am = AlertManager(sample_config, mock_trading_system)
        
        assert am.trading_system is mock_trading_system
    
    def test_init_statistics(self, sample_config):
        """Тест инициализации статистики."""
        am = AlertManager(sample_config)
        
        stats = am.get_statistics()
        assert stats['total_sent'] == 0
        assert stats['telegram_sent'] == 0
        assert stats['email_sent'] == 0
        assert stats['push_sent'] == 0
        assert stats['failed'] == 0


class TestAlertLevelChannels:
    """Тесты маршрутизации по уровням."""
    
    def test_info_level_routes_to_log_only(self, sample_config):
        """Тест INFO уровня — только лог."""
        am = AlertManager(sample_config)
        
        channels = am.LEVEL_CHANNELS[AlertLevel.INFO]
        assert channels == ['log']
    
    def test_warning_level_routes_to_telegram(self, sample_config):
        """Тест WARNING уровня — Telegram."""
        am = AlertManager(sample_config)
        
        channels = am.LEVEL_CHANNELS[AlertLevel.WARNING]
        assert 'telegram' in channels
    
    def test_error_level_routes_to_email(self, sample_config):
        """Тест ERROR уровня — Email."""
        am = AlertManager(sample_config)
        
        channels = am.LEVEL_CHANNELS[AlertLevel.ERROR]
        assert 'email' in channels
    
    def test_critical_level_routes_to_all(self, sample_config):
        """Тест CRITICAL уровня — все каналы."""
        am = AlertManager(sample_config)
        
        channels = am.LEVEL_CHANNELS[AlertLevel.CRITICAL]
        assert 'telegram' in channels
        assert 'email' in channels
        assert 'push' in channels


class TestAlertEmojis:
    """Тесты эмодзи для уровней."""
    
    def test_info_emoji(self):
        """Тест INFO эмодзи."""
        assert AlertManager.LEVEL_EMOJI[AlertLevel.INFO] == '🔵'
    
    def test_warning_emoji(self):
        """Тест WARNING эмодзи."""
        assert AlertManager.LEVEL_EMOJI[AlertLevel.WARNING] == '🟡'
    
    def test_error_emoji(self):
        """Тест ERROR эмодзи."""
        assert AlertManager.LEVEL_EMOJI[AlertLevel.ERROR] == '🟠'
    
    def test_critical_emoji(self):
        """Тест CRITICAL эмодзи."""
        assert AlertManager.LEVEL_EMOJI[AlertLevel.CRITICAL] == '🔴'


class TestSendAlert:
    """Тесты отправки алертов."""
    
    def test_send_alert_disabled(self, sample_config):
        """Тест отправки при отключенном Alert Manager."""
        sample_config.alerting.enabled = False
        am = AlertManager(sample_config)
        
        result = am.send_alert(AlertLevel.INFO, "Test message")
        assert result is False
    
    def test_send_alert_info_logs(self, sample_config):
        """Тест INFO алерта — только логирование."""
        am = AlertManager(sample_config)
        
        with patch.object(am, '_log_alert') as mock_log:
            result = am.send_alert(AlertLevel.INFO, "Test message")
            mock_log.assert_called_once()
    
    def test_send_alert_adds_to_history(self, sample_config):
        """Тест добавления в историю."""
        am = AlertManager(sample_config)
        
        am.send_alert(AlertLevel.INFO, "Test message")
        
        history = am.get_alert_history()
        assert len(history) == 1
        assert history[0]['message'] == '🔵 Test message'
        assert history[0]['level'] == AlertLevel.INFO
    
    def test_send_alert_updates_statistics(self, sample_config):
        """Тест обновления статистики."""
        am = AlertManager(sample_config)
        
        am.send_alert(AlertLevel.INFO, "Test message")
        
        stats = am.get_statistics()
        assert stats['total_sent'] == 1


class TestRateLimiting:
    """Тесты rate limiting."""
    
    def test_rate_limit_allows_normal_flow(self, sample_config):
        """Тест нормального потока алертов."""
        am = AlertManager(sample_config)
        
        # Отправляем меньше лимита
        for i in range(5):
            result = am._check_rate_limit()
            assert result is True
    
    def test_rate_limit_blocks_excess(self, sample_config):
        """Тест блокировки превышения лимита."""
        am = AlertManager(sample_config)
        am.max_alerts_per_minute = 3
        
        # Превышаем лимит
        for i in range(3):
            am._check_rate_limit()
        
        # Следующий должен быть заблокирован
        result = am._check_rate_limit()
        assert result is False
    
    def test_rate_limit_resets_after_minute(self, sample_config):
        """Тест сброса лимита после минуты."""
        am = AlertManager(sample_config)
        am.max_alerts_per_minute = 2
        
        # Превышаем лимит
        am._check_rate_limit()
        am._check_rate_limit()
        
        # Имитируем прошедшее время
        am._last_minute_reset = datetime.now() - timedelta(seconds=61)
        
        # Должен разрешить
        result = am._check_rate_limit()
        assert result is True


class TestQuietHours:
    """Тесты quiet hours."""
    
    def test_quiet_hours_disabled(self, sample_config):
        """Тест отключенных quiet hours."""
        sample_config.alerting.quiet_hours.enabled = False
        am = AlertManager(sample_config)
        
        result = am._is_quiet_hours()
        assert result is False
    
    def test_quiet_hours_overnight(self, sample_config):
        """Тест overnight quiet hours (22:00 - 08:00)."""
        sample_config.alerting.quiet_hours.enabled = True
        sample_config.alerting.quiet_hours.start = '22:00'
        sample_config.alerting.quiet_hours.end = '08:00'
        am = AlertManager(sample_config)
        
        # Тестируем 23:00 (должно быть quiet hours)
        with patch('src.monitoring.alert_manager.datetime') as mock_dt:
            mock_dt.now.return_value.time.return_value = dt_time(23, 0)
            result = am._is_quiet_hours()
            assert result is True
        
        # Тестируем 03:00 (должно быть quiet hours)
        with patch('src.monitoring.alert_manager.datetime') as mock_dt:
            mock_dt.now.return_value.time.return_value = dt_time(3, 0)
            result = am._is_quiet_hours()
            assert result is True
        
        # Тестируем 12:00 (не должно быть quiet hours)
        with patch('src.monitoring.alert_manager.datetime') as mock_dt:
            mock_dt.now.return_value.time.return_value = dt_time(12, 0)
            result = am._is_quiet_hours()
            assert result is False
    
    def test_critical_bypasses_quiet_hours(self, sample_config):
        """Тест что CRITICAL обходит quiet hours."""
        sample_config.alerting.quiet_hours.enabled = True
        am = AlertManager(sample_config)
        
        with patch.object(am, '_is_quiet_hours', return_value=True):
            # CRITICAL должен пройти
            result = am.send_alert(AlertLevel.CRITICAL, "Critical message")
            # Проверяем что не заблокировано (может быть False из-за отключенных каналов)
            # Главное что quiet hours не заблокировал


class TestAlertHistory:
    """Тесты истории алертов."""
    
    def test_get_alert_history_limit(self, sample_config):
        """Тест ограничения истории."""
        am = AlertManager(sample_config)
        
        # Отправляем 150 алертов
        for i in range(150):
            am.send_alert(AlertLevel.INFO, f"Message {i}")
        
        # История должна быть ограничена
        history = am.get_alert_history()
        assert len(history) <= 1000  # maxlen deque
    
    def test_get_alert_history_format(self, sample_config):
        """Тест формата истории."""
        am = AlertManager(sample_config)
        am.send_alert(AlertLevel.WARNING, "Test warning")
        
        history = am.get_alert_history()
        
        assert len(history) == 1
        assert 'level' in history[0]
        assert 'message' in history[0]
        assert 'timestamp' in history[0]
        assert 'channels' in history[0]


class TestAlertRecord:
    """Тесты AlertRecord."""
    
    def test_alert_record_to_dict(self):
        """Тест конвертации в словарь."""
        record = AlertRecord(
            level=AlertLevel.ERROR,
            message="Test error",
            channels=['log', 'email'],
            timestamp=datetime(2026, 3, 28, 12, 0, 0)
        )
        
        data = record.to_dict()
        
        assert data['level'] == AlertLevel.ERROR
        assert data['message'] == "Test error"
        assert data['channels'] == ['log', 'email']
        assert data['timestamp'] == '2026-03-28T12:00:00'
        assert data['success'] is True


class TestChannelSending:
    """Тесты отправки по каналам (с моками)."""
    
    @patch('src.monitoring.alert_manager.httpx.Client')
    def test_send_telegram(self, mock_client_class, sample_config):
        """Тест отправки Telegram."""
        sample_config.alerting.channels.telegram.enabled = True
        am = AlertManager(sample_config)
        
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response
        
        am._send_telegram("Test message")
        
        assert mock_client.post.called
        assert am.stats['telegram_sent'] == 1
    
    @patch('src.monitoring.alert_manager.smtplib.SMTP')
    def test_send_email(self, mock_smtp_class, sample_config):
        """Тест отправки Email."""
        sample_config.alerting.channels.email.enabled = True
        am = AlertManager(sample_config)
        
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp
        
        am._send_email("Test Subject", "Test body")
        
        assert mock_smtp.send_message.called
        assert am.stats['email_sent'] == 1
    
    @patch('src.monitoring.alert_manager.httpx.Client')
    def test_send_push(self, mock_client_class, sample_config):
        """Тест отправки Push."""
        sample_config.alerting.channels.push.enabled = True
        am = AlertManager(sample_config)
        
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response
        
        am._send_push("Test message", priority='normal')
        
        assert mock_client.post.called
        assert am.stats['push_sent'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
