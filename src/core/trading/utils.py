# src/core/trading/utils.py
"""
Утилиты для Trading System — извлечены из TradingSystem God Object.

Включает:
- Кэширование данных
- Замер производительности
- Таймфрейм хелперы
"""

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TradingCache:
    """
    Простой кэш для торговых данных.
    Извлечён из TradingSystem.get_cached_data/set_cached_data.
    """

    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, Any] = {}
        self._max_size = max_size

    def __contains__(self, key: str) -> bool:
        """Поддержка оператора `in`."""
        return key in self._cache

    def __getitem__(self, key: str) -> Any:
        """Поддержка оператора `[]` для получения."""
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Поддержка оператора `[]` для установки."""
        self.set(key, value)

    def get(self, key: str, default: Any = None) -> Optional[Any]:
        """Получить данные из кэша."""
        return self._cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Сохранить данные в кэш."""
        if len(self._cache) >= self._max_size:
            # Удаляем oldest entry
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[key] = value

    def invalidate(self, key: Optional[str] = None) -> None:
        """Инвалидировать кэш (весь или конкретный ключ)."""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def stats(self) -> Dict[str, int]:
        """Статистика кэша."""
        return {"size": len(self._cache), "max_size": self._max_size}


class PerformanceTimer:
    """
    Таймер замера производительности.
    Извлечён из TradingSystem.start/end_performance_timer.
    """

    def __init__(self):
        self._timers: Dict[str, float] = {}

    def start(self, operation_name: str) -> None:
        """Начать замер."""
        self._timers[operation_name] = time.time()

    def end(self, operation_name: str) -> float:
        """Закончить замер, вернуть время в секундах."""
        if operation_name not in self._timers:
            logger.warning(f"[Perf] Timer '{operation_name}' не был запущен")
            return 0.0

        elapsed = time.time() - self._timers.pop(operation_name)
        logger.info(f"[Perf] {operation_name}: {elapsed:.4f}s")
        return elapsed


# Таймфрейм хелперы
TIMEFRAME_MAP = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
}


def get_timeframe_seconds(timeframe: str) -> int:
    """Вернуть количество секунд для таймфрейма."""
    return TIMEFRAME_MAP.get(timeframe, 3600)  # Default H1


def get_timeframe_str(timeframe_code) -> str:
    """Вернуть строковое представление таймфрейма."""
    # Обратный маппинг: код -> строка
    reverse_map = {v: k for k, v in TIMEFRAME_MAP.items()}
    return reverse_map.get(timeframe_code, "H1")
