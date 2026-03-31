# -*- coding: utf-8 -*-
"""
Тесты для ModelVersioning.

Проверяет:
- Семантическое версионирование
- Champion/Challenger модели
- Откат к предыдущим версиям
- Очистка старых моделей
"""

import json
import pickle
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ml.model_versioning import ModelVersion, ModelVersioning

# ===========================================
# Фикстуры
# ===========================================


@pytest.fixture
def mock_db_manager():
    """Мок DatabaseManager."""
    db_manager = MagicMock()
    db_manager.Session = MagicMock()
    db_manager.engine = MagicMock()

    # Мок сессии
    session = MagicMock()
    db_manager.Session.return_value = session

    # Мок load_latest_model
    db_manager.load_latest_model.return_value = {
        "id": 1,
        "symbol": "EURUSD",
        "model_type": "LightGBM",
        "version": 1,
    }

    # Мок save_model
    db_manager.save_model.return_value = True

    return db_manager


@pytest.fixture
def model_versioning(mock_db_manager, tmp_path):
    """Фикстура ModelVersioning."""
    return ModelVersioning(
        db_manager=mock_db_manager,
        models_directory=str(tmp_path / "models"),
    )


@pytest.fixture
def sample_model():
    """Пример модели (простой класс)."""
    import pickle

    class DummyModel:
        def __init__(self):
            self._coef = 0.5

        def predict(self, X):
            return np.random.rand(len(X))

        def feature_importance(self, importance_type="gain"):
            return np.random.rand(10) * 100

        def __getstate__(self):
            return self.__dict__

        def __setstate__(self, state):
            self.__dict__.update(state)

    return DummyModel()


@pytest.fixture
def sample_metrics():
    """Пример метрик."""
    return {
        "sharpe_ratio": 1.5,
        "accuracy": 0.67,
        "profit_factor": 1.8,
        "training_samples": 1000,
    }


# ===========================================
# Тесты ModelVersion (dataclass)
# ===========================================


class TestModelVersion:
    """Тесты ModelVersion dataclass."""

    def test_to_dict(self):
        """Тест конвертации в словарь."""
        version = ModelVersion(
            version="1.2.3",
            model_id=42,
            symbol="EURUSD",
            model_type="LightGBM",
            trained_at=datetime(2026, 3, 31, 12, 0, 0),
            metrics={"sharpe": 1.5},
            is_champion=True,
        )

        result = version.to_dict()

        assert result["version"] == "1.2.3"
        assert result["model_id"] == 42
        assert result["symbol"] == "EURUSD"
        assert result["metrics"]["sharpe"] == 1.5
        assert result["is_champion"] is True
        assert "trained_at" in result

    def test_from_database(self):
        """Тест создания из БД."""
        mock_db_model = MagicMock()
        mock_db_model.id = 42
        mock_db_model.symbol = "EURUSD"
        mock_db_model.model_type = "LightGBM"
        mock_db_model.version = 2
        mock_db_model.training_date = datetime(2026, 3, 31)
        mock_db_model.performance_report = json.dumps({"sharpe": 1.5})
        mock_db_model.hyperparameters_json = json.dumps({"n_estimators": 100})
        mock_db_model.features_json = json.dumps(["ATR", "RSI"])
        mock_db_model.is_champion = True

        version = ModelVersion.from_database(mock_db_model)

        assert version.version == "2.0.0"
        assert version.model_id == 42
        assert version.symbol == "EURUSD"
        assert version.metrics["sharpe"] == 1.5
        assert version.hyperparameters["n_estimators"] == 100
        assert version.features == ["ATR", "RSI"]
        assert version.is_champion is True


# ===========================================
# Тесты ModelVersioning
# ===========================================


