#!/bin/bash
# Genesis Trading System - Запуск всей экосистемы (БД + Desktop приложение)
# Использование: ./start_ecosystem.sh

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
echo "║     Genesis Trading System - Запуск экосистемы            ║"
echo "║     (Базы данных + Десктопное приложение PySide6)         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Проверка Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker не установлен${NC}"
    echo -e "${YELLOW}Установите Docker: https://docs.docker.com/get-docker/${NC}"
    exit 1
fi

# Проверка Docker Compose
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo -e "${RED}✗ Docker Compose не установлен${NC}"
    exit 1
fi

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
        echo -e "${GREEN}✓ .env создан. Отредактируйте с вашими настройками${NC}"
    fi
fi

# Шаг 1: Запуск баз данных
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo "  ШАГ 1: Запуск баз данных (PostgreSQL, TimescaleDB, Qdrant...)"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${YELLOW}→ Запуск контейнеров с базами данных...${NC}"
$COMPOSE_CMD up -d db timescaledb questdb qdrant redis

echo ""
echo -e "${YELLOW}→ Ожидание готовности баз данных...${NC}"
sleep 10

# Проверка готовности PostgreSQL
echo -e "${YELLOW}→ Проверка PostgreSQL...${NC}"
if $COMPOSE_CMD exec db pg_isready -U trading_user &> /dev/null; then
    echo -e "${GREEN}  ✓ PostgreSQL готов${NC}"
else
    echo -e "${RED}  ✗ PostgreSQL не готов${NC}"
fi

# Проверка готовности TimescaleDB
echo -e "${YELLOW}→ Проверка TimescaleDB...${NC}"
if $COMPOSE_CMD exec timescaledb pg_isready -U trading_user &> /dev/null; then
    echo -e "${GREEN}  ✓ TimescaleDB готов${NC}"
else
    echo -e "${RED}  ✗ TimescaleDB не готов${NC}"
fi

# Проверка готовности Redis
echo -e "${YELLOW}→ Проверка Redis...${NC}"
if $COMPOSE_CMD exec redis redis-cli ping &> /dev/null; then
    echo -e "${GREEN}  ✓ Redis готов${NC}"
else
    echo -e "${RED}  ✗ Redis не готов${NC}"
fi

echo ""
echo -e "${GREEN}✓ Базы данных запущены и готовы к работе${NC}"
echo ""

# Шаг 2: Запуск десктопного приложения
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo "  ШАГ 2: Запуск десктопного приложения PySide6"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

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
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo "  Приложение будет запущено в отдельном окне!"
echo "  Подключение к базам данных:"
echo "    PostgreSQL:   localhost:5432"
echo "    TimescaleDB:  localhost:5433"
echo "    Qdrant:       localhost:6333"
echo "    Redis:        localhost:6379"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

python main_pyside.py

echo ""
echo -e "${GREEN}✓ Приложение остановлено${NC}"
echo ""
