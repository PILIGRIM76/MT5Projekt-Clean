#!/usr/bin/env python3
"""
Импорт данных из внешних торговых экосистем в Genesis Trading System.

Использование:
    python scripts/import_to_genesis.py --source freqtrade --path /path/to/db.sqlite
    python scripts/import_to_genesis.py --source csv --path trades.csv
"""

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


GENESIS_DB = "F:/Enjen/database/trading_system.db"


def import_from_freqtrade(freqtrade_db: str, genesis_db: str) -> int:
    """Импорт из Freqtrade."""
    logger.info("=" * 60)
    logger.info("  Импорт из Freqtrade")
    logger.info("=" * 60)

    if not Path(freqtrade_db).exists():
        logger.error(f"❌ Freqtrade DB не найдена: {freqtrade_db}")
        return 0

    freq_conn = sqlite3.connect(freqtrade_db)
    gen_conn = sqlite3.connect(genesis_db)
    gen_cur = gen_conn.cursor()

    try:
        # Чтение сделок
        cursor = freq_conn.execute("SELECT * FROM trades WHERE close_date IS NOT NULL")
        trades = cursor.fetchall()
        logger.info(f"Найдено {len(trades)} сделок")

        imported = 0
        for row in trades:
            try:
                # Схема Freqtrade
                col_map = {desc[0]: idx for idx, desc in enumerate(cursor.description)}

                trade_data = {
                    "ticket": row[col_map.get("id", 0)],
                    "symbol": row[col_map.get("pair", 1)].replace("_", ""),
                    "strategy": row[col_map.get("strategy", "Freqtrade")],
                    "trade_type": "SELL" if row[col_map.get("is_short", 0)] else "BUY",
                    "volume": float(row[col_map.get("amount", 0)] or 0),
                    "price_open": float(row[col_map.get("open_rate", 0)] or 0),
                    "price_close": float(row[col_map.get("close_rate", 0)] or 0),
                    "time_open": datetime.fromtimestamp(row[col_map.get("open_date_h", 0)] / 1000),
                    "time_close": datetime.fromtimestamp(row[col_map.get("close_date_h", 0)] / 1000),
                    "profit": float(row[col_map.get("close_profit_abs", 0)] or 0),
                }

                # Вставка в Genesis (INSERT OR REPLACE для обработки дубликатов)
                gen_cur.execute(
                    """
                    INSERT OR REPLACE INTO trade_history (
                        ticket, symbol, strategy, trade_type, volume,
                        price_open, price_close, time_open, time_close,
                        profit, timeframe
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        trade_data["ticket"],
                        trade_data["symbol"],
                        trade_data["strategy"],
                        trade_data["trade_type"],
                        trade_data["volume"],
                        trade_data["price_open"],
                        trade_data["price_close"],
                        trade_data["time_open"].isoformat(),
                        trade_data["time_close"].isoformat(),
                        trade_data["profit"],
                        "H1",
                    ),
                )

                imported += 1

            except Exception as e:
                logger.error(f"❌ Ошибка импорта сделки: {e}")

        gen_conn.commit()
        logger.info(f"✅ Импортировано {imported} сделок из Freqtrade")
        return imported

    finally:
        freq_conn.close()
        gen_conn.close()


def import_from_csv(csv_file: str, genesis_db: str) -> int:
    """Импорт из CSV."""
    logger.info("=" * 60)
    logger.info("  Импорт из CSV")
    logger.info("=" * 60)

    if not Path(csv_file).exists():
        logger.error(f"❌ CSV файл не найден: {csv_file}")
        return 0

    gen_conn = sqlite3.connect(genesis_db)
    gen_cur = gen_conn.cursor()

    try:
        df = pd.read_csv(csv_file)
        logger.info(f"Найдено {len(df)} записей")

        imported = 0
        for _, row in df.iterrows():
            try:
                gen_cur.execute(
                    """
                    INSERT OR REPLACE INTO trade_history (
                        ticket, symbol, strategy, trade_type, volume,
                        price_open, price_close, time_open, time_close,
                        profit, timeframe
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        int(row.get("ticket", row.get("id", 0))),
                        str(row.get("symbol", "UNKNOWN")),
                        str(row.get("strategy_name", "Imported")),
                        str(row.get("order_type", row.get("type", "BUY"))).upper(),
                        float(row.get("volume", row.get("amount", 0))),
                        float(row.get("open_price", row.get("price", 0))),
                        float(row.get("close_price", row.get("exit_price", 0))),
                        pd.to_datetime(row.get("open_time", row.get("entry_time"))).isoformat(),
                        pd.to_datetime(row.get("close_time", row.get("exit_time"))).isoformat(),
                        float(row.get("profit", row.get("pnl", 0))),
                        "H1",
                    ),
                )

                imported += 1

            except Exception as e:
                logger.error(f"❌ Ошибка импорта: {e}")

        gen_conn.commit()
        logger.info(f"✅ Импортировано {imported} записей из CSV")
        return imported

    finally:
        gen_conn.close()


def main():
    parser = argparse.ArgumentParser(description="Импорт данных в Genesis Trading System")
    parser.add_argument("--source", required=True, choices=["freqtrade", "csv"], help="Источник данных")
    parser.add_argument("--path", required=True, help="Путь к файлу/БД")
    parser.add_argument("--genesis-db", default=GENESIS_DB, help="Путь к БД Genesis")

    args = parser.parse_args()

    logger.info("\n" + "█" * 60)
    logger.info("  ИМПОРТ ДАННЫХ В GENESIS TRADING SYSTEM")
    logger.info("█" * 60 + "\n")

    if args.source == "freqtrade":
        imported = import_from_freqtrade(args.path, args.genesis_db)
    elif args.source == "csv":
        imported = import_from_csv(args.path, args.genesis_db)
    else:
        logger.error(f"❌ Неизвестный источник: {args.source}")
        return 1

    logger.info("\n" + "=" * 60)
    logger.info(f"  ИТОГ: Импортировано {imported} записей")
    logger.info("=" * 60 + "\n")

    return 0 if imported > 0 else 1


if __name__ == "__main__":
    exit(main())
