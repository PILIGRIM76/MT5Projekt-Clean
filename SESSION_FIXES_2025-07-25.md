# Исправления GUI — 25 июля 2025

**Коммит:** `1d6bad65` — fix: исправление GUI — настройки, графики, статус системы

---

## 1. Вкладка "Подключение MT5"
- **Баг:** `_find_env_file()` возвращала `str` вместо `Path`, вызывая `AttributeError` на `.parent`
- **Баг:** Путь к `settings.json` был `configs/configs/settings.json` (двойной)
- **Фикс:** Возврат `Path`, правильный путь `env_path.parent / "settings.json"`
- Поля Логин, Пароль, Сервер, Путь теперь отображаются корректно

## 2. Вкладка "API Ключи"
- **Баг:** Ключи читались только из `.env`, а хранились в `settings.json`
- **Фикс:** Чтение из обоих источников (`json_config` + `dotenv_values`), запись в оба через `write_config()`

## 3. Вкладка "Торговля"
- Карточки режимов (Консервативный, Стандартный, Агрессивный, YOLO) уменьшены в 2-3 раза
- Убрано дублирование заголовка "Режимы Торговли"
- Убрана лишняя вкладка "Интерфейс (GUI)" — тёмная тема по умолчанию
- Все виджеты с `background: transparent` для защиты от глобальной темы

## 4. Вкладка "Уведомления"
- **Баг:** Инструкции имели `background: #f0f0f0` (светлый) при тёмной теме → белый текст на светлом фоне
- **Фикс:** `background: #282a36` + цветная полоса слева (голубая для Telegram, зелёная для Email)
- Настройки мониторинга загружаются из `self.json_config` (актуальный settings.json), а не из Pydantic модели

## 5. AlertManager
- **Проблема:** `self.trading_system.alert_manager` нигде не создавался
- **Фикс:** Инициализация `AlertManager` в `PySideTradingSystem.__init__()` с `config` и `trading_system_ref`

## 6. HotReloadManager (вкладка "Обновления")
- **Проблема:** `_get_hot_reload_manager()` всегда возвращал `None`
- **Фикс:** Инициализация в `PySideTradingSystem._init_hot_reload_manager()`, добавлен `@property hot_reload_manager`

## 7. Статус системы
- **Баг:** Оркестратор и VectorDB показывали "ОСТАНОВЛЕН" до запуска системы
- **Фикс:** Все сервисы показывают статус на основе `core_system.running` + конфига

## 8. Основной график — подробности

### Проблема
Основной график не отображал свечи. Причины были многоуровневые:

1. **`CustomCandlestickItem(GraphicsObject)`** — рисовал через QPainter в координатах данных, но pyqtgraph передаёт QPainter в **экраных координатах** (view coordinates). Свечи сжимались в одну полосу.

2. **`BarGraphItem`** — не работает с Unix timestamps (1.7e9) в pyqtgraph 0.13.7. Ширина бара 500-2500 при диапазоне 360000 = <1 пикселя → невидимы.

3. **live_data.py** — `update_chart()` проверял `mw.trading_system.core_system.running` до запуска системы → график никогда не обновлялся.

### Что尝试овано (и почему не сработало)
| Подход | Результат | Причина |
|--------|-----------|---------|
| `GraphicsObject` + ручной `x_scale/y_scale` | Полоса | Двойное масштабирование |
| `GraphicsObject` без масштабирования | Пусто | QPainter в view coords, не data coords |
| `GraphicsObject` + `viewTransform()` | Пусто | ViewBox transform не применяется к GraphicsObject |
| `BarGraphItem` с width=500 | Пусто | 500/360000 = 0.14% = <1px |
| `BarGraphItem` с width=1800 | Пусто | Та же проблема с Unix timestamps |

### Рабочий подход
**`PlotDataItem` + `FillBetweenItem`** — доказано работает с любыми координатами.

Каждая свеча (100 баров = 800 элементов):
```
Фитиль:   PlotDataItem(x=[t, t], y=[low, high]) — вертикальная линия
Тело:     4× PlotDataItem (границы прямоугольника)
Заливка:  FillBetweenItem(fill_top, fill_bot, brush=color)
```

### Файлы графика
| Файл | Что делает |
|------|-----------|
| `src/gui/main_window_parts/charts.py` | `update_candle_chart()` — рисует свечи через PlotDataItem+FillBetweenItem |
| `src/gui/main_window_parts/panels.py` | `_candle_items = []` — список для удаления старых элементов |
| `src/gui/live_data.py` | `update_chart()` — берёт данные из MT5, проверяет `mt5.account_info()` |
| `src/gui/widgets/graph_widgets.py` | Упрощён (оставлен как заготовка) |

### Дополнительно
- График обновляется только при подключении MT5 (проверка `mt5.account_info() != None`)
- Добавлено логирование: `[Chart] Emitting`, `[GUI-Chart] update_candle_chart called`, `[GUI-Chart] Done`
- Тестовые скриншоты доказывают корректность отрисовки

---

## Файлы
| Файл | Изменения |
|------|-----------|
| `src/gui/settings_window.py` | _find_env_file, API ключи, мониторинг, удалена вкладка GUI |
| `src/gui/main_window.py` | Удалён theme_preview_requested |
| `src/gui/main_window_parts/charts.py` | update_candle_chart переписан на PlotDataItem+FillBetweenItem |
| `src/gui/main_window_parts/panels.py` | _candle_items вместо BarGraphItem |
| `src/gui/live_data.py` | Логирование chart, проверка MT5 перед обновлением |
| `src/gui/trading_modes_widget.py` | Компактные карточки, objectName, цвета |
| `src/gui/trading_system_adapter.py` | AlertManager + HotReloadManager инициализация |
| `src/gui/widgets/graph_widgets.py` | Упрощён (не используется напрямую) |
| `configs/settings.json` | Без изменений |
