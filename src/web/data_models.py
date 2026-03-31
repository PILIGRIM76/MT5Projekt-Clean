from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SystemStatus(BaseModel):
    """Полная модель состояния системы."""

    is_running: bool
    mode: str
    uptime: str
    balance: float
    equity: float
    current_drawdown: float = 0.0


class Position(BaseModel):
    """Модель для одной активной позиции."""

    ticket: int
    symbol: str
    strategy: str
    type: str
    volume: float
    profit: float
    timeframe: str = "N/A"
    bars: str = "0"


class HistoricalTrade(BaseModel):
    """Модель для сделки из истории (для графика P&L)."""

    ticket: int
    symbol: str
    profit: float
    time_close: datetime


class ControlResponse(BaseModel):
    """Стандартный ответ для управляющих команд."""

    success: bool
    message: str


class WebSocketMessage(BaseModel):
    """Базовая модель для всех WebSocket сообщений."""

    type: str
    payload: dict
