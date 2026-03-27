# Руководство по Type Hints для Genesis Trading System

## 📋 Введение

Type hints (подсказки типов) улучшают:
- **Читаемость** - понятно какие типы ожидаются
- **Надежность** - mypy находит ошибки до запуска
- **IDE поддержку** - лучший autocomplete и refactoring
- **Документацию** - типы как форма документации

## 🎯 Базовые импорты

Добавьте в начало файла:

```python
from typing import (
    Optional,      # Может быть None
    List,          # Список
    Dict,          # Словарь
    Tuple,         # Кортеж
    Any,           # Любой тип
    Callable,      # Функция
    Union,         # Или-или
    Type,          # Тип класса
)
```

## 📝 Примеры добавления type hints

### **1. Простые методы**

**До:**
```python
def calculate_position_size(self, symbol, df, account_info, trade_type, strategy_name):
    return lot_size, sl_price
```

**После:**
```python
def calculate_position_size(
    self,
    symbol: str,
    df: pd.DataFrame,
    account_info: Any,
    trade_type: SignalType,
    strategy_name: str
) -> Tuple[Optional[float], Optional[float]]:
    return lot_size, sl_price
```

### **2. Методы с None return**

**До:**
```python
def get_data(self, key):
    if key in cache:
        return cache[key]
    return None
```

**После:**
```python
def get_data(self, key: str) -> Optional[Any]:
    if key in cache:
        return cache[key]
    return None
```

### **3. Словари**

**До:**
```python
def get_config(self) -> dict:
    return self.config
```

**После:**
```python
def get_config(self) -> Dict[str, Any]:
    return self.config
```

### **4. Списки**

**До:**
```python
def get_symbols(self) -> list:
    return self.symbols
```

**После:**
```python
def get_symbols(self) -> List[str]:
    return self.symbols
```

### **5. Функции с несколькими типами**

**До:**
```python
def process_value(value):
    if isinstance(value, str):
        return value.upper()
    return str(value)
```

**После:**
```python
from typing import Union

def process_value(value: Union[str, int, float]) -> str:
    if isinstance(value, str):
        return value.upper()
    return str(value)
```

Или с Python 3.10+:
```python
def process_value(value: str | int | float) -> str:
    ...
```

## 🔧 Постепенное добавление

### **Шаг 1: Начните с простых методов**

Методы которые:
- Не используют сложные типы
- Имеют четкую сигнатуру
- Не зависят от других методов

**Пример:**
```python
# Легко добавить
def set_observer_mode(self, enabled: bool) -> None:
    self.observer_mode = enabled
```

### **Шаг 2: Аннотируйте атрибуты класса**

**До:**
```python
class TradingSystem:
    def __init__(self):
        self.config = None
        self.db_manager = None
        self.symbols = []
```

**После:**
```python
class TradingSystem:
    config: Optional[Settings]
    db_manager: Optional[DatabaseManager]
    symbols: List[str]
    
    def __init__(self):
        self.config = None
        self.db_manager = None
        self.symbols = []
```

### **Шаг 3: Добавьте типы для параметров**

**До:**
```python
def process_symbol(self, symbol, df, timeframe):
    ...
```

**После:**
```python
def process_symbol(
    self, 
    symbol: str, 
    df: pd.DataFrame, 
    timeframe: int
) -> Optional[TradeSignal]:
    ...
```

## 📊 Приоритетные файлы для type hints

### **Высокий приоритет:**
1. `src/core/services/*.py` - Новые сервисы (уже имеют типы)
2. `src/core/system_service_manager.py` - Адаптер
3. `src/core/config_validator.py` - Валидация

### **Средний приоритет:**
4. `src/risk/risk_engine.py` - Критический код
5. `src/core/services/trade_executor.py` - Исполнение ордеров
6. `src/db/database_manager.py` - Работа с БД

### **Низкий приоритет:**
7. `src/core/trading_system.py` - Слишком большой, постепенно
8. `src/gui/*.py` - GUI код сложный для типизации
9. `src/ml/*.py` - ML модели со сложными типами

## 🧪 Проверка типов

