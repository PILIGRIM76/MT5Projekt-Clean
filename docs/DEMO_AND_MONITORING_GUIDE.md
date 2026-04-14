# 🚀 Демо-запуск + Grafana Monitoring: Пошаговое руководство

**Цель**: Запустить систему в демо-режиме и визуализировать метрики в реальном времени через Grafana.

**Время**: ~1.5 часа на настройку + 48 часов наблюдения.

---

## 📋 Часть 1: Подготовка к демо-запуску (15 минут)

### 🔹 Шаг 1: Проверка конфига

```bash
# 1. Убедитесь, что dry_run включён
grep "dry_run:" config/production.yaml
# Должно быть: dry_run: true

# 2. Проверьте лимиты для демо (безопасные значения)
cat << 'EOF' >> config/production.yaml

# Демо-режим: дополнительные ограничения
demo_mode:
  max_order_volume: 0.01
  max_orders_per_day: 10
  allowed_symbols: ["EURUSD", "GBPUSD", "USDJPY"]
  virtual_balance: 10000.0
EOF
```

### 🔹 Шаг 2: Подготовка БД

```bash
# 1. Проверка WAL режима
sqlite3 data/genesis_prod.db "PRAGMA journal_mode;"
# Ожидаемо: wal

# 2. Проверка целостности
sqlite3 data/genesis_prod.db "PRAGMA quick_check;"
# Ожидаемо: ok

# 3. Резервная копия перед запуском
cp -r data/ data.backup.$(date +%F-%H%M)
echo "✅ Backup created: data.backup.$(date +%F-%H%M)"
```

### 🔹 Шаг 3: Проверка зависимостей

```bash
# 1. Активация venv
source venv/Scripts/activate  # Windows
# source venv/bin/activate    # Linux/macOS

# 2. Проверка пакетов
pip check
# Ожидаемо: No broken requirements found

# 3. Проверка MT5 API
python -c "
import MetaTrader5 as mt5
if mt5.initialize():
    info = mt5.terminal_info()
    print(f'✅ MT5: connected={info.connected}, trade_mode={info.trade_mode}')
    mt5.shutdown()
else:
    print('❌ MT5 initialization failed')
"
```

---

## 📊 Часть 2: Настройка Grafana Dashboard (45 минут)

### 🔹 Шаг 1: Запуск мониторинга

```bash
# 1. Запуск стека
docker-compose -f docker-compose.monitoring.yml up -d

# 2. Проверка статуса
docker-compose -f docker-compose.monitoring.yml ps
# Ожидаемо: prometheus, loki, grafana — все Up
```

### 🔹 Шаг 2: Открыть Grafana

- **URL**: http://localhost:3000
- **Логин**: admin
- **Пароль**: admin123
- **Дашборд**: "MT5Projekt-Clean Overview" (загрузится автоматически)

### 🔹 Шаг 3: Запуск приложения

```bash
python main_pyside.py --config config/production.yaml
```

### 🔹 Шаг 4: Проверка экспорта метрик

```bash
curl http://localhost:9118/metrics | grep -E "ticks_received|pipeline_latency"
# Ожидаемо: строки с метриками Prometheus
```

---

## 📊 Часть 3: Что наблюдать в Grafana (первые 48 часов)

### 🔹 Панель 1: Pipeline Latency

| Показатель | Норма | Тревога |
|-----------|-------|---------|
| p50 | < 25ms | > 50ms |
| p95 | < 50ms | > 100ms |
| Пики | Кратковременные | Постоянные > 200ms |

🔍 **Если latency растёт**: проверить Resource Usage → CPU/RAM лимиты → уменьшить max_concurrent_tasks.

### 🔹 Панель 2: Orders Executed vs Failed

| Сценарий | Интерпретация |
|---------|---------------|
| ✅ Executed > Failed | Система работает корректно |
| ⚠️ Failed растёт | Проверить логи: "order_failed" → причина |
| 🔴 Только Failed | Проблема с MT5 или риск-лимитами |

### 🔹 Панель 3: Component Health

Все компоненты должны быть **зелёными** (Healthy = 2):
- `mt5_connection` — подключение к терминалу
- `database` — целостность БД
- `event_bus_queue` — отсутствие бэклога
- `system_resources` — CPU/RAM в норме
- `ml_inference` — латентность предсказаний

### 🔹 Панель 4: Live Logs

- **Фильтр**: `|= "ERROR" or |= "CRITICAL"`
- ✅ **Ожидаемо**: 0 записей за 48 часов
- ⚠️ **Если есть**: кликнуть на лог → увидеть контекст → проверить HealthMonitor

---

## 📋 Часть 4: Ежедневный чеклист

### День 1 (часы 0-24)

```bash
# Утро: проверка старта
grep "started" logs/app.log | wc -l
# Ожидаемо: 4 (MLPredictor, TradingSystem, HealthMonitor, AutoTrainer)

# Обед: проверка метрик
curl -s http://localhost:9090/api/v1/query?query=pipeline_latency_ms | jq '.data.result[0].value[1]'
# Ожидаемо: число < 50

# Вечер: проверка очереди переобучения
grep "Retrain Queue" logs/app.log | tail -3
# Ожидаемо: "pending": 0 или 1, без зависаний
```