class TestModelVersioning:
    """Тесты ModelVersioning."""

    def test_init(self, model_versioning, mock_db_manager):
        """Тест инициализации."""
        assert model_versioning.db_manager == mock_db_manager
        assert model_versioning.models_directory.exists()

    def test_get_next_version_no_existing(self, mock_db_manager):
        """Тест получения следующей версии (нет существующих)."""
        mock_db_manager.load_latest_model.return_value = None

        versioning = ModelVersioning(mock_db_manager)
        version = versioning._get_next_version("EURUSD", "LightGBM")

        assert version == "1.0.0"

    def test_get_next_version_increment(self, model_versioning, mock_db_manager):
        """Тест инкремента версии."""
        # Мок существующих версий
        with patch.object(model_versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [
                ModelVersion(
                    version="1.2.0",
                    model_id=1,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now(),
                )
            ]

            version = model_versioning._get_next_version("EURUSD", "LightGBM")

            assert version == "1.3.0"

    def test_register_model(self, model_versioning, sample_model, sample_metrics):
        """Тест регистрации модели."""
        features = ["ATR_14", "RSI_14", "MACD"]

        with patch.object(model_versioning, "_save_model_file") as mock_save:
            mock_save.return_value = MagicMock()

            version = model_versioning.register_model(
                symbol="EURUSD",
                model=sample_model,
                model_type="LightGBM",
                features=features,
                x_scaler=MagicMock(),
                y_scaler=MagicMock(),
                metrics=sample_metrics,
                hyperparameters={"n_estimators": 100},
            )

            assert version.symbol == "EURUSD"
            assert version.model_type == "LightGBM"
            assert version.metrics == sample_metrics
            assert version.features == features
            assert version.is_champion is False

    def test_save_model_file(self, model_versioning, sample_metrics, tmp_path):
        """Тест сохранения модели в файл."""
        # Используем простой объект вместо модели
        model_data = {"coef": 0.5, "type": "dummy"}

        filepath = model_versioning._save_model_file(
            symbol="EURUSD",
            version="1.0.0",
            model=model_data,
            metrics=sample_metrics,
        )

        assert filepath.exists()
        assert "EURUSD" in str(filepath)
        assert "v1.0.0" in str(filepath)

        # Проверяем содержимое
        with open(filepath, "rb") as f:
            data = pickle.load(f)

        assert "model" in data
        assert "version" in data
        assert "metrics" in data
        assert data["version"] == "1.0.0"

    def test_get_champion_model(self, model_versioning):
        """Тест получения champion модели."""
        # Мок версий
        with patch.object(model_versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [
                ModelVersion(
                    version="2.0.0",
                    model_id=2,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now(),
                    is_champion=False,
                ),
                ModelVersion(
                    version="1.5.0",
                    model_id=1,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now() - timedelta(days=30),
                    is_champion=True,
                ),
            ]

            champion = model_versioning.get_champion_model("EURUSD")

            assert champion is not None
            assert champion.is_champion is True
            assert champion.version == "1.5.0"

    def test_get_champion_model_fallback(self, model_versioning):
        """Тест fallback на последнюю модель (нет champion)."""
        with patch.object(model_versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [
                ModelVersion(
                    version="2.0.0",
                    model_id=2,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now(),
                    is_champion=False,
                ),
            ]

            champion = model_versioning.get_champion_model("EURUSD")

            assert champion is not None
            assert champion.version == "2.0.0"

    def test_promote_to_champion(self, model_versioning, mock_db_manager):
        """Тест повышения до champion."""
        session = mock_db_manager.Session.return_value

        # Мок запроса
        mock_model = MagicMock()
        mock_model.symbol = "EURUSD"
        session.query.return_value.get.return_value = mock_model

        result = model_versioning.promote_to_champion(model_id=42)

        assert result is True
        assert mock_model.is_champion is True
        session.commit.assert_called_once()

    def test_promote_to_champion_not_found(self, model_versioning, mock_db_manager):
        """Тест повышения несуществующей модели."""
        session = mock_db_manager.Session.return_value
        session.query.return_value.get.return_value = None

        result = model_versioning.promote_to_champion(model_id=999)

        assert result is False

    def test_compare_versions(self, model_versioning):
        """Тест сравнения версий."""
        with patch.object(model_versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [
                ModelVersion(
                    version="2.0.0",
                    model_id=2,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now(),
                    metrics={"sharpe_ratio": 1.8, "accuracy": 0.70},
                ),
                ModelVersion(
                    version="1.5.0",
                    model_id=1,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now() - timedelta(days=30),
                    metrics={"sharpe_ratio": 1.5, "accuracy": 0.65},
                ),
            ]

            df = model_versioning.compare_versions("EURUSD", limit=5)

            assert not df.empty
            assert len(df) == 2
            assert "version" in df.columns
            assert "metric_sharpe_ratio" in df.columns

    def test_rollback_to_version(self, model_versioning):
        """Тест отката к версии."""
        with patch.object(model_versioning, "promote_to_champion") as mock_promote:
            mock_promote.return_value = True

            result = model_versioning.rollback_to_version(model_id=42)

            assert result is True
            mock_promote.assert_called_once_with(42)

    def test_get_version_history(self, model_versioning):
        """Тест получения истории версий."""
        with patch.object(model_versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [
                ModelVersion(
                    version="2.0.0",
                    model_id=2,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now(),
                ),
            ]

            history = model_versioning.get_version_history("EURUSD")

            assert len(history) == 1
            assert history[0]["version"] == "2.0.0"
            assert isinstance(history[0], dict)

    def test_cleanup_old_models(self, model_versioning, mock_db_manager):
        """Тест очистки старых моделей."""
        session = mock_db_manager.Session.return_value

        # Мок старых версий
        old_version = ModelVersion(
            version="1.0.0",
            model_id=1,
            symbol="EURUSD",
            model_type="LightGBM",
            trained_at=datetime.now() - timedelta(days=60),  # 60 дней назад
            is_champion=False,
        )

        with patch.object(model_versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [
                ModelVersion(
                    version="3.0.0",
                    model_id=3,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now(),
                    is_champion=True,
                ),
                old_version,
            ]

            deleted = model_versioning.cleanup_old_models(
                symbol="EURUSD",
                keep_count=1,
                min_age_days=30,
            )

            assert deleted == 1
            session.delete.assert_called()
            session.commit.assert_called()

    def test_cleanup_keeps_recent(self, model_versioning, mock_db_manager):
        """Тест сохранения недавних моделей."""
        session = mock_db_manager.Session.return_value

        recent_version = ModelVersion(
            version="2.5.0",
            model_id=2,
            symbol="EURUSD",
            model_type="LightGBM",
            trained_at=datetime.now() - timedelta(days=10),  # 10 дней назад
            is_champion=False,
        )

        with patch.object(model_versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [
                ModelVersion(
                    version="3.0.0",
                    model_id=3,
                    symbol="EURUSD",
                    model_type="LightGBM",
                    trained_at=datetime.now(),
                    is_champion=True,
                ),
                recent_version,
            ]

            deleted = model_versioning.cleanup_old_models(
                symbol="EURUSD",
                keep_count=2,
                min_age_days=30,
            )

            assert deleted == 0  # Ничего не удалено (мало моделей)


# ===========================================
# Интеграционные тесты
# ===========================================


class TestModelVersioningIntegration:
    """Интеграционные тесты ModelVersioning."""

    def test_full_lifecycle(self, mock_db_manager, tmp_path, sample_model, sample_metrics):
        """Тест полного жизненного цикла."""
        versioning = ModelVersioning(mock_db_manager, str(tmp_path / "models"))

        # 1. Регистрация версии 1.0.0
        with patch.object(versioning, "_save_model_file"):
            with patch.object(versioning, "_get_all_versions") as mock_get:
                mock_get.return_value = []  # Нет существующих версий
                v1 = versioning.register_model(
                    symbol="EURUSD",
                    model=sample_model,
                    model_type="LightGBM",
                    features=["ATR"],
                    x_scaler=MagicMock(),
                    y_scaler=MagicMock(),
                    metrics=sample_metrics,
                )

        assert v1.version == "1.0.0"

        # 2. Регистрация версии 1.1.0
        with patch.object(versioning, "_save_model_file"):
            with patch.object(versioning, "_get_all_versions") as mock_get:
                mock_get.return_value = [v1]  # Одна существующая версия
                v2 = versioning.register_model(
                    symbol="EURUSD",
                    model=sample_model,
                    model_type="LightGBM",
                    features=["ATR"],
                    x_scaler=MagicMock(),
                    y_scaler=MagicMock(),
                    metrics={**sample_metrics, "sharpe_ratio": 1.8},
                )

        assert v2.version == "1.1.0"

        # 3. Повышение до champion
        with patch.object(versioning, "promote_to_champion") as mock_promote:
            mock_promote.return_value = True
            versioning.promote_to_champion(v2.model_id)

        # 4. Получение champion
        with patch.object(versioning, "_get_all_versions") as mock_get:
            mock_get.return_value = [v2, v1]
            champion = versioning.get_champion_model("EURUSD")

        assert champion is not None
