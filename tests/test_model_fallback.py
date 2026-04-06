# -*- coding: utf-8 -*-
"""
Тесты для Graceful Degradation — fallback при падении ML моделей.
"""

import pytest
import time
from src.core.trading.model_fallback import (
    GracefulDegradationManager,
    DegradationPhase,
    ModelHealth,
)


class TestModelHealth:
    """Тесты ModelHealth."""

    def test_initial_state_healthy(self):
        """Начальное состояние — модель здорова."""
        health = ModelHealth("LSTM_EURUSD")
        assert health.is_healthy is True
        assert health.last_error is None
        assert health.consecutive_failures == 0

    def test_record_success_resets_failures(self):
        """record_success сбрасывает счётчик сбоев."""
        health = ModelHealth("LSTM_EURUSD")
        health.consecutive_failures = 2
        health.record_success()

        assert health.consecutive_failures == 0
        assert health.is_healthy is True

    def test_record_failure_increments_counter(self):
        """record_failure увеличивает счётчик сбоев."""
        health = ModelHealth("LSTM_EURUSD")
        health.record_failure("OOM error")

        assert health.consecutive_failures == 1
        assert health.is_healthy is False
        assert health.last_error == "OOM error"

    def test_is_permanently_failed_threshold(self):
        """is_permanently_failed=True после max_consecutive_failures."""
        health = ModelHealth("LSTM_EURUSD")
        health.max_consecutive_failures = 3

        health.record_failure("err1")
        health.record_failure("err2")
        assert health.is_permanently_failed is False

        health.record_failure("err3")
        assert health.is_permanently_failed is True


