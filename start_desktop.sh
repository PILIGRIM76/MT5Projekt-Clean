#!/bin/bash
# Genesis Trading System - Запуск десктопного приложения PySide6
# Использование: ./start_desktop.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Genesis Trading System - Десктопное приложение        ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Проверка Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}✗ Python не установлен${NC}"
    exit 1
fi

# Проверка .env файла
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ Файл .env не найден. Создаю из .env.example...${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ .env создан${NC}"
    else
        echo -e "${YELLOW}⚠ .env.example не найден${NC}"
    fi
fi

# Активация виртуального окружения
if [ -d "venv" ]; then
    echo -e "${YELLOW}→ Активация виртуального окружения...${NC}"
    source venv/bin/activate
fi

# Установка зависимостей
echo -e "${YELLOW}→ Проверка зависимостей...${NC}"
pip install -q -r requirements.txt 2>/dev/null || true

# Запуск приложения
echo -e "${GREEN}→ Запуск PySide6 приложения...${NC}"
echo.
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo "  Приложение запущено в отдельном окне!"
echo "  Базы данных должны быть запущены через: ./start_all.sh"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo.

python main_pyside.py

echo.
echo -e "${GREEN}✓ Приложение остановлено${NC}"
echo.
