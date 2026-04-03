#!/usr/bin/env python3
"""
Проверка базы данных на полноту данных для обучения.
Показывает какие данные доступны и используются ли они.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "F:/Enjen/database/trading_system.db"


def check_database():
    """Полная проверка базы данных."""
    logger.info("=" * 70)
    logger.info("  ПРОВЕРКА БАЗЫ ДАННЫХ GENESIS TRADING SYSTEM")
    logger.info("=" * 70)

    if not Path(DB_PATH).exists():
        logger.error(f"❌ База данных не найдена: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Список таблиц
    logger.info("\n📋 ТАБЛИЦЫ В БАЗЕ ДАННЫХ:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        logger.info(f"  • {table}: {count:,} записей")

    # 2. Проверка candle_data (используется для обучения)
    logger.info("\n🕯️ ДАННЫЕ СВЕЧЕЙ (candle_data):")
    cursor.execute("SELECT COUNT(*) FROM candle_data")
    total_candles = cursor.fetchone()[0]
    logger.info(f"  Всего свечей: {total_candles:,}")

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM candle_data")
    symbols_count = cursor.fetchone()[0]
    logger.info(f"  Символов: {symbols_count}")

    cursor.execute("SELECT DISTINCT symbol FROM candle_data ORDER BY symbol")
    symbols = [row[0] for row in cursor.fetchall()]
    logger.info(f"  Список символов: {', '.join(symbols)}")

    cursor.execute("SELECT DISTINCT timeframe FROM candle_data")
    timeframes = [row[0] for row in cursor.fetchall()]
    logger.info(f"  Таймфреймы: {', '.join(map(str, timeframes))}")

    # Данные по каждому символу
    logger.info("\n  📊 Детализация по символам:")
    for symbol in symbols:
        cursor.execute(
            "SELECT timeframe, COUNT(*), MIN(timestamp), MAX(timestamp) FROM candle_data WHERE symbol = ? GROUP BY timeframe",
            (symbol,),
        )
        for tf, count, min_ts, max_ts in cursor.fetchall():
            logger.info(f"    {symbol} ({tf}): {count:,} баров ({min_ts} - {max_ts})")

    # 3. Проверка market_data (НЕ используется для обучения!)
    logger.info("\n📈 ИСТОРИЧЕСКИЕ РЫНОЧНЫЕ ДАННЫЕ (market_data):")
    cursor.execute("SELECT COUNT(*) FROM market_data")
    total_market = cursor.fetchone()[0]
    logger.info(f"  Всего записей: {total_market:,}")

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM market_data")
    market_symbols = cursor.fetchone()[0]
    logger.info(f"  Символов: {market_symbols}")

    cursor.execute("SELECT DISTINCT source FROM market_data")
    sources = [row[0] for row in cursor.fetchall()]
    logger.info(f"  Источники: {', '.join(sources)}")

    cursor.execute("SELECT DISTINCT symbol FROM market_data ORDER BY symbol")
    market_symbols_list = [row[0] for row in cursor.fetchall()]
    logger.info(f"  Список символов: {', '.join(market_symbols_list)}")

    # Данные по каждому символу
    logger.info("\n  📊 Детализация по символам:")
    for symbol in market_symbols_list:
        cursor.execute(
            "SELECT source, COUNT(*), MIN(timestamp), MAX(timestamp) FROM market_data WHERE symbol = ? GROUP BY source",
            (symbol,),
        )
        for source, count, min_ts, max_ts in cursor.fetchall():
            logger.info(f"    {symbol} ({source}): {count:,} записей ({min_ts} - {max_ts})")

    # 4. Проверка trade_history
    logger.info("\n💼 ИСТОРИЯ СДЕЛОК (trade_history):")
    cursor.execute("SELECT COUNT(*) FROM trade_history")
    total_trades = cursor.fetchone()[0]
    logger.info(f"  Всего сделок: {total_trades:,}")

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM trade_history")
    trade_symbols = cursor.fetchone()[0]
    logger.info(f"  Символов: {trade_symbols}")

    # 5. Проверка trained_models
    logger.info("\n🤖 ОБУЧЕННЫЕ МОДЕЛИ (trained_models):")
    cursor.execute("SELECT COUNT(*) FROM trained_models")
    total_models = cursor.fetchone()[0]
    logger.info(f"  Всего моделей: {total_models:,}")

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM trained_models")
    model_symbols = cursor.fetchone()[0]
    logger.info(f"  Символов с моделями: {model_symbols}")

    # 6. Проверка vector_db документов
    logger.info("\n🗃️ ВЕКТОРНАЯ БД (news_articles):")
    cursor.execute("SELECT COUNT(*) FROM news_articles")
    total_news = cursor.fetchone()[0]
    logger.info(f"  Всего новостей: {total_news:,}")

    # 7. ИТОГОВЫЙ ОТЧЁТ
    logger.info("\n" + "=" * 70)
    logger.info("  ИТОГОВЫЙ ОТЧЁТ")
    logger.info("=" * 70)

    # Проверяем какие символы есть в whitelist
    whitelist_symbols = [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCAD",
        "AUDUSD",
        "USDCHF",
        "NZDUSD",
        "EURJPY",
        "GBPJPY",
        "EURGBP",
        "AUDJPY",
        "XAUUSD",
        "XAGUSD",
        "EURCHF",
        "CADJPY",
        "AUDNZD",
        "GBPAUD",
        "BITCOIN",
    ]

    logger.info("\n✅ ДАННЫЕ ДЛЯ ОБУЧЕНИЯ (candle_data):")
    for symbol in whitelist_symbols:
        cursor.execute("SELECT COUNT(*) FROM candle_data WHERE symbol = ?", (symbol,))
        count = cursor.fetchone()[0]
        if count > 0:
            cursor.execute(
                "SELECT timeframe, COUNT(*) FROM candle_data WHERE symbol = ? GROUP BY timeframe",
                (symbol,),
            )
            tf_data = cursor.fetchall()
            tf_str = ", ".join([f"{tf}: {c:,}" for tf, c in tf_data])
            logger.info(f"  ✅ {symbol}: {count:,} баров ({tf_str})")
        else:
            logger.info(f"  ❌ {symbol}: НЕТ ДАННЫХ")

    logger.info("\n⚠️ ДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ (market_data - НЕ ИСПОЛЬЗУЮТСЯ!):")
    for symbol in market_symbols_list:
        cursor.execute("SELECT COUNT(*) FROM market_data WHERE symbol = ?", (symbol,))
        count = cursor.fetchone()[0]
        logger.info(f"  ⚠️ {symbol}: {count:,} записей (НЕ используются для обучения)")

    logger.info("\n🎯 РЕКОМЕНДАЦИИ:")
    missing_symbols = [s for s in whitelist_symbols if s not in symbols]
    if missing_symbols:
        logger.info(f"  ❌ Отсутствуют в candle_data: {', '.join(missing_symbols)}")
        logger.info("     → Загрузите данные через MT5 или импортируйте из market_data")

    if total_market > 0:
        logger.info(f"  ⚠️ market_data содержит {total_market:,} записей, но НЕ используется")
        logger.info("     → Рассмотрите конвертацию market_data в candle_data")

    if total_candles == 0:
        logger.info("  ❌ candle_data пуста!")
        logger.info("     → Запустите синхронизацию истории из MT5")

    logger.info("=" * 70)

    conn.close()


if __name__ == "__main__":
    check_database()
