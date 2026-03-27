# Исправление ошибки: "'<' not supported between instances of 'NoneType' and 'float'"

## Дата: 26 марта 2026
## Статус: ✅ ИСПРАВЛЕНО

---

## 📋 Описание проблемы

При выполнении торговых операций возникала ошибка:
```
TypeError: '<' not supported between instances of 'NoneType' and 'float'
```

Причина: Переменные `stop_loss_in_price`, `fair_spread`, `symbol_info.point` и другие могут быть `None`, но использовались в операциях сравнения без проверки на `None`.

---

## 🔍 Найденные места ошибок

### 1. **src/risk/risk_engine.py (Строки 380, 385)**
**Проблема**: Неправильный return type (возвращает `None` вместо `None, None`)

```python
# ДО (НЕПРАВИЛЬНО):
if not connector.initialize(path=self.config.MT5_PATH):
    return None  # ❌ Должно быть кортежем!

# ПОСЛЕ (ИСПРАВЛЕНО):
if not connector.initialize(path=self.config.MT5_PATH):
    return None, None  # ✅ Корректный return type
```

**Функция**: `calculate_position_size()` 
**Возвращаемый тип**: `Tuple[Optional[float], Optional[float]]`

---

### 2. **src/core/trading_system.py (Строко 2100-2115)**
**Проблема**: Проверка только `lot_size`, но не `stop_loss_in_price`

```python
# ДО (НЕПРАВИЛЬНО):
if lot_size is None or lot_size <= 0:
    # ... обработка ошибки
    # ❌ stop_loss_in_price может быть None!

# ПОСЛЕ (ИСПРАВЛЕНО):
if lot_size is None or lot_size <= 0 or stop_loss_in_price is None:
    # ... обработка ошибки
    # Дополнительно проверяем stop_loss_in_price
    if min_lots is not None and min_lots > 0 and stop_loss_in_price is not None:
        lot_size = min_lots
        # ✅ Используем только если stop_loss_in_price валиден
```

---

### 3. **src/core/services/trade_executor.py - Строка 307 (Market Order)**
**Проблема**: Сравнение `stop_loss_in_price < ...` без проверки на None

```python
# ДО (НЕПРАВИЛЬНО):
if stop_loss_in_price < min_distance_price * 1.1:
    # ❌ TypeError если stop_loss_in_price is None

# ПОСЛЕ (ИСПРАВЛЕНО):
if stop_loss_in_price is None or stop_loss_in_price <= 0:
    logger.error("stop_loss_in_price is None or <= 0. Пропуск ордера.")
    return None
if stop_loss_in_price < min_distance_price * 1.1:
    # ✅ Безопасная проверка
```

---

### 4. **src/core/services/trade_executor.py - Строка 225 (TWAP execution)**
**Проблема**: Сравнение `sl_distance < ...` без проверки на None

```python
# ДО (НЕПРАВИЛЬНО):
sl_distance = stop_loss_in_price
if sl_distance < min_distance_price * 1.1:
    # ❌ TypeError если stop_loss_in_price is None

# ПОСЛЕ (ИСПРАВЛЕНО):
sl_distance = stop_loss_in_price
if sl_distance is None or sl_distance <= 0:
    logger.error("stop_loss_in_price is None or <= 0. Пропуск TWAP.")
    break
if sl_distance < min_distance_price * 1.1:
    # ✅ Безопасная проверка
```

---

### 5. **src/core/services/trade_executor.py - Строка 410 (Spread calculation)**
**Проблема**: `symbol_info.point` может быть None

```python
# ДО (НЕПРАВИЛЬНО):
if symbol_info.point > 0:
    spread_pips = round((tick.ask - tick.bid) / symbol_info.point)
    # ❌ TypeError если symbol_info.point is None

# ПОСЛЕ (ИСПРАВЛЕНО):
if symbol_info.point is not None and symbol_info.point > 0:
    spread_pips = round((tick.ask - tick.bid) / symbol_info.point)
    # ✅ Безопасная проверка
else:
    spread_pips = 5
```

