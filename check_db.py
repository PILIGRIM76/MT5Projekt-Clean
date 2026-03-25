# -*- coding: utf-8 -*-
import sqlite3
from datetime import datetime

DB_PATH = r"F:\Enjen\database\trading_system.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("=" * 60)
print("ПРОВЕРКА БАЗЫ ДАННЫХ")
print("=" * 60)

# Список таблиц
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"\n📊 Таблицы ({len(tables)}):")
for table in tables:
    table_name = table[0]
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"  • {table_name}: {count} записей")

# Проверка candle_data
print("\n" + "=" * 60)
print("📈 СТАТИСТИКА CANDLE_DATA (ценовые данные)")
print("=" * 60)

try:
    cursor.execute("""
        SELECT symbol, timeframe, 
               MIN(timestamp) as first_date, 
               MAX(timestamp) as last_date,
               COUNT(*) as bars_count
        FROM candle_data 
        GROUP BY symbol, timeframe
        ORDER BY symbol, timeframe
    """)

    data = cursor.fetchall()
    if data:
        print(f"\n{'Символ':<12} {'Таймфрейм':<12} {'Баров':<12} {'Первая дата':<20} {'Последняя дата':<20}")
        print("-" * 80)
        for row in data:
            symbol, tf, first, last, count = row
            first_date = datetime.fromtimestamp(first).strftime('%Y-%m-%d %H:%M') if first else 'N/A'
            last_date = datetime.fromtimestamp(last).strftime('%Y-%m-%d %H:%M') if last else 'N/A'
            print(f"{symbol:<12} {tf:<12} {count:<12,} {first_date:<20} {last_date:<20}")
    else:
        print("\n❌ Таблица candle_data пуста!")
except sqlite3.OperationalError as e:
    print(f"\n❌ Таблица candle_data не существует: {e}")

# Проверка trades
print("\n" + "=" * 60)
print("💰 СТАТИСТИКА СДЕЛОК (trade_history)")
print("=" * 60)

try:
    cursor.execute("SELECT COUNT(*) FROM trade_history")
    total_trades = cursor.fetchone()[0]
    print(f"\nВсего сделок: {total_trades}")

    if total_trades > 0:
        # Проверка доступных колонок
        cursor.execute("PRAGMA table_info(trade_history)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"Колонки: {', '.join(columns)}")
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as winning,
                SUM(CASE WHEN profit <= 0 THEN 1 ELSE 0 END) as losing,
                SUM(profit) as total_profit,
                AVG(profit) as avg_profit
            FROM trade_history
        """)
        stats = cursor.fetchone()
        win_rate = (stats[1] / stats[0] * 100) if stats[0] > 0 else 0
        
        print(f"\nВыигрышных: {stats[1]} ({win_rate:.1f}%)")
        print(f"Убыточных: {stats[2]}")
        print(f"Общая прибыль: ${stats[3]:.2f}")
        print(f"Средняя сделка: ${stats[4]:.2f}")
        
        # Период - пробуем разные варианты
        time_col = None
        for col in ['time_close', 'close_time', 'time', 'timestamp', 'exit_time', 'created_at']:
            if col in columns:
                time_col = col
                break
        
        if time_col:
            cursor.execute(f"SELECT MIN({time_col}), MAX({time_col}) FROM trade_history WHERE {time_col} IS NOT NULL")
            period = cursor.fetchone()
            if period[0]:
                # Пробуем распарсить как строку или timestamp
                try:
                    if isinstance(period[0], (int, float)):
                        first_trade = datetime.fromtimestamp(period[0]).strftime('%Y-%m-%d')
                        last_trade = datetime.fromtimestamp(period[1]).strftime('%Y-%m-%d')
                    else:
                        # Строка формата YYYY-MM-DD HH:MM:SS
                        first_trade = str(period[0])[:10]
                        last_trade = str(period[1])[:10]
                    
                    print(f"\nПериод торговли: {first_trade} — {last_trade}")
                    
                    from datetime import datetime as dt
                    d1 = dt.strptime(first_trade, '%Y-%m-%d')
                    d2 = dt.strptime(last_trade, '%Y-%m-%d')
                    days = (d2 - d1).days
                    print(f"Длительность: {days} дней ({days/30:.1f} месяцев)")
                except Exception as e:
                    print(f"\n⚠️ Не удалось определить период: {e}")
        else:
            print("\n⚠️ Не найдена колонка времени для определения периода")
    else:
        print("\n❌ Сделок нет в базе данных")
except sqlite3.OperationalError as e:
    print(f"\n❌ Ошибка: {e}")

# Проверка trained_models
print("\n" + "=" * 60)
print("🤖 ОБУЧЕННЫЕ МОДЕЛИ (trained_models)")
print("=" * 60)

cursor.execute("SELECT COUNT(*) FROM trained_models")
total_models = cursor.fetchone()[0]
print(f"\nВсего моделей: {total_models}")

if total_models > 0:
    cursor.execute("""
        SELECT symbol, COUNT(*) as model_count
        FROM trained_models
        GROUP BY symbol
        ORDER BY model_count DESC
    """)
    models_by_symbol = cursor.fetchall()
    print(f"\n{'Символ':<15} {'Моделей':<10}")
    print("-" * 30)
    for row in models_by_symbol:
        print(f"{row[0]:<15} {row[1]:<10}")
else:
    print("\n❌ Обученных моделей нет")

conn.close()

print("\n" + "=" * 60)
print("ПРОВЕРКА ЗАВЕРШЕНА")
print("=" * 60)
