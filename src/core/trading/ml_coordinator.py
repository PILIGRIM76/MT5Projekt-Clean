# src/core/trading/ml_coordinator.py
"""
MLCoordinator — координация обучения и ML моделей.
Извлечён из TradingSystem God Object (Фаза 4).

Отвечает за:
- Управление циклами обучения
- Валидация метрик моделей
- Принудительное переобучение
- Сбор данных для обучения
- Статус обучения
"""

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MLCoordinator:
    """
    Координатор машинного обучения.

    Атрибуты:
        trading_system: Ссылка на TradingSystem для доступа к сервисам
    """

    def __init__(self, trading_system):
        self.trading_system = trading_system
        self._training_active = False
        self._training_status: Dict[str, str] = {}
        self._last_training_time: Dict[str, float] = {}
        self._model_accuracy: Dict[str, float] = {}

    @property
    def is_training_active(self) -> bool:
        """Проверка активности обучения."""
        return self._training_active

    def can_train_symbol(self, symbol: str, min_interval_hours: float = 1.0) -> bool:
        """
        Проверка можно ли обучить символ (rate limiting).

        Args:
            symbol: Символ для проверки
            min_interval_hours: Минимальный интервал между обучениями

        Returns:
            True если можно обучить
        """
        now = time.time()
        last = self._last_training_time.get(symbol, 0)
        elapsed_hours = (now - last) / 3600.0

        if elapsed_hours < min_interval_hours:
            logger.debug(
                f"[ML] {symbol}: последнее обучение {elapsed_hours:.2f}ч назад "
                f"(минимум {min_interval_hours}ч)"
            )
            return False
        return True

    def mark_symbol_training_complete(self, symbol: str) -> None:
        """
        Отметить что обучение символа завершено.

        Args:
            symbol: Обученный символ
        """
        self._last_training_time[symbol] = time.time()
        self._training_status[symbol] = "completed"
        logger.info(f"[ML] Обучение {symbol} завершено")

    def mark_symbol_training_failed(self, symbol: str, error: str = "") -> None:
        """
        Отметить что обучение символа не удалось.

        Args:
            symbol: Символ
            error: Описание ошибки
        """
        self._training_status[symbol] = f"failed: {error}"
        logger.warning(f"[ML] Обучение {symbol} не удалось: {error}")

    def mark_symbol_training_in_progress(self, symbol: str) -> None:
        """
        Отметить что обучение символа началось.

        Args:
            symbol: Символ
        """
        self._training_status[symbol] = "in_progress"
        logger.info(f"[ML] Начало обучения {symbol}")

    def get_training_status(self, symbol: Optional[str] = None) -> Any:
        """
        Получить статус обучения.

        Args:
            symbol: Символ (None = все)

        Returns:
            Статус обучения
        """
        if symbol:
            return self._training_status.get(symbol, "not_started")
        return dict(self._training_status)

    def update_model_accuracy(self, symbol: str, accuracy: float) -> None:
        """
        Обновить точность модели.

        Args:
            symbol: Символ
            accuracy: Точность (0.0 - 1.0)
        """
        self._model_accuracy[symbol] = accuracy
        logger.info(f"[ML] Точность модели {symbol}: {accuracy:.4f}")

    def get_model_accuracy(self, symbol: str) -> Optional[float]:
        """
        Получить точность модели.

        Args:
            symbol: Символ

        Returns:
            Точность или None
        """
        return self._model_accuracy.get(symbol)

    def get_all_model_accuracy(self) -> Dict[str, float]:
        """
        Получить точности всех моделей.

        Returns:
            Словарь {symbol: accuracy}
        """
        return dict(self._model_accuracy)

    def get_symbols_needing_retraining(self, all_symbols: List[str], max_age_hours: float = 48.0) -> List[str]:
        """
        Получить символы требующие переобучения.

        Args:
            all_symbols: Все символы
            max_age_hours: Максимальный возраст модели

        Returns:
            Список символов для переобучения
        """
        now = time.time()
        needs_retraining = []

        for symbol in all_symbols:
            last_train = self._last_training_time.get(symbol, 0)
            age_hours = (now - last_train) / 3600.0

            if age_hours > max_age_hours:
                needs_retraining.append(symbol)
                logger.debug(f"[ML] {symbol}: модель устарела ({age_hours:.1f}ч)")

        return needs_retraining

    def force_training_for_symbol(self, symbol: str) -> bool:
        """
        Принудительное обучение символа.

        Args:
            symbol: Символ для обучения

        Returns:
            True если обучение запущено
        """
        ts = self.trading_system

        try:
            self.mark_symbol_training_in_progress(symbol)

            # Добавляем задачу в очередь обучения
            if hasattr(ts, "command_queue"):
                ts.command_queue.put({
                    "type": "FORCE_TRAINING",
                    "symbol": symbol,
                    "timestamp": time.time(),
                })
                logger.info(f"[ML] Задача обучения добавлена для {symbol}")
                return True

            return False
        except Exception as e:
            self.mark_symbol_training_failed(symbol, str(e))
            return False

    def send_training_progress_to_gui(self, progress_data: Dict[str, Any]) -> None:
        """
        Отправить прогресс обучения в GUI.

        Args:
            progress_data: Данные прогресса
        """
        ts = self.trading_system
        if hasattr(ts, "_gui_coordinator") and ts._gui_coordinator:
            ts._gui_coordinator.send_retrain_progress(progress_data)

    def send_model_accuracy_to_gui(self) -> None:
        """Отправить точности моделей в GUI."""
        if hasattr(self.trading_system, "_gui_coordinator") and self.trading_system._gui_coordinator:
            self.trading_system._gui_coordinator.send_model_accuracy(self._model_accuracy)

    def start_training_loop(self) -> None:
        """Запустить фоновый цикл обучения."""
        self._training_active = True
        logger.info("[ML] Фоновый цикл обучения запущен")

    def stop_training_loop(self) -> None:
        """Остановить фоновый цикл обучения."""
        self._training_active = False
        logger.info("[ML] Фоновый цикл обучения остановлен")

    def cleanup(self) -> None:
        """Очистка ресурсов."""
        self._training_active = False
        self._training_status.clear()
        self._model_accuracy.clear()
