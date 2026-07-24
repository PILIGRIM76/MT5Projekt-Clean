# src/utils/device_manager.py
"""
Device Manager для Genesis Trading System.

Управление CPU-оптимизацией и кэшированием моделей:
- Ограничение потоков для инференса (2) и обучения (4+)
- Включение MKL-DNN для ускорения CPU-инференса на 30-50%
- LRU-кэш моделей (макс 3) для экономии ОЗУ
"""

import logging
import os
import threading
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Проверка доступности PyTorch
try:
    import torch

    TORCH_AVAILABLE = True
    # Проверка корректности установки
    if not hasattr(torch, "set_num_threads"):
        TORCH_AVAILABLE = False
        logger.warning("⚠️ PyTorch установлен некорректно (пустой пакет-заглушка)")
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("⚠️ PyTorch не установлен, DeviceManager работает в режиме без GPU/CPU оптимизации")


class DeviceManager:
    """
    Singleton для управления CPU-оптимизацией и кэшированием моделей.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        if TORCH_AVAILABLE:
            self.device = torch.device("cpu")

            # 🔹 Ограничиваем потоки: 2 для инференса, 4+ для обучения
            torch.set_num_threads(2)
            torch.set_num_interop_threads(2)
            os.environ["OMP_NUM_THREADS"] = "2"
            os.environ["MKL_NUM_THREADS"] = "2"

            # 🔹 Включаем MKL-DNN (ускоряет CPU-инференс на 30-50%)
            if hasattr(torch.backends, "mkldnn") and torch.backends.mkldnn.is_available():
                torch.backends.mkldnn.enabled = True
                logger.info("✅ MKL-DNN ускорение активировано")

            # 🔹 LRU-кэш моделей (макс 3, чтобы не есть ОЗУ)
            self.model_cache = OrderedDict()
            self.max_cache = 3

            logger.info(f"🖥️ CPU настроен: инференс=2 потока, кэш={self.max_cache} моделей")
        else:
            self.device = None
            self.model_cache = OrderedDict()
            self.max_cache = 3
            logger.warning("⚠️ DeviceManager работает без PyTorch оптимизаций")

    def get_device(self) -> "torch.device | None":
        """Возвращает текущее устройство (CPU) или None если PyTorch недоступен."""
        return self.device

    def load_model(self, path: str, symbol: str):
        """
        Загружает модель с кэшированием и eval-режимом.

        Args:
            path: Путь к файлу модели
            symbol: Символ актива для кэширования

        Returns:
            Загруженная модель в eval-режиме или None при ошибке
        """
        if not TORCH_AVAILABLE:
            logger.error("❌ PyTorch недоступен. Невозможно загрузить модель.")
            return None

        if symbol in self.model_cache:
            self.model_cache.move_to_end(symbol)
            logger.debug(f"📦 {symbol} взят из кэша")
            return self.model_cache[symbol]

        try:
            # Загрузка с диска
            checkpoint = torch.load(path, map_location="cpu", weights_only=False)
            model = checkpoint["model"]
            model.eval()  # Отключаем dropout/batchnorm для инференса

            # Вытеснение старой модели
            if len(self.model_cache) >= self.max_cache:
                oldest = next(iter(self.model_cache))
                del self.model_cache[oldest]
                logger.debug(f"🗑️ Выгружена {oldest}")

            self.model_cache[symbol] = model
            logger.info(f"✅ {symbol} загружена (кэш: {len(self.model_cache)}/{self.max_cache})")
            return model
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки модели {path}: {e}")
            return None

    def clear_cache(self):
        """Очищает кэш моделей."""
        self.model_cache.clear()
        logger.debug("🧹 Кэш моделей очищен")


# Глобальный экземпляр (Singleton)
device_manager = DeviceManager()
