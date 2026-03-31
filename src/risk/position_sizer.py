# src/risk/position_sizer.py
"""
Position Sizing Optimizer — Оптимизатор размера позиции.

Методы расчёта размера позиции:
1. Fixed Fractional — фиксированный процент риска
2. Kelly Criterion — критерий Келли
3. Half-Kelly — консервативная версия Келли
4. Volatility Adjusted — адаптация под волатильность (ATR)
5. Risk Parity — равный вклад в риск

Обеспечивает:
- Валидацию против правил брокера
- Лимиты мин/макс размера
- Статистику расчётов
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np

from src.core.config_models import Settings
from src.data_models import SignalType

logger = logging.getLogger(__name__)


class SizingMethod(Enum):
    """Методы расчёта размера позиции."""

    FIXED_FRACTIONAL = "fixed_fractional"
    KELLY_CRITERION = "kelly"
    HALF_KELLY = "half_kelly"
    VOLATILITY_ADJUSTED = "volatility_adjusted"
    RISK_PARITY = "risk_parity"


@dataclass
class PositionSizeResult:
    """
    Результат расчёта размера позиции.

    Атрибуты:
        lot: Рассчитанный размер позиции
        method: Использованный метод
        risk_usd: Риск в долларах
        risk_percent: Риск в процентах
        stop_loss_pips: Стоп-лосс в пунктах
        validation_passed: Проверка пройдена
        validation_errors: Ошибки валидации
    """

    lot: float
    method: SizingMethod
    risk_usd: float
    risk_percent: float
    stop_loss_pips: float
    validation_passed: bool = True
    validation_errors: List[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует в словарь."""
        return {
            "lot": self.lot,
            "method": self.method.value,
            "risk_usd": self.risk_usd,
            "risk_percent": self.risk_percent,
            "stop_loss_pips": self.stop_loss_pips,
            "validation_passed": self.validation_passed,
            "validation_errors": self.validation_errors,
            "metadata": self.metadata,
        }


