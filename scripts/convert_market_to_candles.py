#!/usr/bin/env python3
"""
Конвертация market_data в candle_data для обучения.
Переносит исторические данные из market_data в candle_data.
"""

import logging
import sqlite3
from datetime import datetime

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "F:/Enjen/database/trading_system.db"


def convert_market_data_to_candles():
    """Конвертация market_data в candle_data."""
    logger.info("=" * 70)
    logger.info("  КОНВЕРТАЦИЯ market_data → candle_data")
    logger.info("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Проверяем market_data
    cursor.execute("SELECT COUNT(*) FROM market_data")
    total_market = cursor.fetchone()[0]
    logger.info(f"📊 market_data: {total_market:,} записей")

    if total_market == 0:
        logger.error("❌ market_data пуста!")
        conn.close()
        return

    # 2. Получаем уникальные символы
    cursor.execute("SELECT DISTINCT symbol FROM market_data")
    symbols = [row[0] for row in cursor.fetchall()]
    logger.info(f"📋 Символы: {', '.join(symbols)}")

    # 3. Создаём candle_data если не существует
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS candle_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL DEFAULT 'D1',
            timestamp TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            tick_volume REAL,
            spread REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, timeframe, timestamp)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candle_symbol ON candle_data(symbol)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candle_timeframe ON candle_data(timeframe)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candle_timestamp ON candle_data(timestamp)")

    # 4. Конвертация
    total_converted = 0
    for symbol in symbols:
        logger.info(f"\n🔄 Конвертация {symbol}...")

        # Загружаем данные
        df = pd.read_sql_query(
            "SELECT timestamp, open, high, low, close, volume FROM market_data WHERE symbol = ? ORDER BY timestamp",
            conn,
            params=(symbol,),
        )

        if df.empty:
            logger.warning(f"⚠ Нет данных для {symbol}")
            continue

        logger.info(f"  Загружено {len(df):,} записей")

        # Конвертация в candle_data формат
        inserted = 0
        for _, row in df.iterrows():
            try:
                # Конвертация timestamp в unix timestamp
                ts = row["timestamp"]
                if isinstance(ts, str):
                    ts = int(pd.to_datetime(ts).timestamp())
                elif isinstance(ts, (int, float)):
                    if ts > 1e12:  # milliseconds
                        ts = int(ts / 1000)
                    else:
                        ts = int(ts)

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO candle_data (
                        symbol, timeframe, timestamp, open, high, low, close, volume, tick_volume
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        "D1",  # Daily timeframe
                        ts,
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        int(row.get("volume", 0)),
                        int(row.get("volume", 0)),  # tick_volume = volume для исторических данных
                    ),
                )
                inserted += 1
            except Exception as e:
                logger.debug(f"  Пропуск: {e}")

        logger.info(f"  ✅ Конвертировано {inserted:,} записей")
        total_converted += inserted

    conn.commit()

    # 5. Итоговый отчёт
    logger.info("\n" + "=" * 70)
    logger.info("  ИТОГОВЫЙ ОТЧЁТ")
    logger.info("=" * 70)

    cursor.execute("SELECT COUNT(*) FROM candle_data")
    total_candles = cursor.fetchone()[0]
    logger.info(f"✅ candle_data: {total_candles:,} записей")

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM candle_data")
    symbols_count = cursor.fetchone()[0]
    logger.info(f"✅ Символов: {symbols_count}")

    cursor.execute("SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp) FROM candle_data GROUP BY symbol")
    for symbol, count, min_ts, max_ts in cursor.fetchall():
        logger.info(f"  • {symbol}: {count:,} баров ({min_ts} - {max_ts})")

    logger.info("=" * 70)
    logger.info(f"✅ Конвертация завершена! {total_converted:,} записей добавлено")
    logger.info("=" * 70)

    conn.close()


if __name__ == "__main__":
    convert_market_data_to_candles()
