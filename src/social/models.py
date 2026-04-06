# src/social/models.py
"""
Модели данных для социального трейдинга.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class TradeAction(Enum):
    OPEN = "OPEN"
    MODIFY = "MODIFY"
    CLOSE = "CLOSE"

@dataclass
class SocialTradeSignal:
    """Сигнал, передаваемый от Мастера к Подписчику."""
    
    # Информация о мастере
    master_account_id: int
    master_balance: float
    master_equity: float
    
    # Параметры сделки
    ticket: int  # Тикет сделки мастера (для идентификации)
    symbol: str
    action: TradeAction
    type: int  # 0=BUY, 1=SELL (для OPEN)
    
    # Цены
    open_price: float
    current_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    
    # Объем
    volume: float
    
    # Метаданные
    timestamp: datetime = datetime.now()
    comment: str = ""
    magic: int = 0
