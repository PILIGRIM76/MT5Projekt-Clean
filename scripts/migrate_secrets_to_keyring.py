#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт миграции секретов из settings.json в Credential Manager.

Использование:
    python scripts/migrate_secrets_to_keyring.py

Что делает:
1. Читает секреты из configs/settings.json
2. Сохраняет в Windows Credential Manager (через keyring)
3. Создаёт backup settings.json без секретов
4. Генерирует .env.example с перечнем необходимых переменных
"""

import json
import os
import sys
from pathlib import Path

# Добавляем корень проекта в path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Секреты для миграции
SECRETS_TO_MIGRATE = [
    # MT5
    "MT5_LOGIN",
    "MT5_PASSWORD",
    "MT5_SERVER",
    "MT5_PATH",
    # API ключи
    "FINNHUB_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "NEWS_API_KEY",
    "POLYGON_API_KEY",
    "TWELVE_DATA_API_KEY",
    "FCS_API_KEY",
    "FRED_API_KEY",
    "SANTIMENT_API_KEY",
    # Соцсети и алерты
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TWITTER_BEARER_TOKEN",
    # Базы данных
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
]


def migrate_secrets():
    """Миграция секретов из settings.json в Credential Manager."""

    print("=" * 60)
    print("  Миграция секретов в Credential Manager")
    print("=" * 60)

    # Пути
    settings_path = project_root / "configs" / "settings.json"
    backup_path = project_root / "configs" / "settings.json.backup"

    # Проверка существования файла
    if not settings_path.exists():
        print(f"\n❌ Файл не найден: {settings_path}")
        sys.exit(1)

    # Чтение настроек
    print(f"\n📖 Чтение настроек из {settings_path}...")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            # Удаляем комментарии перед парсингом JSON
            content = "".join(line for line in f if not line.strip().startswith("//"))
            config = json.loads(content)
    except Exception as e:
        print(f"\n❌ Ошибка чтения файла: {e}")
        sys.exit(1)

    # Импорт keyring
    try:
        import keyring
    except ImportError:
        print("\n❌ Не установлен keyring. Установка:")
        print("   pip install keyring")
        sys.exit(1)

    service_name = "GenesisTrading"
    migrated = []
    not_found = []
    errors = []

    # Миграция каждого секрета
    print(f"\n🔐 Миграция секретов в '{service_name}'...")
    for key in SECRETS_TO_MIGRATE:
        if key in config:
            value = config[key]
            if value:  # Не пустое значение
                try:
                    keyring.set_password(service_name, key, value)
                    migrated.append(key)
                    print(f"  ✅ {key}")
                except Exception as e:
                    errors.append((key, str(e)))
                    print(f"  ❌ {key}: {e}")
            else:
                not_found.append(key)
                print(f"  ⚪ {key}: (пустое значение)")
        else:
            not_found.append(key)
            print(f"  ⚪ {key}: (не найден в settings.json)")

    # Создание backup без секретов
    print(f"\n💾 Создание backup без секретов...")
    safe_config = config.copy()
    for key in SECRETS_TO_MIGRATE:
        if key in safe_config:
            del safe_config[key]

    # Сохранение backup
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(safe_config, f, indent=2, ensure_ascii=False)
    print(f"  ✅ Backup сохранён: {backup_path}")

    # Обновление оригинального файла (замена секретов на плейсхолдеры)
    print(f"\n📝 Обновление settings.json...")
    updated_config = config.copy()
    for key in SECRETS_TO_MIGRATE:
        if key in updated_config:
            updated_config[key] = f"${{{key}}}"  # Плейсхолдер для env переменной

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(updated_config, f, indent=2, ensure_ascii=False)
    print(f"  ✅ settings.json обновлён (секреты заменены на плейсхолдеры)")

    # Генерация .env файла
    print(f"\n📄 Генерация .env файла...")
    env_path = project_root / ".env"
    env_example_path = project_root / ".env.example"

    env_content = []
    env_content.append("# Genesis Trading System - Environment Variables")
    env_content.append("# Скопируйте этот файл в .env и заполните значения")
    env_content.append("")
    env_content.append("# === MT5 Credentials ===")
    for key in ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_PATH"]:
        env_content.append(f"{key}=")

    env_content.append("")
    env_content.append("# === API Keys ===")
    for key in [
        "FINNHUB_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "NEWS_API_KEY",
        "POLYGON_API_KEY",
        "TWELVE_DATA_API_KEY",
        "FCS_API_KEY",
        "FRED_API_KEY",
        "SANTIMENT_API_KEY",
    ]:
        env_content.append(f"{key}=")

    env_content.append("")
    env_content.append("# === Social Media & Alerts ===")
    for key in ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TWITTER_BEARER_TOKEN"]:
        env_content.append(f"{key}=")

    env_content.append("")
    env_content.append("# === Database ===")
    for key in ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"]:
        env_content.append(f"{key}=")

    with open(env_example_path, "w", encoding="utf-8") as f:
        f.write("\n".join(env_content))
    print(f"  ✅ Создан .env.example")

    # Если .env не существует, создаём его
    if not env_path.exists():
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(env_content))
        print(f"  ✅ Создан .env (заполните значения)")

    # Итоговый отчёт
    print("\n" + "=" * 60)
    print("  ИТОГИ МИГРАЦИИ")
    print("=" * 60)
    print(f"  ✅ Успешно мигрировано: {len(migrated)}")
    print(f"  ⚪ Не найдено/пустые: {len(not_found)}")
    print(f"  ❌ Ошибок: {len(errors)}")

    if migrated:
        print(f"\nМигрированные секреты:")
        for key in migrated:
            print(f"  - {key}")

    if not_found:
        print(f"\nНе найдены:")
        for key in not_found:
            print(f"  - {key}")

    if errors:
        print(f"\nОшибки:")
        for key, error in errors:
            print(f"  - {key}: {error}")

    print("\n" + "=" * 60)
    print("  СЛЕДУЮЩИЕ ШАГИ:")
    print("=" * 60)
    print("  1. Проверьте, что все секреты мигрированы")
    print("  2. Заполните .env файл недостающими значениями")
    print("  3. Удалите configs/settings.json.backup если всё работает")
    print("  4. Добавьте .env в .gitignore (уже добавлен)")
    print("=" * 60)


if __name__ == "__main__":
    migrate_secrets()
