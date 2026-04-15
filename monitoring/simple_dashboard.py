import json
import os
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# Автоматическое определение пути к логам
LOG_FILE = Path(__file__).parent.parent / "logs" / "app.log"


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/stats")
def stats():
    try:
        if not LOG_FILE.exists():
            return jsonify({"error": f"Log file not found: {LOG_FILE}"}), 404

        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        # Паттерны под ВАШИ логи (русскоязычные + эмодзи)
        patterns = {
            "ticks": [
                r"Загружено \d+ баров",  # "Загружено 1000 баров из MT5"
                r"Saved \d+ bars",  # "Saved 12 bars for EURUSD"
                r"ticks_received",  # Prometheus-метрика (если есть)
                r"MarketFeed started",  # Старт сбора данных
            ],
            "orders": [
                r"DRY-RUN:",  # "📝 DRY-RUN: BUY EURUSD"
                r"order_executed",  # Prometheus-метрика
                r"Order executed:",  # Успешное исполнение
                r"Исполнен ордер",  # Русскоязычный лог
            ],
            "predictions": [
                r"Prediction:",  # "🎯 Prediction: EURUSD 0.72"
                r"предсказание",  # Русскоязычный вариант
                r"predictions_made",  # Prometheus-метрика
                r"model_prediction",  # Событие EventBus
            ],
            "errors": [r"ERROR", r"CRITICAL", r"❌", r"Traceback"],
        }

        result = {}
        for key, regex_list in patterns.items():
            count = sum(len(re.findall(pattern, content, re.IGNORECASE)) for pattern in regex_list)
            result[key] = count

        result["last_update"] = datetime.now().isoformat()
        result["log_file"] = str(LOG_FILE)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "log_file": str(LOG_FILE)}), 500


@app.route("/api/events")
def events():
    try:
        if not LOG_FILE.exists():
            return jsonify([])

        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-40:]  # Последние 40 строк

        result = []
        keywords = [
            "prediction",
            "DRY-RUN",
            "order",
            "HEALTH",
            "ERROR",
            "CRITICAL",
            "Загружено",
            "Исполнен",
            "предсказание",
            "🎯",
            "💾",
            "📝",
            "✅",
            "❌",
        ]

        for line in lines:
            if any(kw.lower() in line.lower() for kw in keywords):
                # Определение уровня
                if any(kw in line for kw in ["ERROR", "CRITICAL", "❌", "Traceback"]):
                    level = "error"
                elif any(kw in line for kw in ["✅", "успешно", "started", "active"]):
                    level = "success"
                elif any(kw in line for kw in ["DRY-RUN", "prediction", "🎯", "📝"]):
                    level = "info"
                else:
                    level = "neutral"

                result.append({"level": level, "message": line.strip(), "timestamp": datetime.now().isoformat()})

        return jsonify(result)
    except Exception as e:
        return jsonify([{"level": "error", "message": f"Error reading logs: {e}"}])


HTML_TEMPLATE = """
<!DOCTYPE html>
<html><head><title>MT5Projekt Monitor</title>
<meta http-equiv="refresh" content="10">
<style>
body { font-family: 'Consolas', 'Courier New', monospace; background: #1e1e2e; color: #cdd6f4; padding: 20px; margin: 0; }
h1 { color: #89b4fa; border-bottom: 2px solid #45475a; padding-bottom: 10px; }
.card { background: #313244; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #585b70; }
.card h3 { margin-top: 0; color: #94e2d5; }
.metric { font-size: 1.4em; font-weight: bold; margin: 8px 0; }
.metric span { color: #f9e2af; }
.error { color: #f38ba8; }
.success { color: #a6e3a1; }
.info { color: #89b4fa; }
.neutral { color: #a6adc8; }
#stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.stat-item { background: #45475a; padding: 10px; border-radius: 5px; text-align: center; }
.event-log { max-height: 400px; overflow-y: auto; background: #181825; padding: 10px; border-radius: 5px; }
.event-log p { margin: 5px 0; font-size: 0.9em; }
.footer { text-align: center; color: #6c7086; font-size: 0.8em; margin-top: 20px; }
</style></head><body>
<h1>📊 MT5Projekt-Clean Monitor</h1>

<div class="card" id="stats">
    <div class="stat-item">📈 Тики: <span id="ticks">...</span></div>
    <div class="stat-item">💹 Ордеры: <span id="orders">...</span></div>
    <div class="stat-item">🤖 Предсказания: <span id="predictions">...</span></div>
    <div class="stat-item">⚠ Ошибки: <span id="errors" class="error">...</span></div>
</div>

<div class="card">
    <h3>🔔 Последние события</h3>
    <div id="events" class="event-log">Загрузка...</div>
</div>

<div class="footer">
    Авто-обновление: 10 сек | Лог-файл: <span id="logPath">...</span>
</div>

<script>
async function update() {
    try {
        // Статистика
        const stats = await fetch("/api/stats").then(r => r.json());
        if (stats.error) {
            document.getElementById("stats").innerHTML = `<p class="error">❌ ${stats.error}</p>`;
            return;
        }
        document.getElementById("ticks").textContent = stats.ticks ?? 0;
        document.getElementById("orders").textContent = stats.orders ?? 0;
        document.getElementById("predictions").textContent = stats.predictions ?? 0;
        document.getElementById("errors").textContent = stats.errors ?? 0;
        document.getElementById("logPath").textContent = stats.log_file || "unknown";

        // События
        const events = await fetch("/api/events").then(r => r.json());
        const eventsDiv = document.getElementById("events");
        if (events.length === 0) {
            eventsDiv.innerHTML = "<p class='neutral'>⏳ Ожидание событий...</p>";
        } else {
            eventsDiv.innerHTML = events.map(ev =>
                `<p class="${ev.level}">${ev.message}</p>`
            ).join("");
            // Авто-прокрутка вниз
            eventsDiv.scrollTop = eventsDiv.scrollHeight;
        }
    } catch (e) {
        console.error("Update error:", e);
        document.getElementById("stats").innerHTML += `<p class="error">⚠ Ошибка обновления: ${e.message}</p>`;
    }
}
// Первое обновление сразу, затем каждые 10 сек
update();
setInterval(update, 10000);
</script></body></html>
"""

if __name__ == "__main__":
    print(f"📊 MT5Projekt Monitor started")
    print(f"📁 Log file: {LOG_FILE}")
    print(f"🌐 Open: http://127.0.0.1:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
