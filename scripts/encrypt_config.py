#!/usr/bin/env python3
"""
Утилита для генерации ключа шифрования и шифрования чувствительных данных.

Использование:
    python scripts/encrypt_config.py generate-key
    python scripts/encrypt_config.py encrypt "ваш_пароль"
"""

import os
import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.secure_config import SecureConfigLoader, generate_encryption_key


def print_usage():
    """Вывод инструкции по использованию."""
    print("""
Утилита шифрования конфигурации Genesis Trading System

Использование:
    python scripts/encrypt_config.py generate-key              # Сгенерировать новый ключ
    python scripts/encrypt_config.py encrypt "значение"        # Зашифровать значение
    python scripts/encrypt_config.py encrypt-env               # Создать зашифрованный .env файл

Примеры:
    # 1. Генерация ключа шифрования
    python scripts/encrypt_config.py generate-key

    # 2. Шифрование пароля
    python scripts/encrypt_config.py encrypt "mypassword123"

    # 3. Создание зашифрованного .env файла
    python scripts/encrypt_config.py encrypt-env
""")


def generate_key():
    """Генерация и вывод ключа шифрования."""
    key = generate_encryption_key()
    print("\n" + "=" * 60)
    print("НОВЫЙ КЛЮЧ ШИФРОВАНИЯ:")
    print("=" * 60)
    print(f"ENCRYPTION_KEY={key}")
    print("=" * 60)
    print("\n⚠️  ВАЖНО: Сохраните этот ключ в безопасном месте!")
    print("   Добавьте его в ваш .env файл:")
    print(f"   echo 'ENCRYPTION_KEY={key}' >> configs/.env")
    print("\n🔒 Без этого ключа вы не сможете расшифровать свои данные!\n")


def encrypt_value(value: str):
    """Шифрование значения."""
    # Проверяем наличие ключа
    encryption_key = os.environ.get("ENCRYPTION_KEY")

    if not encryption_key:
        print("❌ ОШИБКА: ENCRYPTION_KEY не установлен!")
        print("\nУстановите ключ шифрования:")
        print("  1. Сгенерируйте: python scripts/encrypt_config.py generate-key")
        print("  2. Добавьте в .env: ENCRYPTION_KEY=ваш_ключ")
        print("  3. Или установите переменную окружения")
        sys.exit(1)

    encrypted = SecureConfigLoader.encrypt_value(value, encryption_key)

    print("\n" + "=" * 60)
    print("ЗАШИФРОВАННОЕ ЗНАЧЕНИЕ:")
    print("=" * 60)
    print(encrypted)
    print("=" * 60)
    print("\nДобавьте это значение в ваш .env файл\n")


def encrypt_env_file():
    """Создание зашифрованного .env файла."""
    env_example_path = project_root / "configs" / ".env.example"
    env_path = project_root / "configs" / ".env"

    if not env_example_path.exists():
        print(f"❌ ОШИБКА: Файл {env_example_path} не найден!")
        sys.exit(1)

    # Проверяем наличие ключа
    encryption_key = os.environ.get("ENCRYPTION_KEY")

    if not encryption_key:
        print("❌ ОШИБКА: ENCRYPTION_KEY не установлен!")
        print("\nСначала сгенерируйте ключ:")
        print("  python scripts/encrypt_config.py generate-key")
        sys.exit(1)

    print("📝 Чтение .env.example...")

    # Читаем .env.example
    with open(env_example_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    print("🔐 Шифрование чувствительных данных...")

    # Ключи для шифрования
    sensitive_keys = [
        "MT5_PASSWORD",
        "FINNHUB_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "NEWS_API_KEY",
        "POLYGON_API_KEY",
        "TWELVE_DATA_API_KEY",
        "FCS_API_KEY",
        "SANTIMENT_API_KEY",
        "NEO4J_PASSWORD",
        "FRED_API_KEY",
    ]

    encrypted_lines = []

    for line in lines:
        line = line.strip()

        # Пропускаем комментарии и пустые строки
        if not line or line.startswith("#"):
            encrypted_lines.append(line)
            continue

        # Разбираем KEY=VALUE
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            # Шифруем чувствительные данные
            if key in sensitive_keys and value and not value.startswith("${ENC:"):
                encrypted_value = SecureConfigLoader.encrypt_value(value, encryption_key)
                encrypted_lines.append(f"{key}={encrypted_value}")
                print(f"  ✓ Зашифровано: {key}")
            else:
                encrypted_lines.append(line)
        else:
            encrypted_lines.append(line)

    # Сохраняем зашифрованный файл
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(encrypted_lines))

    print(f"\n✅ Зашифрованный файл создан: {env_path}")
    print("\n⚠️  ВАЖНО:")
    print("   1. Удалите или переместите оригинальный .env.example если он содержал реальные данные")
    print("   2. Никогда не коммитьте .env в репозиторий!")
    print("   3. Убедитесь, что .env добавлен в .gitignore")


def main():
    """Основная функция."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "generate-key":
        generate_key()

    elif command == "encrypt":
        if len(sys.argv) < 3:
            print("❌ ОШИБКА: Укажите значение для шифрования")
            print_usage()
            sys.exit(1)
        value = sys.argv[2]
        encrypt_value(value)

    elif command == "encrypt-env":
        encrypt_env_file()

    else:
        print(f"❌ Неизвестная команда: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
