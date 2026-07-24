#!/bin/bash
set -e

echo "🚀 Запуск MT5Projekt-Clean Demo + Monitoring..."

# 1. Проверка зависимостей
command -v docker-compose >/dev/null 2>&1 || { echo "❌ docker-compose required"; exit 1; }
command -v sqlite3 >/dev/null 2>&1 || { echo "❌ sqlite3 required"; exit 1; }

# 2. Запуск мониторинга
echo "📊 Starting monitoring stack..."
docker-compose -f docker-compose.monitoring.yml up -d

# 3. Ожидание готовности сервисов
echo "⏳ Waiting for services to be ready..."
sleep 10

# 4. Проверка Grafana
if curl -s -u admin:admin123 http://localhost:3000/api/health | grep -q "ok"; then
    echo "✅ Grafana is ready: http://localhost:3000"
else
    echo "⚠️  Grafana not ready yet — check logs with: docker-compose -f docker-compose.monitoring.yml logs grafana"
fi

# 5. Запуск приложения
echo "🤖 Starting MT5Projekt-Clean..."
python main_pyside.py --config config/production.yaml

echo "✅ Done. Monitor at: http://localhost:3000"
