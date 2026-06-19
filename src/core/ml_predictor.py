"""
ML Предиктор (Ensemble Model)
Объединяет технические сигналы, новости и ML-модели в единый голос.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np

from src.db.vector_db_manager import VectorDBManager

logger = logging.getLogger(__name__)


class MLPredictor:
    """
    Ensemble предиктор, который:
    - Получает технический сигнал от стратегий
    - Обогащает его сентиментом новостей (VectorDB)
    - Применяет ML-модели (если загружены)
    - Выдаёт итоговое решение с confidence score
    """

    def __init__(self, config, vector_db_manager: Optional[VectorDBManager] = None, event_bus=None):
        """
        Args:
            config: Конфигурация системы
            vector_db_manager: Менеджер векторной БД для RAG-поиска
            event_bus: Шина событий для публикации предсказаний
        """
        self.config = config
        self.event_bus = event_bus
        self.vector_db = vector_db_manager

        # Веса для ensemble (можно динамически менять)
        self.weights = {
            "technical": 0.5,  # Технический анализ
            "sentiment": 0.3,  # Сентимент новостей
            "ml_model": 0.2,  # ML-модель (если есть)
        }

        # ML модели (загружаются при инициализации)
        self.ml_model = None
        self.model_loaded = False

        # Пороги принятия решений
        self.buy_threshold = 0.3
        self.sell_threshold = -0.3

        # Кэш предсказаний (для оптимизации)
        self._prediction_cache: Dict[str, Dict[str, Any]] = {}

        logger.info(
            f"MLPredictor инициализирован: "
            f"tech={self.weights['technical']}, "
            f"sentiment={self.weights['sentiment']}, "
            f"ml={self.weights['ml_model']}"
        )

    async def predict(self, symbol: str, technical_signal: Dict, last_price: float) -> Dict[str, Any]:
        """
        Принимает сигнал от стратегии и обогащает его ML-анализом.

        Args:
            symbol: Торговый символ
            technical_signal: Сигнал от технической стратегии
                {
                    "signal": "BUY"/"SELL"/"HOLD",
                    "score": -1.0 до 1.0,
                    "confidence": 0.0 до 1.0
                }
            last_price: Текущая цена символа

        Returns:
            Dict с итоковым решением:
            {
                "symbol": "EURUSD",
                "decision": "BUY"/"SELL"/"HOLD",
                "score": -1.0 до 1.0,
                "confidence": 0.0 до 1.0,
                "details": {
                    "tech": -1.0 до 1.0,
                    "sentiment": -1.0 до 1.0,
                    "ml": -1.0 до 1.0
                }
            }
        """
        try:
            # 1. Оценка технического сигнала (-1 до 1)
            tech_score = self._parse_technical_score(technical_signal)

            # 2. Оценка сентимента из новостей (через VectorDB)
            sentiment_score = await self._get_market_sentiment(symbol)

            # 3. ML-предсказание (если модель загружена)
            ml_score = await self._get_ml_prediction(symbol, technical_signal, last_price)

            # 4. Взвешенная сумма всех факторов
            final_score = (
                tech_score * self.weights["technical"]
                + sentiment_score * self.weights["sentiment"]
                + ml_score * self.weights["ml_model"]
            )

            # 5. Принятие решения на основе порогов
            decision, confidence = self._make_decision(final_score)

            result = {
                "symbol": symbol,
                "decision": decision,
                "score": round(final_score, 4),
                "confidence": round(confidence, 4),
                "details": {"tech": round(tech_score, 4), "sentiment": round(sentiment_score, 4), "ml": round(ml_score, 4)},
                "timestamp": datetime.utcnow().isoformat(),
            }

            # 6. Публикация события (если есть event_bus)
            if self.event_bus:
                try:
                    from src.core.events import Event, EventType

                    event = Event(type=EventType.ML_PREDICTION, data=result)
                    # Асинхронная публикация (не блокируем)
                    asyncio.create_task(self.event_bus.publish(event))
                except Exception as e:
                    logger.debug(f"Не удалось опубликовать ML-предсказание: {e}")

            # 7. Логирование
            emoji = "📈" if decision == "BUY" else "📉" if decision == "SELL" else "⏸️"
            logger.info(f"{emoji} ML Prediction {symbol}: {decision} " f"(Score: {final_score:.3f}, Conf: {confidence:.2f})")

            return result

        except Exception as e:
            logger.error(f"Ошибка в MLPredictor.predict: {e}", exc_info=True)
            # Возвращаем HOLD при ошибке (безопасный fallback)
            return {
                "symbol": symbol,
                "decision": "HOLD",
                "score": 0.0,
                "confidence": 0.0,
                "details": {"tech": 0.0, "sentiment": 0.0, "ml": 0.0},
                "error": str(e),
            }

    def _parse_technical_score(self, technical_signal: Dict) -> float:
        """
        Преобразует технический сигнал в числовую оценку (-1 до 1).

        Args:
            technical_signal: Сигнал от стратегии

        Returns:
            float: Оценка от -1 (SELL) до 1 (BUY)
        """
        # Проверяем разные форматы сигналов
        if isinstance(technical_signal, dict):
            # Вариант 1: score уже есть
            if "score" in technical_signal:
                return float(technical_signal["score"])

            # Вариант 2: signal = "BUY"/"SELL"/"HOLD"
            signal = technical_signal.get("signal", "").upper()
            if signal == "BUY":
                return 1.0
            elif signal == "SELL":
                return -1.0
            else:
                return 0.0

        # Fallback
        return 0.0

    async def _get_market_sentiment(self, symbol: str) -> float:
        """
        Получает средний сентимент из VectorDB за последние N часов.

        Args:
            symbol: Торговый символ

        Returns:
            float: Сентимент от -1 (медвежий) до 1 (бычий)
        """
        if not self.vector_db or not self.vector_db.is_ready():
            logger.debug(f"VectorDB не готов, sentiment = 0.0 для {symbol}")
            return 0.0

        try:
            # Создаём эмбеддинг для поискового запроса
            # В реальном коде здесь будет загрузка модели SentenceTransformer
            from sentence_transformers import SentenceTransformer

            # Ленивая загрузка модели
            if not hasattr(self, "_embedding_model") or self._embedding_model is None:
                model_name = getattr(self.config, "vector_db", None)
                model_name = getattr(model_name, "embedding_model", "all-MiniLM-L6-v2") if model_name else "all-MiniLM-L6-v2"
                logger.info(f"Загрузка embedding модели: {model_name}...")
                self._embedding_model = SentenceTransformer(model_name)

            # Формируем запрос для поиска похожих новостей
            query_text = f"{symbol} market sentiment price action trend"
            query_embedding = self._embedding_model.encode(query_text, show_progress_bar=False).tolist()

            # Поиск в VectorDB
            results = self.vector_db.query_similar(query_embedding, n_results=5)

            if not results or not results.get("documents") or not results["documents"][0]:
                logger.debug(f"No sentiment data found for {symbol}")
                return 0.0

            # Анализируем найденные документы (здесь нужен NLP-анализ)
            # Для упрощения возвращаем среднее из результатов
            # В реальном коде: анализ с помощью FinBERT/VADER
            sentiment_scores = []
            for doc in results["documents"][0]:
                # Простая эвристика: если есть слова "bullish", "up" → +1, "bearish", "down" → -1
                doc_lower = doc.lower()
                if any(word in doc_lower for word in ["bullish", "up", "rise", "gain", "positive"]):
                    sentiment_scores.append(0.5)
                elif any(word in doc_lower for word in ["bearish", "down", "fall", "loss", "negative"]):
                    sentiment_scores.append(-0.5)

            if sentiment_scores:
                avg_sentiment = np.mean(sentiment_scores)
                logger.debug(f"Sentiment for {symbol}: {avg_sentiment:.3f} (from {len(sentiment_scores)} docs)")
                return avg_sentiment
            else:
                return 0.0

        except ImportError:
            logger.warning("sentence-transformers не установлен, sentiment анализ отключен")
            return 0.0
        except Exception as e:
            logger.error(f"Ошибка в _get_market_sentiment: {e}", exc_info=True)
            return 0.0

    async def _get_ml_prediction(self, symbol: str, technical_signal: Dict, last_price: float) -> float:
        """
        Получает предсказание от ML-модели (если загружена).

        Args:
            symbol: Торговый символ
            technical_signal: Технический сигнал
            last_price: Текущая цена

        Returns:
            float: Предсказание модели от -1 до 1
        """
        if not self.model_loaded or self.ml_model is None:
            logger.debug(f"ML модель не загружена, score = 0.0 для {symbol}")
            return 0.0

        try:
            # Здесь будет логика предсказания через ML модель
            # Пока возвращаем заглушку
            # В реальном коде: feature_vector = extract_features(symbol, last_price)
            # prediction = self.ml_model.predict(feature_vector)
            return 0.0

        except Exception as e:
            logger.error(f"Ошибка в _get_ml_prediction: {e}", exc_info=True)
            return 0.0

    def _make_decision(self, score: float) -> tuple[str, float]:
        """
        Преобразует итоговый score в решение (BUY/SELL/HOLD) и confidence.

        Args:
            score: Итоговый взвешенный score (-1 до 1)

        Returns:
            Tuple[decision, confidence]
        """
        if score > self.buy_threshold:
            # BUY сигнал
            confidence = min(1.0, abs(score))
            return "BUY", confidence
        elif score < self.sell_threshold:
            # SELL сигнал
            confidence = min(1.0, abs(score))
            return "SELL", confidence
        else:
            # HOLD (сигнал слабый)
            return "HOLD", min(1.0, abs(score))

    def set_weights(self, technical: float = None, sentiment: float = None, ml_model: float = None):
        """
        Обновляет веса ensemble на лету.

        Args:
            technical: Вес технического анализа (0.0 до 1.0)
            sentiment: Вес сентимента (0.0 до 1.0)
            ml_model: Вес ML-модели (0.0 до 1.0)
        """
        if technical is not None:
            self.weights["technical"] = technical
        if sentiment is not None:
            self.weights["sentiment"] = sentiment
        if ml_model is not None:
            self.weights["ml_model"] = ml_model

        # Нормализуем веса (сумма = 1.0)
        total = sum(self.weights.values())
        if total > 0:
            for key in self.weights:
                self.weights[key] /= total

        logger.info(f"MLPredictor веса обновлены: {self.weights}")

    def load_ml_model(self, model_path: str):
        """
        Загружает ML модель для предсказаний.

        Args:
            model_path: Путь к файлу модели
        """
        try:
            import joblib

            logger.info(f"Загрузка ML модели из {model_path}...")
            self.ml_model = joblib.load(model_path)
            self.model_loaded = True
            logger.info("✅ ML модель успешно загружена")

        except Exception as e:
            logger.error(f"Ошибка загрузки ML модели: {e}", exc_info=True)
            self.model_loaded = False

    def get_status(self) -> dict:
        """
        Получает статус предиктора.

        Returns:
            dict: Статус с метриками
        """
        return {
            "model_loaded": self.model_loaded,
            "weights": self.weights,
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "vector_db_ready": self.vector_db.is_ready() if self.vector_db else False,
        }
