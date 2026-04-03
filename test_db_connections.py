#!/usr/bin/env python3
"""
Тест подключения ко всем базам данных Genesis Trading System.
Запустите этот скрипт для проверки доступности всех БД.

Использование:
    python test_db_connections.py

Или через Docker:
    docker-compose exec trading-system python test_db_connections.py
"""

import os
import sys
from pathlib import Path

# Добавляем корень проекта в path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.db.adapters.qdrant_adapter import QdrantAdapter
from src.db.adapters.questdb_adapter import QuestDBAdapter
from src.db.adapters.redis_adapter import RedisAdapter
from src.db.adapters.timescaledb_adapter import TimescaleDBAdapter


def print_header(text: str):
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_result(name: str, success: bool, message: str = ""):
    status = "✓" if success else "✗"
    color = "\033[92m" if success else "\033[91m"
    reset = "\033[0m"

    print(f"{color}{status}{reset} {name}: {message}")
    return success


def test_postgresql():
    """Тест PostgreSQL."""
    print_header("PostgreSQL (Relational Data)")

    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "trading"),
            user=os.getenv("POSTGRES_USER", "trading_user"),
            password=os.getenv("POSTGRES_PASSWORD", "secure_password"),
            connect_timeout=5,
        )

        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            print_result("PostgreSQL", True, version[:50])

        # Проверка таблиц
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            tables = cur.fetchall()
            print(f"  Найдено таблиц: {len(tables)}")
            for table in tables[:10]:
                print(f"    - {table[0]}")
            if len(tables) > 10:
                print(f"    ... и ещё {len(tables) - 10}")

        conn.close()
        return True

    except Exception as e:
        print_result("PostgreSQL", False, str(e))
        return False


def test_timescaledb():
    """Тест TimescaleDB."""
    print_header("TimescaleDB (Time-Series Data)")

    try:
        adapter = TimescaleDBAdapter(
            host=os.getenv("TIMESCALEDB_HOST", "localhost"),
            port=int(os.getenv("TIMESCALEDB_PORT", "5433")),
            database=os.getenv("TIMESCALEDB_DB", "trading_ts"),
            user=os.getenv("TIMESCALEDB_USER", "trading_user"),
            password=os.getenv("TIMESCALEDB_PASSWORD", "secure_password"),
            enabled=True,
        )

        if adapter.enabled:
            print_result("TimescaleDB", True, "Подключен")

            # Проверка hypertables
            stats = adapter.get_table_stats("candle_data")
            if stats:
                print(f"  Hypertable 'candle_data': {stats.get('total_rows', 0)} записей")

            adapter.close()
            return True
        else:
            print_result("TimescaleDB", False, "Адаптер не активен")
            return False

    except Exception as e:
        print_result("TimescaleDB", False, str(e))
        return False


def test_questdb():
    """Тест QuestDB."""
    print_header("QuestDB (High-Performance Time-Series)")

    try:
        adapter = QuestDBAdapter(
            host=os.getenv("QUESTDB_HOST", "localhost"),
            port=int(os.getenv("QUESTDB_PORT", "9000")),
            database="questdb",
            user=os.getenv("QUESTDB_USER", "quest"),
            password=os.getenv("QUESTDB_PASSWORD", "quest"),
            enabled=True,
        )

        if adapter.enabled:
            print_result("QuestDB", True, "Подключен")

            # Проверка таблиц
            stats = adapter.get_table_stats("candle_data")
            if stats:
                print(f"  Таблица 'candle_data': {stats.get('total_rows', 0)} записей")

            adapter.close()
            return True
        else:
            print_result("QuestDB", False, "Адаптер не активен")
            return False

    except Exception as e:
        print_result("QuestDB", False, str(e))
        return False


def test_qdrant():
    """Тест Qdrant."""
    print_header("Qdrant (Vector Database)")

    try:
        adapter = QdrantAdapter(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
            grpc_port=int(os.getenv("QDRANT_GRPC_PORT", "6334")),
            collection_name="trading_rag",
            vector_size=384,
            enabled=True,
        )

        if adapter.enabled:
            print_result("Qdrant", True, "Подключен")

            # Проверка коллекции
            stats = adapter.get_collection_stats()
            if stats:
                print(f"  Коллекция 'trading_rag': {stats.get('vectors_count', 0)} векторов")

            adapter.close()
            return True
        else:
            print_result("Qdrant", False, "Адаптер не активен")
            return False

    except Exception as e:
        print_result("Qdrant", False, str(e))
        return False