### **Запуск mypy:**

```bash
# Проверить весь проект
python -m mypy src/

# Проверить конкретный файл
python -m mypy src/core/services/base_service.py

# Проверить с игнорированием ошибок
python -m mypy src/ --ignore-missing-imports
```

### **Игнорирование ошибок:**

Иногда нужно игнорировать ошибки:

```python
result = some_function()  # type: ignore
```

Или для всего файла:
```python
# mypy: ignore-errors
```

## 📚 Common Patterns

### **Type Guards**

```python
def process(value: Any) -> str:
    if isinstance(value, str):
        return value.upper()  # mypy знает что value это str
    return str(value)
```

### **TypedDict**

```python
from typing import TypedDict

class TradeData(TypedDict):
    symbol: str
    price: float
    volume: int

def process_trade(data: TradeData) -> None:
    print(data['symbol'])  # type-safe
```

### **Protocol**

```python
from typing import Protocol

class SupportsClose(Protocol):
    def close(self) -> None: ...

def cleanup(resource: SupportsClose) -> None:
    resource.close()
```

## ⚠️ Частые ошибки

### **1. Implicit Optional**

**Неправильно:**
```python
def get_name(self, default=None):  # mypy будет ругаться
    ...
```

**Правильно:**
```python
def get_name(self, default: Optional[str] = None) -> Optional[str]:
    ...
```

### **2. Mutable default arguments**

**Неправильно:**
```python
def add_item(item: str, items: list = []) -> list:
    items.append(item)
    return items
```

**Правильно:**
```python
def add_item(item: str, items: Optional[List[str]] = None) -> List[str]:
    if items is None:
        items = []
    items.append(item)
    return items
```

### **3. Слишком общие типы**

**Неправильно:**
```python
def process(data: Any) -> Any:
    return data
```

**Правильно:**
```python
def process(data: Dict[str, float]) -> List[float]:
    return list(data.values())
```

## 🎯 Цели

### **Краткосрочные (1 неделя):**
- ✅ Типизировать `src/core/services/*.py`
- ✅ Типизировать `src/core/system_service_manager.py`
- ✅ Типизировать `src/core/config_validator.py`

### **Среднесрочные (1 месяц):**
- ⏳ Типизировать `src/risk/risk_engine.py`
- ⏳ Типизировать `src/core/services/trade_executor.py`
- ⏳ Типизировать `src/db/database_manager.py`

### **Долгосрочные (3 месяца):**
- 🔲 Типизировать 50% `src/core/trading_system.py`
- 🔲 Типизировать `src/ml/*.py`
- 🔲 Достичь 80% покрытия типами

## 📈 Прогресс

| Файл | Прогресс | Строк с типами / Всего |
|------|----------|------------------------|
| `src/core/services/base_service.py` | ✅ 100% | 360/360 |
| `src/core/services/trading_service.py` | ✅ 100% | 180/180 |
| `src/core/services/monitoring_service.py` | ✅ 100% | 220/220 |
| `src/core/services/orchestrator_service.py` | ✅ 100% | 200/200 |
| `src/core/services/risk_service.py` | ✅ 100% | 200/200 |
| `src/core/system_service_manager.py` | ✅ 100% | 200/200 |
| `src/core/config_validator.py` | ✅ 100% | 280/280 |
| `src/core/trading_system.py` | 🔲 5% | 150/3156 |
| **ВСЕГО** | **~25%** | **~1800/7000** |

## 🚀 Быстрый старт

1. **Установите mypy:**
   ```bash
   pip install mypy
   ```

2. **Запустите проверку:**
   ```bash
   python -m mypy src/core/services/
   ```

3. **Исправьте ошибки:**
   - Добавьте недостающие импорты
   - Аннотируйте параметры
   - Аннотируйте return types

4. **Повторяйте** для других модулей

## 📚 Ресурсы

- [Mypy Documentation](https://mypy.readthedocs.io/)
- [PEP 484 - Type Hints](https://www.python.org/dev/peps/pep-0484/)
- [Python Type Hints Cheat Sheet](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html)
