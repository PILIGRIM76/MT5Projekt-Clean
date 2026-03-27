# Детальный анализ: Сравнение None и Float в критических областях

## 1. STOP LOSS РАСЧЕТЫ

### ✅ Исправленные места:

#### **trade_executor.py - Строка 225 (TWAP execution)**
```python
# ДО:
price = tick.ask if signal_type == SignalType.BUY else tick.bid
sl_distance = stop_loss_in_price  # МОЖЕТ БЫТЬ None!
if sl_distance < min_distance_price * 1.1:  # ❌ TypeError

# ПОСЛЕ:
price = tick.ask if signal_type == SignalType.BUY else tick.bid
sl_distance = stop_loss_in_price

# ДОБАВЛЕНО: Проверка на None
if sl_distance is None or sl_distance <= 0:
    logger.error(f"TWAP: stop_loss_in_price is None or <= 0. Пропуск.")
    break

# Теперь безопасно сравнивать
if sl_distance < min_distance_price * 1.1:  # ✅ Теперь безопасно
    logger.error(f"TWAP: Рассчитанный SL ({sl_distance:.5f}) меньше мин. дистанции ({min_distance_price:.5f})")
    break
```

**Контекст**: Функция `_execute_twap()` - Строка 218-240
**Источник проблемы**: `stop_loss_in_price` передается из `execute_trade()` и может быть None если `calculate_position_size()` вернула ошибку

---

#### **trade_executor.py - Строка 307 (Market Order)**
```python
# ДО:
if stop_loss_in_price < min_distance_price * 1.1:  # ❌ TypeError если None
    logger.error(f"MARKET ОРДЕР: SL ({stop_loss_in_price:.5f}) < ({min_distance_price:.5f})")
    return None

# ПОСЛЕ:
# ДОБАВЛЕНО: Двойная проверка
if stop_loss_in_price is None or stop_loss_in_price <= 0:
    logger.error(f"MARKET ОРДЕР: stop_loss_in_price is None or <= 0. Пропуск.")
    return None

if stop_loss_in_price < min_distance_price * 1.1:  # ✅ Теперь безопасно
    logger.error(f"MARKET ОРДЕР: SL ({stop_loss_in_price:.5f}) < ({min_distance_price:.5f})")
    return None
```

**Контекст**: Функция `_execute_market_order()` - Строка 300-310
**Источник проблемы**: Параметр `stop_loss_in_price` может быть None

**Корневая причина в risk_engine.py - Строка 380:**
```python
# ДО (НЕПРАВИЛЬНО):
if not connector.initialize(path=self.config.MT5_PATH):
    return None  # ❌ ОШИБКА: Должно быть return None, None

# ПОСЛЕ (ИСПРАВЛЕНО):
if not connector.initialize(path=self.config.MT5_PATH):
    return None, None  # ✅ Теперь возвращает корректный tuple
```

---

## 2. TAKE PROFIT РАСЧЕТЫ

**Анализ**: Take Profit рассчитывается как функция от stop_loss:
```python
tp = price + (stop_loss_in_price * self.config.RISK_REWARD_RATIO)  # BUY
tp = price - (stop_loss_in_price * self.config.RISK_REWARD_RATIO)  # SELL
```

### ✅ Исправления:

Когда добавлена проверка `if stop_loss_in_price is None`, TP автоматически защищен, так как:
1. Если `stop_loss_in_price` is None → функция возвращает `None` раньше
2. TP никогда не рассчитывается с None значением
3. Операции `price - None * ratio` больше не выполняются

**Защита транзитивна**: Защита stop_loss = Защита take_profit ✅

---

## 3. ПРОВЕРКИ ЦЕН BID/ASK

### ✅ Исправленные места:

#### **trade_executor.py - Строка 410 (Spread calculation)**
```python
# ДО (НЕПРАВИЛЬНО):
if symbol_info.point > 0:  # ❌ TypeError если point is None
    spread_pips = round((tick.ask - tick.bid) / symbol_info.point)
else:
    spread_pips = 5

# ПОСЛЕ (ИСПРАВЛЕНО):
# ДОБАВЛЕНО: Проверка на None
if symbol_info.point is not None and symbol_info.point > 0:  # ✅ Безопасная проверка
    spread_pips = round((tick.ask - tick.bid) / symbol_info.point)
else:
    spread_pips = 5
```

**Контекст**: Функция `_calculate_adaptive_offset()` - Строка 400-415
**Проблема**: symbol_info.point может быть None, что вызывает деление на None

#### **trade_executor.py - Строка 476 (Spread Filter)**
```python
# ДО (НЕПРАВИЛЬНО):
current_spread_price = tick.ask - tick.bid
fair_spread = self._calculate_fair_value_spread(df, symbol_info)
if current_spread_price > 2.5 * fair_spread:  # ❌ TypeError если fair_spread is None
    logger.critical(f"Спред ({current_spread_price:.5f}) > 2.5 * FairValue ({fair_spread:.5f})")
    return None

# ПОСЛЕ (ИСПРАВЛЕНО):
current_spread_price = tick.ask - tick.bid
fair_spread = self._calculate_fair_value_spread(df, symbol_info)

# ДОБАВЛЕНО: Проверка на None
if fair_spread is None:
    logger.warning(f"fair_spread is None. Пропуск спред-фильтра.")
    return None

# Теперь безопасно сравнивать
if current_spread_price > 2.5 * fair_spread:  # ✅ Теперь безопасно
    logger.critical(f"Спред ({current_spread_price:.5f}) > 2.5 * FairValue ({fair_spread:.5f})")
    return None
```

