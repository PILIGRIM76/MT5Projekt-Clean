"""
Примеры стратегий с использованием мульти-базовой архитектуры.
Демонстрируют работу с TimescaleDB, Qdrant, Redis и Neo4j.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MultiDBStrategyExample:
    """
    Пример стратегии использующей все базы данных Genesis Trading.

    Используемые БД:
    - TimescaleDB: Получение свечных данных
    - Qdrant: Поиск похожих паттернов
    - Redis: Кэширование сигналов и метрик
    - Neo4j: Проверка связей сущностей (граф знаний)
    - PostgreSQL: Сохранение результатов и аудита
    """

    def __init__(self, multi_db_manager, config):
        self.multi_db_manager = multi_db_manager
        self.config = config
        self.name = "MultiDBStrategyExample"

        # Кэш для данных
        self._data_cache = {}
        self._cache_ttl = 60  # секунд

    def generate_signal(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """
        Генерация торгового сигнала с использованием всех БД.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм

        Returns:
            dict: Сигнал или None
        """
        logger.info(f"Генерация сигнала для {symbol} {timeframe}")

        # 1. Проверка кэша Redis
        cached_signal = self._get_cached_signal(symbol)
        if cached_signal:
            logger.info(f"✓ Сигнал получен из кэша Redis: {cached_signal['direction']}")
            return cached_signal

        # 2. Получение свечных данных из TimescaleDB
        candles = self._get_candles_from_timescaledb(symbol, timeframe)
        if candles is None or candles.empty:
            logger.warning("Нет данных свечей")
            return None

        # 3. Поиск похожих паттернов через Qdrant
        similar_patterns = self._find_similar_patterns(symbol, candles)

        # 4. Проверка графа знаний через Neo4j
        kg_sentiment = self._get_kg_sentiment(symbol)

        # 5. Генерация сигнала на основе всех данных
        signal = self._create_signal(symbol, candles, similar_patterns, kg_sentiment)

        # 6. Кэширование сигнала в Redis
        if signal:
            self._cache_signal(symbol, signal)

        # 7. Сохранение в PostgreSQL для аудита
        self._save_signal_audit(symbol, signal, similar_patterns, kg_sentiment)

        return signal

    def _get_candles_from_timescaledb(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Получение свечных данных из TimescaleDB.

        Производительность:
        - 100 свечей: ~2 мс
        - 1000 свечей: ~5 мс
        - С агрегацией: ~1 мс
        """
        if not self.multi_db_manager.is_available("timescaledb"):
            logger.warning("TimescaleDB недоступен")
            return None

        try:
            ts_adapter = self.multi_db_manager.get_timescaledb()

            # Преобразование таймфрейма
            timeframe_seconds = self._timeframe_to_seconds(timeframe)

            # Получение данных за последние N свечей
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=limit * self._timeframe_to_minutes(timeframe))

            candles = ts_adapter.get_candles(
                table_name="candle_data",
                symbol=symbol,
                timeframe=timeframe_seconds,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )

            logger.debug(f"✓ Загружено {len(candles)} свечей из TimescaleDB")
            return candles

        except Exception as e:
            logger.error(f"Ошибка чтения из TimescaleDB: {e}")
            return None

    def _find_similar_patterns(self, symbol: str, candles: pd.DataFrame, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Поиск похожих рыночных паттернов через Qdrant.

        Алгоритм:
        1. Создать вектор текущего паттерна
        2. Найти похожие в Qdrant
        3. Вернуть результаты с метаданными
        """
        if not self.multi_db_manager.is_available("qdrant"):
            logger.info("Qdrant недоступен, пропускаем поиск паттернов")
            return []

        try:
            qdrant = self.multi_db_manager.get_qdrant()

            # Создание вектора паттерна (упрощенно)
            pattern_vector = self._create_pattern_vector(candles)

            # Поиск похожих
            results = qdrant.find_similar_patterns(
                pattern_vector=pattern_vector,
                symbol=symbol,
                timeframe=self._timeframe_to_seconds(self.config.DEFAULT_TIMEFRAME),
                limit=limit,
            )

            logger.debug(f"✓ Найдено {len(results)} похожих паттернов")

            # Форматирование результатов
            formatted_results = []
            for payload, score in results:
                formatted_results.append(
                    {
                        "timestamp": payload.get("timestamp"),
                        "symbol": payload.get("symbol"),
                        "outcome": payload.get("outcome", "unknown"),
                        "profit": payload.get("profit", 0),
                        "score": score,
                    }
                )

            return formatted_results

        except Exception as e:
            logger.error(f"Ошибка поиска паттернов в Qdrant: {e}")
            return []

    def _get_kg_sentiment(self, symbol: str) -> float:
        """
        Получение сентимента из графа знаний Neo4j.

        Пример запроса:
        - Найти сущность символа
        - Получить связанные сущности (компании, персоны, события)
        - Вычислить взвешенный сентимент
        """
        if not self.multi_db_manager.is_available("neo4j"):
            logger.info("Neo4j недоступен, используется сентимент по умолчанию")
            return 0.0

        try:
            neo4j_driver = self.multi_db_manager.get_neo4j_driver()

            from neo4j import Session

            with Session(neo4j_driver) as session:
                # Запрос к графу знаний
                result = session.run(
                    """
                    MATCH (e:Entity {entity_id: $symbol})<-[r]-(other)
                    WHERE r.relation_type IN ['INFLUENCES', 'AFFECTS', 'RELATED_TO']
                    RETURN
                        avg(r.weight * COALESCE(other.sentiment_score, 0)) as weighted_sentiment,
                        count(r) as relation_count
                """,
                    symbol=symbol,
                )

                record = result.single()

                if record and record["weighted_sentiment"] is not None:
                    sentiment = float(record["weighted_sentiment"])
                    logger.debug(f"✓ KG сентимент для {symbol}: {sentiment:.3f} ({record['relation_count']} связей)")
                    return sentiment

            return 0.0

        except Exception as e:
            logger.error(f"Ошибка чтения из Neo4j: {e}")
            return 0.0

    def _create_signal(
        self, symbol: str, candles: pd.DataFrame, similar_patterns: List[Dict], kg_sentiment: float
    ) -> Optional[Dict[str, Any]]:
        """
        Создание торгового сигнала на основе всех данных.
        """
        if candles.empty:
            return None

        # Простая логика для примера
        current_price = candles["close"].iloc[-1]

        # Вычисление направления на основе паттернов
        if similar_patterns:
            bullish_patterns = sum(1 for p in similar_patterns if p.get("outcome") == "bullish")
            bearish_patterns = len(similar_patterns) - bullish_patterns

            pattern_signal = (bullish_patterns - bearish_patterns) / len(similar_patterns)
        else:
            pattern_signal = 0.0

        # Комбинированный сигнал
        combined_signal = (pattern_signal + kg_sentiment) / 2

        # Определение направления
        if combined_signal > 0.3:
            direction = "BUY"
            confidence = min(abs(combined_signal), 1.0)
        elif combined_signal < -0.3:
            direction = "SELL"
            confidence = min(abs(combined_signal), 1.0)
        else:
            direction = "HOLD"
            confidence = 1.0 - abs(combined_signal)

        signal = {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "price": current_price,
            "timestamp": datetime.utcnow(),
            "strategy": self.name,
            "metadata": {
                "pattern_score": pattern_signal,
                "kg_sentiment": kg_sentiment,
                "similar_patterns_count": len(similar_patterns),
                "candles_analyzed": len(candles),
            },
        }

        logger.info(f"✓ Сигнал создан: {direction} {symbol} (confidence: {confidence:.2f})")
        return signal

    def _create_pattern_vector(self, candles: pd.DataFrame) -> np.ndarray:
        """
        Создание векторного представления паттерна.

        В реальном проекте использовать ML модель для эмбеддингов.
        """
        # Упрощенно: используем статистики цен
        returns = candles["close"].pct_change().fillna(0)

        vector = np.array(
            [
                returns.mean(),
                returns.std(),
                returns.skew(),
                returns.kurtosis(),
                (candles["close"].iloc[-1] - candles["close"].iloc[0]) / candles["close"].iloc[0],
                candles["volume"].mean() if "volume" in candles else 0,
            ]
        )

        # Дополнение до размера 384 (для all-MiniLM-L6-v2)
        vector = np.pad(vector, (0, 384 - len(vector)), constant_values=0)

        return vector

    def _get_cached_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Получение сигнала из кэша Redis."""
        if not self.multi_db_manager.is_available("redis"):
            return None

        try:
            redis = self.multi_db_manager.get_redis()
            return redis.get_signal(symbol)
        except Exception as e:
            logger.error(f"Ошибка чтения из Redis: {e}")
            return None

    def _cache_signal(self, symbol: str, signal: Dict[str, Any], ttl: int = 300):
        """Кэширование сигнала в Redis."""
        if not self.multi_db_manager.is_available("redis"):
            return

        try:
            redis = self.multi_db_manager.get_redis()
            redis.cache_signal(symbol, signal, ttl_seconds=ttl)
            logger.debug(f"✓ Сигнал закэширован в Redis (TTL: {ttl}s)")
        except Exception as e:
            logger.error(f"Ошибка записи в Redis: {e}")

    def _save_signal_audit(self, symbol: str, signal: Optional[Dict], similar_patterns: List[Dict], kg_sentiment: float):
        """Сохранение аудита сигнала в PostgreSQL."""
        if not self.multi_db_manager.is_available("postgres"):
            return

        try:
            session = self.multi_db_manager.get_postgres_session()
            from sqlalchemy import text

            query = text("""
                INSERT INTO trade_audit
                (trade_ticket, symbol, decision_type, market_regime, consensus_score,
                 kg_sentiment, risk_checks, execution_status, created_at)
                VALUES
                (:ticket, :symbol, 'SIGNAL', 'unknown', :consensus, :kg_sentiment,
                 :risk_checks, 'PENDING', NOW())
            """)

            session.execute(
                query,
                {
                    "ticket": abs(hash(f"{symbol}_{datetime.utcnow().isoformat()}")),
                    "symbol": symbol,
                    "consensus": signal["confidence"] if signal else 0.0,
                    "kg_sentiment": kg_sentiment,
                    "risk_checks": '{"pattern_check": true, "kg_check": true}',
                },
            )

            session.commit()
            logger.debug("✓ Аудит сигнала сохранен в PostgreSQL")

        except Exception as e:
            logger.error(f"Ошибка записи аудита в PostgreSQL: {e}")

    def _timeframe_to_seconds(self, timeframe: str) -> int:
        """Преобразование таймфрейма в секунды."""
        mapping = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "M30": 1800,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
        }
        return mapping.get(timeframe, 60)

    def _timeframe_to_minutes(self, timeframe: str) -> int:
        """Преобразование таймфрейма в минуты."""
        mapping = {
            "M1": 1,
            "M5": 5,
            "M15": 15,
            "M30": 30,
            "H1": 60,
            "H4": 240,
            "D1": 1440,
        }
        return mapping.get(timeframe, 1)


