# 🚀 Genesis Trading System

**Версия:** 1.0.0  
**Дата:** 23 февраля 2026  
**Статус:** Production Ready ✅

---

## 📋 Описание

Genesis Trading System - это продвинутая AI-торговая система для MetaTrader 5, использующая машинное обучение, NLP и генетическое программирование для автоматической торговли на финансовых рынках.

### Основные возможности:

- 🤖 **AI-модели:** LightGBM, LSTM, Transformer для прогнозирования
- 📊 **Классические стратегии:** Breakout, Mean Reversion, MA Crossover
- 🧬 **Генетическое программирование:** Автоматическая генерация торговых правил
- 📰 **NLP анализ:** Обработка новостей и настроений рынка
- 🎯 **Умное управление рисками:** Динамическое управление позициями
- 📈 **Сканер рынка:** Автоматический поиск торговых возможностей
- 🌐 **Web Dashboard:** Мониторинг в реальном времени

---

## 📦 Установка

### Для пользователей (Windows):

1. **Скачай установщик:**
   ```
   installer_output/GenesisTrading_Setup_v1.0.0.exe
   ```

2. **Запусти установщик** и следуй инструкциям

3. **Настрой конфигурацию:**
   ```
   C:\Program Files\Genesis Trading System\configs\settings.json
   ```
   
   Измени:
   - `MT5_LOGIN` - твой логин MT5
   - `MT5_PASSWORD` - твой пароль MT5
   - `MT5_SERVER` - твой сервер MT5
   - `MT5_PATH` - путь к terminal64.exe

4. **Запусти программу** из меню Пуск или Desktop

### Для разработчиков:

1. **Клонируй репозиторий:**
   ```bash
   git clone https://github.com/PILIGRIM76/MT5Projekt-Clean.git
   cd MT5Projekt-Clean
   ```

2. **Создай виртуальное окружение:**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Установи зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Настрой конфигурацию:**
   ```bash
   copy configs\settings.example.json configs\settings.json
   notepad configs\settings.json
   ```

5. **Запусти систему:**
   ```bash
   python main_pyside.py
   ```

---

## 🔧 Сборка установщика

### Требования:

- Python 3.14+
- PyInstaller 6.19+
- Inno Setup 6+

### Шаги:

1. **Собери EXE:**
   ```bash
   pyinstaller genesis_trading.spec --clean --noconfirm
   ```

2. **Создай установщик:**
   ```bash
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer_script.iss
   ```

3. **Установщик будет в:**
   ```
   installer_output/GenesisTrading_Setup_v1.0.0.exe
   ```

Подробнее: [BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md)

---

## 📚 Документация

- **[QUICK_START.md](QUICK_START.md)** - Быстрый старт для пользователей
- **[HOW_TO_RUN.md](HOW_TO_RUN.md)** - Подробная инструкция по запуску
- **[BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md)** - Инструкция по сборке
- **[TROUBLESHOOTING_PROMPT.md](TROUBLESHOOTING_PROMPT.md)** - Решение проблем
- **[QUICK_FIX_GUIDE.md](QUICK_FIX_GUIDE.md)** - Быстрые исправления
- **[RETRAIN_INSTRUCTIONS.md](RETRAIN_INSTRUCTIONS.md)** - Переобучение моделей
- **[FINAL_BUILD_REPORT.md](FINAL_BUILD_REPORT.md)** - Отчёт о финальной сборке

---

## 🎯 Системные требования

### Минимальные:
- Windows 10/11 (64-bit)
- 8 GB RAM
- 10 GB свободного места
- MetaTrader 5 установлен
- Интернет-соединение

### Рекомендуемые:
- Windows 11 (64-bit)
- 16 GB RAM
- 20 GB свободного места (для AI моделей)
- SSD диск
- Стабильное интернет-соединение

---

## ⚙️ Конфигурация

### Основные параметры:

```json
{
  "MT5_LOGIN": "ВАШ_ЛОГИН",
  "MT5_PASSWORD": "ВАШ_ПАРОЛЬ",
  "MT5_SERVER": "ВАШ_СЕРВЕР",
  "MT5_PATH": "C:/Program Files/MetaTrader 5/terminal64.exe",
  
  "RISK_PERCENTAGE": 0.5,
  "MAX_OPEN_POSITIONS": 5,
  "STOP_LOSS_ATR_MULTIPLIER": 3.5,
  "RISK_REWARD_RATIO": 2.5,
  
  "DATABASE_FOLDER": "./database",
  "HF_MODELS_CACHE_DIR": "F:\\ai_models"
}
```