class IPositionSizer(ABC):
    """Интерфейс оптимизатора размера позиции."""

    @abstractmethod
    def calculate(
        self,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """
        Рассчитывает оптимальный размер позиции.

        Args:
            symbol: Торговый инструмент
            signal_type: Тип сигнала
            account_equity: Капитал счёта
            entry_price: Цена входа
            stop_loss_price: Цена стоп-лосса
            atr: ATR для волатильности
            strategy_stats: Статистика стратегии

        Returns:
            Результат расчёта
        """
        pass


class FixedFractionalSizer(IPositionSizer):
    """
    Fixed Fractional Position Sizing.

    Формула:
    Risk USD = Equity * Risk Percent
    Lot = Risk USD / (Stop Loss in Pips * Pip Value)
    """

    def __init__(self, risk_percent: float = 0.01):
        """
        Инициализация.

        Args:
            risk_percent: Процент риска на сделку (0.01 = 1%)
        """
        self.risk_percent = risk_percent
        logger.info(f"FixedFractionalSizer инициализирован с risk={risk_percent*100}%")

    def calculate(
        self,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """Рассчитывает размер позиции."""

        # Риск в долларах
        risk_usd = account_equity * self.risk_percent

        # Стоп-лосс в пунктах
        stop_loss_pips = abs(entry_price - stop_loss_price) * 10000

        # Pip value (упрощённо для USD пар)
        pip_value = 10.0  # $10 на пип для стандартного лота

        # Размер позиции
        if stop_loss_pips > 0:
            lot = risk_usd / (stop_loss_pips * pip_value)
        else:
            lot = 0.0

        return PositionSizeResult(
            lot=round(lot, 2),
            method=SizingMethod.FIXED_FRACTIONAL,
            risk_usd=risk_usd,
            risk_percent=self.risk_percent * 100,
            stop_loss_pips=stop_loss_pips,
            metadata={"pip_value": pip_value, "account_equity": account_equity},
        )


class KellyCriterionSizer(IPositionSizer):
    """
    Kelly Criterion Position Sizing.

    Формула:
    K = W - (1-W) / R
    где:
      W = Win Rate
      R = Profit/Loss Ratio (Profit Factor)

    Half-Kelly используется для консервативности (50% от Келли).
    """

    def __init__(self, use_half_kelly: bool = True, max_kelly_percent: float = 0.25):
        """
        Инициализация.

        Args:
            use_half_kelly: Использовать Half-Kelly
            max_kelly_percent: Максимальный процент по Келли
        """
        self.use_half_kelly = use_half_kelly
        self.max_kelly_percent = max_kelly_percent
        logger.info(f"KellyCriterionSizer инициализирован (Half-Kelly={use_half_kelly})")

    def calculate(
        self,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """Рассчитывает размер позиции по критерию Келли."""

        # Статистика стратегии по умолчанию
        if strategy_stats is None:
            # Если статистики нет, используем консервативные значения
            win_rate = 0.5
            profit_factor = 1.5
        else:
            win_rate = strategy_stats.get("win_rate", 0.5)
            profit_factor = strategy_stats.get("profit_factor", 1.5)

        # Расчёт по формуле Келли
        if profit_factor <= 0:
            kelly = 0.0
        else:
            kelly = win_rate - (1 - win_rate) / profit_factor

        # Half-Kelly для консервативности
        if self.use_half_kelly:
            kelly = kelly / 2

        # Ограничиваем максимум
        kelly = min(kelly, self.max_kelly_percent)
        kelly = max(kelly, 0.0)  # Не отрицательный

        # Риск в долларах
        risk_usd = account_equity * kelly

        # Стоп-лосс в пунктах
        stop_loss_pips = abs(entry_price - stop_loss_price) * 10000

        # Pip value
        pip_value = 10.0

        # Размер позиции
        if stop_loss_pips > 0:
            lot = risk_usd / (stop_loss_pips * pip_value)
        else:
            lot = 0.0

        method = SizingMethod.HALF_KELLY if self.use_half_kelly else SizingMethod.KELLY_CRITERION

        return PositionSizeResult(
            lot=round(lot, 2),
            method=method,
            risk_usd=risk_usd,
            risk_percent=kelly * 100,
            stop_loss_pips=stop_loss_pips,
            metadata={
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "raw_kelly": kelly * 2 if self.use_half_kelly else kelly,
                "pip_value": pip_value,
            },
        )


class VolatilityAdjustedSizer(IPositionSizer):
    """
    Volatility Adjusted Position Sizing.

    Формула:
    Position Size = Target Risk / (ATR in Pips * Pip Value)

    Адаптирует размер позиции под текущую волатильность рынка.
    """

    def __init__(self, target_risk_percent: float = 0.01, atr_multiplier: float = 2.0):
        """
        Инициализация.

        Args:
            target_risk_percent: Целевой процент риска
            atr_multiplier: Множитель ATR для стоп-лосса
        """
        self.target_risk_percent = target_risk_percent
        self.atr_multiplier = atr_multiplier
        logger.info(f"VolatilityAdjustedSizer инициализирован (ATR mult={atr_multiplier})")

    def calculate(
        self,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """Рассчитывает размер позиции на основе волатильности."""

        # Если ATR не предоставлен, используем стоп-лосс
        if atr is None or atr <= 0:
            atr = abs(entry_price - stop_loss_price)

        # Целевой риск в долларах
        target_risk_usd = account_equity * self.target_risk_percent

        # ATR в пунктах
        atr_pips = atr * 10000

        # Pip value
        pip_value = 10.0

        # Размер позиции на основе волатильности
        if atr_pips > 0:
            lot = target_risk_usd / (atr_pips * self.atr_multiplier * pip_value)
        else:
            lot = 0.0

        # Стоп-лосс в пунктах
        stop_loss_pips = abs(entry_price - stop_loss_price) * 10000

        # Фактический риск
        actual_risk_usd = lot * stop_loss_pips * pip_value
        actual_risk_percent = (actual_risk_usd / account_equity) * 100

        return PositionSizeResult(
            lot=round(lot, 2),
            method=SizingMethod.VOLATILITY_ADJUSTED,
            risk_usd=actual_risk_usd,
            risk_percent=actual_risk_percent,
            stop_loss_pips=stop_loss_pips,
            metadata={
                "atr": atr,
                "atr_pips": atr_pips,
                "atr_multiplier": self.atr_multiplier,
                "target_risk_usd": target_risk_usd,
                "pip_value": pip_value,
            },
        )


class RiskParitySizer(IPositionSizer):
    """
    Risk Parity Position Sizing.

    Равный вклад в риск по всем стратегиям/позициям.
    """

    def __init__(self, total_risk_percent: float = 0.05, max_positions: int = 5):
        """
        Инициализация.

        Args:
            total_risk_percent: Общий процент риска на все позиции
            max_positions: Максимальное количество позиций
        """
        self.total_risk_percent = total_risk_percent
        self.max_positions = max_positions
        self.risk_per_position = total_risk_percent / max_positions

        logger.info(f"RiskParitySizer инициализирован (max_positions={max_positions})")

    def calculate(
        self,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """Рассчитывает размер позиции с равным риском."""

        # Риск на позицию
        risk_percent = self.risk_per_position
        risk_usd = account_equity * risk_percent

        # Стоп-лосс в пунктах
        stop_loss_pips = abs(entry_price - stop_loss_price) * 10000

        # Pip value
        pip_value = 10.0

        # Размер позиции
        if stop_loss_pips > 0:
            lot = risk_usd / (stop_loss_pips * pip_value)
        else:
            lot = 0.0

        return PositionSizeResult(
            lot=round(lot, 2),
            method=SizingMethod.RISK_PARITY,
            risk_usd=risk_usd,
            risk_percent=risk_percent * 100,
            stop_loss_pips=stop_loss_pips,
            metadata={
                "total_risk_percent": self.total_risk_percent * 100,
                "max_positions": self.max_positions,
                "risk_per_position_percent": risk_percent * 100,
                "pip_value": pip_value,
            },
        )


class PositionSizer:
    """
    Главный класс оптимизатора размера позиции.

    Предоставляет:
    - Выбор метода расчёта
    - Валидацию против правил брокера
    - Лимиты мин/макс
    - Статистику расчётов
    """

    def __init__(self, config: Settings):
        """
        Инициализация Position Sizer.

        Args:
            config: Конфигурация системы
        """
        self.config = config

        # Конфигурация из settings
        ps_config = getattr(config, "position_sizing", {})
        self.method = SizingMethod(ps_config.get("method", "fixed_fractional"))
        self.fixed_risk_percent = ps_config.get("fixed_risk_percent", 0.01)
        self.kelly_use_half = ps_config.get("kelly_use_half", True)
        self.kelly_max_percent = ps_config.get("kelly_max_percent", 0.25)
        self.volatility_atr_multiplier = ps_config.get("volatility_atr_multiplier", 2.0)
        self.risk_parity_total = ps_config.get("risk_parity_total_risk", 0.05)
        self.risk_parity_max_positions = ps_config.get("risk_parity_max_positions", 5)

        # Лимиты
        self.min_lot = ps_config.get("min_lot", 0.01)
        self.max_lot = ps_config.get("max_lot", 100.0)
        self.lot_step = ps_config.get("lot_step", 0.01)

        # Создаём сизеры для каждого метода
        self.sizers: Dict[SizingMethod, IPositionSizer] = {
            SizingMethod.FIXED_FRACTIONAL: FixedFractionalSizer(self.fixed_risk_percent),
            SizingMethod.KELLY_CRITERION: KellyCriterionSizer(use_half_kelly=False, max_kelly_percent=self.kelly_max_percent),
            SizingMethod.HALF_KELLY: KellyCriterionSizer(use_half_kelly=True, max_kelly_percent=self.kelly_max_percent),
            SizingMethod.VOLATILITY_ADJUSTED: VolatilityAdjustedSizer(
                target_risk_percent=self.fixed_risk_percent, atr_multiplier=self.volatility_atr_multiplier
            ),
            SizingMethod.RISK_PARITY: RiskParitySizer(
                total_risk_percent=self.risk_parity_total, max_positions=self.risk_parity_max_positions
            ),
        }

        # Статистика
        self.stats = {"total_calculations": 0, "by_method": {}, "avg_lot": 0.0, "total_risk_usd": 0.0}

        logger.info(f"Position Sizer инициализирован (метод: {self.method.value})")

    def calculate(
        self,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """
        Рассчитывает оптимальный размер позиции.

        Args:
            symbol: Торговый инструмент
            signal_type: Тип сигнала
            account_equity: Капитал счёта
            entry_price: Цена входа
            stop_loss_price: Цена стоп-лосса
            atr: ATR для волатильности
            strategy_stats: Статистика стратегии

        Returns:
            Результат расчёта с валидацией
        """
        # Выбираем сизер
        sizer = self.sizers.get(self.method)
        if sizer is None:
            logger.error(f"Неизвестный метод: {self.method}")
            sizer = self.sizers[SizingMethod.FIXED_FRACTIONAL]

        # Рассчитываем
        result = sizer.calculate(
            symbol=symbol,
            signal_type=signal_type,
            account_equity=account_equity,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            atr=atr,
            strategy_stats=strategy_stats,
        )

        # Валидация
        result = self._validate_result(result, symbol)

        # Обновляем статистику
        self._update_stats(result)

        return result

    def calculate_with_method(
        self,
        method: SizingMethod,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """
        Рассчитывает размер позиции с указанным методом.

        Args:
            method: Метод расчёта
            ... (остальные параметры как в calculate)

        Returns:
            Результат расчёта
        """
        sizer = self.sizers.get(method)
        if sizer is None:
            logger.error(f"Неизвестный метод: {method}")
            sizer = self.sizers[SizingMethod.FIXED_FRACTIONAL]

        result = sizer.calculate(
            symbol=symbol,
            signal_type=signal_type,
            account_equity=account_equity,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            atr=atr,
            strategy_stats=strategy_stats,
        )

        return self._validate_result(result, symbol)

    def compare_methods(
        self,
        symbol: str,
        signal_type: SignalType,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        atr: Optional[float] = None,
        strategy_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, PositionSizeResult]:
        """
        Сравнивает все методы расчёта.

        Args:
            ... (параметры как в calculate)

        Returns:
            Словарь {метод: результат}
        """
        results = {}

        for method, sizer in self.sizers.items():
            result = sizer.calculate(
                symbol=symbol,
                signal_type=signal_type,
                account_equity=account_equity,
                entry_price=entry_price,
                stop_loss_price=stop_loss_price,
                atr=atr,
                strategy_stats=strategy_stats,
            )
            result = self._validate_result(result, symbol)
            results[method.value] = result

        return results

    def _validate_result(self, result: PositionSizeResult, symbol: str) -> PositionSizeResult:
        """Валидирует результат против правил брокера."""

        errors = []

        # Проверка минимума
        if result.lot < self.min_lot:
            errors.append(f"Lot {result.lot} < min {self.min_lot}")
            result.validation_passed = False

        # Проверка максимума
        if result.lot > self.max_lot:
            errors.append(f"Lot {result.lot} > max {self.max_lot}")
            result.validation_passed = False

        # Проверка шага
        if result.lot % self.lot_step != 0:
            # Округляем до шага
            result.lot = round(result.lot / self.lot_step) * self.lot_step

        result.validation_errors = errors

        return result

    def _update_stats(self, result: PositionSizeResult) -> None:
        """Обновляет статистику расчётов."""
        self.stats["total_calculations"] += 1

        method_name = result.method.value
        if method_name not in self.stats["by_method"]:
            self.stats["by_method"][method_name] = 0
        self.stats["by_method"][method_name] += 1

        # Скользящее среднее лота
        n = self.stats["total_calculations"]
        self.stats["avg_lot"] = ((self.stats["avg_lot"] * (n - 1)) + result.lot) / n

        self.stats["total_risk_usd"] += result.risk_usd

    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику расчётов."""
        return self.stats.copy()

    def set_method(self, method: SizingMethod) -> None:
        """
        Устанавливает метод расчёта.

        Args:
            method: Новый метод
        """
        self.method = method
        logger.info(f"Метод Position Sizer изменён на {method.value}")
