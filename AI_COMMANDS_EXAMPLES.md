# 🤖 Примеры команд для AI-ассистента

## Как использовать этот файл

Копируй команды из этого файла и вставляй их AI-ассистенту (Kiro, Claude, GPT-4, etc.)

---

## 🎯 БАЗОВЫЕ КОМАНДЫ

### Начало работы

```
Прочитай файл SYSTEM_IMPROVEMENT_PROMPT.md и подтверди, что понял задачу.
Затем прочитай QUICK_START_IMPROVEMENTS.md и скажи, с какого шага начнём.
```

### Проверка текущего состояния

```
Проанализируй текущее состояние системы:
1. Прочитай configs/settings.json и покажи текущие значения RISK_PERCENTAGE, MAX_OPEN_POSITIONS, TRAINING_INTERVAL_SECONDS
2. Найди в src/core/trading_system.py метод _run_champion_contest и проверь, есть ли валидация моделей
3. Проверь, существует ли файл src/core/safety_monitor.py
```

---

## 📝 КОМАНДЫ ДЛЯ КАЖДОГО ШАГА

### ШАГ 1: Обновление рисков

```
Выполни следующие изменения в configs/settings.json:

1. Найди параметр "RISK_PERCENTAGE" и измени значение с 2.0 на 0.5
2. Найди параметр "MAX_OPEN_POSITIONS" и измени значение с 18 на 5
3. Найди параметр "STOP_LOSS_ATR_MULTIPLIER" и измени значение с 2.5 на 3.5
4. Найди параметр "MAX_DAILY_DRAWDOWN_PERCENT" и измени значение с 10.0 на 5.0
5. Найди параметр "TRAINING_INTERVAL_SECONDS" и измени значение с 300 на 86400

Перед применением покажи мне diff изменений.
После подтверждения примени изменения.
```

### ШАГ 2: Добавление валидации моделей

```
Добавь новый метод в класс TradingSystem в файле src/core/trading_system.py:

Метод должен называться _validate_model_metrics и принимать параметр backtest_results (Dict).

Метод должен проверять:
1. profit_factor >= 1.5
2. win_rate >= 0.40
3. sharpe_ratio >= 1.0
4. max_drawdown <= 10.0
5. total_trades >= 50

Если хотя бы одна проверка не пройдена, метод должен:
- Логировать через logger.critical причину отклонения
- Вернуть False

Если все проверки пройдены:
- Логировать через logger.critical успешное принятие с метриками
- Вернуть True

Покажи мне код метода перед добавлением.
```

### ШАГ 2.1: Интеграция валидации

```
Найди метод _run_champion_contest в src/core/trading_system.py.

В цикле обработки кандидатов (for model_id in candidate_ids) после расчёта backtest_results
добавь вызов self._validate_model_metrics(backtest_results).

Если метод вернул False, пропусти этого кандидата (continue).

Покажи мне изменённый фрагмент кода перед применением.
```

### ШАГ 3: Создание Safety Monitor

```
Создай новый файл src/core/safety_monitor.py с классом SafetyMonitor.

Требования к классу:

1. Конструктор принимает config и trading_system
2. Атрибуты:
   - max_daily_loss_percent = 3.0
   - max_consecutive_losses = 5
   - max_drawdown_from_peak = 5.0
   - session_start_balance = 0.0
   - peak_equity = 0.0
   - consecutive_losses = 0
   - emergency_stop_triggered = False

3. Метод initialize():
   - Получает account_info из MT5
   - Сохраняет начальный баланс в session_start_balance
   - Сохраняет начальный equity в peak_equity
   - Логирует инициализацию

4. Метод check_safety_conditions() -> bool:
   - Проверяет дневную просадку (лимит 3%)
   - Проверяет просадку от пика (лимит 5%)
   - Проверяет серию убытков (лимит 5)
   - При превышении вызывает _trigger_emergency_stop()
   - Возвращает False если emergency_stop_triggered

5. Метод record_trade_result(profit: float):
   - Если profit < 0: увеличивает consecutive_losses
   - Если profit >= 0: сбрасывает consecutive_losses в 0

6. Метод _trigger_emergency_stop(reason: str):
   - Устанавливает emergency_stop_triggered = True
   - Логирует критическое сообщение
   - Вызывает emergency_close_all_positions()
   - Устанавливает stop_event
   - Отправляет алерт в GUI

Покажи мне полный код класса перед созданием файла.
```

### ШАГ 3.1: Интеграция Safety Monitor

```
Интегрируй SafetyMonitor в TradingSystem:

1. В __init__ добавь: self.safety_monitor = None

2. В initialize_heavy_components добавь:
   from src.core.safety_monitor import SafetyMonitor
   self.safety_monitor = SafetyMonitor(self.config, self)

3. В start_all_background_services добавь:
   if self.safety_monitor:
       self.safety_monitor.initialize()

4. В начале метода run_cycle добавь:
   if self.safety_monitor and not self.safety_monitor.check_safety_conditions():
       logger.critical("Trading stopped by safety monitor")
       return

Покажи мне все изменения перед применением.
```

