# src/analysis/drift_detector.py
import logging
import math
from typing import Dict, Tuple

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class PurePythonADWIN:
    def __init__(self, delta=0.002, min_window=30):
        self.delta = delta
        self.min_window = min_window
        self.width = 0
        self.total = 0.0
        self.window = []
        self.min_len = 5  # Минимальный размер под-окна для сравнения

    def update(self, value: float) -> bool:
        self.window.append(value)
        self.width += 1
        self.total += value

        drift = False

        # --- Core ADWIN Logic ---
        while self.width > self.min_window:
            # Начинаем с самого маленького под-окна W0 (длиной self.min_len)
            n0 = self.min_len

            # Итерируемся, пока W0 не станет слишком большим (половина W)
            while n0 < self.width / 2:
                n1 = self.width - n0

                # Средние значения
                mean0 = sum(self.window[:n0]) / n0
                mean1 = sum(self.window[n0:]) / n1

                # Вычисляем порог (epsilon_adwin)
                m = 1.0 / (1.0 / n0 + 1.0 / n1)
                epsilon = math.sqrt((1.0 / (2.0 * m)) * math.log(4.0 / self.delta))

                if abs(mean0 - mean1) > epsilon:
                    # Дрейф обнаружен! Сокращаем окно, удаляя W0
                    self.window = self.window[n0:]
                    self.width = len(self.window)
                    self.total = sum(self.window)
                    drift = True
                    break

                n0 += 1

            if drift:
                break
            else:
                # Если дрейфа нет, но окно достаточно большое, выходим
                break

        # --- Ограничение размера окна (для предотвращения OOM) ---
        if self.width > 1000:
            pop_count = 100
            self.window = self.window[pop_count:]
            self.width -= pop_count
            self.total = sum(self.window)

        return drift

    def reset(self):
        self.width = 0
        self.total = 0.0
        self.window = []


class ConceptDriftManager:
    def __init__(self, config: Settings):
        self.config = config.concept_drift
        self.detectors: Dict[str, PurePythonADWIN] = {}
        self.drift_statuses: Dict[str, bool] = {}

    def _get_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}_{timeframe}"

    def update(self, symbol: str, timeframe: str, predicted_price: float, actual_price: float) -> Tuple[bool, float]:
        if not self.config.enabled or predicted_price is None or actual_price is None or actual_price == 0:
            return False, 0.0

        key = self._get_key(symbol, timeframe)

        if key not in self.detectors:
            self.detectors[key] = PurePythonADWIN(delta=self.config.adwin_delta, min_window=self.config.min_window_size)
            self.drift_statuses[key] = False

        # Вычисляем APE (Absolute Percentage Error)
        error = abs((predicted_price - actual_price) / actual_price)

        is_drift = self.detectors[key].update(error)

        if is_drift:
            avg_error = self.detectors[key].total / self.detectors[key].width if self.detectors[key].width > 0 else 0
            logger.warning(f"[DriftDetector] ДРЕЙФ ОБНАРУЖЕН для {key}! Ошибка: {error:.5f}, Средняя: {avg_error:.5f}")
            self.drift_statuses[key] = True

        return is_drift, error

    def reset(self, symbol: str, timeframe: str):
        key = self._get_key(symbol, timeframe)
        if key in self.detectors:
            self.detectors[key].reset()
            self.drift_statuses[key] = False