---

### 6. **src/core/services/trade_executor.py - Строка 476 (Spread Filter)**
**Проблема**: `fair_spread` может быть None

```python
# ДО (НЕПРАВИЛЬНО):
fair_spread = self._calculate_fair_value_spread(df, symbol_info)
if current_spread_price > 2.5 * fair_spread:
    # ❌ TypeError если fair_spread is None

# ПОСЛЕ (ИСПРАВЛЕНО):
fair_spread = self._calculate_fair_value_spread(df, symbol_info)
if fair_spread is None:
    logger.warning("fair_spread is None. Пропуск спред-фильтра.")
    return None
if current_spread_price > 2.5 * fair_spread:
    # ✅ Безопасная проверка
```

---

### 7. **src/core/services/trade_executor.py - Строка 493-494 (Volatility Calculation)**
**Проблема**: `symbol_info.point` может быть None в сравнении

```python
# ДО (НЕПРАВИЛЬНО):
is_tight_spread = current_spread_price < 1.5 * symbol_info.point
# ❌ TypeError если symbol_info.point is None

# ПОСЛЕ (ИСПРАВЛЕНО):
is_tight_spread = symbol_info.point is not None and current_spread_price < 1.5 * symbol_info.point
# ✅ Безопасная проверка
```

---

### 8. **src/core/services/trade_executor.py - Строка 825-827 (Trade Outcome)**
**Проблема**: `profit` может быть None перед сравнением

```python
# ДО (НЕПРАВИЛЬНО):
def _track_trade_outcome(self, symbol: str, profit: float):
    if profit > 0:
        outcome = 'profit'
    elif profit < 0:
        outcome = 'loss'
    # ❌ TypeError если profit is None

# ПОСЛЕ (ИСПРАВЛЕНО):
def _track_trade_outcome(self, symbol: str, profit: float):
    if profit is None:
        logger.warning("profit is None. Пропуск записи исхода.")
        return
    if profit > 0:
        outcome = 'profit'
    elif profit < 0:
        outcome = 'loss'
    # ✅ Безопасная проверка
```

---

## ✅ Суммарные исправления

| Файл | Строки | Исправление | Статус |
|------|--------|------------|--------|
| risk_engine.py | 380, 385 | `return None` → `return None, None` | ✅ |
| trading_system.py | 2100-2115 | Добавлена проверка на `stop_loss_in_price is None` | ✅ |
| trade_executor.py | 307 | Добавлена проверка `if stop_loss_in_price is None` | ✅ |
| trade_executor.py | 225 | Добавлена проверка `if sl_distance is None` | ✅ |
| trade_executor.py | 410 | Добавлена проверка `if symbol_info.point is not None` | ✅ |
| trade_executor.py | 476 | Добавлена проверка `if fair_spread is None` | ✅ |
| trade_executor.py | 493-494 | Добавлена проверка для `symbol_info.point` | ✅ |
| trade_executor.py | 825-827 | Добавлена проверка `if profit is None` | ✅ |

---

## 🧪 Рекомендации по тестированию

1. ✅ **Запустить торговый цикл** - проверить, что нет ошибок TypeError
2. ✅ **Открыть сделку** - убедиться, что stop_loss и take_profit рассчитываются правильно
3. ✅ **Проверить TWAP execution** - для крупных лотов
4. ✅ **Проверить Limit-to-Market** - адаптивный вход
5. ✅ **Закрыть сделку** - убедиться, что profit_tracking работает

---

## 📝 Примечания

- Все исправления добавляют **защитные проверки на None** перед использованием переменных в операциях сравнения
- Логирование улучшено для лучшей диагностики проблем
- Код становится более устойчивым к граничным случаям

---

**Автор**: GitHub Copilot  
**Дата применения**: 26 марта 2026
