# src/data_models.py
"""
Модели данных для торговой системы с валидацией Pydantic.

Обеспечивает:
- Валидацию входных данных
- Типизацию всех полей
- Информативные сообщения об ошибках
"""

import datetime as dt
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, root_validator, validator


class SignalType(Enum):
    """
    Перечисление для типов торговых сигналов.
    Использование Enum делает код более читаемым и безопасным,
    чем использование строк или чисел.
    """

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderType(str, Enum):
    """Типы ордеров для API запросов."""

    BUY = "BUY"
    SELL = "SELL"


class TradeSignalBase(BaseModel):
    """Базовая модель торгового сигнала с валидацией."""

    type: SignalType = Field(..., description="Тип сигнала: BUY, SELL или HOLD")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность сигнала от 0.0 до 1.0")
    symbol: str = Field(..., description="Торговый инструмент (например, EURUSD)")

    @validator("symbol")
    def validate_symbol_format(cls, v):
        """Проверка формата символа."""
        if not v:
            raise ValueError("Символ не может быть пустым")

        # Разрешаем стандартные Forex пары (6 букв)
        if re.match(r"^[A-Z]{6}$", v):
            return v

        # Разрешаем специальные символы
        allowed_special = ["BITCOIN", "GOLD", "SILVER", "XAUUSD", "XAGUSD", "BTCUSD"]
        if v.upper() in allowed_special:
            return v.upper()

        raise ValueError(
            f"Неверный формат символа: {v}. "
            f'Ожидается 6 заглавных букв (например, EURUSD) или один из: {", ".join(allowed_special)}'
        )

    @validator("confidence")
    def validate_confidence(cls, v):
        """Проверка уровня уверенности."""
        if v < 0.3:
            raise ValueError(f"Уверенность сигнала слишком низкая: {v:.3f}. " f"Минимальный порог: 0.3")
        return v


class TradeSignal(TradeSignalBase):
    """
    Расширенная модель торгового сигнала.
    Dataclass с валидацией Pydantic.
    """

    predicted_price: Optional[float] = Field(None, gt=0, description="Прогнозируемая цена (должна быть положительной)")
    stop_loss: Optional[float] = Field(None, gt=0, description="Стоп-лосс (должен быть положительным)")
    take_profit: Optional[float] = Field(None, gt=0, description="Тейк-профит (должен быть положительным)")
    strategy_name: Optional[str] = Field(
        None, min_length=1, max_length=50, description="Название стратегии, сгенерировавшей сигнал"
    )

    @validator("take_profit")
    def validate_take_profit_vs_stop_loss(cls, v, values):
        """Проверка соотношения тейк-профита и стоп-лосса."""
        if v is not None and "stop_loss" in values and values["stop_loss"] is not None:
            sl = values["stop_loss"]
            if v <= sl:
                raise ValueError(f"Take-Profit ({v}) должен быть больше Stop-Loss ({sl})")
        return v

    class Config:
        use_enum_values = True
        extra = "forbid"  # Запрет на дополнительные поля


class TradeRequest(BaseModel):
    """
    Модель запроса на исполнение торговой операции.
    Используется для API endpoints.
    """

    symbol: str = Field(..., min_length=4, max_length=10, description="Торговый инструмент (4-10 символов)")
    lot: float = Field(..., gt=0.0, le=100.0, description="Объем сделки (0 < lot <= 100)")
    order_type: OrderType = Field(..., description="Тип ордера: BUY или SELL")
    stop_loss: Optional[float] = Field(None, gt=0, description="Стоп-лосс (опционально)")
    take_profit: Optional[float] = Field(None, gt=0, description="Тейк-профит (опционально)")
    strategy_name: Optional[str] = Field(None, min_length=1, max_length=50, description="Название стратегии для аудита")

    @validator("symbol")
    def validate_symbol(cls, v):
        """Проверка формата символа."""
        v = v.upper()
        if not re.match(r"^[A-Z]{4,10}$", v) and v not in ["BITCOIN", "GOLD", "SILVER"]:
            raise ValueError(f"Неверный формат символа: {v}. " f"Ожидается 4-10 заглавных букв (например, EURUSD)")
        return v

    @validator("lot")
    def validate_lot(cls, v):
        """Проверка объема сделки."""
        if v > 50.0:
            raise ValueError(
                f"Объем сделки слишком большой: {v}. "
                f"Максимальный лот: 50.0. Для больших объемов используйте множественные ордера."
            )
        return v

    @validator("order_type")
    def validate_order_type(cls, v):
        """Проверка типа ордера."""
        if v not in ["BUY", "SELL"]:
            raise ValueError(f"Неверный тип ордера: {v}. Ожидается BUY или SELL")
        return v

    class Config:
        use_enum_values = True
        extra = "forbid"


class ClosePositionRequest(BaseModel):
    """Модель запроса на закрытие позиции."""

    ticket: int = Field(..., gt=0, description="Номер тикета позиции для закрытия")
    partial_lot: Optional[float] = Field(None, gt=0, le=100.0, description="Объем для частичного закрытия (опционально)")

    @validator("partial_lot")
    def validate_partial_lot(cls, v, values):
        """Проверка объема частичного закрытия."""
        if v is not None and v > 50.0:
            raise ValueError(f"Объем частичного закрытия слишком большой: {v}. " f"Максимум: 50.0")
        return v

    class Config:
        extra = "forbid"


@dataclass
class NewsItem:
    """
    Унифицированная структура для новостного сообщения из любого источника.
    """

    source: str
    text: str
    timestamp: dt.datetime
    asset: Optional[str] = None  # Для какого актива новость (если можно определить)


class NewsItemPydantic(BaseModel):
    """Pydantic версия NewsItem для API."""

    source: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=1)
    timestamp: dt.datetime
    asset: Optional[str] = Field(None, max_length=20)
    sentiment: Optional[float] = Field(None, ge=-1.0, le=1.0, description="Сентимент новости от -1.0 до 1.0")

    @validator("text")
    def validate_text_length(cls, v):
        """Проверка длины текста."""
        if len(v.strip()) < 10:
            raise ValueError("Текст новости слишком короткий (минимум 10 символов)")
        return v

    class Config:
        extra = "forbid"
