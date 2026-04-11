# -*- coding: utf-8 -*-
"""
src/utils/retry_utils.py — Утилиты повторных попыток с экспоненциальной задержкой

Централизованная реализация retry-логики для устранения дублирования
по всему проекту (MT5 подключения, HTTP запросы, работа с БД и т.д.).
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    logger_name: Optional[str] = None,
):
    """
    Декоратор для повторных попыток с экспоненциальной задержкой.

    Args:
        max_retries: Максимальное количество попыток
        base_delay: Начальная задержка в секундах
        max_delay: Максимальная задержка в секундах
        exceptions: Кортеж исключений для перехвата
        logger_name: Имя логгера (по умолчанию использует __name__ вызывающего)

    Returns:
        Декоратор для функции

    Пример:
        @retry_with_backoff(max_retries=3, base_delay=1.0, exceptions=(ConnectionError,))
        def fetch_data():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            func_logger = logging.getLogger(logger_name or func.__module__)
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        func_logger.error(f"[{func.__name__}] Все {max_retries} попыток исчерпаны. " f"Последняя ошибка: {e}")
                        raise

                    delay = min(base_delay * (2**attempt), max_delay)
                    func_logger.warning(
                        f"[{func.__name__}] Попытка {attempt + 1}/{max_retries} не удалась: {e}. "
                        f"Повтор через {delay:.1f}с..."
                    )
                    time.sleep(delay)

            # Должно быть unreachable, но для type checking
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


def retry_async_with_backoff(
    max_retries: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    logger_name: Optional[str] = None,
):
    """
    Асинхронный декоратор для повторных попыток с экспоненциальной задержкой.

    Args:
        max_retries: Максимальное количество попыток
        base_delay: Начальная задержка в секундах
        max_delay: Максимальная задержка в секундах
        exceptions: Кортеж исключений для перехвата
        logger_name: Имя логгера

    Пример:
        @retry_async_with_backoff(max_retries=3, base_delay=1.0)
        async def fetch_data_async():
            ...
    """
    import asyncio

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            func_logger = logging.getLogger(logger_name or func.__module__)
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        func_logger.error(f"[{func.__name__}] Все {max_retries} попыток исчерпаны. " f"Последняя ошибка: {e}")
                        raise

                    delay = min(base_delay * (2**attempt), max_delay)
                    func_logger.warning(
                        f"[{func.__name__}] Попытка {attempt + 1}/{max_retries} не удалась: {e}. "
                        f"Повтор через {delay:.1f}с..."
                    )
                    await asyncio.sleep(delay)

            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
