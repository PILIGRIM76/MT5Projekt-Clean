"""
Скрипт для проверки доступности BITCOIN в MT5
"""
import MetaTrader5 as mt5
from pathlib import Path
import json

# Загружаем конфигурацию
config_path = Path("configs/settings.json")
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Инициализация MT5
print("Подключение к MT5...")
if not mt5.initialize(
    path=config.get("MT5_PATH"),
    login=int(config.get("MT5_LOGIN")),
    password=config.get("MT5_PASSWORD"),
    server=config.get("MT5_SERVER")
):
    print(f"Ошибка подключения: {mt5.last_error()}")
    exit(1)

print(f"Подключено к: {config.get('MT5_SERVER')}")
print(f"Аккаунт: {config.get('MT5_LOGIN')}")
print()

# Проверяем BITCOIN
symbol = "BITCOIN"
print(f"Проверка символа: {symbol}")
print("="*60)

# Получаем информацию о символе
symbol_info = mt5.symbol_info(symbol)

if symbol_info is None:
    print(f"❌ Символ {symbol} НЕ НАЙДЕН на брокере")
    print()
    print("Возможные причины:")
    print("1. Брокер не предоставляет этот инструмент")
    print("2. Неправильное название символа")
    print("3. Символ не добавлен в Market Watch")
    print()
    print("Попробуйте найти правильное название:")
    
    # Ищем похожие символы
    all_symbols = mt5.symbols_get()
    bitcoin_like = [s.name for s in all_symbols if 'BTC' in s.name.upper() or 'BITCOIN' in s.name.upper()]
    
    if bitcoin_like:
        print(f"\nНайдены похожие символы ({len(bitcoin_like)}):")
        for s in bitcoin_like[:10]:  # Показываем первые 10
            print(f"  - {s}")
    else:
        print("\nПохожие символы не найдены")
        print("Ваш брокер может не поддерживать криптовалюты")
else:
    print(f"✓ Символ {symbol} НАЙДЕН")
    print(f"  Название: {symbol_info.name}")
    print(f"  Описание: {symbol_info.description}")
    print(f"  Видимость: {symbol_info.visible}")
    print(f"  Режим торговли: {symbol_info.trade_mode}")
    print(f"  Минимальный лот: {symbol_info.volume_min}")
    print(f"  Максимальный лот: {symbol_info.volume_max}")
    
    # Проверяем, можно ли торговать
    if symbol_info.trade_mode == 0:
        print("\n⚠ ВНИМАНИЕ: Торговля ОТКЛЮЧЕНА для этого символа")
    elif symbol_info.trade_mode == 4:
        print("\n✓ Торговля РАЗРЕШЕНА (Full Access)")
    
    # Получаем последний тик
    tick = mt5.symbol_info_tick(symbol)
    if tick:
        print(f"\nПоследний тик:")
        print(f"  Bid: {tick.bid}")
        print(f"  Ask: {tick.ask}")
        print(f"  Время: {tick.time}")
    else:
        print("\n❌ Не удалось получить тик (рынок закрыт?)")

mt5.shutdown()
print("\n" + "="*60)
