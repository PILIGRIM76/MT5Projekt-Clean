#!/usr/bin/env python3
"""
Демонстрационный импорт тестовых данных в Genesis DB.
"""

import json
import random
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "F:/Enjen/database/trading_system.db"

print("=" * 60)
print("  Демонстрационный импорт данных")
print("=" * 60)
print()

# Подключение к БД
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Генерация тестовых сделок
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
strategies = ["DemoStrategy", "MLStrategy", "TrendFollower"]

print("📊 Генерация 50 тестовых сделок...")

for i in range(50):
    symbol = random.choice(symbols)
    strategy = random.choice(strategies)
    is_buy = random.choice([True, False])

    open_price = random.uniform(100, 50000)
    close_price = open_price * (1 + random.uniform(-0.05, 0.1))
    volume = random.uniform(0.1, 10)
    profit = (close_price - open_price) * volume if is_buy else (open_price - close_price) * volume

    open_time = datetime.now() - timedelta(days=random.randint(1, 30), hours=random.randint(0, 23))
    close_time = open_time + timedelta(hours=random.randint(1, 48))

    trade_data = {
        "ticket": 10000 + i,
        "symbol": symbol,
        "strategy": strategy,
        "trade_type": "BUY" if is_buy else "SELL",
        "volume": volume,
        "price_open": open_price,
        "price_close": close_price,
        "time_open": open_time.isoformat(),
        "time_close": close_time.isoformat(),
        "profit": profit,
        "timeframe": "H1",
        "xai_data": None,
        "market_regime": "Trend",
        "news_sentiment": random.uniform(-0.5, 0.5),
        "volatility_metric": random.uniform(0.1, 0.3),
    }

    cursor.execute(
        """
        INSERT OR REPLACE INTO trade_history (
            ticket, symbol, strategy, trade_type, volume,
            price_open, price_close, time_open, time_close,
            profit, timeframe, market_regime, news_sentiment, volatility_metric
        ) VALUES (
            :ticket, :symbol, :strategy, :trade_type, :volume,
            :price_open, :price_close, :time_open, :time_close,
            :profit, :timeframe, :market_regime, :news_sentiment, :volatility_metric
        )
    """,
        trade_data,
    )

conn.commit()

# Проверка результата
cursor.execute("SELECT COUNT(*) FROM trade_history")
total_trades = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM trade_history WHERE strategy = 'DemoStrategy'")
demo_trades = cursor.fetchone()[0]

cursor.execute("SELECT SUM(profit) FROM trade_history WHERE strategy = 'DemoStrategy'")
demo_profit = cursor.fetchone()[0] or 0

print()
print("=" * 60)
print("  ✅ Импорт завершен!")
print("=" * 60)
print()
print(f"📊 Статистика:")
print(f"  • Всего сделок в БД: {total_trades:,}")
print(f"  • Импортировано (Demo): {demo_trades}")
print(f"  • PnL импортированных: ${demo_profit:,.2f}")
print()
print("📈 Данные сразу доступны:")
print(f"  • В виджете 'История Сделок'")
print(f"  • На вкладке '🗄️ Базы Данных'")
print()
print("=" * 60)

conn.close()
