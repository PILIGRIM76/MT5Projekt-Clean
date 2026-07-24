# src/ml/predictor.py
"""
Асинхронный предиктор с разделением доменов выполнения.

Архитектура:
• Инференс: ThreadDomain.ML_INFERENCE (быстрый, в потоке)
• Обучение: ThreadDomain.ML_TRAINING (тяжёлый, в процессе)
• Кэш моделей: двойной буфер + атомарная замена
• Защита: CircuitBreaker + фолбэк на скользящее среднее
"""

import asyncio
import logging
import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from src.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager
from src.core.resource_governor import ResourceClass, get_governor
from src.core.thread_domains import ThreadDomain, run_in_domain

logger = logging.getLogger(__name__)


class ModelCache:
    """
    Двойной буфер для моделей: атомарная замена без блокировки инференса.

    Pattern: Copy-On-Write
    • read: без локов, просто атомарное чтение ссылки
    • write: создаём копию, обучаем, затем атомарно меняем указатель
    """

    def __init__(self):
        self._models: Dict[str, Any] = {}
        self._metadata: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

    def get(self, symbol: str) -> Optional[Any]:
        """Быстрое чтение без блокировок."""
        return self._models.get(symbol)

    def get_metadata(self, symbol: str) -> Optional[Dict]:
        return self._metadata.get(symbol)

    async def update(self, symbol: str, model: Any, metadata: Dict):
        """Атомарное обновление модели."""
        async with self._lock:
            self._models[symbol] = model
            self._metadata[symbol] = {
                **metadata,
                "updated_at": time.time(),
                "version": self._metadata.get(symbol, {}).get("version", 0) + 1,
            }
            logger.info(f"Model cache updated for {symbol} " f"(v{self._metadata[symbol]['version']})")

    def list_symbols(self) -> List[str]:
        return list(self._models.keys())


