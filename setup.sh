#!/bin/bash
# Genesis Trading System - Быстрая настройка
# Использование: ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Genesis Trading System - Настройка                    ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Шаг 1: Создание .env
if [ ! -f .env ]; then
    echo "[1/4] Создание файла .env..."
    cp .env.example .env
    echo "✓ .env создан"
    echo "  Откройте .env и заполните вашими данными!"
else
    echo "[1/4] .env уже существует"
fi

# Шаг 2: Создание venv
if [ ! -d venv ]; then
    echo ""
    echo "[2/4] Создание виртуального окружения..."
    python3 -m venv venv
    echo "✓ Виртуальное окружение создано"
else
    echo ""
    echo "[2/4] Виртуальное окружение уже существует"
fi

# Шаг 3: Активация venv
echo ""
echo "[3/4] Активация виртуального окружения..."
source venv/bin/activate
echo "✓ Виртуальное окружение активировано"

# Шаг 4: Установка зависимостей
echo ""
echo "[4/4] Установка зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Зависимости установлены"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Настройка завершена!                                  ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "Следующие шаги:"
echo "  1. Откройте и отредактируйте .env файл"
echo "  2. Перезагрузите VS Code (Ctrl+Shift+P → Developer: Reload Window)"
echo "  3. Запустите: ./start_ecosystem.sh"
echo ""
echo "Для запуска экосистемы выполните:"
echo "  ./start_ecosystem.sh"
echo ""
