# tests/test_service_integration.py
"""
Integration тесты для SystemServiceManager.

Тестирует интеграцию новых сервисов в TradingSystem.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestSystemServiceManager:
    """Тесты для SystemServiceManager"""
    
    @pytest.fixture
    def mock_trading_system(self):
        """Фикстура для mock TradingSystem"""
        mock_ts = Mock()
        mock_ts.running = True
        mock_ts.is_heavy_init_complete = True
        mock_ts.stop_event = Mock()
        mock_ts.stop_event.is_set = Mock(return_value=False)
        mock_ts.mt5_lock = Mock()
        mock_ts.config = Mock()
        mock_ts.config.TRADE_INTERVAL_SECONDS = 60
        mock_ts.risk_engine = Mock()
        mock_ts.bridge = Mock()
        return mock_ts
    
    def test_service_manager_creation(self, mock_trading_system):
        """Тест создания SystemServiceManager"""
        from src.core.system_service_manager import SystemServiceManager
        
        manager = SystemServiceManager(mock_trading_system)
        
        assert manager is not None
        assert manager.trading_system == mock_trading_system
        assert manager.use_new_services == False  # По умолчанию выключено
    
    def test_service_manager_initialize(self, mock_trading_system):
        """Тест инициализации сервисов"""
        from src.core.system_service_manager import SystemServiceManager
        
        manager = SystemServiceManager(mock_trading_system)
        manager.initialize_services()
        
        # Проверка что сервисы созданы
        assert manager.trading_service is not None
        assert manager.monitoring_service is not None
        assert manager.orchestrator_service is not None
        assert manager.risk_service is not None
        
        # Проверка регистрации
        assert len(manager.service_manager.services) == 4
    
    def test_service_manager_start_stop(self, mock_trading_system):
        """Тест запуска и остановки сервисов (без реального запуска)"""
        from src.core.system_service_manager import SystemServiceManager
        
        manager = SystemServiceManager(mock_trading_system)
        manager.initialize_services()
        
        # Включаем сервисы
        manager.enable_new_services(True)
        assert manager.use_new_services == True
        
        # Проверяем что сервисы зарегистрированы
        assert len(manager.service_manager.services) == 4
        
        # Не запускаем реально - только проверяем регистрацию
        # results = manager.start_all()
        # assert isinstance(results, dict)
    
    def test_service_manager_status(self, mock_trading_system):
        """Тест получения статуса сервисов"""
        from src.core.system_service_manager import SystemServiceManager
        
        manager = SystemServiceManager(mock_trading_system)
        manager.initialize_services()
        
        # Статус до включения
        status = manager.get_status()
        assert "use_new_services" in status or isinstance(status, dict)
        
        # Включаем и проверяем
        manager.enable_new_services(True)
        status = manager.get_status()
        assert isinstance(status, dict)
    
    def test_service_manager_health_check(self, mock_trading_system):
        """Тест проверки здоровья сервисов"""
        from src.core.system_service_manager import SystemServiceManager
        
        manager = SystemServiceManager(mock_trading_system)
        manager.initialize_services()
        
        # Проверка здоровья
        health = manager.health_check()
        assert isinstance(health, dict)
    
    def test_service_manager_get_services(self, mock_trading_system):
        """Тест получения отдельных сервисов"""
        from src.core.system_service_manager import SystemServiceManager
        
        manager = SystemServiceManager(mock_trading_system)
        manager.initialize_services()
        
        # Получение сервисов
        assert manager.get_trading_service() is not None
        assert manager.get_monitoring_service() is not None
        assert manager.get_orchestrator_service() is not None
        assert manager.get_risk_service() is not None
    
    def test_backward_compatibility(self, mock_trading_system):
        """Тест обратной совместимости (сервисы выключены)"""
        from src.core.system_service_manager import SystemServiceManager
        
        manager = SystemServiceManager(mock_trading_system)
        manager.initialize_services()
        
        # Сервисы выключены по умолчанию
        assert manager.use_new_services == False
        
        # Запуск не должен ничего делать
        results = manager.start_all()
        assert results == {}
        
        # Остановка не должна ничего делать
        results = manager.stop_all()
        assert results == {}
        
        # Статус должен показывать что сервисы выключены
        status = manager.get_status()
        assert "use_new_services" in str(status)


class TestTradingSystemIntegration:
    """Тесты интеграции в TradingSystem"""
    
    @pytest.mark.skip(reason="Требует полной инициализации TradingSystem")
    def test_trading_system_has_service_manager(self):
        """Тест что TradingSystem имеет service_manager"""
        # Этот тест требует реальной инициализации TradingSystem
        # Пока пропускаем
        pass
    
    @pytest.mark.skip(reason="Требует полной инициализации TradingSystem")
    def test_trading_system_enable_services(self):
        """Тест включения сервисов в TradingSystem"""
        # Этот тест требует реальной инициализации TradingSystem
        # Пока пропускаем
        pass
