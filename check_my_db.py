#!/usr/bin/env python3
"""Проверка вашей базы данных Genesis"""

import sqlite3

db_path = "F:/Enjen/database/trading_system.db"

print("=" * 60)
print(f"  База данных: {db_path}")
print("=" * 60)
print()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Список таблиц
tables = [
    "trade_history",
    "candle_data",
    "trained_models",
    "strategy_performance",
    "active_directives",
    "news_articles",
    "entities",
    "relations",
    "trade_audit",
]

total = 0
for table in tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"  • {table}: {count:,} записей")
            total += count
    except Exception as e:
        print(f"  • {table}: не найдена")

print()
print(f"📈 ВСЕГО ЗАПИСЕЙ: {total:,}")
print("=" * 60)

# Детали по trade_history
print()
print("📊 Детали по trade_history:")
try:
    cursor.execute("SELECT COUNT(*) FROM trade_history")
    trades = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(profit) FROM trade_history")
    total_profit = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM trade_history WHERE profit > 0")
    wins = cursor.fetchone()[0]

    win_rate = (wins / trades * 100) if trades > 0 else 0

    print(f"  Сделок: {trades:,}")
    print(f"  Win Rate: {win_rate:.1f}%")
    print(f"  Total PnL: ${total_profit:,.2f}")
except Exception as e:
    print(f"  Ошибка: {e}")

# Детали по candle_data
print()
print("📊 Детали по candle_data:")
try:
    cursor.execute("SELECT COUNT(*) FROM candle_data")
    candles = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM candle_data")
    symbols = cursor.fetchone()[0]

    print(f"  Свечей: {candles:,}")
    print(f"  Символов: {symbols}")
except Exception as e:
    print(f"  Ошибка: {e}")

conn.close()
print()
print("=" * 60)
print("  ✅ Проверка завершена!")
print("=" * 60)
