# E2E Testing Guide

## Требования

### 1. Демо-счет MetaTrader 5

Для запуска E2E тестов необходим демо-счет MT5:

1. Скачайте MT5 с сайта брокера
2. Откройте демо-счет
3. Запишите credentials:
   - Login (номер счета)
   - Password (пароль инвестора или трейдера)
   - Server (название сервера)

### 2. Настройка переменных окружения

Создайте файл `.env` в корне проекта:

```bash
# MT5 Credentials
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=MetaQuotes-Demo

# Опционально
MT5_SYMBOL=EURUSD
MT5_TIMEFRAME=H1
```

Или используйте `.env.example` как шаблон:

```bash
cp .env.example .env
```

### 3. Запуск MT5 терминала

Перед запуском тестов убедитесь что MT5 запущен:

```bash
# Windows
# MT5 должен быть запущен с вашим демо-счетом

# Проверка подключения
python -c "import MetaTrader5 as mt5; print(mt5.initialize())"
```

---

## Запуск E2E тестов

### Базовый запуск

```bash
# Запустить все E2E тесты
pytest tests/e2e/ -v --e2e

# Запустить конкретный тест
pytest tests/e2e/test_mt5_connection.py::TestMT5Connection::test_mt5_initialized -v

# Запустить тесты с покрытием
pytest tests/e2e/ -v --e2e --cov=src --cov-report=html
```

### Запуск с маркерами

```bash
# Только MT5 тесты
pytest tests/e2e/ -v -m mt5

# Только интеграция
pytest tests/e2e/ -v -m integration

# Медленные тесты
pytest tests/e2e/ -v -m slow
```

---

## Структура E2E тестов

```
tests/e2e/
├── test_mt5_connection.py       # Тесты подключения к MT5
├── test_trading_flow.py         # Тесты полного цикла торговли
├── test_trading_system.py       # Тесты интеграции с TradingSystem
└── conftest.py                  # Общие фикстуры
```

---

## Сценарии тестирования

### 1. Подключение → Получение данных → Сигнал → Сделка → Закрытие

```python
def test_full_trading_cycle():
    # 1. Подключение
    mt5.initialize()

    # 2. Получение данных
    rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_H1, 0, 100)

    # 3. Генерация сигнала
    signal = signal_service.get_trade_signal("EURUSD", df, 60)

    # 4. Открытие сделки
    order = trade_executor.open_position(signal)

    # 5. Закрытие сделки
    result = trade_executor.close_position(order.ticket)

    assert result.profit is not None
```

### 2. Обработка ошибок (потеря соединения, маржин-колл)

```python
def test_connection_loss_handling():
    # Имитация потери соединения
    mt5.shutdown()

    # Попытка получить данные
    with pytest.raises(ConnectionError):
        data_provider.get_historical_data("EURUSD", mt5.TIMEFRAME_H1, 100)
```

### 3. Ночная торговля (свопы, перезагрузка)

```python
def test_overnight_trading():
    # Проверка расчета свопов
    swap_info = mt5.symbol_info("EURUSD")
    assert swap_info.swap_long is not None
    assert swap_info.swap_short is not None
```

---

## Устранение неполадок

### Ошибка: "MT5 не запустился"

**Решение:**
1. Убедитесь что MT5 установлен
2. Проверьте credentials в `.env`
3. Запустите MT5 вручную перед тестами

### Ошибка: "Demo account expired"

**Решение:**
1. Откройте новый демо-счет в MT5
2. Обновите `.env` с новыми credentials

### Ошибка: "No symbols found"

**Решение:**
1. Проверьте что символ существует в MT5
2. Убедитесь что рынок открыт (не выходной)

---

## Best Practices

1. **Используйте демо-счет** - никогда не запускайте E2E тесты на реальном счете!

2. **Изолируйте тесты** - каждый тест должен быть независимым

3. **Очищайте позиции** - закрывайте все позиции после теста:
   ```python
   @pytest.fixture(autouse=True)
   def cleanup_positions(mt5_connection):
       yield
       # Закрыть все позиции
       positions = mt5_connection.positions_get()
       for pos in positions:
           mt5_connection.position_close(pos.ticket)
   ```

4. **Лимитируйте запуск** - E2E тесты медленные, запускайте только при необходимости

5. **Логируйте ошибки** - используйте `--tb=long` для подробных логов

---

## Интеграция с CI/CD

E2E тесты не запускаются в CI по умолчанию (требуют MT5).

Для запуска в GitHub Actions добавьте secret variables:
- `MT5_LOGIN`
- `MT5_PASSWORD`
- `MT5_SERVER`

И обновите `.github/workflows/tests.yml`:

```yaml
- name: Run E2E tests
  if: github.event_name == 'schedule'  # Только по расписанию
  run: |
    pytest tests/e2e/ -v --e2e
  env:
    MT5_LOGIN: ${{ secrets.MT5_LOGIN }}
    MT5_PASSWORD: ${{ secrets.MT5_PASSWORD }}
    MT5_SERVER: ${{ secrets.MT5_SERVER }}
```
