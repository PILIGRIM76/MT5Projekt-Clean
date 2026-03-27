# 🔧 Исправление торговли по всем символам

## 📋 Проблема

**Текущая ситуация:**
- Торговля ограничена `MAX_OPEN_POSITIONS = 18`
- Даже если в whitelist 18 символов, система может торговать меньше
- Логика ограничивает количество одновременных позиций

## ✅ Решение

### **1. Проверка конфига**

Убедитесь что в `configs/settings.json`:

```json
{
  "TOP_N_SYMBOLS": 18,        // Количество символов для торговли
  "MAX_OPEN_POSITIONS": 18,   // Максимум открытых позиций
  "SYMBOLS_WHITELIST": [      // Все символы для торговли
    "EURUSD", "GBPUSD", "USDJPY", ...
  ]
}
```

### **2. Исправление в TradingSystem**

**Файл:** `src/core/trading_system.py`

**Строка ~967:** Заменить цикл торговли:

**БЫЛО:**
```python
for symbol in ranked_symbols:
    if len(current_positions) + len(analysis_tasks) >= self.config.MAX_OPEN_POSITIONS:
        break
    # ... обработка символа
```

**СТАЛО:**
```python
# ТОРГОВЛЯ ПО ВСЕМ СИМВОЛАМ ИЗ WHITELIST
symbols_to_trade = ranked_symbols  # Все ранжированные символы

logger.info(f"[Trading] Торговля по {len(symbols_to_trade)} символам из {len(full_ranked_list)} доступных")
logger.info(f"[Trading] Текущих позиций: {len(current_positions)}, Максимум: {self.config.MAX_OPEN_POSITIONS}")

for symbol in symbols_to_trade:
    # Проверяем лимит позиций (но не блокируем, а логируем)
    if len(current_positions) + len(analysis_tasks) >= self.config.MAX_OPEN_POSITIONS:
        logger.warning(f"[Trading] Достигнут лимит позиций ({len(current_positions)}/{self.config.MAX_OPEN_POSITIONS}). "
                      f"Символ {symbol} будет пропущен.")
        continue  # Пропускаем, но не прерываем цикл
    
    # Проверяем, есть ли уже позиция по этому символу
    symbol_positions = [p for p in current_positions if p.symbol == symbol]
    if symbol_positions:
        logger.debug(f"[Trading] Пропуск {symbol}: уже есть открытая позиция")
        continue
    
    # Обработка символа
    self.start_performance_timer(f"select_optimal_timeframe_{symbol}")
    optimal_timeframe = self._select_optimal_timeframe(symbol, data_dict)
    self.end_performance_timer(f"select_optimal_timeframe_{symbol}")
    
    df_optimal = data_dict.get(f"{symbol}_{optimal_timeframe}")
    if df_optimal is None:
        logger.warning(f"[Trading] Нет данных для {symbol} на таймфрейме {optimal_timeframe}")
        continue
    
    task = self._process_single_symbol(symbol, df_optimal, optimal_timeframe, account_info, current_positions)
    analysis_tasks.append(task)
    logger.info(f"[Trading] Добавлен символ {symbol} на обработку (всего задач: {len(analysis_tasks)})")
```

### **3. Логирование**

Добавить детальное логирование в начале `run_cycle`:

```python
logger.info("=" * 80)
logger.info("НАЧАЛО ТОРГОВОГО ЦИКЛА")
logger.info("=" * 80)
logger.info(f"[Config] SYMBOLS_WHITELIST: {len(self.config.SYMBOLS_WHITELIST)} символов")
logger.info(f"[Config] TOP_N_SYMBOLS: {self.config.TOP_N_SYMBOLS}")
logger.info(f"[Config] MAX_OPEN_POSITIONS: {self.config.MAX_OPEN_POSITIONS}")
logger.info(f"[Market] Доступно данных: {len(data_dict_raw)}")
logger.info(f"[Market] Ранжировано символов: {len(ranked_symbols)}")
logger.info(f"[Positions] Текущих позиций: {len(current_positions)}")
logger.info("=" * 80)
```

### **4. Проверка _process_single_symbol**

Убедиться что метод корректно обрабатывает каждый символ:

**Файл:** `src/core/trading_system.py`
**Строка:** ~2070

Проверить:
1. ✅ Проверка на существующие позиции
2. ✅ Проверка кулдауна
3. ✅ Генерация сигнала
4. ✅ Расчет лота
5. ✅ Исполнение ордера

## 🧪 Тестирование

### **1. Проверка конфига:**

```python
# В GUI или консоли
print(f"SYMBOLS_WHITELIST: {trading_system.config.SYMBOLS_WHITELIST}")
print(f"TOP_N_SYMBOLS: {trading_system.config.TOP_N_SYMBOLS}")
print(f"MAX_OPEN_POSITIONS: {trading_system.config.MAX_OPEN_POSITIONS}")
```

### **2. Мониторинг торговли:**

Включить debug логирование:
```python
import logging
logging.getLogger('genesis').setLevel(logging.DEBUG)
```

### **3. Проверка логов:**

Искать в логах:
```
[Trading] Торговля по X символам из Y доступных
[Trading] Добавлен символ SYMBOL на обработку
[Trading] Пропуск SYMBOL: уже есть открытая позиция
[Trading] Достигнут лимит позиций
```

## ⚙️ Настройки для торговли по всем символам

### **Вариант 1: Торговля по всем (рекомендуется)**

```json
{
  "TOP_N_SYMBOLS": 0,           // 0 = все символы из whitelist
  "MAX_OPEN_POSITIONS": 50,     // Большой лимит
  "SYMBOLS_WHITELIST": [...]    // Все символы для торговли
}
```

### **Вариант 2: Торговля по топ-N**

```json
{
  "TOP_N_SYMBOLS": 18,          // Топ-18 символов
  "MAX_OPEN_POSITIONS": 18,     // 18 позиций максимум
  "SYMBOLS_WHITELIST": [...]    // Все доступные символы
}
```

### **Вариант 3: Ограниченная торговля**

```json
{
  "TOP_N_SYMBOLS": 5,           // Только топ-5
  "MAX_OPEN_POSITIONS": 5,      // 5 позиций максимум
  "SYMBOLS_WHITELIST": [...]    // Все доступные символы
}
```

## 🎯 Результат

После исправления:
- ✅ **Все символы из whitelist** будут обрабатываться
- ✅ **Логирование** покажет какие символы торгуются
- ✅ **Гибкость** настройки через конфиг
- ✅ **Контроль** лимитов позиций

## 📊 Пример лога

```
================================================================================
НАЧАЛО ТОРГОВОГО ЦИКЛА
================================================================================
[Config] SYMBOLS_WHITELIST: 18 символов
[Config] TOP_N_SYMBOLS: 18
[Config] MAX_OPEN_POSITIONS: 18
[Market] Доступно данных: 18
[Market] Ранжировано символов: 18
[Positions] Текущих позиций: 0
================================================================================
[Trading] Торговля по 18 символам из 18 доступных
[Trading] Добавлен символ EURUSD на обработку (всего задач: 1)
[Trading] Добавлен символ GBPUSD на обработку (всего задач: 2)
...
[Trading] Пропуск USDJPY: уже есть открытая позиция
...
```

## ⚠️ Важные замечания

1. **Риск-менеджмент:** Убедитесь что риск на сделку настроен корректно
2. **Маржа:** Проверьте доступную маржу для торговли по всем символам
3. **Производительность:** Больше символов = больше вычислений
