# Dockerfile для Genesis Trading System
# Версия: 1.0
# Дата: 27 марта 2026

# ===========================================
# Base Image
# ===========================================
FROM python:3.10-slim

# ===========================================
# Environment Variables
# ===========================================
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PYSIDE6_DISABLE_OPENGL=1

# ===========================================
# System Dependencies
# ===========================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools
    gcc \
    g++ \
    make \
    cmake \
    pkg-config \
    # C libraries
    libatlas-base-dev \
    libblas-dev \
    liblapack-dev \
    libgomp1 \
    # GUI dependencies (for PySide6)
    libgl1-mesa-glx \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    libxcb-xfixes0 \
    # Cleanup
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ===========================================
# Working Directory
# ===========================================
WORKDIR /app

# ===========================================
# Copy Requirements
# ===========================================
COPY requirements.txt .

# ===========================================
# Install Python Dependencies
# ===========================================
RUN pip install --no-cache-dir -r requirements.txt

# ===========================================
# Copy Application Code
# ===========================================
COPY . .

# ===========================================
# Create Volumes
# ===========================================
VOLUME ["/app/database", "/app/logs", "/app/configs"]

# ===========================================
# Expose Ports
# ===========================================
# FastAPI Web Dashboard
EXPOSE 8000
# Prometheus Metrics
EXPOSE 8080

# ===========================================
# Health Check
# ===========================================
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/status', timeout=5)" || exit 1

# ===========================================
# Labels
# ===========================================
LABEL maintainer="Genesis Trading Team" \
      version="13.0.0" \
      description="AI-Powered Trading System with Multi-Strategy Consensus" \
      repository="https://github.com/PILIGRIM76/MT5Projekt-Clean"

# ===========================================
# Default Command
# ===========================================
# For headless mode (no GUI)
CMD ["python", "-m", "src.core.trading_system"]

# ===========================================
# Alternative Commands
# ===========================================
# For GUI mode (requires X11 forwarding)
# CMD ["python", "main_pyside.py"]

# For web-only mode
# CMD ["python", "-m", "src.web.server"]

# For development mode with hot reload
# CMD ["python", "-m", "uvicorn", "src.web.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
