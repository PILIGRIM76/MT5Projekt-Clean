# Система Мониторинга и Тестирования Genesis Trading System

Автоматизированный мониторинг GUI, E2E тестирование и стресс-тесты для обеспечения стабильности торговой системы.

## 📂 Структура

```
tests/monitoring/
├── __init__.py                      # Инициализация пакета
├── test_system_monitor.py           # E2E + GUI тесты (pytest)
├── stress_test.py                   # Стресс-тестирование
└── README.md                        # Документация (этот файл)

reports/
├── monitor_YYYYMMDD_HHMMSS.log     # Логи мониторинга
├── stress_YYYYMMDD_HHMMSS.log      # Логи стресс-тестов
└── monitor-results.xml             # Результаты тестов (JUnit формат)
```

## 🚀 Быстрый Старт

### 1. Установка зависимостей

```bash
pip install pytest pytest-qt psutil
```

### 2. Запуск тестов мониторинга

```bash
# Все тесты с подробным выводом
pytest tests/monitoring/test_system_monitor.py -v -s --log-cli-level=INFO

# Конкретный тест
pytest tests/monitoring/test_system_monitor.py::TestSystemMonitor::test_01_gui_responsiveness -v

# С сохранением результатов в XML
pytest tests/monitoring/test_system_monitor.py -v --junitxml=reports/monitor-results.xml
```

### 3. Запуск стресс-теста

```bash
# Стресс-тест на 2 минуты (по умолчанию)
python tests/monitoring/stress_test.py

# Кастомные параметры
python tests/monitoring/stress_test.py --duration 300 --interval 0.05 --check-interval 5
```

**Параметры:**
- `--duration`: Длительность теста в секундах (по умолчанию: 120)
- `--interval`: Пауза между действиями в секундах (по умолчанию: 0.1)
- `--check-interval`: Интервал проверки ресурсов в секундах (по умолчанию: 10)

## 📊 Тесты

### test_system_monitor.py

**10 тестов для проверки работоспособности системы:**

| # | Тест | Что проверяет | Статус |
|---|------|---------------|--------|
| 1 | `test_01_gui_responsiveness` | Отзывчивость GUI, event loop, память | ✅ |
| 2 | `test_02_data_update_latency` | Тайминги обновления данных (< 3с) | ✅ |
| 3 | `test_03_tab_switching_stability` | Стабильность переключения вкладок | ✅ |
| 4 | `test_04_error_handling_simulation` | Обработка ошибок MT5 | ✅ |
| 5 | `test_05_auto_retrain_threshold` | Порог авто-переобучения 30% | ✅ |
| 6 | `test_06_scaler_mismatch_validation` | Валидация scaler mismatch | ✅ |
| 7 | `test_07_memory_cleanup_after_training` | Очистка памяти после обучения | ✅ |
| 8 | `test_08_thread_safety_utilities` | Thread safety утилиты GUI | ✅ |
| 9 | `test_09_critical_error_logging` | Логирование критических ошибок | ✅ |
| 10 | `test_10_system_resources` | CPU, RAM, Disk usage | ✅ |

### stress_test.py

**Интенсивное тестирование стабильности:**

- 🔄 Быстрое переключение вкладок
- 📊 Частые запросы данных
- 🖱️ Эмуляция действий пользователя
- 💤 Проверка утечек памяти
- ⚡ Мониторинг CPU usage
- 📝 Детальная статистика по каждому действию

## 📈 Отчёты

### Логи мониторинга

Файл: `reports/monitor_YYYYMMDD_HHMMSS.log`

**Пример содержимого:**
```
2026-04-12 18:30:15 - INFO - ================================================================================
2026-04-12 18:30:15 - INFO - === ТЕСТ 1: ОТЗЫВЧИВОСТЬ GUI ===
2026-04-12 18:30:15 - INFO - ================================================================================
2026-04-12 18:30:15 - INFO - ✅ Приложение активно и отвечает
2026-04-12 18:30:15 - INFO - ✅ Event loop обработал 10 событий за 0.52с
2026-04-12 18:30:15 - INFO - 📊 Потребление памяти: 512.3MB
2026-04-12 18:30:15 - INFO - ✅ Потребление памяти в норме
```

### Логи стресс-теста

Файл: `reports/stress_YYYYMMDD_HHMMSS.log`

**Пример финального отчёта:**
```
================================================================================
🏁 СТРЕСС-ТЕСТ ЗАВЕРШЁН
================================================================================
⏱️  Длительность: 120.5с
🔄 Всего итераций: 1150
⚡ Скорость: 9.5 итераций/с
📊 Конечная память: 645.2MB
📈 Рост памяти: +12.3MB
❌ Ошибок: 0
⚠️  Предупреждений: 2

📊 СТАТИСТИКА ДЕЙСТВИЙ:
Действие             Кол-во     Всего (с)    Среднее (мс) Макс (мс)
----------------------------------------------------------------
switch_tab           205        10.25        50.0         120.5
scroll_table         198        9.90         50.0         95.2
click_button         192        9.60         50.0         110.3
update_data          187        18.70        100.0        250.7
check_status         185        9.25         50.0         88.4
resize_window        183        9.15         50.0         105.6

✅ Ошибок не обнаружено.
```

