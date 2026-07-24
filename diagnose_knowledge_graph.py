#!/usr/bin/env python3
"""
Диагностика Графа Знаний.
Проверяет наличие данных в Entity и Relation таблицах.
"""

import json
import sqlite3
import sys
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("🔍 ДИАГНОСТИКА ГРАФА ЗНАНИЙ")
print("=" * 60)

# Читаем настройки напрямую из JSON
settings_path = PROJECT_ROOT / "configs" / "settings.json"
if settings_path.exists():
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)

    db_folder = settings.get("DATABASE_FOLDER", "F:\\Enjen\\database")
    db_name = settings.get("DATABASE_NAME", "trading_system.db")
    kg_visualization = settings.get("ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION", False)

    print(f"\n📊 Конфигурация:")
    print(f"   ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION = {kg_visualization}")
    print(f"   DATABASE_FOLDER = {db_folder}")
    print(f"   DATABASE_NAME = {db_name}")

    db_path = Path(db_folder) / db_name

    if not db_path.exists():
        print(f"\n❌ База данных не найдена: {db_path}")
        sys.exit(1)

    print(f"\n✅ База данных найдена: {db_path}")
    print(f"   Размер: {db_path.stat().st_size / (1024*1024):.2f} МБ")

    # Подключаемся напрямую к SQLite
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        # Проверяем существование таблиц
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='entity' OR name='relation');")
        tables = [row[0] for row in cursor.fetchall()]

        print(f"\n📈 Таблицы Графа Знаний:")
        if "entity" in tables:
            cursor.execute("SELECT COUNT(*) FROM entity;")
            entity_count = cursor.fetchone()[0]
            print(f"   ✅ entity (узлы): {entity_count} записей")
        else:
            print(f"   ❌ Таблица entity отсутствует!")
            entity_count = 0

        if "relation" in tables:
            cursor.execute("SELECT COUNT(*) FROM relation;")
            relation_count = cursor.fetchone()[0]
            print(f"   ✅ relation (связи): {relation_count} записей")
        else:
            print(f"   ❌ Таблица relation отсутствует!")
            relation_count = 0

        # Показываем примеры данных
        if entity_count > 0:
            print(f"\n🔵 Примеры узлов (первые 5):")
            cursor.execute("SELECT id, name, type FROM entity LIMIT 5;")
            for row in cursor.fetchall():
                print(f"   ID={row[0]}, Name='{row[1]}', Type='{row[2]}'")

        if relation_count > 0:
            print(f"\n🔗 Примеры связей (первые 5):")
            cursor.execute("""
                SELECT r.source_id, r.target_id, r.relation_type,
                       e1.name as source_name, e2.name as target_name
                FROM relation r
                LEFT JOIN entity e1 ON r.source_id = e1.id
                LEFT JOIN entity e2 ON r.target_id = e2.id
                LIMIT 5;
            """)
            for row in cursor.fetchall():
                print(f"   {row[3]}(ID:{row[0]}) --[{row[2]}]--> {row[4]}(ID:{row[1]})")

        print(f"\n{'=' * 60}")
        if entity_count == 0 and relation_count == 0:
            print("⚠️  ГРАФ ЗНАНИЙ ПУСТ!")
            print("   Данные не записывались в таблицы Entity и Relation.")
            print("   Возможные причины:")
            print("   - NLP Processor не обрабатывает новости")
            print("   - KG-фичи отключены в FeatureEngineer")
            print("   - Neo4j не подключен (используется только SQLite)")
        else:
            print("✅ ГРАФ ЗНАНИЙ СОДЕРЖИТ ДАННЫЕ!")
            if not kg_visualization:
                print("   ⚠️  Но визуализация ОТКЛЮЧЕНА в настройках.")
                print("   Установи ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION = True")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\n❌ Ошибка при диагностике: {e}")
        import traceback

        traceback.print_exc()
    finally:
        conn.close()

else:
    print("❌ Файл настроек не найден!")
    sys.exit(1)
