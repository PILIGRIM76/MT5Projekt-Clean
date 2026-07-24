#!/usr/bin/env python3
"""
Добавить тестовые данные в Граф Знаний для проверки визуализации.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("🧪 ДОБАВЛЕНИЕ ТЕСТОВЫХ ДАННЫХ В ГРАФ ЗНАНИЙ")
print("=" * 60)

# Читаем настройки
settings_path = PROJECT_ROOT / "configs" / "settings.json"
with open(settings_path, "r", encoding="utf-8") as f:
    settings = json.load(f)

db_folder = settings.get("DATABASE_FOLDER", "F:\\Enjen\\database")
db_name = settings.get("DATABASE_NAME", "trading_system.db")
db_path = Path(db_folder) / db_name

print(f"\n📂 База данных: {db_path}")

# Подключаемся к БД
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

try:
    # Проверяем текущее состояние
    cursor.execute("SELECT COUNT(*) FROM entities;")
    entity_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM relations;")
    relation_count = cursor.fetchone()[0]

    print(f"\n📊 До добавления:")
    print(f"   Узлы: {entity_count}")
    print(f"   Связи: {relation_count}")

    if entity_count == 0:
        print("\n➕ Добавляю тестовые узлы...")
        test_entities = [
            ("EURUSD", "Currency Pair"),
            ("EUR", "Currency"),
            ("USD", "Currency"),
            ("GBPUSD", "Currency Pair"),
            ("GBP", "Currency"),
            ("Federal Reserve", "Central Bank"),
            ("ECB", "Central Bank"),
            ("Interest Rate", "Economic Indicator"),
            ("Inflation", "Economic Indicator"),
            ("Trading Signal", "Signal"),
        ]

        for name, entity_type in test_entities:
            cursor.execute("INSERT OR IGNORE INTO entities (name, entity_type) VALUES (?, ?);", (name, entity_type))

        conn.commit()
        print(f"   ✅ Добавлено {len(test_entities)} узлов")

    # Получаем ID узлов
    cursor.execute("SELECT id, name FROM entities;")
    entities = {row[1]: row[0] for row in cursor.fetchall()}

    if relation_count == 0 and len(entities) >= 2:
        print("\n➕ Добавляю тестовые связи...")
        now = datetime.utcnow().isoformat()

        test_relations = [
            (entities.get("EURUSD"), entities.get("EUR"), "contains", now),
            (entities.get("EURUSD"), entities.get("USD"), "contains", now),
            (entities.get("GBPUSD"), entities.get("GBP"), "contains", now),
            (entities.get("GBPUSD"), entities.get("USD"), "contains", now),
            (entities.get("Federal Reserve"), entities.get("USD"), "controls", now),
            (entities.get("ECB"), entities.get("EUR"), "controls", now),
            (entities.get("Federal Reserve"), entities.get("Interest Rate"), "sets", now),
            (entities.get("ECB"), entities.get("Interest Rate"), "sets", now),
            (entities.get("Interest Rate"), entities.get("Inflation"), "affects", now),
            (entities.get("EURUSD"), entities.get("Trading Signal"), "generates", now),
        ]

        for source_id, target_id, rel_type, timestamp in test_relations:
            if source_id and target_id:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO relations
                    (source_id, target_id, relation_type, timestamp)
                    VALUES (?, ?, ?, ?);
                """,
                    (source_id, target_id, rel_type, timestamp),
                )

        conn.commit()
        print(f"   ✅ Добавлено {len(test_relations)} связей")

    # Финальная проверка
    cursor.execute("SELECT COUNT(*) FROM entities;")
    final_entity_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM relations;")
    final_relation_count = cursor.fetchone()[0]

    print(f"\n{'=' * 60}")
    print("📊 После добавления:")
    print(f"   Узлы: {final_entity_count}")
    print(f"   Связи: {final_relation_count}")

    if final_entity_count > 0 and final_relation_count > 0:
        print("\n✅ Тестовые данные добавлены!")
        print("   Перезапусти приложение и включи визуализацию Графа Знаний.")
    else:
        print("\n❌ Что-то пошло не так")

    print(f"{'=' * 60}")

except Exception as e:
    print(f"\n❌ Ошибка: {e}")
    import traceback

    traceback.print_exc()
    conn.rollback()
finally:
    conn.close()
