# -*- coding: utf-8 -*-
"""
Тесты для новых ML-модулей (Этап 3).

Покрывает:
- PredictionResult (base)
- LSTMPredictor
- TransformerPredictor
- LightGBMPredictor
- ModelPathConfig
- NewsEnrichmentEngine
- KGSyncPipeline
- PredictiveEngine
- BinanceDataStream
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ============================================================================
# 1. PredictionResult (base.py)
# ============================================================================


class TestPredictionResult:
    """Тесты для структуры PredictionResult."""

    def test_buy_signal(self):
        result = self._make_result(signal=1, confidence=0.85)
        assert result.is_buy is True
        assert result.is_sell is False
        assert result.is_hold is False
        assert result.signal_name == "BUY"
        assert result.confidence == 0.85

    def test_sell_signal(self):
        result = self._make_result(signal=-1, confidence=0.72)
        assert result.is_sell is True
        assert result.is_buy is False
        assert result.signal_name == "SELL"

    def test_hold_signal(self):
        result = self._make_result(signal=0, confidence=0.1)
        assert result.is_hold is True
        assert result.signal_name == "HOLD"

    def test_repr(self):
        result = self._make_result(signal=1, confidence=0.9, model_type="LightGBM")
        repr_str = repr(result)
        assert "BUY" in repr_str
        assert "0.900" in repr_str
        assert "LightGBM" in repr_str

    def test_default_probability(self):
        result = self._make_result(signal=1)
        assert result.probability == {}

    def test_metadata_default(self):
        result = self._make_result(signal=0)
        assert result.metadata == {}

    @staticmethod
    def _make_result(signal=0, confidence=0.5, model_type="Test", **kwargs):
        from src.ml.predictors.base import PredictionResult

        return PredictionResult(
            signal=signal,
            confidence=confidence,
            model_type=model_type,
            **kwargs,
        )


# ============================================================================
# 2. BasePredictor (base.py)
# ============================================================================


class TestBasePredictor:
    """Тесты абстрактного BasePredictor через мок-подкласс."""

    @pytest.fixture
    def mock_predictor(self, tmp_path):
        """Создаёт конкретный подкласс BasePredictor для тестов."""
        from src.ml.predictors.base import BasePredictor, PredictionResult

        class ConcretePredictor(BasePredictor):
            @property
            def model_type(self):
                return "Test"

            def predict(self, data):
                return PredictionResult(signal=1, confidence=0.8, model_type="Test")

            def _load_model(self):
                self.model = MagicMock()

            def _save_model(self, path):
                pass

        return ConcretePredictor(model_path=tmp_path / "test_model.joblib")

    def test_is_loaded_initially_false(self, mock_predictor):
        assert mock_predictor.is_loaded is False

    def test_load_sets_flag(self, mock_predictor):
        assert mock_predictor.load() is True
        assert mock_predictor.is_loaded is True

    def test_load_idempotent(self, mock_predictor):
        mock_predictor.load()
        mock_predictor.load()  # второй вызов не должен падать
        assert mock_predictor.is_loaded is True

    def test_unload(self, mock_predictor):
        mock_predictor.load()
        mock_predictor.unload()
        assert mock_predictor.is_loaded is False
        assert mock_predictor.model is None

    def test_predict_batch(self, mock_predictor):
        mock_predictor.load()
        data = np.random.rand(3, 10)  # 3 сэмпла
        results = mock_predictor.predict_batch(data)
        assert len(results) == 3
        assert all(r.signal == 1 for r in results)

    def test_get_feature_names_empty(self, mock_predictor):
        assert mock_predictor.get_feature_names() == []

    def test_get_feature_names_from_metadata(self, mock_predictor):
        mock_predictor.metadata = {"feature_names": ["a", "b", "c"]}
        assert mock_predictor.get_feature_names() == ["a", "b", "c"]

    def test_get_input_shape_none(self, mock_predictor):
        assert mock_predictor.get_input_shape() is None

    def test_get_input_shape_from_metadata(self, mock_predictor):
        mock_predictor.metadata = {"input_shape": [60, 20]}
        assert mock_predictor.get_input_shape() == (60, 20)

    def test_repr(self, mock_predictor):
        assert "not loaded" in repr(mock_predictor)
        mock_predictor.load()
        assert "loaded" in repr(mock_predictor)


# ============================================================================
# 3. LightGBMPredictor
# ============================================================================


class TestLightGBMPredictor:
    """Тесты LightGBM адаптера."""

    @pytest.fixture
    def predictor(self, tmp_path):
        import joblib
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler

        from src.ml.predictors.lightgbm_predictor import LightGBMPredictor

        model = RandomForestClassifier(n_estimators=10, random_state=42)
        model.fit(np.random.rand(100, 14), np.random.randint(0, 2, 100))

        scaler = StandardScaler()
        scaler.fit(np.random.rand(50, 14))

        model_path = tmp_path / "model.joblib"
        scaler_path = tmp_path / "scaler.joblib"
        meta_path = tmp_path / "metadata.json"

        joblib.dump(model, model_path)
        joblib.dump(scaler, scaler_path)

        meta = {
            "feature_names": [f"f{i}" for i in range(14)],
            "input_dim": 14,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        return LightGBMPredictor(
            model_path=model_path,
            scaler_path=scaler_path,
            metadata_path=meta_path,
        )

    def test_load_success(self, predictor):
        assert predictor.load() is True
        assert predictor.is_loaded is True
        assert predictor.model is not None

    def test_load_file_not_found(self, tmp_path):
        from src.ml.predictors.lightgbm_predictor import LightGBMPredictor

        p = LightGBMPredictor(model_path=tmp_path / "nonexistent.joblib")
        assert p.load() is False  # load() ловит исключение и возвращает False
        assert p.is_loaded is False

    def test_predict_returns_result(self, predictor):
        predictor.load()
        data = np.random.rand(14)
        result = predictor.predict(data)
        assert result.signal in [-1, 0, 1]
        assert 0.0 <= result.confidence <= 1.0
        assert result.model_type == "LightGBM"

    def test_predict_batch(self, predictor):
        predictor.load()
        data = np.random.rand(5, 14)
        results = predictor.predict_batch(data)
        assert len(results) == 5

    def test_get_feature_importance(self, predictor):
        predictor.load()
        importance = predictor.get_feature_importance(top_n=5)
        assert len(importance) == 5
        assert importance[0][1] >= importance[1][1]  # отсортировано

    def test_save_and_reload(self, predictor, tmp_path):
        predictor.load()
        save_path = tmp_path / "saved_model.joblib"
        predictor.save(save_path)
        assert save_path.exists()


# ============================================================================
# 4. LSTMPredictor
# ============================================================================


class TestLSTMPredictor:
    """Тесты LSTM адаптера."""

    @pytest.fixture
    def predictor(self, tmp_path):
        import joblib
        import torch
        from sklearn.preprocessing import StandardScaler

        from src.ml.architectures import SimpleLSTM
        from src.ml.predictors.lstm_predictor import LSTMPredictor

        # Создаём модель той же архитектуры что и SimpleLSTM
        model = SimpleLSTM(input_dim=10, hidden_dim=16, num_layers=1, output_dim=1)
        model.eval()

        model_path = tmp_path / "model.pt"
        torch.save(
            {
                "model_state_dict": model.state_dict(),
                "input_dim": 10,
                "hidden_dim": 16,
                "num_layers": 1,
            },
            model_path,
        )

        scaler = StandardScaler()
        scaler.fit(np.random.rand(50, 10))
        scaler_path = tmp_path / "scaler.joblib"
        joblib.dump(scaler, scaler_path)

        meta_path = tmp_path / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump({"input_dim": 10, "feature_names": [f"f{i}" for i in range(10)]}, f)

        return LSTMPredictor(
            model_path=model_path,
            scaler_path=scaler_path,
            metadata_path=meta_path,
            sequence_length=5,
        )

    def test_load_success(self, predictor):
        assert predictor.load() is True
        assert predictor.is_loaded is True

    def test_load_missing_file(self, tmp_path):
        from src.ml.predictors.lstm_predictor import LSTMPredictor

        p = LSTMPredictor(model_path=tmp_path / "missing.pt")
        assert p.load() is False  # load() ловит исключение и возвращает False

    def test_predict_returns_result(self, predictor):
        predictor.load()
        data = np.random.rand(5, 10)
        result = predictor.predict(data)
        assert result.signal in [-1, 0, 1]
        assert 0.0 <= result.confidence <= 1.0
        assert result.model_type == "LSTM"

    def test_predict_short_sequence_padded(self, predictor):
        predictor.load()
        data = np.random.rand(2, 10)  # короче sequence_length
        result = predictor.predict(data)
        assert result.signal in [-1, 0, 1]

    def test_device_auto(self):
        from src.ml.predictors.lstm_predictor import LSTMPredictor

        p = LSTMPredictor(device="auto")
        # device должен быть cuda или cpu
        assert p.device in ["cuda", "cpu"]

    def test_device_explicit_cpu(self):
        from src.ml.predictors.lstm_predictor import LSTMPredictor

        p = LSTMPredictor(device="cpu")
        assert p.device == "cpu"


# ============================================================================
# 5. TransformerPredictor
# ============================================================================


class TestTransformerPredictor:
    """Тесты Transformer адаптера."""

    @pytest.fixture
    def predictor(self, tmp_path):
        import torch
        import torch.nn as nn

        from src.ml.predictors.transformer_predictor import TransformerPredictor

        class TinyTransformer(nn.Module):
            def __init__(self, inp_dim):
                super().__init__()
                d_model = 16
                self.encoder = nn.Linear(inp_dim, d_model)
                layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=2, dim_feedforward=32, batch_first=True)
                self.transformer_encoder = nn.TransformerEncoder(layer, num_layers=1)
                self.decoder = nn.Linear(d_model, 1)

            def forward(self, x):
                x = torch.clamp(x, -10, 10)
                x = self.encoder(x)
                x = self.transformer_encoder(x)
                out = self.decoder(x[:, -1, :])
                return torch.sigmoid(out)

        model = TinyTransformer(10)
        model_path = tmp_path / "model.pt"
        torch.save({"model_state_dict": model.state_dict(), "input_dim": 10}, model_path)

        return TransformerPredictor(
            model_path=model_path,
            sequence_length=5,
        )

    def test_load_and_predict(self, predictor):
        predictor.load()
        data = np.random.rand(5, 10)
        result = predictor.predict(data)
        assert result.signal in [-1, 0, 1]
        assert result.model_type == "Transformer"


# ============================================================================
# 6. ModelPathConfig
# ============================================================================


class TestModelPathConfig:
    """Тесты менеджера путей к моделям."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Создаёт реальный объект конфига через SimpleNamespace."""
        from types import SimpleNamespace

        db_folder = tmp_path / "database"
        db_folder.mkdir(parents=True, exist_ok=True)
        cfg = SimpleNamespace(
            MODEL_DIR="",
            MODEL_FORMAT="joblib",
            ACTIVE_MODEL="test_model",
            HF_MODELS_CACHE_DIR="",
            DATABASE_FOLDER=str(db_folder),
        )
        return cfg

    def test_default_paths(self, mock_config):
        from src.ml.model_paths import ModelPathConfig

        mpc = ModelPathConfig(mock_config)
        assert mpc.model_dir is not None
        assert mpc.hf_home is not None
        assert mpc.faiss_dir is not None

    def test_env_var_model_dir_takes_priority(self, mock_config, monkeypatch):
        monkeypatch.setenv("MODEL_DIR", "/custom/models")
        from src.ml.model_paths import ModelPathConfig

        mpc = ModelPathConfig(mock_config)
        # Windows может конвертировать /custom/models в \custom\models
        assert "custom" in str(mpc.model_dir)
        assert "models" in str(mpc.model_dir)

    def test_hf_home_env(self, mock_config, monkeypatch):
        monkeypatch.setenv("HF_HOME", "/custom/hf")
        from src.ml.model_paths import ModelPathConfig

        mpc = ModelPathConfig(mock_config)
        assert "custom" in str(mpc.hf_home)
        assert "hf" in str(mpc.hf_home)

    def test_get_model_path(self, mock_config):
        from src.ml.model_paths import ModelPathConfig

        mpc = ModelPathConfig(mock_config)
        path = mpc.get_model_path("EURUSD")
        assert "EURUSD" in str(path)
        assert path.suffix == ".joblib"

    def test_get_scaler_path(self, mock_config):
        from src.ml.model_paths import ModelPathConfig

        mpc = ModelPathConfig(mock_config)
        path = mpc.get_scaler_path("EURUSD")
        assert "EURUSD" in str(path)
        assert "scaler" in str(path)

    def test_get_metadata_path(self, mock_config):
        from src.ml.model_paths import ModelPathConfig

        mpc = ModelPathConfig(mock_config)
        path = mpc.get_metadata_path("EURUSD")
        assert "EURUSD" in str(path)
        assert path.suffix == ".json"

    def test_list_models_empty(self, tmp_path, monkeypatch):
        """list_models() возвращает [] для пустой директории."""
        from types import SimpleNamespace

        from src.ml.model_paths import ModelPathConfig

        # Создаём полностью изолированные директории
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        # Env var MODEL_DIR имеет высший приоритет
        monkeypatch.setenv("MODEL_DIR", str(models_dir))

        cfg = SimpleNamespace(
            MODEL_DIR="",  # пустой — env переопределит
            MODEL_FORMAT="joblib",
            ACTIVE_MODEL="test",
            HF_MODELS_CACHE_DIR="",
            DATABASE_FOLDER=str(db_dir),
        )
        mpc = ModelPathConfig(cfg)

        # Проверяем что env сработал
        assert mpc.model_dir == models_dir, f"Expected {models_dir}, got {mpc.model_dir}"

        models = mpc.list_models()
        assert models == []

    def test_repr(self, mock_config):
        from src.ml.model_paths import ModelPathConfig

        mpc = ModelPathConfig(mock_config)
        assert "model_dir" in repr(mpc)


