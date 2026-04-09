"""
Memory utilities — оптимизация потребления памяти для TradingSystem.

Включает:
- SmartModelCache: LRU-кэш моделей с автоматической выгрузкой
- prepare_for_heavy_task(): очистка памяти перед тяжёлыми операциями
- Memory-mapped data loader для больших файлов
"""

import gc
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None


class SmartModelCache:
    """
    LRU-кэш моделей с автоматической выгрузкой неактивных.

    Предотвращает перегрузку памяти при работе с множеством моделей
    для разных символов.

    Использование:
        cache = SmartModelCache(max_cached_models=3, max_ram_gb=2.0)
        model = cache.get("EURUSD", "path/to/model.pt")
    """

    def __init__(self, max_cached_models: int = 3, max_ram_gb: float = 2.0):
        """
        Args:
            max_cached_models: Максимум моделей в кэше
            max_ram_gb: Максимальный объём RAM для кэша
        """
        self.cache: OrderedDict = OrderedDict()
        self.max_models = max_cached_models
        self.max_ram_bytes = max_ram_gb * (1024**3)
        self._load_count = 0
        self._evict_count = 0

    def get(self, symbol: str, model_path: str, loader_func: Any = None) -> Optional[Any]:
        """
        Получает модель из кэша или загружает с диска.

        Args:
            symbol: Символ (ключ кэша)
            model_path: Путь к файлу модели
            loader_func: Функция загрузки (по умолчанию: torch.load или joblib)

        Returns:
            Загруженная модель или None при ошибке
        """
        # Если уже в кэше — переместить в конец (LRU)
        if symbol in self.cache:
            self.cache.move_to_end(symbol)
            logger.debug(f"📦 Модель {symbol} взята из кэша")
            return self.cache[symbol]

        # Если кэш полон — выгрузить наименее используемую
        if len(self.cache) >= self.max_models:
            self._evict_oldest()

        # Загрузить новую
        model = self._load_model(model_path, loader_func)
        if model is None:
            return None

        self.cache[symbol] = model
        self._load_count += 1

        logger.info(
            f"📦 Загружена модель {symbol} "
            f"(в кэше: {len(self.cache)}/{self.max_models}, "
            f"загрузок: {self._load_count}, выгрузок: {self._evict_count})"
        )
        return model

    def evict(self, symbol: str) -> bool:
        """
        Принудительно выгружает модель из кэша.

        Args:
            symbol: Символ для выгрузки

        Returns:
            True если модель была в кэше
        """
        if symbol in self.cache:
            del self.cache[symbol]
            self._cleanup_memory()
            logger.debug(f"🗑️ Модель {symbol} выгружена из кэша")
            return True
        return False

    def clear(self):
        """Очищает весь кэш."""
        self.cache.clear()
        self._cleanup_memory()
        logger.info(f"🧹 Кэш моделей очищен ({len(self.cache)} моделей)")

    def get_stats(self) -> dict:
        """Возвращает статистику кэша."""
        return {
            "cached_models": len(self.cache),
            "max_models": self.max_models,
            "total_loads": self._load_count,
            "total_evictions": self._evict_count,
            "symbols": list(self.cache.keys()),
        }

    def _evict_oldest(self):
        """Выгружает наименее используемую модель."""
        if self.cache:
            oldest_symbol, oldest_model = self.cache.popitem(last=False)
            del oldest_model
            self._evict_count += 1
            logger.debug(f"🗑️ Выгружена модель {oldest_symbol} из кэша (LRU)")

    def _load_model(self, model_path: str, loader_func: Any = None) -> Optional[Any]:
        """Загружает модель с диска через DeviceManager (оптимизировано)."""
        path = Path(model_path)
        if not path.exists():
            logger.warning(f"⚠️ Файл модели не найден: {model_path}")
            return None

        try:
            if loader_func is not None:
                model = loader_func(model_path)
            elif HAS_TORCH and model_path.endswith((".pt", ".pth")):
                # Используем DeviceManager для кэширования
                from src.utils.device_manager import TORCH_AVAILABLE, device_manager

                if TORCH_AVAILABLE:
                    model = device_manager.load_model(model_path, path.stem)
                else:
                    model = torch.load(model_path, map_location="cpu", weights_only=False)
            else:
                import joblib

                model = joblib.load(model_path)

            return model
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки модели {model_path}: {e}")
            return None

    def _cleanup_memory(self):
        """Очищает память после выгрузки моделей."""
        if HAS_TORCH and torch.cuda.is_available():
            torch.cuda.empty_cache()

        gc.collect()


def prepare_for_heavy_task():
    """
    Освобождает память перед ресурсоёмкой операцией (R&D, обучение).

    Вызывать перед:
    - Загрузкой большой модели
    - Запуском R&D цикла
    - Обучением новой модели
    """
    # 1. Очистить кэш PyTorch
    if HAS_TORCH and torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.debug("🧹 CUDA cache очищен")

    # 2. Запустить сборку мусора
    collected = gc.collect()
    logger.debug(f"🧹 GC собрал {collected} объектов")

    # 3. Логируем состояние памяти
    try:
        import psutil

        mem = psutil.virtual_memory()
        free_gb = mem.available / (1024**3)
        logger.info(f"🧹 Память подготовлена: свободно {free_gb:.1f}GB")
    except ImportError:
        logger.info("🧹 Память подготовлена для тяжёлой задачи")


class MappedDataLoader:
    """
    Memory-mapped загрузчик данных для больших файлов.

    Вместо загрузки всего DataFrame в RAM, загружает только нужные срезы.

    Использование:
        loader = MappedDataLoader("data/EURUSD_H1.npy")
        slice_data = loader.get_slice(0, 1000)  # Только первые 1000 строк
    """

    def __init__(self, filepath: str, dtype: np.dtype = np.float32):
        """
        Args:
            filepath: Путь к .npy файлу
            dtype: Тип данных numpy
        """
        self.filepath = filepath
        self.dtype = dtype
        self._memmap = None
        self._shape = None

    def get_slice(self, start_idx: int, end_idx: int) -> np.ndarray:
        """
        Загружает только нужный срез данных с диска.

        Args:
            start_idx: Начальный индекс
            end_idx: Конечный индекс

        Returns:
            numpy array со срезом данных
        """
        if self._memmap is None:
            self._init_memmap()

        return np.array(self._memmap[start_idx:end_idx])

    def get_shape(self) -> tuple:
        """Возвращает форму полного массива."""
        if self._shape is None:
            self._init_memmap()
        return self._shape

    def close(self):
        """Закрывает memory-mapped файл."""
        if self._memmap is not None:
            del self._memmap
            self._memmap = None

    def _init_memmap(self):
        """Инициализирует memory-mapped массив."""
        path = Path(self.filepath)
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {self.filepath}")

        shape = self._infer_shape()
        self._shape = shape
        self._memmap = np.memmap(str(path), dtype=self.dtype, mode="r", shape=shape)

        logger.debug(f"📂 Memory-mapped файл инициализирован: {path.name} {shape}")

    def _infer_shape(self) -> tuple:
        """Определяет размер файла → форму массива."""
        size = os.path.getsize(self.filepath)
        item_size = np.dtype(self.dtype).itemsize
        items = size // item_size

        # Предполагаем 2D массив (строки, колонки)
        # Для OHLCV данных: [time, open, high, low, close, volume] = 6 колонок
        # Но точное число колонок нужно знать заранее
        # Здесь используем заглушку — в реальном коде нужно передавать n_cols
        n_cols = 6  # По умолчанию
        n_rows = items // n_cols

        return (n_rows, n_cols)

    def __del__(self):
        self.close()
