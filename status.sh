#!/bin/bash
# Genesis Trading System - Проверка статуса
# Использование: ./status.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Genesis Trading System - Статус экосистемы            ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Проверка Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker не установлен${NC}"
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

# Получение статуса контейнеров
echo -e "${CYAN}КОНТЕЙНЕРЫ:${NC}"
echo ""

services=("db" "timescaledb" "questdb" "qdrant" "redis" "trading-system" "prometheus" "grafana")

for service in "${services[@]}"; do
    status=$($COMPOSE_CMD ps --format json "$service" 2>/dev/null | jq -r '.State' 2>/dev/null || echo "not_found")
    ports=$($COMPOSE_CMD ps --format json "$service" 2>/dev/null | jq -r '.Publishers[].PublishedPort' 2>/dev/null | tr '\n' ',' | sed 's/,$//')

    case $status in
        "running")
            status_icon="${GREEN}●${NC}"
            status_text="${GREEN}RUNNING${NC}"
            ;;
        "starting"|"healthy")
            status_icon="${YELLOW}◐${NC}"
            status_text="${YELLOW}STARTING${NC}"
            ;;
        "unhealthy"|"exited")
            status_icon="${RED}○${NC}"
            status_text="${RED}STOPPED${NC}"
            ;;
        *)
            status_icon="${RED}✗${NC}"
            status_text="${RED}NOT FOUND${NC}"
            ;;
    esac

    printf "  %b %-20s %b" "$status_icon" "$service" "$status_text"
    if [ -n "$ports" ]; then
        printf " (port: %s)" "$ports"
    fi
    echo ""
done

echo ""
echo -e "${CYAN}ТОМЫ:${NC}"
echo ""

volumes=("postgres_data" "timescaledb_data" "questdb_data" "qdrant_storage" "redis_data" "trading_data" "trading_logs")

for volume in "${volumes[@]}"; do
    exists=$(docker volume ls --format "{{.Name}}" | grep -c "^${volume}$" || echo "0")

    if [ "$exists" -gt 0 ]; then
        echo -e "  ${GREEN}●${NC} $volume"
    else
        echo -e "  ${YELLOW}○${NC} $volume (не создан)"
    fi
done

echo ""
echo -e "${CYAN}СЕТИ:${NC}"
echo ""

networks=("genesis-trading-network" "genesis-trading_default")

for network in "${networks[@]}"; do
    exists=$(docker network ls --format "{{.Name}}" | grep -c "^${network}$" || echo "0")

    if [ "$exists" -gt 0 ]; then
        echo -e "  ${GREEN}●${NC} $network"
    else
        echo -e "  ${YELLOW}○${NC} $network (не создана)"
    fi
done

echo ""
echo -e "${CYAN}БАЗЫ ДАННЫХ:${NC}"
echo ""

# Проверка PostgreSQL
echo -n "  PostgreSQL (localhost:5432): "
if docker-compose ps db | grep -q "running\|healthy"; then
    tables=$(docker-compose exec -T db psql -U trading_user -d trading -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ' || echo "?")
    echo -e "${GREEN}● CONNECTED${NC} (tables: $tables)"
else
    echo -e "${RED}○ NOT AVAILABLE${NC}"
fi

# Проверка TimescaleDB
echo -n "  TimescaleDB (localhost:5433): "
if docker-compose ps timescaledb | grep -q "running\|healthy"; then
    tables=$(docker-compose exec -T timescaledb psql -U trading_user -d trading_ts -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ' || echo "?")
    echo -e "${GREEN}● CONNECTED${NC} (tables: $tables)"
else
    echo -e "${RED}○ NOT AVAILABLE${NC}"
fi

# Проверка QuestDB
echo -n "  QuestDB (localhost:9000): "
if docker-compose ps questdb | grep -q "running\|healthy"; then
    echo -e "${GREEN}● CONNECTED${NC}"
else
    echo -e "${RED}○ NOT AVAILABLE${NC}"
fi

# Проверка Qdrant
echo -n "  Qdrant (localhost:6333): "
if docker-compose ps qdrant | grep -q "running\|healthy"; then
    collections=$(curl -s http://localhost:6333/collections 2>/dev/null | jq -r '.result.collections | length' 2>/dev/null || echo "?")
    echo -e "${GREEN}● CONNECTED${NC} (collections: $collections)"
else
    echo -e "${RED}○ NOT AVAILABLE${NC}"
fi

# Проверка Redis
echo -n "  Redis (localhost:6379): "
if docker-compose ps redis | grep -q "running\|healthy"; then
    keys=$(docker-compose exec -T redis redis-cli DBSIZE 2>/dev/null | tr -d ' ' || echo "?")
    echo -e "${GREEN}● CONNECTED${NC} (keys: $keys)"
else
    echo -e "${RED}○ NOT AVAILABLE${NC}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Управление:"
echo "  Запуск:     ./start_all.sh"
echo "  Остановка:  ./stop_all.sh"
echo "  Логи:       ./logs.sh [service]"
echo "  Статус:     ./status.sh"
echo ""
