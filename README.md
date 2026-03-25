# 🚀 Genesis Trading System

**Версия:** 13.0.0  
**Платформа:** Windows 10/11 x64  
**Python:** 3.9+

[![Build EXE](https://github.com/PILIGRIM76/MT5Projekt-Clean/actions/workflows/build.yml/badge.svg)](https://github.com/PILIGRIM76/MT5Projekt-Clean/actions/workflows/build.yml)

---

## 📖 О проекте

Genesis Trading System - это саморазвивающаяся торговая экосистема для MetaTrader 5 с использованием AI/ML.

**Основные возможности:**
- 🤖 AI Trading (Deep Learning, Reinforcement Learning)
- 📊 Market Scanner (сканирование рынка)
- 📈 Trading Signals (торговые сигналы)
- 🛡️ Risk Management (управление рисками)
- 📉 Backtesting (тестирование на истории)
- 🔄 Auto Retraining (автоматическое переобучение)

---

## 🚀 Быстрый старт

### 1️⃣ Скачать

Перейдите в [Releases](https://github.com/PILIGRIM76/MT5Projekt-Clean/releases) и скачайте последнюю версию.

### 2️⃣ Распаковать

Распакуйте архив в любую папку.

### 3️⃣ Настроить

Откройте `configs/settings.json` и укажите:

```json
{
  "MT5_LOGIN": "ваш_логин",
  "MT5_PASSWORD": "ваш_пароль",
  "MT5_SERVER": "ваш_сервер",
  "MT5_PATH": "C:/Program Files/MetaTrader 5/terminal64.exe"
}
```

### 4️⃣ Запустить

Запустите `GenesisTrading.exe`

---

## 📦 Сборка из исходного кода

### Требования

- Python 3.9+
- Git
- 10 GB свободного места

### Установка

```bash
# Клонирование репозитория
git clone https://github.com/PILIGRIM76/MT5Projekt-Clean.git
cd MT5Projekt-Clean

# Установка зависимостей
pip install -r requirements.txt

# Сборка EXE
cd GenesisTrading_Build
build.bat
```

### Автоматическая сборка (GitHub Actions)

1. Перейдите в [Actions](https://github.com/PILIGRIM76/MT5Projekt-Clean/actions)
2. Выберите workflow **Build EXE**
3. Скачайте артефакт из последнего запуска

---

## 📁 Структура проекта

```
MT5Projekt-Clean/
├── .github/workflows/    # GitHub Actions workflow
├── GenesisTrading_Build/ # Скрипты сборки
│   ├── build.bat         # Сборка EXE
│   ├── deploy.bat        # Развёртывание
│   └── GenesisTrading.spec
├── src/                  # Исходный код
│   ├── core/             # Ядро системы
│   ├── ml/               # ML модели
│   ├── gui/              # GUI компоненты
│   ├── data/             # Работа с данными
│   └── db/               # Базы данных
├── configs/              # Конфигурация
├── assets/               # Ресурсы
└── main_pyside.py        # Точка входа
```

---

## 🔧 Документация

| Файл | Описание |
|------|----------|
| [QUICK_START.md](QUICK_START.md) | Быстрый старт |
| [SETUP_GUIDE.md](SETUP_GUIDE.md) | Полная установка |
| [GITHUB_SETUP_GUIDE.md](GITHUB_SETUP_GUIDE.md) | Настройка GitHub |
| [BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md) | Инструкция по сборке |
| [HOW_TO_RUN.md](HOW_TO_RUN.md) | Как запустить |

---

## ⚙️ Конфигурация

### Основные параметры

| Параметр | Описание | Пример |
|----------|----------|--------|
| `MT5_LOGIN` | Логин MT5 | `12345678` |
| `MT5_PASSWORD` | Пароль MT5 | `MyPassword` |
| `MT5_SERVER` | Сервер MT5 | `Alpari-MT5-Demo` |
| `MT5_PATH` | Путь к терминалу | `C:/Program Files/MetaTrader 5/terminal64.exe` |

### Дополнительные параметры

- `RISK_PERCENT` - Риск на сделку (по умолчанию: 0.5%)
- `MAX_POSITIONS` - Максимум позиций (по умолчанию: 5)
- `USE_AI` - Использовать AI (по умолчанию: True)

---

## 🐛 Решение проблем

### EXE не запускается

1. Проверьте логи в `logs/genesis_system.log`
2. Убедитесь, что MT5 установлен
3. Проверьте `configs/settings.json`

### Ошибка matplotlib

Обновите matplotlib:
```bash
pip install --upgrade matplotlib
```

### Сборка не удаётся

1. Очистите кэш: `clean_before_build.bat`
2. Проверьте зависимости: `pip install -r requirements.txt`
3. Запустите сборку снова

---

## 📊 Системные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **ОС** | Windows 10 x64 | Windows 11 x64 |
| **CPU** | 4 ядра | 8+ ядер |
| **RAM** | 8 GB | 16+ GB |
| **Диск** | 10 GB | 20+ GB (SSD) |
| **MT5** | Любая версия | Последняя |

---

## 🔐 Безопасность

**Никогда не загружайте на GitHub:**
- ❌ `configs/settings.json` (пароли)
- ❌ `*.db` (базы данных)
- ❌ `*.log` (логи)
- ❌ `ai_models/` (модели)

Эти файлы добавлены в `.gitignore`.

---

## 📈 Roadmap

- [ ] Поддержка других брокеров
- [ ] Мобильное приложение
- [ ] Веб-интерфейс
- [ ] Облачная синхронизация
- [ ] Социальный трейдинг

---

## 🤝 Вклад в проект

### Pull Requests приветствуются!

1. Fork репозиторий
2. Создайте ветку (`git checkout -b feature/AmazingFeature`)
3. Закоммитьте изменения (`git commit -m 'Add AmazingFeature'`)
4. Отправьте в ветку (`git push origin feature/AmazingFeature`)
5. Откройте Pull Request

---

## 📝 Лицензия

MIT License - см. файл [LICENSE](LICENSE)

---

## 📞 Контакты

- **GitHub:** https://github.com/PILIGRIM76
- **Issues:** https://github.com/PILIGRIM76/MT5Projekt-Clean/issues
- **Releases:** https://github.com/PILIGRIM76/MT5Projekt-Clean/releases

---

## ⚠️ Предупреждение о рисках

**Торговля на финансовых рынках сопряжена с высоким уровнем риска.**

- Тестируйте стратегию на демо-счёте минимум 30 дней
- Не используйте деньги, которые не готовы потерять
- Прошлые результаты не гарантируют будущую прибыль

---

**Удачной торговли! 🚀**

*Последнее обновление: 25 марта 2026*
