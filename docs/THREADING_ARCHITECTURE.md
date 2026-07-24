# 🧵 Архитектура многопоточности "Единый организм"

## Принципы

1. **Изоляция доменов**: Каждый компонент работает в своём ThreadDomain
2. **Иерархия блокировок**: Захват только по возрастанию уровней
3. **Event-driven коммуникация**: Компоненты общаются через EventBus, не напрямую
4. **Адаптивное управление ресурсами**: Система сама регулирует нагрузку
5. **Graceful degradation**: При сбоях — отключаем не-критичные функции, сохраняем трейдинг

## Быстрый старт

### Добавить новый обработчик событий
```python
from src.core.event_bus import get_event_bus, SystemEvent, EventPriority
from src.core.thread_domains import ThreadDomain

event_bus = get_event_bus()

async def my_handler(event: SystemEvent):
    symbol = event.payload['symbol']
    # ... логика ...
    await event_bus.publish(SystemEvent(
        type="my_result",
        payload={"symbol": symbol, "result": 123},
        priority=EventPriority.MEDIUM
    ))

# Регистрация (обычно в __init__ компонента)
await event_bus.subscribe("market_tick", my_handler, domain=ThreadDomain.ML_INFERENCE)
```

### Использовать блокировки безопасно
```python
from src.core.lock_manager import lock_manager, LockLevel, requires_locks

# Вариант 1: декоратор
@requires_locks(LockLevel.MT5_ACCESS, LockLevel.DB_WRITE)
def save_trade_to_mt5(trade_data):
    # Автоматически защищено
    mt5.order_send(trade_data)
    db.save(trade_data)

# Вариант 2: контекстный менеджер
def complex_operation():
    with lock_manager.acquire(LockLevel.SYMBOL_DATA, LockLevel.MODEL_CACHE):
        # Код имеет доступ к обоим ресурсам
        data = cache.get(symbol)
        if not data:
            data = fetch_and_cache(symbol)
```

### Отладка

#### Проверить статус блокировок
```python
>>> from src.core.lock_manager import lock_manager
>>> lock_manager.get_stats(LockLevel.MT5_ACCESS)
{
    'level': 'MT5_ACCESS',
    'acquire_count': 1523,
    'avg_hold_time_ms': 12.4,
    'contention_ratio': 0.03,  # 3% запросов ждали
}
```

#### Мониторить EventBus
```python
>>> from src.core.event_bus import get_event_bus
>>> get_event_bus().get_stats()
{
    'published': 45210,
    'dispatched': 45198,
    'errors': 2,
    'avg_dispatch_latency_ms': 3.2,
    'queue_size': 0,
}
```

#### Обнаружить риск дедлока
```python
>>> risk = lock_manager.check_deadlock_risk()
>>> if risk:
...     logger.critical(risk)  # Отправить алерт
```

## Частые ошибки и решения

| Ошибка | Причина | Решение |
|--------|---------|---------|
| RuntimeError: Lock hierarchy order | Захват блокировок не по возрастанию | Пересмотреть порядок: CACHE → CONFIG → ... → MODEL_TRAINING |
| TimeoutError: Failed to acquire MT5_ACCESS | Долгая операция держит лок | Уменьшить критическую секцию, вынести тяжёлые вычисления |
| События не доставляются | EventBus не запущен или очередь переполнена | Проверить `event_bus.get_stats()['queue_size']`, увеличить max_queue_size |
| GUI зависает | Блокирующая операция в главном потоке | Использовать `@run_in_domain(ThreadDomain.ML_INFERENCE)` или asyncio.to_thread() |

## Производительность

Ожидаемые метрики на среднем желеде (6 ядер, 16GB RAM):

| Операция | Целевая латентность | 95-й перцентиль |
|----------|---------------------|-----------------|
| Захват блокировки (без ожидания) | < 0.1 ms | < 0.5 ms |
| Публикация события | < 1 ms | < 5 ms |
| Доставка события подписчику | < 10 ms | < 50 ms |
| Инференс модели (одна) | < 50 ms | < 200 ms |
| Обучение модели (фон) | < 5 мин | < 15 мин |

💡 **Совет**: Если метрики хуже — проверить `lock_manager.get_stats()` на высокий `contention_ratio` или `event_bus.get_stats()` на растущую очередь.

---

## 📦 Структура модулей

### src/core/
```
src/core/
├── event_bus.py              # Асинхронная шина с приоритетами
├── lock_manager.py           # Иерархия + deadlock detection
├── thread_domains.py         # Типизация доменов потоков (НОВЫЙ)
├── resource_governor.py      # Адаптивное управление ресурсами
├── circuit_breaker.py        # Защита от каскадных сбоев (НОВЫЙ)
└── __init__.py               # Обновлённый экспорт
```