### День 2 (часы 24-48)

```bash
# Сводный отчёт по ошибкам
grep -c "ERROR\|CRITICAL" logs/app.log
# Ожидаемо: 0

# Проверка роста БД
sqlite3 data/genesis_prod.db "SELECT COUNT(*) FROM bars;"
# Ожидаемо: число растёт (новые бары сохраняются)

# Финальная проверка Health Report
grep "HEALTH REPORT" logs/app.log | tail -1
# Ожидаемо: все компоненты "healthy"
```

---

## ✅ Критерии успеха для перехода к реальным ордерам

| Критерий | Порог | Проверка |
|---------|-------|---------|
| 🔴 Ошибки ERROR/CRITICAL | 0 за 48ч | `grep -c "ERROR\|CRITICAL" logs/app.log` |
| 🟡 Pipeline latency p95 | < 50ms | Grafana → Pipeline Latency panel |
| 🟢 Health Monitor | 100% healthy | `grep "HEALTH REPORT" logs/app.log` |
| 🔵 Dry-run ордера | Логируются корректно | `grep "DRY-RUN" logs/app.log \| wc -l` |
| 🟣 AutoTrainer | Нет зависаний очереди | `grep "Retrain Queue" logs/app.log` |
| 💾 БД целостность | WAL + quick_check=ok | `sqlite3 data/genesis_prod.db "PRAGMA quick_check;"` |

🟢 **Если все 6 критериев выполнены** → система готова к `dry_run: false`.

---

## 🔄 Переход к реальным ордерам (после успешного демо)

### Шаг 1: Изменение конфига

```yaml
# config/production.yaml
system:
  dry_run: false  # ← Меняем на false
  environment: "live"

trading:
  max_orders_per_hour: 2  # ← Начинаем с минимума
  max_total_exposure: 0.5  # ← Консервативный лимит
```

### Шаг 2: Подтверждение

```bash
# Создаём маркер-файл (защита от случайного запуска)
echo "Confirmed: $(date -Iseconds)" > data/.real_trading_enabled

# Проверка перед запуском
test -f data/.real_trading_enabled && echo "✅ Real trading enabled" || echo "❌ Missing confirmation"
```

### Шаг 3: Запуск с повышенным логированием

```bash
python main_pyside.py --config config/production.yaml --log-level=DEBUG 2>&1 | tee logs/live-trading.log
```

### Шаг 4: Первые 10 ордеров — ручной мониторинг

```bash
# В отдельном терминале:
tail -f logs/live-trading.log | grep -E "order_executed|order_failed|DRY-RUN"

# Ожидаемо:
# ✅ Order executed: BUY EURUSD 0.01 @ 1.08512 (id=12345)
# 📊 METRICS: orders_executed_total{symbol="EURUSD",action="BUY"} 1
```

⚠️ **Важно**: Первые 10 реальных ордеров выполняйте с минимальным объёмом (0.01 лота) и только на демо-счёте. После успешного прохождения — можно переходить на микро-реальный счёт ($50-100).

---

## 🎁 Бонус: готовые команды

### 📈 Быстрый дашборд в терминале

```bash
# Алиас для проверки метрик
alias mt5-metrics='curl -s http://localhost:9090/api/v1/query?query=up | jq ".data.result[].metric.job"'

# Алиас для проверки ошибок
alias mt5-errors='grep -E "ERROR|CRITICAL" logs/app.log | tail -20'

# Алиас для проверки здоровья
alias mt5-health='grep "HEALTH REPORT" logs/app.log | tail -1'
```

### 🔄 Автоматический бэкап БД (crontab)

```bash
# Ежедневный бэкап в 3:00 ночи
0 3 * * * cp /path/to/data/genesis_prod.db /backup/genesis_prod.db.$(date +\%F) && sqlite3 /backup/genesis_prod.db.$(date +\%F) "VACUUM;"
```

### 🛡️ Экстренные действия

```bash
# ⏸️ Приостановить торговлю
touch data/.pause_trading

# 🔄 Перезапустить мониторинг
docker-compose -f docker-compose.monitoring.yml restart

# 🆘 Полный сброс мониторинга
docker-compose -f docker-compose.monitoring.yml down -v
docker-compose -f docker-compose.monitoring.yml up -d
```

---

## 🧠 Архитектура "Единого организма":

```
├── 📡 Событийный пайплайн (tick → predict → signal → risk → exec)
├── 🧵 Изоляция доменов (GUI, MT5, ML, DB, Health)
├── 🛡️ Самовосстановление (HealthMonitor + CircuitBreaker)
├── 📊 Наблюдаемость (Prometheus + Grafana + Loki)
├── 🤖 Авто-обучение (AutoTrainer с приоритетной очередью)
└── 🚀 Готовность к 24/7 (systemd + headless mode)
```

---

> 📝 **Дата**: 14 апреля 2026
> 👥 **Team**: MT5 Projekt
> 🚀 **Статус**: ✅ Production Ready
