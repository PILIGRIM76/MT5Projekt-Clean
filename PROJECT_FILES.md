# 📁 Структура проекта Genesis Trading System

**Дата:** 23 февраля 2026  
**Версия:** 1.0.0  
**Статус:** ✅ Очищено и готово

---

## 📂 Корневые файлы

### Основные файлы:
- **main_pyside.py** (170 KB) - Точка входа приложения
- **requirements.txt** (844 B) - Python зависимости
- **LICENSE** (35 KB) - Лицензия проекта
- **pyproject.toml** (2.92 KB) - Конфигурация проекта

### Конфигурация сборки:
- **genesis_trading.spec** (5.97 KB) - PyInstaller конфигурация
- **installer_script.iss** (3.83 KB) - Inno Setup скрипт
- **build_exe.bat** (1.78 KB) - Скрипт сборки EXE
- **BUILD_RELEASE.bat** (4.81 KB) - Скрипт полной сборки релиза

### Git конфигурация:
- **.gitignore** (660 B) - Исключения для Git
- **.gitattributes** (303 B) - Атрибуты Git

---

## 📚 Документация (9 файлов)

### Для пользователей:
1. **README.md** (10 KB) - Главная документация
2. **QUICK_START.md** (8.3 KB) - Быстрый старт
3. **HOW_TO_RUN.md** (7.27 KB) - Инструкция по запуску
4. **TROUBLESHOOTING_PROMPT.md** (20.94 KB) - Решение проблем
5. **QUICK_FIX_GUIDE.md** (11.04 KB) - Быстрые исправления

### Для разработчиков:
6. **BUILD_INSTRUCTIONS.md** (7.22 KB) - Инструкция по сборке
7. **RETRAIN_INSTRUCTIONS.md** (5.96 KB) - Переобучение моделей
8. **AI_COMMANDS_EXAMPLES.md** (17.2 KB) - Примеры команд

### Отчёты:
9. **PROJECT_CLEANUP_REPORT.md** (10.03 KB) - Отчёт об очистке

---

## 📁 Папки

### src/ - Исходный код
```
src/
├── core/           # Ядро системы
├── ml/             # ML модели
├── strategies/     # Торговые стратегии
├── data/           # Провайдеры данных
├── analysis/       # Анализ рынка
├── risk/           # Управление рисками
├── gui/            # Графический интерфейс
├── web/            # Web сервер
├── db/             # База данных
└── utils/          # Утилиты
```

### configs/ - Конфигурации
```
configs/
├── settings.example.json       # Пример конфигурации
├── settings.json              # Рабочая конфигурация (в .gitignore)
├── optimized_params.json      # Оптимизированные параметры
├── strategy_configurations.json
├── strategy_parameters.json
└── .env                       # Переменные окружения (в .gitignore)
```

### assets/ - Ресурсы
```
assets/
├── dashboard/      # Web dashboard
├── sounds/         # Звуковые эффекты
├── icon.ico.ico    # Иконка приложения
└── *.html, *.js    # Web файлы
```

### installer_output/ - Установщик
```
installer_output/
├── GenesisTrading_Setup_v1.0.0.exe  # Установщик (407.67 MB)
├── README.md                         # Инструкция
└── SHA256.txt                        # Контрольная сумма
```

---

## 🗑️ Удалённые файлы (20 шт.)

### Утилиты и скрипты:
- `__init__.py` - пустой файл
- `check_bitcoin_availability.py` - проверка Bitcoin
- `collect_code.py` - сборка кода
- `setup_telegram.py` - настройка Telegram
- `sync_symbols.py` - синхронизация символов
- `run_headless.py` - запуск без GUI

### Скрипты переобучения:
- `train_bitcoin_now.py` - обучение Bitcoin
- `retrain_all_models.py` - переобучение всех моделей
- `retrain_symbols.py` - переобучение символов
- `retrain_symbols_simple.py` - простое переобучение
- `smart_retrain.py` - умное переобучение
- `smart_retrain.bat` - скрипт умного переобучения

### Batch скрипты:
- `create_portable.bat` - создание portable версии
- `maintenance.bat` - обслуживание
- `optimize_all.bat` - оптимизация
- `start_genesis.bat` - запуск системы

### Конфигурационные файлы:
- `VERSION` - файл версии
- `MANIFEST.in` - манифест
- `qodana.yaml` - конфигурация Qodana
- `installed.txt` - список установленных пакетов

---

## 📊 Статистика

### До очистки:
- Файлов в корне: 39
- Документов: ~25
- Временных файлов: 20

### После очистки:
- Файлов в корне: 19
- Документов: 9 (актуальных)
- Временных файлов: 0

### Освобождено места:
- Временные файлы: ~50 KB
- Устаревшие документы: ~200 KB
- Папки сборки: ~1.5 GB
- Утилиты и скрипты: ~100 KB

**Итого освобождено: ~1.5 GB**

---

## ✅ Актуальная структура

```
MT5Projekt-Clean/
├── .git/                       # Git репозиторий
├── .gitignore                  # Git исключения
├── .gitattributes             # Git атрибуты
├── src/                        # Исходный код (без изменений)
├── configs/                    # Конфигурации
├── assets/                     # Ресурсы
├── installer_output/           # Готовый установщик
├── main_pyside.py             # Точка входа
├── requirements.txt           # Зависимости
├── pyproject.toml             # Конфигурация проекта
├── LICENSE                    # Лицензия
├── genesis_trading.spec       # PyInstaller конфиг
├── installer_script.iss       # Inno Setup скрипт
├── build_exe.bat              # Скрипт сборки EXE
├── BUILD_RELEASE.bat          # Скрипт полной сборки
├── README.md                  # Главная документация
├── QUICK_START.md            # Быстрый старт
├── HOW_TO_RUN.md             # Инструкция
├── BUILD_INSTRUCTIONS.md     # Сборка
├── TROUBLESHOOTING_PROMPT.md # Проблемы
├── QUICK_FIX_GUIDE.md        # Исправления
├── RETRAIN_INSTRUCTIONS.md   # Переобучение
├── AI_COMMANDS_EXAMPLES.md   # Примеры
└── PROJECT_CLEANUP_REPORT.md # Отчёт об очистке
```

---

## 🎯 Что нужно для работы

### Для пользователей:
1. Установщик из `installer_output/`
2. MetaTrader 5
3. Windows 10/11

### Для разработчиков:
1. Python 3.14+
2. Зависимости из `requirements.txt`
3. PyInstaller для сборки
4. Inno Setup для создания установщика

---

## 🔄 Обслуживание

### Что НЕ коммитить в Git:
- `database/` - локальная БД
- `logs/` - логи
- `configs/settings.json` - личная конфигурация
- `build/`, `dist/` - временные файлы сборки
- Временные файлы (error*.txt, output*.txt)

Всё это в `.gitignore`!

### Что коммитить:
- Исходный код в `src/`
- Примеры конфигураций
- Документацию
- Скрипты сборки
- Ресурсы

---

## ✨ Итог

Проект полностью очищен от ненужных файлов. Осталось только актуальное и необходимое для работы и разработки.

**Размер проекта уменьшен на ~1.5 GB**

**Готово к использованию и разработке!** 🚀

---

**Дата:** 23 февраля 2026  
**Статус:** ✅ Очистка завершена
