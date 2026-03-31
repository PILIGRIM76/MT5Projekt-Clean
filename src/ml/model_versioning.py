# src/ml/model_versioning.py
"""
Система версионирования ML моделей для Genesis Trading System.

Поддерживает:
- Семантическое версионирование (major.minor.patch)
- Champion/Challenger модели
- Метрики производительности
- Откат к предыдущим версиям

Пример использования:
    versioning = ModelVersioning(db_manager)

    # Регистрация новой модели
    versioning.register_model(
        symbol="EURUSD",
        model=model,
        metrics={"sharpe": 1.5, "accuracy": 0.67},
        model_type="LightGBM"
    )

    # Получение champion модели
    champion = versioning.get_champion_model("EURUSD")

    # Сравнение версий
    comparison = versioning.compare_versions("EURUSD")
"""

import json
import logging
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.config_models import Settings
from src.db.database_manager import DatabaseManager, TrainedModel

logger = logging.getLogger(__name__)


@dataclass
class ModelVersion:
    """Информация о версии модели."""

    version: str  # Семантическая версия (e.g., "1.2.3")
    model_id: int
    symbol: str
    model_type: str
    trained_at: datetime
    metrics: Dict[str, float] = field(default_factory=dict)
    is_champion: bool = False
    is_challenger: bool = False
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    training_samples: int = 0
    features: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь."""
        return {
            "version": self.version,
            "model_id": self.model_id,
            "symbol": self.symbol,
            "model_type": self.model_type,
            "trained_at": self.trained_at.isoformat(),
            "metrics": self.metrics,
            "is_champion": self.is_champion,
            "is_challenger": self.is_challenger,
            "hyperparameters": self.hyperparameters,
            "training_samples": self.training_samples,
            "features": self.features,
        }

    @classmethod
    def from_database(cls, db_model: TrainedModel) -> "ModelVersion":
        """Создание из записи БД."""
        metrics = {}
        if db_model.performance_report:
            try:
                metrics = json.loads(db_model.performance_report)
            except json.JSONDecodeError:
                pass

        hyperparameters = {}
        if db_model.hyperparameters_json:
            try:
                hyperparameters = json.loads(db_model.hyperparameters_json)
            except json.JSONDecodeError:
                pass

        features = []
        if db_model.features_json:
            try:
                features = json.loads(db_model.features_json)
            except json.JSONDecodeError:
                pass

        return cls(
            version=f"{db_model.version}.0.0",
            model_id=db_model.id,
            symbol=db_model.symbol,
            model_type=db_model.model_type,
            trained_at=db_model.training_date,
            metrics=metrics,
            is_champion=db_model.is_champion,
            is_challenger=False,  # Нужно устанавливать отдельно
            hyperparameters=hyperparameters,
            training_samples=metrics.get("training_samples", 0),
            features=features,
        )


class ModelVersioning:
    """
    Менеджер версионирования ML моделей.

    Атрибуты:
        db_manager: Менеджер базы данных
        models_directory: Папка для хранения моделей
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        models_directory: str = "ai_models",
    ):
        """
        Инициализация менеджера версионирования.

        Args:
            db_manager: Менеджер базы данных
            models_directory: Папка для хранения файлов моделей
        """
        self.db_manager = db_manager
        self.models_directory = Path(models_directory)
        self.models_directory.mkdir(parents=True, exist_ok=True)

        logger.info(f"ModelVersioning инициализирован (папка: {self.models_directory})")

    def _get_next_version(self, symbol: str, model_type: str) -> str:
        """
        Получение следующей версии для модели.

        Args:
            symbol: Символ
            model_type: Тип модели

        Returns:
            Семантическая версия (e.g., "1.3.0")
        """
        # Получаем последнюю версию
        latest = self.db_manager.load_latest_model(symbol)

        if not latest:
            return "1.0.0"

        # Извлекаем версию из БД
        # В текущей схеме version - это просто int
        # Для семантического версионирования используем свою логику
        existing_versions = self._get_all_versions(symbol, model_type)

        if not existing_versions:
            return "1.0.0"

        # Парсим последнюю версию
        last_version = existing_versions[-1].version
        parts = last_version.split(".")

        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0

            # Инкрементируем minor версию
            return f"{major}.{minor + 1}.0"
        except (ValueError, IndexError):
            return "1.0.0"

    def _get_all_versions(self, symbol: str, model_type: Optional[str] = None) -> List[ModelVersion]:
        """
        Получение всех версий модели для символа.

        Args:
            symbol: Символ
            model_type: Тип модели (None = все типы)

        Returns:
            Список версий, отсортированный по дате
        """
        from sqlalchemy import and_

        session = self.db_manager.Session()
        try:
            query = session.query(TrainedModel).filter(TrainedModel.symbol == symbol)

            if model_type:
                query = query.filter(TrainedModel.model_type == model_type)

            query = query.order_by(TrainedModel.trained_at.desc())

            db_models = query.all()
            versions = [ModelVersion.from_database(m) for m in db_models]

            # Устанавливаем challenger флаг
            if versions:
                # Первая не-champion модель — challenger
                for v in versions[1:]:
                    if not v.is_champion:
                        v.is_challenger = True
                        break

            return versions
        finally:
            session.close()

    def register_model(
        self,
        symbol: str,
        model: Any,
        model_type: str,
        features: List[str],
        x_scaler: Any,
        y_scaler: Any,
        metrics: Dict[str, float],
        hyperparameters: Optional[Dict[str, Any]] = None,
    ) -> ModelVersion:
        """
        Регистрация новой версии модели.

        Args:
            symbol: Символ
            model: Объект модели
            model_type: Тип модели (e.g., "LightGBM", "LSTM")
            features: Список признаков
            x_scaler: Скейлер признаков
            y_scaler: Скейлер целевой переменной
            metrics: Метрики производительности
            hyperparameters: Гиперпараметры модели

        Returns:
            Информация о версии
        """
        # Получаем следующую версию
        version = self._get_next_version(symbol, model_type)

        logger.info(f"Регистрация модели {symbol} {model_type} v{version}")

        # Сохраняем модель в БД через существующий метод
        self.db_manager.save_model(
            symbol=symbol,
            model=model,
            features=features,
            x_scaler=x_scaler,
            y_scaler=y_scaler,
            metrics=metrics,
            model_type=model_type,
            hyperparameters=hyperparameters or {},
        )

        # Получаем последнюю сохранённую модель
        latest = self.db_manager.load_latest_model(symbol)

        if not latest:
            raise ValueError("Не удалось сохранить модель")

        # Обновляем версию и метрики
        session = self.db_manager.Session()
        try:
            db_model = session.query(TrainedModel).get(latest["id"])

            if db_model:
                # Обновляем версию (семантическую)
                version_parts = version.split(".")
                db_model.version = int(version_parts[0])  # Major версия

                # Сохраняем метрики
                db_model.performance_report = json.dumps(metrics)
                db_model.hyperparameters_json = json.dumps(hyperparameters or {})
                db_model.features_json = json.dumps(features)

                session.commit()

                logger.info(f"Модель {symbol} v{version} сохранена в БД (ID: {db_model.id})")

        finally:
            session.close()

        # Сохраняем файл модели отдельно (для бэкапа)
        self._save_model_file(symbol, version, model, metrics)

        # Создаём объект версии
        model_version = ModelVersion(
            version=version,
            model_id=latest["id"],
            symbol=symbol,
            model_type=model_type,
            trained_at=datetime.now(),
            metrics=metrics,
            is_champion=False,  # По умолчанию не champion
            hyperparameters=hyperparameters or {},
            training_samples=metrics.get("training_samples", 0),
            features=features,
        )

        return model_version

    def _save_model_file(
        self,
        symbol: str,
        version: str,
        model: Any,
        metrics: Dict[str, float],
    ) -> Path:
        """
        Сохранение модели в файл (бэкап).

        Args:
            symbol: Символ
            version: Версия
            model: Объект модели
            metrics: Метрики

        Returns:
            Путь к файлу
        """
        # Создаём директорию для символа
        symbol_dir = self.models_directory / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)

        # Формируем имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sharpe = metrics.get("sharpe_ratio", 0.0)
        filename = f"model_v{version}_{timestamp}_sharpe{sharpe:.2f}.pkl"

        filepath = symbol_dir / filename

        # Сохраняем
        with open(filepath, "wb") as f:
            pickle.dump(
                {
                    "model": model,
                    "version": version,
                    "metrics": metrics,
                    "saved_at": datetime.now().isoformat(),
                },
                f,
            )

        logger.debug(f"Модель сохранена в {filepath}")
        return filepath

    def get_champion_model(self, symbol: str) -> Optional[ModelVersion]:
        """
        Получение champion модели для символа.

        Args:
            symbol: Символ

        Returns:
            Champion модель или None
        """
        versions = self._get_all_versions(symbol)

        for v in versions:
            if v.is_champion:
                logger.info(f"Champion модель для {symbol}: v{v.version} (ID: {v.model_id})")
                return v

        # Если champion нет, возвращаем последнюю
        if versions:
            logger.info(f"Champion не найден, используем последнюю: v{versions[0].version}")
            return versions[0]

        return None

    def promote_to_champion(self, model_id: int) -> bool:
        """
        Повышение модели до champion.

        Args:
            model_id: ID модели

        Returns:
            True если успешно
        """
        session = self.db_manager.Session()
        try:
            # Находим модель
            model = session.query(TrainedModel).get(model_id)

            if not model:
                logger.error(f"Модель с ID {model_id} не найдена")
                return False

            symbol = model.symbol

            # Снимаем champion со всех моделей этого символа
            session.query(TrainedModel).filter(
                TrainedModel.symbol == symbol,
                TrainedModel.is_champion == True,
            ).update({"is_champion": False})

            # Устанавливаем champion
            model.is_champion = True
            session.commit()

            logger.info(f"Модель {symbol} ID:{model_id} повышена до champion")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка повышения до champion: {e}")
            return False
        finally:
            session.close()

    def compare_versions(self, symbol: str, limit: int = 5) -> pd.DataFrame:
        """
        Сравнение версий моделей.

        Args:
            symbol: Символ
            limit: Количество версий для сравнения

        Returns:
            DataFrame с метриками версий
        """
        versions = self._get_all_versions(symbol)[:limit]

        if not versions:
            return pd.DataFrame()

        # Создаём таблицу сравнения
        data = []
        for v in versions:
            row = {
                "version": v.version,
                "model_id": v.model_id,
                "model_type": v.model_type,
                "trained_at": v.trained_at.strftime("%Y-%m-%d %H:%M"),
                "is_champion": v.is_champion,
                "is_challenger": v.is_challenger,
                "training_samples": v.training_samples,
            }

            # Добавляем метрики
            for key, value in v.metrics.items():
                if isinstance(value, (int, float)):
                    row[f"metric_{key}"] = round(value, 4)

            data.append(row)

        df = pd.DataFrame(data)

        # Сортировка по дате
        if not df.empty:
            df = df.sort_values("trained_at", ascending=False).reset_index(drop=True)

        return df

    def rollback_to_version(self, model_id: int) -> bool:
        """
        Откат к предыдущей версии.

        Args:
            model_id: ID модели для отката

        Returns:
            True если успешно
        """
        return self.promote_to_champion(model_id)

    def get_version_history(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Получение истории версий.

        Args:
            symbol: Символ

        Returns:
            Список версий
        """
        versions = self._get_all_versions(symbol)
        return [v.to_dict() for v in versions]

    def cleanup_old_models(
        self,
        symbol: str,
        keep_count: int = 10,
        min_age_days: int = 30,
    ) -> int:
        """
        Очистка старых моделей.

        Args:
            symbol: Символ
            keep_count: Сколько последних версий сохранить
            min_age_days: Минимальный возраст для удаления

        Returns:
            Количество удалённых моделей
        """
        versions = self._get_all_versions(symbol)

        if len(versions) <= keep_count:
            logger.info(f"Модели {symbol}: сохранено {len(versions)} версий (порог: {keep_count})")
            return 0

        # Не удаляем champion
        versions_to_delete = [v for v in versions[keep_count:] if not v.is_champion]

        deleted_count = 0
        session = self.db_manager.Session()

        try:
            for v in versions_to_delete:
                # Проверяем возраст
                age = datetime.now() - v.trained_at
                if age.days < min_age_days:
                    continue

                # Удаляем из БД
                model = session.query(TrainedModel).get(v.model_id)
                if model:
                    session.delete(model)
                    deleted_count += 1
                    logger.info(f"Удалена старая модель {symbol} v{v.version} (ID: {v.model_id})")

            session.commit()
            logger.info(f"Очистка {symbol}: удалено {deleted_count} моделей")

        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка очистки моделей: {e}")

        finally:
            session.close()

        return deleted_count
