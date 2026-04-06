# -*- coding: utf-8 -*-
"""
Тесты для ML Coordinator — координация ML обучения.
"""

import pytest
from unittest.mock import Mock, patch
import time
from src.core.trading.ml_coordinator import MLCoordinator


class TestMLCoordinator:
    """Тесты MLCoordinator."""

    @pytest.fixture
    def trading_system_mock(self):
        """Создаёт мок TradingSystem."""
        ts = Mock()
        ts.command_queue = Mock()
        ts.command_queue.put = Mock()
        ts._gui_coordinator = Mock()
        ts._gui_coordinator.send_retrain_progress = Mock()
        ts._gui_coordinator.send_model_accuracy = Mock()
        return ts

    @pytest.fixture
    def coordinator(self, trading_system_mock):
        """Создаёт MLCoordinator с моком."""
        return MLCoordinator(trading_system_mock)

    def test_initial_state(self, coordinator):
        """Начальное состояние: обучение не активно."""
        assert coordinator.is_training_active is False

    def test_start_stop_training_loop(self, coordinator):
        """Запуск и остановка цикла обучения."""
        coordinator.start_training_loop()
        assert coordinator.is_training_active is True

        coordinator.stop_training_loop()
        assert coordinator.is_training_active is False

    def test_can_train_symbol_when_not_trained(self, coordinator):
        """can_train_symbol возвращает True если символ не обучался."""
        assert coordinator.can_train_symbol("EURUSD") is True

    def test_can_train_symbol_when_recently_trained(self, coordinator):
        """can_train_symbol возвращает False если недавно обучался."""
        coordinator._last_training_time["EURUSD"] = time.time() - 1800  # 30 мин назад
        assert coordinator.can_train_symbol("EURUSD", min_interval_hours=1.0) is False

    def test_can_train_symbol_when_old_training(self, coordinator):
        """can_train_symbol возвращает True если обучение было давно."""
        coordinator._last_training_time["EURUSD"] = time.time() - 7200  # 2 часа назад
        assert coordinator.can_train_symbol("EURUSD", min_interval_hours=1.0) is True

    def test_mark_training_complete(self, coordinator):
        """mark_symbol_training_complete обновляет статус."""
        coordinator.mark_symbol_training_complete("EURUSD")

        assert coordinator._training_status["EURUSD"] == "completed"
        assert "EURUSD" in coordinator._last_training_time

    def test_mark_training_failed(self, coordinator):
        """mark_symbol_training_failed обновляет статус с ошибкой."""
        coordinator.mark_symbol_training_failed("GBPUSD", "Out of memory")

        assert "failed" in coordinator._training_status["GBPUSD"]
        assert "Out of memory" in coordinator._training_status["GBPUSD"]

    def test_mark_training_in_progress(self, coordinator):
        """mark_symbol_training_in_progress обновляет статус."""
        coordinator.mark_symbol_training_in_progress("USDJPY")

        assert coordinator._training_status["USDJPY"] == "in_progress"

    def test_get_training_status_single(self, coordinator):
        """get_training_status возвращает статус конкретного символа."""
        coordinator._training_status["EURUSD"] = "completed"

        status = coordinator.get_training_status("EURUSD")
        assert status == "completed"

    def test_get_training_status_all(self, coordinator):
        """get_training_status возвращает все статусы."""
        coordinator._training_status["EURUSD"] = "completed"
        coordinator._training_status["GBPUSD"] = "in_progress"

        status = coordinator.get_training_status()
        assert isinstance(status, dict)
        assert status["EURUSD"] == "completed"
        assert status["GBPUSD"] == "in_progress"

    def test_update_model_accuracy(self, coordinator):
        """update_model_accuracy обновляет точность."""
        coordinator.update_model_accuracy("EURUSD", 0.85)

        assert coordinator._model_accuracy["EURUSD"] == 0.85

    def test_get_model_accuracy(self, coordinator):
        """get_model_accuracy возвращает точность."""
        coordinator._model_accuracy["EURUSD"] = 0.85

        assert coordinator.get_model_accuracy("EURUSD") == 0.85

    def test_get_model_accuracy_returns_none_for_missing(self, coordinator):
        """get_model_accuracy возвращает None для отсутствующего."""
        assert coordinator.get_model_accuracy("NONEXISTENT") is None

    def test_get_all_model_accuracy(self, coordinator):
        """get_all_model_accuracy возвращает копию словаря."""
        coordinator._model_accuracy = {"EURUSD": 0.85, "GBPUSD": 0.75}

        result = coordinator.get_all_model_accuracy()
        assert result == {"EURUSD": 0.85, "GBPUSD": 0.75}
        # Изменение результата не должно влиять на внутренние данные
        result["EURUSD"] = 0.0
        assert coordinator._model_accuracy["EURUSD"] == 0.85

    def test_get_symbols_needing_retraining(self, coordinator):
        """get_symbols_needing_retraining возвращает устаревшие модели."""
        coordinator._last_training_time["EURUSD"] = time.time() - 100 * 3600  # 100 часов назад
        coordinator._last_training_time["GBPUSD"] = time.time() - 10 * 3600  # 10 часов назад

        symbols = coordinator.get_symbols_needing_retraining(["EURUSD", "GBPUSD"], max_age_hours=48.0)

        assert symbols == ["EURUSD"]

    def test_get_symbols_needing_retraining_no_symbols(self, coordinator):
        """get_symbols_needing_retraining возвращает пустой список если все свежие."""
        coordinator._last_training_time["EURUSD"] = time.time() - 10 * 3600  # 10 часов назад

        symbols = coordinator.get_symbols_needing_retraining(["EURUSD"], max_age_hours=48.0)

        assert symbols == []

    def test_force_training_for_symbol(self, coordinator):
        """force_training_for_symbol добавляет задачу в очередь."""
        result = coordinator.force_training_for_symbol("EURUSD")

        assert result is True
        coordinator.trading_system.command_queue.put.assert_called_once()

    def test_cleanup_clears_all_data(self, coordinator):
        """cleanup очищает все данные."""
        coordinator._training_active = True
        coordinator._training_status = {"EURUSD": "completed"}
        coordinator._model_accuracy = {"EURUSD": 0.85}

        coordinator.cleanup()

        assert coordinator.is_training_active is False
        assert coordinator.get_training_status() == {}
        assert coordinator.get_all_model_accuracy() == {}

    def test_send_training_progress_to_gui(self, coordinator):
        """send_training_progress_to_gui отправляет данные в GUI."""
        progress_data = {"EURUSD": 0.5, "GBPUSD": 1.0}
        coordinator.send_training_progress_to_gui(progress_data)

        coordinator.trading_system._gui_coordinator.send_retrain_progress.assert_called_once_with(progress_data)

    def test_send_model_accuracy_to_gui(self, coordinator):
        """send_model_accuracy_to_gui отправляет точности в GUI."""
        coordinator._model_accuracy = {"EURUSD": 0.85}
        coordinator.send_model_accuracy_to_gui()

        coordinator.trading_system._gui_coordinator.send_model_accuracy.assert_called_once_with(
            {"EURUSD": 0.85}
        )
