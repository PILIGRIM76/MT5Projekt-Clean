import re
import time
from pathlib import Path

from flask import Flask, jsonify

app = Flask(__name__)
LOG_PATH = Path(r"F:\MT5Qoder\MT5Projekt-Clean\logs\app.log")


@app.route("/")
def index():
    return "<h1>✅ Dashboard OK</h1><p>Check /api/stats</p>"


@app.route("/api/stats")
def stats():
    if not LOG_PATH.exists():
        return jsonify({"error": "Log not found", "path": str(LOG_PATH)}), 404

    with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()[-50000:]  # Последние 50KB

    return jsonify(
        {
            "ok": True,
            "log_size": len(content),
            "has_predictions": bool(re.search(r"Prediction:", content)),
            "has_orders": bool(re.search(r"DRY-RUN:|order", content)),
            "has_errors": bool(re.search(r"ERROR|CRITICAL", content)),
            "timestamp": time.time(),
        }
    )


if __name__ == "__main__":
    print(f"📊 Log exists: {LOG_PATH.exists()}")
    app.run(port=8080, debug=False)