### ШАГ 4: Улучшение сигналов

```
Выполни следующие изменения в configs/settings.json:

1. Измени "ENTRY_THRESHOLD" с 0.003 на 0.01
2. Измени "CONSENSUS_THRESHOLD" с 0.05 на 0.15
3. Измени "STRATEGY_MIN_WIN_RATE_THRESHOLD" с 0.2 на 0.45
4. В объекте "CONSENSUS_WEIGHTS":
   - Измени "ai_forecast" с 0.4 на 0.5
   - Измени "sentiment_kg" с 0.2 на 0.1

Покажи diff перед применением.
```

### ШАГ 4.1: Исправление дубликатов признаков

```
Найди метод generate_features в файле src/ml/feature_engineer.py.

В конце метода, перед return df, добавь:

# Удаление дубликатов колонок
df = df.loc[:, ~df.columns.duplicated()]

# Проверка KG признаков на надёжность
kg_features = ['KG_CB_SENTIMENT', 'KG_INFLATION_SURPRISE']
for feat in kg_features:
    if feat in df.columns:
        zero_ratio = (df[feat] == 0).sum() / len(df)
        if zero_ratio > 0.8:
            logger.warning(f"KG feature {feat} is {zero_ratio:.1%} zeros - removing")
            df = df.drop(columns=[feat])

Покажи изменённый фрагмент кода перед применением.
```

### ШАГ 5: Увеличение данных для обучения

```
Выполни следующие изменения в configs/settings.json:

1. Измени "TRAINING_DATA_POINTS" с 2000 на 10000

2. В объекте "rd_cycle_config":
   - Измени "sharpe_ratio_threshold" с 1.2 на 1.0
   - Измени "performance_check_trades_min" с 20 на 50
   - Измени "profit_factor_threshold" с 1.1 на 1.5
   - Добавь новый параметр "min_win_rate_threshold": 0.40

3. В "model_candidates" найди объект с "type": "LSTM_PyTorch" и добавь параметр "epochs": 50

Покажи diff перед применением.
```

---

## 🔍 КОМАНДЫ ДЛЯ ПРОВЕРКИ

### Проверка синтаксиса

```
Выполни проверку синтаксиса Python для следующих файлов:
- src/core/trading_system.py
- src/core/safety_monitor.py
- src/ml/feature_engineer.py
- src/core/services/signal_service.py

Используй команду: python -m py_compile <файл>

Сообщи о результатах.
```

### Проверка изменений в конфигурации

```
Прочитай файл configs/settings.json и покажи текущие значения:
- RISK_PERCENTAGE
- MAX_OPEN_POSITIONS
- STOP_LOSS_ATR_MULTIPLIER
- MAX_DAILY_DRAWDOWN_PERCENT
- TRAINING_INTERVAL_SECONDS
- TRAINING_DATA_POINTS
- ENTRY_THRESHOLD
- CONSENSUS_THRESHOLD

Сравни с целевыми значениями из QUICK_START_IMPROVEMENTS.md
```

### Проверка наличия новых методов

```
Проверь наличие следующих методов в src/core/trading_system.py:
1. _validate_model_metrics
2. Вызов _validate_model_metrics в методе _run_champion_contest

Покажи фрагменты кода, где они используются.
```

### Проверка Safety Monitor

```
Проверь:
1. Существует ли файл src/core/safety_monitor.py
2. Импортируется ли SafetyMonitor в src/core/trading_system.py
3. Инициализируется ли safety_monitor в методе initialize_heavy_components
4. Вызывается ли check_safety_conditions в методе run_cycle

Покажи фрагменты кода для каждого пункта.
```

---

## 🐛 КОМАНДЫ ДЛЯ ОТЛАДКИ

### Если система не запускается

```
Проанализируй последние 100 строк логов из файла logs/trading_system.log.
Найди ошибки (ERROR, CRITICAL) и покажи их с контекстом (5 строк до и после).
Предложи решение для каждой ошибки.
```

### Если модели не обучаются

```
Найди в логах (logs/trading_system.log) все сообщения, содержащие:
- "R&D ЦИКЛ"
- "MODEL REJECTED"
- "MODEL ACCEPTED"
- "TRAINING_DATA_POINTS"

Покажи последние 10 таких сообщений и объясни, что происходит.
```

### Если система не торгует

```
Найди в логах все сообщения, содержащие:
- "Signal rejected"
- "БЛОКИРОВКА"
- "Пропуск"
- "check_safety_conditions"

Покажи последние 20 таких сообщений и объясни причины блокировки сделок.
```

---

## 🔄 КОМАНДЫ ДЛЯ ОТКАТА ИЗМЕНЕНИЙ

