# -*- coding: utf-8 -*-
"""
Проверка доступности всех символов в MT5
"""

import MetaTrader5 as mt5
from datetime import datetime

MT5_PATH = r"C:\Program Files\Alpari MT5\terminal64.exe"

SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "USDCHF", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "XAUUSD", "XAGUSD", "EURCHF",
    "CADJPY", "AUDNZD", "GBPAUD", "BITCOIN"
]

TIMEFRAMES = [
    (mt5.TIMEFRAME_M1, "M1"),
    (mt5.TIMEFRAME_M5, "M5"),
    (mt5.TIMEFRAME_M15, "M15"),
    (mt5.TIMEFRAME_H1, "H1"),
    (mt5.TIMEFRAME_H4, "H4"),
    (mt5.TIMEFRAME_D1, "D1"),
]

print("=" * 80)
print("ПРОВЕРКА ДОСТУПНОСТИ СИМВОЛОВ В MT5")
print("=" * 80)
print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# Подключение к MT5
print("\n🔌 Подключение к MT5...")
if not mt5.initialize(path=MT5_PATH):
    print(f"❌ Ошибка подключения: {mt5.last_error()}")
    exit(1)

print("✅ MT5 подключён")

# Получение информации о счёте
account_info = mt5.account_info()
if account_info:
    print(f"📊 Счёт: #{account_info.login}")
    print(f"📊 Сервер: {account_info.server}")
    print(f"📊 Тип счёта: {account_info.trade_mode}")
else:
    print("⚠️ Не удалось получить информацию о счёте")

print("\n" + "=" * 80)
print("ПРОВЕРКА СИМВОЛОВ")
print("=" * 80)

# Получение всех доступных символов
all_symbols = mt5.symbols_get()
if all_symbols:
    available_names = {s.name for s in all_symbols}
    print(f"\nВсего символов у брокера: {len(all_symbols)}")
else:
    print("❌ Не удалось получить список символов")
    available_names = set()

# Проверка каждого символа из списка
print(f"\n{'Символ':<15} {'Доступен':<10} {'Тип':<15} {'Видимость':<10}")
print("-" * 60)

results = []
for symbol in SYMBOLS:
    if symbol in available_names:
        # Получение детальной информации
        info = mt5.symbol_info(symbol)
        if info:
            is_visible = info.visible
            symbol_type = "Forex" if "USD" in symbol or "EUR" in symbol or "GBP" in symbol else "Crypto/Metal"
            
            # Попытка получить последнюю цену
            tick = mt5.symbol_info_tick(symbol)
            price = f"{tick.bid:.5f}" if tick else "N/A"
            
            results.append({
                'symbol': symbol,
                'available': True,
                'visible': is_visible,
                'type': symbol_type,
                'price': price
            })
            
            status = "✅" if is_visible else "⚠️ Скрыт"
            print(f"{symbol:<15} {status:<10} {symbol_type:<15} {'Да' if is_visible else 'Нет':<10}")
        else:
            results.append({
                'symbol': symbol,
                'available': True,
                'visible': False,
                'type': 'Unknown',
                'price': 'N/A'
            })
            print(f"{symbol:<15} {'✅':<10} {'Unknown':<15} {'Нет':<10}")
    else:
        results.append({
            'symbol': symbol,
            'available': False,
            'visible': False,
            'type': 'N/A',
            'price': 'N/A'
        })
        print(f"{symbol:<15} {'❌':<10} {'N/A':<15} {'N/A':<10}")

# Статистика
print("\n" + "=" * 80)
print("СТАТИСТИКА")
print("=" * 80)

available_count = sum(1 for r in results if r['available'])
visible_count = sum(1 for r in results if r['visible'])
unavailable_count = sum(1 for r in results if not r['available'])

print(f"\nДоступно символов: {available_count}/{len(SYMBOLS)}")
print(f"Видимых в Market Watch: {visible_count}")
print(f"Недоступно: {unavailable_count}")

if unavailable_count > 0:
    print(f"\n❌ Недоступные символы:")
    for r in results:
        if not r['available']:
            print(f"   • {r['symbol']}")

if visible_count < available_count:
    print(f"\n⚠️ Скрытые символы (требуют включения):")
    for r in results:
        if r['available'] and not r['visible']:
            print(f"   • {r['symbol']}")

# Проверка данных для доступных символов
print("\n" + "=" * 80)
print("ПРОВЕРКА ДАННЫХ (последние бары)")
print("=" * 80)

print(f"\n{'Символ':<12} {'Таймфрейм':<8} {'Баров':<10} {'Последняя цена':<15}")
print("-" * 55)

for symbol in SYMBOLS:
    if symbol in available_names:
        # Пробуем получить данные для H1
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 10)
        if rates is not None and len(rates) > 0:
            last_close = rates[-1]['close']
            print(f"{symbol:<12} {'H1':<8} {len(rates):<10} {last_close:.5f}")
        else:
            print(f"{symbol:<12} {'H1':<8} {'0':<10} ❌ Нет данных")

mt5.shutdown()

print("\n" + "=" * 80)
print("ПРОВЕРКА ЗАВЕРШЕНА")
print("=" * 80)
