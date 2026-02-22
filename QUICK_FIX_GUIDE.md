# ⚡ БЫСТРОЕ УСТРАНЕНИЕ ПРОБЛЕМ

## 🚨 КРИТИЧЕСКИЕ ПРОБЛЕМЫ И РЕШЕНИЯ

---

## ❌ ПРОБЛЕМА 1: СИСТЕМА КРАШИТСЯ

### Быстрая диагностика:
```powershell
# Запусти и сохрани вывод
python main_pyside.py 2>&1 | Tee-Object crash_log.txt

# Через 30 секунд проверь
Get-Content crash_log.txt | Select-String -Pattern "Error|Exception|Traceback"
```

### Быстрые решения:

#### Если ошибка: `ImportError: SafetyMonitor`
```powershell
# Проверь файл
Test-Path src\core\safety_monitor.py

# Если нет - скопируй из бэкапа или пересоздай
# Если есть - проверь синтаксис
python -m py_compile src\core\safety_monitor.py
```

#### Если ошибка: `KeyError: 'min_win_rate_threshold'`
```json
// Открой configs/settings.json
// Найди "rd_cycle_config"
// Добавь внутри:
"min_win_rate_threshold": 0.40,
```

#### Если ошибка: `MT5 initialization failed`
```powershell
# Запусти MT5 вручную
Start-Process "C:\Program Files\Alpari MT5\terminal64.exe"

# Подожди 10 секунд
Start-Sleep -Seconds 10

# Запусти систему снова
python main_pyside.py
```

#### Если ошибка: `database is locked`
```powershell
# Останови все Python процессы
Get-Process python | Stop-Process -Force

# Подожди 5 секунд
Start-Sleep -Seconds 5

# Запусти снова
python main_pyside.py
```

---

## ❌ ПРОБЛЕМА 2: SAFETY MONITOR НЕ ИНИЦИАЛИЗИРУЕТСЯ

### Быстрая диагностика:
```powershell
# Проверь логи
Get-Content logs\trading_system.log | Select-String -Pattern "\[SAFETY\]"
```

### Если ничего не найдено:

#### Шаг 1: Проверь импорт
```powershell
Select-String -Path src\core\trading_system.py -Pattern "from src.core.safety_monitor import SafetyMonitor"
```

**Если не найдено** - добавь в `src/core/trading_system.py` в метод `initialize_heavy_components()`:
```python
# CRITICAL: Инициализация Safety Monitor
from src.core.safety_monitor import SafetyMonitor
self.safety_monitor = SafetyMonitor(self.config, self)
logger.critical("INIT STEP 8/8: Safety Monitor initialized.")
```

#### Шаг 2: Проверь вызов initialize()
```powershell
Select-String -Path src\core\trading_system.py -Pattern "self.safety_monitor.initialize"
```

**Если не найдено** - добавь в `start_all_background_services()`:
```python
# CRITICAL: Инициализация Safety Monitor
if self.safety_monitor:
    self.safety_monitor.initialize()
    logger.critical("[SAFETY] Safety Monitor активирован")
```

#### Шаг 3: Проверь вызов в run_cycle
```powershell
Select-String -Path src\core\trading_system.py -Pattern "safety_monitor.check_safety_conditions"
```

**Если не найдено** - добавь в начало `run_cycle()`:
```python
async def run_cycle(self):
    # CRITICAL: Check safety before each cycle
    if self.safety_monitor and not self.safety_monitor.check_safety_conditions():
        logger.critical("⛔ Trading stopped by Safety Monitor")
        return
    # ... остальной код
```

#### Шаг 4: Перезапусти
```powershell
python main_pyside.py
Start-Sleep -Seconds 30
Get-Content logs\trading_system.log | Select-String -Pattern "\[SAFETY\]"
```

**Ожидается:** `[SAFETY] ✅ Monitoring initialized`

---

## ❌ ПРОБЛЕМА 3: ОТКРЫВАЕТСЯ >5 ПОЗИЦИЙ

### Быстрая диагностика:
```powershell
# Проверь конфиг
Select-String -Path configs\settings.json -Pattern '"MAX_OPEN_POSITIONS"'
```

### Решение:

#### Если показывает 18:
```json
// Открой configs/settings.json
// Найди "MAX_OPEN_POSITIONS": 18
// Измени на "MAX_OPEN_POSITIONS": 5
// Сохрани
```

#### Перезапусти систему:
```powershell
# Останови
Get-Process python | Where-Object {$_.MainWindowTitle -like "*Genesis*"} | Stop-Process

# Подожди
Start-Sleep -Seconds 5

# Запусти
python main_pyside.py
```

#### Если позиции уже открыты:
- Старые позиции (открытые до изменения) останутся
- Новые позиции будут ограничены 5
- Дождись закрытия старых позиций естественным путём

#### Проверь код:
```powershell
Select-String -Path src\core\trading_system.py -Pattern "MAX_OPEN_POSITIONS" -Context 2
```

**Должно быть:**
```python
if len(current_positions) >= self.config.MAX_OPEN_POSITIONS:
    return
```

---

## ❌ ПРОБЛЕМА 4: МОДЕЛИ ПРИНИМАЮТСЯ С PF<1.5

### Быстрая диагностика:
```powershell
# Проверь логи R&D
Get-Content logs\trading_system.log | Select-String -Pattern "MODEL.*ACCEPTED.*PF=" | Select-Object -Last 5
```

### Решение:

#### Шаг 1: Проверь метод валидации
```powershell
Select-String -Path src\core\trading_system.py -Pattern "def _validate_model_metrics"
```

