#!/usr/bin/env python3
"""
Загрузка долгосрочных исторических рыночных данных в Genesis Trading System.

═══════════════════════════════════════════════════════════════════════════
ИСТОЧНИКИ ДАННЫХ (70+ лет истории):
═══════════════════════════════════════════════════════════════════════════

1. FRED (Federal Reserve Economic Data): 1776–now (250+ лет)
   - 840,000+ временных рядов
   - GDP, инфляция, процентные ставки, S&P 500
   - API key: https://fred.stlouisfed.org/docs/api/api_key.html

2. Shiller Data: 1871–now (150+ лет)
   - S&P 500, CAPE ratio, earnings, dividends
   - Бесплатно, без API key

3. yfinance (Yahoo Finance): 1970–now (50+ лет)
   - Global stocks, ETF, forex, crypto
   - Бесплатно, без API key

4. Stooq: 1990–now (30+ лет)
   - US, UK, Japan, Poland markets
   - Daily, hourly, 5-min data
   - Бесплатно, без регистрации

5. NBER Macrohistory: 1860–1991 (130+ лет)
   - Macro data for 17 countries
   - Requires Kaggle account

═══════════════════════════════════════════════════════════════════════════
ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ:
═══════════════════════════════════════════════════════════════════════════

# Загрузка данных FRED (S&P 500 с 1900 года)
python download_historical_data.py --source fred --symbol SP500 DJIA --start 1900-01-01 --api-key YOUR_KEY

# Загрузка данных Shiller (150+ лет S&P 500)
python download_historical_data.py --source shiller

# Загрузка конкретных символов из yfinance
python download_historical_data.py --source yfinance --symbol AAPL MSFT GOOGL --start 1980-01-01

# Загрузка из Stooq (бесплатно, без API key)
python download_historical_data.py --source stooq --symbol ^spx ^dji aapl.us

# Массовая загрузка всех данных
python download_historical_data.py --source all --bulk --api-key YOUR_KEY

# Загрузка NBER через Kaggle (130 лет макроэкономики)
python download_historical_data.py --source nber
"""

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class HistoricalDataDownloader:
    """Загрузка долгосрочных исторических данных из различных источников."""

    def __init__(
        self,
        genesis_db_path: str = "F:/Enjen/database/trading_system.db",
    ):
        self.genesis_db_path = Path(genesis_db_path)
        self.stats = {
            "downloaded": 0,
            "imported": 0,
            "skipped": 0,
            "errors": 0,
            "symbols": [],
        }

        logger.info(f"✅ Инициализация загрузчика исторических данных")
        logger.info(f"   Genesis DB: {self.genesis_db_path}")

    def _ensure_db_directory(self):
        """Создание директории БД если не существует."""
        self.genesis_db_path.parent.mkdir(parents=True, exist_ok=True)

    def _save_to_sqlite(
        self,
        df: pd.DataFrame,
        symbol: str,
        source: str,
        table_name: str = "market_data",
    ):
        """Сохранение данных в SQLite."""
        if df.empty:
            logger.warning(f"⚠ Пустой DataFrame для {symbol}")
            return

        self._ensure_db_directory()
        conn = sqlite3.connect(str(self.genesis_db_path))
        cursor = conn.cursor()

        try:
            # Создание таблицы если не существует
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    source TEXT,
                    timeframe TEXT DEFAULT 'D1',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timestamp, source)
                )
            """)

            # Создание индексов для быстрого поиска
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_symbol ON {table_name}(symbol)")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp ON {table_name}(timestamp)")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_source ON {table_name}(source)")

            # Подготовка данных
            records = []
            for _, row in df.iterrows():
                timestamp = row.get("timestamp") or row.get("date") or row.get("Date")
                if timestamp is None or str(timestamp).strip() in ["N/D", "N/A", "", "nan", "None"]:
                    continue

                try:
                    # Конвертация timestamp
                    if isinstance(timestamp, (int, float)):
                        if timestamp > 1e12:  # milliseconds
                            timestamp = pd.to_datetime(timestamp, unit="ms")
                        else:  # seconds or days since epoch
                            timestamp = pd.to_datetime(timestamp, unit="s")
                    else:
                        # Обработка различных форматов дат
                        timestamp_str = str(timestamp).strip()

                        # Формат YYYY.MM.DD (Stooq)
                        if "." in timestamp_str and len(timestamp_str) == 10:
                            timestamp = pd.Timestamp(timestamp_str.replace(".", "-"))
                        # Формат YYYY-MM-DD
                        elif "-" in timestamp_str:
                            timestamp = pd.Timestamp(timestamp_str)
                        # Формат MM/DD/YYYY
                        elif "/" in timestamp_str:
                            timestamp = pd.Timestamp(timestamp_str)
                        else:
                            # Попытка автоматического парсинга
                            timestamp = pd.Timestamp(timestamp_str)

                    if pd.isna(timestamp):
                        continue

                    records.append(
                        {
                            "symbol": symbol,
                            "timestamp": timestamp.isoformat(),
                            "open": float(row.get("open", row.get("Open", 0)) or 0),
                            "high": float(row.get("high", row.get("High", 0)) or 0),
                            "low": float(row.get("low", row.get("Low", 0)) or 0),
                            "close": float(row.get("close", row.get("Close", 0)) or 0),
                            "volume": float(row.get("volume", row.get("Volume", 0)) or 0),
                            "source": source,
                            "timeframe": "D1",
                        }
                    )
                except Exception as e:
                    logger.debug(f"⚠ Пропуск строки с невалидной датой: {timestamp} ({e})")
                    continue

            if not records:
                logger.warning(f"⚠ Нет валидных записей для {symbol}")
                return

            # Вставка с обработкой дубликатов
            inserted = 0
            for record in records:
                try:
                    cursor.execute(
                        f"""
                        INSERT OR REPLACE INTO {table_name} (
                            symbol, timestamp, open, high, low, close, volume, source, timeframe
                        ) VALUES (
                            :symbol, :timestamp, :open, :high, :low, :close, :volume, :source, :timeframe
                        )
                    """,
                        record,
                    )
                    inserted += 1
                except Exception as e:
                    logger.error(f"❌ Ошибка вставки: {e}")
                    self.stats["errors"] += 1

            conn.commit()
            self.stats["imported"] += inserted
            logger.info(f"✅ Импортировано {inserted} записей для {symbol}")

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения в БД: {e}")
            self.stats["errors"] += 1
        finally:
            conn.close()

    def download_fred(
        self,
        symbols: Optional[List[str]] = None,
        start_date: str = "1900-01-01",
        api_key: str = "",
    ) -> pd.DataFrame:
        """
        Загрузка данных из FRED (Federal Reserve Economic Data).

        Период: 1776–настоящее время (250+ лет)
        API key: https://fred.stlouisfed.org/docs/api/api_key.html

        Популярные series:
        - SP500: S&P 500 Index (с 1871)
        - DJIA: Dow Jones Industrial Average (с 1896)
        - GDP: Gross Domestic Product (с 1947)
        - CPIAUCSL: Consumer Price Index (с 1913)
        - DGS10: 10-Year Treasury Rate (с 1962)
        - FEDFUNDS: Federal Funds Rate (с 1954)
        - M2SL: M2 Money Stock (с 1959)
        - VIXCLS: VIX (с 1990)
        """
        logger.info("\n" + "=" * 70)
        logger.info("  ЗАГРУЗКА ДАННЫХ ИЗ FRED (Federal Reserve Economic Data)")
        logger.info("  Период: 1776–настоящее время (250+ лет)")
        logger.info("  840,000+ временных рядов")
        logger.info("=" * 70)

        try:
            from fredapi import Fred
        except ImportError:
            logger.error("❌ Установите fredapi: pip install fredapi")
            self.stats["errors"] += 1
            return pd.DataFrame()

        if not api_key:
            logger.warning("⚠ API ключ не указан.")
            logger.info("   Получите бесплатно: https://fred.stlouisfed.org/docs/api/api_key.html")
            return pd.DataFrame()

        fred = Fred(api_key=api_key)

        if symbols is None:
            symbols = [
                "SP500",  # S&P 500 (с 1871)
                "DJIA",  # Dow Jones (с 1896)
                "GDP",  # GDP (с 1947)
                "CPIAUCSL",  # CPI (с 1913)
                "DGS10",  # 10-Year Treasury (с 1962)
                "FEDFUNDS",  # Federal Funds Rate (с 1954)
                "M2SL",  # M2 Money Stock (с 1959)
                "T10Y2YM",  # 10-Year minus 2-Year Treasury
                "BAMLH0A0HYM2",  # High Yield OAS
                "VIXCLS",  # VIX (с 1990)
            ]

        all_data = pd.DataFrame()

        for symbol in symbols:
            try:
                logger.info(f"📥 Загрузка {symbol}...")
                series = fred.get_series(symbol, observation_start=start_date)

                if series.empty:
                    logger.warning(f"⚠ Нет данных для {symbol}")
                    continue

                # Конвертация в DataFrame
                df = series.reset_index()
                df.columns = ["timestamp", "close"]
                df["open"] = df["close"]
                df["high"] = df["close"]
                df["low"] = df["close"]
                df["volume"] = 0

                # Сохранение
                self._save_to_sqlite(df, symbol, source="FRED")
                self.stats["downloaded"] += 1
                self.stats["symbols"].append(symbol)

                logger.info(f"✅ {symbol}: {len(df)} записей ({df['timestamp'].min()} - {df['timestamp'].max()})")

                all_data = pd.concat([all_data, df], ignore_index=True)

                # Rate limiting
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"❌ Ошибка загрузки {symbol}: {e}")
                self.stats["errors"] += 1

        logger.info(f"\n✅ FRED: Загружено {self.stats['downloaded']} series, {len(all_data)} записей")
        return all_data

    def download_shiller(self, save_to_db: bool = True) -> pd.DataFrame:
        """
        Загрузка данных Shiller (CAPE ratio, S&P 500).

        Период: 1871–настоящее время (150+ лет)
        Источник: http://www.econ.yale.edu/~shiller/data.htm
        """
        logger.info("\n" + "=" * 70)
        logger.info("  ЗАГРУЗКА ДАННЫХ SHILLER (S&P 500, CAPE, Earnings, Dividends)")
        logger.info("  Период: 1871–настоящее время (150+ лет)")
        logger.info("=" * 70)

        try:
            # Прямая ссылка на данные Shiller
            excel_url = "https://www.albany.edu/~shiller/iedata.xls"
            logger.info(f"📥 Загрузка с {excel_url}...")

            df = pd.read_excel(excel_url, skiprows=8, header=0)

            logger.info(f"✅ Загружено {len(df)} строк")
            logger.info(f"   Колонки: {df.columns.tolist()}")

            # Обработка данных
            records = []
            for _, row in df.iterrows():
                try:
                    date_str = row.get("Date")
                    if pd.isna(date_str):
                        continue

                    # Парсинг даты (формат YYYY.MM)
                    if isinstance(date_str, float):
                        year = int(date_str)
                        month = int((date_str - year) * 100 + 0.5)
                        timestamp = pd.Timestamp(year=year, month=month, day=1)
                    else:
                        timestamp = pd.to_datetime(date_str)

                    record = {
                        "timestamp": timestamp,
                        "close": row.get("S&P Composite", 0),
                        "open": row.get("S&P Composite", 0),
                        "high": row.get("S&P Composite", 0),
                        "low": row.get("S&P Composite", 0),
                        "dividend": row.get("Dividend", 0),
                        "earnings": row.get("Earnings", 0),
                        "cpi": row.get("CPI", 0),
                        "long_interest_rate": row.get("Long Interest Rate", 0),
                        "real_price": row.get("Real Price", 0),
                        "real_earnings": row.get("Real Earnings", 0),
                        "real_dividend": row.get("Real Dividend", 0),
                        "volume": 0,
                    }
                    records.append(record)
                except Exception as e:
                    logger.warning(f"⚠ Ошибка обработки строки: {e}")

            result_df = pd.DataFrame(records)

            if save_to_db and not result_df.empty:
                # Сохранение основных цен
                price_df = result_df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
                self._save_to_sqlite(price_df, "SP500_Shiller", source="Shiller")

                self.stats["downloaded"] += 1
                self.stats["symbols"].append("SP500_Shiller")

            logger.info(
                f"\n✅ Shiller: {len(result_df)} записей " f"({result_df['timestamp'].min()} - {result_df['timestamp'].max()})"
            )

            return result_df

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки данных Shiller: {e}")
            return pd.DataFrame()

    def download_yfinance(
        self,
        symbols: Optional[List[str]] = None,
        start_date: str = "1970-01-01",
        end_date: Optional[str] = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Загрузка данных из Yahoo Finance через yfinance.

        Период: 1970–настоящее время (50+ лет)
        """
        logger.info("\n" + "=" * 70)
        logger.info("  ЗАГРУЗКА ДАННЫХ ИЗ YAHOO FINANCE (yfinance)")
        logger.info(f"  Период: {start_date}–{end_date or 'now'}")
        logger.info("=" * 70)

        try:
            import yfinance as yf
        except ImportError:
            logger.error("❌ Установите yfinance: pip install yfinance")
            self.stats["errors"] += 1
            return pd.DataFrame()

        if symbols is None:
            symbols = [
                "^GSPC",  # S&P 500
                "^DJI",  # Dow Jones
                "^IXIC",  # NASDAQ
                "GC=F",  # Gold
                "CL=F",  # Crude Oil
                "EURUSD=X",  # EUR/USD
                "GBPUSD=X",  # GBP/USD
                "USDJPY=X",  # USD/JPY
                "BTC-USD",  # Bitcoin
                "AAPL",  # Apple
                "MSFT",  # Microsoft
                "GOOGL",  # Google
                "AMZN",  # Amazon
                "SPY",  # S&P 500 ETF
                "QQQ",  # NASDAQ ETF
                "TLT",  # 20+ Year Treasury Bond ETF
                "GLD",  # Gold ETF
                "SLV",  # Silver ETF
            ]

        all_data = pd.DataFrame()

        for symbol in symbols:
            try:
                logger.info(f"📥 Загрузка {symbol}...")

                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start_date, end=end_date, interval=interval)

                if df.empty:
                    logger.warning(f"⚠ Нет данных для {symbol}")
                    continue

                # Сброс индекса
                df = df.reset_index()
                df.columns = [col.lower() if isinstance(col, str) else col for col in df.columns]

                # Сохранение
                self._save_to_sqlite(df, symbol, source="yfinance")
                self.stats["downloaded"] += 1
                self.stats["symbols"].append(symbol)

                logger.info(f"✅ {symbol}: {len(df)} записей ({df['date'].min()} - {df['date'].max()})")

                all_data = pd.concat([all_data, df], ignore_index=True)

                # Rate limiting
                time.sleep(1)

            except Exception as e:
                logger.error(f"❌ Ошибка загрузки {symbol}: {e}")
                self.stats["errors"] += 1

        logger.info(f"\n✅ yfinance: Загружено {self.stats['downloaded']} символов, {len(all_data)} записей")
        return all_data

    def download_stooq(
        self,
        symbols: Optional[List[str]] = None,
        timeframe: str = "d",  # d=daily, h=hourly, c=5min
    ) -> pd.DataFrame:
        """
        Загрузка данных из Stooq.

        Период: 1990–настоящее время (30+ лет)
        Формат: CSV (бесплатно, без регистрации)

        Символы:
        - Индексы: ^spx, ^dji, ^ndq
        - Акции: aapl.us, msft.us, googl.us
        - Forex: eurusd, gbpusd, usdjpy
        - Crypto: btcusd
        """
        logger.info("\n" + "=" * 70)
        logger.info("  ЗАГРУЗКА ДАННЫХ ИЗ STOOQ")
        logger.info("  Период: 1990–настоящее время (30+ лет)")
        logger.info("  Формат: CSV (бесплатно)")
        logger.info("=" * 70)

        if symbols is None:
            symbols = [
                "^spx",  # S&P 500
                "^dji",  # Dow Jones
                "^ndq",  # NASDAQ 100
                "usdx",  # US Dollar Index
                "eurusd",  # EUR/USD
                "gbpusd",  # GBP/USD
                "usdjpy",  # USD/JPY
                "aapl.us",  # Apple
                "msft.us",  # Microsoft
                "googl.us",  # Google
                "amzn.us",  # Amazon
                "tsla.us",  # Tesla
                "btcusd",  # Bitcoin
            ]

        all_data = pd.DataFrame()

        for symbol in symbols:
            try:
                # Формирование URL
                url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
                logger.info(f"📥 Загрузка {symbol}...")

                # Загрузка CSV
                df = pd.read_csv(url)

                if df.empty:
                    logger.warning(f"⚠ Нет данных для {symbol}")
                    continue

                logger.info(f"   Колонки: {df.columns.tolist()}")
                logger.info(f"   Первые строки:\n{df.head(3)}")

                # Stooq возвращает Date и Time как отдельные колонки
                if "Date" in df.columns and "Time" in df.columns:
                    df["timestamp"] = df["Date"].astype(str) + " " + df["Time"].astype(str)
                elif "Date" in df.columns:
                    df["timestamp"] = df["Date"].astype(str)
                elif "date" in df.columns and "time" in df.columns:
                    df["timestamp"] = df["date"].astype(str) + " " + df["time"].astype(str)
                elif "date" in df.columns:
                    df["timestamp"] = df["date"].astype(str)
                else:
                    logger.error(f"❌ Не найдена колонка даты для {symbol}")
                    continue

                df.columns = [col.lower().strip() if isinstance(col, str) else col for col in df.columns]

                # Фильтрация невалидных данных
                df = df[~df["timestamp"].str.contains("N/D|N/A", na=False)]

                logger.info(f"   После обработки: {len(df)} записей")

                if df.empty:
                    logger.warning(f"⚠ Нет валидных данных для {symbol}")
                    continue

                # Сохранение
                self._save_to_sqlite(df, symbol, source="Stooq")
                self.stats["downloaded"] += 1
                self.stats["symbols"].append(symbol)

                logger.info(f"✅ {symbol}: {len(df)} записей")

                all_data = pd.concat([all_data, df], ignore_index=True)

                # Rate limiting
                time.sleep(1)

            except Exception as e:
                logger.error(f"❌ Ошибка загрузки {symbol}: {e}")
                self.stats["errors"] += 1

        logger.info(f"\n✅ Stooq: Загружено {self.stats['downloaded']} символов, {len(all_data)} записей")
        return all_data

    def download_nber(self, save_to_db: bool = True) -> pd.DataFrame:
        """
        Загрузка NBER Macrohistory Database.

        Период: 1860–1991 (130+ лет)
        Источник: Kaggle (требуется регистрация)
        """
        logger.info("\n" + "=" * 70)
        logger.info("  ЗАГРУЗКА NBER MACROHISTORY DATABASE")
        logger.info("  Период: 1860–1991 (130+ лет)")
        logger.info("  Источник: Kaggle")
        logger.info("=" * 70)

        try:
            import kaggle
        except ImportError:
            logger.error("❌ Установите kaggle: pip install kaggle")
            logger.info("   Требуется регистрация на Kaggle и API ключ")
            self.stats["errors"] += 1
            return pd.DataFrame()

        try:
            logger.info("📥 Загрузка датасета NBER Macrohistory...")

            # Загрузка через Kaggle API
            kaggle.api.dataset_download_files(
                "sohier/nber-macrohistory-database",
                path="data/nber",
                unzip=True,
            )

            # Чтение загруженных файлов
            data_dir = Path("data/nber")
            all_data = pd.DataFrame()

            if data_dir.exists():
                for csv_file in data_dir.glob("*.csv"):
                    try:
                        logger.info(f"📄 Чтение {csv_file.name}...")
                        df = pd.read_csv(csv_file)

                        # Сохранение
                        symbol = csv_file.stem
                        self._save_to_sqlite(df, symbol, source="NBER")
                        self.stats["downloaded"] += 1
                        self.stats["symbols"].append(symbol)

                        all_data = pd.concat([all_data, df], ignore_index=True)

                    except Exception as e:
                        logger.error(f"❌ Ошибка чтения {csv_file.name}: {e}")

            logger.info(f"\n✅ NBER: Загружено {self.stats['downloaded']} файлов, {len(all_data)} записей")
            return all_data

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки NBER: {e}")
            self.stats["errors"] += 1
            return pd.DataFrame()

    def download_bulk(
        self,
        fred_api_key: str = "",
    ):
        """
        Массовая загрузка данных из всех источников.
        """
        logger.info("\n" + "█" * 70)
        logger.info("  МАССОВАЯ ЗАГРУЗКА ИСТОРИЧЕСКИХ ДАННЫХ")
        logger.info("  Источники: FRED, Shiller, yfinance, Stooq")
        logger.info("  Ожидаемый период: 100+ лет")
        logger.info("█" * 70)

        # 1. FRED
        if fred_api_key:
            try:
                self.download_fred(api_key=fred_api_key)
            except Exception as e:
                logger.error(f"❌ Ошибка FRED: {e}")
        else:
            logger.warning("⚠ Пропуск FRED (нет API key)")

        # 2. Shiller
        try:
            self.download_shiller()
        except Exception as e:
            logger.error(f"❌ Ошибка Shiller: {e}")

        # 3. yfinance
        try:
            self.download_yfinance()
        except Exception as e:
            logger.error(f"❌ Ошибка yfinance: {e}")

        # 4. Stooq
        try:
            self.download_stooq()
        except Exception as e:
            logger.error(f"❌ Ошибка Stooq: {e}")

        # Итоговый отчет
        self._print_summary()

    def _print_summary(self):
        """Вывод итогового отчета."""
        logger.info("\n" + "=" * 70)
        logger.info("  ИТОГОВЫЙ ОТЧЕТ ПО ЗАГРУЗКЕ ДАННЫХ")
        logger.info("=" * 70)
        logger.info(f"  ✅ Загружено источников: {self.stats['downloaded']}")
        logger.info(f"  ✅ Импортировано записей: {self.stats['imported']}")
        logger.info(f"  ⚠ Пропущено: {self.stats['skipped']}")
        logger.info(f"  ❌ Ошибок: {self.stats['errors']}")
        logger.info(f"  📊 Символы: {', '.join(self.stats['symbols'][:10])}")
        if len(self.stats["symbols"]) > 10:
            logger.info(f"     ... и ещё {len(self.stats['symbols']) - 10}")
        logger.info("=" * 70)


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(
        description="Загрузка долгосрочных исторических данных в Genesis Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Загрузка данных FRED
  python download_historical_data.py --source fred --api-key YOUR_KEY

  # Загрузка данных Shiller
  python download_historical_data.py --source shiller

  # Загрузка конкретных символов из yfinance
  python download_historical_data.py --source yfinance --symbol AAPL MSFT GOOGL

  # Загрузка из Stooq
  python download_historical_data.py --source stooq --symbol ^spx eurusd

  # Массовая загрузка всех данных
  python download_historical_data.py --source all --bulk --api-key YOUR_KEY

  # Загрузка NBER через Kaggle
  python download_historical_data.py --source nber
        """,
    )

    parser.add_argument(
        "--source",
        type=str,
        required=True,
        choices=["fred", "shiller", "yfinance", "stooq", "nber", "all"],
        help="Источник данных",
    )

    parser.add_argument("--symbol", nargs="+", help="Список символов для загрузки")
    parser.add_argument("--start", default="1900-01-01", help="Начальная дата (YYYY-MM-DD)")
    parser.add_argument("--end", help="Конечная дата (YYYY-MM-DD)")
    parser.add_argument("--api-key", default="", help="API ключ (FRED, Kaggle)")
    parser.add_argument("--bulk", action="store_true", help="Массовая загрузка")
    parser.add_argument("--db", default="F:/Enjen/database/trading_system.db", help="Путь к БД Genesis")

    args = parser.parse_args()

    # Создание загрузчика
    downloader = HistoricalDataDownloader(genesis_db_path=args.db)

    # Загрузка в зависимости от источника
    if args.source == "fred":
        downloader.download_fred(symbols=args.symbol, start_date=args.start, api_key=args.api_key)
    elif args.source == "shiller":
        downloader.download_shiller()
    elif args.source == "yfinance":
        downloader.download_yfinance(symbols=args.symbol, start_date=args.start, end_date=args.end)
    elif args.source == "stooq":
        downloader.download_stooq(symbols=args.symbol)
    elif args.source == "nber":
        downloader.download_nber()
    elif args.source == "all":
        downloader.download_bulk(fred_api_key=args.api_key)

    # Итоговый отчет
    downloader._print_summary()

    return 0 if downloader.stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
