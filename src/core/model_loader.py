"""
Model Loader — централизованная загрузка AI-моделей.

Поддерживает:
  - Кастомный путь к директории моделей (MODEL_DIR из конфига или env)
  - Несколько форматов: Keras (.h5/.keras), PyTorch (.pt), ONNX (.onnx)
  - Fallback на резервную модель при повреждении основной
  - Валидацию пути при старте (до начала торговли)
  - Docker через переменные окружения (MODEL_DIR=${MODEL_DIR:-/models})
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Расширения файлов по формату
FORMAT_EXTENSIONS: Dict[str, str] = {
    "keras": "h5",
    "keras_v2": "keras",
    "pytorch": "pt",
    "onnx": "onnx",
    "joblib": "joblib",
}


class ModelLoader:
    """Загрузчик моделей с поддержкой кастомных путей и fallback."""

    def __init__(self, config: Any):
        """
        Инициализация загрузчика моделей.

        Args:
            config: Объект конфигурации Settings
        """
        self.config = config
        self._loaded_models: Dict[str, Any] = {}
        self._validated = False

    # ──────────────────── PUBLIC ────────────────────

    def validate_model_dir(self) -> Path:
        """
        Валидирует директорию моделей при старте.

        Returns:
            Path к директории моделей

        Raises:
            FileNotFoundError: Если директория не существует
            ValueError: Если путь не указан
        """
        model_dir = self._resolve_model_dir()

        if not model_dir.exists():
            raise FileNotFoundError(
                f"🚫 Директория моделей не найдена: {model_dir}\n"
                f"   Проверьте MODEL_DIR в конфиге или переменную окружения MODEL_DIR"
            )

        if not model_dir.is_dir():
            raise NotADirectoryError(f"🚫 MODEL_DIR указывает на файл, а не директорию: {model_dir}")

        self._validated = True
        logger.info(f"✅ Директория моделей валидна: {model_dir}")
        return model_dir

    def load_model(
        self,
        model_name: Optional[str] = None,
        use_backup: bool = False,
        force_reload: bool = False,
    ) -> Any:
        """
        Загружает модель с поддержкой fallback.

        Args:
            model_name: Имя модели (без расширения). Если None — используется ACTIVE_MODEL
            use_backup: Загрузить резервную модель
            force_reload: Принудительная перезагрузка (игнорировать кэш)

        Returns:
            Загруженная модель

        Raises:
            FileNotFoundError: Если ни основная, ни резервная модель не найдены
            ValueError: Если формат модели не поддерживается
        """
        name = model_name or (self.config.BACKUP_MODEL if use_backup else self.config.ACTIVE_MODEL)
        cache_key = f"{name}_backup" if use_backup else name

        # Проверяем кэш
        if not force_reload and cache_key in self._loaded_models:
            logger.debug(f"📦 Модель '{name}' загружена из кэша")
            return self._loaded_models[cache_key]

        model_path = self._build_model_path(name)

        # Попытка загрузки основной модели
        try:
            model = self._load_file(model_path)
            self._loaded_models[cache_key] = model
            logger.info(f"✅ Модель загружена: {model_path}")
            return model

        except Exception as primary_error:
            logger.warning(f"⚠️ Ошибка загрузки основной модели '{name}': {primary_error}")

            # Fallback на резервную модель (если ещё не используем её)
            if not use_backup:
                logger.info(f"🔄 Попытка загрузки резервной модели: {self.config.BACKUP_MODEL}")
                try:
                    return self.load_model(model_name=self.config.BACKUP_MODEL, use_backup=True)
                except Exception as backup_error:
                    logger.error(
                        f"🚫 Не удалось загрузить ни основную, ни резервную модель!\n"
                        f"   Основная: {model_path}\n"
                        f"   Резервная: {self.config.BACKUP_MODEL}\n"
                        f"   Ошибка резервной: {backup_error}"
                    )
                    raise

            raise FileNotFoundError(f"🚫 Модель не найдена: {model_path}") from primary_error

    def load_model_safe(self, model_name: Optional[str] = None) -> Optional[Any]:
        """
        Безопасная загрузка модели (без исключений).

        Returns:
            Модель или None при ошибке
        """
        try:
            return self.load_model(model_name=model_name)
        except Exception as e:
            logger.error(f"❌ Безопасная загрузка модели не удалась: {e}")
            return None

    def get_model_path(self, model_name: Optional[str] = None) -> Path:
        """Возвращает полный путь к файлу модели."""
        name = model_name or self.config.ACTIVE_MODEL
        return self._build_model_path(name)

    def list_available_models(self) -> Dict[str, Path]:
        """
        Сканирует директорию моделей и возвращает доступные модели.

        Returns:
            Dict {имя_модели: путь_к_файлу}
        """
        model_dir = self._resolve_model_dir()
        available = {}

        for ext in FORMAT_EXTENSIONS.values():
            for model_file in model_dir.glob(f"*.{ext}"):
                name = model_file.stem
                available[name] = model_file

        return available

    def clear_cache(self, model_name: Optional[str] = None) -> None:
        """Очищает кэш загруженных моделей."""
        if model_name:
            self._loaded_models.pop(model_name, None)
            self._loaded_models.pop(f"{model_name}_backup", None)
        else:
            self._loaded_models.clear()
        logger.info("🧹 Кэш моделей очищен")

    def reload_active_model(self) -> Optional[Any]:
        """
        Перезагружает активную модель (используется после смены чемпионата).

        Returns:
            Загруженная модель или None при ошибке
        """
        old_model = self.config.ACTIVE_MODEL
        logger.info(f"🔄 Перезагрузка активной модели: {old_model}")

        # Очищаем кэш
        self.clear_cache(old_model)

        # Загружаем заново
        return self.load_model(force_reload=True)

    # ──────────────────── PRIVATE ────────────────────

    def _resolve_model_dir(self) -> Path:
        """
        Определяет директорию моделей с приоритетом:
          1. Переменная окружения MODEL_DIR
          2. Конфиг MODEL_DIR
          3. Fallback: DATABASE_FOLDER/ai_models
        """
        # 1. Переменная окружения (Docker support)
        env_model_dir = os.environ.get("MODEL_DIR")
        if env_model_dir:
            return Path(env_model_dir).resolve()

        # 2. Конфиг
        if self.config.MODEL_DIR:
            return Path(self.config.MODEL_DIR).resolve()

        # 3. Fallback на DATABASE_FOLDER/ai_models
        fallback = Path(self.config.DATABASE_FOLDER) / "ai_models"
        logger.info(f"📂 MODEL_DIR не указан, используем fallback: {fallback}")
        return fallback.resolve()

    def _resolve_model_format(self) -> str:
        """Определяет формат модели из конфига или env."""
        env_format = os.environ.get("MODEL_FORMAT")
        if env_format:
            return env_format.lower()
        return self.config.MODEL_FORMAT.lower()

    def _build_model_path(self, model_name: str) -> Path:
        """Строит полный путь к файлу модели."""
        model_dir = self._resolve_model_dir()
        fmt = self._resolve_model_format()

        # Определяем расширение
        ext = FORMAT_EXTENSIONS.get(fmt)
        if not ext:
            raise ValueError(f"🚫 Неподдерживаемый формат модели: {fmt}. Поддерживаемые: {list(FORMAT_EXTENSIONS.keys())}")

        # Проверяем несколько вариантов имени файла
        candidates = [
            model_dir / f"{model_name}.{ext}",  # lstm_v4.h5, EURUSD_model.joblib
        ]

        # Для keras проверяем оба расширения
        if fmt == "keras":
            candidates.append(model_dir / f"{model_name}.keras")

        # Для joblib — проверяем если имя уже содержит _model
        if fmt == "joblib" and "_model" not in model_name:
            candidates.insert(0, model_dir / f"{model_name}_model.{ext}")

        for candidate in candidates:
            if candidate.exists():
                logger.debug(f"📂 Найден файл модели: {candidate}")
                return candidate

        # Возвращаем первый вариант по умолчанию
        return candidates[0]

    def _load_file(self, model_path: Path) -> Any:
        """
        Загружает модель в зависимости от расширения файла.

        Raises:
            FileNotFoundError: Если файл не существует
            ImportError: Если необходимая библиотека не установлена
        """
        if not model_path.exists():
            raise FileNotFoundError(f"Файл модели не найден: {model_path}")

        ext = model_path.suffix.lower()

        # Keras (.h5 или .keras)
        if ext in (".h5", ".keras"):
            return self._load_keras_model(model_path)

        # PyTorch (.pt)
        if ext == ".pt":
            return self._load_pytorch_model(model_path)

        # ONNX (.onnx)
        if ext == ".onnx":
            return self._load_onnx_model(model_path)

        # Joblib (.joblib — sklearn/lightgbm)
        if ext == ".joblib":
            return self._load_joblib_model(model_path)

        raise ValueError(f"🚫 Неподдерживаемое расширение файла: {ext}")

    def _load_keras_model(self, model_path: Path) -> Any:
        """Загрузка Keras модели."""
        try:
            from tensorflow import keras  # type: ignore

            model = keras.models.load_model(str(model_path))
            logger.debug(f"🧠 Keras модель загружена: {model_path}")
            return model
        except ImportError:
            raise ImportError("🚫 Требуется tensorflow: pip install tensorflow")
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки Keras модели: {e}") from e

    def _load_pytorch_model(self, model_path: Path) -> Any:
        """Загрузка PyTorch модели через DeviceManager (оптимизировано)."""
        try:
            from src.utils.device_manager import TORCH_AVAILABLE, device_manager  # type: ignore

            if TORCH_AVAILABLE:
                # Используем DeviceManager с кэшированием и inference_mode
                model = device_manager.load_model(str(model_path), model_path.stem)
                if model is not None:
                    logger.debug(f"🔥 PyTorch модель загружена через DeviceManager: {model_path}")
                    return model
                raise RuntimeError("DeviceManager вернул None")
            else:
                # Fallback без оптимизаций
                import torch  # type: ignore

                model = torch.load(str(model_path), map_location="cpu", weights_only=False)
                logger.debug(f"🔥 PyTorch модель загружена (fallback): {model_path}")
                return model
        except ImportError:
            raise ImportError("🚫 Требуется torch: pip install torch")
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки PyTorch модели: {e}") from e

    def _load_onnx_model(self, model_path: Path) -> Any:
        """Загрузка ONNX модели."""
        try:
            import onnxruntime  # type: ignore

            session = onnxruntime.InferenceSession(str(model_path))
            logger.debug(f"📦 ONNX модель загружена: {model_path}")
            return session
        except ImportError:
            raise ImportError("🚫 Требуется onnxruntime: pip install onnxruntime")
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки ONNX модели: {e}") from e

    def _load_joblib_model(self, model_path: Path) -> Any:
        """Загрузка Joblib модели (sklearn/lightgbm)."""
        try:
            import joblib

            model = joblib.load(model_path)
            logger.debug(f"📊 Joblib модель загружена: {model_path}")
            return model
        except ImportError:
            raise ImportError("🚫 Требуется joblib: pip install joblib")
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки Joblib модели: {e}") from e


# ──────────────────── MODULE-LEVEL HELPERS ────────────────────


def create_model_loader(config: Any) -> ModelLoader:
    """Фабричная функция для создания загрузчика моделей."""
    return ModelLoader(config)


def validate_models_at_startup(config: Any) -> bool:
    """
    Валидирует конфигурацию моделей при старте системы.

    Returns:
        True если всё в порядке, False если есть проблемы
    """
    loader = create_model_loader(config)

    try:
        model_dir = loader.validate_model_dir()
        logger.info(f"✅ Валидация директории моделей: {model_dir}")

        # Проверяем наличие активной модели
        active_path = loader.get_model_path(config.ACTIVE_MODEL)
        if active_path.exists():
            logger.info(f"✅ Активная модель найдена: {active_path}")
        else:
            logger.warning(f"⚠️ Активная модель не найдена: {active_path}")
            backup_path = loader.get_model_path(config.BACKUP_MODEL)
            if backup_path.exists():
                logger.info(f"✅ Резервная модель найдена: {backup_path}")
            else:
                logger.error(f"🚫 Резервная модель также не найдена: {backup_path}")
                return False

        return True

    except Exception as e:
        logger.error(f"❌ Валидация моделей не удалась: {e}")
        return False
