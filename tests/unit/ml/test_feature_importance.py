# -*- coding: utf-8 -*-
"""
Тесты для FeatureImportanceTracker.

Проверяет:
- LightGBM importance
- SHAP значения
- Permutation importance
- Стабильность признаков
- Обнаружение дрейфа
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ml.feature_importance import FeatureImportanceTracker

# ===========================================
# Фикстуры
# ===========================================


@pytest.fixture
def mock_db_manager():
    """Мок DatabaseManager."""
    db_manager = MagicMock()
    db_manager.Session = MagicMock()
    db_manager.engine = MagicMock()

    session = MagicMock()
    db_manager.Session.return_value = session

    return db_manager


@pytest.fixture
def feature_tracker(mock_db_manager):
    """Фикстура FeatureImportanceTracker."""
    return FeatureImportanceTracker(db_manager=mock_db_manager)


@pytest.fixture
def sample_lgb_model():
    """Пример LightGBM модели."""
    model = MagicMock()
    model.feature_importance.return_value = np.array([100, 50, 30, 20, 10])
    return model


@pytest.fixture
def sample_data():
    """Пример данных."""
    np.random.seed(42)
    X = np.random.rand(100, 5)
    y = np.random.rand(100)
    return X, y


@pytest.fixture
def sample_features():
    """Пример списка признаков."""
    return ["ATR_14", "RSI_14", "MACD", "EMA_50", "EMA_200"]


# ===========================================
# Тесты compute_lgb_importance
# ===========================================


class TestComputeLGBImportance:
    """Тесты compute_lgb_importance."""

    def test_compute_lgb_importance(self, feature_tracker, sample_lgb_model, sample_features):
        """Тест вычисления LGB importance."""
        importance = feature_tracker.compute_lgb_importance(
            model=sample_lgb_model,
            features=sample_features,
            importance_type="gain",
        )

        assert len(importance) == 5
        assert "ATR_14" in importance
        assert importance["ATR_14"] > importance["EMA_200"]  # Первый важнее последнего

        # Проверка нормализации (сумма = 1)
        assert abs(sum(importance.values()) - 1.0) < 0.001

    def test_compute_lgb_importance_empty(self, feature_tracker, sample_lgb_model):
        """Тест с пустыми признаками."""
        importance = feature_tracker.compute_lgb_importance(
            model=sample_lgb_model,
            features=[],
        )

        assert importance == {}

    def test_compute_lgb_importance_error(self, feature_tracker):
        """Тест обработки ошибок."""
        model = MagicMock()
        model.feature_importance.side_effect = Exception("Test error")

        importance = feature_tracker.compute_lgb_importance(
            model=model,
            features=["ATR"],
        )

        assert importance == {}


# ===========================================
# Тесты compute_shap_values
# ===========================================


class TestComputeSHAPValues:
    """Тесты compute_shap_values."""

    @patch("shap.TreeExplainer")
    def test_compute_shap_values(self, mock_tree_explainer, feature_tracker, sample_lgb_model, sample_data, sample_features):
        """Тест вычисления SHAP значений."""
        X, y = sample_data

        # Мок explainer
        mock_explainer = MagicMock()
        mock_tree_explainer.return_value = mock_explainer
        mock_explainer.shap_values.return_value = np.random.rand(100, 5)

        shap_values, mean_importance = feature_tracker.compute_shap_values(
            model=sample_lgb_model,
            X=X,
            features=sample_features,
            sample_size=100,
        )

        assert len(mean_importance) == 5
        assert "ATR_14" in mean_importance
        mock_tree_explainer.assert_called_once()

    def test_compute_shap_import_error(self, feature_tracker, sample_lgb_model, sample_data, sample_features):
        """Тест когда SHAP не установлен."""
        X, y = sample_data

        # Патчим import shap чтобы вызвать ImportError
        with patch.dict("sys.modules", {"shap": None}):
            shap_values, mean_importance = feature_tracker.compute_shap_values(
                model=sample_lgb_model,
                X=X,
                features=sample_features,
            )

        assert len(shap_values) == 0
        assert mean_importance == {}


# ===========================================
# Тесты compute_permutation_importance
# ===========================================


class TestPermutationImportance:
    """Тесты compute_permutation_importance."""

    @patch("sklearn.inspection.permutation_importance")
    def test_compute_permutation_importance(
        self, mock_perm_importance, feature_tracker, sample_lgb_model, sample_data, sample_features
    ):
        """Тест вычисления Permutation importance."""
        X, y = sample_data

        # Мок результата
        mock_result = MagicMock()
        mock_result.importances_mean = np.array([0.5, 0.3, 0.2, 0.1, 0.05])
        mock_perm_importance.return_value = mock_result

        importance = feature_tracker.compute_permutation_importance(
            model=sample_lgb_model,
            X=X,
            y=y,
            features=sample_features,
            n_repeats=10,
        )

        assert len(importance) == 5
        assert "ATR_14" in importance
        assert importance["ATR_14"] == 0.5
        mock_perm_importance.assert_called_once()

    @patch("sklearn.inspection.permutation_importance")
    def test_compute_permutation_importance_error(
        self, mock_perm_importance, feature_tracker, sample_lgb_model, sample_data, sample_features
    ):
        """Тест обработки ошибок."""
        mock_perm_importance.side_effect = Exception("Test error")

        X, y = sample_data

        importance = feature_tracker.compute_permutation_importance(
            model=sample_lgb_model,
            X=X,
            y=y,
            features=sample_features,
        )

        assert importance == {}


# ===========================================
# Тесты save_importance
# ===========================================


class TestSaveImportance:
    """Тесты save_importance."""

    def test_save_importance(self, feature_tracker, mock_db_manager):
        """Тест сохранения важности."""
        importance = {"ATR_14": 0.5, "RSI_14": 0.3, "MACD": 0.2}

        # Мок создания таблицы
        mock_db_manager.Session.return_value.__enter__ = MagicMock()
        mock_db_manager.Session.return_value.__exit__ = MagicMock()

        result = feature_tracker.save_importance(
            symbol="EURUSD",
            importance=importance,
            model_id=42,
            importance_type="gain",
        )

        assert result is True

    def test_save_importance_error(self, feature_tracker, mock_db_manager):
        """Тест обработки ошибок сохранения."""
        mock_db_manager.Session.side_effect = Exception("DB error")

        importance = {"ATR_14": 0.5}

        result = feature_tracker.save_importance(
            symbol="EURUSD",
            importance=importance,
            model_id=42,
        )

        assert result is False


# ===========================================
# Тесты get_importance_history
# ===========================================


class TestGetImportanceHistory:
    """Тесты get_importance_history."""

    def test_get_importance_history_empty(self, feature_tracker, mock_db_manager):
        """Тест пустой истории."""
        session = mock_db_manager.Session.return_value
        mock_query = MagicMock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        history = feature_tracker.get_importance_history("EURUSD")

        assert history.empty

    def test_get_importance_history_with_data(self, feature_tracker, mock_db_manager):
        """Тест с данными."""
        # Создаём мок запись с правильными атрибутами
        mock_record = type(
            "MockRecord",
            (),
            {
                "model_id": 42,
                "feature_name": "ATR_14",
                "importance": 0.5,
                "importance_type": "gain",
                "created_at": datetime.now(),
            },
        )()

        session = mock_db_manager.Session.return_value
        mock_query = MagicMock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_record]

        history = feature_tracker.get_importance_history("EURUSD")

        assert not history.empty


# ===========================================
# Тесты get_top_features
# ===========================================


class TestGetTopFeatures:
    """Тесты get_top_features."""

    def test_get_top_features(self, feature_tracker, mock_db_manager):
        """Тест получения топ признаков."""
        # Создаём мок запись с правильными атрибутами
        mock_record = type(
            "MockRecord",
            (),
            {
                "model_id": 42,
                "feature_name": "ATR_14",
                "importance": 0.5,
                "importance_type": "gain",
                "created_at": datetime.now(),
            },
        )()

        session = mock_db_manager.Session.return_value
        mock_query = MagicMock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_record]

        top = feature_tracker.get_top_features("EURUSD", top_n=5)

        assert len(top) > 0


# ===========================================
# Тесты compute_stability_score
# ===========================================


class TestComputeStabilityScore:
    """Тесты compute_stability_score."""

    def test_compute_stability_score_stable(self, feature_tracker, mock_db_manager):
        """Тест стабильного признака."""
        # Создаём мок записи
        mock_record = type(
            "MockRecord",
            (),
            {
                "model_id": 42,
                "feature_name": "ATR_14",
                "importance": 0.5,
                "created_at": datetime.now(),
            },
        )()

        session = mock_db_manager.Session.return_value
        mock_query = MagicMock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_record] * 5

        stability = feature_tracker.compute_stability_score(
            symbol="EURUSD",
            feature="ATR_14",
            window_size=5,
        )

        assert 0.0 <= stability <= 1.0

    def test_compute_stability_score_no_data(self, feature_tracker, mock_db_manager):
        """Тест без данных."""
        session = mock_db_manager.Session.return_value
        mock_query = MagicMock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        stability = feature_tracker.compute_stability_score(
            symbol="EURUSD",
            feature="ATR_14",
        )

        assert stability == 0.0


# ===========================================
# Тесты analyze_feature_drift
# ===========================================


class TestAnalyzeFeatureDrift:
    """Тесты analyze_feature_drift."""

    def test_analyze_feature_drift_detected(self, feature_tracker, mock_db_manager):
        """Тест обнаружения дрейфа."""
        # Создаём мок записи с дрейфом
        records = []
        for i in range(6):
            mock_record = type(
                "MockRecord",
                (),
                {
                    "model_id": i,
                    "feature_name": "MACD",
                    "importance": 0.1 if i < 3 else 0.5,  # Резкий рост
                    "created_at": datetime.now(),
                },
            )()
            records.append(mock_record)

        session = mock_db_manager.Session.return_value
        mock_query = MagicMock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = records

        result = feature_tracker.analyze_feature_drift(
            symbol="EURUSD",
            feature="MACD",
            threshold=0.3,
        )

        assert "drift_detected" in result
        assert "change_ratio" in result

    def test_analyze_feature_drift_no_data(self, feature_tracker, mock_db_manager):
        """Тест без данных."""
        session = mock_db_manager.Session.return_value
        mock_query = MagicMock()
        session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        result = feature_tracker.analyze_feature_drift(
            symbol="EURUSD",
            feature="MACD",
        )

        assert result["drift_detected"] is False
        assert "No data" in result.get("reason", "")


# ===========================================
# Интеграционные тесты
# ===========================================


class TestFeatureImportanceIntegration:
    """Интеграционные тесты FeatureImportanceTracker."""

    def test_full_workflow(self, feature_tracker, sample_lgb_model, sample_features):
        """Тест полного рабочего процесса."""
        # 1. Вычисление LGB importance
        importance = feature_tracker.compute_lgb_importance(
            model=sample_lgb_model,
            features=sample_features,
        )

        assert len(importance) == 5
        assert sum(importance.values()) == pytest.approx(1.0, abs=0.01)

        # 2. Проверка что важность отсортирована
        importance_list = list(importance.values())
        assert importance_list == sorted(importance_list, reverse=True)
