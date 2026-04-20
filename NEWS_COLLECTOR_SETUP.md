# 📰 Настройка сбора новостей для Genesis Trading System

## ✅ Что сделано

### 1. Интеграция NewsCollector в главный цикл
Метод `_async_start_all_threads()` в `src/gui/trading_system_adapter.py` теперь запускает:
- **MLPredictor** (уже было)
- **SimpleMarketFeed** (уже было)
- **NewsCollector** (НОВОЕ 📰)

### 2. Автоматический запуск
NewsCollector запускается автоматически при старте системы, если в конфиге установлено:
```json
{
  "news_scheduler": {
    "enabled": true
  }
}
```

### 3. Интервал сбора
По умолчанию: **каждые 30 минут** (настраивается через `NEWS_COLLECTION_INTERVAL_MINUTES`)

## 🚀 Как проверить

### Способ 1: Через главный лог
Запустите систему и посмотрите лог:
```powershell
Get-Content "F:\Enjen\database\logs\genesis_system.log" -Encoding UTF8 -Wait -Tail 50
```

Ожидаемые сообщения:
```
📰 NewsCollector started
📰 Запуск первичного сбора новостей...
✅ Первичный сбор: X новостей
📰 Загрузка из Finnhub...
✅ Загружено X новостей из Finnhub
📰 Загрузка из NewsAPI...
✅ Загружено X новостей из NewsAPI
```

### Способ 2: Тестовый скрипт
Запустите изолированный тест:
```bash
python test_news.py
```

Это проверит:
1. Finnhub API
2. NewsAPI.org
3. RSS ленты
4. Анализ сентимента
5. Сохранение в БД

## 📊 Где смотреть результаты

### 1. База данных
Новости сохраняются в таблицу `news`:
```sql
SELECT * FROM news ORDER BY published_at DESC LIMIT 10;
```

### 2. VectorDB (когда подключите)
Новости можно искать через VectorDB search в GUI

### 3. Лог
`F:\Enjen\database\logs\genesis_system.log`

## ⚙️ Настройка

### Включить/выключить
В `configs/settings.json`:
```json
{
  "news_scheduler": {
    "enabled": true  // false = отключить
  }
}
```

### Изменить интервал
```json
{
  "news_scheduler": {
    "enabled": true,
    "interval_hours": 2  // Сбор каждые 2 часа
  }
}
```

### Настроить API ключи
В `.env`:
```env
FINNHUB_API_KEY=your_finnhub_key
NEWS_API_KEY=your_newsapi_key
```

## 🔧 Зависимости
Проверьте установленные пакеты:
```powershell
pip list | Select-String "feedparser|httpx|beautifulsoup4|nltk"
```

Если чего-то нет:
```bash
pip install feedparser httpx beautifulsoup4 nltk
python -c "import nltk; nltk.download('vader_lexicon'); nltk.download('punkt')"
```

## 🐛 Отладка

### Если новости не собираются
1. Проверьте API ключи в `.env`
2. Запустите `test_news.py` для изолированного теста
3. Проверьте логи на ошибки подключения

### Частые ошибки
| Ошибка | Решение |
|--------|---------|
| `Finnhub API ключ не настроен` | Добавьте `FINNHUB_API_KEY` в `.env` |
| `NewsAPI ключ не настроен` | Добавьте `NEWS_API_KEY` в `.env` |
| `Database not initialized` | Проверьте инициализацию БД в `core_system` |
| `Connection timeout` | Проверьте интернет-соединение |

## 📈 Что дальше?

1. **VectorDB интеграция** - сохранять новости в векторную БД для поиска
2. **Сентимент-трейдинг** - использовать сентимент для торговых сигналов
3. **News-based strategies** - стратегии на основе новостей
4. **Экономический календарь** - интеграция с ForexFactory, Investing.com

## 📞 Поддержка

Если что-то не работает:
1. Запустите `python test_news.py`
2. Пришлите вывод
3. Пришлите последние 50 строк лога
