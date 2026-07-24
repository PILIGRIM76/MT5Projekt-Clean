# -*- coding: utf-8 -*-
"""
src/data/binance_data_stream.py — Real-time поток данных Binance

Поддерживает:
- WebSocket stream для klines (свечи), trades, tickers
- REST API для исторических данных
- Open Interest, Funding Rate
- Интеграция с Knowledge Graph
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class BinanceDataStream:
    """
    Поток данных Binance для real-time крипто-рынка.

    Источники:
    - WebSocket: wss://stream.binance.com:9443/ws
    - REST: https://api.binance.com/api/v3

    Поддерживаемые stream'ы:
    - kline_<symbol>_<interval> — свечи
    - trade_<symbol> — сделки
    - ticker_<symbol> — тикеры 24h
    - !bookTicker — лучшие bid/ask
    """

    # Маппинг интервалов
    INTERVAL_MAP = {
        "1m": "1m",
        "3m": "3m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "2h": "2h",
        "4h": "4h",
        "6h": "6h",
        "8h": "8h",
        "12h": "12h",
        "1d": "1d",
        "3d": "3d",
        "1w": "1w",
        "1M": "1M",
    }

    def __init__(self, testnet: bool = False):
        self.testnet = testnet

        if testnet:
            self.rest_url = "https://testnet.binance.vision/api/v3"
            self.ws_url = "wss://testnet.binance.vision/ws"
        else:
            self.rest_url = "https://api.binance.com/api/v3"
            self.ws_url = "wss://stream.binance.com:9443/ws"

        self._callbacks: Dict[str, List[Callable]] = {}
        self._ws_client = None

    # ===================================================================
    # REST API
    # ===================================================================

    def get_ohlcv(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        start_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Получает OHLCV данные через REST API.

        Args:
            symbol: BTCUSDT, ETHUSDT, ...
            interval: 1m, 5m, 15m, 1h, 4h, 1d, ...
            limit: Максимум 1000
            start_time: Unix timestamp ms (опционально)

        Returns:
            Список свечей [{time, open, high, low, close, volume, ...}]
        """
        url = f"{self.rest_url}/klines"
        params = {
            "symbol": symbol.upper(),
            "interval": self.INTERVAL_MAP.get(interval, interval),
            "limit": min(limit, 1000),
        }
        if start_time:
            params["startTime"] = start_time

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            candles = []
            for k in data:
                candles.append(
                    {
                        "timestamp": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc),
                        "quote_volume": float(k[7]),
                        "trades": k[8],
                        "taker_buy_base": float(k[9]),
                        "taker_buy_quote": float(k[10]),
                    }
                )

            logger.info(f"[Binance-REST] {symbol} {interval}: {len(candles)} свечей")
            return candles

        except Exception as e:
            logger.error(f"[Binance-REST] Ошибка: {e}")
            return []

    def get_ticker_24h(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получает 24h тикер.

        Args:
            symbol: Если None — все символы

        Returns:
            Список тикеров
        """
        url = f"{self.rest_url}/ticker/24hr"
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict):
                data = [data]

            tickers = []
            for t in data:
                tickers.append(
                    {
                        "symbol": t.get("symbol", ""),
                        "price_change": float(t.get("priceChange", 0)),
                        "price_change_pct": float(t.get("priceChangePercent", 0)),
                        "volume": float(t.get("volume", 0)),
                        "quote_volume": float(t.get("quoteVolume", 0)),
                        "last_price": float(t.get("lastPrice", 0)),
                        "high": float(t.get("highPrice", 0)),
                        "low": float(t.get("lowPrice", 0)),
                        "trades": t.get("count", 0),
                        "timestamp": datetime.now(timezone.utc),
                    }
                )

            return tickers

        except Exception as e:
            logger.error(f"[Binance-REST] Ticker error: {e}")
            return []

    def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получает Open Interest для фьючерсов.

        Args:
            symbol: BTCUSDT

        Returns:
            {symbol, open_interest, timestamp}
        """
        url = "https://fapi.binance.com/fapi/v1/openInterest"
        params = {"symbol": symbol.upper()}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            return {
                "symbol": data.get("symbol", symbol),
                "open_interest": float(data.get("openInterest", 0)),
                "timestamp": datetime.fromtimestamp(data.get("time", 0) / 1000, tz=timezone.utc),
            }
        except Exception as e:
            logger.error(f"[Binance-OI] Ошибка: {e}")
            return None

    def get_funding_rate(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получает исторические Funding Rate.

        Args:
            symbol: BTCUSDT
            limit: До 1000

        Returns:
            Список [{symbol, funding_rate, timestamp}]
        """
        url = "https://fapi.binance.com/fapi/v1/fundingRate"
        params = {"symbol": symbol.upper(), "limit": min(limit, 1000)}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            return [
                {
                    "symbol": item.get("symbol", symbol),
                    "funding_rate": float(item.get("fundingRate", 0)),
                    "timestamp": datetime.fromtimestamp(item.get("fundingTime", 0) / 1000, tz=timezone.utc),
                }
                for item in data
            ]
        except Exception as e:
            logger.error(f"[Binance-FR] Ошибка: {e}")
            return []

    def get_server_time(self) -> Optional[datetime]:
        """Проверяет соединение и получает время сервера."""
        try:
            resp = requests.get(f"{self.rest_url}/time", timeout=5)
            resp.raise_for_status()
            ts = resp.json().get("serverTime", 0)
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        except Exception as e:
            logger.error(f"[Binance-Time] Ошибка: {e}")
            return None

    # ===================================================================
    # WebSocket Stream
    # ===================================================================

    def build_ws_url(self, streams: List[str]) -> str:
        """
        Строит URL для WebSocket подключения.

        Args:
            streams: ['btcusdt@kline_1h', 'ethusdt@ticker', ...]

        Returns:
            Полный URL
        """
        if len(streams) == 1:
            return f"{self.ws_url}/{streams[0]}"
        else:
            return f"{self.ws_url}/?streams={'/'.join(streams)}"

    def subscribe(
        self,
        stream_type: str,  # 'kline', 'trade', 'ticker'
        symbols: List[str],
        interval: str = "1h",
        callback: Optional[Callable] = None,
    ) -> List[str]:
        """
        Подписывается на stream'и.

        Returns:
            Список stream имён для WebSocket URL
        """
        streams = []
        for sym in symbols:
            sym_lower = sym.lower()
            if stream_type == "kline":
                name = f"{sym_lower}@kline_{interval}"
            elif stream_type == "trade":
                name = f"{sym_lower}@trade"
            elif stream_type == "ticker":
                name = f"{sym_lower}@ticker"
            else:
                continue

            streams.append(name)
            if callback:
                self._callbacks.setdefault(name, []).append(callback)

        logger.info(f"[Binance-WS] Подписка: {streams}")
        return streams

    def parse_ws_message(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Парсит WebSocket сообщение в унифицированный формат.

        Args:
            message: JSON строка от Binance

        Returns:
            Словарь с данными или None
        """
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return None

        # Kline
        if "k" in data:
            k = data["k"]
            return {
                "type": "kline",
                "symbol": data.get("s", ""),
                "timestamp": datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc),
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "is_closed": k.get("x", False),
                "raw": data,
            }

        # Trade
        if "p" in data and "q" in data and "k" not in data:
            return {
                "type": "trade",
                "symbol": data.get("s", ""),
                "price": float(data["p"]),
                "quantity": float(data["q"]),
                "timestamp": datetime.fromtimestamp(data.get("T", 0) / 1000, tz=timezone.utc),
                "raw": data,
            }

        # Ticker
        if "c" in data and "h" in data and "v" in data:
            return {
                "type": "ticker",
                "symbol": data.get("s", ""),
                "price": float(data["c"]),
                "high": float(data.get("h", 0)),
                "low": float(data.get("l", 0)),
                "volume": float(data.get("v", 0)),
                "price_change_pct": float(data.get("P", 0)),
                "timestamp": datetime.now(timezone.utc),
                "raw": data,
            }

        return None

    # ===================================================================
    # Утилиты
    # ===================================================================

    def get_exchange_info(self, symbol: Optional[str] = None) -> Optional[Dict]:
        """Получает информацию о символах (лоты, тикеры, фильтры)."""
        url = f"{self.rest_url}/exchangeInfo"
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[Binance-Info] Ошибка: {e}")
            return None

    def get_depth(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Получает книгу ордеров."""
        url = f"{self.rest_url}/depth"
        params = {"symbol": symbol.upper(), "limit": min(limit, 1000)}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return {
                "symbol": symbol,
                "bids": [(float(p), float(q)) for p, q in data.get("bids", [])[:limit]],
                "asks": [(float(p), float(q)) for p, q in data.get("asks", [])[:limit]],
                "timestamp": datetime.fromtimestamp(data.get("lastUpdateId", 0) / 1000, tz=timezone.utc),
            }
        except Exception as e:
            logger.error(f"[Binance-Depth] Ошибка: {e}")
            return None

    def __repr__(self) -> str:
        mode = "testnet" if self.testnet else "mainnet"
        return f"BinanceDataStream(mode={mode})"