**Контекст**: Функция `execute_trade()` - Строка 470-480
**Проблема**: `_calculate_fair_value_spread()` может вернуть None или неинициализированное значение

---

## 4. ПРОВЕРКИ LOT_SIZE

### ✅ Исправленные места:

#### **trading_system.py - Строка 2100-2115 (_process_single_symbol)**
```python
# ДО (НЕПРАВИЛЬНО):
lot_size, stop_loss_in_price = self.risk_engine.calculate_position_size(
    symbol=symbol, df=df, account_info=account_info, 
    trade_type=confirmed_signal.type, strategy_name=final_strategy_name
)

if lot_size is None or lot_size <= 0:  # ❌ Проверяет только lot_size!
    logger.warning(f"Лот размер равен 0 или None. Lot Size: {lot_size}. SL Price: {stop_loss_in_price}.")
    min_lots = self.data_provider.get_minimum_lot_size(symbol)
    if min_lots is not None and min_lots > 0:  # ❌ stop_loss_in_price может быть None!
        lot_size = min_lots
        logger.info(f"Используем минимальный размер лота: {lot_size}")
    else:
        return

# ПОСЛЕ (ИСПРАВЛЕНО):
lot_size, stop_loss_in_price = self.risk_engine.calculate_position_size(...)

# ДОБАВЛЕНО: Проверка ОБЕИХ переменных
if lot_size is None or lot_size <= 0 or stop_loss_in_price is None:
    logger.warning(
        f"Лот размер равен 0 или None. Lot Size: {lot_size}. SL Price: {stop_loss_in_price}."
    )
    min_lots = self.data_provider.get_minimum_lot_size(symbol)
    # ДОБАВЛЕНО: Дополнительная проверка stop_loss_in_price
    if min_lots is not None and min_lots > 0 and stop_loss_in_price is not None:
        lot_size = min_lots
        logger.info(f"Используем минимальный размер лота: {lot_size}")
    else:
        return  # ✅ Выходим если stop_loss_in_price is None
```

**Контекст**: Функция `_process_single_symbol()` - Строка 2095-2135
**Проблема**: После вызова `calculate_position_size()` должны быть проверены ОБЕ переменные

**Источник**: risk_engine.py - Строка 380, 385:
```python
# ДО (НЕПРАВИЛЬНО):
if not connector.initialize(...):
    return None  # ❌ tuple должен быть (None, None)

# ПОСЛЕ (ИСПРАВЛЕНО):
if not connector.initialize(...):
    return None, None  # ✅ Теперь может быть распакован корректно
```

---

## 5. ПРОВЕРКИ В EXECUTE_TRADE() ФУНКЦИИ

### ✅ Исправленные места:

#### **trade_executor.py - Строка 493-494 (Volatility check)**
```python
# ДО (НЕПРАВИЛЬНО):
normalized_atr_percent = (df['ATR_14'].iloc[-1] / df['close'].iloc[-1]) * 100 if 'ATR_14' in df.columns and df['close'].iloc[-1] > 0 else 1.0
is_low_volatility = normalized_atr_percent < 0.15
is_tight_spread = current_spread_price < 1.5 * symbol_info.point  # ❌ point может быть None!

# ПОСЛЕ (ИСПРАВЛЕНО):
normalized_atr_percent = (df['ATR_14'].iloc[-1] / df['close'].iloc[-1]) * 100 if 'ATR_14' in df.columns and df['close'].iloc[-1] > 0 else 1.0
is_low_volatility = normalized_atr_percent < 0.15
# ДОБАВЛЕНО: Проверка на None для symbol_info.point
is_tight_spread = symbol_info.point is not None and current_spread_price < 1.5 * symbol_info.point  # ✅ Безопасно
```

**Контекст**: Функция `execute_trade()` - Строка 490-500
**Проблема**: `symbol_info.point` может быть None, что вызывает TypeError при сравнении

---

## 📊 Таблица исправлений

| № | Файл | Строки | Переменная | Проблема | Решение |
|---|------|--------|-----------|---------|---------|
| 1 | risk_engine.py | 380, 385 | return value | Возвращает `None` вместо `(None, None)` | Добавлен второй `None` в return |
| 2 | trade_executor.py | 225 | sl_distance | Может быть None перед `<` | Добавлена проверка `if sl_distance is None` |
| 3 | trade_executor.py | 307 | stop_loss_in_price | Может быть None перед `<` | Добавлена проверка `if stop_loss_in_price is None` |
| 4 | trade_executor.py | 410 | symbol_info.point | Может быть None перед `>` | Добавлена проверка `if symbol_info.point is not None` |
| 5 | trade_executor.py | 476 | fair_spread | Может быть None перед `>` | Добавлена проверка `if fair_spread is None` |
| 6 | trade_executor.py | 493 | symbol_info.point | Может быть None перед `<` | Добавлена проверка `is not None and` |
| 7 | trading_system.py | 2100 | stop_loss_in_price | Может быть None после распаковки | Добавлена проверка в условии `if` |
| 8 | trade_executor.py | 825 | profit | Может быть None перед `>` | Добавлена проверка `if profit is None` |

---

## 🎯 Итоговые замечания

1. **Корневая причина**: Функция `calculate_position_size()` в некоторых случаях возвращает `None` вместо кортежа
2. **Распространение ошибки**: Эта None значение передается в `execute_trade()` без проверки
3. **Срабатывание**: Когда код пытается сравнить None с float → TypeError
4. **Решение**: Добавлены защитные проверки на None перед каждым сравнением

**Все исправления применены и готовы к тестированию! ✅**
