# src/core/services/news_service.py
"""
NewsCollectorService — Сервис сбора и анализа новостей.

Публикует события news_batch_processed в EventBus.
Использует VADER для сентимент-анализа.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.core.config_models import Settings
from src.core.event_bus import AsyncEventBus, EventPriority, SystemEvent, get_event_bus
from src.core.services.base_service import BaseService, HealthStatus
from src.core.thread_domains import ThreadDomain

logger = logging.getLogger(__name__)


class NewsCollectorService(BaseService):
    """
    Сервис сбора новостей с публикацией в EventBus.

    Наследует BaseService и интегрируется с EventBus.
    """

    def __init__(self, config: Settings, db_manager=None, vector_db_manager=None):
        super().__init__(config, name="NewsCollectorService")
        self.db_manager = db_manager
        self.vector_db_manager = vector_db_manager

        # Конфигурация
        self.news_api_key = getattr(config, "NEWS_API_KEY", None) or getattr(config, "news_api_key", None)
        self.rss_feeds = getattr(config, "rss_feeds", []) or getattr(config, "NEWS_RSS_FEEDS", [])
        self.max_articles = getattr(config, "max_news_per_load", 20) or 20
        self.poll_interval = getattr(config, "news_poll_interval_minutes", 15) or 15

        # Инициализируем VADER
        self._init_sentiment_analyzer()

        # EventBus
        self.event_bus = get_event_bus()

        # Embedding модель (lazy load)
        self._embedding_model = None

        # Состояние
        self._collection_task: Optional[asyncio.Task] = None
        self._last_sentiment: float = 0.0
        self._articles_collected: int = 0
        self._vectors_stored: int = 0

        logger.info(
            f"NewsCollectorService: API key={'есть' if self.news_api_key else 'нет'}, RSS={len(self.rss_feeds)} лент, VectorDB={'да' if vector_db_manager else 'нет'}"
        )

    def _init_sentiment_analyzer(self):
        """Инициализация VADER анализатора."""
        try:
            from nltk.sentiment.vader import SentimentIntensityAnalyzer

            self.analyzer = SentimentIntensityAnalyzer()
            logger.info("VADER sentiment analyzer инициализирован")
        except Exception as e:
            logger.warning(f"Не удалось инициализировать VADER: {e}. Используется fallback.")
            self.analyzer = None

    def _load_embedding_model(self):
        """Lazy load SentenceTransformer для эмбеддингов."""
        if self._embedding_model is not None:
            return True

        if not self.vector_db_manager or not self.vector_db_manager.is_ready():
            return False

        try:
            from sentence_transformers import SentenceTransformer

            model_name = getattr(self.config, "vector_db", None)
            model_name = getattr(model_name, "embedding_model", "all-MiniLM-L6-v2") if model_name else "all-MiniLM-L6-v2"
            self._embedding_model = SentenceTransformer(model_name)
            logger.info(f"Embedding модель загружена: {model_name}")
            return True
        except Exception as e:
            logger.warning(f"Не удалось загрузить embedding модель: {e}")
            return False

    async def start(self) -> None:
        """Запуск сервиса."""
        if self._running:
            return

        self._running = True
        self._healthy = True

        # Подписываемся на запросы ручного сбора из GUI
        await self.event_bus.subscribe(
            "news_collection_requested",
            self._on_collection_requested,
            domain=ThreadDomain.STRATEGY_ENGINE,
            priority=EventPriority.CRITICAL,
        )

        # Запускаем периодический сбор
        self._collection_task = asyncio.create_task(self._run_periodic_collection())

        logger.info(f"NewsCollectorService запущен (интервал: {self.poll_interval} мин)")

    async def stop(self) -> None:
        """Остановка сервиса."""
        self._running = False

        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass

        logger.info("NewsCollectorService остановлен")

    def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса."""
        if not self._running:
            return HealthStatus(False, "Service not running")._asdict()

        if not self._healthy:
            return HealthStatus(False, "Service in degraded state")._asdict()

        return HealthStatus(
            True,
            "Service healthy",
            {
                "articles_collected": self._articles_collected,
                "last_sentiment": self._last_sentiment,
                "poll_interval_minutes": self.poll_interval,
            },
        )._asdict()

    async def _on_collection_requested(self, event: SystemEvent) -> None:
        """Обработка запроса на ручной сбор новостей из GUI."""
        source = event.payload.get("source", "unknown")
        logger.info(f"[NewsCollector] Получен запрос на сбор от: {source}")
        await self._collect_and_publish()

    async def _run_periodic_collection(self) -> None:
        """Периодический сбор новостей."""
        logger.info("Начало периодического сбора новостей")

        try:
            while self._running:
                await self._collect_and_publish()
                await asyncio.sleep(self.poll_interval * 60)
        except asyncio.CancelledError:
            logger.info("Periodic news collection cancelled")
        except Exception as e:
            logger.error(f"Error in periodic collection: {e}", exc_info=True)
            self._healthy = False

    async def _collect_and_publish(self) -> None:
        """Сбор новостей и публикация в EventBus."""
        articles = []

        # Сбор из NewsAPI
        if self.news_api_key:
            try:
                articles.extend(await self._fetch_newsapi())
            except Exception as e:
                logger.warning(f"NewsAPI failed: {e}")

        # Сбор из RSS
        for feed_url in self.rss_feeds:
            try:
                articles.extend(await self._fetch_rss(feed_url))
            except Exception as e:
                logger.warning(f"RSS failed {feed_url}: {e}")

        if not articles:
            logger.debug("Новостей не получено")
            return

        # Обработка и анализ сентимента
        processed = []
        for art in articles[: self.max_articles]:
            text = f"{art.get('title', '')} {art.get('summary', '')}"
            sentiment = self._analyze_sentiment(text)

            item = {
                "title": art.get("title", "N/A"),
                "source": art.get("source", "N/A"),
                "published": art.get("published", ""),
                "url": art.get("url", ""),
                "sentiment": sentiment["compound"],
                "positive": sentiment["pos"],
                "negative": sentiment["neg"],
                "neutral": sentiment["neu"],
            }
            processed.append(item)

        self._articles_collected += len(processed)

        # Расчёт среднего сентимента
        if processed:
            avg_sentiment = sum(a["sentiment"] for a in processed) / len(processed)
            self._last_sentiment = avg_sentiment

        # Публикация в EventBus
        await self.event_bus.publish(
            SystemEvent(
                type="news_batch_processed",
                payload={
                    "articles": processed,
                    "count": len(processed),
                    "avg_sentiment": self._last_sentiment,
                    "sources": list(set(a["source"] for a in processed)),
                },
                priority=EventPriority.LOW,
            )
        )

        logger.info(f"Опубликовано {len(processed)} новостей | Ср. сентимент: {self._last_sentiment:.2f}")

    def _analyze_sentiment(self, text: str) -> Dict[str, float]:
        """Анализ сентимента текста."""
        if self.analyzer:
            return self.analyzer.polarity_scores(text)

        # Fallback: простой анализ по ключевым словам
        positive_words = ["rise", "gain", "increase", "growth", "positive", "bullish", "strong", "beat", "exceed"]
        negative_words = ["fall", "drop", "decrease", "decline", "negative", "bearish", "weak", "miss", "fail"]

        text_lower = text.lower()
        pos = sum(1 for w in positive_words if w in text_lower)
        neg = sum(1 for w in negative_words if w in text_lower)
        total = pos + neg or 1

        compound = (pos - neg) / total
        return {
            "compound": compound,
            "pos": pos / total,
            "neg": neg / total,
            "neu": 1 - (pos + neg) / total,
        }

    async def _fetch_newsapi(self) -> List[Dict[str, Any]]:
        """Загрузка новостей из NewsAPI."""
        import aiohttp

        url = "https://newsapi.org/v2/everything"
        params = {
            "apiKey": self.news_api_key,
            "q": "forex OR trading OR finance OR economy",
            "language": "en,ru",
            "sortBy": "publishedAt",
            "pageSize": 10,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                data = await resp.json()
                return [
                    {
                        "title": a.get("title", ""),
                        "summary": a.get("description", ""),
                        "source": a.get("source", {}).get("name", "newsapi"),
                        "published": a.get("publishedAt", ""),
                        "url": a.get("url", ""),
                    }
                    for a in data.get("articles", [])
                ]

    async def _fetch_rss(self, url: str) -> List[Dict[str, Any]]:
        """Загрузка новостей из RSS."""
        import aiohttp
        import feedparser

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                xml = await resp.text()

        feed = feedparser.parse(xml)
        return [
            {
                "title": e.title,
                "summary": e.get("summary", ""),
                "source": feed.feed.get("title", url),
                "published": e.get("published", ""),
                "url": e.get("link", ""),
            }
            for e in feed.entries[:5]
        ]

    async def force_collect(self) -> Dict[str, Any]:
        """Принудительный сбор новостей (для ручного запуска)."""
        await self._collect_and_publish()
        return {
            "collected": self._articles_collected,
            "last_sentiment": self._last_sentiment,
        }
