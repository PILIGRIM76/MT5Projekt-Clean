#!/usr/bin/env python3
"""
Миграция: Создание таблиц Графа Знаний (entities и relations).
"""

import json
import sqlite3
import sys
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("🔧 МИГРАЦИЯ: Создание таблиц Графа Знаний")
print("=" * 60)

# Читаем настройки
settings_path = PROJECT_ROOT / "configs" / "settings.json"
if not settings_path.exists():
    print("❌ Файл настроек не найден!")
    sys.exit(1)

with open(settings_path, "r", encoding="utf-8") as f:
    settings = json.load(f)

db_folder = settings.get("DATABASE_FOLDER", "F:\\Enjen\\database")
db_name = settings.get("DATABASE_NAME", "trading_system.db")
db_path = Path(db_folder) / db_name

if not db_path.exists():
    print(f"❌ База данных не найдена: {db_path}")
    sys.exit(1)

print(f"\n📂 База данных: {db_path}")

# Подключаемся к БД
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

try:
    # Проверяем существующие таблицы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    existing_tables = [row[0] for row in cursor.fetchall()]
    print(f"\n📋 Существующие таблицы: {len(existing_tables)}")

    # Создаём таблицу entities если отсутствует
    if "entities" not in existing_tables:
        print("\n✅ Создаю таблицу 'entities'...")
        cursor.execute("""
            CREATE TABLE entities (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                entity_type TEXT NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type);")
        print("   ✅ Таблица 'entities' создана")
    else:
        print("\n✅ Таблица 'entities' уже существует")

    # Создаём таблицу relations если отсутствует
    if "relations" not in existing_tables:
        print("\n✅ Создаю таблицу 'relations'...")
        cursor.execute("""
            CREATE TABLE relations (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                context_json TEXT,
                UNIQUE(source_id, target_id, relation_type, timestamp)
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_source ON relations(source_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_target ON relations(target_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_type ON relations(relation_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_timestamp ON relations(timestamp);")
        print("   ✅ Таблица 'relations' создана")
    else:
        print("\n✅ Таблица 'relations' уже существует")

    # Включаем визуализацию Графа Знаний
    print("\n⚙️  Включаю ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION...")
    settings["ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION"] = True
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    print("   ✅ ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION = True")

    conn.commit()

    # Финальная проверка
    cursor.execute("SELECT COUNT(*) FROM entities;")
    entity_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM relations;")
    relation_count = cursor.fetchone()[0]

    print(f"\n{'=' * 60}")
    print("📊 Результат миграции:")
    print(f"   Узлы (entities): {entity_count}")
    print(f"   Связи (relations): {relation_count}")
    print(f"   Визуализация: {'✅ ВКЛЮЧЕНА' if settings.get('ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION') else '❌ ВЫКЛЮЧЕНА'}")
    print(f"{'=' * 60}")

    if entity_count == 0 and relation_count == 0:
        print("\n⚠️  Таблицы созданы, но данных пока нет.")
        print("   Данные появятся когда NLP Processor обработает новости.")
        print("   Или можно запустить систему и подождать обработку новостей.")
    else:
        print("\n✅ Граф Знаний готов к использованию!")

except Exception as e:
    print(f"\n❌ Ошибка миграции: {e}")
    import traceback

    traceback.print_exc()
    conn.rollback()
finally:
    conn.close()
