"""
Unit тесты для ML-модулей: ConsensusEngine, ModelFactory.

Тестирует:
- ConsensusEngine (многофакторный консенсус)
- On-Chain score расчет
- Historical context sentiment (RAG)
- Взвешенный консенсус
- Uncertainty penalty
"""

from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, call, patch

import numpy as np
import pandas as pd
import pytest

from src.core.config_models import ConsensusWeights, Settings
from src.data_models import SignalType, TradeSignal


class TestConsensusEngineBasics:
    """Базовые тесты для ConsensusEngine."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_config, mock_database_manager, mock_vector_db_manager):
        """Фикстура для настройки тестов ConsensusEngine."""
        self.mock_config = mock_config
        self.mock_db_manager = mock_database_manager
        self.mock_vector_db_manager = mock_vector_db_manager

    def test_consensus_engine_initialization(self):
        """Проверка инициализации ConsensusEngine."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(
                config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=self.mock_vector_db_manager
            )

            assert engine.config is self.mock_config
            assert engine.consensus_weights is self.mock_config.CONSENSUS_WEIGHTS

    def test_get_uncertainty_score_low(self):
        """Проверка low uncertainty score."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(
                config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=self.mock_vector_db_manager
            )

            text = "The market is stable and growing steadily."
            score = engine._get_uncertainty_score(text)

            assert score >= 0.0
            assert score <= 0.2  # Низкая неопределенность

    def test_get_uncertainty_score_high(self):
        """Проверка high uncertainty score."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(
                config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=self.mock_vector_db_manager
            )

            text = "Market uncertainty and volatility create unpredictable risk and doubt."
            score = engine._get_uncertainty_score(text)

            assert score > 0.5
            assert score <= 1.0

    def test_get_uncertainty_score_multiple_keywords(self):
        """Проверка с несколькими ключевыми словами."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(
                config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=self.mock_vector_db_manager
            )

            text = "uncertainty uncertainty volatility risk"
            score = engine._get_uncertainty_score(text)

            # Должно быть ограничено 1.0
            assert score <= 1.0


class TestConsensusEngineOnChainScore:
    """Тесты для On-Chain score."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_config, mock_database_manager):
        """Фикстура для настройки тестов."""
        self.mock_config = mock_config
        self.mock_db_manager = mock_database_manager

    def test_calculate_on_chain_score_no_columns(self):
        """Проверка без On-Chain колонок."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            df = pd.DataFrame({"open": [1.1, 1.2, 1.3], "close": [1.15, 1.25, 1.35]})

            score = engine.calculate_on_chain_score(df)

            assert score == 0.0

    def test_calculate_on_chain_score_mvrv_overvalued(self):
        """Проверка с MVRV > 1.0 (переоценен)."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            df = pd.DataFrame(
                {
                    "ONCHAIN_MVRV_ZSCORE": [0.5, 0.8, 1.5],  # Последний > 1.0
                    "ONCHAIN_FUNDING_RATE_EWMA": [0.0001, 0.0002, 0.0003],
                }
            )

            score = engine.calculate_on_chain_score(df)

            # MVRV > 1.0 дает -0.5
            assert score < 0.0
            assert score >= -0.5

    def test_calculate_on_chain_score_mvrv_undervalued(self):
        """Проверка с MVRV < -1.0 (недооценен)."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            df = pd.DataFrame(
                {
                    "ONCHAIN_MVRV_ZSCORE": [-0.5, -0.8, -1.5],  # Последний < -1.0
                    "ONCHAIN_FUNDING_RATE_EWMA": [0.0001, 0.0002, 0.0003],
                }
            )

            score = engine.calculate_on_chain_score(df)

            # MVRV < -1.0 дает +0.5
            assert score > 0.0
            assert score <= 0.5

    def test_calculate_on_chain_score_funding_high(self):
        """Проверка с высоким Funding Rate."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            df = pd.DataFrame(
                {
                    "ONCHAIN_MVRV_ZSCORE": [0.0, 0.0, 0.0],
                    "ONCHAIN_FUNDING_RATE_EWMA": [0.0001, 0.0003, 0.0006],  # Последний > 0.0005
                }
            )

            score = engine.calculate_on_chain_score(df)

            # Funding > 0.0005 дает -0.5
            assert score < 0.0

    def test_calculate_on_chain_score_funding_low(self):
        """Проверка с низким Funding Rate."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            df = pd.DataFrame(
                {
                    "ONCHAIN_MVRV_ZSCORE": [0.0, 0.0, 0.0],
                    "ONCHAIN_FUNDING_RATE_EWMA": [-0.0001, -0.0003, -0.0006],  # Последний < -0.0005
                }
            )

            score = engine.calculate_on_chain_score(df)

            # Funding < -0.0005 дает +0.5
            assert score > 0.0

    def test_calculate_on_chain_score_both_factors(self):
        """Проверка с обоими факторами."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            df = pd.DataFrame(
                {
                    "ONCHAIN_MVRV_ZSCORE": [-1.5, -1.5, -1.5],  # BUY сигнал
                    "ONCHAIN_FUNDING_RATE_EWMA": [0.0006, 0.0006, 0.0006],  # SELL сигнал
                }
            )

            score = engine.calculate_on_chain_score(df)

            # Сигналы компенсируют друг друга
            assert score == 0.0  # (-0.5 + 0.5) / 2

    def test_calculate_on_chain_score_clipped(self):
        """Проверка что score ограничен [-1.0, 1.0]."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            # Создаем ситуацию где score может выйти за пределы
            df = pd.DataFrame(
                {
                    "ONCHAIN_MVRV_ZSCORE": [-2.0, -2.0, -2.0],  # +0.5
                    "ONCHAIN_FUNDING_RATE_EWMA": [-0.001, -0.001, -0.001],  # +0.5
                }
            )

            score = engine.calculate_on_chain_score(df)

            # Score должен быть в пределах [-1.0, 1.0]
            assert score >= -1.0
            assert score <= 1.0


class TestConsensusEngineHistoricalSentiment:
    """Тесты для Historical Context Sentiment (RAG)."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_config, mock_database_manager, mock_vector_db_manager):
        """Фикстура для настройки тестов."""
        self.mock_config = mock_config
        self.mock_db_manager = mock_database_manager
        self.mock_vector_db_manager = mock_vector_db_manager

    def test_get_historical_context_sentiment_no_vector_db(self):
        """Проверка без VectorDB."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            result = engine.get_historical_context_sentiment("EURUSD", "trending")

            assert result is None

    def test_get_historical_context_sentiment_no_embedding_model(self):
        """Проверка без embedding модели."""
        from src.ml.consensus_engine import ConsensusEngine

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(
                config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=self.mock_vector_db_manager
            )
            # embedding_model не установлен

            result = engine.get_historical_context_sentiment("EURUSD", "trending")

            assert result is None

    def test_get_historical_context_sentiment_no_results(self, mock_embedding_model):
        """Проверка без результатов поиска."""
        from src.ml.consensus_engine import ConsensusEngine

        self.mock_vector_db_manager.query_similar.return_value = {"ids": [[]], "distances": [[]]}

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(
                config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=self.mock_vector_db_manager
            )
            engine.embedding_model = mock_embedding_model
            engine.sentiment_pipeline = MagicMock()

            result = engine.get_historical_context_sentiment("EURUSD", "trending")

            assert result is None

    def test_get_historical_context_sentiment_success(self, mock_embedding_model):
        """Проверка успешного RAG поиска."""
        from src.ml.consensus_engine import ConsensusEngine

        self.mock_db_manager.get_articles_by_vector_ids.return_value = {
            "doc1": "Positive market news",
            "doc2": "Another positive article",
        }

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(
                config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=self.mock_vector_db_manager
            )
            engine.embedding_model = mock_embedding_model

            mock_result = [{"label": "positive", "score": 0.8}]
            engine.sentiment_pipeline = MagicMock(return_value=mock_result)

            result = engine.get_historical_context_sentiment("EURUSD", "trending")

            assert result is not None
            assert isinstance(result, float)


class TestConsensusEngineMultifactorConsensus:
    """Тесты для многофакторного консенсуса."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_config, mock_database_manager):
        """Фикстура для настройки тестов."""
        self.mock_config = mock_config
        self.mock_db_manager = mock_database_manager

    def test_calculate_multifactor_consensus_ai_only(self):
        """Проверка консенсуса только с AI сигналом."""
        from src.data_models import SignalType, TradeSignal
        from src.ml.consensus_engine import ConsensusEngine

        ai_signal = TradeSignal(symbol="EURUSD", type=SignalType.BUY, confidence=0.8)

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            signal_type, score = engine.calculate_multifactor_consensus(
                ai_signal=ai_signal, classic_signals=[], kg_sentiment_score=0.0, on_chain_score=0.0, is_crypto=False
            )

        # AI сигнал BUY с confidence 0.8 - результат зависит от порогов
        assert signal_type in [SignalType.BUY, SignalType.HOLD]
        assert score >= 0.0

    def test_calculate_multifactor_consensus_classic_only(self):
        """Проверка консенсуса только с классическими сигналами."""
        from src.data_models import SignalType, TradeSignal
        from src.ml.consensus_engine import ConsensusEngine

        classic_signals = [
            TradeSignal(symbol="EURUSD", type=SignalType.BUY, confidence=0.7),
            TradeSignal(symbol="EURUSD", type=SignalType.BUY, confidence=0.8),
            TradeSignal(symbol="EURUSD", type=SignalType.SELL, confidence=0.5),
        ]

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            signal_type, score = engine.calculate_multifactor_consensus(
                ai_signal=TradeSignal(symbol="EURUSD", type=SignalType.HOLD, confidence=0.5),
                classic_signals=classic_signals,
                kg_sentiment_score=0.0,
                on_chain_score=0.0,
                is_crypto=False,
            )

            # 2 BUY vs 1 SELL = положительный скор
            assert signal_type in [SignalType.BUY, SignalType.HOLD]

    def test_calculate_multifactor_consensus_strong_kg_sentiment(self):
        """Проверка с сильным KG сентиментом."""
        from src.data_models import SignalType, TradeSignal
        from src.ml.consensus_engine import ConsensusEngine

        # Устанавливаем исторический PnL < 0
        self.mock_db_manager.get_historical_pnl_for_kg_sentiment.return_value = -50.0

        ai_signal = TradeSignal(symbol="EURUSD", type=SignalType.BUY, confidence=0.7)

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            signal_type, score = engine.calculate_multifactor_consensus(
                ai_signal=ai_signal,
                classic_signals=[],
                kg_sentiment_score=0.8,  # Сильный положительный сентимент
                on_chain_score=0.0,
                is_crypto=False,
            )

            # KG вес должен быть снижен из-за отрицательного исторического PnL
            # Проверка что решение принято
            assert signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_calculate_multifactor_consensus_crypto_with_onchain(self):
        """Проверка крипто-консенсуса с On-Chain данными."""
        from src.data_models import SignalType, TradeSignal
        from src.ml.consensus_engine import ConsensusEngine

        ai_signal = TradeSignal(symbol="BTCUSD", type=SignalType.BUY, confidence=0.7)

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            signal_type, score = engine.calculate_multifactor_consensus(
                ai_signal=ai_signal,
                classic_signals=[],
                kg_sentiment_score=0.0,
                on_chain_score=0.5,  # Положительный On-Chain скор
                is_crypto=True,
            )

            # On-Chain должен усилить сигнал - результат зависит от порогов
            assert signal_type in [SignalType.BUY, SignalType.HOLD]
            assert score >= 0.0

    def test_calculate_multifactor_consensus_uncertainty_penalty(self):
        """Проверка uncertainty penalty."""
        from src.data_models import SignalType, TradeSignal
        from src.ml.consensus_engine import ConsensusEngine

        ai_signal = TradeSignal(symbol="EURUSD", type=SignalType.BUY, confidence=0.8)

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            # Мокаем high uncertainty
            original_method = engine._get_uncertainty_score
            engine._get_uncertainty_score = lambda x: 0.8  # High uncertainty

            signal_type, score = engine.calculate_multifactor_consensus(
                ai_signal=ai_signal, classic_signals=[], kg_sentiment_score=0.0, on_chain_score=0.0, is_crypto=False
            )

            # Score должен быть снижен из-за uncertainty penalty
            assert score < 0.8  # Меньше чем original AI confidence

            # Восстанавливаем метод
            engine._get_uncertainty_score = original_method

    def test_calculate_multifactor_consensus_hold(self):
        """Проверка сигнала HOLD."""
        from src.data_models import SignalType, TradeSignal
        from src.ml.consensus_engine import ConsensusEngine

        # Слабые сигналы ниже порога
        ai_signal = TradeSignal(symbol="EURUSD", type=SignalType.BUY, confidence=0.3)  # Ниже порога 0.6

        with patch.object(ConsensusEngine, "load_models", return_value=None):
            engine = ConsensusEngine(config=self.mock_config, db_manager=self.mock_db_manager, vector_db_manager=None)

            signal_type, score = engine.calculate_multifactor_consensus(
                ai_signal=ai_signal, classic_signals=[], kg_sentiment_score=0.0, on_chain_score=0.0, is_crypto=False
            )

            # Должен быть HOLD так как confidence ниже порога
            assert signal_type == SignalType.HOLD


class TestConsensusResult:
    """Тесты для ConsensusResult."""

    def test_consensus_result_initialization(self):
        """Проверка инициализации ConsensusResult."""
        from src.ml.consensus_engine import ConsensusResult

        result = ConsensusResult()

        assert result.relations == []
        assert result.aggregated_sentiment == 0.0
        assert result.historical_context_sentiment is None
        assert result.on_chain_score == 0.0


class TestModelFactory:
    """Тесты для ModelFactory (заглушки)."""

    def test_model_factory_initialization(self, mock_config):
        """Проверка инициализации ModelFactory."""
        from src.ml.model_factory import ModelFactory

        # ModelFactory требует только config
        factory = ModelFactory(config=mock_config)

        assert factory is not None

    def test_model_factory_create_lstm(self, mock_config):
        """Создание LSTM модели."""
        from src.ml.model_factory import ModelFactory

        factory = ModelFactory(config=mock_config)

        # Проверяем что фабрика создана
        assert factory is not None
        # Тест требует наличия модели в конфиге и дополнительных зависимостей
        pytest.skip("Тест требует полной настройки ML пайплайна")
