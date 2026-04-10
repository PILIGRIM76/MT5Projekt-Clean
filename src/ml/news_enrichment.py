# -*- coding: utf-8 -*-
"""
src/ml/news_enrichment.py — Обогащение данных новостями через FAISS + KG

Реализует:
- Семантический поиск релевантных новостей через FAISS
- Извлечение контекста из Knowledge Graph
- Формирование enriched features для ML-моделей
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """Единица новостных данных."""

    headline: str
    body: str
    source: str
    timestamp: datetime
    sentiment: float = 0.0  # [-1.0, 1.0]
    relevance: float = 0.0  # [0.0, 1.0]
    symbols: List[str] = field(default_factory=list)
    embedding: Optional[np.ndarray] = None

    def __repr__(self) -> str:
        return f"NewsItem(headline='{self.headline[:50]}...', sentiment={self.sentiment:.2f})"


@dataclass
class EnrichedContext:
    """
    Обогащённый контекст для модели.

    Содержит:
    - Агрегированный сентимент новостей
    - Количество релевантных новостей
    - Вектор семантической близости
    - KG-фичи
    """

    avg_sentiment: float = 0.0
    news_count: int = 0
    max_relevance: float = 0.0
    semantic_score: float = 0.0  # Насколько тема новостей совпадает с символом
    kg_sentiment: float = 0.0
    kg_causality_score: float = 0.0
    raw_news: List[NewsItem] = field(default_factory=list)
    feature_vector: Optional[np.ndarray] = None

    def to_features(self) -> np.ndarray:
        """Возвращает вектор признаковей для модели."""
        if self.feature_vector is not None:
            return self.feature_vector

        self.feature_vector = np.array(
            [
                self.avg_sentiment,
                self.news_count / 100.0,  # Нормализуем
                self.max_relevance,
                self.semantic_score,
                self.kg_sentiment,
                self.kg_causality_score,
            ],
            dtype=np.float32,
        )

        return self.feature_vector


class NewsEnrichmentEngine:
    """
    Движок обогащения торговых данных новостями.

    Поток:
    1. Получает эмбеддинг символа/запроса
    2. Ищет релевантные новости в FAISS
    3. Запрашивает контекст из Knowledge Graph
    4. Агрегирует сентимент
    5. Возвращает EnrichedContext
    """

    def __init__(
        self,
        faiss_index_dir: Optional[Path] = None,
        kg_querier: Optional[Any] = None,  # KnowledgeGraphQuerier
        embedding_model: Optional[Any] = None,  # SentenceTransformer
    ):
        self.faiss_index_dir = faiss_index_dir
        self.kg_querier = kg_querier
        self.embedding_model = embedding_model

        self._faiss_index = None
        self._faiss_metadata = []
        self._is_initialized = False

    def initialize(self) -> bool:
        """Инициализирует FAISS индекс."""
        if self._is_initialized:
            return True

        try:
            self._load_faiss_index()
            self._is_initialized = True
            logger.info(f"[NewsEnrichment] Инициализирован. FAISS: {self._faiss_index is not None}")
            return True
        except Exception as e:
            logger.error(f"[NewsEnrichment] Ошибка инициализации: {e}")
            return False

    def enrich(
        self,
        symbol: str,
        query_text: Optional[str] = None,
        hours_back: int = 24,
        top_k: int = 10,
    ) -> EnrichedContext:
        """
        Обогащает данные новостями для символа.

        Args:
            symbol: Торговый символ (EURUSD, BTC, ...)
            query_text: Произвольный текстовый запрос (если None, использует symbol)
            hours_back: Глубина поиска в часах
            top_k: Количество топ результатов

        Returns:
            EnrichedContext с агрегированными новостными фичами
        """
        if not self._is_initialized:
            self.initialize()

        context = EnrichedContext()

        # 1. Семантический поиск новостей через FAISS
        news_items = self._search_news(symbol, query_text, top_k=top_k)

        if not news_items:
            logger.debug(f"[NewsEnrichment] Новости не найдены для {symbol}")
            return context

        # 2. Фильтрация по времени
        cutoff = datetime.now() - timedelta(hours=hours_back)
        recent_news = [n for n in news_items if n.timestamp >= cutoff]

        if not recent_news:
            return context

        # 3. Агрегация сентимента
        sentiments = [n.sentiment for n in recent_news if abs(n.sentiment) > 0.01]
        if sentiments:
            context.avg_sentiment = float(np.mean(sentiments))
            context.max_relevance = max(n.relevance for n in recent_news)

        context.news_count = len(recent_news)
        context.raw_news = recent_news

        # 4. Семантическая близость
        if self.embedding_model and query_text:
            context.semantic_score = self._compute_semantic_similarity(query_text, recent_news)

        # 5. Knowledge Graph контекст
        if self.kg_querier:
            kg_context = self._get_kg_sentiment(symbol)
            context.kg_sentiment = kg_context.get("sentiment", 0.0)
            context.kg_causality_score = kg_context.get("causality", 0.0)

        logger.debug(f"[NewsEnrichment] {symbol}: {context.news_count} новостей, " f"сентимент={context.avg_sentiment:.3f}")

        return context

    def _search_news(self, symbol: str, query_text: Optional[str], top_k: int) -> List[NewsItem]:
        """Ищет новости через FAISS."""
        if self._faiss_index is None:
            return []

        try:
            import faiss

            query = query_text or f"market analysis {symbol}"

            # Создаём эмбеддинг запроса
            if self.embedding_model:
                query_embedding = self.embedding_model.encode([query])
            else:
                # Fallback: нулевой вектор (не рекомендуется)
                dim = self._faiss_index.d
                query_embedding = np.zeros((1, dim), dtype=np.float32)

            # FAISS поиск
            distances, indices = self._faiss_index.search(
                query_embedding.astype(np.float32),
                min(top_k * 2, len(self._faiss_metadata)),
            )

            # Собираем результаты
            news_items = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self._faiss_metadata):
                    continue

                meta = self._faiss_metadata[idx]
                similarity = 1.0 - dist  # FAISS distance -> similarity

                news_items.append(
                    NewsItem(
                        headline=meta.get("headline", ""),
                        body=meta.get("body", ""),
                        source=meta.get("source", "unknown"),
                        timestamp=datetime.fromisoformat(meta["timestamp"]) if "timestamp" in meta else datetime.now(),
                        sentiment=meta.get("sentiment", 0.0),
                        relevance=similarity,
                        symbols=meta.get("symbols", []),
                    )
                )

            return news_items[:top_k]

        except Exception as e:
            logger.warning(f"[NewsEnrichment] Ошибка FAISS поиска: {e}")
            return []

    def _compute_semantic_similarity(self, query: str, news_items: List[NewsItem]) -> float:
        """Вычисляет среднюю семантическую близость новостей к запросу."""
        if not self.embedding_model or not news_items:
            return 0.0

        try:
            from sklearn.metrics.pairwise import cosine_similarity

            query_emb = self.embedding_model.encode([query])[0]
            news_texts = [n.headline + " " + n.body[:200] for n in news_items]
            news_embs = self.embedding_model.encode(news_texts)

            similarities = cosine_similarity([query_emb], news_embs)[0]
            return float(np.mean(similarities))
        except Exception as e:
            logger.debug(f"[NewsEnrichment] Ошибка семантической близости: {e}")
            return 0.0

    def _get_kg_sentiment(self, symbol: str) -> Dict[str, float]:
        """Получает сентимент из Knowledge Graph."""
        if not self.kg_querier:
            return {"sentiment": 0.0, "causality": 0.0}

        try:
            # Проверяем интерфейс KG querier
            if hasattr(self.kg_querier, "get_symbol_sentiment"):
                return self.kg_querier.get_symbol_sentiment(symbol)
            elif hasattr(self.kg_querier, "query"):
                result = self.kg_querier.query(f"SELECT sentiment, causality FROM asset_sentiment WHERE symbol = '{symbol}'")
                if result:
                    return {
                        "sentiment": result[0].get("sentiment", 0.0),
                        "causality": result[0].get("causality", 0.0),
                    }
        except Exception as e:
            logger.debug(f"[NewsEnrichment] Ошибка KG запроса: {e}")

        return {"sentiment": 0.0, "causality": 0.0}

    def _load_faiss_index(self) -> None:
        """Загружает FAISS индекс и метаданные."""
        if not self.faiss_index_dir:
            return

        try:
            import faiss

            index_path = self.faiss_index_dir / "faiss_index.bin"
            meta_path = self.faiss_index_dir / "faiss_metadata.json"

            if index_path.exists():
                self._faiss_index = faiss.read_index(str(index_path))
                logger.info(f"[NewsEnrichment] FAISS индекс загружен: {index_path}")

            if meta_path.exists():
                import json

                with open(meta_path, "r", encoding="utf-8") as f:
                    self._faiss_metadata = json.load(f)
                logger.info(f"[NewsEnrichment] FAISS метаданные: {len(self._faiss_metadata)} документов")

        except ImportError:
            logger.warning("[NewsEnrichment] FAISS не установлен. pip install faiss-cpu")
        except Exception as e:
            logger.error(f"[NewsEnrichment] Ошибка загрузки FAISS: {e}")

    def get_enriched_features(
        self,
        symbol: str,
        base_features: np.ndarray,
        hours_back: int = 24,
    ) -> np.ndarray:
        """
        Возвращает объединённый вектор: base_features + news_features.

        Args:
            symbol: Торговый символ
            base_features: Базовые технические признаки
            hours_back: Глубина новостей

        Returns:
            np.array: Concat(base_features, news_features)
        """
        context = self.enrich(symbol, hours_back=hours_back)
        news_features = context.to_features()

        return np.concatenate([base_features, news_features])

    def __repr__(self) -> str:
        status = "initialized" if self._is_initialized else "not initialized"
        return f"NewsEnrichmentEngine(faiss={'yes' if self._faiss_index else 'no'}, status={status})"
