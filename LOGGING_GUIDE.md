# Система логирования Genesis Trading

## Обзор

Система логирования обеспечивает отслеживание работы приложения для отладки и мониторинга.

## Структура логов

```
logs/
├── genesis.log              # Основной лог (с ротацией)
├── genesis_errors.log       # Только ошибки (с ротацией)
├── genesis.log.YYYY-MM-DD   # Архивные логи (daily ротация)
└── recent_log_excerpt.txt   # Последние записи
```

## Использование в коде

```python
from src.utils.logger import get_logger, setup_logger

# Получить существующий логгер
logger = get_logger('genesis')

# Или создать новый с настройками
logger = setup_logger(
    name='my_module',
    level=logging.INFO,
    log_to_file=True,
    log_to_console=True,
    rotation='daily',
    backup_count=7
)

# Логирование
logger.debug("Отладочное сообщение")
logger.info("Информационное сообщение")
logger.warning("Предупреждение")
logger.error("Ошибка")
logger.critical("Критическая ошибка")
```

## Конфигурация

В `configs/settings.json` добавьте секцию `logging`:

```json
{
  "logging": {
    "enabled": true,
    "level": "INFO",
    "log_to_file": true,
    "log_to_console": true,
    "rotation": "daily",
    "backup_count": 7,
    "max_bytes": 10485760,
    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
  }
}
```

## Параметры конфигурации

| Параметр | Описание | Значения |
|----------|----------|----------|
| `enabled` | Включить логирование | `true` / `false` |
| `level` | Уровень логирования | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `log_to_file` | Писать в файл | `true` / `false` |
| `log_to_console` | Вывод в консоль | `true` / `false` |
| `rotation` | Тип ротации | `daily`, `hourly`, `size`, `none` |
| `backup_count` | Кол-во резервных файлов | число (например, `7`) |
| `max_bytes` | Макс. размер файла (байт) | число (например, `10485760` = 10MB) |

## Уровни логирования

- **DEBUG** — детальная отладочная информация
- **INFO** — общая информация о работе системы
- **WARNING** — предупреждения (некритичные проблемы)
- **ERROR** — ошибки (критичные проблемы, но работа продолжается)
- **CRITICAL** — критические ошибки (работа может быть прекращена)

## Формат записи

```
2026-03-24 19:00:00 | INFO     | genesis | main:123 | Сообщение лога
```

Формат: `дата время | уровень | имя_логгера | функция:строка | сообщение`

## Просмотр логов

### Windows (PowerShell)
```powershell
# Последние 50 строк
Get-Content logs\genesis.log -Tail 50

# Следить в реальном времени
Get-Content logs\genesis.log -Wait -Tail 10
```

### Linux/Mac
```bash
# Последние 50 строк
tail -n 50 logs/genesis.log

# Следить в реальном времени
tail -f logs/genesis.log
```

## Автоматическая ротация

- **Daily**: создаётся новый файл каждый день, старые архивируются
- **Hourly**: создаётся новый файл каждый час
- **Size**: при достижении 10MB создаётся новый файл
- **None**: один файл с меткой времени запуска

## Обработка ошибок

Все ошибки уровня ERROR и выше автоматически записываются в отдельный файл `genesis_errors.log` для удобного мониторинга проблем.