Полная конфигурация: `configs/settings.example.json`

---

## 🚦 Быстрый старт

1. **Установи программу** (см. раздел Установка)
2. **Настрой MT5 credentials** в `settings.json`
3. **Запусти программу**
4. **Дождись загрузки AI моделей** (первый запуск ~5-10 минут)
5. **Проверь подключение к MT5** в статус-баре
6. **Запусти сканирование рынка** (кнопка "Start Scan")
7. **Мониторь сигналы** во вкладке "Signals"

⚠️ **ВАЖНО:** Тестируй на демо-счёте минимум 30 дней!

---

## 📊 Структура проекта

```
MT5Projekt-Clean/
├── src/                      # Исходный код
│   ├── core/                 # Ядро системы
│   ├── ml/                   # ML модели
│   ├── strategies/           # Торговые стратегии
│   ├── data/                 # Провайдеры данных
│   ├── analysis/             # Анализ рынка
│   ├── risk/                 # Управление рисками
│   ├── gui/                  # Графический интерфейс
│   └── web/                  # Web сервер
├── configs/                  # Конфигурационные файлы
├── assets/                   # Ресурсы (иконки, звуки)
├── installer_output/         # Готовый установщик
├── main_pyside.py           # Точка входа
├── genesis_trading.spec     # PyInstaller конфиг
├── installer_script.iss     # Inno Setup скрипт
└── requirements.txt         # Python зависимости
```

---

## 🔍 Основные компоненты

### 1. Trading System (`src/core/trading_system.py`)
Главный оркестратор системы, управляет всеми компонентами.

### 2. Model Factory (`src/ml/model_factory.py`)
Создание и обучение ML моделей (LightGBM, LSTM, Transformer).

### 3. Strategy Loader (`src/strategies/strategy_loader.py`)
Загрузка и управление торговыми стратегиями.

### 4. Risk Engine (`src/risk/risk_engine.py`)
Управление рисками и размером позиций.

### 5. Market Screener (`src/analysis/market_screener.py`)
Сканирование рынка и поиск возможностей.

### 6. NLP Processor (`src/analysis/nlp_processor.py`)
Анализ новостей и настроений.

---

## 🛠️ Технологии

- **Python 3.14** - Основной язык
- **PySide6** - GUI фреймворк
- **PyTorch** - Deep Learning
- **LightGBM** - Gradient Boosting
- **Transformers** - NLP модели
- **MetaTrader5** - Торговая платформа
- **SQLite** - База данных
- **FAISS** - Vector DB
- **FastAPI** - Web API

---

## ⚠️ Предупреждения

1. **Торговля сопряжена с рисками** - можешь потерять весь капитал
2. **Тестируй на демо** минимум 30 дней перед реальной торговлей
3. **Не инвестируй больше**, чем можешь позволить себе потерять
4. **Система не гарантирует прибыль** - прошлые результаты не гарантируют будущих
5. **Используй только на демо-счетах** для обучения и тестирования

---

## 📝 Лицензия

Этот проект предоставляется "как есть" для образовательных целей.

См. [LICENSE](LICENSE) для деталей.

---

## 🆘 Поддержка

### GitHub:
- **Репозиторий:** https://github.com/PILIGRIM76/MT5Projekt-Clean
- **Issues:** https://github.com/PILIGRIM76/MT5Projekt-Clean/issues
- **Releases:** https://github.com/PILIGRIM76/MT5Projekt-Clean/releases

### Документация:
- Проверь [TROUBLESHOOTING_PROMPT.md](TROUBLESHOOTING_PROMPT.md) для решения проблем
- Читай [QUICK_FIX_GUIDE.md](QUICK_FIX_GUIDE.md) для быстрых исправлений

---

## 🎉 Благодарности

Спасибо всем контрибьюторам и сообществу за поддержку!

---

## 📈 Статус проекта

- ✅ Стабильная версия 1.0.0
- ✅ Полностью рабочий установщик
- ✅ Протестировано на Windows 10/11
- ✅ Все зависимости включены
- ✅ GUI работает корректно
- ✅ AI модели загружаются

**Готово к использованию!** 🚀

---

**Удачной торговли! Помни: тестируй на демо!** 💰
