#!/usr/bin/env python3
"""
Экспорт данных из баз данных Genesis Trading System.

Извлекает данные из всех подключенных БД:
- PostgreSQL (реляционные данные: позиции, аудит, стратегии)
- TimescaleDB (временные ряды: свечи, тики)
- QuestDB (альтернатива TimescaleDB)
- Qdrant (векторы: новости, паттерны)
- Redis (кэш, метрики)
- SQLite (локальные данные)

Использование:
    python scripts/export_genesis_databases.py --output genesis_backup.json
    python scripts/export_genesis_databases.py --db postgres --output postgres_export.json
    python scripts/export_genesis_databases.py --db timescaledb --output candles_export.json
"""

import argparse
import json
import logging
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class GenesisDatabaseExporter:
    """Экспорт данных из всех баз данных Genesis Trading System."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._load_default_config()
        self.stats = {
            "exported_tables": 0,
            "exported_rows": 0,
            "exported_vectors": 0,
            "errors": 0,
        }
        self.exported_data = {
            "postgres": {},
            "timescaledb": {},
            "questdb": {},
            "qdrant": {},
            "redis": {},
            "sqlite": {},
        }

    def _load_default_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации по умолчанию из переменных окружения."""
        return {
            # PostgreSQL
            "postgres_host": os.getenv("POSTGRES_HOST", "localhost"),
            "postgres_port": int(os.getenv("POSTGRES_PORT", "5432")),
            "postgres_db": os.getenv("POSTGRES_DB", "trading"),
            "postgres_user": os.getenv("POSTGRES_USER", "trading_user"),
            "postgres_password": os.getenv("POSTGRES_PASSWORD", "secure_password"),
            # TimescaleDB
            "timescaledb_host": os.getenv("TIMESCALEDB_HOST", "localhost"),
            "timescaledb_port": int(os.getenv("TIMESCALEDB_PORT", "5433")),
            "timescaledb_db": os.getenv("TIMESCALEDB_DB", "trading_ts"),
            "timescaledb_user": os.getenv("TIMESCALEDB_USER", "trading_user"),
            "timescaledb_password": os.getenv("TIMESCALEDB_PASSWORD", "secure_password"),
            # QuestDB
            "questdb_host": os.getenv("QUESTDB_HOST", "localhost"),
            "questdb_port": int(os.getenv("QUESTDB_PORT", "9000")),
            "questdb_user": os.getenv("QUESTDB_USER", "admin"),
            "questdb_password": os.getenv("QUESTDB_PASSWORD", "quest"),
            # Qdrant
            "qdrant_host": os.getenv("QDRANT_HOST", "localhost"),
            "qdrant_port": int(os.getenv("QDRANT_PORT", "6333")),
            # Redis
            "redis_host": os.getenv("REDIS_HOST", "localhost"),
            "redis_port": int(os.getenv("REDIS_PORT", "6379")),
            # SQLite
            "sqlite_path": os.getenv("SQLITE_PATH", "database/trading_system.db"),
        }

    # ========================================================================
    # POSTGRESQL EXPORT
    # ========================================================================
    def export_from_postgres(self, tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Экспорт данных из PostgreSQL.

        Таблицы:
        - users, active_positions, trade_history, trade_audit
        - strategy_performance, human_feedback, active_directives
        - news_articles, entities, relations
        - trained_models, scalers, system_metrics
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из PostgreSQL")
        logger.info("=" * 60)

        try:
            from sqlalchemy import create_engine, inspect, text
            from sqlalchemy.orm import sessionmaker

            # Подключение
            connection_url = (
                f"postgresql://{self.config['postgres_user']}:"
                f"{self.config['postgres_password']}@"
                f"{self.config['postgres_host']}:"
                f"{self.config['postgres_port']}/"
                f"{self.config['postgres_db']}"
            )

            logger.info(f"Подключение к PostgreSQL: {self.config['postgres_host']}:{self.config['postgres_port']}")

            engine = create_engine(connection_url)

            # Проверка подключения
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✓ PostgreSQL подключен")

            # Получение списка таблиц
            inspector = inspect(engine)
            available_tables = inspector.get_table_names()
            logger.info(f"Найдено таблиц: {len(available_tables)}")
            logger.info(f"Таблицы: {', '.join(available_tables)}")

            # Фильтрация таблиц
            if tables:
                tables_to_export = [t for t in available_tables if t in tables]
            else:
                tables_to_export = available_tables

            # Экспорт каждой таблицы
            for table_name in tables_to_export:
                try:
                    logger.info(f"Экспорт таблицы: {table_name}")

                    query = text(f"SELECT * FROM {table_name}")
                    df = pd.read_sql_query(query, engine)

                    self.exported_data["postgres"][table_name] = {
                        "columns": list(df.columns),
                        "row_count": len(df),
                        "data": df.to_dict("records"),
                        "exported_at": datetime.utcnow().isoformat(),
                    }

                    self.stats["exported_tables"] += 1
                    self.stats["exported_rows"] += len(df)

                    logger.info(f"  ✓ Экспортировано {len(df)} записей")

                except Exception as e:
                    logger.error(f"  ✗ Ошибка экспорта таблицы {table_name}: {e}")
                    self.stats["errors"] += 1

            logger.info(
                f"\nВсего экспортировано из PostgreSQL: {len(tables_to_export)} таблиц, {self.stats['exported_rows']} записей"
            )

        except Exception as e:
            logger.error(f"Ошибка экспорта из PostgreSQL: {e}")
            self.stats["errors"] += 1
            self.exported_data["postgres"]["error"] = str(e)

        return self.exported_data["postgres"]

    # ========================================================================
    # TIMESCALEDB EXPORT
    # ========================================================================
    def export_from_timescaledb(self, tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Экспорт данных из TimescaleDB.

        Hypertables:
        - candle_data (OHLCV свечи)
        - tick_data (тиковые данные)
        - orderbook_data (стакан заявок)

        Continuous Aggregates:
        - candle_data_1h (часовые агрегаты)
        - candle_data_1d (дневные агрегаты)
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из TimescaleDB")
        logger.info("=" * 60)

        try:
            from sqlalchemy import create_engine, text

            # Подключение
            connection_url = (
                f"postgresql://{self.config['timescaledb_user']}:"
                f"{self.config['timescaledb_password']}@"
                f"{self.config['timescaledb_host']}:"
                f"{self.config['timescaledb_port']}/"
                f"{self.config['timescaledb_db']}"
            )

            logger.info(f"Подключение к TimescaleDB: {self.config['timescaledb_host']}:{self.config['timescaledb_port']}")

            engine = create_engine(connection_url)

            # Проверка подключения
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✓ TimescaleDB подключен")

            # Таблицы для экспорта
            default_tables = ["candle_data", "tick_data", "orderbook_data", "candle_data_1h", "candle_data_1d"]

            if tables:
                tables_to_export = tables
            else:
                tables_to_export = default_tables

            # Экспорт каждой таблицы
            for table_name in tables_to_export:
                try:
                    logger.info(f"Экспорт таблицы: {table_name}")

                    # Для больших таблиц ограничиваем количество записей
                    query = text(f"""
                        SELECT * FROM {table_name}
                        ORDER BY timestamp DESC
                        LIMIT 100000
                    """)

                    df = pd.read_sql_query(query, engine)

                    self.exported_data["timescaledb"][table_name] = {
                        "columns": list(df.columns),
                        "row_count": len(df),
                        "data": df.to_dict("records"),
                        "exported_at": datetime.utcnow().isoformat(),
                    }

                    self.stats["exported_tables"] += 1
                    self.stats["exported_rows"] += len(df)

                    logger.info(f"  ✓ Экспортировано {len(df)} записей")

                except Exception as e:
                    logger.warning(f"  ⚠ Таблица {table_name} не найдена или пуста: {e}")
                    self.exported_data["timescaledb"][table_name] = {"error": str(e)}

            logger.info(f"\nВсего экспортировано из TimescaleDB: {len(tables_to_export)} таблиц")

        except Exception as e:
            logger.error(f"Ошибка экспорта из TimescaleDB: {e}")
            self.stats["errors"] += 1
            self.exported_data["timescaledb"]["error"] = str(e)

        return self.exported_data["timescaledb"]

    # ========================================================================
    # QUESTDB EXPORT
    # ========================================================================
    def export_from_questdb(self, tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Экспорт данных из QuestDB.

        Таблицы:
        - candle_data, tick_data, orderbook_data
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из QuestDB")
        logger.info("=" * 60)

        try:
            import psycopg2
            from psycopg2 import pool

            # Подключение
            logger.info(f"Подключение к QuestDB: {self.config['questdb_host']}:{self.config['questdb_port']}")

            conn = psycopg2.connect(
                host=self.config["questdb_host"],
                port=self.config["questdb_port"],
                database="questdb",
                user=self.config["questdb_user"],
                password=self.config["questdb_password"],
            )

            logger.info("✓ QuestDB подключен")

            # Получение списка таблиц
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename;
            """)
            available_tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"Найдено таблиц: {len(available_tables)}")

            # Фильтрация таблиц
            if tables:
                tables_to_export = [t for t in available_tables if t in tables]
            else:
                tables_to_export = available_tables

            # Экспорт каждой таблицы
            for table_name in tables_to_export:
                try:
                    logger.info(f"Экспорт таблицы: {table_name}")

                    query = f"""
                        SELECT * FROM {table_name}
                        ORDER BY timestamp DESC
                        LIMIT 100000
                    """

                    df = pd.read_sql_query(query, conn)

                    self.exported_data["questdb"][table_name] = {
                        "columns": list(df.columns),
                        "row_count": len(df),
                        "data": df.to_dict("records"),
                        "exported_at": datetime.utcnow().isoformat(),
                    }

                    self.stats["exported_tables"] += 1
                    self.stats["exported_rows"] += len(df)

                    logger.info(f"  ✓ Экспортировано {len(df)} записей")

                except Exception as e:
                    logger.warning(f"  ⚠ Таблица {table_name} не найдена: {e}")

            cursor.close()
            conn.close()

            logger.info(f"\nВсего экспортировано из QuestDB: {len(tables_to_export)} таблиц")

        except ImportError:
            logger.error("psycopg2 не установлен. Пропуск экспорта из QuestDB.")
            self.exported_data["questdb"]["error"] = "psycopg2 not installed"
        except Exception as e:
            logger.error(f"Ошибка экспорта из QuestDB: {e}")
            self.stats["errors"] += 1
            self.exported_data["questdb"]["error"] = str(e)

        return self.exported_data["questdb"]

    # ========================================================================
    # QDRANT EXPORT
    # ========================================================================
    def export_from_qdrant(self, limit: int = 10000) -> Dict[str, Any]:
        """
        Экспорт векторных данных из Qdrant.

        Коллекции:
        - trading_rag (новости, паттерны, сентимент)
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из Qdrant")
        logger.info("=" * 60)

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models

            # Подключение
            logger.info(f"Подключение к Qdrant: {self.config['qdrant_host']}:{self.config['qdrant_port']}")

            client = QdrantClient(
                host=self.config["qdrant_host"],
                port=self.config["qdrant_port"],
            )

            logger.info("✓ Qdrant подключен")

            # Получение списка коллекций
            collections = client.get_collections()
            logger.info(f"Найдено коллекций: {len(collections.collections)}")

            # Экспорт каждой коллекции
            for collection in collections.collections:
                collection_name = collection.name
                logger.info(f"Экспорт коллекции: {collection_name}")

                try:
                    # Получение всех точек
                    points = []
                    offset = None

                    while True:
                        records, offset = client.scroll(
                            collection_name=collection_name,
                            limit=1000,
                            offset=offset,
                        )

                        for record in records:
                            point_data = {
                                "id": record.id,
                                "payload": record.payload,
                                "vector": record.vector.tolist() if hasattr(record.vector, "tolist") else record.vector,
                            }
                            points.append(point_data)
                            self.stats["exported_vectors"] += 1

                        if offset is None:
                            break

                        if len(points) >= limit:
                            break

                    self.exported_data["qdrant"][collection_name] = {
                        "vectors_count": len(points),
                        "points": points[:limit],
                        "exported_at": datetime.utcnow().isoformat(),
                    }

                    logger.info(f"  ✓ Экспортировано {len(points)} векторов")

                except Exception as e:
                    logger.error(f"  ✗ Ошибка экспорта коллекции {collection_name}: {e}")
                    self.stats["errors"] += 1

            logger.info(f"\nВсего экспортировано из Qdrant: {self.stats['exported_vectors']} векторов")

        except ImportError:
            logger.error("qdrant-client не установлен. Пропуск экспорта из Qdrant.")
            self.exported_data["qdrant"]["error"] = "qdrant-client not installed"
        except Exception as e:
            logger.error(f"Ошибка экспорта из Qdrant: {e}")
            self.stats["errors"] += 1
            self.exported_data["qdrant"]["error"] = str(e)

        return self.exported_data["qdrant"]

    # ========================================================================
    # REDIS EXPORT
    # ========================================================================
    def export_from_redis(self) -> Dict[str, Any]:
        """
        Экспорт данных из Redis.

        Данные:
        - Кэш метрик
        - Pub/Sub сообщения
        - Временные данные
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из Redis")
        logger.info("=" * 60)

        try:
            import redis

            # Подключение
            logger.info(f"Подключение к Redis: {self.config['redis_host']}:{self.config['redis_port']}")

            r = redis.Redis(
                host=self.config["redis_host"],
                port=self.config["redis_port"],
                decode_responses=True,
            )

            # Проверка подключения
            r.ping()
            logger.info("✓ Redis подключен")

            # Получение всех ключей
            keys = r.keys("*")
            logger.info(f"Найдено ключей: {len(keys)}")

            # Экспорт данных
            redis_data = {}

            for key in keys[:1000]:  # Ограничение на количество ключей
                try:
                    key_type = r.type(key)

                    if key_type == "string":
                        redis_data[key] = {
                            "type": "string",
                            "value": r.get(key),
                        }
                    elif key_type == "list":
                        redis_data[key] = {
                            "type": "list",
                            "value": r.lrange(key, 0, -1),
                        }
                    elif key_type == "set":
                        redis_data[key] = {
                            "type": "set",
                            "value": list(r.smembers(key)),
                        }
                    elif key_type == "hash":
                        redis_data[key] = {
                            "type": "hash",
                            "value": r.hgetall(key),
                        }
                    elif key_type == "zset":
                        redis_data[key] = {
                            "type": "zset",
                            "value": r.zrange(key, 0, -1, withscores=True),
                        }

                except Exception as e:
                    logger.debug(f"  ⚠ Ключ {key}: {e}")

            self.exported_data["redis"] = {
                "keys_count": len(redis_data),
                "data": redis_data,
                "exported_at": datetime.utcnow().isoformat(),
            }

            logger.info(f"  ✓ Экспортировано {len(redis_data)} ключей")

        except ImportError:
            logger.error("redis не установлен. Пропуск экспорта из Redis.")
            self.exported_data["redis"]["error"] = "redis not installed"
        except Exception as e:
            logger.error(f"Ошибка экспорта из Redis: {e}")
            self.stats["errors"] += 1
            self.exported_data["redis"]["error"] = str(e)

        return self.exported_data["redis"]

    # ========================================================================
    # SQLITE EXPORT
    # ========================================================================
    def export_from_sqlite(self, tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Экспорт данных из SQLite.

        Таблицы:
        - trade_history, active_positions, trade_audit
        - trained_models, scalers, candle_data
        - news_articles, entities, relations
        """
        logger.info("\n" + "=" * 60)
        logger.info("  Экспорт из SQLite")
        logger.info("=" * 60)

        sqlite_path = Path(self.config["sqlite_path"])

        if not sqlite_path.exists():
            logger.warning(f"SQLite база не найдена: {sqlite_path}")
            self.exported_data["sqlite"]["error"] = "Database not found"
            return self.exported_data["sqlite"]

        try:
            import sqlite3

            # Подключение
            logger.info(f"Подключение к SQLite: {sqlite_path}")

            conn = sqlite3.connect(sqlite_path)
            conn.row_factory = sqlite3.Row

            # Получение списка таблиц
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table'
                ORDER BY name;
            """)
            available_tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"Найдено таблиц: {len(available_tables)}")

            # Фильтрация таблиц
            if tables:
                tables_to_export = [t for t in available_tables if t in tables]
            else:
                tables_to_export = available_tables

            # Экспорт каждой таблицы
            for table_name in tables_to_export:
                try:
                    logger.info(f"Экспорт таблицы: {table_name}")

                    query = f"SELECT * FROM {table_name}"
                    df = pd.read_sql_query(query, conn)

                    self.exported_data["sqlite"][table_name] = {
                        "columns": list(df.columns),
                        "row_count": len(df),
                        "data": df.to_dict("records"),
                        "exported_at": datetime.utcnow().isoformat(),
                    }

                    self.stats["exported_tables"] += 1
                    self.stats["exported_rows"] += len(df)

                    logger.info(f"  ✓ Экспортировано {len(df)} записей")

                except Exception as e:
                    logger.error(f"  ✗ Ошибка экспорта таблицы {table_name}: {e}")
                    self.stats["errors"] += 1

            conn.close()

            logger.info(f"\nВсего экспортировано из SQLite: {len(tables_to_export)} таблиц")

        except Exception as e:
            logger.error(f"Ошибка экспорта из SQLite: {e}")
            self.stats["errors"] += 1
            self.exported_data["sqlite"]["error"] = str(e)

        return self.exported_data["sqlite"]

    # ========================================================================
    # EXPORT ALL DATABASES
    # ========================================================================
    def export_all(self, exclude: Optional[List[str]] = None) -> Dict[str, Any]:
        """Экспорт из всех баз данных."""
        logger.info("\n" + "█" * 60)
        logger.info("  Genesis Trading System - Полный экспорт данных")
        logger.info("█" * 60)

        exclude = exclude or []

        if "postgres" not in exclude:
            self.export_from_postgres()

        if "timescaledb" not in exclude:
            self.export_from_timescaledb()

        if "questdb" not in exclude:
            self.export_from_questdb()

        if "qdrant" not in exclude:
            self.export_from_qdrant()

        if "redis" not in exclude:
            self.export_from_redis()

        if "sqlite" not in exclude:
            self.export_from_sqlite()

        return self.exported_data

    # ========================================================================
    # SAVE TO FILE
    # ========================================================================
    def save_to_file(self, output_path: str, format: str = "json"):
        """Сохранение экспортированных данных в файл."""
        logger.info("\n" + "=" * 60)
        logger.info(f"  Сохранение в формате: {format}")
        logger.info("=" * 60)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        export_data = {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "config": {k: v for k, v in self.config.items() if not k.endswith("password")},
            "stats": self.stats,
            "data": self.exported_data,
        }

        try:
            if format == "json":
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

            elif format == "parquet":
                # Сохранение каждой таблицы в отдельный Parquet файл
                for db_name, db_data in self.exported_data.items():
                    if isinstance(db_data, dict):
                        for table_name, table_data in db_data.items():
                            if isinstance(table_data, dict) and "data" in table_data:
                                df = pd.DataFrame(table_data["data"])
                                parquet_path = output_file.parent / f"{db_name}_{table_name}.parquet"
                                df.to_parquet(parquet_path, index=False)
                                logger.info(f"  ✓ Сохранено: {parquet_path}")

            elif format == "csv":
                # Сохранение каждой таблицы в отдельный CSV файл
                for db_name, db_data in self.exported_data.items():
                    if isinstance(db_data, dict):
                        for table_name, table_data in db_data.items():
                            if isinstance(table_data, dict) and "data" in table_data:
                                df = pd.DataFrame(table_data["data"])
                                csv_path = output_file.parent / f"{db_name}_{table_name}.csv"
                                df.to_csv(csv_path, index=False)
                                logger.info(f"  ✓ Сохранено: {csv_path}")

            logger.info(f"✓ Данные сохранены в: {output_file}")
            logger.info(f"  Всего таблиц: {self.stats['exported_tables']}")
            logger.info(f"  Всего записей: {self.stats['exported_rows']}")
            logger.info(f"  Всего векторов: {self.stats['exported_vectors']}")

        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            raise

    def get_stats(self) -> Dict[str, int]:
        """Получение статистики экспорта."""
        return self.stats


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(description="Экспорт данных из баз данных Genesis Trading System")

    parser.add_argument(
        "--db",
        type=str,
        nargs="+",
        choices=["postgres", "timescaledb", "questdb", "qdrant", "redis", "sqlite", "all"],
        default="all",
        help="Базы данных для экспорта",
    )

    parser.add_argument("--output", type=str, default="genesis_export.json", help="Путь к выходному файлу")

    parser.add_argument(
        "--format", type=str, choices=["json", "parquet", "csv"], default="json", help="Формат выходных данных"
    )

    parser.add_argument("--tables", type=str, nargs="+", help="Конкретные таблицы для экспорта")

    parser.add_argument(
        "--exclude",
        type=str,
        nargs="+",
        choices=["postgres", "timescaledb", "questdb", "qdrant", "redis", "sqlite"],
        help="Исключить базы данных",
    )

    parser.add_argument("--limit", type=int, default=100000, help="Лимит записей на таблицу")

    args = parser.parse_args()

    # Создание экспортера
    exporter = GenesisDatabaseExporter()

    # Экспорт
    if "all" in args.db:
        exporter.export_all(exclude=args.exclude)
    else:
        for db_name in args.db:
            if db_name == "postgres":
                exporter.export_from_postgres(tables=args.tables)
            elif db_name == "timescaledb":
                exporter.export_from_timescaledb(tables=args.tables)
            elif db_name == "questdb":
                exporter.export_from_questdb(tables=args.tables)
            elif db_name == "qdrant":
                exporter.export_from_qdrant(limit=args.limit)
            elif db_name == "redis":
                exporter.export_from_redis()
            elif db_name == "sqlite":
                exporter.export_from_sqlite(tables=args.tables)

    # Сохранение
    exporter.save_to_file(args.output, format=args.format)

    # Итоговый отчет
    stats = exporter.get_stats()

    logger.info("\n" + "=" * 60)
    logger.info("  ИТОГОВЫЙ ОТЧЕТ ПО ЭКСПОРТУ")
    logger.info("=" * 60)
    logger.info(f"  Экспортировано таблиц: {stats['exported_tables']}")
    logger.info(f"  Экспортировано записей: {stats['exported_rows']}")
    logger.info(f"  Экспортировано векторов: {stats['exported_vectors']}")
    logger.info(f"  Ошибок: {stats['errors']}")

    if stats["errors"] == 0:
        logger.info("\n  ✅ Экспорт завершен успешно!")
    else:
        logger.warning(f"\n  ⚠ Экспорт завершен с {stats['errors']} ошибками")

    logger.info("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