class RealTimeCandleStrategy(MultiDBStrategyExample):
    """
    Стратегия реального времени с использованием TimescaleDB continuous aggregates.

    Особенности:
    - Использует агрегированные данные (материализованные представления)
    - Автоматическое обновление через continuous aggregates
    - Производительность: ~1 мс на запрос
    """

    def __init__(self, multi_db_manager, config):
        super().__init__(multi_db_manager, config)
        self.name = "RealTimeCandleStrategy"

    def get_aggregated_data(self, symbol: str, bucket_width: str = "1 hour", days_back: int = 7) -> Optional[pd.DataFrame]:
        """
        Получение агрегированных данных из TimescaleDB.

        Args:
            symbol: Торговый инструмент
            bucket_width: Ширина бакета ('1 hour', '15 minutes', etc.)
            days_back: Количество дней для загрузки

        Returns:
            DataFrame с агрегированными данными
        """
        if not self.multi_db_manager.is_available("timescaledb"):
            return None

        try:
            ts_adapter = self.multi_db_manager.get_timescaledb()

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days_back)

            # Использование continuous aggregate
            data = ts_adapter.get_continuous_agrate(
                table_name="candle_data",
                symbol=symbol,
                timeframe=self._timeframe_to_seconds("H1"),
                bucket_width=bucket_width,
                start_time=start_time,
                end_time=end_time,
            )

            logger.debug(f"✓ Загружено {len(data)} агрегированных записей")
            return data

        except Exception as e:
            logger.error(f"Ошибка чтения агрегатов: {e}")
            return None