class TestGracefulDegradationManager:
    """Тесты GracefulDegradationManager."""

    def test_initial_phase_full_ml(self):
        """Начальная фаза — FULL_ML."""
        manager = GracefulDegradationManager()
        assert manager.current_phase == DegradationPhase.FULL_ML

    def test_register_model(self):
        """register_model регистрирует модель."""
        manager = GracefulDegradationManager()
        manager.register_model("LSTM_EURUSD")

        assert "LSTM_EURUSD" in manager.model_health
        assert manager.model_health["LSTM_EURUSD"].is_healthy is True

    def test_record_model_success(self):
        """record_model_success обновляет статус."""
        manager = GracefulDegradationManager()
        manager.record_model_success("LSTM_EURUSD")

        assert manager.model_health["LSTM_EURUSD"].is_healthy is True

    def test_record_model_failure(self):
        """record_model_failure обновляет статус с ошибкой."""
        manager = GracefulDegradationManager()
        manager.record_model_failure("LSTM_EURUSD", "CUDA out of memory")

        assert manager.model_health["LSTM_EURUSD"].is_healthy is False

    def test_phase_degradation_at_50_percent(self):
        """При 50%+ сбоев — переход в CLASSICAL_FALLBACK."""
        manager = GracefulDegradationManager()
        manager._min_phase_change_interval = 0  # Отключить rate limiting

        # Регистрируем 4 модели, 2 фейлятся (50%)
        # Нужно 3 failure для permanently_failed
        manager.record_model_success("model1")
        manager.record_model_success("model2")
        for _ in range(3):
            manager.record_model_failure("model3", "error")
            manager.record_model_failure("model4", "error")

        # Принудительно проверяем деградацию
        manager._check_phase_degradation()

        assert manager.current_phase == DegradationPhase.CLASSICAL_FALLBACK

    def test_phase_degradation_at_80_percent(self):
        """При 80%+ сбоев — переход в OBSERVER_MODE."""
        manager = GracefulDegradationManager()
        manager._min_phase_change_interval = 0

        # 5 моделей, 4 фейлятся (80%)
        manager.record_model_success("model1")
        for i in range(4):
            for _ in range(3):  # 3 failure для permanently_failed
                manager.record_model_failure(f"model_{i+2}", "error")

        manager._check_phase_degradation()

        assert manager.current_phase == DegradationPhase.OBSERVER_MODE

    def test_phase_upgrade_on_recovery(self):
        """Фаза повышается при восстановлении моделей."""
        manager = GracefulDegradationManager()
        manager._min_phase_change_interval = 0

        # Сначала деградируем
        manager.record_model_failure("model1", "error")
        manager.record_model_failure("model2", "error")
        manager._check_phase_degradation()

        # Теперь восстанавливаем
        manager.record_model_success("model1")
        manager.record_model_success("model2")
        manager._check_phase_upgrade()

        # Должна вернуться в FULL_ML или PARTIAL_ML
        assert manager.current_phase in [
            DegradationPhase.FULL_ML,
            DegradationPhase.PARTIAL_ML,
        ]

    def test_can_use_model_returns_true_for_healthy(self):
        """can_use_model=True для здоровой модели."""
        manager = GracefulDegradationManager()
        manager.record_model_success("LSTM_EURUSD")

        assert manager.can_use_model("LSTM_EURUSD") is True

    def test_can_use_model_returns_false_for_permanently_failed(self):
        """can_use_model=False для окончательно сломанной модели."""
        manager = GracefulDegradationManager()
        # 3 сбоя = permanently failed
        manager.record_model_failure("LSTM_EURUSD", "error1")
        manager.record_model_failure("LSTM_EURUSD", "error2")
        manager.record_model_failure("LSTM_EURUSD", "error3")

        assert manager.can_use_model("LSTM_EURUSD") is False

    def test_can_use_model_returns_true_for_unregistered(self):
        """can_use_model=True для незарегистрированной модели."""
        manager = GracefulDegradationManager()
        assert manager.can_use_model("NONEXISTENT") is True

    def test_get_fallback_strategy_full_ml(self):
        """get_fallback_strategy для FULL_ML."""
        manager = GracefulDegradationManager()
        assert manager.get_fallback_strategy() == "ML_ensemble"

    def test_get_fallback_strategy_classical(self):
        """get_fallback_strategy для CLASSICAL_FALLBACK."""
        manager = GracefulDegradationManager()
        manager.current_phase = DegradationPhase.CLASSICAL_FALLBACK
        assert manager.get_fallback_strategy() == "BreakoutStrategy"

    def test_get_fallback_strategy_observer(self):
        """get_fallback_strategy для OBSERVER_MODE."""
        manager = GracefulDegradationManager()
        manager.current_phase = DegradationPhase.OBSERVER_MODE
        assert manager.get_fallback_strategy() == "monitor_only"

    def test_get_fallback_strategy_emergency(self):
        """get_fallback_strategy для EMERGENCY_STOP."""
        manager = GracefulDegradationManager()
        manager.current_phase = DegradationPhase.EMERGENCY_STOP
        assert manager.get_fallback_strategy() == "close_all_positions"

    def test_get_health_report(self):
        """get_health_report возвращает полный отчёт."""
        manager = GracefulDegradationManager()
        manager.record_model_success("model1")
        manager.record_model_failure("model2", "error")

        report = manager.get_health_report()

        assert "current_phase" in report
        assert "total_models" in report
        assert "healthy_models" in report
        assert "failed_models" in report
        assert "health_percentage" in report
        assert report["total_models"] == 2
        assert report["healthy_models"] == 1
        assert report["health_percentage"] == 50.0

    def test_reset_model(self):
        """reset_model сбрасывает статус конкретной модели."""
        manager = GracefulDegradationManager()
        manager.record_model_failure("model1", "error")
        manager.reset_model("model1")

        assert manager.model_health["model1"].is_healthy is True
        assert manager.model_health["model1"].consecutive_failures == 0

    def test_reset_all(self):
        """reset_all очищает все данные."""
        manager = GracefulDegradationManager()
        manager.record_model_failure("model1", "error")
        manager.current_phase = DegradationPhase.CLASSICAL_FALLBACK

        manager.reset_all()

        assert len(manager.model_health) == 0
        assert manager.current_phase == DegradationPhase.FULL_ML
