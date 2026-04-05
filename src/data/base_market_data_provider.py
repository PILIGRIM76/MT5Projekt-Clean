"""
Базовый абстрактный интерфейс провайдера рыночных данных.

Определяет единый контракт для всех источников данных (MT5, крипто-биржи, фондовые биржи).
Позволяет системе торговать с любым источником без изменения бизнес-логики.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class OrderType(str, Enum):
    """Типы ордеров, поддерживаемые провайдерами."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(str, Enum):
    """Направление ордера."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Статус исполнения ордера."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TimeFrame:
    """Унифицированные таймфреймы для всех провайдеров."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H6 = "6h"
    H8 = "8h"
    H12 = "12h"
    D1 = "1d"
    W1 = "1w"
    MN = "1M"

    @staticmethod
    def to_minutes(tf_str: str) -> int:
        """Конвертирует строку таймфрейма в минуты."""
        mapping = {
            "1m": 1,
            "3m": 3,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "2h": 120,
            "4h": 240,
            "6h": 360,
            "8h": 480,
            "12h": 720,
            "1d": 1440,
            "1w": 10080,
            "1M": 43200,
        }
        return mapping.get(tf_str, 60)


class MarketOrder:
    """Унифицированная структура ордера."""

    def __init__(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        volume: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_id: Optional[str] = None,
        status: OrderStatus = OrderStatus.PENDING,
        fill_price: Optional[float] = None,
        commission: float = 0.0,
        timestamp: Optional[datetime] = None,
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.volume = volume
        self.price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.order_id = order_id
        self.status = status
        self.fill_price = fill_price
        self.commission = commission
        self.timestamp = timestamp or datetime.utcnow()
        self.raw_response = raw_response

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "volume": self.volume,
            "price": self.price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "order_id": self.order_id,
            "status": self.status.value,
            "fill_price": self.fill_price,
            "commission": self.commission,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class Position:
    """Унифицированная структура позиции."""

    def __init__(
        self,
        symbol: str,
        side: str,
        volume: float,
        entry_price: float,
        current_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        unrealized_pnl: float = 0.0,
        realized_pnl: float = 0.0,
        commission: float = 0.0,
        swap: float = 0.0,
        timestamp: Optional[datetime] = None,
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        self.symbol = symbol
        self.side = side
        self.volume = volume
        self.entry_price = entry_price
        self.current_price = current_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.unrealized_pnl = unrealized_pnl
        self.realized_pnl = realized_pnl
        self.commission = commission
        self.swap = swap
        self.timestamp = timestamp or datetime.utcnow()
        self.raw_response = raw_response

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "commission": self.commission,
            "swap": self.swap,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class Balance:
    """Унифицированная структура баланса."""

    def __init__(
        self,
        total: float,
        free: float,
        used: float,
        currency: str = "USD",
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        self.total = total
        self.free = free
        self.used = used
        self.currency = currency
        self.raw_response = raw_response

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "free": self.free,
            "used": self.used,
            "currency": self.currency,
        }


class BaseMarketDataProvider(ABC):
    """
    Абстрактный базовый класс для всех провайдеров рыночных данных.

    Каждый конкретный провайдер (MT5, Binance, Interactive Brokers и т.д.)
    должен реализовать этот интерфейс.
    """

    @abstractmethod
    async def initialize(self) -> bool:
        """
        Инициализация подключения к провайдеру.
        Возвращает True при успешном подключении.
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Корректное закрытие соединения."""
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        """Проверка статуса соединения."""
        pass

    # === РАНОЧНЫЕ ДАННЫЕ ===

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        since: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Получение OHLCV-данных (свечи).

        Args:
            symbol: Торговый символ (напр. "EURUSD" для MT5 или "BTC/USDT" для ccxt)
            timeframe: Строка таймфрейма ("1m", "5m", "1h", "1d", ...)
            limit: Количество баров
            since: Начальная дата (опционально)

        Returns:
            DataFrame с колонками: open, high, low, close, volume,
            plus tick_volume, symbol. Индекс: datetime.
        """
        pass

    @abstractmethod
    async def get_tick(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        Получение текущего тика (bid/ask/last).

        Args:
            symbol: Торговый символ

        Returns:
            Словарь с ключами: bid, ask, last, volume, timestamp
            или None при ошибке.
        """
        pass

    @abstractmethod
    async def get_symbols(self) -> List[str]:
        """
        Получение списка доступных торговых символов.

        Returns:
            Список строк с именами символов.
        """
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получение информации о символе.

        Args:
            symbol: Торговый символ

        Returns:
            Словарь с информацией: point, digits, trade_mode,
            volume_min, volume_max, volume_step, spread, swap и т.д.
        """
        pass

    @abstractmethod
    async def get_spread(self, symbol: str) -> float:
        """
        Получение текущего спреда в пунктах.

        Args:
            symbol: Торговый символ

        Returns:
            Спред в пунктах (float).
        """
        pass

    # === ТОРГОВЛЯ ===

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        volume: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
    ) -> Optional[MarketOrder]:
        """
        Размещение ордера.

        Args:
            symbol: Торговый символ
            side: Направление (BUY/SELL)
            order_type: Тип ордера (MARKET/LIMIT/STOP)
            volume: Объем позиции
            price: Цена для отложенных ордеров (None для рыночных)
            stop_loss: Цена стоп-лосса
            take_profit: Цена тейк-профита
            comment: Комментарий к ордеру

        Returns:
            Объект MarketOrder с информацией об ордере или None.
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """
        Отмена отложенного ордера.

        Args:
            order_id: ID ордера

        Returns:
            True при успешной отмене.
        """
        pass

    @abstractmethod
    async def close_position(self, symbol: str, volume: Optional[float] = None) -> bool:
        """
        Закрытие позиции по символу.

        Args:
            symbol: Торговый символ
            volume: Объем для закрытия (None = закрыть всё)

        Returns:
            True при успешном закрытии.
        """
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """
        Получение списка открытых позиций.

        Returns:
            Список объектов Position.
        """
        pass

    @abstractmethod
    async def get_balance(self, currency: Optional[str] = None) -> Optional[Balance]:
        """
        Получение баланса счёта.

        Args:
            currency: Валюта (None = основная валюта счёта)

        Returns:
            Объект Balance или None.
        """
        pass

    # === ВСПОМОГАТЕЛЬНЫЕ ===

    @abstractmethod
    async def get_minimum_lot_size(self, symbol: str) -> Optional[float]:
        """
        Получение минимального размера лота для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Минимальный объем лота или None.
        """
        pass

    @abstractmethod
    async def get_lot_step(self, symbol: str) -> Optional[float]:
        """
        Получение шага лота (минимальное изменение объема).

        Args:
            symbol: Торговый символ

        Returns:
            Шаг лота или None.
        """
        pass

    @abstractmethod
    async def get_account_info(self) -> Optional[Dict[str, Any]]:
        """
        Получение информации о счёте.

        Returns:
            Словарь с информацией: login, balance, equity, margin,
            free_margin, leverage, currency, name и т.д.
        """
        pass

    @abstractmethod
    async def get_conversion_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Получение курса конвертации валют.

        Args:
            from_currency: Исходная валюта
            to_currency: Целевая валюта

        Returns:
            Курс конвертации (1.0 если не найден).
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Возвращает название провайдера.

        Returns:
            Строка с названием провайдера.
        """
        pass

    @abstractmethod
    def get_provider_type(self) -> str:
        """
        Возвращает тип провайдера (MT5, CRYPTO, STOCKS, ...).

        Returns:
            Строка с типом провайдера.
        """
        pass
