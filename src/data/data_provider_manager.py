"""
DataProviderManager — менеджер множественных провайдеров данных.

Управляет MT5, крипто-биржами и другими источниками данных.
Автоматически определяет тип символа и маршрутизирует запросы к нужному провайдеру.
"""

import asyncio
import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.core.config_models import Settings
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


class DataProviderManager:
    """
    Центральный менеджер для работы с несколькими провайдерами данных.

    Поддерживает:
    - MT5 (Forex, акции, фьючерсы)
    - Крипто-биржи (Binance, Bybit, OKX и др. через ccxt)
    - Автоматическое определение типа символа
    - Маршрутизация запросов
    """

    def __init__(self, config: Settings, mt5_lock: threading.Lock):
        self.config = config
        self.mt5_lock = mt5_lock

        # Провайдеры
        self._mt5_provider: Optional[Any] = None  # DataProvider
        self._crypto_providers: Dict[str, Any] = {}  # exchange_id -> CryptoExchangeProvider
        self._default_provider: str = "mt5"  # По умолчанию MT5

        # Кэш типов символов
        self._symbol_type_cache: Dict[str, str] = {}

        # Маппинг символов к провайдерам
        self._symbol_provider_map: Dict[str, str] = {}

    async def initialize(self) -> bool:
        """Инициализация всех провайдеров."""
        logger.info("[DataProviderManager] Инициализация провайдеров данных...")

        # Инициализация крипто-бирж
        if self.config.crypto_exchanges.enabled:
            await self._initialize_crypto_providers()

        logger.info(f"[DataProviderManager] Инициализация завершена. " f"Крипто-бирж: {len(self._crypto_providers)}")
        return True

    async def _initialize_crypto_providers(self) -> None:
        """Инициализация настроенных крипто-бирж."""
        from src.data.crypto_exchange_provider import (
            CryptoExchangeConfig,
            CryptoExchangeProvider,
        )

        for exchange_id, exchange_config in self.config.crypto_exchanges.exchanges.items():
            if not exchange_config.enabled:
                logger.info(f"[DataProviderManager] Биржа {exchange_id} отключена, пропускаем")
                continue

            try:
                logger.info(f"[DataProviderManager] Инициализация биржи {exchange_id}...")

                # Получаем API ключи из переменных окружения
                api_key = os.getenv(exchange_config.api_key_env, "")
                api_secret = os.getenv(exchange_config.api_secret_env, "")

                if not api_key or not api_secret:
                    logger.warning(
                        f"[DataProviderManager] API ключи для {exchange_id} не найдены "
                        f"({exchange_config.api_key_env}, {exchange_config.api_secret_env})"
                    )
                    continue

                # Создаём конфигурацию провайдера
                crypto_config = CryptoExchangeConfig(
                    exchange_id=exchange_id,
                    api_key=api_key,
                    api_secret=api_secret,
                    sandbox=exchange_config.sandbox,
                    symbols=exchange_config.symbols,
                    default_leverage=exchange_config.default_leverage,
                    market_type=exchange_config.market_type,
                )

                # Создаём и инициализируем провайдер
                provider = CryptoExchangeProvider(crypto_config)
                success = await provider.initialize()

                if success:
                    self._crypto_providers[exchange_id] = provider

                    # Регистрируем символы
                    symbols = await provider.get_symbols()
                    for symbol in symbols:
                        self._symbol_provider_map[symbol] = exchange_id

                    logger.info(f"[DataProviderManager] Биржа {exchange_id} инициализирована. " f"Символов: {len(symbols)}")
                else:
                    logger.warning(f"[DataProviderManager] Не удалось инициализировать {exchange_id}")

            except Exception as e:
                logger.error(f"[DataProviderManager] Ошибка инициализации {exchange_id}: {e}", exc_info=True)

    def set_mt5_provider(self, mt5_provider: Any) -> None:
        """Устанавливает MT5 DataProvider."""
        self._mt5_provider = mt5_provider
        logger.info("[DataProviderManager] MT5 DataProvider установлен")

    def get_provider_for_symbol(self, symbol: str) -> str:
        """
        Определяет провайдера для символа.

        Returns:
            'mt5' или exchange_id (напр. 'binance')
        """
        # Проверяем кэш
        if symbol in self._symbol_type_cache:
            return self._symbol_type_cache[symbol]

        # Проверяем маппинг крипто-символов
        if symbol in self._symbol_provider_map:
            provider_id = self._symbol_provider_map[symbol]
            self._symbol_type_cache[symbol] = provider_id
            return provider_id

        # Проверяем по паттернам
        if self._is_crypto_symbol(symbol):
            # Ищем подходя биржу
            for exchange_id, provider in self._crypto_providers.items():
                # Проверяем есть ли такой символ у провайдера
                if hasattr(provider, "_markets") and provider._markets:
                    normalized = symbol
                    if "/" not in symbol:
                        # Пробуем найти в рынках
                        for market_symbol in provider._markets.keys():
                            market_normalized = market_symbol.replace("/", "").replace("-", "").replace("_", "")
                            if market_normalized == symbol:
                                self._symbol_provider_map[symbol] = exchange_id
                                self._symbol_type_cache[symbol] = exchange_id
                                return exchange_id

        # По умолчанию MT5
        self._symbol_type_cache[symbol] = "mt5"
        return "mt5"

    def _is_crypto_symbol(self, symbol: str) -> bool:
        """
        Проверяет, является ли символ криптовалютным.

        Крипто-символы обычно содержат USDT, BTC, ETH, BUSD и т.д.
        """
        crypto_suffixes = ["USDT", "BTC", "ETH", "BUSD", "USDC", "BNB", "SOL", "XRP"]
        crypto_prefixes = ["BTC", "ETH"]  # Для пар типа BTCUSD

        upper_symbol = symbol.upper()

        for suffix in crypto_suffixes:
            if upper_symbol.endswith(suffix):
                return True

        for prefix in crypto_prefixes:
            if upper_symbol.startswith(prefix):
                return True

        return False

    def is_crypto_symbol(self, symbol: str) -> bool:
        """Публичный метод проверки крипто-символа."""
        return self._is_crypto_symbol(symbol)

    def get_crypto_provider(self, symbol: str) -> Optional[Any]:
        """Получает крипто-провайдер для символа."""
        provider_id = self.get_provider_for_symbol(symbol)
        if provider_id == "mt5":
            return None
        return self._crypto_providers.get(provider_id)

    # === МАРШРУТИЗАЦИЯ ЗАПРОСОВ ===

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        since: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """Получение OHLCV данных через соответствующий провайдер."""
        provider_id = self.get_provider_for_symbol(symbol)

        if provider_id == "mt5":
            if self._mt5_provider:
                # MT5 использует синхронный метод
                import asyncio

                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    lambda: self._mt5_provider.get_historical_data(
                        symbol,
                        timeframe,
                        since or (datetime.utcnow() - pd.Timedelta(minutes=limit * TimeFrame.to_minutes(timeframe))),
                        datetime.utcnow(),
                    ),
                )
            return None
        else:
            provider = self._crypto_providers.get(provider_id)
            if provider:
                return await provider.get_ohlcv(symbol, timeframe, limit, since)
            return None

    async def get_tick(self, symbol: str) -> Optional[Dict[str, float]]:
        """Получение тика."""
        provider_id = self.get_provider_for_symbol(symbol)

        if provider_id == "mt5":
            if self._mt5_provider:
                import asyncio

                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: self._mt5_provider.get_tick(symbol))
            return None
        else:
            provider = self._crypto_providers.get(provider_id)
            if provider:
                return await provider.get_tick(symbol)
            return None

    async def get_symbols(self) -> List[str]:
        """Получение всех доступных символов."""
        symbols = []

        # MT5 символы
        if self._mt5_provider:
            mt5_symbols = self._mt5_provider.get_available_symbols()
            symbols.extend(mt5_symbols)

        # Крипто символы
        for exchange_id, provider in self._crypto_providers.items():
            crypto_symbols = await provider.get_symbols()
            symbols.extend(crypto_symbols)

        return symbols

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
        """Размещение ордера через соответствующий провайдер."""
        provider_id = self.get_provider_for_symbol(symbol)

        if provider_id == "mt5":
            if self._mt5_provider:
                import asyncio

                loop = asyncio.get_event_loop()

                def _place_order():
                    return self._mt5_provider.place_order(
                        symbol, side, order_type, volume, price, stop_loss, take_profit, comment
                    )

                return await loop.run_in_executor(None, _place_order)
            return None
        else:
            provider = self._crypto_providers.get(provider_id)
            if provider:
                return await provider.place_order(symbol, side, order_type, volume, price, stop_loss, take_profit, comment)
            return None

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Получение позиций."""
        all_positions = []

        # MT5 позиции
        if self._mt5_provider:
            import asyncio

            loop = asyncio.get_event_loop()
            mt5_positions = await loop.run_in_executor(None, lambda: self._mt5_provider.get_positions())
            all_positions.extend(mt5_positions)

        # Крипто позиции
        for exchange_id, provider in self._crypto_providers.items():
            crypto_positions = await provider.get_positions()
            if symbol:
                crypto_positions = [p for p in crypto_positions if p.symbol == symbol]
            all_positions.extend(crypto_positions)

        return all_positions

    async def get_balance(self, currency: Optional[str] = None) -> Optional[Balance]:
        """Получение баланса."""
        # Для MT5 используем основной провайдер
        if self._mt5_provider:
            import asyncio

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._mt5_provider.get_balance(currency))

        # Для крипто — суммируем балансы
        total_balance = {"total": 0.0, "free": 0.0, "used": 0.0}

        for exchange_id, provider in self._crypto_providers.items():
            balance = await provider.get_balance(currency)
            if balance:
                total_balance["total"] += balance.total
                total_balance["free"] += balance.free
                total_balance["used"] += balance.used

        if total_balance["total"] > 0:
            return Balance(
                total=total_balance["total"],
                free=total_balance["free"],
                used=total_balance["used"],
                currency=currency or "USDT",
            )

        return None

    async def get_minimum_lot_size(self, symbol: str) -> Optional[float]:
        """Получение минимального лота."""
        provider_id = self.get_provider_for_symbol(symbol)

        if provider_id == "mt5":
            if self._mt5_provider:
                import asyncio

                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: self._mt5_provider.get_minimum_lot_size(symbol))
            return None
        else:
            provider = self._crypto_providers.get(provider_id)
            if provider:
                return await provider.get_minimum_lot_size(symbol)
            return None

    async def get_spread(self, symbol: str) -> float:
        """Получение спреда."""
        provider_id = self.get_provider_for_symbol(symbol)

        if provider_id == "mt5":
            if self._mt5_provider:
                import asyncio

                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: self._mt5_provider.get_spread(symbol))
            return 0.0
        else:
            provider = self._crypto_providers.get(provider_id)
            if provider:
                return await provider.get_spread(symbol)
            return 0.0

    async def get_conversion_rate(self, from_currency: str, to_currency: str) -> float:
        """Получение курса конвертации."""
        # Проверяем крипто-провайдеры
        for exchange_id, provider in self._crypto_providers.items():
            rate = await provider.get_conversion_rate(from_currency, to_currency)
            if rate != 1.0:
                return rate

        # Если не нашли — используем MT5
        if self._mt5_provider:
            import asyncio

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._mt5_provider.get_conversion_rate(from_currency, to_currency))

        return 1.0

    # === УПРАВЛЕНИЕ ===

    def get_available_exchanges(self) -> List[str]:
        """Получение списка доступных бирж."""
        return list(self._crypto_providers.keys())

    def get_provider_status(self) -> Dict[str, Any]:
        """Получение статуса всех провайдеров."""
        status = {
            "mt5": {
                "connected": self._mt5_provider is not None,
                "type": "MT5",
            },
        }

        for exchange_id, provider in self._crypto_providers.items():
            status[exchange_id] = {
                "connected": True,  # Если в словаре — подключен
                "type": "CRYPTO",
                "markets": len(provider._markets) if hasattr(provider, "_markets") else 0,
            }

        return status

    async def shutdown(self) -> None:
        """Отключение всех провайдеров."""
        logger.info("[DataProviderManager] Отключение провайдеров...")

        for exchange_id, provider in self._crypto_providers.items():
            try:
                await provider.shutdown()
                logger.info(f"[DataProviderManager] {exchange_id} отключена")
            except Exception as e:
                logger.error(f"[DataProviderManager] Ошибка отключения {exchange_id}: {e}")

        self._crypto_providers.clear()
        self._symbol_provider_map.clear()
        self._symbol_type_cache.clear()

        logger.info("[DataProviderManager] Все провайдеры отключены")