# ============================================================================
# 7. NewsEnrichmentEngine
# ============================================================================


class TestNewsEnrichment:
    """Тесты обогащения новостей."""

    @pytest.fixture
    def engine(self):
        from src.ml.news_enrichment import NewsEnrichmentEngine

        return NewsEnrichmentEngine()

    def test_init(self, engine):
        assert engine.faiss_index_dir is None
        assert engine._is_initialized is False

    def test_enrich_no_faiss_returns_empty(self, engine):
        context = engine.enrich("EURUSD", hours_back=24)
        assert context.avg_sentiment == 0.0
        assert context.news_count == 0
        assert context.kg_sentiment == 0.0

    def test_enriched_features_returns_vector(self, engine):
        context = engine.enrich("EURUSD")
        features = context.to_features()
        assert features.shape == (6,)
        assert features.dtype == np.float32

    def test_to_features_idempotent(self, engine):
        context = engine.enrich("EURUSD")
        v1 = context.to_features()
        v2 = context.to_features()
        np.testing.assert_array_equal(v1, v2)

    def test_repr(self, engine):
        assert "not initialized" in repr(engine)


# ============================================================================
# 8. KGSyncPipeline
# ============================================================================


class TestKGSyncPipeline:
    """Тесты KG синхронизации."""

    @pytest.fixture
    def pipeline(self):
        from src.data.kg_sync_pipeline import KGSyncPipeline

        return KGSyncPipeline()

    def test_init(self, pipeline):
        assert pipeline._stats["items_processed"] == 0

    def test_process_news_batch_empty(self, pipeline):
        stats = pipeline.process_news_batch([])
        assert stats["entities"] == 0
        assert stats["relations"] == 0

    def test_process_single_news(self, pipeline):
        from datetime import datetime, timezone

        from src.data.unified_news_connector import NewsItem

        news = NewsItem(
            headline="Fed raises interest rates",
            content="The Federal Reserve announced a rate hike affecting EUR and USD.",
            source="newsapi",
            source_name="Reuters",
            url="https://example.com",
            timestamp=datetime.now(timezone.utc),
            symbols=["EURUSD"],
            sentiment=-0.3,
        )

        stats = pipeline.process_news_batch([news])
        assert stats["entities"] > 0  # Fed, EUR, USD и т.д.
        assert stats["relations"] > 0

    def test_extract_entities(self, pipeline):
        from datetime import datetime, timezone

        from src.data.unified_news_connector import NewsItem

        news = NewsItem(
            headline="Bitcoin surges past 100k as Fed cuts rates",
            content="BTC rallies while EUR weakens against USD.",
            source="rss",
            source_name="CoinDesk",
            url="https://example.com",
            timestamp=datetime.now(timezone.utc),
            sentiment=0.7,
        )

        entities = pipeline._extract_entities(news)
        entity_names = [e["name"] for e in entities]
        assert "BTC" in entity_names or "BITCOIN" in entity_names
        assert any("USD" in n for n in entity_names)

    def test_get_stats(self, pipeline):
        stats = pipeline.get_stats()
        assert "items_processed" in stats
        assert "entities_extracted" in stats

    def test_reset_stats(self, pipeline):
        pipeline._stats["items_processed"] = 42
        pipeline.reset_stats()
        assert pipeline._stats["items_processed"] == 0


