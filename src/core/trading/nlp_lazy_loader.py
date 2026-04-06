# src/core/trading/nlp_lazy_loader.py
"""
Lazy Loading для NLP моделей — экономия ~1GB RAM.

Вместо загрузки всех NLP моделей при старте системы:
- SentenceTransformer (~80MB)
- T5ForConditionalGeneration (~800MB)
- AutoTokenizer

Модели загружаются только при первом использовании и выгружаются
при неактивности.

Экономия: ~880MB RAM при старте, если NLP не используется.
"""

import gc
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LazyNLPModel:
    """
    Обёртка для ленивой загрузки одной NLP модели.

    Атрибуты:
        model_name: Имя модели (например, 'all-MiniLM-L6-v2')
        model_type: Тип модели ('embedding', 'summarization', 'sentiment')
        _model: Загруженная модель (None если не загружена)
        _last_used: Время последнего использования
        _idle_timeout: Таймаут бездействия для выгрузки (секунды)
    """

    def __init__(self, model_name: str, model_type: str, idle_timeout: float = 3600.0):
        self.model_name = model_name
        self.model_type = model_type
        self._model = None
        self._tokenizer = None
        self._last_used = 0
        self._idle_timeout = idle_timeout
        self._lock = threading.Lock()
        self._load_count = 0
        self._unload_count = 0

    @property
    def is_loaded(self) -> bool:
        """Модель загружена в память."""
        return self._model is not None

    @property
    def last_used(self) -> float:
        """Время последнего использования."""
        return self._last_used

    def load(self) -> Any:
        """
        Загрузить модель в память.

        Returns:
            Загруженная модель
        """
        with self._lock:
            if self._model is not None:
                self._last_used = time.time()
                return self._model

            logger.info(f"[NLP Lazy] Загрузка {self.model_type} модели: {self.model_name}")
            start_time = time.time()

            try:
                if self.model_type == "embedding":
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(self.model_name)
                elif self.model_type == "summarization":
                    from transformers import AutoTokenizer, T5ForConditionalGeneration
                    self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                    self._model = T5ForConditionalGeneration.from_pretrained(self.model_name)
                elif self.model_type == "sentiment":
                    from transformers import pipeline
                    self._model = pipeline("sentiment-analysis", model=self.model_name)
                else:
                    raise ValueError(f"Неизвестный тип модели: {self.model_type}")

                elapsed = time.time() - start_time
                self._load_count += 1
                self._last_used = time.time()
                logger.info(f"[NLP Lazy] Модель {self.model_name} загружена за {elapsed:.2f}s")

            except Exception as e:
                logger.error(f"[NLP Lazy] Ошибка загрузки {self.model_name}: {e}")
                raise

            return self._model

    def unload(self) -> None:
        """Выгрузить модель из памяти."""
        with self._lock:
            if self._model is None:
                return

            logger.info(f"[NLP Lazy] Выгрузка {self.model_type} модели: {self.model_name}")
            self._model = None
            self._tokenizer = None
            self._unload_count += 1

            # Принудительная сборка мусора
            gc.collect()

    def get(self) -> Any:
        """
        Получить модель (загрузить если нужно).

        Returns:
            Загруженная модель
        """
        if self._model is None:
            return self.load()
        self._last_used = time.time()
        return self._model

    def get_tokenizer(self) -> Any:
        """Получить токенизатор (загрузить если нужно)."""
        if self._model is None:
            self.load()
        return self._tokenizer

    def check_idle(self) -> bool:
        """
        Проверить неактивность и выгрузить если прошло много времени.

        Returns:
            True если модель была выгружена
        """
        if self._model is None:
            return False

        idle_time = time.time() - self._last_used
        if idle_time > self._idle_timeout:
            logger.info(
                f"[NLP Lazy] Модель {self.model_name} неактивна {idle_time:.0f}s, выгрузка"
            )
            self.unload()
            return True
        return False

    def get_stats(self) -> dict:
        """Получить статистику использования."""
        return {
            "model_name": self.model_name,
            "model_type": self.model_type,
            "is_loaded": self.is_loaded,
            "load_count": self._load_count,
            "unload_count": self._unload_count,
            "last_used": self._last_used,
            "idle_timeout": self._idle_timeout,
        }


class NLPLazyLoader:
    """
    Менеджер ленивой загрузки NLP моделей.

    Управляет несколькими NLP моделями:
    - Embedding модель (SentenceTransformer)
    - Summarization модель (T5)
    - Sentiment модель

    Все модели загружаются только при первом использовании.
    """

    def __init__(self, idle_timeout: float = 3600.0):
        self._models: dict[str, LazyNLPModel] = {}
        self._idle_timeout = idle_timeout
        self._lock = threading.Lock()

    def register_model(self, model_name: str, model_type: str) -> LazyNLPModel:
        """
        Зарегистрировать модель для ленивой загрузки.

        Args:
            model_name: Имя модели (HuggingFace path)
            model_type: Тип модели ('embedding', 'summarization', 'sentiment')

        Returns:
            LazyNLPModel обёртка
        """
        with self._lock:
            key = f"{model_type}:{model_name}"
            if key not in self._models:
                self._models[key] = LazyNLPModel(model_name, model_type, self._idle_timeout)
                logger.info(f"[NLP Lazy] Зарегистрирована модель: {model_name} ({model_type})")
            return self._models[key]

    def get_embedding_model(self, model_name: str = "all-MiniLM-L6-v2") -> Any:
        """
        Получить embedding модель (ленивая загрузка).

        Args:
            model_name: Имя embedding модели

        Returns:
            SentenceTransformer модель
        """
        return self.register_model(model_name, "embedding").get()

    def get_summarization_model(self, model_name: str = "t5-base") -> Any:
        """
        Получить summarization модель (ленивая загрузка).

        Args:
            model_name: Имя summarization модели

        Returns:
            T5ForConditionalGeneration модель
        """
        return self.register_model(model_name, "summarization").get()

    def get_sentiment_model(self, model_name: str = "distilbert-base-uncased-finetuned-sst-2-english") -> Any:
        """
        Получить sentiment модель (ленивая загрузка).

        Args:
            model_name: Имя sentiment модели

        Returns:
            Sentiment pipeline
        """
        return self.register_model(model_name, "sentiment").get()

    def check_all_idle(self) -> int:
        """
        Проверить неактивность всех моделей и выгрузить.

        Returns:
            Количество выгруженных моделей
        """
        unloaded = 0
        with self._lock:
            for model in self._models.values():
                if model.check_idle():
                    unloaded += 1
        return unloaded

    def unload_all(self) -> None:
        """Выгрузить все модели."""
        with self._lock:
            for model in self._models.values():
                model.unload()
        logger.info("[NLP Lazy] Все модели выгружены")

    def get_all_stats(self) -> dict:
        """Получить статистику всех моделей."""
        with self._lock:
            return {
                key: model.get_stats()
                for key, model in self._models.items()
            }

    def get_loaded_count(self) -> int:
        """Количество загруженных моделей."""
        with self._lock:
            return sum(1 for m in self._models.values() if m.is_loaded)

    def get_total_count(self) -> int:
        """Общее количество зарегистрированных моделей."""
        return len(self._models)