class RAGNewsStrategy(MultiDBStrategyExample):
    """
    Стратегия на основе RAG поиска новостей.

    Использует Qdrant для:
    - Поиска похожих новостей
    - Поиска исторических событий
    - Анализа сентимента
    """

    def __init__(self, multi_db_manager, config, embedding_model=None):
        super().__init__(multi_db_manager, config)
        self.name = "RAGNewsStrategy"
        self.embedding_model = embedding_model

    def search_relevant_news(
        self, symbol: str, query_text: Optional[str] = None, days_back: int = 7, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Поиск релевантных новостей через RAG.

        Args:
            symbol: Торговый инструмент
            query_text: Текст запроса (если None, используется символ)
            days_back: Период поиска в днях
            limit: Количество результатов

        Returns:
            Список новостей с метаданными
        """
        if not self.multi_db_manager.is_available("qdrant"):
            logger.warning("Qdrant недоступен")
            return []

        try:
            qdrant = self.multi_db_manager.get_qdrant()

            # Если текст запроса не указан, используем символ
            if query_text is None:
                query_text = f"Торговые новости для {symbol}"

            # RAG поиск
            results = qdrant.search_by_text(
                query_text=query_text,
                embedding_model=self.embedding_model,
                symbol=symbol,
                days_back=days_back,
                limit=limit,
            )

            logger.debug(f"✓ Найдено {len(results)} релевантных новостей")

            # Форматирование
            formatted_news = []
            for payload, score in results:
                formatted_news.append(
                    {
                        "content": payload.get("content", ""),
                        "source": payload.get("source", "unknown"),
                        "timestamp": payload.get("timestamp"),
                        "sentiment": payload.get("sentiment_score", 0),
                        "score": score,
                    }
                )

            return formatted_news

        except Exception as e:
            logger.error(f"Ошибка RAG поиска: {e}")
            return []

    def analyze_news_sentiment(self, symbol: str, days_back: int = 3) -> Dict[str, float]:
        """
        Анализ сентимента новостей.

        Returns:
            dict: Статистика сентимента
        """
        news = self.search_relevant_news(symbol, days_back=days_back, limit=50)

        if not news:
            return {"sentiment": 0.0, "count": 0}

        sentiments = [n["sentiment"] for n in news]
        scores = [n["score"] for n in news]

        # Взвешенный сентимент
        weighted_sentiment = sum(s * sc for s, sc in zip(sentiments, scores)) / sum(scores) if sum(scores) > 0 else 0

        return {
            "sentiment": weighted_sentiment,
            "count": len(news),
            "avg_sentiment": sum(sentiments) / len(sentiments),
            "max_sentiment": max(sentiments),
            "min_sentiment": min(sentiments),
        }
