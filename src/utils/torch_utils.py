# -*- coding: utf-8 -*-
"""
src/utils/torch_utils.py — Утилиты для PyTorch

Централизованное определение устройства, управление памятью,
и общие операции для всех ML-модулей.
"""

from __future__ import annotations

import logging
from typing import Optional

import torch

logger = logging.getLogger(__name__)

# Кэшированное устройство (избегает повторных вызовов cuda.is_available())
_cached_device: Optional[str] = None


def get_torch_device(force_refresh: bool = False) -> str:
    """
    Возвращает оптимальное устройство для PyTorch.

    Args:
        force_refresh: Принудительно перепроверить доступность CUDA

    Returns:
        'cuda' если доступно, иначе 'cpu'
    """
    global _cached_device

    if _cached_device is None or force_refresh:
        _cached_device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.debug(f"[TorchUtils] Устройство определено: {_cached_device}")

    return _cached_device


def get_device_name() -> str:
    """
    Возвращает читаемое имя устройства.

    Returns:
        Название GPU (если CUDA доступна) или 'CPU'
    """
    device = get_torch_device()
    if device == "cuda":
        return torch.cuda.get_device_name(0)
    return "CPU"


def get_gpu_memory_info() -> Optional[dict]:
    """
    Возвращает информацию о памяти GPU.

    Returns:
        Dict с ключами 'allocated', 'reserved', 'free_mb' или None если CPU
    """
    if get_torch_device() != "cuda":
        return None

    return {
        "allocated_mb": torch.cuda.memory_allocated(0) / 1024**2,
        "reserved_mb": torch.cuda.memory_reserved(0) / 1024**2,
        "free_mb": (torch.cuda.get_device_properties(0).total_mem - torch.cuda.memory_allocated(0)) / 1024**2,
    }


def clear_cache() -> None:
    """Очищает кэш CUDA если доступен."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.debug("[TorchUtils] CUDA кэш очищен")


def set_deterministic(seed: int = 42) -> None:
    """
    Устанавливает детерминированное поведение PyTorch.

    Args:
        seed: Зерно для генератора случайных чисел
    """
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    logger.info(f"[TorchUtils] Детерминизм установлен (seed={seed})")
