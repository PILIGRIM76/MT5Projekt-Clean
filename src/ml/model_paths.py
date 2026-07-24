# -*- coding: utf-8 -*-
"""
src/ml/model_paths.py — Централизованное управление путями к ML-моделям

Отвечает за:
- Определение путей к директориям моделей (активные, backup, чемпионат)
- Настройку HF_HOME (кэш Hugging Face)
- Создание директорий при отсутствии
- Поддержку конфигурации через Settings + env vars
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from src.core.config_models import Settings

logger = logging.getLogger(__name__)

# Константы — расширения файлов моделей
MODEL_EXTENSIONS = {
    "pytorch": [".pt", ".pth"],
    "keras": [".h5", ".keras"],
    "onnx": [".onnx"],
    "joblib": [".joblib", ".pkl"],
    "rl": [".zip"],  # Stable Baselines3 PPO
}


class ModelPathConfig:
    """
    Централизованный менеджер путей к ML-артефактам.

    Приоритет конфигурации:
    1. Переменная окружения MODEL_DIR
    2. settings.MODEL_DIR
    3. {DATABASE_FOLDER}/ai_models
    4. Fallback: F:\ai_models
    """

    def __init__(self, config: Settings):
        self.config = config
        self._model_dir: Optional[Path] = None
        self._hf_home: Optional[Path] = None
        self._faiss_dir: Optional[Path] = None

        # Инициализация
        self._resolve_paths()
        self._ensure_directories()
        self._set_env_vars()

        logger.info(f"[ModelPaths] Модель: {self.model_dir}")
        logger.info(f"[ModelPaths] HF HOME: {self.hf_home}")
        logger.info(f"[ModelPaths] FAISS: {self.faiss_dir}")

    # ===================================================================
    # Публичные свойства
    # ===================================================================

    @property
    def model_dir(self) -> Path:
        """Директория AI-моделей."""
        return self._model_dir

    @property
    def hf_home(self) -> Path:
        """Директория кэша Hugging Face."""
        return self._hf_home

    @property
    def faiss_dir(self) -> Path:
        """Директория FAISS индексов."""
        return self._faiss_dir

    @property
    def rl_models_dir(self) -> Path:
        """Директория RL-моделей (PPO)."""
        return self.model_dir / "rl_models"

    @property
    def championship_dir(self) -> Path:
        """Директория моделей чемпионата."""
        return self.model_dir / "championship"

    @property
    def backup_dir(self) -> Path:
        """Директория резервных копий."""
        return self.model_dir / "backup"

    # ===================================================================
    # Разрешение путей
    # ===================================================================

    def _resolve_paths(self) -> None:
        """Определяет все пути с учётом приоритетов."""
        # --- MODEL_DIR ---
        # 1. Env var
        env_model_dir = os.environ.get("MODEL_DIR")
        if env_model_dir:
            self._model_dir = Path(env_model_dir)
            self._finalize_resolve()
            return

        # 2. Config (проверяем не только truthiness, но и наличие атрибута)
        if hasattr(self.config, "MODEL_DIR") and self.config.MODEL_DIR:
            self._model_dir = Path(self.config.MODEL_DIR)
            self._finalize_resolve()
            return

        # 3. DATABASE_FOLDER/ai_models
        if hasattr(self.config, "DATABASE_FOLDER") and self.config.DATABASE_FOLDER:
            self._model_dir = Path(self.config.DATABASE_FOLDER) / "ai_models"
            self._finalize_resolve()
            return

        # 4. Fallback — пользовательская директория
        self._model_dir = Path(r"F:\ai_models")
        self._finalize_resolve()

    def _finalize_resolve(self) -> None:
        """Завершает определение путей (HF_HOME, FAISS) после того как model_dir установлен."""
        # --- HF_HOME ---
        env_hf = os.environ.get("HF_HOME")
        if env_hf:
            self._hf_home = Path(env_hf)
        elif hasattr(self.config, "HF_MODELS_CACHE_DIR") and self.config.HF_MODELS_CACHE_DIR:
            self._hf_home = Path(self.config.HF_MODELS_CACHE_DIR)
        else:
            # По умолчанию — поддиректория внутри model_dir
            self._hf_home = self._model_dir / "hf_cache"

        # --- FAISS ---
        env_faiss = os.environ.get("FAISS_INDEX_DIR")
        if env_faiss:
            self._faiss_dir = Path(env_faiss)
        elif hasattr(self.config, "DATABASE_FOLDER") and self.config.DATABASE_FOLDER:
            self._faiss_dir = Path(self.config.DATABASE_FOLDER) / "vector_db"
        else:
            self._faiss_dir = self._model_dir / "faiss_indexes"

    def _ensure_directories(self) -> None:
        """Создаёт все необходимые директории."""
        dirs_to_create = [
            self._model_dir,
            self._hf_home,
            self._faiss_dir,
            self.rl_models_dir,
            self.championship_dir,
            self.backup_dir,
        ]

        for d in dirs_to_create:
            try:
                d.mkdir(parents=True, exist_ok=True)
                logger.debug(f"[ModelPaths] Директория готова: {d}")
            except Exception as e:
                logger.warning(f"[ModelPaths] Не удалось создать {d}: {e}")

    def _set_env_vars(self) -> None:
        """Устанавливает переменные окружения для внешних библиотек."""
        os.environ["HF_HOME"] = str(self._hf_home)
        os.environ["TRANSFORMERS_CACHE"] = str(self._hf_home / "transformers")
        os.environ["FAISS_INDEX_DIR"] = str(self._faiss_dir)
        logger.info(f"[ModelPaths] HF_HOME установлен: {self._hf_home}")

    # ===================================================================
    # Утилиты
    # ===================================================================

    def get_model_path(self, symbol: str, model_name: Optional[str] = None) -> Path:
        """
        Возвращает путь к модели для символа.

        Args:
            symbol: Торговый символ (EURUSD, BTCUSD, ...)
            model_name: Имя модели (если None, используется ACTIVE_MODEL из конфига)
        """
        name = model_name or self.config.ACTIVE_MODEL
        fmt = self.config.MODEL_FORMAT.lower()

        # Определяем расширение
        ext_list = MODEL_EXTENSIONS.get(fmt, [".joblib"])
        ext = ext_list[0]  # Берём основное расширение

        return self._model_dir / f"{symbol}_{name}{ext}"

    def get_scaler_path(self, symbol: str) -> Path:
        """Путь к скалеру для символа."""
        return self._model_dir / f"{symbol}_scaler.joblib"

    def get_metadata_path(self, symbol: str) -> Path:
        """Путь к метаданным модели для символа."""
        return self._model_dir / f"{symbol}_metadata.json"

    def list_models(self, symbol: Optional[str] = None) -> list[Path]:
        """
        Возвращает список всех моделей в директории.

        Args:
            symbol: Если указан, фильтрует по префиксу символа
        """
        all_extensions = [ext for exts in MODEL_EXTENSIONS.values() for ext in exts]

        models = []
        for f in self._model_dir.iterdir():
            if f.is_file() and f.suffix in all_extensions:
                if symbol is None or f.name.startswith(f"{symbol}_"):
                    models.append(f)

        return sorted(models, key=lambda p: p.stat().st_mtime, reverse=True)

    def backup_model(self, source: Path) -> Path:
        """Создаёт резервную копию модели."""
        if not source.exists():
            raise FileNotFoundError(f"Модель не найдена: {source}")

        backup_path = self.backup_dir / f"{source.name}.bak_{_timestamp()}"
        import shutil

        shutil.copy2(source, backup_path)
        logger.info(f"[ModelPaths] Резервная копия: {backup_path}")
        return backup_path

    def __repr__(self) -> str:
        return (
            f"ModelPathConfig(" f"model_dir={self._model_dir}, " f"hf_home={self._hf_home}, " f"faiss_dir={self._faiss_dir})"
        )


def _timestamp() -> str:
    """Возвращает timestamp для имён файлов."""
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def create_model_path_config(config: Settings) -> ModelPathConfig:
    """
    Factory функция для создания менеджера путей.

    Args:
        config: Настройки приложения

    Returns:
        Настроенный ModelPathConfig
    """
    return ModelPathConfig(config)
