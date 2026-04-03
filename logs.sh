#!/bin/bash
# Genesis Trading System - Просмотр логов
# Использование: ./logs.sh [service] [--follow]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SERVICE=$1
FOLLOW=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--follow)
            FOLLOW=true
            shift
            ;;
        -h|--help)
            echo "Использование: $0 [SERVICE] [OPTIONS]"
            echo ""
            echo "SERVICE: db, timescaledb, questdb, qdrant, redis,"
            echo "         trading-system, prometheus, grafana, nginx"
            echo ""
            echo "OPTIONS:"
            echo "  -f, --follow    Режим реального времени (tail -f)"
            echo "  -h, --help      Показать эту справку"
            echo ""
            echo "Примеры:"
            echo "  $0 trading-system        # Логи trading-system"
            echo "  $0 db                    # Логи PostgreSQL"
            echo "  $0 --follow              # Все логи в реальном времени"
            echo "  $0 db -f                 # Логи PostgreSQL в реальном времени"
            exit 0
            ;;
        *)
            SERVICE=$1
            shift
            ;;
    esac
done

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Genesis Trading System - Логи                         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

if [ "$FOLLOW" = true ]; then
    if [ -n "$SERVICE" ]; then
        echo -e "${YELLOW}→ Логи сервиса '$SERVICE' (режим реального времени)...${NC}"
        docker-compose logs -f "$SERVICE"
    else
        echo -e "${YELLOW}→ Логи всех сервисов (режим реального времени)...${NC}"
        docker-compose logs -f
    fi
else
    if [ -n "$SERVICE" ]; then
        echo -e "${YELLOW}→ Логи сервиса '$SERVICE'...${NC}"
        docker-compose logs "$SERVICE"
    else
        echo -e "${YELLOW}→ Логи всех сервисов...${NC}"
        docker-compose logs
    fi
fi