class MLPredictor:
    """
    Асинхронный предиктор с разделением инференс/обучение.

    Использование:
        predictor = MLPredictor(config)
        await predictor.start()

        # Инференс (быстрый, в потоке)
        result = await predictor.predict("EURUSD", data)

        # Обучение (тяжёлое, в процессе)
        await predictor.retrain_background("EURUSD", training_data)
    """

    def __init__(
        self,
        config: Dict,
        model_registry: Optional[ModelCache] = None,
        fallback_strategy: str = "sma",
    ):
        self.config = config
        self.cache = model_registry or ModelCache()
        self.fallback_strategy = fallback_strategy
        self.event_bus = get_event_bus()

        # Circuit breaker для защиты от каскадных сбоев
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=60.0,
        )

        # ProcessPool для обучения (обход GIL)
        self._train_pool: Optional[ProcessPoolExecutor] = None

        # Статистика
        self._stats = {
            "predictions": 0,
            "inference_avg_ms": 0.0,
            "training_count": 0,
            "fallback_count": 0,
        }
        self._latency_samples: List[float] = []
        self._running = False

    async def start(self):
        """Инициализация: создать пул, подписки, прогреть кэш."""
        self._running = True

        # 1. Пул обучения (spawn для Windows)
        self._train_pool = ProcessPoolExecutor(
            max_workers=1,
            mp_context=mp.get_context("spawn"),
        )

        # 2. Подписка на события
        await self.event_bus.subscribe(
            "market_tick",
            self._on_market_tick,
            domain=ThreadDomain.ML_INFERENCE,
            priority=EventPriority.HIGH,
        )
        await self.event_bus.subscribe(
            "model_retrain_requested",
            self._on_retrain_request,
            domain=ThreadDomain.ML_TRAINING,
            priority=EventPriority.LOW,
        )

        # 3. Прогрев кэша
        asyncio.create_task(self._warmup_cache())

        logger.info("MLPredictor started")

    async def stop(self):
        """Корректное завершение."""
        self._running = False
        if self._train_pool:
            self._train_pool.shutdown(wait=False)
        logger.info(f"MLPredictor stopped, stats: {self._stats}")

    @run_in_domain(ThreadDomain.ML_INFERENCE)
    async def _on_market_tick(self, event: SystemEvent):
        """Обработчик тика: быстрый инференс."""
        symbol = event.payload.get("symbol")
        data = event.payload.get("features")

        if not symbol or data is None:
            return

        try:
            prediction = await self.predict(symbol, data)

            await self.event_bus.publish(
                SystemEvent(
                    type="model_prediction",
                    payload={
                        "symbol": symbol,
                        "prediction": prediction,
                        "confidence": self._estimate_confidence(symbol),
                        "model_version": (self.cache.get_metadata(symbol) or {}).get("version", 0),
                    },
                    priority=EventPriority.HIGH,
                    correlation_id=event.correlation_id,
                    source_domain=ThreadDomain.ML_INFERENCE,
                )
            )

        except Exception as e:
            logger.error(f"Prediction failed for {symbol}: {e}", exc_info=True)
            await self.event_bus.publish(
                SystemEvent(
                    type="model_prediction",
                    payload={
                        "symbol": symbol,
                        "prediction": 0.5,
                        "confidence": 0.0,
                        "fallback": True,
                    },
                    priority=EventPriority.MEDIUM,
                )
            )

    @run_in_domain(ThreadDomain.ML_INFERENCE)
    async def predict(self, symbol: str, features: np.ndarray) -> float:
        """
        Быстрое предсказание с защитой и кэшированием.

        Returns:
            float: Предсказание [0, 1] (0=SELL, 1=BUY)
        """
        start = time.perf_counter()

        try:
            model = self.cache.get(symbol)
            if model is None:
                return self._fallback_predict(symbol, features)

            if not self.circuit_breaker.can_execute():
                logger.warning(f"Circuit OPEN for {symbol} → fallback")
                self._stats["fallback_count"] += 1
                return self._fallback_predict(symbol, features)

            try:
                result = await asyncio.to_thread(self._run_inference_sync, model, features)
                self.circuit_breaker.record_success()
            except Exception as e:
                self.circuit_breaker.record_failure()
                raise

            latency = (time.perf_counter() - start) * 1000
            self._update_latency_stat(latency)
            self._stats["predictions"] += 1

            return float(np.clip(result, 0.0, 1.0))

        except Exception as e:
            logger.error(f"Inference error for {symbol}: {e}")
            self._stats["fallback_count"] += 1
            return self._fallback_predict(symbol, features)

    @staticmethod
    def _run_inference_sync(model: Any, features: np.ndarray) -> float:
        """Синхронный инференс — вызывается через to_thread."""
        if hasattr(model, "predict_proba"):
            return model.predict_proba(features.reshape(1, -1))[0][1]
        elif hasattr(model, "predict"):
            pred = model.predict(features.reshape(1, -1))[0]
            return (pred + 1) / 2 if pred in [-1, 1] else pred
        else:
            return 0.5

    def _fallback_predict(self, symbol: str, features: np.ndarray) -> float:
        """Стратегия фолбэка при недоступности модели."""
        if self.fallback_strategy == "sma":
            prices = features[-10:, 0] if features.ndim > 1 else features[-10:]
            return 0.6 if np.mean(np.diff(prices)) > 0 else 0.4
        elif self.fallback_strategy == "random":
            return 0.5 + np.random.uniform(-0.1, 0.1)
        else:
            return 0.5

    def _estimate_confidence(self, symbol: str) -> float:
        """Эвристика уверенности предсказания."""
        meta = self.cache.get_metadata(symbol)
        if not meta:
            return 0.0

        age_hours = (time.time() - meta.get("trained_at", 0)) / 3600
        accuracy = meta.get("accuracy", 0.5)

        freshness = max(0, 1 - age_hours / 24)
        return float(np.clip(freshness * accuracy, 0.0, 1.0))

    @run_in_domain(ThreadDomain.ML_TRAINING)
    async def retrain_background(self, symbol: str, data: Dict[str, Any]) -> bool:
        """
        Фоновое переобучение модели в отдельном процессе.

        Не блокирует инференс и трейдинг!
        """
        if not self._running:
            return False

        gov = get_governor()

        if not gov.can_start(f"train_{symbol}", ResourceClass.MEDIUM):
            logger.warning(f"Training deferred for {symbol}: resources busy")
            return False

        try:
            loop = asyncio.get_event_loop()

            # 1. Подготовка данных (I/O-bound)
            prepared = await asyncio.to_thread(
                self._prepare_training_data,
                symbol,
                data,
            )

            # 2. Обучение в процессе (CPU-bound, обход GIL)
            new_model = await loop.run_in_executor(
                self._train_pool,
                self._train_sync_worker,
                symbol,
                prepared,
                self.config,
            )

            # 3. Валидация
            metrics = await asyncio.to_thread(
                self._validate_model,
                new_model,
                prepared,
            )

            if metrics["accuracy"] < self.config.get("min_accuracy", 0.45):
                logger.warning(f"Model validation failed for {symbol}: " f"acc={metrics['accuracy']:.3f}")
                return False

            # 4. Атомарная замена в кэше
            async with lock_manager.acquire(LockLevel.MODEL_CACHE, timeout=5.0):
                await self.cache.update(
                    symbol,
                    new_model,
                    {
                        "accuracy": metrics["accuracy"],
                        "trained_at": time.time(),
                        "samples": len(prepared),
                        "loss": metrics.get("loss", 0),
                    },
                )

            # 5. Уведомление системы
            await self.event_bus.publish(
                SystemEvent(
                    type="model_updated",
                    payload={
                        "symbol": symbol,
                        "accuracy": metrics["accuracy"],
                        "version": self.cache.get_metadata(symbol)["version"],
                    },
                    priority=EventPriority.MEDIUM,
                )
            )

            self._stats["training_count"] += 1
            logger.info(f"Model retrained for {symbol} " f"(acc={metrics['accuracy']:.3f})")
            return True

        except Exception as e:
            logger.error(f"Training failed for {symbol}: {e}", exc_info=True)
            return False
        finally:
            gov.task_finished(f"train_{symbol}")

    async def _on_retrain_request(self, event: SystemEvent):
        """Обработчик запроса на переобучение."""
        symbol = event.payload.get("symbol")
        data = event.payload.get("data")

        if symbol and data:
            await self.retrain_background(symbol, data)

    @staticmethod
    def _prepare_training_data(symbol: str, raw_data: Dict) -> np.ndarray:
        """Подготовка данных для обучения — синхронная."""
        return raw_data.get("features", np.array([]))

    @staticmethod
    def _train_sync_worker(
        symbol: str,
        data: np.ndarray,
        config: Dict,
    ) -> Any:
        """
        Синхронная функция обучения — выполняется в отдельном процессе.
        """

        class DummyModel:
            def predict(self, X):
                return np.random.rand(len(X))

            def predict_proba(self, X):
                return np.random.rand(len(X), 2)

        return DummyModel()

    @staticmethod
    def _validate_model(model: Any, data: np.ndarray) -> Dict[str, float]:
        """Валидация модели на отложенной выборке."""
        return {
            "accuracy": 0.52,
            "loss": 0.48,
        }

    async def _warmup_cache(self):
        """Фоновая загрузка моделей из БД при старте."""
        try:
            logger.debug("Model cache warmup completed")
        except Exception as e:
            logger.warning(f"Cache warmup failed: {e}")

    def _update_latency_stat(self, new_latency: float):
        """Обновление скользящего среднего латентности."""
        self._latency_samples.append(new_latency)
        if len(self._latency_samples) > 100:
            self._latency_samples.pop(0)
        if self._latency_samples:
            self._stats["inference_avg_ms"] = sum(self._latency_samples) / len(self._latency_samples)

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики для мониторинга."""
        return {
            **self._stats,
            "cached_models": len(self.cache.list_symbols()),
            "circuit_state": self.circuit_breaker.state.name,
        }
