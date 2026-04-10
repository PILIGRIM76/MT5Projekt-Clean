# -*- coding: utf-8 -*-
"""
src/data/unified_news_connector.py — Единый интерфейс для всех новостных источников

Источники:
- NewsAPI.org
- RSS-ленты (DailyFX, ForexLive, FXStreet, Reuters, Bloomberg)
- Finnhub
- MT5 встроенные новости

Нормализует все источники в единый формат NewsItem.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional
from urllib.parse import urlparse

import feedparser
import requests

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """
    Унифицированная новостная единица.

    Все коннекторы нормализуют данные в этот формат.
    """

    headline: str
    content: str
    source: str  # 'newsapi', 'rss', 'finnhub', 'mt5'
    source_name: str  # 'Reuters', 'Bloomberg', 'DailyFX', ...
    url: str
    timestamp: datetime
    symbols: List[str] = field(default_factory=list)  # ['EURUSD', 'BTC', ...]
    sentiment: float = 0.0  # [-1.0, 1.0]
    importance: float = 0.5  # [0.0, 1.0]
    category: str = "general"  # 'forex', 'crypto', 'macro', 'earnings', ...
    language: str = "en"
    raw_data: Optional[Dict] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.headline,
            "content": self.content[:500],  # Обрезаем для хранения
            "source": self.source,
            "source_name": self.source_name,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "symbols": self.symbols,
            "sentiment": self.sentiment,
            "importance": self.importance,
            "category": self.category,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "NewsItem":
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif ts is None:
            ts = datetime.now(timezone.utc)

        return cls(
            headline=data.get("headline", ""),
            content=data.get("content", ""),
            source=data.get("source", "unknown"),
            source_name=data.get("source_name", "Unknown"),
            url=data.get("url", ""),
            timestamp=ts,
            symbols=data.get("symbols", []),
            sentiment=data.get("sentiment", 0.0),
            importance=data.get("importance", 0.5),
            category=data.get("category", "general"),
            language=data.get("language", "en"),
        )


class UnifiedNewsConnector:
    """
    Единый интерфейс для получения новостей из всех источников.

    Поддерживает:
    - NewsAPI.org
    - RSS-ленты (настраиваемые)
    - Finnhub
    - MT5 новости
    - Асинхронный сбор из всех источников
    - Дедупликацию по заголовку
    - Базовый сентимент-анализ по ключевым словам
    """

    # Ключевые слова для сентимента
    _BULLISH_WORDS = [
        "rally",
        "surge",
        "jump",
        "gain",
        "rise",
        "higher",
        "bullish",
        "optimism",
        "growth",
        "profit",
        "beat",
        "upgrade",
        "breakout",
        "record",
        "strong",
        "recovery",
        "boost",
        "positive",
        "expansion",
        "stimulus",
    ]
    _BEARISH_WORDS = [
        "crash",
        "plunge",
        "drop",
        "fall",
        "decline",
        "lower",
        "bearish",
        "pessimism",
        "loss",
        "miss",
        "downgrade",
        "breakdown",
        "risk",
        "weak",
        "recession",
        "cut",
        "negative",
        "contraction",
        "tariff",
        "sanction",
        "crisis",
    ]

    def __init__(
        self,
        newsapi_key: Optional[str] = None,
        finnhub_key: Optional[str] = None,
        rss_feeds: Optional[List[Dict[str, str]]] = None,
        symbol_map: Optional[Dict[str, List[str]]] = None,
    ):
        self.newsapi_key = newsapi_key
        self.finnhub_key = finnhub_key

        # RSS ленты по умолчанию
        self.rss_feeds = rss_feeds or self._default_rss_feeds()

        # Карта символов для связывания новостей с инструментами
        self.symbol_map = symbol_map or self._default_symbol_map()

        # Кэш для дедупликации
        self._seen_headlines: Dict[str, float] = {}
        self._dedup_ttl = 3600  # 1 час

    def _default_rss_feeds(self) -> List[Dict[str, str]]:
        """RSS-ленты по умолчанию."""
        return [
            {"name": "Reuters Business", "url": "https://feeds.reuters.com/reuters/businessNews"},
            {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss"},
            {"name": "DailyFX", "url": "https://www.dailyfx.com/feeds/articles/"},
            {"name": "ForexLive", "url": "https://www.forexlive.com/rss/"},
            {"name": "FXStreet", "url": "https://www.fxstreet.com/rss"},
            {
                "name": "CNBC Top",
                "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
            },
            {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
        ]

    def _default_symbol_map(self) -> Dict[str, List[str]]:
        """Карта ключевых слов → торговые символы."""
        return {
            "EUR/USD": ["EURUSD"],
            "GBP/USD": ["GBPUSD"],
            "USD/JPY": ["USDJPY"],
            "Gold": ["XAUUSD"],
            "Bitcoin": ["BITCOIN", "BTCUSD"],
            "Ethereum": ["ETHUSD"],
            "Oil": ["USOIL", "BRENT"],
            "Fed": ["USDJPY", "EURUSD", "XAUUSD"],
            "ECB": ["EURUSD", "EURGBP", "EURJPY"],
            "S&P 500": ["US500", "SPX"],
            "Nasdaq": ["USTEC", "NDX"],
        }

    # ===================================================================
    # Основной API
    # ===================================================================

    def fetch_all(self, hours_back: int = 24, max_per_source: int = 50) -> List[NewsItem]:
        """
        Собирает новости из ВСЕХ источников.

        Args:
            hours_back: Глубина поиска
            max_per_source: Максимум новостей с одного источника

        Returns:
            Список NewsItem (дедуплицированный)
        """
        all_news = []

        # Параллельный сбор
        sources = [
            ("NewsAPI", lambda: self._fetch_newsapi(hours_back, max_per_source)),
            ("RSS", lambda: self._fetch_rss(max_per_source)),
            ("Finnhub", lambda: self._fetch_finnhub(hours_back, max_per_source)),
        ]

        for source_name, fetcher in sources:
            try:
                start = time.time()
                items = fetcher()
                elapsed = time.time() - start
                logger.info(f"[News-{source_name}] Получено {len(items)} новостей за {elapsed:.2f}s")
                all_news.extend(items)
            except Exception as e:
                logger.warning(f"[News-{source_name}] Ошибка: {e}")

        # Дедупликация и обогащение
        result = self._deduplicate_and_enrich(all_news)
        logger.info(f"[News-Unified] Итого: {len(result)} уникальных новостей из {len(all_news)}")
        return result

    def fetch_async(self, hours_back: int = 24, max_per_source: int = 50) -> Coroutine:
        """Асинхронная версия fetch_all."""
        return self._fetch_all_async(hours_back, max_per_source)

    # ===================================================================
    # Коннекторы
    # ===================================================================

    def _fetch_newsapi(self, hours_back: int, max_items: int) -> List[NewsItem]:
        """Получает новости через NewsAPI.org."""
        if not self.newsapi_key:
            return []

        url = "https://newsapi.org/v2/everything"
        from_ts = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%S")

        params = {
            "apiKey": self.newsapi_key,
            "language": "en",
            "sortBy": "publishedAt",
            "from": from_ts,
            "pageSize": min(max_items, 100),
            "q": "forex OR crypto OR trading OR market OR economy OR stocks",
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "ok":
                logger.warning(f"[NewsAPI] Error: {data.get('message', 'unknown')}")
                return []

            items = []
            for article in data.get("articles", []):
                ts_str = article.get("publishedAt")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)

                symbols = self._extract_symbols(article.get("title", "") + " " + (article.get("description") or ""))

                items.append(
                    NewsItem(
                        headline=article.get("title", ""),
                        content=article.get("description") or article.get("content", ""),
                        source="newsapi",
                        source_name=article.get("source", {}).get("name", "NewsAPI"),
                        url=article.get("url", ""),
                        timestamp=ts,
                        symbols=symbols,
                        sentiment=self._simple_sentiment(article.get("title", "")),
                        category=self._categorize(article.get("title", "")),
                        raw_data=article,
                    )
                )

            return items
        except Exception as e:
            logger.error(f"[NewsAPI] Request failed: {e}")
            return []

    def _fetch_rss(self, max_per_feed: int) -> List[NewsItem]:
        """Парсит RSS-ленты."""
        all_items = []

        for feed_info in self.rss_feeds:
            try:
                feed_url = feed_info["url"]
                feed_name = feed_info["name"]

                resp = requests.get(feed_url, timeout=10, headers={"User-Agent": "Mozilla/5.0 Genesis/TradingSystem"})
                resp.raise_for_status()

                parsed = feedparser.parse(resp.text)

                for entry in parsed.entries[:max_per_feed]:
                    ts = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                        ts = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                    if ts is None:
                        ts = datetime.now(timezone.utc)

                    title = entry.get("title", "")
                    summary = entry.get("summary", "")

                    # Извлекаем ссылку
                    link = entry.get("link", "")
                    if not link and entry.get("links"):
                        link = entry.links[0].get("href", "")

                    symbols = self._extract_symbols(title + " " + summary)

                    all_items.append(
                        NewsItem(
                            headline=title,
                            content=summary[:500],
                            source="rss",
                            source_name=feed_name,
                            url=link,
                            timestamp=ts,
                            symbols=symbols,
                            sentiment=self._simple_sentiment(title),
                            category=self._categorize(title),
                            raw_data=dict(entry),
                        )
                    )

            except Exception as e:
                logger.debug(f"[RSS-{feed_info.get('name', '?')}] Ошибка: {e}")

        return all_items

    def _fetch_finnhub(self, hours_back: int, max_items: int) -> List[NewsItem]:
        """Получает новости через Finnhub."""
        if not self.finnhub_key:
            return []

        url = "https://finnhub.io/api/v1/news"
        from_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())
        to_ts = int(datetime.now(timezone.utc).timestamp())

        params = {
            "token": self.finnhub_key,
            "category": "general",
            "from": from_ts,
            "to": to_ts,
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            items = []
            for article in data[:max_items]:
                ts = datetime.fromtimestamp(article.get("datetime", 0), tz=timezone.utc)

                symbols = self._extract_symbols(article.get("headline", "") + " " + (article.get("summary") or ""))

                items.append(
                    NewsItem(
                        headline=article.get("headline", ""),
                        content=article.get("summary", "")[:500],
                        source="finnhub",
                        source_name=article.get("source", "Finnhub"),
                        url=article.get("url", ""),
                        timestamp=ts,
                        symbols=symbols,
                        sentiment=self._simple_sentiment(article.get("headline", "")),
                        category=article.get("category", "general"),
                        raw_data=article,
                    )
                )

            return items
        except Exception as e:
            logger.error(f"[Finnhub] Request failed: {e}")
            return []

    async def _fetch_all_async(self, hours_back: int, max_per_source: int) -> List[NewsItem]:
        """Асинхронный сбор из всех источников."""
        loop = asyncio.get_event_loop()

        tasks = [
            loop.run_in_executor(None, lambda: self._fetch_newsapi(hours_back, max_per_source)),
            loop.run_in_executor(None, lambda: self._fetch_rss(max_per_source)),
            loop.run_in_executor(None, lambda: self._fetch_finnhub(hours_back, max_per_source)),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_news = []
        for result in results:
            if isinstance(result, list):
                all_news.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"[News-Async] Ошибка источника: {result}")

        return self._deduplicate_and_enrich(all_news)

    # ===================================================================
    # Обогащение
    # ===================================================================

    def _deduplicate_and_enrich(self, items: List[NewsItem]) -> List[NewsItem]:
        """Дедупликация + очистка старых записей + сортировка."""
        now = time.time()

        # Очистка старых записей из кэша
        expired = [k for k, v in self._seen_headlines.items() if now - v > self._dedup_ttl]
        for k in expired:
            del self._seen_headlines[k]

        unique = []
        seen_now = set()

        for item in items:
            key = self._normalize_headline(item.headline)
            if key and key not in seen_now and key not in self._seen_headlines:
                seen_now.add(key)
                self._seen_headlines[key] = now
                unique.append(item)

        # Сортировка по времени (новые первыми)
        unique.sort(key=lambda x: x.timestamp, reverse=True)
        return unique

    def _extract_symbols(self, text: str) -> List[str]:
        """Извлекает торговые символы из текста."""
        if not text:
            return []

        text_upper = text.upper()
        found = set()

        for keyword, symbols in self.symbol_map.items():
            if keyword.upper() in text_upper:
                found.update(symbols)

        # Прямые символы
        direct = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BITCOIN", "BTC", "ETH"]
        for sym in direct:
            if sym in text_upper:
                found.add(sym)

        return sorted(found)

    def _simple_sentiment(self, text: str) -> float:
        """Базовый сентимент по ключевым словам."""
        if not text:
            return 0.0

        words = re.findall(r"\b\w+\b", text.lower())
        if not words:
            return 0.0

        bullish = sum(1 for w in words if w in self._BULLISH_WORDS)
        bearish = sum(1 for w in words if w in self._BEARISH_WORDS)
        total = bullish + bearish

        if total == 0:
            return 0.0

        return (bullish - bearish) / total

    def _categorize(self, text: str) -> str:
        """Определяет категорию новости."""
        text_lower = text.lower()

        if any(w in text_lower for w in ["bitcoin", "crypto", "btc", "eth", "blockchain"]):
            return "crypto"
        if any(w in text_lower for w in ["forex", "eur", "gbp", "jpy", "usd", "pip"]):
            return "forex"
        if any(w in text_lower for w in ["fed", "ecb", "rate", "inflation", "gdp", "cpi"]):
            return "macro"
        if any(w in text_lower for w in ["earnings", "revenue", "profit", "eps", "quarter"]):
            return "earnings"
        if any(w in text_lower for w in ["stock", "sp500", "s&p", "nasdaq", "dow"]):
            return "stocks"

        return "general"

    @staticmethod
    def _normalize_headline(headline: str) -> str:
        """Нормализует заголовок для дедупликации."""
        if not headline:
            return ""
        # Убираем спецсимволы, приводим к нижнему регистру
        h = headline.lower().strip()
        h = re.sub(r"[^a-z0-9\s]", "", h)
        h = re.sub(r"\s+", " ", h)
        return h[:100]  # Первые 100 символов

    def get_stats(self) -> Dict[str, Any]:
        """Статистика коннектора."""
        return {
            "cached_headlines": len(self._seen_headlines),
            "rss_feeds": len(self.rss_feeds),
            "newsapi_enabled": bool(self.newsapi_key),
            "finnhub_enabled": bool(self.finnhub_key),
            "symbol_map_size": len(self.symbol_map),
        }
