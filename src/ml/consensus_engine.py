# src/ml/consensus_engine.py
import logging
from typing import List, Dict, Any, Optional, Tuple  # <--- ДОБАВЛЕН Tuple

import numpy as np
import pandas as pd  # <--- ДОБАВЛЕН
from transformers import pipeline
from sentence_transformers import SentenceTransformer

from src.db.vector_db_manager import VectorDBManager
from src.db.database_manager import DatabaseManager
from src.core.config_models import Settings, ConsensusWeights  # <--- ИЗМЕНЕНИЕ: Импорт ConsensusWeights
from src.data_models import TradeSignal, SignalType

logger = logging.getLogger(__name__)


class ConsensusResult:
    """Структура для хранения комплексного результата анализа."""

    def __init__(self):
        self.relations: List[Dict] = []
        self.aggregated_sentiment: float = 0.0
        self.historical_context_sentiment: Optional[float] = None
        # --- НОВОЕ ПОЛЕ: On-Chain Score ---
        self.on_chain_score: float = 0.0
        # -----------------------------------


class ConsensusEngine:
    """
    Движок консенсуса. Версия 2.1 с многофакторным взвешенным консенсусом.
    """

    def __init__(self, config: Settings, db_manager: DatabaseManager, vector_db_manager: Optional[VectorDBManager]):
        self.config = config
        self.db_manager = db_manager
        self.vector_db_manager = vector_db_manager
        self.sentiment_pipeline = None
        self.embedding_model: Optional[SentenceTransformer] = None
        self.consensus_weights: ConsensusWeights = config.CONSENSUS_WEIGHTS  #  Сохраняем веса

    def _get_uncertainty_score(self, text: str) -> float:
        """
        Имитирует анализ тональности для определения "Неопределенности".
        В реальном коде здесь была бы специализированная модель.
        """
        # Имитация: ищем ключевые слова неопределенности
        uncertainty_keywords = ["uncertainty", "volatility", "risk", "unpredictable", "doubt"]
        score = 0.0
        for keyword in uncertainty_keywords:
            if keyword in text.lower():
                score += 0.2
        return min(score, 1.0)

    def load_models(self):
        """Загружает необходимые NLP модели."""
        if self.sentiment_pipeline:
            return
        try:
            logger.info("Загрузка модели анализа настроений FinBERT ('ProsusAI/finbert')...")
            # Указываем device=-1, чтобы принудительно использовать CPU, если нет CUDA.
            self.sentiment_pipeline = pipeline("text-classification", model="ProsusAI/finbert", framework="pt",
                                               device=-1)
            logger.info("Модель FinBERT успешно загружена.")
        except Exception as e:
            logger.error(f"Не удалось загрузить модель FinBERT: {e}", exc_info=True)

        if self.config.vector_db.enabled and self.embedding_model is None:
            logger.warning(
                "Модель для эмбеддингов не была передана в ConsensusEngine. Семантический поиск будет недоступен.")

    def get_historical_context_sentiment(self, symbol: str, market_regime: str) -> Optional[float]:
        """
        [TZ 4.1] Использует VectorDB (RAG) для поиска семантически похожих новостей.
        Возвращает средневзвешенный сентимент.
        """
        if not self.vector_db_manager or not self.vector_db_manager.is_ready() or not self.embedding_model or not self.sentiment_pipeline:
            return None

        query_text = f"Market context for {symbol}: a {market_regime.lower().replace('_', ' ')} period."

        try:
            # 1. Векторизация и поиск (RAG)
            query_embedding = self.embedding_model.encode(query_text).tolist()
            similar_events = self.vector_db_manager.query_similar(query_embedding, n_results=5)

            if not similar_events or not similar_events.get('ids') or not similar_events['ids'][0]:
                return None

            vector_ids = similar_events['ids'][0]
            distances = similar_events['distances'][0]
            original_texts_map = self.db_manager.get_articles_by_vector_ids(vector_ids)

            sentiments = []
            weights = []

            for i, doc_id in enumerate(vector_ids):
                text = original_texts_map.get(doc_id)
                if text:
                    # 2. Анализ сентимента и взвешивание
                    result = self.sentiment_pipeline(text[:512])[0]
                    score = result['score']
                    if result['label'] == 'negative': score *= -1
                    if result['label'] == 'neutral': score = 0

                    similarity = 1.0 - distances[i]
                    sentiments.append(score)
                    weights.append(similarity)

            if not sentiments: return None

            weighted_sentiment = float(np.average(sentiments, weights=weights))
            return weighted_sentiment

        except Exception as e:
            logger.error(f"Ошибка в процессе семантического поиска (RAG): {e}")
            return None

    def calculate_on_chain_score(self, df: pd.DataFrame) -> float:
        """
        Вычисляет унифицированный скор On-Chain данных (-1.0 до 1.0) на основе DF с фичами.

        Логика:
        - MVRV Z-Score: > 1.0 = переоценен (SELL: -0.5), < -1.0 = недооценен (BUY: +0.5)
        - Funding Rate EWMA: > 0.0005 = перегрев (SELL: -0.5), < -0.0005 = паника (BUY: +0.5)
        """
        score = 0.0
        factors = 0

        # --- ИЗМЕНЕНИЕ: Используем новые имена признаков из FeatureEngineer ---
        if 'ONCHAIN_MVRV_ZSCORE' in df.columns and 'ONCHAIN_FUNDING_RATE_EWMA' in df.columns:
            last_row = df.iloc[-1]
            mvrv_zscore = last_row['ONCHAIN_MVRV_ZSCORE']
            funding_rate_ewma = last_row['ONCHAIN_FUNDING_RATE_EWMA']

            # MVRV Score
            if mvrv_zscore > 1.0:
                score -= 0.5
            elif mvrv_zscore < -1.0:
                score += 0.5
            factors += 1

            # Funding Rate Score
            if funding_rate_ewma > 0.0005:
                score -= 0.5
            elif funding_rate_ewma < -0.0005:
                score += 0.5
            factors += 1

            return np.clip(score / factors, -1.0, 1.0) if factors > 0 else 0.0

        return 0.0

    def calculate_multifactor_consensus(
            self,
            ai_signal: TradeSignal,
            classic_signals: List[TradeSignal],
            kg_sentiment_score: float,
            on_chain_score: float,
            is_crypto: bool
    ) -> Tuple[SignalType, float]:
        """
        Рассчитывает финальный взвешенный консенсус.
        """
        weights = self.consensus_weights
        kg_score = kg_sentiment_score

        # --- TZ 2.3: Анализ Причинности KG ---
        # Проверка: Если KG_Sentiment сильный (>$0.5$), но исторический PnL по сделкам с этим сентиментом отрицательный,
        # снизить вес KG-фактора до 0.05.
        
        if abs(kg_score) > 0.5:
            try:
                # 1. Запрос исторического PnL для данного сентимента
                historical_pnl_for_sentiment = self.db_manager.get_historical_pnl_for_kg_sentiment(kg_score)
                
                # Проверка, что возвращаемое значение действительное число
                if historical_pnl_for_sentiment is not None and isinstance(historical_pnl_for_sentiment, (int, float)):
                    if historical_pnl_for_sentiment < 0:
                        logger.critical(
                            f"[KG-CAUSALITY] СИЛЬНЫЙ СЕНТИМЕНТ ({kg_score:.2f}) исторически убыточен. Снижение веса KG.")
                        weights.sentiment_kg = 0.05  # Снижаем вес
                else:
                    logger.warning(f"[KG-CAUSALITY] Недействительное значение исторического PnL: {historical_pnl_for_sentiment}")
            except Exception as e:
                logger.error(f"[KG-CAUSALITY] Ошибка при получении исторического PnL: {e}")
        # -------------------------------------

        # 1.1. AI-прогноз
        ai_score = 0.0
        if ai_signal.type == SignalType.BUY:
            ai_score = ai_signal.confidence
        elif ai_signal.type == SignalType.SELL:
            ai_score = -ai_signal.confidence

        # 1.2. Классические стратегии
        classic_score = 0.0
        if classic_signals:
            buy_count = sum(1 for s in classic_signals if s.type == SignalType.BUY)
            sell_count = sum(1 for s in classic_signals if s.type == SignalType.SELL)
            total_count = len(classic_signals)
            if total_count > 0:
                classic_score = (buy_count - sell_count) / total_count

        # 1.3. Сентимент KG (уже в диапазоне -1.0 до 1.0)
        # kg_score уже определен

        # 1.4. On-Chain данные
        on_chain_factor = on_chain_score

        # 2. Применяем веса
        weighted_sum = (ai_score * weights.ai_forecast) + \
                       (classic_score * weights.classic_strategies) + \
                       (kg_score * weights.sentiment_kg)

        total_weight = weights.ai_forecast + weights.classic_strategies + weights.sentiment_kg
        if is_crypto:
            weighted_sum += (on_chain_score * weights.on_chain_data)
            total_weight += weights.on_chain_data

        if total_weight > 0:
            weighted_sum /= total_weight

        # --- TZ 4.2: Анализ Тональности (Uncertainty Penalty) ---
        # Снижен penalty с 10% до 5% для более мягкого влияния
        latest_news_text = "The market is facing high uncertainty due to unpredictable FED decisions."
        uncertainty_score = self._get_uncertainty_score(latest_news_text)

        if uncertainty_score > 0.7:
            penalty_factor = 1.0 - 0.05  # Снижение на 5% (было 10%)
            weighted_sum *= penalty_factor
            logger.warning(
                f"[Tone Analysis] Высокая неопределенность ({uncertainty_score:.2f}). Consensus Score снижен на 5%.")

        # 3. Финальное решение
        final_signal_type = SignalType.HOLD
        if weighted_sum > self.config.CONSENSUS_THRESHOLD:
            final_signal_type = SignalType.BUY
        elif weighted_sum < -self.config.CONSENSUS_THRESHOLD:
            final_signal_type = SignalType.SELL

        final_score = abs(weighted_sum)

        return final_signal_type, final_score