## 🔄 CI/CD Интеграция

### GitHub Actions

Workflow: `.github/workflows/monitoring.yml`

**Автоматические запуски:**
- ✅ При push в main/develop
- ✅ При pull request
- ✅ По расписанию (каждый день в 02:00 UTC)
- ✅ Вручную через workflow_dispatch

**Что проверяет:**
- Все 10 тестов мониторинга
- Стресс-тест на 2 минуты (только schedule/dispatch)
- Результаты сохраняются как артефакты

### Локальный запуск перед коммитом

```bash
# Быстрая проверка (только критичные тесты)
pytest tests/monitoring/test_system_monitor.py -k "01 or 05 or 06 or 07" -v

# Полная проверка
pytest tests/monitoring/test_system_monitor.py -v

# Стресс-тест (1 минута)
python tests/monitoring/stress_test.py --duration 60
```

## 🔧 Настройка под ваш проект

### 1. Укажите реальные виджеты

В `test_system_monitor.py` замените заглушки на реальные объекты:

```python
# Найдите objectName ваших виджетов в main_window.py
# Например: self.start_btn.setObjectName("start_trading_btn")

# В тесте:
start_button = self.window.findChild(QPushButton, "start_trading_btn")
assert start_button is not None
```

### 2. Добавьте проверку реальных данных

```python
def test_02_data_update_latency(self, app):
    # Реальная проверка обновления эквити
    start_time = time.time()

    # Подписываемся на сигнал
    equity_values = []
    self.window.bridge.balance_updated.connect(
        lambda balance, equity: equity_values.append(equity)
    )

    # Ждём обновления
    updated = self._wait_for_condition(
        lambda: len(equity_values) > 0,
        timeout=3.0,
        description="обновление equity"
    )

    elapsed = time.time() - start_time
    assert updated, f"Equity не обновилось за {elapsed:.2f}с"
```

### 3. Настройте пороги

```python
# В начале файла
MAX_ALLOWED_DELAY = 3.0  # Секунды
MAX_MEMORY_MB = 2048     # MB
MAX_CPU_PERCENT = 90     # %
MAX_MEMORY_GROWTH_MB = 500  # MB за тест
```

## 💡 Советы

1. **Запускайте тесты после каждого изменения GUI**
   ```bash
   pytest tests/monitoring/test_system_monitor.py -v
   ```

2. **Используйте стресс-тест для проверки оптимизаций**
   ```bash
   # До оптимизации
   python tests/monitoring/stress_test.py --duration 300

   # После оптимизации
   python tests/monitoring/stress_test.py --duration 300

   # Сравните отчёты в reports/
   ```

3. **Автоматизируйте через CI/CD**
   - Результаты сохраняются как артефакты GitHub
   - Можно отслеживать тренды памяти/производительности
   - Автоматические уведомления при регрессиях

4. **Мониторьте ключевые метрики:**
   - 📈 Рост памяти > 500MB за тест = утечка
   - ⚡ CPU > 95% = проблемы с производительностью
   - ⏱️ Задержки обновления > 3с = UX проблемы
   - ❌ Ошибки в стресс-тесте = нестабильность

## 📝 Примеры использования

### Проверка после изменения авто-переобучения

```bash
# Проверяем что порог 30% работает
pytest tests/monitoring/test_system_monitor.py::TestSystemMonitor::test_05_auto_retrain_threshold -v

# Проверяем валидацию scaler mismatch
pytest tests/monitoring/test_system_monitor.py::TestSystemMonitor::test_06_scaler_mismatch_validation -v

# Проверяем очистку памяти
pytest tests/monitoring/test_system_monitor.py::TestSystemMonitor::test_07_memory_cleanup_after_training -v
```

### Полный регрессионный тест

```bash
# Все тесты мониторинга
pytest tests/monitoring/test_system_monitor.py -v --tb=short

# Стресс-тест на 5 минут
python tests/monitoring/stress_test.py --duration 300 --check-interval 15
```

## 🐛 Решение проблем

### Ошибка: "Qt platform plugin could not be initialized"

**Решение:**
```bash
# Windows
set QT_QPA_PLATFORM=offscreen

# Linux
export QT_QPA_PLATFORM=offscreen

# Затем запуск
pytest tests/monitoring/test_system_monitor.py -v
```

### Ошибка: "No module named 'pytestqt'"

**Решение:**
```bash
pip install pytest-qt
```

### Тесты падают на CI но проходят локально

**Причина:** CI использует headless режим без дисплея.

**Решение:** Добавьте в workflow:
```yaml
- name: Set up virtual display
  run: |
    pip install pytest-qt
    export QT_QPA_PLATFORM=offscreen
```

## 📞 Поддержка

При возникновении проблем создавайте Issue с:
- Полным логом из `reports/`
- Версией Python
- Версией PySide6
- Описанием ошибки

---

**Удачного тестирования! 🚀**
