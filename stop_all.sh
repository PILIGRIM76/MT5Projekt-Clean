#!/bin/bash
# Genesis Trading System - Остановка всех сервисов
# Использование: ./stop_all.sh [--volumes]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Флаг для удаления volumes
REMOVE_VOLUMES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --volumes)
            REMOVE_VOLUMES=true
            shift
            ;;
        -h|--help)
            echo "Использование: $0 [OPTIONS]"
            echo ""
            echo "OPTIONS:"
            echo "  --volumes    Удалить все volumes (данные будут потеряны!)"
            echo "  -h, --help   Показать эту справку"
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
echo "║     Genesis Trading System - Остановка экосистемы         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

if [ "$REMOVE_VOLUMES" = true ]; then
    echo -e "${RED}⚠ ВНИМАНИЕ: Все данные будут удалены!${NC}"
    echo -n "Продолжить? (y/N): "
    read -r response
    if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        echo "Отменено"
        exit 0
    fi

    echo -e "${YELLOW}→ Остановка и удаление контейнеров и volumes...${NC}"
    docker-compose down --volumes --remove-orphans
else
    echo -e "${YELLOW}→ Остановка контейнеров...${NC}"
    docker-compose down --remove-orphans
fi

echo ""
echo -e "${GREEN}✓ Экосистема остановлена${NC}"
echo ""

if [ "$REMOVE_VOLUMES" = true ]; then
    echo -e "${RED}⚠ Все данные удалены!${NC}"
else
    echo "Данные сохранены в volumes. Для полного удаления используйте:"
    echo "  $0 --volumes"
fi
echo ""
