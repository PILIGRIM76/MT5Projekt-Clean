#!/usr/bin/env python3
"""
Импорт данных из внешних торговых экосистем в Genesis Trading System.

Поддерживаемые источники:
- Freqtrade (SQLite)
- Hummingbot (SQLite)
- Jesse AI (SQLite)
- OctoBot (SQLite)
- QuantConnect (CSV)
- Backtrader (CSV)
- Universal CSV

Использование:
    python import_external_data.py --source freqtrade --path /path/to/tradesv3.sqlite
    python import_external_data.py --source all --path /path/to/data
"""

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ExternalDataImporter:
    """Импорт данных из внешних торговых систем в Genesis."""

    def __init__(self, genesis_db_path: str):
        self.genesis_db_path = Path(genesis_db_path)
        self.stats = {
            "imported": 0,
            "skipped": 0,
            "errors": 0,
        }

        if not self.genesis_db_path.exists():
            logger.error(f"❌ База данных Genesis не найдена: {self.genesis_db_path}")
            raise FileNotFoundError(f"Genesis DB not found: {self.genesis_db_path}")

        logger.info(f"✅ Подключение к Genesis DB: {self.genesis_db_path}")

    def import_from_freqtrade(self, freqtrade_db_path: str) -> Dict[str, int]:
        """Импорт из Freqtrade."""
        logger.info("\n" + "=" * 60)
        logger.info("  Импорт из Freqtrade")
        logger.info("=" * 60)

        freqtrade_path = Path(freqtrade_db_path)
        if not freqtrade_path.exists():
            logger.error(f"❌ Freqtrade DB не найдена: {freqtrade_path}")
            self.stats["errors"] += 1
            return self.stats

        conn = sqlite3.connect(freqtrade_path)
        conn.row_factory = sqlite3.Row
        genesis_conn = sqlite3.connect(self.genesis_db_path)
        genesis_cursor = genesis_conn.cursor()

        try:
            # Чтение сделок из Freqtrade
            query = """
                SELECT * FROM trades
                WHERE close_date IS NOT NULL
                ORDER BY close_date DESC
            """

            freqtrade_cursor = conn.execute(query)
            trades_rows = freqtrade_cursor.fetchall()
            logger.info(f"Найдено {len(trades_rows)} сделок в Freqtrade")

            # Импорт в Genesis
            for row in trades_rows:
                try:
                    trade_data = {
                        "ticket": row["id"],
                        "symbol": row["pair"].replace("_", ""),
                        "order_type": "SELL" if row.get("is_short", False) else "BUY",
                        "volume": float(row["amount"] or 0),
                        "open_price": float(row["open_rate"] or 0),
                        "close_price": float(row["close_rate"] or 0),
                        "sl": float(row["stop_loss"] or 0) if row.get("stop_loss") else None,
                        "tp": float(row["take_profit"] or 0) if row.get("take_profit") else None,
                        "open_time": datetime.fromtimestamp(row["open_date_h"] / 1000) if row.get("open_date_h") else None,
                        "close_time": datetime.fromtimestamp(row["close_date_h"] / 1000) if row.get("close_date_h") else None,
                        "profit": float(row["close_profit_abs"] or 0),
                        "strategy_name": row.get("strategy", "Freqtrade"),
                        "model_type": "Freqtrade",
                        "metadata": json.dumps(
                            {
                                "source": "Freqtrade",
                                "freqtrade_id": row["id"],
                                "is_short": row.get("is_short", False),
                                "stake_amount": row.get("stake_amount"),
                                "stake_currency": row.get("stake_currency", "USDT"),
                                "exchange": row.get("exchange", "unknown"),
                                "fee_open": float(row["fee_open"] or 0),
                                "fee_close": float(row["fee_close"] or 0),
                                "exit_reason": row.get("exit_reason"),
                            }
                        ),
                    }

                    # Вставка в Genesis (с учетом реальной схемы таблицы)
                    genesis_cursor.execute(
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
                        {
                            "ticket": int(trade_data["ticket"]),
                            "symbol": str(trade_data["symbol"]),
                            "strategy": str(trade_data.get("strategy_name", "Imported")),
                            "trade_type": str(trade_data["order_type"]),
                            "volume": float(trade_data["volume"]),
                            "price_open": float(trade_data["open_price"]),
                            "price_close": float(trade_data["close_price"]),
                            "time_open": trade_data["open_time"].isoformat() if trade_data.get("open_time") else None,
                            "time_close": trade_data["close_time"].isoformat() if trade_data.get("close_time") else None,
                            "profit": float(trade_data["profit"]),
                            "timeframe": "H1",
                            "market_regime": "Unknown",
                            "news_sentiment": None,
                            "volatility_metric": None,
                        },
                    )

                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"❌ Ошибка импорта сделки {row['id']}: {e}")
                    self.stats["errors"] += 1

            genesis_conn.commit()
            logger.info(f"✅ Импортировано {self.stats['imported']} сделок из Freqtrade")

        except Exception as e:
            logger.error(f"❌ Ошибка импорта из Freqtrade: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()
            genesis_conn.close()

        return self.stats

    def import_from_hummingbot(self, hummingbot_db_path: str) -> Dict[str, int]:
        """Импорт из Hummingbot."""
        logger.info("\n" + "=" * 60)
        logger.info("  Импорт из Hummingbot")
        logger.info("=" * 60)

        db_path = Path(hummingbot_db_path)
        if not db_path.exists():
            logger.error(f"❌ Hummingbot DB не найдена: {db_path}")
            self.stats["errors"] += 1
            return self.stats

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        genesis_conn = sqlite3.connect(self.genesis_db_path)
        genesis_cursor = genesis_conn.cursor()

        try:
            # Пробуем разные названия таблиц
            table_names = ["TradeEntry", "trades", "Trade"]
            trades_rows = []

            for table_name in table_names:
                try:
                    query = f"SELECT * FROM {table_name}"
                    cursor = conn.execute(query)
                    trades_rows = cursor.fetchall()
                    logger.info(f"✓ Найдена таблица: {table_name}")
                    break
                except:
                    continue

            if not trades_rows:
                logger.info("⚠ Нет сделок для импорта")
                return self.stats

            logger.info(f"Найдено {len(trades_rows)} сделок")

            for row in trades_rows:
                try:
                    row_dict = dict(row)

                    trade_data = {
                        "ticket": row_dict.get("id", 0),
                        "symbol": row_dict.get("market", "").replace("-", ""),
                        "order_type": "SELL" if row_dict.get("trade_type", "").upper() == "SELL" else "BUY",
                        "volume": float(row_dict.get("amount", 0) or 0),
                        "open_price": float(row_dict.get("price", 0) or 0),
                        "close_price": float(row_dict.get("price", 0) or 0),
                        "open_time": (
                            datetime.fromtimestamp(row_dict.get("timestamp", 0) / 1000) if row_dict.get("timestamp") else None
                        ),
                        "close_time": (
                            datetime.fromtimestamp(row_dict.get("timestamp", 0) / 1000) if row_dict.get("timestamp") else None
                        ),
                        "profit": float(row_dict.get("pnl", 0) or 0),
                        "strategy_name": "Hummingbot",
                        "model_type": "Hummingbot",
                        "metadata": json.dumps(
                            {
                                "source": "Hummingbot",
                                "trade_id": row_dict.get("id"),
                                "order_id": row_dict.get("order_id"),
                                "exchange": row_dict.get("exchange", "unknown"),
                            }
                        ),
                    }

                    genesis_cursor.execute(
                        """
                        INSERT OR REPLACE INTO trade_history (
                            ticket, symbol, order_type, volume, open_price, close_price,
                            open_time, close_time, profit,
                            strategy_name, model_type, metadata
                        ) VALUES (
                            :ticket, :symbol, :order_type, :volume, :open_price, :close_price,
                            :open_time, :close_time, :profit,
                            :strategy_name, :model_type, :metadata
                        )
                    """,
                        trade_data,
                    )

                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"❌ Ошибка импорта: {e}")
                    self.stats["errors"] += 1

            genesis_conn.commit()
            logger.info(f"✅ Импортировано {self.stats['imported']} сделок из Hummingbot")

        except Exception as e:
            logger.error(f"❌ Ошибка импорта из Hummingbot: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()
            genesis_conn.close()

        return self.stats

    def import_from_jesse(self, jesse_db_path: str) -> Dict[str, int]:
        """Импорт из Jesse AI."""
        logger.info("\n" + "=" * 60)
        logger.info("  Импорт из Jesse AI")
        logger.info("=" * 60)

        db_path = Path(jesse_db_path)
        if not db_path.exists():
            logger.error(f"❌ Jesse DB не найдена: {db_path}")
            self.stats["errors"] += 1
            return self.stats

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        genesis_conn = sqlite3.connect(self.genesis_db_path)
        genesis_cursor = genesis_conn.cursor()

        try:
            query = "SELECT * FROM executed_orders"
            cursor = conn.execute(query)
            orders_rows = cursor.fetchall()
            logger.info(f"Найдено {len(orders_rows)} ордеров")

            for row in orders_rows:
                try:
                    row_dict = dict(row)

                    trade_data = {
                        "ticket": row_dict.get("id", 0),
                        "symbol": row_dict.get("symbol", "").replace("_", ""),
                        "order_type": row_dict.get("side", "buy").upper(),
                        "volume": float(row_dict.get("amount", 0) or 0),
                        "open_price": float(row_dict.get("price", 0) or 0),
                        "close_price": float(row_dict.get("price", 0) or 0),
                        "open_time": (
                            datetime.fromisoformat(row_dict.get("created_at", "")) if row_dict.get("created_at") else None
                        ),
                        "close_time": (
                            datetime.fromisoformat(row_dict.get("created_at", "")) if row_dict.get("created_at") else None
                        ),
                        "profit": float(row_dict.get("profit", 0) or 0),
                        "strategy_name": row_dict.get("strategy_name", "Jesse"),
                        "model_type": "Jesse",
                        "metadata": json.dumps(
                            {
                                "source": "Jesse",
                                "exchange": row_dict.get("exchange"),
                            }
                        ),
                    }

                    genesis_cursor.execute(
                        """
                        INSERT OR REPLACE INTO trade_history (
                            ticket, symbol, order_type, volume, open_price, close_price,
                            open_time, close_time, profit,
                            strategy_name, model_type, metadata
                        ) VALUES (
                            :ticket, :symbol, :order_type, :volume, :open_price, :close_price,
                            :open_time, :close_time, :profit,
                            :strategy_name, :model_type, :metadata
                        )
                    """,
                        trade_data,
                    )

                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"❌ Ошибка импорта: {e}")
                    self.stats["errors"] += 1

            genesis_conn.commit()
            logger.info(f"✅ Импортировано {self.stats['imported']} ордеров из Jesse")

        except Exception as e:
            logger.error(f"❌ Ошибка импорта из Jesse: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()
            genesis_conn.close()

        return self.stats

    def import_from_csv(self, csv_path: str) -> Dict[str, int]:
        """Импорт из CSV."""
        logger.info("\n" + "=" * 60)
        logger.info("  Импорт из CSV")
        logger.info("=" * 60)

        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.error(f"❌ CSV файл не найден: {csv_file}")
            self.stats["errors"] += 1
            return self.stats

        genesis_conn = sqlite3.connect(self.genesis_db_path)
        genesis_cursor = genesis_conn.cursor()

        try:
            df = pd.read_csv(csv_path)
            logger.info(f"Найдено {len(df)} записей")

            for _, row in df.iterrows():
                try:
                    trade_data = {
                        "ticket": int(row.get("ticket", row.get("id", 0))),
                        "symbol": str(row.get("symbol", "UNKNOWN")),
                        "order_type": str(row.get("order_type", "BUY")).upper(),
                        "volume": float(row.get("volume", row.get("amount", 0)) or 0),
                        "open_price": float(row.get("open_price", row.get("price", 0)) or 0),
                        "close_price": float(row.get("close_price", row.get("exit_price", 0)) or 0),
                        "open_time": pd.to_datetime(row.get("open_time", row.get("entry_time"))),
                        "close_time": pd.to_datetime(row.get("close_time", row.get("exit_time"))),
                        "profit": float(row.get("profit", row.get("pnl", 0)) or 0),
                        "strategy_name": str(row.get("strategy_name", "CSV")),
                        "model_type": str(row.get("model_type", "CSV")),
                        "metadata": json.dumps(
                            {
                                "source": "CSV Import",
                            }
                        ),
                    }

                    genesis_cursor.execute(
                        """
                        INSERT OR REPLACE INTO trade_history (
                            ticket, symbol, order_type, volume, open_price, close_price,
                            open_time, close_time, profit,
                            strategy_name, model_type, metadata
                        ) VALUES (
                            :ticket, :symbol, :order_type, :volume, :open_price, :close_price,
                            :open_time, :close_time, :profit,
                            :strategy_name, :model_type, :metadata
                        )
                    """,
                        trade_data,
                    )

                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"❌ Ошибка импорта: {e}")
                    self.stats["errors"] += 1

            genesis_conn.commit()
            logger.info(f"✅ Импортировано {self.stats['imported']} записей из CSV")

        except Exception as e:
            logger.error(f"❌ Ошибка импорта из CSV: {e}")
            self.stats["errors"] += 1

        finally:
            genesis_conn.close()

        return self.stats

    def import_from_all(self, data_dir: str) -> Dict[str, int]:
        """Импорт из всех источников в директории."""
        logger.info("\n" + "█" * 60)
        logger.info("  МАССОВЫЙ ИМПОРТ ИЗ ВСЕХ ИСТОЧНИКОВ")
        logger.info("█" * 60)

        path = Path(data_dir)

        if not path.exists():
            logger.error(f"❌ Директория не найдена: {path}")
            self.stats["errors"] += 1
            return self.stats

        # Поиск и импорт из всех источников
        for db_file in path.rglob("*.sqlite"):
            db_name = db_file.name.lower()
            if "freqtrade" in db_name or "tradesv3" in db_name:
                self.import_from_freqtrade(str(db_file))
            elif "hummingbot" in db_name:
                self.import_from_hummingbot(str(db_file))
            elif "jesse" in db_name:
                self.import_from_jesse(str(db_file))

        for csv_file in path.rglob("*.csv"):
            self.import_from_csv(str(csv_file))

        return self.stats


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(description="Импорт данных из внешних торговых систем в Genesis")

    parser.add_argument(
        "--source", type=str, required=True, choices=["freqtrade", "hummingbot", "jesse", "csv", "all"], help="Источник данных"
    )

    parser.add_argument("--path", type=str, required=True, help="Путь к файлу/базе данных источника")

    parser.add_argument(
        "--genesis-db", type=str, default="F:/Enjen/database/trading_system.db", help="Путь к базе данных Genesis"
    )

    args = parser.parse_args()

    # Создание импортёра
    try:
        importer = ExternalDataImporter(args.genesis_db)
    except FileNotFoundError as e:
        logger.error(e)
        return 1

    # Импорт в зависимости от источника
    if args.source == "freqtrade":
        importer.import_from_freqtrade(args.path)
    elif args.source == "hummingbot":
        importer.import_from_hummingbot(args.path)
    elif args.source == "jesse":
        importer.import_from_jesse(args.path)
    elif args.source == "csv":
        importer.import_from_csv(args.path)
    elif args.source == "all":
        importer.import_from_all(args.path)

    # Итоговый отчет
    stats = importer.stats

    logger.info("\n" + "=" * 60)
    logger.info("  ИТОГОВЫЙ ОТЧЕТ ПО ИМПОРТУ")
    logger.info("=" * 60)
    logger.info(f"  ✅ Импортировано: {stats['imported']}")
    logger.info(f"  ⚠ Пропущено: {stats['skipped']}")
    logger.info(f"  ❌ Ошибок: {stats['errors']}")

    if stats["errors"] == 0:
        logger.info("\n  🎉 Импорт завершен успешно!")
    else:
        logger.warning(f"\n  ⚠ Импорт завершен с {stats['errors']} ошибками")

    logger.info("\n" + "=" * 60 + "\n")

    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    exit(main())
