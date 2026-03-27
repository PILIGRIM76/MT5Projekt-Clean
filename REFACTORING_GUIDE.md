# Руководство по рефакторингу TradingSystem

## 📋 Обзор

Этот документ описывает процесс рефакторинга монолитного `TradingSystem` (3156 строк) на модульные сервисы.

## 🎯 Цели рефакторинга

1. **Уменьшение связанности** - каждый сервис отвечает за одну функцию
2. **Улучшение тестируемости** - сервисы можно тестировать изолированно
3. **Повышение читаемости** - код организован по функциональности
4. **Упрощение поддержки** - легче находить и исправлять ошибки
5. **Масштабируемость** - легко добавлять новые функции

## 🏗️ Архитектура

### **Базовые классы**

```
src/core/services/base_service.py
├── BaseService          # Абстрактный базовый класс для всех сервисов
├── ServiceManager       # Менеджер для управления группой сервисов
├── ServiceState         # Enum состояний сервиса
├── HealthStatus         # Статус здоровья сервиса
└── ServiceMetrics       # Метрики производительности
```

### **Конкретные сервисы**

```
src/core/services/
├── trading_service.py       # Торговый цикл (async)
├── monitoring_service.py    # Мониторинг и обновление GUI
├── orchestrator_service.py  # RL-оркестратор
├── risk_service.py          # Риск-менеджмент (в разработке)
└── execution_service.py     # Исполнение ордеров (существует)
```

### **Инфраструктура**

```
src/core/
├── loop_manager.py          # Менеджер циклов (универсальный)
├── trading_system.py        # Ядро (координирует сервисы)
└── services/                # Пакет сервисов
```

## 📦 Использование

### **1. Создание сервиса**

```python
from src.core.services.base_service import BaseService, HealthStatus

class MyCustomService(BaseService):
    def __init__(self, config: dict):
        super().__init__(name="MyCustomService")
        self.config = config
    
    def _on_start(self) -> None:
        """Логика запуска"""
        self._logger.info("Запуск...")
        # Инициализация ресурсов
    
    def _on_stop(self) -> None:
        """Логика остановки"""
        self._logger.info("Остановка...")
        # Очистка ресурсов
    
    def _health_check(self) -> HealthStatus:
        """Проверка здоровья"""
        checks = {
            "resource_available": self._check_resource(),
            "connected": self._check_connection(),
        }
        return HealthStatus(
            is_healthy=all(checks.values()),
            checks=checks,
            message="OK" if all(checks.values()) else "Problem detected"
        )
```

### **2. Регистрация в ServiceManager**

```python
from src.core.services import ServiceManager, TradingService, MonitoringService

# Создание менеджера
manager = ServiceManager(name="TradingSystemManager")

# Создание и регистрация сервисов
trading_service = TradingService(trading_system, interval_seconds=60)
monitoring_service = MonitoringService(trading_system, interval_seconds=3)

manager.register(trading_service)
manager.register(monitoring_service)

# Запуск всех сервисов
results = manager.start_all()
print(f"Запущено: {sum(results.values())}/{len(results)}")

# Остановка
manager.stop_all()
```

### **3. Мониторинг состояния**

```python
# Проверка здоровья всех сервисов
health_status = manager.health_check_all()
for name, health in health_status.items():
    print(f"{name}: {'✓' if health.is_healthy else '✗'}")

# Получение метрик
status = manager.get_status_all()
for name, data in status.items():
    print(f"{name}: {data['state']} (uptime: {data['metrics']['uptime_seconds']:.0f}s)")
```

## 🔄 Migration план

### **Фаза 1: Создание инфраструктуры** ✅

- [x] `base_service.py` - Базовые классы
- [x] `loop_manager.py` - Менеджер циклов
- [x] `trading_service.py` - Торговый сервис
- [x] `monitoring_service.py` - Сервис мониторинга
- [x] `orchestrator_service.py` - Сервис оркестратора

### **Фаза 2: Интеграция в TradingSystem** (В процессе)

