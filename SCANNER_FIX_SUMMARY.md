# Исправление проблемы со сканером рынка

## Проблема
Данные в таблице сканера рынка появлялись на секунду и исчезали.

## Найденная причина
Обнаружено **двойное и тройное подключение** сигналов:

### Проблема 1: Дублирующее подключение в main_pyside.py
- **Строка 2061**: `self.bridge.market_scan_updated.connect(self.control_center_tab.update_market_table)` (УДАЛЕНО)
- **Строка 47 в control_center_widget.py**: То же подключение через `_connect_signals()` (правильно)

### Проблема 2: Двойная отправка сигнала в trading_system.py
- **Строка 640**: `self.market_scan_updated.emit(gui_data_list)` - отправка через core_system
- **Строка 642**: `self.bridge.market_scan_updated.emit(gui_data_list)` - дублирующая отправка (УДАЛЕНО)
- **Результат**: Сигнал отправлялся дважды, так как core_system.market_scan_updated уже подключен к bridge.market_scan_updated в PySideTradingSystem (строка 457)

### Итоговая проблема:
Данные отправлялись **4 раза**:
1. `core_system.market_scan_updated.emit()` → `bridge.market_scan_updated` (через подключение)
2. `bridge.market_scan_updated.emit()` (дубликат)
3. Каждый из этих сигналов шел в `control_center_tab.update_market_table` дважды

Это вызывало конфликты и перезапись данных.

## Выполненные исправления

### 1. Удалено дублирующее подключение (main_pyside.py, строка 2061)
```python
# БЫЛО:
self.bridge.market_scan_updated.connect(self.control_center_tab.update_market_table)

# СТАЛО:
# ИСПРАВЛЕНИЕ: Удалена дублирующая связь
# Эта связь уже установлена в control_center_widget.py:47
```

### 2. Удалена двойная отправка сигнала (trading_system.py, строки 640-642)
```python
# БЫЛО:
self.market_scan_updated.emit(gui_data_list)
if self.bridge:
    self.bridge.market_scan_updated.emit(gui_data_list)  # Дубликат!

# СТАЛО:
self.market_scan_updated.emit(gui_data_list)
# Сигнал автоматически пробрасывается в bridge через подключение
```

### 3. Добавлено подключение trading_signals_updated (main_pyside.py, строка 458)
```python
self.core_system.trading_signals_updated.connect(self.bridge.trading_signals_updated)
```

### 4. Добавлено детальное логирование (control_center_widget.py)
Добавлены логи с префиксом `[ControlCenter-Scanner]` для отслеживания:
- Количества получаемых элементов
- Режима отображения (рыночные данные / торговые сигналы)
- Количества обработанных элементов
- Количества установленных строк в таблице

### 5. Ранее выполненные исправления (из предыдущей сессии)
- Добавлена проверка на пустые данные в `update_market_scanner_view`
- Улучшена инициализация таблицы с чередующимися цветами
- Исправлена конвертация numpy типов в Python типы

## Как проверить исправление

### Шаг 1: Перезапустите систему
```cmd
python main_pyside.py
```

### Шаг 2: Откройте вкладку "Сканер Рынка"
Данные должны появиться и оставаться в таблице.

### Шаг 3: Проверьте логи
Ищите сообщения с префиксами:
- `[GUI-Scanner]` - обновления основной таблицы сканера
- `[ControlCenter-Scanner]` - обновления таблицы в Control Center
- `[GenericTableModel]` - обновления модели данных

Пример правильных логов:
```
INFO - [GUI-Scanner] ===== ВЫЗОВ update_market_scanner_view с 20 элементами =====
INFO - [GUI-Scanner] Обновление сканера рынка: 20 символов
INFO - [GUI-Scanner] Подготовлено 20 строк для таблицы
INFO - [GUI-Scanner] Модель таблицы обновлена с 20 строками
INFO - [GenericTableModel] update_data вызван с 20 строками
INFO - [ControlCenter-Scanner] ===== ВЫЗОВ update_market_table с 20 элементами =====
INFO - [ControlCenter-Scanner] Режим рыночных данных, обработка 20 элементов
INFO - [ControlCenter-Scanner] Обработано 20 элементов
INFO - [ControlCenter-Scanner] Установлено строк в таблице: 20
```

### Шаг 4: Проверьте обе вкладки
1. **Вкладка "Сканер Рынка"** (правая панель) - должна показывать топ символов с оценками
2. **Вкладка "Дашборд"** в Control Center (левая панель) - должна показывать рыночные данные

## Известные проблемы (не связанные со сканером)

### 1. Модели BITCOIN и USDJPY несовместимы ✅ ИСПРАВЛЕНО
**Проблема**: LSTM модели ожидают 24 признака, но получают 20.

**Решение**: Модели успешно удалены из базы данных (5387 моделей).

**Следующие шаги**:
1. Запустите систему: `python main_pyside.py`
2. R&D цикл автоматически переобучит модели (каждые 5 минут)
3. Новые модели будут использовать 20 признаков (без KG)

Для переобучения других символов используйте:
```cmd
python retrain_symbols_simple.py SYMBOL1 SYMBOL2
```

Подробности в файле `RETRAIN_INSTRUCTIONS.md`.

### 2. Рынок закрыт
**Проблема**: Ордера не исполняются (retcode 10018 - Market closed).

**Причина**: Торговля на выходных/праздниках недоступна.

**Решение**: Дождитесь открытия рынка в понедельник.

## Архитектура подключений сигналов

```
trading_system.market_scan_updated
    ↓
bridge.market_scan_updated
    ↓
    ├─→ main_window.update_market_scanner_view (вкладка "Сканер Рынка")
    └─→ control_center_widget.update_market_table (вкладка "Дашборд")
```

Каждый сигнал должен быть подключен **только один раз** к каждому получателю.

## Статус
✅ Исправление применено
⏳ Требуется перезапуск системы для проверки