**Если не найдено** - добавь в `src/core/trading_system.py`:
```python
def _validate_model_metrics(self, backtest_results: Dict) -> bool:
    """CRITICAL: Reject models that don't meet minimum profitability criteria."""
    profit_factor = backtest_results.get('profit_factor', 0)
    win_rate = backtest_results.get('win_rate', 0)
    sharpe_ratio = backtest_results.get('sharpe_ratio', 0)
    max_drawdown = backtest_results.get('max_drawdown', 100)
    total_trades = backtest_results.get('total_trades', 0)
    
    if profit_factor < 1.5:
        logger.critical(f"❌ MODEL REJECTED: Profit Factor {profit_factor:.2f} < 1.5")
        return False
    if win_rate < 0.40:
        logger.critical(f"❌ MODEL REJECTED: Win Rate {win_rate:.2%} < 40%")
        return False
    if sharpe_ratio < 1.0:
        logger.critical(f"❌ MODEL REJECTED: Sharpe Ratio {sharpe_ratio:.2f} < 1.0")
        return False
    if max_drawdown > 10.0:
        logger.critical(f"❌ MODEL REJECTED: Max Drawdown {max_drawdown:.2f}% > 10%")
        return False
    if total_trades < 50:
        logger.critical(f"❌ MODEL REJECTED: Total Trades {total_trades} < 50")
        return False
    
    logger.critical(f"✅ MODEL ACCEPTED: PF={profit_factor:.2f}, WR={win_rate:.2%}")
    return True
```

#### Шаг 2: Проверь вызов валидации
```powershell
Select-String -Path src\core\trading_system.py -Pattern "_validate_model_metrics.*backtest_report"
```

**Если не найдено** - найди в `_run_champion_contest()`:
```python
backtest_report = backtester.run()
logger.warning(f"Полный отчет: {backtest_report}")

# ДОБАВЬ ЭТО:
if not self._validate_model_metrics(backtest_report):
    logger.critical(f"!!! МОДЕЛЬ ОТКЛОНЕНА ВАЛИДАЦИЕЙ !!!")
    return

# Только после валидации:
final_report = {"holdout_neg_mse": best_score, **backtest_report}
self.db_manager.promote_challenger_to_champion(...)
```

#### Шаг 3: Перезапусти и дождись R&D
```powershell
python main_pyside.py

# R&D цикл запускается раз в день
# Или дождись следующего цикла
```

---

## 🔧 УНИВЕРСАЛЬНОЕ РЕШЕНИЕ

### Если ничего не помогает:

#### 1. Полная проверка
```powershell
# Проверь все файлы
python -m py_compile src\core\trading_system.py
python -m py_compile src\core\safety_monitor.py
python -m py_compile src\ml\feature_engineer.py

# Проверь конфиг
Get-Content configs\settings.json | ConvertFrom-Json | Out-Null
```

#### 2. Чистый перезапуск
```powershell
# Останови всё
Get-Process python | Stop-Process -Force

# Очисти кэш
Remove-Item -Recurse -Force __pycache__, src\__pycache__, src\*\__pycache__ -ErrorAction SilentlyContinue

# Подожди
Start-Sleep -Seconds 10

# Запусти
python main_pyside.py
```

#### 3. Откат (крайняя мера)
```powershell
# Сохрани текущее состояние
Copy-Item configs\settings.json configs\settings.json.backup

# Откат
git checkout configs/settings.json
git checkout src/core/trading_system.py
git checkout src/ml/feature_engineer.py
Remove-Item src\core\safety_monitor.py -ErrorAction SilentlyContinue

# Запусти
python main_pyside.py

# Система должна работать (но с рискованными настройками!)
```

---

## ✅ ПРОВЕРКА ПОСЛЕ ИСПРАВЛЕНИЯ

### Чеклист:
```powershell
# 1. Система запускается
python main_pyside.py
Start-Sleep -Seconds 60
Get-Process python | Where-Object {$_.MainWindowTitle -like "*Genesis*"}
```
- [ ] Процесс работает >60 секунд

```powershell
# 2. Safety Monitor работает
Get-Content logs\trading_system.log | Select-String -Pattern "\[SAFETY\]"
```
- [ ] Есть "[SAFETY] ✅ Monitoring initialized"

```powershell
# 3. Конфиг применён
Select-String -Path configs\settings.json -Pattern '"MAX_OPEN_POSITIONS":\s*5'
```
- [ ] Показывает 5

```powershell
# 4. Нет ошибок
Get-Content logs\trading_system.log -Tail 100 | Select-String -Pattern "ERROR|Exception"
```
- [ ] Нет критических ошибок

---

## 📞 НУЖНА ПОМОЩЬ?

### Собери информацию:
```powershell
# Создай отчёт
$report = @"
ПРОБЛЕМА: [опиши]

ЛОГИ:
$(Get-Content logs\trading_system.log -Tail 50)

КОНФИГ MAX_OPEN_POSITIONS:
$(Select-String -Path configs\settings.json -Pattern 'MAX_OPEN_POSITIONS')

ПРОЦЕССЫ:
$(Get-Process python -ErrorAction SilentlyContinue)
"@

$report | Out-File problem_report.txt
Get-Content problem_report.txt
```

### Отправь AI:
```
Я исправлял проблему [номер проблемы] по QUICK_FIX_GUIDE.md

Вот что я сделал:
[опиши шаги]

Вот результат:
[вставь содержимое problem_report.txt]

Что делать дальше?
```

---

## ⏱️ ВРЕМЯ РЕШЕНИЯ

- **Проблема 1 (краш):** 5-15 минут
- **Проблема 2 (Safety Monitor):** 10-20 минут
- **Проблема 3 (>5 позиций):** 2-5 минут
- **Проблема 4 (валидация):** 10-30 минут

**Если дольше** - используй откат и попроси помощь.

---

**Удачи! 🔧**