# ============================================================================
# 9. PredictiveEngine
# ============================================================================


class TestPredictiveEngine:
    """Тесты унифицированного движка предсказаний."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        from types import SimpleNamespace

        db_folder = tmp_path / "database"
        db_folder.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            MODEL_DIR="",
            MODEL_FORMAT="joblib",
            ACTIVE_MODEL="test",
            HF_MODELS_CACHE_DIR="",
            DATABASE_FOLDER=str(db_folder),
            ENTRY_THRESHOLD=0.01,
        )

    def test_init(self, mock_config):
        from src.ml.predictive_engine import PredictiveEngine

        engine = PredictiveEngine(mock_config)
        assert engine._predictors == {}

    def test_predict_no_models_returns_hold(self, mock_config):
        from src.ml.predictive_engine import PredictiveEngine

        engine = PredictiveEngine(mock_config)
        result = engine.predict("EURUSD", np.zeros(10))
        assert result.signal == 0
        assert result.confidence == 0.0

    def test_set_weight(self, mock_config):
        from src.ml.predictive_engine import PredictiveEngine

        engine = PredictiveEngine(mock_config)
        engine.set_weight("LSTM", 0.5)
        assert engine.get_weights()["LSTM"] == 0.5

    def test_get_weights(self, mock_config):
        from src.ml.predictive_engine import PredictiveEngine

        engine = PredictiveEngine(mock_config)
        weights = engine.get_weights()
        assert "LSTM" in weights
        assert "LightGBM" in weights

    def test_get_status_empty(self, mock_config):
        from src.ml.predictive_engine import PredictiveEngine

        engine = PredictiveEngine(mock_config)
        status = engine.get_status()
        assert status == {}

    def test_repr(self, mock_config):
        from src.ml.predictive_engine import PredictiveEngine

        engine = PredictiveEngine(mock_config)
        assert "symbols=0" in repr(engine)


# ============================================================================
# 10. BinanceDataStream
# ============================================================================


class TestBinanceDataStream:
    """Тесты потока данных Binance."""

    @pytest.fixture
    def stream(self):
        from src.data.binance_data_stream import BinanceDataStream

        return BinanceDataStream(testnet=True)

    def test_init_testnet(self, stream):
        assert stream.testnet is True
        assert "testnet" in stream.rest_url

    def test_init_mainnet(self):
        from src.data.binance_data_stream import BinanceDataStream

        s = BinanceDataStream(testnet=False)
        assert "testnet" not in s.rest_url
        assert "api.binance.com" in s.rest_url

    def test_build_ws_url_single(self, stream):
        url = stream.build_ws_url(["btcusdt@kline_1h"])
        assert "btcusdt@kline_1h" in url
        assert "?streams=" not in url  # single stream

    def test_build_ws_url_multiple(self, stream):
        url = stream.build_ws_url(["btcusdt@kline_1h", "ethusdt@ticker"])
        assert "?streams=" in url
        assert "btcusdt@kline_1h" in url
        assert "ethusdt@ticker" in url

    def test_subscribe_kline(self, stream):
        streams = stream.subscribe("kline", ["BTCUSDT", "ETHUSDT"], interval="1h")
        assert len(streams) == 2
        assert "btcusdt@kline_1h" in streams

    def test_subscribe_ticker(self, stream):
        streams = stream.subscribe("ticker", ["BTCUSDT"])
        assert "btcusdt@ticker" in streams

    def test_subscribe_trade(self, stream):
        streams = stream.subscribe("trade", ["BTCUSDT"])
        assert "btcusdt@trade" in streams

    def test_parse_kline_message(self, stream):
        msg = json.dumps(
            {
                "e": "kline",
                "s": "BTCUSDT",
                "k": {
                    "t": 1700000000000,
                    "o": "35000.00",
                    "h": "35500.00",
                    "l": "34800.00",
                    "c": "35200.00",
                    "v": "100.5",
                    "x": True,
                },
            }
        )
        result = stream.parse_ws_message(msg)
        assert result is not None
        assert result["type"] == "kline"
        assert result["symbol"] == "BTCUSDT"
        assert result["is_closed"] is True
        assert result["close"] == 35200.0

    def test_parse_trade_message(self, stream):
        msg = json.dumps(
            {
                "e": "trade",
                "s": "ETHUSDT",
                "p": "2000.00",
                "q": "5.5",
                "T": 1700000000000,
            }
        )
        result = stream.parse_ws_message(msg)
        assert result is not None
        assert result["type"] == "trade"
        assert result["price"] == 2000.0

    def test_parse_ticker_message(self, stream):
        msg = json.dumps(
            {
                "e": "24hrTicker",
                "s": "BTCUSDT",
                "c": "35000.00",
                "h": "36000.00",
                "l": "34000.00",
                "v": "50000.0",
                "P": "2.5",
            }
        )
        result = stream.parse_ws_message(msg)
        assert result is not None
        assert result["type"] == "ticker"
        assert result["price_change_pct"] == 2.5

    def test_parse_invalid_message(self, stream):
        result = stream.parse_ws_message("not json")
        assert result is None

    def test_parse_empty_message(self, stream):
        result = stream.parse_ws_message("{}")
        assert result is None

    def test_repr(self, stream):
        assert "testnet" in repr(stream)

    def test_repr_mainnet(self):
        from src.data.binance_data_stream import BinanceDataStream

        s = BinanceDataStream(testnet=False)
        assert "mainnet" in repr(s)
