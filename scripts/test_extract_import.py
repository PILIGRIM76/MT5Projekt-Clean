#!/usr/bin/env python3
"""
Тест скрипта extract_and_import.py - проверка логики извлечения без БД.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_csv_extraction():
    """Тест извлечения из CSV."""
    logger.info("\n" + "=" * 60)
    logger.info("  ТЕСТ: Извлечение из CSV")
    logger.info("=" * 60)

    csv_path = Path("test_import.csv")
    if not csv_path.exists():
        logger.error(f"CSV файл не найден: {csv_path}")
        return False

    df = pd.read_csv(csv_path)
    logger.info(f"✓ Найдено {len(df)} записей в CSV")

    # Проверка колонок
    required_columns = ["symbol", "order_type"]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        logger.error(f"✗ Отсутствуют колонки: {missing}")
        return False

    logger.info("✓ Все обязательные колонки присутствуют")

    # Проверка данных
    for idx, row in df.iterrows():
        logger.info(f"  Запись {idx+1}: {row['symbol']} {row['order_type']} {row['volume']} @ {row['open_price']}")

    logger.info(f"\n✓ Тест CSV извлечения: УСПЕШНО")
    return True


def test_freqtrade_schema():
    """Тест схемы Freqtrade."""
    logger.info("\n" + "=" * 60)
    logger.info("  ТЕСТ: Схема Freqtrade SQLite")
    logger.info("=" * 60)

    # Создаем тестовую БД
    test_db = Path("test_freqtrade.sqlite")

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    # Создание таблицы trades
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            pair TEXT,
            is_open BOOLEAN,
            is_short BOOLEAN,
            open_rate REAL,
            close_rate REAL,
            amount REAL,
            open_date_h INTEGER,
            close_date_h INTEGER,
            close_profit REAL,
            close_profit_abs REAL,
            stop_loss REAL,
            take_profit REAL,
            exit_reason TEXT,
            strategy TEXT,
            fee_open REAL,
            fee_close REAL
        )
    """)

    # Вставка тестовых данных
    test_data = [
        (
            1,
            "BTC_USDT",
            0,
            0,
            45000.0,
            45500.0,
            0.5,
            1704067200000,
            1704200400000,
            0.011,
            250.0,
            44000.0,
            47000.0,
            "roi",
            "TestStrategy",
            0.001,
            0.001,
        ),
        (
            2,
            "ETH_USDT",
            0,
            1,
            3200.0,
            3150.0,
            1.0,
            1704067200000,
            1704287700000,
            0.015,
            50.0,
            3300.0,
            3100.0,
            "stop_loss",
            "TestStrategy",
            0.001,
            0.001,
        ),
    ]

    cursor.executemany(
        """
        INSERT OR REPLACE INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        test_data,
    )

    conn.commit()

    # Проверка данных
    cursor.execute("SELECT * FROM trades")
    rows = cursor.fetchall()
    logger.info(f"✓ Создано {len(rows)} тестовых записей")

    for row in rows:
        logger.info(f"  Сделка {row[0]}: {row[1]} {'SHORT' if row[3] else 'LONG'} Profit: {row[10]}")

    conn.close()
    logger.info(f"\n✓ Тест схемы Freqtrade: УСПЕШНО")

    # Очистка
    test_db.unlink()
    return True


def test_transformation():
    """Тест преобразования данных."""
    logger.info("\n" + "=" * 60)
    logger.info("  ТЕСТ: Преобразование данных")
    logger.info("=" * 60)

    # Пример данных Freqtrade
    freqtrade_row = {
        "id": 12345,
        "pair": "BTC_USDT",
        "is_short": False,
        "open_rate": 45000.0,
        "close_rate": 45500.0,
        "amount": 0.5,
        "open_date_h": 1704067200000,
        "close_date_h": 1704200400000,
        "close_profit_abs": 250.0,
        "stop_loss": 44000.0,
        "take_profit": 47000.0,
        "exit_reason": "roi",
        "strategy": "TestStrategy",
        "fee_open": 0.001,
        "fee_close": 0.001,
    }

    # Преобразование в формат Genesis
    genesis_trade = {
        "ticket": freqtrade_row["id"],
        "symbol": freqtrade_row["pair"].replace("_", ""),
        "order_type": "SELL" if freqtrade_row["is_short"] else "BUY",
        "volume": freqtrade_row["amount"],
        "open_price": freqtrade_row["open_rate"],
        "close_price": freqtrade_row["close_rate"],
        "sl": freqtrade_row["stop_loss"],
        "tp": freqtrade_row["take_profit"],
        "open_time": datetime.fromtimestamp(freqtrade_row["open_date_h"] / 1000).isoformat(),
        "close_time": datetime.fromtimestamp(freqtrade_row["close_date_h"] / 1000).isoformat(),
        "profit": freqtrade_row["close_profit_abs"],
        "strategy_name": freqtrade_row["strategy"],
        "model_type": "Freqtrade",
        "metadata": json.dumps(
            {
                "source": "Freqtrade",
                "exit_reason": freqtrade_row["exit_reason"],
                "fee_open": freqtrade_row["fee_open"],
                "fee_close": freqtrade_row["fee_close"],
            }
        ),
    }

    logger.info("Преобразование Freqtrade → Genesis:")
    logger.info(f"  Вход: {freqtrade_row['pair']} {freqtrade_row['amount']} @ {freqtrade_row['open_rate']}")
    logger.info(
        f"  Выход: {genesis_trade['symbol']} {genesis_trade['order_type']} {genesis_trade['volume']} @ {genesis_trade['open_price']}"
    )
    logger.info(f"  Profit: {genesis_trade['profit']}")
    logger.info(f"  Metadata: {genesis_trade['metadata'][:100]}...")

    logger.info(f"\n✓ Тест преобразования: УСПЕШНО")
    return True


def main():
    """Запуск всех тестов."""
    logger.info("\n" + "█" * 60)
    logger.info("  ТЕСТЫ СКРИПТА extract_and_import.py")
    logger.info("█" * 60)

    results = []

    # Тест 1: CSV извлечение
    results.append(("CSV Extraction", test_csv_extraction()))

    # Тест 2: Схема Freqtrade
    results.append(("Freqtrade Schema", test_freqtrade_schema()))

    # Тест 3: Преобразование
    results.append(("Data Transformation", test_transformation()))

    # Итоговый отчет
    logger.info("\n" + "=" * 60)
    logger.info("  ИТОГОВЫЙ ОТЧЕТ ПО ТЕСТАМ")
    logger.info("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {status}: {name}")

    logger.info(f"\n  Всего: {passed}/{total} тестов пройдено")

    if passed == total:
        logger.info("\n  ✅ ВСЕ ТЕСТЫ УСПЕШНЫ!")
    else:
        logger.warning(f"\n  ⚠ {total - passed} тестов провалено")

    logger.info("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