### Откат всех изменений

```
Используя git, откати следующие файлы к предыдущей версии:
- configs/settings.json
- src/core/trading_system.py
- src/ml/feature_engineer.py

Команда: git checkout <файл>

Затем удали файл src/core/safety_monitor.py если он был создан.

Подтверди выполнение.
```

### Откат только конфигурации

```
Откати файл configs/settings.json к предыдущей версии:
git checkout configs/settings.json

Подтверди выполнение и покажи текущие значения RISK_PERCENTAGE и MAX_OPEN_POSITIONS.
```

---

## 📊 КОМАНДЫ ДЛЯ МОНИТОРИНГА

### Статистика моделей

```
Найди в логах за последние 7 дней все сообщения "MODEL REJECTED" и "MODEL ACCEPTED".

Посчитай:
1. Сколько моделей было отклонено
2. Сколько моделей было принято
3. Средний Profit Factor принятых моделей
4. Средний Win Rate принятых моделей

Представь результаты в виде таблицы.
```

### Статистика сделок

```
Найди в логах за последние 7 дней все сообщения "MARKET ОРДЕР ИСПОЛНЕН" и "СДЕЛКА ЗАБЛОКИРОВАНА".

Посчитай:
1. Сколько сделок было исполнено
2. Сколько сделок было заблокировано
3. Основные причины блокировки (топ-3)

Представь результаты в виде таблицы.
```

### Проверка Safety Monitor

```
Найди в логах все сообщения, содержащие "[SAFETY]".

Покажи:
1. Когда был инициализирован Safety Monitor
2. Срабатывал ли emergency stop (если да, покажи причину)
3. Текущее количество consecutive_losses (если есть в логах)

Если Safety Monitor не найден в логах, сообщи об этом.
```

---

## 🎓 ОБУЧАЮЩИЕ КОМАНДЫ

### Объяснение изменений

```
Объясни простыми словами, почему мы:
1. Снизили RISK_PERCENTAGE с 2% до 0.5%
2. Увеличили TRAINING_DATA_POINTS с 2000 до 10000
3. Добавили валидацию моделей с минимальным Profit Factor 1.5
4. Создали Safety Monitor

Для каждого пункта объясни риски старого подхода и преимущества нового.
```

### Анализ метрик

```
Объясни, что означают следующие метрики модели:
- Profit Factor: 0.34
- Win Rate: 14%
- Sharpe Ratio: -0.47
- Max Drawdown: 4.2%

Почему модель с такими метриками убыточна?
Какие метрики должны быть у прибыльной модели?
```

---

## 💡 ПРОДВИНУТЫЕ КОМАНДЫ

### Создание отчёта

```
Создай файл SYSTEM_STATUS_REPORT.md с анализом текущего состояния системы:

1. Конфигурация (текущие значения всех критических параметров)
2. Статус Safety Monitor (инициализирован ли, срабатывал ли)
3. Статистика моделей за последние 7 дней (принято/отклонено)
4. Статистика сделок за последние 7 дней (исполнено/заблокировано)
5. Топ-3 причины блокировки сделок
6. Рекомендации по дальнейшим действиям

Используй данные из логов и конфигурационных файлов.
```

### Сравнение до/после

```
Создай сравнительную таблицу параметров системы ДО и ПОСЛЕ внедрения улучшений:

Параметры для сравнения:
- RISK_PERCENTAGE
- MAX_OPEN_POSITIONS
- STOP_LOSS_ATR_MULTIPLIER
- TRAINING_INTERVAL_SECONDS
- TRAINING_DATA_POINTS
- ENTRY_THRESHOLD
- CONSENSUS_THRESHOLD
- Наличие валидации моделей
- Наличие Safety Monitor

Для каждого параметра укажи:
- Старое значение
- Новое значение
- Изменение (в %, если применимо)
- Влияние на риск (снижение/повышение)
```

---

## 🚀 ФИНАЛЬНАЯ КОМАНДА

### Полная проверка готовности

```
Выполни полную проверку готовности системы к тестированию:

1. Проверь все критические параметры в configs/settings.json
2. Проверь наличие всех новых методов и классов
3. Проверь синтаксис всех изменённых файлов
4. Проанализируй последние логи на наличие ошибок
5. Создай чеклист готовности с галочками

Формат ответа:
✅ - выполнено корректно
⚠️ - выполнено с замечаниями
❌ - не выполнено или ошибка

В конце дай рекомендацию: готова ли система к запуску на демо-счёте.
```

---

## 📞 КОМАНДА ДЛЯ ПОМОЩИ

```
Я застрял на этапе: [укажи этап]

Проблема: [опиши проблему]

Логи (последние 50 строк):
[вставь логи]

Что мне делать дальше?
```

---

**Совет:** Копируй команды по одной, дожидайся выполнения, проверяй результат, затем переходи к следующей.

Удачи! 🚀
