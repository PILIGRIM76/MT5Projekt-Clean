#!/usr/bin/env python3
"""
Импорт данных из других SQLite баз данных в основную Genesis БД.

Использование:
    python scripts/import_from_sqlite.py --source /path/to/source.db --genesis-db F:/Enjen/database/trading_system.db
"""

import argparse
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_table_info(conn: sqlite3.Connection, table_name: str) -> list:
    """Получить информацию о колонках таблицы."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return cursor.fetchall()


def import_table(source_db: str, target_db: str, table_name: str) -> int:
    """Импорт таблицы из одной БД в другую."""
    logger.info(f"  Импорт таблицы: {table_name}")

    source_conn = sqlite3.connect(source_db)
    target_conn = sqlite3.connect(target_db)
    source_conn.row_factory = sqlite3.Row
    target_cur = target_conn.cursor()

    try:
        # Получаем информацию о колонках
        source_cols = get_table_info(source_conn, table_name)
        target_cols = get_table_info(target_conn, table_name)

        if not source_cols:
            logger.warning(f"    ⚠ Таблица {table_name} не найдена в источнике")
            return 0

        if not target_cols:
            logger.warning(f"    ⚠ Таблица {table_name} не найдена в цели")
            return 0

        # Получаем имена колонок
        source_col_names = [col[1] for col in source_cols]
        target_col_names = [col[1] for col in target_cols]

        # Находим общие колонки
        common_cols = [col for col in source_col_names if col in target_col_names]

        if not common_cols:
            logger.warning(f"    ⚠ Нет общих колонок между таблицами")
            return 0

        # Читаем данные из источника
        source_cursor = source_conn.execute(f"SELECT {', '.join(common_cols)} FROM {table_name}")
        rows = source_cursor.fetchall()

        if not rows:
            logger.info(f"    Таблица пуста")
            return 0

        logger.info(f"    Найдено {len(rows)} записей")

        # Вставляем в цель
        placeholders = ", ".join(["?" for _ in common_cols])
        insert_sql = f"INSERT OR REPLACE INTO {table_name} ({', '.join(common_cols)}) VALUES ({placeholders})"

        imported = 0
        for row in rows:
            try:
                target_cur.execute(insert_sql, list(row))
                imported += 1
            except Exception as e:
                logger.debug(f"    Ошибка вставки: {e}")

        target_conn.commit()
        logger.info(f"    ✅ Импортировано {imported}/{len(rows)} записей")
        return imported

    except Exception as e:
        logger.error(f"    ❌ Ошибка импорта: {e}")
        return 0
    finally:
        source_conn.close()
        target_conn.close()


def main():
    parser = argparse.ArgumentParser(description="Импорт из SQLite в Genesis")
    parser.add_argument("--source", required=True, help="Путь к исходной БД")
    parser.add_argument("--genesis-db", default="F:/Enjen/database/trading_system.db", help="Путь к Genesis БД")
    parser.add_argument("--tables", nargs="+", help="Таблицы для импорта (все если не указано)")

    args = parser.parse_args()

    source_path = Path(args.source)
    if not source_path.exists():
        logger.error(f"❌ Исходная БД не найдена: {source_path}")
        return 1

    target_path = Path(args.genesis_db)
    if not target_path.exists():
        logger.error(f"❌ Genesis БД не найдена: {target_path}")
        return 1

    logger.info("\n" + "=" * 60)
    logger.info("  ИМПОРТ ДАННЫХ ИЗ SQLITE В GENESIS")
    logger.info("=" * 60)
    logger.info(f"  Источник: {source_path}")
    logger.info(f"  Цель: {target_path}")
    logger.info("=" * 60 + "\n")

    # Получаем список таблиц в источнике
    source_conn = sqlite3.connect(source_path)
    cursor = source_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    source_conn.close()

    logger.info(f"Таблицы в источнике: {', '.join(tables)}\n")

    # Фильтруем таблицы если указаны
    if args.tables:
        tables = [t for t in tables if t in args.tables]

    # Импортируем каждую таблицу
    total_imported = 0
    for table in tables:
        if table.startswith("sqlite_"):
            continue

        imported = import_table(args.source, args.genesis_db, table)
        total_imported += imported

    logger.info("\n" + "=" * 60)
    logger.info(f"  ИТОГО: Импортировано {total_imported} записей")
    logger.info("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    exit(main())
