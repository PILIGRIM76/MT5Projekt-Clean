#!/usr/bin/env python3
"""
Экспорт данных из торговых экосистем в формат Genesis Trading System.

Поддерживаемые экосистемы:
- Freqtrade (SQLite)
- Hummingbot (SQLite/CSV)
- QuantConnect/LEAN (CSV/JSON)
- Jesse AI (SQLite)
- OctoBot (SQLite)
- Superalgos (JSON)
- Backtrader (CSV)
- Universal CSV

Использование:
    python scripts/export_to_genesis.py --source freqtrade --path /path/to/tradesv3.sqlite --output exported_data.json
    python scripts/export_to_genesis.py --source all --path /path/to/data --output genesis_import.json
"""

import argparse
import csv
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class GenesisDataExporter:
    """Экспорт данных из различных торговых систем в формат Genesis."""

    def __init__(self, output_format: str = "genesis"):
        self.output_format = output_format
        self.stats = {
            "exported": 0,
            "skipped": 0,
            "errors": 0,
        }
        self.exported_data = {
            "trades": [],
            "candles": [],
            "orders": [],
        }

    # ========================================================================
    # FREQTRADE EXPORTER
    # ========================================================================
    def export_from_freqtrade(self, db_path: str) -> Dict[str, List]:
        """
        Экспорт данных из Freqtrade.

        Схема БД Freqtrade:
        - trades: история сделок
        - orders: заказы
        - trade_custom_data: пользовательские данные
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из Freqtrade")
        logger.info("=" * 60)

        freqtrade_path = Path(db_path)
        if not freqtrade_path.exists():
            logger.error(f"Freqtrade база не найдена: {freqtrade_path}")
            self.stats["errors"] += 1
            return self.exported_data

        conn = sqlite3.connect(freqtrade_path)
        conn.row_factory = sqlite3.Row

        try:
            # ========== Экспорт сделок ==========
            logger.info("Экспорт сделок из таблицы 'trades'...")

            query = """
                SELECT * FROM trades
                WHERE close_date IS NOT NULL
                ORDER BY close_date DESC
            """

            trades_cursor = conn.execute(query)
            trades_rows = trades_cursor.fetchall()

            logger.info(f"Найдено {len(trades_rows)} закрытых сделок")

            for row in trades_rows:
                try:
                    trade = {
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
                        "profit_pct": float(row["close_profit"] or 0) * 100,
                        "exit_reason": row.get("exit_reason"),
                        "strategy_name": row.get("strategy", "Freqtrade"),
                        "model_type": "Freqtrade",
                        "fee_open": float(row["fee_open"] or 0),
                        "fee_close": float(row["fee_close"] or 0),
                        "metadata": json.dumps(
                            {
                                "source": "Freqtrade",
                                "freqtrade_id": row["id"],
                                "is_short": row.get("is_short", False),
                                "stake_amount": row.get("stake_amount"),
                                "stake_currency": row.get("stake_currency", "USDT"),
                                "exchange": row.get("exchange", "unknown"),
                                "open_rate_requested": row.get("open_rate_requested"),
                                "close_rate_requested": row.get("close_rate_requested"),
                            }
                        ),
                    }
                    self.exported_data["trades"].append(trade)
                    self.stats["exported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка экспорта сделки {row['id']}: {e}")
                    self.stats["errors"] += 1

            # ========== Экспорт ордеров ==========
            logger.info("Экспорт ордеров из таблицы 'orders'...")

            try:
                orders_query = "SELECT * FROM orders"
                orders_cursor = conn.execute(orders_query)
                orders_rows = orders_cursor.fetchall()

                logger.info(f"Найдено {len(orders_rows)} ордеров")

                for row in orders_rows:
                    try:
                        order = {
                            "order_id": row["order_id"],
                            "trade_id": row["ft_trade_id"],
                            "order_type": row["order_type"],
                            "side": row["side"],
                            "price": float(row["price"] or 0),
                            "amount": float(row["amount"] or 0),
                            "filled": float(row["filled"] or 0),
                            "remaining": float(row["remaining"] or 0),
                            "status": row["status"],
                            "symbol": row["ft_pair"],
                            "created_at": row["order_date"],
                            "updated_at": row["order_update_date"],
                            "metadata": json.dumps(
                                {
                                    "source": "Freqtrade",
                                    "order_filled": row.get("order_filled"),
                                }
                            ),
                        }
                        self.exported_data["orders"].append(order)

                    except Exception as e:
                        logger.error(f"Ошибка экспорта ордера {row['order_id']}: {e}")
                        self.stats["errors"] += 1

            except Exception as e:
                logger.warning(f"Таблица 'orders' не найдена или пуста: {e}")

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} сделок из Freqtrade")

        except Exception as e:
            logger.error(f"Ошибка экспорта из Freqtrade: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.exported_data

    # ========================================================================
    # HUMMINGBOT EXPORTER
    # ========================================================================
    def export_from_hummingbot(self, db_path: str) -> Dict[str, List]:
        """
        Экспорт данных из Hummingbot.

        Схема БД Hummingbot:
        - TradeEntry: история сделок
        - Order: заказы
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из Hummingbot")
        logger.info("=" * 60)

        db_file = Path(db_path)
        if not db_file.exists():
            logger.error(f"Hummingbot база не найдена: {db_file}")
            self.stats["errors"] += 1
            return self.exported_data

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row

        try:
            # ========== Экспорт сделок ==========
            logger.info("Экспорт сделок...")

            # Пробуем разные возможные названия таблиц
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
                logger.info("Нет сделок для экспорта")
                return self.exported_data

            logger.info(f"Найдено {len(trades_rows)} сделок")

            for row in trades_rows:
                try:
                    row_dict = dict(row)

                    # Определяем тип сделки
                    trade_type = "BUY" if row_dict.get("trade_type", "").upper() == "BUY" else "SELL"

                    trade = {
                        "ticket": row_dict.get("id", 0),
                        "symbol": row_dict.get("market", "").replace("-", ""),
                        "order_type": trade_type,
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
                    self.exported_data["trades"].append(trade)
                    self.stats["exported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка экспорта сделки: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} сделок из Hummingbot")

        except Exception as e:
            logger.error(f"Ошибка экспорта из Hummingbot: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.exported_data

    # ========================================================================
    # QUANTCONNECT/LEAN EXPORTER
    # ========================================================================
    def export_from_quantconnect(self, data_path: str) -> Dict[str, List]:
        """
        Экспорт данных из QuantConnect LEAN.

        Формат данных LEAN:
        - CSV/JSON файлы с данными
        - Структура: /data/securityType/marketName/resolution/ticker/
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из QuantConnect LEAN")
        logger.info("=" * 60)

        data_dir = Path(data_path)
        if not data_dir.exists():
            logger.error(f"Данные QuantConnect не найдены: {data_dir}")
            self.stats["errors"] += 1
            return self.exported_data

        try:
            # Поиск CSV файлов с торговыми данными
            trade_files = list(data_dir.rglob("*.csv"))
            logger.info(f"Найдено {len(trade_files)} CSV файлов")

            for file_path in trade_files:
                try:
                    df = pd.read_csv(file_path)

                    # Определяем тип данных по колонкам
                    columns = [c.lower() for c in df.columns]

                    if "symbol" in columns and ("close" in columns or "price" in columns):
                        # Это могут быть свечи или торговые данные
                        for _, row in df.iterrows():
                            try:
                                trade = {
                                    "ticket": 0,
                                    "symbol": str(row.get("symbol", row.get("Symbol", "UNKNOWN"))),
                                    "order_type": "BUY",  # По умолчанию BUY для свечей
                                    "volume": float(row.get("volume", row.get("Volume", 0)) or 0),
                                    "open_price": float(row.get("open", row.get("Open", 0)) or 0),
                                    "close_price": float(row.get("close", row.get("Close", 0)) or 0),
                                    "open_time": pd.to_datetime(row.get("time", row.get("Time", row.get("datetime")))),
                                    "close_time": pd.to_datetime(row.get("time", row.get("Time", row.get("datetime")))),
                                    "strategy_name": "QuantConnect",
                                    "model_type": "LEAN",
                                    "metadata": json.dumps(
                                        {
                                            "source": "QuantConnect",
                                            "file": str(file_path),
                                            "high": float(row.get("high", row.get("High", 0)) or 0),
                                            "low": float(row.get("low", row.get("Low", 0)) or 0),
                                        }
                                    ),
                                }
                                self.exported_data["trades"].append(trade)
                                self.stats["exported"] += 1

                            except Exception as e:
                                logger.error(f"Ошибка обработки строки: {e}")
                                self.stats["errors"] += 1

                except Exception as e:
                    logger.error(f"Ошибка чтения файла {file_path}: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} записей из QuantConnect")

        except Exception as e:
            logger.error(f"Ошибка экспорта из QuantConnect: {e}")
            self.stats["errors"] += 1

        return self.exported_data

    # ========================================================================
    # JESSE AI EXPORTER
    # ========================================================================
    def export_from_jesse(self, db_path: str) -> Dict[str, List]:
        """
        Экспорт данных из Jesse AI.

        Схема БД Jesse:
        - candles: свечные данные
        - executed_orders: выполненные ордеры
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из Jesse AI")
        logger.info("=" * 60)

        db_file = Path(db_path)
        if not db_file.exists():
            logger.error(f"Jesse база не найдена: {db_file}")
            self.stats["errors"] += 1
            return self.exported_data

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row

        try:
            # ========== Экспорт ордеров ==========
            logger.info("Экспорт ордеров...")

            try:
                query = "SELECT * FROM executed_orders"
                cursor = conn.execute(query)
                rows = cursor.fetchall()

                logger.info(f"Найдено {len(rows)} ордеров")

                for row in rows:
                    try:
                        row_dict = dict(row)

                        order = {
                            "ticket": row_dict.get("id", 0),
                            "symbol": row_dict.get("symbol", "").replace("_", ""),
                            "order_type": row_dict.get("side", "BUY").upper(),
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
                        self.exported_data["trades"].append(order)
                        self.stats["exported"] += 1

                    except Exception as e:
                        logger.error(f"Ошибка экспорта ордера: {e}")
                        self.stats["errors"] += 1

            except Exception as e:
                logger.warning(f"Таблица 'executed_orders' не найдена: {e}")

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} ордеров из Jesse")

        except Exception as e:
            logger.error(f"Ошибка экспорта из Jesse: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.exported_data

    # ========================================================================
    # OCTOBOT EXPORTER
    # ========================================================================
    def export_from_octobot(self, db_path: str) -> Dict[str, List]:
        """
        Экспорт данных из OctoBot.

        Схема БД OctoBot:
        - trades: история сделок
        - orders: заказы
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из OctoBot")
        logger.info("=" * 60)

        db_file = Path(db_path)
        if not db_file.exists():
            logger.error(f"OctoBot база не найдена: {db_file}")
            self.stats["errors"] += 1
            return self.exported_data

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row

        try:
            # ========== Экспорт сделок ==========
            logger.info("Экспорт сделок...")

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

            if trades_rows:
                logger.info(f"Найдено {len(trades_rows)} сделок")

                for row in trades_rows:
                    try:
                        row_dict = dict(row)

                        trade = {
                            "ticket": row_dict.get("id", 0),
                            "symbol": row_dict.get("symbol", row_dict.get("market", "")).replace("_", ""),
                            "order_type": row_dict.get("side", "BUY").upper(),
                            "volume": float(row_dict.get("quantity", row_dict.get("amount", 0)) or 0),
                            "open_price": float(row_dict.get("price", 0) or 0),
                            "close_price": float(row_dict.get("price", 0) or 0),
                            "open_time": (
                                datetime.fromisoformat(row_dict.get("timestamp", row_dict.get("created_at", "")))
                                if row_dict.get("timestamp") or row_dict.get("created_at")
                                else None
                            ),
                            "close_time": (
                                datetime.fromisoformat(row_dict.get("timestamp", row_dict.get("created_at", "")))
                                if row_dict.get("timestamp") or row_dict.get("created_at")
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
                        self.exported_data["trades"].append(trade)
                        self.stats["exported"] += 1

                    except Exception as e:
                        logger.error(f"Ошибка экспорта сделки: {e}")
                        self.stats["errors"] += 1

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} сделок из OctoBot")

        except Exception as e:
            logger.error(f"Ошибка экспорта из OctoBot: {e}")
            self.stats["errors"] += 1

        finally:
            conn.close()

        return self.exported_data

    # ========================================================================
    # SUPERALGOS EXPORTER
    # ========================================================================
    def export_from_superalgos(self, data_path: str) -> Dict[str, List]:
        """
        Экспорт данных из Superalgos.

        Формат данных Superalgos:
        - JSON файлы в Data-Storage
        - Workspace файлы
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из Superalgos")
        logger.info("=" * 60)

        data_dir = Path(data_path)
        if not data_dir.exists():
            logger.error(f"Данные Superalgos не найдены: {data_dir}")
            self.stats["errors"] += 1
            return self.exported_data

        try:
            # Поиск JSON файлов с торговыми данными
            json_files = list(data_dir.rglob("*.json"))
            logger.info(f"Найдено {len(json_files)} JSON файлов")

            for file_path in json_files:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Проверяем, является ли файл торговыми данными
                    if isinstance(data, list) and len(data) > 0:
                        for item in data:
                            if isinstance(item, dict) and ("symbol" in item or "market" in item):
                                try:
                                    trade = {
                                        "ticket": item.get("id", 0),
                                        "symbol": str(item.get("symbol", item.get("market", "UNKNOWN"))),
                                        "order_type": str(item.get("side", item.get("direction", "BUY"))).upper(),
                                        "volume": float(item.get("amount", item.get("quantity", 0)) or 0),
                                        "open_price": float(item.get("price", item.get("entryPrice", 0)) or 0),
                                        "close_price": float(item.get("exitPrice", item.get("price", 0)) or 0),
                                        "open_time": (
                                            datetime.fromisoformat(item.get("timestamp", item.get("time", "")))
                                            if item.get("timestamp") or item.get("time")
                                            else None
                                        ),
                                        "close_time": (
                                            datetime.fromisoformat(item.get("exitTimestamp", item.get("exitTime", "")))
                                            if item.get("exitTimestamp") or item.get("exitTime")
                                            else None
                                        ),
                                        "profit": float(item.get("profit", item.get("pnl", 0)) or 0),
                                        "strategy_name": "Superalgos",
                                        "model_type": "Superalgos",
                                        "metadata": json.dumps(
                                            {
                                                "source": "Superalgos",
                                                "file": str(file_path),
                                                "original_data": item,
                                            }
                                        ),
                                    }
                                    self.exported_data["trades"].append(trade)
                                    self.stats["exported"] += 1

                                except Exception as e:
                                    logger.debug(f"Пропущена запись: {e}")

                except Exception as e:
                    logger.debug(f"Ошибка чтения файла {file_path}: {e}")

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} записей из Superalgos")

        except Exception as e:
            logger.error(f"Ошибка экспорта из Superalgos: {e}")
            self.stats["errors"] += 1

        return self.exported_data

    # ========================================================================
    # BACKTRADER EXPORTER
    # ========================================================================
    def export_from_backtrader(self, csv_path: str) -> Dict[str, List]:
        """
        Экспорт данных из Backtrader.

        Формат данных Backtrader:
        - CSV файлы с OHLCV данными
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из Backtrader")
        logger.info("=" * 60)

        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.error(f"CSV файл не найден: {csv_file}")
            self.stats["errors"] += 1
            return self.exported_data

        try:
            logger.info(f"Чтение CSV: {csv_file}")

            df = pd.read_csv(csv_file)
            logger.info(f"Найдено {len(df)} записей")

            # Определяем колонки
            columns = [c.lower() for c in df.columns]

            for _, row in df.iterrows():
                try:
                    trade = {
                        "ticket": 0,
                        "symbol": "BACKTRADER",
                        "order_type": "BUY",
                        "volume": float(row.get("volume", row.get("Volume", 0)) or 0),
                        "open_price": float(row.get("open", row.get("Open", 0)) or 0),
                        "close_price": float(row.get("close", row.get("Close", 0)) or 0),
                        "open_time": pd.to_datetime(row.get("datetime", row.get("time", row.get("date")))),
                        "close_time": pd.to_datetime(row.get("datetime", row.get("time", row.get("date")))),
                        "strategy_name": "Backtrader",
                        "model_type": "Backtrader",
                        "metadata": json.dumps(
                            {
                                "source": "Backtrader",
                                "file": str(csv_file),
                                "high": float(row.get("high", row.get("High", 0)) or 0),
                                "low": float(row.get("low", row.get("Low", 0)) or 0),
                            }
                        ),
                    }
                    self.exported_data["trades"].append(trade)
                    self.stats["exported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки строки: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} записей из Backtrader")

        except Exception as e:
            logger.error(f"Ошибка экспорта из Backtrader: {e}")
            self.stats["errors"] += 1

        return self.exported_data

    # ========================================================================
    # UNIVERSAL CSV EXPORTER
    # ========================================================================
    def export_from_csv(self, csv_path: str) -> Dict[str, List]:
        """
        Экспорт из универсального CSV формата.
        """
        logger.info("\n" + "=" * 60)
        logger.info(f"  Экспорт из CSV")
        logger.info("=" * 60)

        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.error(f"CSV файл не найден: {csv_file}")
            self.stats["errors"] += 1
            return self.exported_data

        try:
            logger.info(f"Чтение CSV: {csv_file}")

            df = pd.read_csv(csv_path)
            logger.info(f"Найдено {len(df)} записей")

            # Проверка обязательных колонок
            required_columns = ["symbol", "order_type"]
            missing = [col for col in required_columns if col not in df.columns]

            if missing:
                logger.error(f"Отсутствуют обязательные колонки: {missing}")
                self.stats["errors"] += 1
                return self.exported_data

            for _, row in df.iterrows():
                try:
                    trade = {
                        "ticket": row.get("ticket", row.get("id", 0)),
                        "symbol": str(row.get("symbol", "UNKNOWN")),
                        "order_type": str(row.get("order_type", row.get("type", "BUY"))).upper(),
                        "volume": float(row.get("volume", row.get("amount", row.get("size", 0))) or 0),
                        "open_price": float(row.get("open_price", row.get("price", row.get("entry_price", 0))) or 0),
                        "close_price": float(row.get("close_price", row.get("exit_price", row.get("price", 0))) or 0),
                        "open_time": (
                            pd.to_datetime(row.get("open_time", row.get("entry_time", row.get("timestamp"))))
                            if "open_time" in row or "entry_time" in row or "timestamp" in row
                            else None
                        ),
                        "close_time": (
                            pd.to_datetime(row.get("close_time", row.get("exit_time", row.get("timestamp"))))
                            if "close_time" in row or "exit_time" in row or "timestamp" in row
                            else None
                        ),
                        "profit": float(row.get("profit", row.get("pnl", row.get("gain", 0))) or 0),
                        "strategy_name": str(row.get("strategy_name", row.get("strategy", "CSV"))),
                        "model_type": str(row.get("model_type", row.get("model", "CSV"))),
                        "metadata": json.dumps(
                            {
                                "source": "Universal CSV",
                                "original_data": row.to_dict(),
                            }
                        ),
                    }
                    self.exported_data["trades"].append(trade)
                    self.stats["exported"] += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки строки: {e}")
                    self.stats["errors"] += 1

            logger.info(f"✓ Экспортировано {len(self.exported_data['trades'])} записей из CSV")

        except Exception as e:
            logger.error(f"Ошибка экспорта из CSV: {e}")
            self.stats["errors"] += 1

        return self.exported_data

    # ========================================================================
    # EXPORT TO GENESIS FORMAT
    # ========================================================================
    def save_to_genesis_format(self, output_path: str):
        """Сохранение данных в формате Genesis Trading System."""
        logger.info("\n" + "=" * 60)
        logger.info("  Сохранение в формате Genesis")
        logger.info("=" * 60)

        output_file = Path(output_path)

        genesis_format = {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "stats": self.stats,
            "data": self.exported_data,
        }

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(genesis_format, f, indent=2, ensure_ascii=False, default=str)

            logger.info(f"✓ Данные сохранены в: {output_file}")
            logger.info(f"  Всего записей: {len(self.exported_data['trades'])}")

        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            raise

    def get_stats(self) -> Dict[str, int]:
        """Получение статистики экспорта."""
        return self.stats


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(description="Экспорт данных из торговых систем в формат Genesis")

    parser.add_argument(
        "--source",
        type=str,
        required=True,
        choices=["freqtrade", "hummingbot", "quantconnect", "jesse", "octobot", "superalgos", "backtrader", "csv", "all"],
        help="Источник данных",
    )

    parser.add_argument("--path", type=str, required=True, help="Путь к файлу/базе данных/директории источника")

    parser.add_argument("--output", type=str, default="genesis_export.json", help="Путь к выходному файлу")

    args = parser.parse_args()

    # Создание экспортера
    exporter = GenesisDataExporter()

    # Экспорт в зависимости от источника
    if args.source == "freqtrade":
        exporter.export_from_freqtrade(args.path)

    elif args.source == "hummingbot":
        exporter.export_from_hummingbot(args.path)

    elif args.source == "quantconnect":
        exporter.export_from_quantconnect(args.path)

    elif args.source == "jesse":
        exporter.export_from_jesse(args.path)

    elif args.source == "octobot":
        exporter.export_from_octobot(args.path)

    elif args.source == "superalgos":
        exporter.export_from_superalgos(args.path)

    elif args.source == "backtrader":
        exporter.export_from_backtrader(args.path)

    elif args.source == "csv":
        exporter.export_from_csv(args.path)

    elif args.source == "all":
        # Попытка экспорта из всех источников
        logger.info("Попытка экспорта из всех доступных источников...")

        # Проверяем различные типы файлов в указанной директории
        path = Path(args.path)

        if path.is_dir():
            # Поиск SQLite баз
            for db_file in path.rglob("*.sqlite"):
                db_name = db_file.name.lower()
                if "freqtrade" in db_name or "tradesv3" in db_name:
                    exporter.export_from_freqtrade(str(db_file))
                elif "hummingbot" in db_name:
                    exporter.export_from_hummingbot(str(db_file))
                elif "jesse" in db_name:
                    exporter.export_from_jesse(str(db_file))
                elif "octobot" in db_name:
                    exporter.export_from_octobot(str(db_file))

            # Поиск CSV файлов
            for csv_file in path.rglob("*.csv"):
                exporter.export_from_csv(str(csv_file))

            # Поиск JSON файлов
            for json_file in path.rglob("*.json"):
                exporter.export_from_superalgos(str(json_file.parent))

    # Сохранение в формате Genesis
    exporter.save_to_genesis_format(args.output)

    # Итоговый отчет
    stats = exporter.get_stats()

    logger.info("\n" + "=" * 60)
    logger.info("  ИТОГОВЫЙ ОТЧЕТ ПО ЭКСПОРТУ")
    logger.info("=" * 60)
    logger.info(f"  Экспортировано: {stats['exported']}")
    logger.info(f"  Пропущено: {stats['skipped']}")
    logger.info(f"  Ошибок: {stats['errors']}")

    if stats["errors"] == 0:
        logger.info("\n  ✅ Экспорт завершен успешно!")
    else:
        logger.warning(f"\n  ⚠ Экспорт завершен с {stats['errors']} ошибками")

    logger.info("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
