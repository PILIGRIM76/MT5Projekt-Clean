# src/core/trading/model_fallback.py
"""
Graceful Degradation для ML моделей.
Если модель падает или недоступна — используем fallback стратегию.

Фазы деградации:
1. ML модель (LSTM/LightGBM) — основная
2. Классическая стратегия (Breakout/MeanReversion) — fallback
3. Режим наблюдателя (только мониторинг) — последний resort

Это предотвращает полную остановку торговли при сбое ML.
"""

import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DegradationPhase(Enum):
    """Фазы деградации ML системы."""
    FULL_ML = "full_ml"  # Полная ML функциональность
    PARTIAL_ML = "partial_ml"  # Частичная (некоторые модели недоступны)
    CLASSICAL_FALLBACK = "classical_fallback"  # Классические стратегии
    OBSERVER_MODE = "observer_mode"  # Только мониторинг
    EMERGENCY_STOP = "emergency_stop"  # Аварийная остановка


class ModelHealth:
    """Статус здоровья одной модели."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.is_healthy = True
        self.last_error: Optional[str] = None
        self.last_check_time: float = 0
        self.consecutive_failures: int = 0
        self.max_consecutive_failures: int = 3

    def record_success(self) -> None:
        """Записать успешное использование модели."""
        self.is_healthy = True
        self.last_error = None
        self.last_check_time = time.time()
        self.consecutive_failures = 0

    def record_failure(self, error: str = "") -> None:
        """Записать сбой модели."""
        self.is_healthy = False
        self.last_error = error
        self.last_check_time = time.time()
        self.consecutive_failures += 1
        logger.warning(
            f"[ModelHealth] {self.model_name} failed ({self.consecutive_failures}/{self.max_consecutive_failures}): {error}"
        )

    @property
    def is_permanently_failed(self) -> bool:
        """Модель окончательно не работает."""
        return self.consecutive_failures >= self.max_consecutive_failures


class GracefulDegradationManager:
    """
    Менеджер graceful degradation.

    Мониторит здоровье ML моделей и переключает фазы деградации
    при сбоях.

    Атрибуты:
        model_health: Словарь {model_name: ModelHealth}
        current_phase: Текущая фаза деградации
    """

    def __init__(self):
        self.model_health: Dict[str, ModelHealth] = {}
        self.current_phase = DegradationPhase.FULL_ML
        self._phase_history: List[tuple] = []  # (timestamp, phase)
        self._last_phase_change: float = 0
        self._min_phase_change_interval = 30.0  # Мин. 30 сек между сменами фаз

    def register_model(self, model_name: str) -> None:
        """
        Зарегистрировать модель для мониторинга.

        Args:
            model_name: Имя модели
        """
        if model_name not in self.model_health:
            self.model_health[model_name] = ModelHealth(model_name)
            logger.info(f"[Degradation] Зарегистрирована модель: {model_name}")

    def record_model_success(self, model_name: str) -> None:
        """
        Записать успешное использование модели.

        Args:
            model_name: Имя модели
        """
        self.register_model(model_name)
        self.model_health[model_name].record_success()
        self._check_phase_upgrade()

    def record_model_failure(self, model_name: str, error: str = "") -> None:
        """
        Записать сбой модели.

        Args:
            model_name: Имя модели
            error: Описание ошибки
        """
        self.register_model(model_name)
        self.model_health[model_name].record_failure(error)
        self._check_phase_degradation()

    def _check_phase_degradation(self) -> None:
        """Проверить нужно ли понизить фазу."""
        now = time.time()
        if now - self._last_phase_change < self._min_phase_change_interval:
            return

        total_models = len(self.model_health)
        failed_models = sum(1 for h in self.model_health.values() if h.is_permanently_failed)
        failed_ratio = failed_models / max(total_models, 1)

        new_phase = self.current_phase

        if failed_ratio >= 0.8:
            # 80%+ моделей не работает → observer mode
            new_phase = DegradationPhase.OBSERVER_MODE
        elif failed_ratio >= 0.5:
            # 50%+ моделей не работает → classical fallback
            new_phase = DegradationPhase.CLASSICAL_FALLBACK
        elif failed_ratio >= 0.2:
            # 20%+ моделей не работает → partial ML
            new_phase = DegradationPhase.PARTIAL_ML

        if new_phase != self.current_phase:
            self._switch_phase(new_phase)

    def _check_phase_upgrade(self) -> None:
        """Проверить можно ли повысить фазу."""
        now = time.time()
        if now - self._last_phase_change < self._min_phase_change_interval:
            return

        total_models = len(self.model_health)
        healthy_models = sum(1 for h in self.model_health.values() if h.is_healthy)
        healthy_ratio = healthy_models / max(total_models, 1)

        new_phase = self.current_phase

        if self.current_phase == DegradationPhase.OBSERVER_MODE and healthy_ratio >= 0.5:
            new_phase = DegradationPhase.CLASSICAL_FALLBACK
        elif self.current_phase == DegradationPhase.CLASSICAL_FALLBACK and healthy_ratio >= 0.8:
            new_phase = DegradationPhase.FULL_ML
        elif self.current_phase == DegradationPhase.PARTIAL_ML and healthy_ratio >= 0.9:
            new_phase = DegradationPhase.FULL_ML

        if new_phase != self.current_phase:
            self._switch_phase(new_phase)

    def _switch_phase(self, new_phase: DegradationPhase) -> None:
        """
        Переключить фазу деградации.

        Args:
            new_phase: Новая фаза
        """
        old_phase = self.current_phase
        self.current_phase = new_phase
        self._last_phase_change = time.time()
        self._phase_history.append((time.time(), new_phase))

        logger.warning(
            f"[Degradation] Фаза изменена: {old_phase.value} → {new_phase.value}"
        )

        # Если перешли в observer mode или emergency stop — логируем критично
        if new_phase in [DegradationPhase.OBSERVER_MODE, DegradationPhase.EMERGENCY_STOP]:
            logger.critical(
                f"[Degradation] КРИТИЧНО: Система перешла в {new_phase.value}! "
                f"Здоровые модели: {sum(1 for h in self.model_health.values() if h.is_healthy)}/{len(self.model_health)}"
            )

    def can_use_model(self, model_name: str) -> bool:
        """
        Проверить можно ли использовать модель.

        Args:
            model_name: Имя модели

        Returns:
            True если модель доступна
        """
        if model_name not in self.model_health:
            return True  # Не зарегистрирована — считаем доступной

        health = self.model_health[model_name]
        if health.is_permanently_failed:
            logger.warning(f"[Degradation] {model_name} permanently failed, using fallback")
            return False

        return True

    def get_fallback_strategy(self) -> str:
        """
        Получить fallback стратегию для текущей фазы.

        Returns:
            Имя fallback стратегии
        """
        fallback_map = {
            DegradationPhase.FULL_ML: "ML_ensemble",
            DegradationPhase.PARTIAL_ML: "available_models_only",
            DegradationPhase.CLASSICAL_FALLBACK: "BreakoutStrategy",
            DegradationPhase.OBSERVER_MODE: "monitor_only",
            DegradationPhase.EMERGENCY_STOP: "close_all_positions",
        }
        return fallback_map.get(self.current_phase, "monitor_only")

    def get_health_report(self) -> Dict[str, Any]:
        """
        Получить отчёт о здоровье системы.

        Returns:
            Словарь с отчётом
        """
        total = len(self.model_health)
        healthy = sum(1 for h in self.model_health.values() if h.is_healthy)
        failed = sum(1 for h in self.model_health.values() if h.is_permanently_failed)

        return {
            "current_phase": self.current_phase.value,
            "fallback_strategy": self.get_fallback_strategy(),
            "total_models": total,
            "healthy_models": healthy,
            "failed_models": failed,
            "health_percentage": (healthy / max(total, 1)) * 100,
            "model_details": {
                name: {
                    "healthy": h.is_healthy,
                    "consecutive_failures": h.consecutive_failures,
                    "last_error": h.last_error,
                }
                for name, h in self.model_health.items()
            },
            "phase_history": [(t, p.value) for t, p in self._phase_history[-10:]],  # Последние 10
        }

    def reset_model(self, model_name: str) -> None:
        """
        Сбросить статус модели (после восстановления).

        Args:
            model_name: Имя модели
        """
        if model_name in self.model_health:
            self.model_health[model_name] = ModelHealth(model_name)
            logger.info(f"[Degradation] Статус модели {model_name} сброшен")

    def reset_all(self) -> None:
        """Сбросить все модели и фазу."""
        self.model_health.clear()
        self.current_phase = DegradationPhase.FULL_ML
        self._phase_history.clear()
        logger.info("[Degradation] Все статусы сброшены")
