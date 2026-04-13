# src/ml/predictor.py
"""
ML Predictor для Genesis Trading System с асинхронным обучением.

Архитектурный сдвиг:
- Было: Инференс и обучение в одном потоке, блокировка GUI
- Стало: Разделение ThreadDomain.ML_INFERENCE vs ML_TRAINING,
         ProcessPool для обучения, hot-swap моделей

Особенности:
- Быстрый инференс в THREAD_POOL (NumPy освобождает GIL)
- Обучение в PROCESS_POOL (полный обход GIL)
- Hot-swap моделей без блокировки трейдинга
- ResourceGovernor для контроля загрузки
"""

import asyncio
import logging
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, Optional

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager
from src.core.resource_governor import ResourceClass, get_governor
from src.core.thread_domains import ThreadDomain, run_in_domain

logger = logging.getLogger(__name__)


class MLPredictor:
    """
    Координатор ML моделей с асинхронным обучением.

    Использование:
        predictor = MLPredictor()

        # Подписка на market ticks
        await event_bus.subscribe("market_tick", predictor.on_market_tick)

        # Запуск обучения в фоне
        asyncio.create_task(predictor.retrain_background("EURUSD", data_path))
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.event_bus = get_event_bus()

        # ProcessPool для обучения (обход GIL)
        self._train_pool = ProcessPoolExecutor(
            max_workers=1, mp_context=mp.get_context("spawn")  # Только одно обучение за раз!  # Важно для Windows
        )

        # Registry моделей
        self._models: Dict[str, Any] = {}
        self._models_lock = asyncio.Lock()

        # Статистика
        self._prediction_count = 0
        self._training_count = 0
        self._training_failures = 0

        logger.info("MLPredictor initialized")

    @run_in_domain(ThreadDomain.ML_INFERENCE)
    async def on_market_tick(self, event: SystemEvent):
        """
        Быстрый инференс на каждый тик.

        Выполняется в THREAD_POOL executor:
        - Не блокирует GUI
        - Имеет timeout 5 сек (из конфигурации домена)
        - Приоритет HIGH
        """
        symbol = event.payload.get("symbol")
        if not symbol:
            return

        model = self._models.get(symbol)
        if not model:
            logger.debug(f"No model for {symbol}, skipping prediction")
            return

        try:
            # Инференс обычно не блокирует GIL (NumPy/ONNX/TorchScript)
            prediction = await asyncio.to_thread(
                self._predict_sync,
                model,
                event.payload,
            )

            self._prediction_count += 1

            await self.event_bus.publish(
                SystemEvent(
                    type="model_prediction",
                    payload={
                        "symbol": symbol,
                        "prediction": prediction,
                        "confidence": 0.85,  # Заглушка, заменить на реальную
                    },
                    priority=EventPriority.HIGH,
                    correlation_id=event.correlation_id,
                )
            )

        except Exception as e:
            logger.error(f"Prediction failed for {symbol}: {e}")

    @run_in_domain(ThreadDomain.ML_TRAINING)
    async def retrain_background(self, symbol: str, data_path: str) -> bool:
        """
        Фоновое переобучение с hot-swap заменой.

        НЕ блокирует основной поток трейдинга!

        Args:
            symbol: Инструмент
            data_path: Путь к данным для обучения

        Returns:
            True если обучение успешно
        """
        gov = get_governor()

        # Проверка ресурсов
        if not gov.can_start(f"train_{symbol}", ResourceClass.MEDIUM):
            logger.warning(f"Training deferred: {symbol} - resources busy")
            return False

        try:
            loop = asyncio.get_event_loop()

            # Подготовка данных
            data = await asyncio.to_thread(
                self._prepare_training_data,
                symbol,
                data_path,
            )

            # Выполнение в отдельном процессе (обход GIL)
            new_model = await loop.run_in_executor(
                self._train_pool,
                self._train_sync_worker,
                symbol,
                data,
                self.config,
            )

            # Валидация перед заменой
            if not self._validate_model(new_model, symbol):
                logger.warning(f"Model validation failed for {symbol}")
                return False

            # Атомарная замена модели (с блокировкой)
            async with self._models_lock:
                self._models[symbol] = new_model

            self._training_count += 1

            # Уведомление системы
            await self.event_bus.publish(
                SystemEvent(
                    type="model_updated",
                    payload={
                        "symbol": symbol,
                        "training_count": self._training_count,
                    },
                    priority=EventPriority.MEDIUM,
                )
            )

            logger.info(f"✅ Model for {symbol} updated successfully")
            return True

        except Exception as e:
            self._training_failures += 1
            logger.error(f"Training failed for {symbol}: {e}", exc_info=True)
            return False

        finally:
            gov.task_finished(f"train_{symbol}")

    def _predict_sync(self, model, data: Dict[str, Any]) -> float:
        """
        Синхронное предсказание.

        Выполняется в THREAD_POOL.
        """
        # Здесь ваша логика извлечения фич и предсказания
        # Пример:
        # features = self._extract_features(data)
        # return model.predict(features)[0]
        return 0.5  # Заглушка

    def _train_sync_worker(self, symbol: str, data: Any, config: Dict) -> Any:
        """
        Синхронная функция обучения — выполняется в отдельном процессе.

        Здесь можно грузить CPU на 100% без блокировки!
        """
        # Здесь ваша логика обучения
        # Пример:
        # model = self._build_model(config)
        # model.fit(data['X'], data['y'])
        # return model
        return {"symbol": symbol, "trained": True}

    def _prepare_training_data(self, symbol: str, data_path: str) -> Any:
        """Подготовка данных для обучения"""
        # Загрузка и предобработка данных
        return {"X": [], "y": []}

    def _validate_model(self, model: Any, symbol: str) -> bool:
        """Валидация модели перед заменой"""
        # Проверка качества модели
        return True

    async def get_model_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Получение информации о модели"""
        async with self._models_lock:
            model = self._models.get(symbol)

        if model is None:
            return None

        return {
            "symbol": symbol,
            "has_model": True,
            "prediction_count": self._prediction_count,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        return {
            "models_loaded": len(self._models),
            "prediction_count": self._prediction_count,
            "training_count": self._training_count,
            "training_failures": self._training_failures,
        }
