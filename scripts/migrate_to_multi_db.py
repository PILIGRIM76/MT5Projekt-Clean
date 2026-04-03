#!/usr/bin/env python3
"""
Скрипт миграции данных из SQLite в PostgreSQL + TimescaleDB + Qdrant.

Использование:
    python scripts/migrate_to_multi_db.py

Скрипт:
1. Подключается к существующей SQLite базе
2. Извлекает все данные
3. Переносит в соответствующие новые базы данных:
   - PostgreSQL: позиции, аудит, стратегии, директивы
   - TimescaleDB: свечные данные
   - Qdrant: векторы (если есть сохраненные эмбеддинги)
"""

import logging
import pickle
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class SQLiteToMultiDBMigrator:
    """Миграция данных из SQLite в мульти-базовую архитектуру."""

    def __init__(
        self,
        sqlite_path: str = "database/trading_system.db",
        postgres_url: str = None,
        timescaledb_url: str = None,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
    ):
        self.sqlite_path = Path(sqlite_path)

        # PostgreSQL подключение
        self.postgres_url = postgres_url or ("postgresql://trading_user:secure_password@localhost:5432/trading")

        # TimescaleDB подключение
        self.timescaledb_url = timescaledb_url or ("postgresql://trading_user:secure_password@localhost:5433/trading_ts")

        # Qdrant подключение
        self.qdrant_host = qdrant_host
        self.qdrant_port = qdrant_port

        # Счетчики миграции
        self.stats = {
            "sqlite_tables": 0,
            "postgres_rows": 0,
            "timescaledb_rows": 0,
            "qdrant_vectors": 0,
            "errors": 0,
        }

    def check_sqlite_exists(self) -> bool:
        """Проверка существования SQLite базы."""
        if not self.sqlite_path.exists():
            logger.warning(f"SQLite база не найдена: {self.sqlite_path}")
            return False

        logger.info(f"✓ SQLite база найдена: {self.sqlite_path}")
        return True

    def get_sqlite_tables(self) -> List[str]:
        """Получение списка таблиц в SQLite."""
        conn = sqlite3.connect(self.sqlite_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name;
        """)

        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        self.stats["sqlite_tables"] = len(tables)
        logger.info(f"Найдено таблиц в SQLite: {len(tables)}")
        logger.info(f"Таблицы: {', '.join(tables)}")

        return tables

    def migrate_to_postgresql(self):
        """Миграция реляционных данных в PostgreSQL."""
        logger.info("\n" + "=" * 60)
        logger.info("  Миграция в PostgreSQL")
        logger.info("=" * 60)

        if not self.check_sqlite_exists():
            logger.warning("Пропуск миграции в PostgreSQL - SQLite не найден")
            return

        # Подключение к SQLite
        sqlite_conn = sqlite3.connect(self.sqlite_path)

        # Подключение к PostgreSQL
        postgres_engine = create_engine(self.postgres_url)

        # Таблицы для миграции
        tables_to_migrate = [
            "active_positions",
            "trade_history",
            "trade_audit",
            "strategy_performance",
            "active_directives",
            "human_feedback",
            "news_articles",
            "entities",
            "relations",
            "trained_models",
            "scalers",
        ]

        for table_name in tables_to_migrate:
            try:
                logger.info(f"Миграция таблицы: {table_name}")

                # Чтение из SQLite
                query = f"SELECT * FROM {table_name}"
                df = pd.read_sql_query(query, sqlite_conn)

                if df.empty:
                    logger.info(f"  Таблица {table_name} пуста")
                    continue

                logger.info(f"  Найдено {len(df)} записей")

                # Вставка в PostgreSQL
                df.to_sql(
                    table_name,
                    postgres_engine,
                    if_exists="append",
                    index=False,
                    method="multi",
                    chunksize=1000,
                )

                self.stats["postgres_rows"] += len(df)
                logger.info(f"  ✓ Мигрировано {len(df)} записей в PostgreSQL")

            except Exception as e:
                logger.error(f"  ✗ Ошибка миграции {table_name}: {e}")
                self.stats["errors"] += 1

        sqlite_conn.close()
        logger.info(f"\nВсего мигрировано в PostgreSQL: {self.stats['postgres_rows']} записей")

    def migrate_to_timescaledb(self):
        """Миграция свечных данных в TimescaleDB."""
        logger.info("\n" + "=" * 60)
        logger.info("  Миграция в TimescaleDB")
        logger.info("=" * 60)

        if not self.check_sqlite_exists():
            logger.warning("Пропуск миграции в TimescaleDB - SQLite не найден")
            return

        # Подключение к SQLite
        sqlite_conn = sqlite3.connect(self.sqlite_path)

        # Подключение к TimescaleDB
        ts_engine = create_engine(self.timescaledb_url)

        try:
            logger.info("Миграция таблицы: candle_data")

            # Чтение из SQLite
            query = "SELECT * FROM candle_data"
            df = pd.read_sql_query(query, sqlite_conn)

            if df.empty:
                logger.info("  Таблица candle_data пуста")
                return

            logger.info(f"  Найдено {len(df)} свечей")

            # Преобразование формата
            # SQLite: timeframe как строка ('M1', 'H1')
            # TimescaleDB: timeframe как секунды (60, 3600)
            def timeframe_to_seconds(tf: str) -> int:
                mapping = {
                    "M1": 60,
                    "M5": 300,
                    "M15": 900,
                    "M30": 1800,
                    "H1": 3600,
                    "H4": 14400,
                    "D1": 86400,
                    "W1": 604800,
                    "MN1": 2592000,
                }
                return mapping.get(tf, 60)

            df["timeframe"] = df["timeframe"].apply(timeframe_to_seconds)

            # Переименование колонок
            df = df.rename(
                columns={
                    "tick_volume": "volume",  # В TimescaleDB просто volume
                }
            )

            # Добавление created_at если нет
            if "created_at" not in df.columns:
                df["created_at"] = datetime.utcnow()

            # Выбор нужных колонок
            columns = [
                "symbol",
                "timeframe",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "tick_volume",
                "spread",
                "created_at",
            ]

            # Добавление spread если нет
            if "spread" not in df.columns:
                df["spread"] = 0

            df = df[[c for c in columns if c in df.columns]]

            # Вставка в TimescaleDB
            df.to_sql(
                "candle_data",
                ts_engine,
                if_exists="append",
                index=True,
                index_label="timestamp",
                method="multi",
                chunksize=1000,
            )

            self.stats["timescaledb_rows"] += len(df)
            logger.info(f"  ✓ Мигрировано {len(df)} свечей в TimescaleDB")

        except Exception as e:
            logger.error(f"  ✗ Ошибка миграции candle_data: {e}")
            self.stats["errors"] += 1

        sqlite_conn.close()
        logger.info(f"\nВсего мигрировано в TimescaleDB: {self.stats['timescaledb_rows']} записей")

    def migrate_to_qdrant(self):
        """Миграция векторных данных в Qdrant."""
        logger.info("\n" + "=" * 60)
        logger.info("  Миграция в Qdrant")
        logger.info("=" * 60)

        if not self.check_sqlite_exists():
            logger.warning("Пропуск миграции в Qdrant - SQLite не найден")
            return

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import PointStruct
        except ImportError:
            logger.warning("qdrant-client не установлен. Пропуск миграции в Qdrant.")
            return

        # Подключение к SQLite
        sqlite_conn = sqlite3.connect(self.sqlite_path)

        # Подключение к Qdrant
        qdrant_client = QdrantClient(
            host=self.qdrant_host,
            port=self.qdrant_port,
        )

        # Проверка существования коллекции
        collection_name = "trading_rag"
        collections = qdrant_client.get_collections()

        if not any(c.name == collection_name for c in collections.collections):
            logger.info(f"Создание коллекции: {collection_name}")
            from qdrant_client.http.models import Distance, VectorParams

            qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )

        # Миграция новостей с эмбеддингами
        try:
            logger.info("Миграция новостей из news_articles")

            query = """
                SELECT id, vector_id, content, source, timestamp,
                       sentiment_score, sentiment_label
                FROM news_articles
            """
            df = pd.read_sql_query(query, sqlite_conn)

            if df.empty:
                logger.info("  Таблица news_articles пуста")
            else:
                logger.info(f"  Найдено {len(df)} новостей")

                # Для каждой новости нужен вектор
                # Если векторы не сохранены, пропускаем
                # (в реальной системе нужно будет перегенерировать эмбеддинги)
                logger.warning("  ⚠ Для миграции в Qdrant нужны эмбеддинги!")
                logger.warning("  Пропуск миграции векторов (требуется перегенерация)")

        except Exception as e:
            logger.error(f"  ✗ Ошибка миграции в Qdrant: {e}")
            self.stats["errors"] += 1

        sqlite_conn.close()
        logger.info(f"\nВсего мигрировано в Qdrant: {self.stats['qdrant_vectors']} векторов")

    def run_migration(self):
        """Запуск полной миграции."""
        logger.info("\n" + "█" * 60)
        logger.info("  Genesis Trading System - Миграция данных")
        logger.info("  SQLite → PostgreSQL + TimescaleDB + Qdrant")
        logger.info("█" * 60)

        start_time = datetime.now()

        # Миграция в PostgreSQL
        self.migrate_to_postgresql()

        # Миграция в TimescaleDB
        self.migrate_to_timescaledb()

        # Миграция в Qdrant
        self.migrate_to_qdrant()

        # Итоговый отчет
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("\n" + "=" * 60)
        logger.info("  ИТОГОВЫЙ ОТЧЕТ ПО МИГРАЦИИ")
        logger.info("=" * 60)
        logger.info(f"  Время выполнения: {duration:.2f} сек")
        logger.info(f"  Таблиц в SQLite: {self.stats['sqlite_tables']}")
        logger.info(f"  Записей в PostgreSQL: {self.stats['postgres_rows']}")
        logger.info(f"  Записей в TimescaleDB: {self.stats['timescaledb_rows']}")
        logger.info(f"  Векторов в Qdrant: {self.stats['qdrant_vectors']}")
        logger.info(f"  Ошибок: {self.stats['errors']}")

        if self.stats["errors"] == 0:
            logger.info("\n  ✅ Миграция завершена успешно!")
        else:
            logger.warning(f"\n  ⚠ Миграция завершена с {self.stats['errors']} ошибками")

        logger.info("\n" + "█" * 60 + "\n")


def main():
    """Главная функция."""
    import argparse

    parser = argparse.ArgumentParser(description="Миграция данных из SQLite в мульти-базовую архитектуру")

    parser.add_argument("--sqlite-path", default="database/trading_system.db", help="Путь к SQLite базе")

    parser.add_argument("--postgres-url", default=None, help="PostgreSQL connection URL")

    parser.add_argument("--timescaledb-url", default=None, help="TimescaleDB connection URL")

    parser.add_argument("--qdrant-host", default="localhost", help="Qdrant host")

    parser.add_argument("--qdrant-port", type=int, default=6333, help="Qdrant port")

    parser.add_argument("--dry-run", action="store_true", help="Тестовый запуск без записи")

    args = parser.parse_args()

    # Создание мигратора
    migrator = SQLiteToMultiDBMigrator(
        sqlite_path=args.sqlite_path,
        postgres_url=args.postgres_url,
        timescaledb_url=args.timescaledb_url,
        qdrant_host=args.qdrant_host,
        qdrant_port=args.qdrant_port,
    )

    # Запуск миграции
    if args.dry_run:
        logger.info("DRY RUN - только проверка без записи")
        migrator.check_sqlite_exists()
        migrator.get_sqlite_tables()
    else:
        migrator.run_migration()


if __name__ == "__main__":
    main()
