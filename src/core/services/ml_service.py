# src/core/services/ml_service.py
"""
ML сервис для Genesis Trading System.

Объединяет:
- FeatureEngineer (генерация признаков)
- ModelFactory (создание/загрузка моделей)
- Обучение и предсказание моделей

Жизненный цикл:
- start(): Загрузка моделей
- stop(): Выгрузка моделей из памяти
- health_check(): Проверка доступности моделей
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.config_models import Settings
from src.core.services.base_service import BaseService
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.db.database_manager import DatabaseManager
from src.ml.feature_engineer import FeatureEngineer
from src.ml.model_factory import ModelFactory

logger = logging.getLogger(__name__)


class MLService(BaseService):
    """
    Сервис машинного обучения.

    Атрибуты:
        feature_engineer: Инженер признаков
        model_factory: Фабрика моделей
        db_manager: Менеджер БД для загрузки моделей
    """

    def __init__(
        self,
        config: Settings,
        db_manager: DatabaseManager,
    ):
        """
        Инициализация ML сервиса.

        Args:
            config: Конфигурация системы
            db_manager: Менеджер базы данных
        """
        super().__init__(config, name="MLService")

        self.db_manager = db_manager

        # Инициализация Knowledge Graph Querier
        self.kg_querier = KnowledgeGraphQuerier(db_manager) if db_manager else None

        # Инициализация FeatureEngineer
        self.feature_engineer = FeatureEngineer(config=config, querier=self.kg_querier)

        # Инициализация ModelFactory
        self.model_factory = ModelFactory(config=config, db_manager=db_manager)

        # Статистика
        self._predictions_count = 0
        self._training_count = 0
        self._models_loaded = 0

        self._healthy = True

    async def start(self) -> None:
        """
        Запуск ML сервиса.

        Загружает последние версии моделей из БД.
        """
        logger.info(f"{self.name}: Запуск ML сервиса...")

        try:
            # Загрузка последних моделей
            await self._safe_execute(self._load_latest_models(), "Загрузка моделей")

            self._running = True
            self._healthy = True

            logger.info(f"{self.name}: Сервис запущен успешно")

        except Exception as e:
            logger.error(f"{self.name}: Ошибка при запуске: {e}", exc_info=True)
            self._healthy = False
            raise

    async def stop(self) -> None:
        """
        Остановка ML сервиса.

        Выгружает модели из памяти для освобождения VRAM.
        """
        logger.info(f"{self.name}: Остановка ML сервиса...")

        try:
            # Очистка кэша моделей
            await self._safe_execute(self._unload_models(), "Выгрузка моделей")

            # Очистка CUDA памяти (если используется GPU)
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.debug(f"{self.name}: CUDA память очищена")
            except Exception:
                pass  # GPU не доступен или не используется

            self._running = False
            self._healthy = False

            logger.info(f"{self.name}: Сервис остановлен")

        except Exception as e:
            logger.error(f"{self.name}: Ошибка при остановке: {e}", exc_info=True)

    def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья сервиса.

        Returns:
            Словарь с информацией о состоянии:
            - status: "healthy" | "unhealthy" | "degraded"
            - models_loaded: int
            - predictions_count: int
            - training_count: int
        """
        # Проверка доступности моделей
        models_available = self._models_loaded > 0

        status = "healthy" if self._healthy and models_available else "degraded"
        if not self._healthy:
            status = "unhealthy"

        return {
            "status": status,
            "models_loaded": self._models_loaded,
            "predictions_count": self._predictions_count,
            "training_count": self._training_count,
        }

    async def _load_latest_models(self) -> int:
        """
        Загрузка последних версий моделей из БД.

        Returns:
            Количество загруженных моделей
        """
        if not self.db_manager:
            logger.warning(f"{self.name}: DB менеджер не доступен, модели не загружены")
            return 0

        # Загрузка последних моделей для каждого символа
        symbols = self.config.SYMBOLS_WHITELIST[:5]  # Ограничим 5 символами для скорости
        loaded_count = 0

        for symbol in symbols:
            try:
                model_components = self.db_manager.load_latest_model(symbol)
                if model_components:
                    loaded_count += 1
                    logger.debug(f"{self.name}: Модель загружена для {symbol}")
            except Exception as e:
                logger.debug(f"{self.name}: Не удалось загрузить модель для {symbol}: {e}")

        self._models_loaded = loaded_count
        logger.info(f"{self.name}: Загружено {loaded_count} моделей")

        return loaded_count

    async def _unload_models(self) -> None:
        """Выгрузка моделей из памяти."""
        self.model_factory.clear_cache()
        self._models_loaded = 0
        logger.info(f"{self.name}: Модели выгружены из памяти")

    # ===========================================
    # Публичные методы для ML операций
    # ===========================================

    async def generate_features(
        self,
        df: pd.DataFrame,
        symbol: str,
        onchain_data: Optional[pd.DataFrame] = None,
        lunarcrush_data: Optional[pd.DataFrame] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Генерация признаков для данных.

        Args:
            df: Исходный DataFrame с данными
            symbol: Символ (e.g., "EURUSD")
            onchain_data: On-chain данные (опционально)
            lunarcrush_data: LunarCrush данные (опционально)

        Returns:
            DataFrame с признаками или None
        """
        if df.empty:
            logger.error(f"{self.name}: Пустой DataFrame для генерации признаков")
            return None

        def _generate():
            return self.feature_engineer.generate_features(
                df=df,
                symbol=symbol,
                onchain_data=onchain_data,
                lunarcrush_data=lunarcrush_data,
            )

        # Выполняем в пуле потоков (CPU-bound операция)
        loop = asyncio.get_event_loop()
        df_featured = await loop.run_in_executor(None, _generate)

        if df_featured is None or df_featured.empty:
            logger.error(f"{self.name}: Не удалось сгенерировать признаки для {symbol}")
            return None

        logger.debug(f"{self.name}: Сгенерировано {len(df_featured.columns)} признаков для {symbol}")
        return df_featured

    async def predict(
        self,
        df: pd.DataFrame,
        symbol: str,
        model_id: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """
        Предсказание модели.

        Args:
            df: DataFrame с признаками
            symbol: Символ
            model_id: ID модели (None = последняя версия)

        Returns:
            Массив предсказаний или None
        """
        self._predictions_count += 1

        # Загрузка модели
        if model_id:
            model_components = self.db_manager.load_model_components_by_id(model_id)
        else:
            model_components = self.db_manager.load_latest_model(symbol)

        if not model_components:
            logger.error(f"{self.name}: Модель не найдена для {symbol}")
            return None

        # Предсказание
        def _predict():
            model = model_components["model"]
            features = model_components["features"]
            x_scaler = model_components["x_scaler"]

            # Подготовка данных
            X = df[features].values

            # Масштабирование
            if x_scaler:
                X = x_scaler.transform(X)

            # Предсказание
            predictions = model.predict(X)

            return predictions

        loop = asyncio.get_event_loop()
        predictions = await loop.run_in_executor(None, _predict)

        logger.debug(f"{self.name}: Выполнено {len(predictions)} предсказаний для {symbol}")
        return predictions

    async def train_model(
        self,
        df: pd.DataFrame,
        symbol: str,
        model_type: str = "LightGBM",
    ) -> Tuple[bool, Optional[str]]:
        """
        Обучение новой модели.

        Args:
            df: DataFrame с данными и признаками
            symbol: Символ
            model_type: Тип модели ("LightGBM", "LSTM", etc.)

        Returns:
            (успех, сообщение об ошибке)
        """
        self._training_count += 1

        try:
            # Обучение в пуле потоков
            loop = asyncio.get_event_loop()

            def _train():
                return self.model_factory.train_model(
                    df=df,
                    symbol=symbol,
                    model_type=model_type,
                )

            model_artifact = await loop.run_in_executor(None, _train)

            if model_artifact:
                # Сохранение модели в БД
                self.db_manager.save_model(
                    symbol=symbol,
                    model=model_artifact["model"],
                    features=model_artifact["features"],
                    x_scaler=model_artifact["x_scaler"],
                    y_scaler=model_artifact["y_scaler"],
                    metrics=model_artifact["metrics"],
                )

                self._models_loaded += 1
                logger.info(f"{self.name}: Модель {model_type} обучена для {symbol}")
                return True, None
            else:
                return False, "Модель не обучена"

        except Exception as e:
            error_msg = f"Ошибка обучения модели: {e}"
            logger.error(f"{self.name}: {error_msg}", exc_info=True)
            return False, error_msg

    async def get_model_metrics(
        self,
        symbol: str,
        model_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Получение метрик модели.

        Args:
            symbol: Символ
            model_id: ID модели (None = последняя)

        Returns:
            Словарь с метриками или None
        """
        if not self.db_manager:
            return None

        if model_id:
            model_stats = self.db_manager.get_model_stats_by_id(model_id)
        else:
            model_stats = self.db_manager.get_latest_model_stats(symbol)

        if not model_stats:
            return None

        return {
            "model_id": model_stats.get("id"),
            "symbol": symbol,
            "model_type": model_stats.get("model_type"),
            "metrics": model_stats.get("metrics", {}),
            "trained_at": model_stats.get("trained_at"),
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"running={self._running}, "
            f"healthy={self._healthy}, "
            f"models={self._models_loaded})"
        )