def test_redis():
    """Тест Redis."""
    print_header("Redis (Cache & Pub/Sub)")

    try:
        adapter = RedisAdapter(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=0,
            enabled=True,
        )

        if adapter.enabled and adapter.ping():
            print_result("Redis", True, "Подключен")

            # Проверка статистики
            stats = adapter.get_stats()
            print(f"  Используется памяти: {stats.get('used_memory_human', 'N/A')}")
            print(f"  Подключений: {stats.get('connected_clients', 0)}")

            # Тест кэширования
            test_key = "test:connection_check"
            adapter.set(test_key, "OK", ex=10)
            value = adapter.get(test_key)
            if value == b"OK" or value == "OK":
                print(f"  Тест записи/чтения: ✓")

            adapter.close()
            return True
        else:
            print_result("Redis", False, "Адаптер не активен или не отвечает на PING")
            return False

    except Exception as e:
        print_result("Redis", False, str(e))
        return False


def test_neo4j():
    """Тест Neo4j."""
    print_header("Neo4j (Graph Database)")

    try:
        from neo4j import GraphDatabase

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()

        print_result("Neo4j", True, "Подключен")

        # Проверка количества узлов и связей
        with driver.session() as session:
            result = session.run("""
                MATCH ()-[r]->()
                RETURN
                    count(DISTINCT n) as nodes,
                    count(r) as relationships
            """)
            record = result.single()
            if record:
                print(f"  Узлов: {record['nodes']}, Связей: {record['relationships']}")

        driver.close()
        return True

    except Exception as e:
        print_result("Neo4j", False, str(e))
        return False


def test_sqlite():
    """Тест SQLite (резервный вариант)."""
    print_header("SQLite (Local Storage / Backup)")

    try:
        import sqlite3

        db_path = os.getenv("SQLITE_PATH", "database/trading_system.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Проверка таблиц
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name;
        """)
        tables = cursor.fetchall()

        print_result("SQLite", True, f"Найдено таблиц: {len(tables)}")

        for table in tables[:10]:
            print(f"    - {table[0]}")
        if len(tables) > 10:
            print(f"    ... и ещё {len(tables) - 10}")

        conn.close()
        return True

    except Exception as e:
        print_result("SQLite", False, str(e))
        return False


def main():
    """Главная функция."""
    print("\n" + "█" * 60)
    print("  Genesis Trading System - Database Connection Test")
    print("█" * 60)

    results = {
        "PostgreSQL": test_postgresql(),
        "TimescaleDB": test_timescaledb(),
        "QuestDB": test_questdb(),
        "Qdrant": test_qdrant(),
        "Redis": test_redis(),
        "Neo4j": test_neo4j(),
        "SQLite": test_sqlite(),
    }

    # Итоговый отчет
    print_header("ИТОГОВЫЙ ОТЧЕТ")

    total = len(results)
    passed = sum(results.values())
    failed = total - passed

    print(f"\n  Всего тестов: {total}")
    print(f"  ✓ Успешно: {passed}")
    print(f"  ✗ Не успешно: {failed}")

    print("\n  Статус по базам данных:")
    for name, success in results.items():
        status = "✓" if success else "✗"
        print(f"    {status} {name}")

    # Рекомендации
    print("\n  Рекомендации:")

    if not results["PostgreSQL"] and not results["SQLite"]:
        print("    ⚠ ВНИМАНИЕ: Ни одна реляционная БД не доступна!")
        print("    → Запустите: docker-compose up -d db")

    if not results["TimescaleDB"] and not results["QuestDB"]:
        print("    ⚠ ВНИМАНИЕ: БД временных рядов не доступна!")
        print("    → Запустите: docker-compose up -d timescaledb questdb")

    if not results["Qdrant"]:
        print("    ⚠ ВНИМАНИЕ: Qdrant не доступен, будет использоваться локальный FAISS")
        print("    → Запустите: docker-compose up -d qdrant")

    if not results["Redis"]:
        print("    ⚠ ВНИМАНИЕ: Redis не доступен, кэширование отключено")
        print("    → Запустите: docker-compose up -d redis")

    if not results["Neo4j"]:
        print("    ⚠ ВНИМАНИЕ: Neo4j не доступен, граф знаний отключен")
        print("    → Запустите: docker-compose up -d neo4j")

    print("\n" + "█" * 60 + "\n")

    # Возвращаем код выхода
    if passed >= total // 2:
        print("✅ Тестирование завершено успешно (более 50% БД доступно)")
        return 0
    else:
        print("❌ Тестирование провалено (менее 50% БД доступно)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
