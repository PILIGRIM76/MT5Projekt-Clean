#!/usr/bin/env python3
"""
Скрипт для проверки количества записей в базе данных Genesis.
"""

import sqlite3
from pathlib import Path

# Путь к базе данных
db_path = Path("database/trading_system.db")

if not db_path.exists():
    print(f"❌ База данных не найдена: {db_path}")
    exit(1)

print("=" * 60)
print(f"  Проверка базы данных: {db_path}")
print("=" * 60)
print()

# Подключение к базе
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Получение списка таблиц
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()

print(f"📊 Найдено таблиц: {len(tables)}")
print()

# Подсчет записей в каждой таблице
total_records = 0
for (table_name,) in tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"  • {table_name}: {count:,} записей")
            total_records += count
    except Exception as e:
        print(f"  • {table_name}: ошибка ({e})")

print()
print("=" * 60)
print(f"  ВСЕГО ЗАПИСЕЙ: {total_records:,}")
print("=" * 60)
print()

# Дополнительная статистика
print("📈 Детальная статистика:")
print()

# TradeHistory
try:
    cursor.execute("SELECT COUNT(*) FROM trade_history")
    trades_count = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(profit) FROM trade_history")
    total_profit = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM trade_history WHERE profit > 0")
    winning_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trade_history WHERE profit < 0")
    losing_trades = cursor.fetchone()[0]

    win_rate = (winning_trades / trades_count * 100) if trades_count > 0 else 0

    print(f"  Торговых сделок: {trades_count:,}")
    print(f"    - Выигрышных: {winning_trades:,} ({win_rate:.1f}%)")
    print(f"    - Проигрышных: {losing_trades:,}")
    print(f"    - Общий PnL: ${total_profit:,.2f}")
    print()
except Exception as e:
    print(f"  TradeHistory: {e}")

# CandleData
try:
    cursor.execute("SELECT COUNT(*) FROM candle_data")
    candles_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM candle_data")
    symbols_count = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM candle_data")
    time_range = cursor.fetchone()

    print(f"  Свечных данных: {candles_count:,}")
    print(f"    - Символов: {symbols_count}")
    print(f"    - Период: {time_range[0]} - {time_range[1]}")
    print()
except Exception as e:
    print(f"  CandleData: {e}")

# TrainedModel
try:
    cursor.execute("SELECT COUNT(*) FROM trained_models")
    models_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trained_models WHERE is_champion = 1")
    champions_count = cursor.fetchone()[0]

    print(f"  Обученных моделей: {models_count:,}")
    print(f"    - Чемпионов: {champions_count}")
    print()
except Exception as e:
    print(f"  TrainedModel: {e}")

conn.close()

print("=" * 60)
print("  ✅ Проверка завершена!")
print("=" * 60)
