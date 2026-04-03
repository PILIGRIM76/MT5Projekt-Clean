#!/usr/bin/env python3
"""
Извлечение данных из торговых экосистем и импорт в БД Genesis Trading System.

Поддерживаемые источники:
- Freqtrade (SQLite) → PostgreSQL/TimescaleDB
- Hummingbot (SQLite) → PostgreSQL
- QuantConnect/LEAN (CSV) → TimescaleDB
- Jesse AI (SQLite) → PostgreSQL
- OctoBot (SQLite) → PostgreSQL
- Superalgos (JSON) → PostgreSQL
- Backtrader (CSV) → TimescaleDB
- Universal CSV → PostgreSQL

Использование:
    python scripts/extract_and_import.py --source freqtrade --path /path/to/tradesv3.sqlite
    python scripts/extract_and_import.py --source all --path /path/to/data
"""

import argparse
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class DataExtractorAndImporter:
    """Извлечение и импорт данных из внешних торговых систем в Genesis БД."""

    def __init__(self, genesis_config: Dict[str, Any]):
        self.genesis_config = genesis_config
        self.stats = {
            "extracted": 0,
            "imported": 0,
            "skipped": 0,
            "errors": 0,
        }
        self._init_database_connections()

    def _init_database_connections(self):
        """Инициализация подключений к БД Genesis."""
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.orm import sessionmaker

            # PostgreSQL
            pg_url = (
                f"postgresql://{self.genesis_config.get('postgres_user', 'trading_user')}:"
                f"{self.genesis_config.get('postgres_password', 'secure_password')}@"
                f"{self.genesis_config.get('postgres_host', 'localhost')}:"
                f"{self.genesis_config.get('postgres_port', 5432)}/"
                f"{self.genesis_config.get('postgres_db', 'trading')}"
            )
            self.pg_engine = create_engine(pg_url)

            # Проверка подключения
            with self.pg_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info(f"✓ PostgreSQL подключен: {self.genesis_config.get('postgres_host')}")

            # TimescaleDB
            ts_url = (
                f"postgresql://{self.genesis_config.get('timescaledb_user', 'trading_user')}:"
                f"{self.genesis_config.get('timescaledb_password', 'secure_password')}@"
                f"{self.genesis_config.get('timescaledb_host', 'localhost')}:"
                f"{self.genesis_config.get('timescaledb_port', 5433)}/"
                f"{self.genesis_config.get('timescaledb_db', 'trading_ts')}"
            )
            self.ts_engine = create_engine(ts_url)

            # Проверка подключения
            with self.ts_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info(f"✓ TimescaleDB подключен: {self.genesis_config.get('timescaledb_host')}")

            self.Session = sessionmaker(bind=self.pg_engine)

        except Exception as e:
            logger.error(f"Ошибка подключения к БД Genesis: {e}")
            raise

    # ========================================================================
    # FREQTRADE EXTRACT & IMPORT
    # ========================================================================
    def extract_import_from_freqtrade(self, db_path: str) -> Dict[str, int]:
        """Извлечение из Freqtrade и импорт в Genesis."""
        logger.info("\n" + "=" * 60)
        logger.info("  Freqtrade → Genesis (PostgreSQL/TimescaleDB)")
        logger.info("=" * 60)

        freqtrade_path = Path(db_path)
        if not freqtrade_path.exists():
            logger.error(f"Freqtrade база не найдена: {freqtrade_path}")
            self.stats["errors"] += 1
            return self.stats

        conn = sqlite3.connect(freqtrade_path)
        conn.row_factory = sqlite3.Row

        try:
            # ========== Извлечение сделок ==========
            logger.info("Извлечение сделок из Freqtrade...")

            query = """
                SELECT * FROM trades
                WHERE close_date IS NOT NULL
                ORDER BY close_date DESC
            """

            trades_cursor = conn.execute(query)
            trades_rows = trades_cursor.fetchall()
            logger.info(f"Найдено {len(trades_rows)} сделок")

            # ========== Импорт в PostgreSQL ==========
            logger.info("Импорт в PostgreSQL (trade_history)...")

            imported_count = 0
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

                    # Вставка в PostgreSQL
                    self._insert_trade_history(trade_data)
                    imported_count += 1
                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка импорта сделки {row['id']}: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Импортировано {imported_count} сделок из Freqtrade")
            self.stats["extracted"] += len(trades_rows)

            # ========== Извлечение ордеров ==========
            logger.info("Извлечение ордеров...")

            try:
                orders_query = "SELECT * FROM orders"
                orders_cursor = conn.execute(orders_query)
                orders_rows = orders_cursor.fetchall()
                logger.info(f"Найдено {len(orders_rows)} ордеров")

                # Импорт в PostgreSQL (можно добавить отдельную таблицу)
                for row in orders_rows:
                    self.stats["extracted"] += 1

            except Exception as e:
                logger.warning(f"Таблица 'orders' не найдена: {e}")

        except Exception as e:
            logger.error(f"Ошибка работы с Freqtrade: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.stats

    # ========================================================================
    # HUMMINGBOT EXTRACT & IMPORT
    # ========================================================================
    def extract_import_from_hummingbot(self, db_path: str) -> Dict[str, int]:
        """Извлечение из Hummingbot и импорт в Genesis."""
        logger.info("\n" + "=" * 60)
        logger.info("  Hummingbot → Genesis (PostgreSQL)")
        logger.info("=" * 60)

        db_file = Path(db_path)
        if not db_file.exists():
            logger.error(f"Hummingbot база не найдена: {db_file}")
            self.stats["errors"] += 1
            return self.stats

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row

        try:
            logger.info("Извлечение сделок из Hummingbot...")

            # Пробуем разные названия таблиц
            table_names = ["TradeEntry", "trades", "Trade"]
            trades_rows = []

            for table_name in table_names:
                try:
                    query = f"SELECT * FROM {table_name}"
                    trades_cursor = conn.execute(query)
                    trades_rows = trades_cursor.fetchall()
                    logger.info(f"Найдена таблица: {table_name}")
                    break
                except:
                    continue

            if not trades_rows:
                logger.info("Нет сделок для импорта")
                return self.stats

            logger.info(f"Найдено {len(trades_rows)} сделок")

            # Импорт в PostgreSQL
            logger.info("Импорт в PostgreSQL (trade_history)...")

            imported_count = 0
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
                                "fee": row_dict.get("fee"),
                            }
                        ),
                    }

                    self._insert_trade_history(trade_data)
                    imported_count += 1
                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка импорта сделки: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Импортировано {imported_count} сделок из Hummingbot")
            self.stats["extracted"] += len(trades_rows)

        except Exception as e:
            logger.error(f"Ошибка работы с Hummingbot: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.stats

    # ========================================================================
    # QUANTCONNECT EXTRACT & IMPORT
    # ========================================================================
    def extract_import_from_quantconnect(self, data_path: str) -> Dict[str, int]:
        """Извлечение из QuantConnect и импорт в Genesis (TimescaleDB)."""
        logger.info("\n" + "=" * 60)
        logger.info("  QuantConnect LEAN → Genesis (TimescaleDB)")
        logger.info("=" * 60)

        data_dir = Path(data_path)
        if not data_dir.exists():
            logger.error(f"Данные QuantConnect не найдены: {data_dir}")
            self.stats["errors"] += 1
            return self.stats

        try:
            # Поиск CSV файлов
            csv_files = list(data_dir.rglob("*.csv"))
            logger.info(f"Найдено {len(csv_files)} CSV файлов")

            # Импорт в TimescaleDB
            for file_path in csv_files:
                try:
                    df = pd.read_csv(file_path)
                    columns = [c.lower() for c in df.columns]

                    if "symbol" in columns and ("close" in columns or "price" in columns):
                        logger.info(f"Обработка файла: {file_path.name}")

                        # Подготовка данных для TimescaleDB
                        candles_data = []
                        for _, row in df.iterrows():
                            try:
                                candle = {
                                    "symbol": str(row.get("symbol", row.get("Symbol", "UNKNOWN"))),
                                    "timeframe": 60,  # По умолчанию M1
                                    "timestamp": pd.to_datetime(row.get("time", row.get("Time", row.get("datetime")))),
                                    "open": float(row.get("open", row.get("Open", 0)) or 0),
                                    "high": float(row.get("high", row.get("High", 0)) or 0),
                                    "low": float(row.get("low", row.get("Low", 0)) or 0),
                                    "close": float(row.get("close", row.get("Close", 0)) or 0),
                                    "volume": int(row.get("volume", row.get("Volume", 0)) or 0),
                                }
                                candles_data.append(candle)
                                self.stats["extracted"] += 1

                            except Exception as e:
                                logger.debug(f"Пропущена строка: {e}")
                                self.stats["errors"] += 1

                        # Пакетный импорт в TimescaleDB
                        if candles_data:
                            self._insert_candles_batch(candles_data)
                            logger.info(f"  ✓ Импортировано {len(candles_data)} свечей")

                except Exception as e:
                    logger.error(f"Ошибка чтения файла {file_path}: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Завершена обработка QuantConnect данных")

        except Exception as e:
            logger.error(f"Ошибка работы с QuantConnect: {e}")
            self.stats["errors"] += 1

        return self.stats

    # ========================================================================
    # JESSE AI EXTRACT & IMPORT
    # ========================================================================
    def extract_import_from_jesse(self, db_path: str) -> Dict[str, int]:
        """Извлечение из Jesse AI и импорт в Genesis."""
        logger.info("\n" + "=" * 60)
        logger.info("  Jesse AI → Genesis (PostgreSQL)")
        logger.info("=" * 60)

        db_file = Path(db_path)
        if not db_file.exists():
            logger.error(f"Jesse база не найдена: {db_file}")
            self.stats["errors"] += 1
            return self.stats

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row

        try:
            logger.info("Извлечение ордеров из Jesse...")

            try:
                query = "SELECT * FROM executed_orders"
                cursor = conn.execute(query)
                rows = cursor.fetchall()
                logger.info(f"Найдено {len(rows)} ордеров")

            except Exception as e:
                logger.error(f"Таблица 'executed_orders' не найдена: {e}")
                return self.stats

            # Импорт в PostgreSQL
            logger.info("Импорт в PostgreSQL (trade_history)...")

            imported_count = 0
            for row in rows:
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
                                "fee": row_dict.get("fee"),
                            }
                        ),
                    }

                    self._insert_trade_history(trade_data)
                    imported_count += 1
                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка импорта ордера: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Импортировано {imported_count} ордеров из Jesse")
            self.stats["extracted"] += len(rows)

        except Exception as e:
            logger.error(f"Ошибка работы с Jesse: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.stats

    # ========================================================================
    # OCTOBOT EXTRACT & IMPORT
    # ========================================================================
    def extract_import_from_octobot(self, db_path: str) -> Dict[str, int]:
        """Извлечение из OctoBot и импорт в Genesis."""
        logger.info("\n" + "=" * 60)
        logger.info("  OctoBot → Genesis (PostgreSQL)")
        logger.info("=" * 60)

        db_file = Path(db_path)
        if not db_file.exists():
            logger.error(f"OctoBot база не найдена: {db_file}")
            self.stats["errors"] += 1
            return self.stats

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row

        try:
            logger.info("Извлечение сделок из OctoBot...")

            table_names = ["trades", "Trade", "trade_history"]
            trades_rows = []

            for table_name in table_names:
                try:
                    query = f"SELECT * FROM {table_name}"
                    cursor = conn.execute(query)
                    trades_rows = cursor.fetchall()
                    logger.info(f"Найдена таблица: {table_name}")
                    break
                except:
                    continue

            if not trades_rows:
                logger.info("Нет сделок для импорта")
                return self.stats

            logger.info(f"Найдено {len(trades_rows)} сделок")

            # Импорт в PostgreSQL
            logger.info("Импорт в PostgreSQL (trade_history)...")

            imported_count = 0
            for row in trades_rows:
                try:
                    row_dict = dict(row)

                    trade_data = {
                        "ticket": row_dict.get("id", 0),
                        "symbol": row_dict.get("symbol", row_dict.get("market", "")).replace("_", ""),
                        "order_type": row_dict.get("side", "BUY").upper(),
                        "volume": float(row_dict.get("quantity", row_dict.get("amount", 0)) or 0),
                        "open_price": float(row_dict.get("price", 0) or 0),
                        "close_price": float(row_dict.get("price", 0) or 0),
                        "open_time": (
                            datetime.fromisoformat(row_dict.get("timestamp", row_dict.get("created_at", "")))
                            if row_dict.get("timestamp")
                            else None
                        ),
                        "close_time": (
                            datetime.fromisoformat(row_dict.get("timestamp", row_dict.get("created_at", "")))
                            if row_dict.get("timestamp")
                            else None
                        ),
                        "profit": float(row_dict.get("profit", row_dict.get("pnl", 0)) or 0),
                        "strategy_name": row_dict.get("strategy_name", "OctoBot"),
                        "model_type": "OctoBot",
                        "metadata": json.dumps(
                            {
                                "source": "OctoBot",
                                "exchange": row_dict.get("exchange"),
                                "fee": row_dict.get("fee"),
                            }
                        ),
                    }

                    self._insert_trade_history(trade_data)
                    imported_count += 1
                    self.stats["imported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка импорта сделки: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Импортировано {imported_count} сделок из OctoBot")
            self.stats["extracted"] += len(trades_rows)

        except Exception as e:
            logger.error(f"Ошибка работы с OctoBot: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.stats

    # ========================================================================
    # UNIVERSAL CSV EXTRACT & IMPORT
    # ========================================================================
    def extract_import_from_csv(self, csv_path: str, target_db: str = "postgres") -> Dict[str, int]:
        """Извлечение из CSV и импорт в Genesis."""
        logger.info("\n" + "=" * 60)
        logger.info(f"  CSV → Genesis ({target_db})")
        logger.info("=" * 60)

        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.error(f"CSV файл не найден: {csv_file}")
            self.stats["errors"] += 1
            return self.stats

        try:
            logger.info(f"Чтение CSV: {csv_file}")

            df = pd.read_csv(csv_path)
            logger.info(f"Найдено {len(df)} записей")

            # Проверка колонок
            required_columns = ["symbol", "order_type"]
            missing = [col for col in required_columns if col not in df.columns]

            if missing:
                logger.error(f"Отсутствуют обязательные колонки: {missing}")
                self.stats["errors"] += 1
                return self.stats

            # Импорт в PostgreSQL или TimescaleDB
            if target_db == "timescaledb":
                # Импорт свечных данных
                candles_data = []
                for _, row in df.iterrows():
                    try:
                        candle = {
                            "symbol": str(row.get("symbol", "UNKNOWN")),
                            "timeframe": int(row.get("timeframe", 60)),
                            "timestamp": pd.to_datetime(row.get("timestamp", row.get("time"))),
                            "open": float(row.get("open", 0)),
                            "high": float(row.get("high", 0)),
                            "low": float(row.get("low", 0)),
                            "close": float(row.get("close", 0)),
                            "volume": int(row.get("volume", 0)),
                        }
                        candles_data.append(candle)
                        self.stats["extracted"] += 1

                    except Exception as e:
                        logger.error(f"Ошибка обработки строки: {e}")
                        self.stats["errors"] += 1

                if candles_data:
                    self._insert_candles_batch(candles_data)
                    self.stats["imported"] += len(candles_data)
                    logger.info(f"✓ Импортировано {len(candles_data)} свечей в TimescaleDB")

            else:
                # Импорт торговых данных в PostgreSQL
                imported_count = 0
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
                                    "source": "Universal CSV",
                                    "original_data": row.to_dict(),
                                }
                            ),
                        }

                        self._insert_trade_history(trade_data)
                        imported_count += 1
                        self.stats["imported"] += 1

                    except Exception as e:
                        logger.error(f"Ошибка импорта записи: {e}")
                        self.stats["errors"] += 1

                logger.info(f"✓ Импортировано {imported_count} записей в PostgreSQL")
                self.stats["extracted"] += len(df)

        except Exception as e:
            logger.error(f"Ошибка работы с CSV: {e}")
            self.stats["errors"] += 1

        return self.stats

    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    def _insert_trade_history(self, trade_data: Dict[str, Any]):
        """Вставка записи в таблицу trade_history."""
        from sqlalchemy import text

        query = text("""
            INSERT INTO trade_history (
                ticket, symbol, order_type, volume, open_price, close_price,
                sl, tp, open_time, close_time, profit,
                strategy_name, model_type, metadata, created_at
            ) VALUES (
                :ticket, :symbol, :order_type, :volume, :open_price, :close_price,
                :sl, :tp, :open_time, :close_time, :profit,
                :strategy_name, :model_type, :metadata, :created_at
            )
            ON CONFLICT (ticket) DO UPDATE SET
                symbol = EXCLUDED.symbol,
                order_type = EXCLUDED.order_type,
                volume = EXCLUDED.volume,
                open_price = EXCLUDED.open_price,
                close_price = EXCLUDED.close_price,
                sl = EXCLUDED.sl,
                tp = EXCLUDED.tp,
                open_time = EXCLUDED.open_time,
                close_time = EXCLUDED.close_time,
                profit = EXCLUDED.profit,
                strategy_name = EXCLUDED.strategy_name,
                model_type = EXCLUDED.model_type,
                metadata = EXCLUDED.metadata
        """)

        trade_data["created_at"] = datetime.utcnow()

        with self.pg_engine.connect() as conn:
            conn.execute(query, trade_data)
            conn.commit()

    def _insert_candles_batch(self, candles_data: List[Dict[str, Any]]):
        """Пакетная вставка свечных данных в TimescaleDB."""
        df = pd.DataFrame(candles_data)

        df.to_sql(
            "candle_data",
            self.ts_engine,
            if_exists="append",
            index=True,
            index_label="timestamp",
            method="multi",
            chunksize=1000,
        )

    def _process_all_in_directory(self, data_dir: str):
        """Обработка всех файлов в директории."""
        path = Path(data_dir)

        if path.is_dir():
            # Поиск SQLite баз
            for db_file in path.rglob("*.sqlite"):
                db_name = db_file.name.lower()
                if "freqtrade" in db_name or "tradesv3" in db_name:
                    self.extract_import_from_freqtrade(str(db_file))
                elif "hummingbot" in db_name:
                    self.extract_import_from_hummingbot(str(db_file))
                elif "jesse" in db_name:
                    self.extract_import_from_jesse(str(db_file))
                elif "octobot" in db_name:
                    self.extract_import_from_octobot(str(db_file))

            # Поиск CSV файлов
            for csv_file in path.rglob("*.csv"):
                self.extract_import_from_csv(str(csv_file), target_db="postgres")

    def get_stats(self) -> Dict[str, int]:
        """Получение статистики."""
        return self.stats


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(description="Извлечение данных из торговых систем и импорт в Genesis")

    parser.add_argument(
        "--source",
        type=str,
        required=True,
        choices=["freqtrade", "hummingbot", "quantconnect", "jesse", "octobot", "csv", "all"],
        help="Источник данных",
    )

    parser.add_argument("--path", type=str, required=True, help="Путь к файлу/базе данных/директории источника")

    parser.add_argument("--postgres-host", default=os.getenv("POSTGRES_HOST", "localhost"), help="PostgreSQL host")

    parser.add_argument("--postgres-port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")), help="PostgreSQL port")

    parser.add_argument("--postgres-db", default=os.getenv("POSTGRES_DB", "trading"), help="PostgreSQL database")

    parser.add_argument("--postgres-user", default=os.getenv("POSTGRES_USER", "trading_user"), help="PostgreSQL user")

    parser.add_argument(
        "--postgres-password", default=os.getenv("POSTGRES_PASSWORD", "secure_password"), help="PostgreSQL password"
    )

    parser.add_argument("--timescaledb-host", default=os.getenv("TIMESCALEDB_HOST", "localhost"), help="TimescaleDB host")

    parser.add_argument(
        "--timescaledb-port", type=int, default=int(os.getenv("TIMESCALEDB_PORT", "5433")), help="TimescaleDB port"
    )

    parser.add_argument("--timescaledb-db", default=os.getenv("TIMESCALEDB_DB", "trading_ts"), help="TimescaleDB database")

    parser.add_argument("--timescaledb-user", default=os.getenv("TIMESCALEDB_USER", "trading_user"), help="TimescaleDB user")

    parser.add_argument(
        "--timescaledb-password", default=os.getenv("TIMESCALEDB_PASSWORD", "secure_password"), help="TimescaleDB password"
    )

    args = parser.parse_args()

    # Конфигурация
    config = {
        "postgres_host": args.postgres_host,
        "postgres_port": args.postgres_port,
        "postgres_db": args.postgres_db,
        "postgres_user": args.postgres_user,
        "postgres_password": args.postgres_password,
        "timescaledb_host": args.timescaledb_host,
        "timescaledb_port": args.timescaledb_port,
        "timescaledb_db": args.timescaledb_db,
        "timescaledb_user": args.timescaledb_user,
        "timescaledb_password": args.timescaledb_password,
    }

    # Создание экстрактора
    extractor = DataExtractorAndImporter(config)

    # Извлечение и импорт
    if args.source == "freqtrade":
        extractor.extract_import_from_freqtrade(args.path)

    elif args.source == "hummingbot":
        extractor.extract_import_from_hummingbot(args.path)

    elif args.source == "quantconnect":
        extractor.extract_import_from_quantconnect(args.path)

    elif args.source == "jesse":
        extractor.extract_import_from_jesse(args.path)

    elif args.source == "octobot":
        extractor.extract_import_from_octobot(args.path)

    elif args.source == "csv":
        extractor.extract_import_from_csv(args.path)

    elif args.source == "all":
        extractor._process_all_in_directory(args.path)

    # Итоговый отчет
    stats = extractor.get_stats()

    logger.info("\n" + "=" * 60)
    logger.info("  ИТОГОВЫЙ ОТЧЕТ")
    logger.info("=" * 60)
    logger.info(f"  Извлечено записей: {stats['extracted']}")
    logger.info(f"  Импортировано записей: {stats['imported']}")
    logger.info(f"  Пропущено: {stats['skipped']}")
    logger.info(f"  Ошибок: {stats['errors']}")

    if stats["errors"] == 0:
        logger.info("\n  ✅ Импорт завершен успешно!")
    else:
        logger.warning(f"\n  ⚠ Импорт завершен с {stats['errors']} ошибками")

    logger.info("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
