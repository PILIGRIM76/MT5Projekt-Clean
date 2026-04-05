#!/bin/bash
# Genesis Trading System - Запуск всех баз данных и экосистемы
# Использование: ./start_all.sh [--databases-only] [--detach]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Флаги
DATABASES_ONLY=false
DETACH=true

# Парсинг аргументов
while [[ $# -gt 0 ]]; do
    case $1 in
        --databases-only)
            DATABASES_ONLY=true
            shift
            ;;
        --foreground)
            DETACH=false
            shift
            ;;
        -h|--help)
            echo "Использование: $0 [OPTIONS]"
            echo ""
            echo "OPTIONS:"
            echo "  --databases-only  Запустить только базы данных (без trading-system)"
            echo "  --foreground        Запустить в foreground режиме"
            echo "  -h, --help          Показать эту справку"
            exit 0
            ;;
        *)
            echo "Неизвестный аргумент: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Genesis Trading System - Запуск экосистемы            ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Проверка Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker не установлен${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}✗ Docker Compose не установлен${NC}"
    exit 1
fi

# Проверка .env файла
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ Файл .env не найден. Создаю из .env.example...${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ .env создан. Отредактируйте файл с вашими настройками${NC}"
    else
        echo -e "${YELLOW}⚠ .env.example не найден. Продолжаю без .env...${NC}"
    fi
fi

# Функция для проверки статуса сервиса
check_service() {
    local service=$1
    local status=$(docker-compose ps --format json "$service" 2>/dev/null | jq -r '.State' 2>/dev/null || echo "not_found")

    case $status in
        "running")
            echo -e "${GREEN}●${NC}"
            ;;
        "starting"|"healthy")
            echo -e "${YELLOW}◐${NC}"
            ;;
        "unhealthy"|"exited")
            echo -e "${RED}○${NC}"
            ;;
        *)
            echo -e "${RED}✗${NC}"
            ;;
    esac
}

# Функция для ожидания готовности БД
wait_for_db() {
    local service=$1
    local port=$2
    local max_attempts=${3:-30}
    local attempt=1

    echo -ne "${YELLOW}Ожидание $service...${NC}"

    while [ $attempt -le $max_attempts ]; do
        if docker-compose ps "$service" | grep -q "running\|healthy"; then
            echo -e "${GREEN} ✓${NC}"
            return 0
        fi
        echo -ne "."
        sleep 2
        ((attempt++))
    done

    echo -e "${RED} ✗ (таймаут)${NC}"
    return 1
}

# Остановка существующих контейнеров
echo -e "${YELLOW}→ Остановка существующих контейнеров...${NC}"
docker-compose down --remove-orphans 2>/dev/null || true

# Запуск баз данных
echo -e "${BLUE}"
echo "═══════════════════════════════════════════════════════════"
echo "  ЗАПУСК БАЗ ДАННЫХ"
echo "═══════════════════════════════════════════════════════════"
echo -e "${NC}"

echo -e "${YELLOW}→ Запуск PostgreSQL, TimescaleDB, QuestDB, Qdrant, Redis...${NC}"

if [ "$DETACH" = true ]; then
    docker-compose up -d db timescaledb questdb qdrant redis
else
    docker-compose up db timescaledb questdb qdrant redis
fi

# Ожидание готовности БД
echo ""
echo -e "${BLUE}→ Проверка готовности баз данных...${NC}"
sleep 5

wait_for_db "db" 5432
wait_for_db "timescaledb" 5433
wait_for_db "questdb" 9001
wait_for_db "qdrant" 6333
wait_for_db "redis" 6379

echo ""

# Если только базы данных - завершаем
if [ "$DATABASES_ONLY" = true ]; then
    echo -e "${GREEN}✓ Базы данных запущены!${NC}"
    echo ""
    echo "Подключение к базам данных:"
    echo "  PostgreSQL:   localhost:5432 (trading)"
    echo "  TimescaleDB:  localhost:5433 (trading_ts)"
    echo "  QuestDB:      localhost:9000 (questdb)"
    echo "  Qdrant:       localhost:6333"
    echo "  Redis:        localhost:6379"
    echo ""
    exit 0
fi

# Запуск основного приложения
echo -e "${BLUE}"
echo "═══════════════════════════════════════════════════════════"
echo "  ЗАПУСК TRADING SYSTEM"
echo "═══════════════════════════════════════════════════════════"
echo -e "${NC}"

echo -e "${YELLOW}→ Запуск trading-system...${NC}"

if [ "$DETACH" = true ]; then
    docker-compose up -d trading-system
else
    docker-compose up trading-system
fi

# Ожидание готовности приложения
sleep 10
wait_for_db "trading-system" 8000

# Итоговый статус
echo ""
echo -e "${BLUE}"
echo "═══════════════════════════════════════════════════════════"
echo "  СТАТУС ЭКОСИСТЕМЫ"
echo "═══════════════════════════════════════════════════════════"
echo -e "${NC}"

echo "Сервисы:"
echo "  $(check_service) PostgreSQL (db:5432)"
echo "  $(check_service) TimescaleDB (timescaledb:5433)"
echo "  $(check_service) QuestDB (questdb:9000)"
echo "  $(check_service) Qdrant (qdrant:6333)"
echo "  $(check_service) Redis (redis:6379)"
echo "  $(check_service) Trading System (trading-system:8000)"
echo "  $(check_service) Prometheus (prometheus:9090)"
echo "  $(check_service) Grafana (grafana:3000)"

echo ""
echo -e "${GREEN}✓ Экосистема Genesis запущена!${NC}"
echo ""
echo "Доступ к сервисам:"
echo "  Web Dashboard:    http://localhost:8000"
echo "  Grafana:          http://localhost:3000"
echo "  Prometheus:       http://localhost:9090"
echo "  QuestDB Console:  http://localhost:9001"
echo ""
echo "Базы данных:"
echo "  PostgreSQL:       localhost:5432 (db: trading)"
echo "  TimescaleDB:      localhost:5433 (db: trading_ts)"
echo "  QuestDB:          localhost:9000 (db: questdb)"
echo "  Qdrant:           localhost:6333"
echo "  Redis:            localhost:6379"
echo ""
echo "Остановка:"
echo "  ./stop_all.sh"
echo ""
echo "Логи:"
echo "  ./logs.sh"
echo ""
