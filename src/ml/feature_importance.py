# src/ml/feature_importance.py
"""
Отслеживание важности признаков (Feature Importance) для ML моделей.

Поддерживает:
- Feature importance для LightGBM
- SHAP значения
- Permutation importance
- Временные ряды важности
- Стабильность признаков

Пример использования:
    tracker = FeatureImportanceTracker(db_manager)

    # Для LightGBM
    importance = tracker.compute_lgb_importance(model, features)

    # SHAP анализ
    shap_values = tracker.compute_shap_values(model, X_test)

    # Сохранение в БД
    tracker.save_importance("EURUSD", importance, model_id=42)

    # Получение истории
    history = tracker.get_importance_history("EURUSD")
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.config_models import Settings
from src.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class FeatureImportanceTracker:
    """
    Трекер важности признаков.

    Атрибуты:
        db_manager: Менеджер базы данных
        config: Конфигурация
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        config: Optional[Settings] = None,
    ):
        """
        Инициализация трекера.

        Args:
            db_manager: Менеджер базы данных
            config: Конфигурация
        """
        self.db_manager = db_manager
        self.config = config

        # Кэш для SHAP
        self._shap_cache = {}

        logger.info("FeatureImportanceTracker инициализирован")

    def compute_lgb_importance(
        self,
        model: Any,
        features: List[str],
        importance_type: str = "gain",
    ) -> Dict[str, float]:
        """
        Вычисление важности признаков для LightGBM.

        Args:
            model: Обученная модель LightGBM
            features: Список признаков
            importance_type: Тип важности ("gain", "split", "weight")

        Returns:
            Словарь {feature: importance}
        """
        try:
            # Получаем важность из модели
            importance = model.feature_importance(importance_type=importance_type)

            # Создаём словарь
            importance_dict = dict(zip(features, importance))

            # Нормализуем (сумма = 1)
            total = sum(importance_dict.values())
            if total > 0:
                importance_dict = {k: v / total for k, v in importance_dict.items()}

            # Сортируем по убыванию
            importance_dict = dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))

            logger.info(f"LightGBM importance вычислена ({importance_type}). " f"Топ-3: {list(importance_dict.items())[:3]}")

            return importance_dict

        except Exception as e:
            logger.error(f"Ошибка вычисления LGB importance: {e}")
            return {}

    def compute_shap_values(
        self,
        model: Any,
        X: np.ndarray,
        features: List[str],
        sample_size: int = 1000,
    ) -> Tuple[np.ndarray, Dict[str, float]]:
        """
        Вычисление SHAP значений.

        Args:
            model: Обученная модель
            X: Данные (features)
            features: Список признаков
            sample_size: Размер выборки для скорости

        Returns:
            (shap_values, mean_shap_importance)
        """
        try:
            import shap

            # Создаём explainer
            if hasattr(model, "booster_"):
                # LightGBM
                explainer = shap.TreeExplainer(model)
            else:
                # Другие модели (медленнее)
                explainer = shap.KernelExplainer(model.predict, X[:100])

            # Вычисляем SHAP значения (выборка для скорости)
            if len(X) > sample_size:
                indices = np.random.choice(len(X), sample_size, replace=False)
                X_sample = X[indices]
            else:
                X_sample = X

            shap_values = explainer.shap_values(X_sample)

            # Для бинарной классификации берём абсолютные значения
            if isinstance(shap_values, list):
                shap_values = np.abs(shap_values[0]).mean(axis=0)
            else:
                shap_values = np.abs(shap_values).mean(axis=0)

            # Средняя важность
            mean_importance = dict(zip(features, shap_values))
            mean_importance = dict(sorted(mean_importance.items(), key=lambda x: x[1], reverse=True))

            logger.info(f"SHAP значения вычислены. Топ-3: {list(mean_importance.items())[:3]}")

            return shap_values, mean_importance

        except ImportError:
            logger.warning("SHAP не установлен. Пропускаем SHAP анализ.")
            return np.array([]), {}
        except Exception as e:
            logger.error(f"Ошибка вычисления SHAP: {e}")
            return np.array([]), {}

    def compute_permutation_importance(
        self,
        model: Any,
        X: np.ndarray,
        y: np.ndarray,
        features: List[str],
        n_repeats: int = 10,
        random_state: int = 42,
    ) -> Dict[str, float]:
        """
        Вычисление Permutation Importance.

        Args:
            model: Обученная модель
            X: Данные (features)
            y: Целевая переменная
            features: Список признаков
            n_repeats: Количество повторений
            random_state: Seed для воспроизводимости

        Returns:
            Словарь {feature: importance}
        """
        try:
            from sklearn.inspection import permutation_importance

            # Вычисляем
            result = permutation_importance(
                model,
                X,
                y,
                n_repeats=n_repeats,
                random_state=random_state,
                n_jobs=-1,
            )

            # Создаём словарь
            importance_dict = dict(zip(features, result.importances_mean))

            # Сортируем
            importance_dict = dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))

            logger.info(f"Permutation importance вычислена. Топ-3: {list(importance_dict.items())[:3]}")

            return importance_dict

        except Exception as e:
            logger.error(f"Ошибка вычисления permutation importance: {e}")
            return {}

    def save_importance(
        self,
        symbol: str,
        importance: Dict[str, float],
        model_id: int,
        importance_type: str = "gain",
    ) -> bool:
        """
        Сохранение важности в БД.

        Args:
            symbol: Символ
            importance: Словарь важности
            model_id: ID модели
            importance_type: Тип важности

        Returns:
            True если успешно
        """
        try:
            # Создаём запись
            from sqlalchemy import (
                Column,
                DateTime,
                Float,
                Integer,
                String,
                UniqueConstraint,
            )
            from sqlalchemy.orm import declarative_base

            Base = declarative_base()

            class FeatureImportance(Base):
                __tablename__ = "feature_importance"

                id = Column(Integer, primary_key=True)
                symbol = Column(String, nullable=False, index=True)
                model_id = Column(Integer, nullable=False, index=True)
                feature_name = Column(String, nullable=False)
                importance = Column(Float, nullable=False)
                importance_type = Column(String, nullable=False)
                created_at = Column(DateTime, default=datetime.utcnow)

                __table_args__ = (UniqueConstraint("symbol", "model_id", "feature_name", name="uq_symbol_model_feature"),)

            # Создаём таблицу если не существует
            Base.metadata.create_all(self.db_manager.engine)

            # Сохраняем
            session = self.db_manager.Session()

            try:
                # Удаляем старую важность для этой модели
                session.query(FeatureImportance).filter(
                    FeatureImportance.symbol == symbol,
                    FeatureImportance.model_id == model_id,
                ).delete()

                # Добавляем новую
                for feature, importance_value in importance.items():
                    fi = FeatureImportance(
                        symbol=symbol,
                        model_id=model_id,
                        feature_name=feature,
                        importance=importance_value,
                        importance_type=importance_type,
                    )
                    session.add(fi)

                session.commit()
                logger.info(f"Сохранено {len(importance)} признаков важности для {symbol}")
                return True

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Ошибка сохранения важности: {e}")
            return False

    def get_importance_history(
        self,
        symbol: str,
        model_id: Optional[int] = None,
        limit: int = 10,
    ) -> pd.DataFrame:
        """
        Получение истории важности признаков.

        Args:
            symbol: Символ
            model_id: ID модели (None = все модели)
            limit: Количество записей

        Returns:
            DataFrame с историей
        """
        from sqlalchemy import Column, DateTime, Float, Integer, String

        Base = declarative_base()

        class FeatureImportance(Base):
            __tablename__ = "feature_importance"

            id = Column(Integer, primary_key=True)
            symbol = Column(String, nullable=False)
            model_id = Column(Integer, nullable=False)
            feature_name = Column(String, nullable=False)
            importance = Column(Float, nullable=False)
            importance_type = Column(String, nullable=False)
            created_at = Column(DateTime, nullable=False)

        session = self.db_manager.Session()

        try:
            query = session.query(FeatureImportance).filter(FeatureImportance.symbol == symbol)

            if model_id:
                query = query.filter(FeatureImportance.model_id == model_id)

            query = query.order_by(FeatureImportance.created_at.desc()).limit(limit)

            records = query.all()

            if not records:
                return pd.DataFrame()

            # Создаём DataFrame
            data = [
                {
                    "model_id": r.model_id,
                    "feature": r.feature_name,
                    "importance": r.importance,
                    "type": r.importance_type,
                    "date": r.created_at,
                }
                for r in records
            ]

            df = pd.DataFrame(data)

            # Группировка по признакам
            if not df.empty:
                df = df.pivot_table(
                    index="feature",
                    columns="model_id",
                    values="importance",
                    fill_value=0,
                )

            return df

        finally:
            session.close()

    def get_top_features(
        self,
        symbol: str,
        top_n: int = 10,
        model_id: Optional[int] = None,
    ) -> List[str]:
        """
        Получение топ-N важных признаков.

        Args:
            symbol: Символ
            top_n: Количество признаков
            model_id: ID модели (None = последняя)

        Returns:
            Список признаков
        """
        history = self.get_importance_history(symbol, model_id)

        if history.empty:
            return []

        # Если pivot таблица - берём последний столбец
        if isinstance(history, pd.DataFrame) and isinstance(history.columns, pd.MultiIndex):
            last_model = history.columns[-1]
            importance = history[last_model]
        elif isinstance(history, pd.DataFrame):
            # Ищем столбец с важностью
            importance_cols = [c for c in history.columns if "importance" in str(c).lower()]
            if importance_cols:
                importance = history[importance_cols[0]]
            else:
                return []
        else:
            return []

        # Сортируем и берём топ
        top_features = importance.nlargest(top_n).index.tolist()

        logger.info(f"Топ-{top_n} признаков для {symbol}: {top_features[:5]}")
        return top_features

    def compute_stability_score(
        self,
        symbol: str,
        feature: str,
        window_size: int = 5,
    ) -> float:
        """
        Вычисление стабильности признака во времени.

        Args:
            symbol: Символ
            feature: Признак
            window_size: Количество моделей для анализа

        Returns:
            Стабильность (0-1, где 1 = очень стабилен)
        """
        history = self.get_importance_history(symbol, limit=window_size)

        if history.empty or feature not in history.index:
            return 0.0

        # Получаем значения важности
        if isinstance(history, pd.DataFrame) and isinstance(history.columns, pd.MultiIndex):
            values = []
            for col in history.columns:
                val = history.loc[feature, col] if feature in history.index else None
                if val is not None:
                    values.append(val)
        else:
            values = history.loc[feature].tolist() if feature in history.index else []

        if len(values) < 2:
            return 1.0  # Мало данных

        # Вычисляем стабильность как обратную величину от коэффициента вариации
        values = np.array(values)
        mean = np.mean(values)
        std = np.std(values)

        if mean == 0:
            return 0.0

        cv = std / mean  # Коэффициент вариации

        # Преобразуем в стабильность (0-1)
        stability = 1.0 / (1.0 + cv)

        logger.debug(f"Стабильность {feature}: {stability:.3f} (CV: {cv:.3f})")
        return stability

    def analyze_feature_drift(
        self,
        symbol: str,
        feature: str,
        threshold: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Анализ дрейфа важности признака.

        Args:
            symbol: Символ
            feature: Признак
            threshold: Порог для обнаружения дрейфа

        Returns:
            Результаты анализа
        """
        history = self.get_importance_history(symbol, limit=10)

        if history.empty or feature not in history.index:
            return {"drift_detected": False, "reason": "No data"}

        # Получаем значения
        if isinstance(history, pd.DataFrame):
            importance_cols = [c for c in history.columns if "importance" in str(c).lower()]
            if importance_cols:
                values = history.loc[feature, importance_cols[0]].tolist()
            else:
                return {"drift_detected": False, "reason": "No importance column"}
        else:
            return {"drift_detected": False, "reason": "Invalid history format"}

        if len(values) < 3:
            return {"drift_detected": False, "reason": "Not enough data"}

        # Сравниваем последние 3 значения с предыдущими
        recent = np.mean(values[-3:])
        previous = np.mean(values[:-3])

        if previous == 0:
            change_ratio = abs(recent) if recent != 0 else 0
        else:
            change_ratio = abs(recent - previous) / abs(previous)

        drift_detected = change_ratio > threshold

        result = {
            "drift_detected": drift_detected,
            "change_ratio": round(change_ratio, 3),
            "recent_avg": round(recent, 4),
            "previous_avg": round(previous, 4),
            "threshold": threshold,
        }

        if drift_detected:
            logger.warning(
                f"Обнаружен дрейф признака {feature}: " f"{previous:.4f} -> {recent:.4f} ({change_ratio:.1%} изменение)"
            )

        return result
