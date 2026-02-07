#src\data_models.py
import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class SignalType(Enum):
    """
    Перечисление для типов торговых сигналов.
    Использование Enum делает код более читаемым и безопасным,
    чем использование строк или чисел.
    """
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

@dataclass
class TradeSignal:
    """
    Структура данных (dataclass) для хранения информации о торговом сигнале.
    Использование dataclass автоматически создает __init__, __repr__ и другие
    полезные методы.
    """
    type: SignalType
    confidence: float
    predicted_price: Optional[float] = None # Необязательное поле для цены

# Вы можете добавить сюда другие модели данных, если они понадобятся,
# например, для ордеров или результатов сделок.


@dataclass
class NewsItem:
    """
    Унифицированная структура для новостного сообщения из любого источника.
    """
    source: str
    text: str
    timestamp: datetime
    asset: Optional[str] = None # Для какого актива новость (если можно определить)