### tests/core/
```
tests/core/
├── test_event_bus.py         # Тесты AsyncEventBus (НОВЫЙ)
├── test_lock_manager.py      # Тесты LockHierarchy (НОВЫЙ)
└── test_resource_governor.py # Тесты ResourceGovernor (НОВЫЙ)
```

---

## 🔧 API Reference

### ThreadDomains

Домены выполнения определяют где и как выполняется код:

```python
from src.core.thread_domains import ThreadDomain, DomainRegistry, run_in_domain

# Все доступные домены:
ThreadDomain.GUI               # Qt главный поток
ThreadDomain.MT5_IO            # MetaTrader 5 API
ThreadDomain.DATA_INGEST       # Загрузка данных
ThreadDomain.PERSISTENCE       # Запись в БД
ThreadDomain.ML_INFERENCE      # Предсказания моделей
ThreadDomain.ML_TRAINING       # Обучение моделей
ThreadDomain.STRATEGY_ENGINE   # Торговые сигналы
ThreadDomain.RISK_ENGINE       # Расчёт рисков
ThreadDomain.ORCHESTRATOR      # Координация
ThreadDomain.LOGGING           # Фоновое логирование
ThreadDomain.HEALTH_CHECK      # Мониторинг

# Использование декоратора
@run_in_domain(ThreadDomain.ML_INFERENCE)
def predict(symbol: str) -> float:
    return model.predict(symbol)

# Получение конфигурации домена
config = DomainRegistry.get_config(ThreadDomain.ML_INFERENCE)
print(config['resources'].max_concurrent_tasks)  # 4
```

### EventBus (Новый API)

Асинхронная шина событий с приоритетами:

```python
from src.core.event_bus import (
    AsyncEventBus, get_event_bus,
    SystemEvent, EventPriority
)

# Инициализация
event_bus = get_event_bus()
await event_bus.start()

# Подписка
async def on_market_data(event: SystemEvent):
    print(f"Received: {event.payload}")

await event_bus.subscribe(
    "market_data",
    on_market_data,
    domain=ThreadDomain.STRATEGY_ENGINE,
    priority=EventPriority.HIGH
)

# Публикация
await event_bus.publish(SystemEvent(
    type="market_data",
    payload={"symbol": "EURUSD", "price": 1.0850},
    priority=EventPriority.HIGH
))

# Контекстный менеджер
async with event_bus.event_context("trade_executed") as event:
    event.payload["symbol"] = "EURUSD"
    event.payload["profit"] = 150.0
    # Автопубликация при выходе

# Статистика
stats = event_bus.get_stats()
print(f"Published: {stats['published']}")
print(f"Avg latency: {stats['avg_dispatch_latency_ms']}ms")

# Остановка
await event_bus.stop()
```

### LockManager

Иерархические блокировки с защитой от дедлоков:

```python
from src.core.lock_manager import (
    lock_manager, LockLevel,
    requires_locks, DeadlockDetector
)

# Уровни блокировки (захватывать по возрастанию!):
LockLevel.CACHE           # 1 - Кэш данных
LockLevel.CONFIG          # 2 - Конфигурация
LockLevel.SYMBOL_DATA     # 3 - Данные инструмента
LockLevel.MODEL_CACHE     # 4 - Кэш моделей
LockLevel.STRATEGY_STATE  # 5 - Состояние стратегий
LockLevel.DB_WRITE        # 6 - Запись в БД
LockLevel.MT5_ACCESS      # 7 - Доступ к MT5
LockLevel.TRADE_EXECUTION # 8 - Исполнение ордеров
LockLevel.SYSTEM_RECONFIG # 9 - Переконфигурация
LockLevel.MODEL_TRAINING  # 10 - Обучение моделей

# Контекстный менеджер
with lock_manager.acquire(LockLevel.MT5_ACCESS, LockLevel.DB_WRITE):
    # Код имеет оба лока
    deals = mt5.history_deals_get(...)
    db.log_deals(deals)

# Декоратор
@requires_locks(LockLevel.MT5_ACCESS, LockLevel.DB_WRITE, timeout=10.0)
def execute_trade(symbol, volume):
    # Автоматически защищено
    pass

# Статистика
stats = lock_manager.get_stats()
print(f"Contention ratio: {stats['by_level']['MT5_ACCESS']['contention_ratio']}")

# Проверка дедлоков
risk = lock_manager.check_deadlock_risk()
if risk:
    logger.critical(risk)
```

### ResourceGovernor

Адаптивное управление ресурсами:

```python
from src.core.resource_governor import (
    ResourceGovernor, ResourceClass, get_governor,
    AdaptiveResourceGovernor, ResourceBudget
)

# Старый API (совместимость)
governor = get_governor()
if governor.can_start("retrain_model", ResourceClass.MEDIUM):
    try:
        train_model()
    finally:
        governor.task_finished("retrain_model")

# Новый API (AdaptiveResourceGovernor)
adaptive_gov = AdaptiveResourceGovernor(
    total_cpu_cores=8,
    total_memory_gb=16.0
)

budget = ResourceBudget(
    cpu_percent_max=70.0,
    memory_mb_max=4096,
    timeout_seconds=300.0
)

if await adaptive_gov.acquire_resources("ml_training", budget):
    try:
        train_model()
    finally:
        adaptive_gov.release_resources("ml_training")

# Мониторинг
report = adaptive_gov.get_usage_report()
print(f"Active components: {report['active_components']}")
print(f"System CPU: {report['system_cpu_pct']}%")
```

