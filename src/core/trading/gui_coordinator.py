# src/core/trading/gui_coordinator.py
"""
GUI Coordinator — управляет отправкой данных в GUI.
Извлечён из TradingSystem God Object (~140 строк методов GUI).

Отвечает за:
- Безопасное обновление GUI через Bridge
- Обновление PnL KPI
- Отправка точности моделей
- Отправка прогресса переобучения
- Веб-статус
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GUICoordinator:
    """
    Координатор обновлений GUI.

    Заменяет методы TradingSystem:
    - _safe_gui_update
    - _update_pnl_kpis
    - _send_model_accuracy_to_gui
    - _send_retrain_progress_to_gui
    - _send_initial_web_status
    - _on_drift_data_emitted
    """

    def __init__(self, bridge=None, config=None):
        self.bridge = bridge
        self.config = config
        self._last_gui_update = {}  # Rate limiting
        self._min_update_interval = 1.0  # Мин. 1 сек между обновлениями

    def safe_gui_update(self, method_name: str, *args) -> bool:
        """
        Безопасное обновление GUI с rate limiting.
        Заменяет TradingSystem._safe_gui_update.
        """
        if not self.bridge:
            return False

        # Rate limiting
        now = time.time()
        last_update = self._last_gui_update.get(method_name, 0)
        if now - last_update < self._min_update_interval:
            return False
        self._last_gui_update[method_name] = now

        try:
            # Проверяем что сигнал существует
            signal = getattr(self.bridge, method_name, None)
            if signal and hasattr(signal, "emit"):
                signal.emit(*args)
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка GUI update ({method_name}): {e}", exc_info=True)
            return False

    def update_pnl_kpis(self, kpis: Dict[str, float]) -> None:
        """
        Обновить PnL KPI в GUI.
        Заменяет TradingSystem._update_pnl_kpis.
        """
        if not self.bridge:
            return

        try:
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Отправляем все KPI одним сигналом
            if hasattr(self.bridge, "pnl_kpis_updated") and hasattr(self.bridge.pnl_kpis_updated, "emit"):
                self.bridge.pnl_kpis_updated.emit(kpis)
                logger.debug(f"[GUI] PnL KPI отправлены: {kpis}")
        except Exception as e:
            logger.error(f"Ошибка обновления PnL KPI: {e}", exc_info=True)

    def send_model_accuracy(self, accuracy_data: Dict[str, float]) -> None:
        """
        Отправить точность моделей в GUI.
        Заменяет TradingSystem._send_model_accuracy_to_gui.
        """
        if self.bridge and hasattr(self.bridge, "model_accuracy_updated"):
            try:
                self.bridge.model_accuracy_updated.emit(accuracy_data)
            except Exception as e:
                logger.error(f"Ошибка отправки точности моделей: {e}")

    def send_retrain_progress(self, progress_data: Dict[str, float]) -> None:
        """
        Отправить прогресс переобучения в GUI.
        Заменяет TradingSystem._send_retrain_progress_to_gui.
        """
        if self.bridge and hasattr(self.bridge, "retrain_progress_updated"):
            try:
                self.bridge.retrain_progress_updated.emit(progress_data)
            except Exception as e:
                logger.error(f"Ошибка отправки прогресса переобучения: {e}")

    def send_drift_data(self, timestamp: float, symbol: str, error: float, is_drifting: bool) -> None:
        """
        Отправить данные дрейфа в GUI.
        Заменяет TradingSystem._on_drift_data_emitted.
        """
        if self.bridge and hasattr(self.bridge, "drift_data_updated"):
            try:
                self.bridge.drift_data_updated.emit(timestamp, symbol, error, is_drifting)
            except Exception as e:
                logger.error(f"Ошибка отправки данных дрейфа: {e}")

    def send_web_status(self, status: str) -> None:
        """
        Отправить веб-статус.
        Заменяет TradingSystem._send_initial_web_status.
        """
        # Это используется если есть веб-сервер
        pass  # Веб-статус обрабатывается отдельно

    def cleanup(self) -> None:
        """Очистка ресурсов."""
        self._last_gui_update.clear()