```python
# В TradingSystem.__init__:
from src.core.services import ServiceManager, TradingService, MonitoringService, OrchestratorService

# Создание менеджера сервисов
self.service_manager = ServiceManager()

# Создание сервисов
self.trading_service = TradingService(self, interval_seconds=self.config.TRADE_INTERVAL_SECONDS)
self.monitoring_service = MonitoringService(self, interval_seconds=3)
self.orchestrator_service = OrchestratorService(self, interval_seconds=300)

# Регистрация
self.service_manager.register(self.trading_service)
self.service_manager.register(self.monitoring_service)
self.service_manager.register(self.orchestrator_service)

# В start_all_threads:
def start_all_threads(self):
    # ... инициализация ...
    
    # Запуск сервисов вместо ручного создания потоков
    self.service_manager.start_all()
```

### **Фаза 3: Выделение дополнительных сервисов**

- [ ] `risk_service.py` - Риск-менеджмент
- [ ] `data_service.py` - Управление данными
- [ ] `ml_service.py` - ML обучение и предсказания
- [ ] `db_service.py` - Управление БД

### **Фаза 4: Рефакторинг TradingSystem**

После выделения всех сервисов, `TradingSystem` станет координатором:

```python
class TradingSystem(QObject):
    """
    Координатор системы.
    
    НЕ выполняет напрямую:
    - Торговые циклы
    - Мониторинг
    - Обучение моделей
    
    Вместо этого управляет сервисами:
    - service_manager.start_all()
    - service_manager.health_check_all()
    """
    
    def __init__(self, config, gui, bridge):
        # ... конфигурация ...
        
        # Создание менеджера сервисов
        self.service_manager = ServiceManager()
        
        # Регистрация сервисов
        self._register_services()
    
    def _register_services(self):
        self.trading_service = TradingService(self)
        self.monitoring_service = MonitoringService(self)
        self.orchestrator_service = OrchestratorService(self)
        # ... другие сервисы ...
        
        for service in [self.trading_service, self.monitoring_service, ...]:
            self.service_manager.register(service)
    
    def start_all_threads(self):
        """Запуск через менеджер сервисов"""
        self.service_manager.start_all()
    
    def stop(self):
        """Остановка через менеджер сервисов"""
        self.service_manager.stop_all()
```

## 📊 Преимущества нового подхода

| Аспект | До | После |
|--------|-----|-------|
| **Размер TradingSystem** | 3156 строк | ~500 строк |
| **Связанность** | Высокая | Низкая |
| **Тестируемость** | Сложная | Простая |
| **Читаемость** | Низкая | Высокая |
| **Добавление функций** | Сложно | Просто |

## 🧪 Тестирование

### **Unit тесты для сервисов**

```python
# tests/test_trading_service.py
import pytest
from src.core.services.trading_service import TradingService

def test_trading_service_start(mock_trading_system):
    service = TradingService(mock_trading_system)
    assert service.start() == True
    assert service.is_running == True
    service.stop()
    assert service.is_running == False

def test_trading_service_health(mock_trading_system):
    service = TradingService(mock_trading_system)
    service.start()
    health = service.health_check()
    assert health.is_healthy == True
    assert "iterations" in health.details
```

### **Integration тесты**

```python
# tests/test_service_manager.py
def test_service_manager_lifecycle():
    manager = ServiceManager()
    service1 = MockService("Service1")
    service2 = MockService("Service2")
    
    manager.register(service1)
    manager.register(service2)
    
    results = manager.start_all()
    assert all(results.values())
    
    health = manager.health_check_all()
    assert all(h.is_healthy for h in health.values())
    
    manager.stop_all()
    assert manager.get_running_count() == 0
```

## 📚 Дополнительные ресурсы

- [Pattern: Service Layer](https://martinfowler.com/eaaCatalog/serviceLayer.html)
- [Python ABC](https://docs.python.org/3/library/abc.html)
- [Asyncio Best Practices](https://docs.python.org/3/library/asyncio-dev.html)

## ⚠️ Важные замечания

1. **Обратная совместимость**: Старый код продолжает работать
2. **Постепенная миграция**: Можно переносить по одному сервису
3. **Тестирование**: Обязательно тестируйте после каждого изменения
4. **Документация**: Обновляйте docstrings при изменении API

## 🚀 Следующие шаги

1. ✅ Завершить создание сервисов
2. ⏳ Интегрировать в TradingSystem
3. ⏳ Написать unit тесты
4. ⏳ Обновить документацию
5. ⏳ Добавить type hints
6. ⏳ Оптимизировать async операции
