# tests/test_base_service.py
"""
Unit тесты для базового класса BaseService.
"""

import pytest
from datetime import datetime
from src.core.services.base_service import (
    BaseService, ServiceManager, ServiceState, HealthStatus, ServiceMetrics
)


class MockService(BaseService):
    """Mock сервис для тестирования"""
    
    def __init__(self, name: str = "MockService", config: dict = None):
        super().__init__(name, config)
        self.start_called = False
        self.stop_called = False
        self.health_check_called = False
    
    def _on_start(self) -> None:
        self.start_called = True
    
    def _on_stop(self) -> None:
        self.stop_called = True
    
    def _health_check(self) -> HealthStatus:
        self.health_check_called = True
        return HealthStatus(
            is_healthy=True,
            checks={"mock_check": True},
            message="OK"
        )


class TestBaseService:
    """Тесты для BaseService"""
    
    def test_service_creation(self):
        """Тест создания сервиса"""
        service = MockService()
        assert service.name == "MockService"
        assert service.state == ServiceState.CREATED
        assert service.is_running == False
    
    def test_service_start(self):
        """Тест запуска сервиса"""
        service = MockService()
        result = service.start()
        
        assert result == True
        assert service.state == ServiceState.RUNNING
        assert service.is_running == True
        assert service.start_called == True
        assert service.metrics.start_time is not None
    
    def test_service_stop(self):
        """Тест остановки сервиса"""
        service = MockService()
        service.start()
        result = service.stop()
        
        assert result == True
        assert service.state == ServiceState.STOPPED
        assert service.is_running == False
        assert service.stop_called == True
        assert service.metrics.stop_time is not None
    
    def test_service_restart(self):
        """Тест перезапуска сервиса"""
        service = MockService()
        service.start()
        initial_start_time = service.metrics.start_time
        
        result = service.restart()
        
        assert result == True
        assert service.state == ServiceState.RUNNING
        assert service.metrics.start_time > initial_start_time
    
    def test_health_check(self):
        """Тест проверки здоровья"""
        service = MockService()
        service.start()
        
        health = service.health_check()
        
        assert health.is_healthy == True
        assert "mock_check" in health.checks
        assert health.checks["mock_check"] == True
        assert health.last_check is not None
        assert service.health_check_called == True
    
    def test_get_metrics(self):
        """Тест получения метрик"""
        service = MockService()
        service.start()
        
        metrics = service.get_metrics()
        
        assert isinstance(metrics, ServiceMetrics)
        assert metrics.start_time is not None
        assert metrics.uptime_seconds > 0
    
    def test_get_status(self):
        """Тест получения статуса"""
        service = MockService()
        service.start()
        
        status = service.get_status()
        
        assert isinstance(status, dict)
        assert status["name"] == "MockService"
        assert status["state"] == "running"
        assert status["is_running"] == True
        assert "metrics" in status
    
    def test_increment_operations(self):
        """Тест счетчика операций"""
        service = MockService()
        service.start()
        
        service.increment_operations(5)
        assert service.metrics.operations_count == 5
        
        service.increment_operations(3)
        assert service.metrics.operations_count == 8
    
    def test_record_error(self):
        """Тест записи ошибок"""
        service = MockService()
        service.record_error("Test error")
        
        assert service.metrics.errors_count == 1
        assert service.metrics.last_error == "Test error"
        assert service.metrics.last_error_time is not None
    
    def test_record_metric(self):
        """Тест записи метрик"""
        service = MockService()
        service.record_metric("test_metric", 42.0)
        
        assert "test_metric" in service.metrics.custom_metrics
        assert service.metrics.custom_metrics["test_metric"] == 42.0


class TestServiceManager:
    """Тесты для ServiceManager"""
    
    def test_manager_creation(self):
        """Тест создания менеджера"""
        manager = ServiceManager()
        assert manager.name == "ServiceManager"
        assert len(manager.services) == 0
    
    def test_register_service(self):
        """Тест регистрации сервиса"""
        manager = ServiceManager()
        service = MockService("TestService")
        
        manager.register(service)
        
        assert len(manager.services) == 1
        assert manager.get_service("TestService") == service
    
    def test_unregister_service(self):
        """Тест от регистрации сервиса"""
        manager = ServiceManager()
        service = MockService("TestService")
        manager.register(service)
        
        unregistered = manager.unregister("TestService")
        
        assert unregistered == service
        assert len(manager.services) == 0
        assert manager.get_service("TestService") is None
    
    def test_start_all(self):
        """Тест запуска всех сервисов"""
        manager = ServiceManager()
        service1 = MockService("Service1")
        service2 = MockService("Service2")
        
        manager.register(service1)
        manager.register(service2)
        
        results = manager.start_all()
        
        assert len(results) == 2
        assert results["Service1"] == True
        assert results["Service2"] == True
        assert service1.is_running == True
        assert service2.is_running == True
    
    def test_stop_all(self):
        """Тест остановки всех сервисов"""
        manager = ServiceManager()
        service1 = MockService("Service1")
        service2 = MockService("Service2")
        
        manager.register(service1)
        manager.register(service2)
        manager.start_all()
        
        results = manager.stop_all()
        
        assert len(results) == 2
        assert results["Service1"] == True
        assert results["Service2"] == True
        assert service1.is_running == False
        assert service2.is_running == False
    
    def test_health_check_all(self):
        """Тест проверки здоровья всех сервисов"""
        manager = ServiceManager()
        service1 = MockService("Service1")
        service2 = MockService("Service2")
        
        manager.register(service1)
        manager.register(service2)
        manager.start_all()
        
        health_results = manager.health_check_all()
        
        assert len(health_results) == 2
        assert health_results["Service1"].is_healthy == True
        assert health_results["Service2"].is_healthy == True
    
    def test_get_status_all(self):
        """Тест получения статуса всех сервисов"""
        manager = ServiceManager()
        service1 = MockService("Service1")
        service2 = MockService("Service2")
        
        manager.register(service1)
        manager.register(service2)
        manager.start_all()
        
        status_all = manager.get_status_all()
        
        assert len(status_all) == 2
        assert "Service1" in status_all
        assert "Service2" in status_all
        assert status_all["Service1"]["is_running"] == True
    
    def test_get_running_count(self):
        """Тест подсчета запущенных сервисов"""
        manager = ServiceManager()
        service1 = MockService("Service1")
        service2 = MockService("Service2")
        
        manager.register(service1)
        manager.register(service2)
        
        assert manager.get_running_count() == 0
        
        manager.start_all()
        assert manager.get_running_count() == 2
        
        manager.stop_all()
        assert manager.get_running_count() == 0
    
    def test_get_healthy_count(self):
        """Тест подсчета здоровых сервисов"""
        manager = ServiceManager()
        service1 = MockService("Service1")
        service2 = MockService("Service2")
        
        manager.register(service1)
        manager.register(service2)
        manager.start_all()
        
        assert manager.get_healthy_count() == 2
