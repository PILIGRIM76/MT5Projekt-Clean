"""
CryptoExchangeProvider — провайдер данных для криптовалютных бирч через ccxt.

Поддерживает 100+ бирч: Binance, Bybit, OKX, Kraken, KuCoin и др.
Реализует единый интерфейс BaseMarketDataProvider для бесшовной интеграции
с существующей архитектурой Genesis Trading System.

Особенности:
- Спотовый и фьючерсный рынки
- Асинхронные запросы через ccxt.pro (если установлен)
- Автоматическая обработка rate limits
- Конвертация валют через внутренние пары биржи
- Кэширование OHLCV данных
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import ccxt
import ccxt.async_support as ccxt_async
import pandas as pd

from src.data.base_market_data_provider import (
    Balance,
    BaseMarketDataProvider,
    MarketOrder,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TimeFrame,
)

logger = logging.getLogger(__name__)

# Маппинг таймфреймов ccxt -> унифицированные
CCXT_TIMEFRAME_MAP = {
    "1m": TimeFrame.M1,
    "3m": TimeFrame.M3,
    "5m": TimeFrame.M5,
    "15m": TimeFrame.M15,
    "30m": TimeFrame.M30,
    "1h": TimeFrame.H1,
    "2h": TimeFrame.H2,
    "4h": TimeFrame.H4,
    "6h": TimeFrame.H6,
    "8h": TimeFrame.H8,
    "12h": TimeFrame.H12,
    "1d": TimeFrame.D1,
    "1w": TimeFrame.W1,
    "1M": TimeFrame.MN,
}

# Обратный маппинг
REVERSE_TIMEFRAME_MAP = {v: k for k, v in CCXT_TIMEFRAME_MAP.items()}


class CryptoExchangeConfig:
    """Конфигурация крипто-биржи."""

    def __init__(
        self,
        exchange_id: str,
        api_key: str = "",
        api_secret: str = "",
        sandbox: bool = False,
        symbols: Optional[List[str]] = None,
        default_leverage: int = 1,
        market_type: str = "spot",
        options: Optional[Dict[str, Any]] = None,
    ):
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.symbols = symbols or []
        self.default_leverage = default_leverage
        self.market_type = market_type  # "spot" или "future"
        self.options = options or {}


class CryptoExchangeProvider(BaseMarketDataProvider):
    """
    Провайдер данных для криптовалютных бирж на базе ccxt.

    Поддерживает:
    - Получение OHLCV-данных
    - Тикеры и стаканы
    - Размещение/отмену ордеров
    - Управление позициями
    - Балансы и информацию о счёте
    """

    def __init__(self, config: CryptoExchangeConfig):
        self.config = config
        self._exchange: Optional[ccxt.Exchange] = None
        self._exchange_async: Optional[Any] = None  # ccxt.async_support
        self._initialized = False
        self._connected = False
        self._markets: Dict[str, Any] = {}
        self._ohlcv_cache: Dict[str, pd.DataFrame] = {}
        self._rate_limit_delay = 0.0  # Будет установлено из exchange.rateLimit

    def _create_exchange(self, use_async: bool = False) -> Any:
        """Создаёт экземпляр биржи ccxt."""
        exchange_class = getattr(ccxt_async if use_async else ccxt, self.config.exchange_id)

        exchange_config: Dict[str, Any] = {
            "enableRateLimit": True,
            "options": {
                "defaultType": self.config.market_type,
                **self.config.options,
            },
        }

        if self.config.api_key and self.config.api_secret:
            exchange_config["apiKey"] = self.config.api_key
            exchange_config["secret"] = self.config.api_secret

        exchange = exchange_class(exchange_config)

        if self.config.sandbox:
            exchange.set_sandbox_mode(True)

        return exchange

    # === ИНИЦИАЛИЗАЦИЯ ===

    async def initialize(self) -> bool:
        """Инициализация подключения к бирже."""
        try:
            logger.info(f"[CryptoExchange] Инициализация {self.config.exchange_id} ({self.config.market_type})...")

            # Синхронная биржа для основных операций
            self._exchange = self._create_exchange(use_async=False)

            # Загрузка рынков
            self._markets = self._exchange.load_markets()

            # Получение rate limit
            self._rate_limit_delay = getattr(self._exchange, "rateLimit", 0) / 1000.0

            # Установка leverage для фьючерсов
            if self.config.market_type == "future" and self.config.default_leverage > 1:
                if hasattr(self._exchange, "set_leverage"):
                    self._exchange.set_leverage(self.config.default_leverage)

            self._initialized = True
            self._connected = True

            logger.info(
                f"[CryptoExchange] {self.config.exchange_id} инициализирована. "
                f"Доступно рынков: {len(self._markets)}, Rate Limit: {self._rate_limit_delay:.3f}s"
            )
            return True

        except ccxt.AuthenticationError as e:
            logger.error(f"[CryptoExchange] Ошибка аутентификации {self.config.exchange_id}: {e}")
        except ccxt.NetworkError as e:
            logger.error(f"[CryptoExchange] Сетевая ошибка {self.config.exchange_id}: {e}")
        except ccxt.BaseError as e:
            logger.error(f"[CryptoExchange] Ошибка ccxt {self.config.exchange_id}: {e}")
        except Exception as e:
            logger.error(f"[CryptoExchange] Неожиданная ошибка инициализации: {e}", exc_info=True)

        self._connected = False
        return False

    async def shutdown(self) -> None:
        """Закрытие соединения с биржей."""
        if self._exchange_async:
            try:
                await self._exchange_async.close()
            except Exception:
                pass
            self._exchange_async = None

        self._connected = False
        self._initialized = False
        self._ohlcv_cache.clear()
        logger.info(f"[CryptoExchange] {self.config.exchange_id} отключена")

    async def is_connected(self) -> bool:
        """Проверка статуса соединения."""
        if not self._initialized or not self._connected:
            return False

        try:
            # Пробуем получить время с биржи
            if self._exchange:
                self._exchange.fetch_time()
                return True
        except Exception:
            self._connected = False

        return False

    # === РЫНОЧНЫЕ ДАННЫЕ ===

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        since: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Получение OHLCV-данных.

        Конвертирует символ из формата Genesis (BTCUSDT) в формат ccxt (BTC/USDT).
        """
        ccxt_symbol = self._normalize_symbol(symbol)
        ccxt_timeframe = REVERSE_TIMEFRAME_MAP.get(timeframe, timeframe)

        # Проверка кэша
        cache_key = f"{ccxt_symbol}_{ccxt_timeframe}_{limit}"
        if cache_key in self._ohlcv_cache:
            cached_df = self._ohlcv_cache[cache_key]
            if not cached_df.empty:
                logger.debug(f"[CryptoExchange] Кэш HIT для {symbol} {timeframe}")
                return cached_df.copy()

        try:
            since_ms = None
            if since:
                since_ms = int(since.timestamp() * 1000)

            ohlcv = self._exchange.fetch_ohlcv(
                ccxt_symbol,
                timeframe=ccxt_timeframe,
                since=since_ms,
                limit=limit,
            )

            if not ohlcv:
                logger.warning(f"[CryptoExchange] Нет данных OHLCV для {ccxt_symbol} {ccxt_timeframe}")
                return None

            # Конвертация в DataFrame (формат совместимый с MT5)
            df = pd.DataFrame(
                ohlcv,
                columns=["time", "open", "high", "low", "close", "volume"],
            )
            df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
            df.set_index("time", inplace=True)
            df["tick_volume"] = df["volume"]  # Для крипты volume = tick_volume
            df["symbol"] = ccxt_symbol

            # Преобразование в float32 для экономии RAM
            float64_cols = df.select_dtypes(include=["float64"]).columns
            if len(float64_cols) > 0:
                df[float64_cols] = df[float64_cols].astype("float32")

            # Кэширование
            self._ohlcv_cache[cache_key] = df

            logger.debug(f"[CryptoExchange] Получено {len(df)} баров для {ccxt_symbol} {ccxt_timeframe}")
            return df

        except ccxt.RateLimitExceeded:
            logger.warning(f"[CryptoExchange] Rate Limit для {ccxt_symbol}. Пауза...")
            time.sleep(self._rate_limit_delay * 2)
            return await self.get_ohlcv(symbol, timeframe, limit, since)
        except ccxt.ExchangeError as e:
            logger.error(f"[CryptoExchange] Ошибка биржи при получении OHLCV {ccxt_symbol}: {e}")
        except Exception as e:
            logger.error(f"[CryptoExchange] Неожиданная ошибка при получении OHLCV: {e}", exc_info=True)

        return None

    async def get_tick(self, symbol: str) -> Optional[Dict[str, float]]:
        """Получение текущего тика."""
        ccxt_symbol = self._normalize_symbol(symbol)

        try:
            ticker = self._exchange.fetch_ticker(ccxt_symbol)

            return {
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "last": ticker.get("last"),
                "volume": ticker.get("baseVolume", 0.0),
                "timestamp": (
                    datetime.fromtimestamp(ticker["timestamp"] / 1000, tz=timezone.utc)
                    if ticker.get("timestamp")
                    else datetime.now(timezone.utc)
                ),
            }

        except Exception as e:
            logger.error(f"[CryptoExchange] Ошибка получения тикера {ccxt_symbol}: {e}")
            return None

    async def get_symbols(self) -> List[str]:
        """Получение списка доступных символов."""
        if self.config.symbols:
            return self.config.symbols

        # Если нет белого списка, возвращаем все активные рынки
        if not self._markets:
            return []

        symbols = []
        for symbol, market in self._markets.items():
            if market.get("active", False) and not market.get("inactive", False):
                # Конвертируем из BTC/USDT в BTCUSDT
                genesis_symbol = symbol.replace("/", "").replace("-", "").replace("_", "")
                symbols.append(genesis_symbol)

        return symbols

    async def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Получение информации о символе."""
        ccxt_symbol = self._normalize_symbol(symbol)

        if ccxt_symbol not in self._markets:
            logger.warning(f"[CryptoExchange] Символ {ccxt_symbol} не найден в рынках")
            return None

        market = self._markets[ccxt_symbol]
        limits = market.get("limits", {})
        amount_limits = limits.get("amount", {})
        price_limits = limits.get("price", {})

        return {
            "symbol": ccxt_symbol,
            "point": market.get("precision", {}).get("price", 0.0),
            "digits": (
                len(str(market.get("precision", {}).get("price", 0)).split(".")[-1])
                if isinstance(market.get("precision", {}).get("price"), float)
                else 8
            ),
            "trade_mode": "full" if market.get("active") else "disabled",
            "volume_min": amount_limits.get("min", 0.0),
            "volume_max": amount_limits.get("max", float("inf")),
            "volume_step": amount_limits.get("step", 0.0),
            "price_min": price_limits.get("min", 0.0),
            "price_max": price_limits.get("max", float("inf")),
            "spread": 0.0,  # Будет обновлено динамически
            "swap_long": market.get("taker", 0.0),
            "swap_short": market.get("maker", 0.0),
            "contract_size": market.get("contractSize", 1.0),
            "leverage": market.get("limits", {}).get("leverage", {}).get("max", 1),
        }

    async def get_spread(self, symbol: str) -> float:
        """Получение текущего спреда."""
        tick = await self.get_tick(symbol)
        if tick and tick.get("bid") and tick.get("ask"):
            return tick["ask"] - tick["bid"]
        return 0.0

    # === ТОРГОВЛЯ ===

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
        """Размещение ордера."""
        ccxt_symbol = self._normalize_symbol(symbol)
        ccxt_side = "buy" if side == OrderSide.BUY else "sell"
        ccxt_order_type = self._map_order_type(order_type)

        try:
            params = {}
            if comment:
                params["comment"] = comment

            # Размещение ордера
            order = self._exchange.create_order(
                symbol=ccxt_symbol,
                type=ccxt_order_type,
                side=ccxt_side,
                amount=volume,
                price=price if order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) else None,
                params=params,
            )

            # Установка SL/TP для фьючерсов
            if stop_loss or take_profit:
                await self._set_sl_tp(ccxt_symbol, order["id"], stop_loss, take_profit, side)

            # Конвертация в унифицированный формат
            market_order = MarketOrder(
                symbol=symbol,
                side=side,
                order_type=order_type,
                volume=volume,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                order_id=order.get("id"),
                status=self._map_order_status(order.get("status")),
                fill_price=order.get("average") or order.get("price"),
                commission=order.get("fee", {}).get("cost", 0.0) if order.get("fee") else 0.0,
                timestamp=(
                    datetime.fromtimestamp(order["timestamp"] / 1000, tz=timezone.utc)
                    if order.get("timestamp")
                    else datetime.now(timezone.utc)
                ),
                raw_response=order,
            )

            logger.info(
                f"[CryptoExchange] Ордер размещен: {side.value} {volume} {ccxt_symbol} "
                f"@ {price or 'MARKET'}, ID: {market_order.order_id}"
            )
            return market_order

        except ccxt.InsufficientFunds:
            logger.error(f"[CryptoExchange] Недостаточно средств для ордера {ccxt_symbol}")
        except ccxt.InvalidOrder as e:
            logger.error(f"[CryptoExchange] Неверный ордер для {ccxt_symbol}: {e}")
        except Exception as e:
            logger.error(f"[CryptoExchange] Ошибка размещения ордера: {e}", exc_info=True)

        return None

    async def _set_sl_tp(
        self,
        symbol: str,
        position_id: str,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        side: OrderSide,
    ) -> None:
        """Установка SL/TP через отложенные ордера (для фьючерсов)."""
        if not (stop_loss or take_profit):
            return

        try:
            # Для Binance futures используем reduceOnly ордера
            params = {"reduceOnly": True, "closePosition": False}

            if stop_loss:
                sl_side = "sell" if side == OrderSide.BUY else "buy"
                self._exchange.create_order(
                    symbol=symbol,
                    type="STOP_MARKET",
                    side=sl_side,
                    amount=0,  # Закрыть всю позицию
                    stopLossPrice=stop_loss,
                    params={**params, "stopPrice": stop_loss},
                )
                logger.debug(f"[CryptoExchange] SL установлен: {stop_loss}")

            if take_profit:
                tp_side = "sell" if side == OrderSide.BUY else "buy"
                self._exchange.create_order(
                    symbol=symbol,
                    type="TAKE_PROFIT_MARKET",
                    side=tp_side,
                    amount=0,
                    takeProfitPrice=take_profit,
                    params={**params, "stopPrice": take_profit},
                )
                logger.debug(f"[CryptoExchange] TP установлен: {take_profit}")

        except Exception as e:
            logger.warning(f"[CryptoExchange] Не удалось установить SL/TP: {e}")

    async def cancel_order(self, order_id: str) -> bool:
        """Отмена отложенного ордера."""
        # Для отмены нужен символ — получаем из информации об ордере
        try:
            order = self._exchange.fetch_order(order_id)
            symbol = order.get("symbol")

            if symbol:
                self._exchange.cancel_order(order_id, symbol)
                logger.info(f"[CryptoExchange] Ордер отменен: {order_id}")
                return True
        except Exception as e:
            logger.error(f"[CryptoExchange] Ошибка отмены ордера {order_id}: {e}")

        return False

    async def close_position(self, symbol: str, volume: Optional[float] = None) -> bool:
        """Закрытие позиции."""
        try:
            ccxt_symbol = self._normalize_symbol(symbol)

            # Получаем текущую позицию
            positions = await self.get_positions()
            position = next((p for p in positions if p.symbol == symbol), None)

            if not position:
                logger.warning(f"[CryptoExchange] Нет открытой позиции по {symbol}")
                return False

            close_volume = volume or position.volume
            close_side = OrderSide.SELL if position.side == "BUY" else OrderSide.BUY

            order = await self.place_order(
                symbol=symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                volume=close_volume,
            )

            if order:
                logger.info(f"[CryptoExchange] Позиция закрыта: {symbol}, объем: {close_volume}")
                return True

        except Exception as e:
            logger.error(f"[CryptoExchange] Ошибка закрытия позиции {symbol}: {e}", exc_info=True)

        return False

    async def get_positions(self) -> List[Position]:
        """Получение списка открытых позиций."""
        try:
            positions_raw = self._exchange.fetch_positions()

            positions = []
            for pos in positions_raw:
                # Пропускаем закрытые позиции
                if pos.get("contracts", 0) <= 0:
                    continue

                symbol_raw = pos.get("symbol", "")
                side = pos.get("side", "long")
                contracts = pos.get("contracts", 0.0)
                entry_price = pos.get("entryPrice", 0.0)
                unrealized_pnl = pos.get("unrealizedPnl", 0.0)

                # Конвертируем символ
                genesis_symbol = symbol_raw.replace("/", "").replace("-", "").replace("_", "")

                positions.append(
                    Position(
                        symbol=genesis_symbol,
                        side=side.upper(),
                        volume=contracts,
                        entry_price=entry_price,
                        current_price=pos.get("markPrice"),
                        unrealized_pnl=unrealized_pnl or 0.0,
                        realized_pnl=pos.get("realizedPnl", 0.0) or 0.0,
                        commission=0.0,  # Будет рассчитано позже
                        swap=pos.get("funding", 0.0) or 0.0,
                        raw_response=pos,
                    )
                )

            return positions

        except Exception as e:
            logger.error(f"[CryptoExchange] Ошибка получения позиций: {e}")
            return []

    async def get_balance(self, currency: Optional[str] = None) -> Optional[Balance]:
        """Получение баланса счёта."""
        try:
            balance = self._exchange.fetch_balance()

            if currency:
                # Баланс конкретной валюты
                currency_balance = balance.get(currency.lower(), {})
                return Balance(
                    total=currency_balance.get("total", 0.0),
                    free=currency_balance.get("free", 0.0),
                    used=currency_balance.get("used", 0.0),
                    currency=currency.upper(),
                    raw_response=balance,
                )

            # Общий баланс в USDT (или базовой валюте)
            total_balance = balance.get("total", {})
            free_balance = balance.get("free", {})
            used_balance = balance.get("used", {})

            # Суммируем все валюты (упрощенно)
            total_usdt = total_balance.get("usdt", 0.0) or 0.0
            free_usdt = free_balance.get("usdt", 0.0) or 0.0
            used_usdt = used_balance.get("usdt", 0.0) or 0.0

            return Balance(
                total=total_usdt,
                free=free_usdt,
                used=used_usdt,
                currency="USDT",
                raw_response=balance,
            )

        except Exception as e:
            logger.error(f"[CryptoExchange] Ошибка получения баланса: {e}")
            return None

    # === ВСПОМОГАТЕЛЬНЫЕ ===

    async def get_minimum_lot_size(self, symbol: str) -> Optional[float]:
        """Получение минимального размера лота."""
        info = await self.get_symbol_info(symbol)
        if info:
            return info.get("volume_min")
        return None

    async def get_lot_step(self, symbol: str) -> Optional[float]:
        """Получение шага лота."""
        info = await self.get_symbol_info(symbol)
        if info:
            return info.get("volume_step")
        return None

    async def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Получение информации о счёте."""
        try:
            balance = await self.get_balance()
            if not balance:
                return None

            return {
                "login": self.config.exchange_id,
                "balance": balance.total,
                "equity": balance.total,
                "margin": balance.used,
                "free_margin": balance.free,
                "leverage": self.config.default_leverage,
                "currency": balance.currency,
                "name": f"{self.config.exchange_id} ({self.config.market_type})",
            }

        except Exception as e:
            logger.error(f"[CryptoExchange] Ошибка получения информации о счёте: {e}")
            return None

    async def get_conversion_rate(self, from_currency: str, to_currency: str) -> float:
        """Получение курса конвертации валют."""
        if from_currency == to_currency:
            return 1.0

        try:
            # Формируем пару
            pair = f"{from_currency}/{to_currency}"
            if pair not in self._markets:
                # Пробуем обратную пару
                reverse_pair = f"{to_currency}/{from_currency}"
                if reverse_pair in self._markets:
                    ticker = self._exchange.fetch_ticker(reverse_pair)
                    if ticker.get("last") and ticker["last"] > 0:
                        return 1.0 / ticker["last"]
                return 1.0

            ticker = self._exchange.fetch_ticker(pair)
            return ticker.get("last", 1.0)

        except Exception as e:
            logger.warning(f"[CryptoExchange] Ошибка получения курса {from_currency}/{to_currency}: {e}")
            return 1.0

    def get_provider_name(self) -> str:
        """Название провайдера."""
        return f"ccxt:{self.config.exchange_id}"

    def get_provider_type(self) -> str:
        """Тип провайдера."""
        return "CRYPTO"

    # === ВНУТРЕННИЕ МЕТОДЫ ===

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Конвертирует символ из формата Genesis (BTCUSDT) в формат ccxt (BTC/USDT).
        """
        # Если уже в ccxt-формате
        if "/" in symbol or "-" in symbol:
            return symbol

        # Пробуем найти пару в рынках
        ccxt_symbol = f"{symbol[:3]}/{symbol[3:]}"

        # Для USDT пар
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            ccxt_symbol = f"{base}/USDT"
        elif symbol.endswith("BUSD"):
            base = symbol[:-4]
            ccxt_symbol = f"{base}/BUSD"
        elif symbol.endswith("USDC"):
            base = symbol[:-4]
            ccxt_symbol = f"{base}/USDC"
        elif symbol.endswith("BTC"):
            base = symbol[:-3]
            ccxt_symbol = f"{base}/BTC"
        elif symbol.endswith("ETH"):
            base = symbol[:-3]
            ccxt_symbol = f"{base}/ETH"
        else:
            # Для сложных случаев (BTCUSD, EURUSD и т.д.)
            # Пробуем найти в markets
            for market_symbol in self._markets.keys():
                normalized = market_symbol.replace("/", "").replace("-", "").replace("_", "")
                if normalized == symbol:
                    return market_symbol

            # Если не нашли — оставляем как есть
            ccxt_symbol = symbol

        return ccxt_symbol

    def _map_order_type(self, order_type: OrderType) -> str:
        """Конвертация типа ордера в формат ccxt."""
        mapping = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP: "stop",
            OrderType.STOP_LIMIT: "stop",
        }
        return mapping.get(order_type, "market")

    def _map_order_status(self, status: Optional[str]) -> OrderStatus:
        """Конвертация статуса ордера."""
        if not status:
            return OrderStatus.PENDING

        mapping = {
            "open": OrderStatus.PENDING,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
            "rejected": OrderStatus.REJECTED,
        }
        return mapping.get(status, OrderStatus.PENDING)

    def clear_cache(self) -> None:
        """Очистка кэша OHLCV."""
        self._ohlcv_cache.clear()
        logger.debug("[CryptoExchange] Кэш очищен")