### CircuitBreaker

Защита от каскадных сбоев:

```python
from src.core.circuit_breaker import (
    CircuitBreaker, CircuitState,
    CircuitOpenError, create_circuit_breaker
)

# Создание
breaker = create_circuit_breaker(
    name="mt5_api",
    failure_threshold=5,     # 5 ошибок = OPEN
    recovery_timeout=30.0    # 30 сек до HALF_OPEN
)

# Декоратор
@breaker.protect
def call_mt5_api():
    return mt5.symbol_info_tick("EURUSD")

# Ручное использование
try:
    if not breaker.can_execute():
        return cached_data  # Fallback

    result = call_mt5_api()
    breaker.record_success()
except Exception as e:
    breaker.record_failure()
    raise

# Мониторинг
metrics = breaker.get_metrics()
print(f"State: {metrics['state']}")
print(f"Success rate: {metrics['metrics']['success_rate']}%")

# Health report
from src.core.circuit_breaker import circuit_breaker_registry
health = circuit_breaker_registry.get_health_report()
print(f"Overall health: {health['overall_health']}")
```

---

## 🔄 Миграция старого кода

### LockManager
```python
# Старое:
from src.core.lock_manager import LockHierarchy, LockLevel

with lock_manager.acquire(LockLevel.MT5_LOCK, LockLevel.DB_LOCK):
    pass

# Новое (обратная совместимость сохранена):
from src.core.lock_manager import lock_manager, LockLevel, requires_locks

# Код продолжает работать! MT5_LOCK и DB_LOCK — алиасы
# Рекомендуется обновить на новые уровни:
with lock_manager.acquire(LockLevel.MT5_ACCESS, LockLevel.DB_WRITE):
    pass
```

### EventBus
```python
# Старое:
from src.core.event_bus import event_bus, EventType

event_bus.subscribe(EventType.TRADE_OPENED, handler)
event_bus.publish(Event(type=EventType.TRADE_OPENED))

# Новое (оба API работают параллельно):
from src.core.event_bus import get_event_bus, SystemEvent, EventPriority

event_bus = get_event_bus()
await event_bus.subscribe("trade_opened", handler, domain=ThreadDomain.RISK_ENGINE)
await event_bus.publish(SystemEvent(
    type="trade_opened",
    payload={"symbol": "EURUSD"},
    priority=EventPriority.HIGH
))
```

---

## 🧪 Тестирование

### Запуск тестов
```bash
pytest tests/core/ -v
```

### Пример теста
```python
import pytest
import asyncio
from src.core.event_bus import AsyncEventBus, SystemEvent
from src.core.lock_manager import lock_manager, LockLevel

@pytest.mark.asyncio
async def test_event_bus_with_locks():
    """Интеграционный тест: EventBus + LockManager."""
    bus = AsyncEventBus()
    await bus.start()

    results = []

    async def handler(event: SystemEvent):
        with lock_manager.acquire(LockLevel.DB_WRITE):
            results.append(event.payload)

    await bus.subscribe("test", handler, domain=ThreadDomain.PERSISTENCE)
    await bus.publish(SystemEvent(type="test", payload={"data": 123}))

    await asyncio.sleep(0.1)
    assert {"data": 123} in results

    await bus.stop()
```

---

## ✅ Чеклист перед мержем

- [x] Все новые файлы имеют типизацию (type hints)
- [x] Добавлены docstrings для публичных API
- [x] Написаны unit-тесты для новой функциональности
- [x] Пройдены интеграционные тесты с TradingSystem
- [x] Обновлена документация в `docs/`
- [x] Нет регрессий в существующих тестах (`pytest -x`)
- [x] Проверено на Windows (учтён `spawn` для multiprocessing)
- [x] Добавлены метрики для мониторинга

---

## 🎯 Итог

После внедрения этих изменений система получит:

- 🔒 **Безопасность**: Защита от дедлоков и каскадных сбоев
- ⚡ **Производительность**: Параллелизм без блокировок там, где это возможно
- 🔍 **Наблюдаемость**: Статистика и мониторинг конкурентности в реальном времени
- 🧩 **Масштабируемость**: Легко добавлять новые компоненты без переписывания ядра
- 🔄 **Обратная совместимость**: Существующий код работает без изменений

---

> 📝 **Дата создания**: 14 апреля 2026
> 👤 **Автор**: MT5 Projekt Team
> 🚀 **Статус**: ✅ Готово к production
