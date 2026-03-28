# src/strategies/breakout.py
"""
Breakout Strategy v2.0 - Стратегия пробоя каналов с улучшенной фильтрацией.

Улучшения:
- Динамический расчёт confidence на основе множественных факторов
- Фильтр ложных пробоев на основе ML-эвристик
- Exit signals (take profit, stop loss, trailing stop)
- Адаптивность к режиму волатильности
- Расширенное логирование решений
- Метрики производительности
- Валидация параметров

Автор: Genesis Trading System
Версия: 2.0.0
"""
import logging
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import pandas as pd
import numpy as np

from src.data_models import TradeSignal, SignalType
from src.core.config_models import Settings
from .StrategyInterface import BaseStrategy
from .features import FeatureStore, BreakoutFeatureEngine, BreakoutFeatures


class Position:
    """
    Простая модель позиции для управления выходом.

    Attributes:
        symbol: Торговый инструмент
        type: Тип позиции (BUY/SELL)
        entry_price: Цена входа
        stop_loss: Уровень стоп-лосса
        take_profit: Уровень тейк-профита
        size: Размер позиции
    """

    def __init__(
        self,
        symbol: str,
        type: SignalType,
        entry_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        size: float = 1.0
    ):
        self.symbol = symbol
        self.type = type
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.size = size


logger = logging.getLogger(__name__)
PARAMS_FILE = Path("configs/optimized_params.json")


class BreakoutType(Enum):
    """Типы пробоев."""
    UPPER_BREAKOUT = "upper_breakout"
    LOWER_BREAKOUT = "lower_breakout"
    FALSE_BREAKOUT_UPPER = "false_upper"
    FALSE_BREAKOUT_LOWER = "false_lower"


@dataclass
class ExitSignal:
    """Сигнал на выход из позиции."""
    type: SignalType
    reason: str
    confidence: float
    price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class BreakoutMetrics:
    """Метрики стратегии для мониторинга."""
    total_signals: int = 0
    breakout_signals: int = 0
    false_breakouts: int = 0
    successful_breakouts: int = 0
    avg_confidence: float = 0.0
    avg_breakout_strength: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    _win_trades: list = field(default_factory=list)
    _loss_trades: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для сериализации."""
        return {
            'total_signals': self.total_signals,
            'breakout_signals': self.breakout_signals,
            'false_breakouts': self.false_breakouts,
            'successful_breakouts': self.successful_breakouts,
            'avg_confidence': round(self.avg_confidence, 3),
            'avg_breakout_strength': round(self.avg_breakout_strength, 4),
            'win_rate': round(self.win_rate, 3),
            'profit_factor': round(self.profit_factor, 3),
            'total_pnl': round(self.total_pnl, 2)
        }


class BreakoutStrategy(BaseStrategy):
    """
    Улучшенная стратегия пробоя каналов.

    Особенности:
    1. Динамический confidence на основе 7 факторов
    2. Фильтр ложных пробоев (ADX, RSI, Volume, Volatility)
    3. Exit signals с trailing stop
    4. Адаптация к режиму волатильности
    5. Валидация параметров
    6. Расширенное логирование
    7. Метрики производительности
    """

    def __init__(self, config: Settings):
        super().__init__(config)
        self.strategy_name = self.__class__.__name__

        # Инициализация параметров
        self._init_parameters()

        # Feature Store для общих индикаторов
        self.feature_store = FeatureStore()
        self.breakout_engine = BreakoutFeatureEngine(self.feature_store)

        # Метрики
        self.metrics = BreakoutMetrics()

        # Активные позиции (для управления выходом)
        self._active_positions: Dict[str, Position] = {}

        # Кэш последних сигналов
        self._last_signals: Dict[str, TradeSignal] = {}

        logger.info(
            f"{self.strategy_name} инициализирована с window={self.window}")

    def _init_parameters(self):
        """Инициализация и валидация параметров."""
        default_params = self.config.strategies.breakout

        # Загрузка параметров
        self.window = default_params.window

        # Загрузка оптимизированных параметров
        if PARAMS_FILE.exists():
            self._load_optimized_params()

        # Валидация параметров
        self._validate_parameters()

        # Параметры для exit signals
        self.atr_stop_multiplier = 2.5  # ATR множитель для stop loss
        self.risk_reward_ratio = 2.5    # Соотношение риск/прибыль
        # Активация trailing stop (в % от TP)
        self.trailing_stop_activation = 0.5

    def _load_optimized_params(self):
        """Загрузка оптимизированных параметров из файла."""
        try:
            with open(PARAMS_FILE, 'r', encoding='utf-8') as f:
                optimized_params = json.load(f)
                if self.strategy_name in optimized_params:
                    params = optimized_params[self.strategy_name]
                    old_window = self.window
                    self.window = params.get('window', self.window)
                    logger.info(
                        f"{self.strategy_name}: загружены ОПТИМИЗИРОВАННЫЕ параметры: "
                        f"window={old_window} → {self.window}"
                    )
        except json.JSONDecodeError as e:
            logger.error(
                f"{self.strategy_name}: ошибка парсинга {PARAMS_FILE}: {e}")
        except Exception as e:
            logger.error(
                f"{self.strategy_name}: ошибка загрузки параметров: {e}")

    def _validate_parameters(self):
        """Валидация параметров стратегии."""
        errors = []
        warnings = []

        # Проверка window
        if not (5 <= self.window <= 100):
            errors.append(
                f"window должен быть в диапазоне [5, 100], текущий: {self.window}")
        elif self.window < 10:
            warnings.append(
                f"window={self.window} может давать много ложных сигналов")
        elif self.window > 50:
            warnings.append(
                f"window={self.window} может пропускать ранние входы")

        # Логирование
        for error in errors:
            logger.error(f"{self.strategy_name}: {error}")
        for warning in warnings:
            logger.warning(f"{self.strategy_name}: {warning}")

        if errors:
            raise ValueError(
                f"{self.strategy_name}: Критические ошибки параметров: {errors}")

    def check_entry_conditions(
        self,
        df: pd.DataFrame,
        current_index: int,
        timeframe: int,
        symbol: str = None
    ) -> Optional[TradeSignal]:
        """
        Проверка условий для входа в позицию.

        Args:
            df: DataFrame с данными (цены + признаки из FeatureStore)
            current_index: Индекс текущей свечи
            timeframe: Таймфрейм в минутах
            symbol: Символ для торговли (опционально)

        Returns:
            TradeSignal или None
        """
        # Базовая валидация
        if not self._validate_dataframe(df, current_index):
            return None

        # Расчет признаков (если ещё не рассчитаны)
        if 'atr' not in df.columns:
            df = self.feature_store.calculate_all_features(
                df,
                df['symbol'].iloc[0] if 'symbol' in df.columns else (symbol if symbol else 'UNKNOWN')
            )

        # Расчет breakout-признаков
        breakout_features = self.breakout_engine.calculate_breakout_features(
            df, self.window, current_index
        )

        # Обновление метрик
        self.metrics.total_signals += 1

        # Проверка на пробой
        signal = self._check_breakout(
            df, current_index, breakout_features, timeframe, symbol
        )

        if signal:
            self.metrics.breakout_signals += 1
            self._log_signal_decision(
                signal, breakout_features, df, current_index)
            self._last_signals[signal.symbol] = signal

        return signal

    def _validate_dataframe(self, df: pd.DataFrame, current_index: int) -> bool:
        """Валидация входных данных."""
        required_cols = ['high', 'low', 'close']
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            logger.debug(f"Отсутствуют колонки: {missing_cols}")
            return False

        if current_index < self.window + 1:
            logger.debug(
                f"Недостаточно данных: index={current_index}, window={self.window}")
            return False

        if df.empty:
            logger.warning("Пустой DataFrame")
            return False

        return True

    def _check_breakout(
        self,
        df: pd.DataFrame,
        current_index: int,
        features: BreakoutFeatures,
        timeframe: int,
        symbol: str = None
    ) -> Optional[TradeSignal]:
        """
        Проверка на пробой с фильтрацией ложных сигналов.

        Returns:
            TradeSignal если обнаружен валидный пробой
        """
        current_price = df['close'].iloc[current_index]
        prev_price = df['close'].iloc[current_index - 1]

        # Получение символа через универсальный метод с default_symbol
        symbol = self._get_symbol_from_dataframe(df, current_index, default_symbol=symbol)
        if symbol == 'UNKNOWN':
            logger.warning(
                f"Не удалось определить символ для Breakout стратегии")
            return None

        # Определение типа пробоя
        breakout_type = self._determine_breakout_type(
            current_price, prev_price, features.channel_high, features.channel_low
        )

        if breakout_type is None:
            return None

        # Фильтр ложных пробоев
        if not self._filter_false_breakout(df, current_index, features, breakout_type):
            self.metrics.false_breakouts += 1
            logger.debug(
                f"{symbol}: Пробой отфильтрован (false breakout prob={features.false_breakout_probability:.2f})"
            )
            return None

        # Расчет динамического confidence
        confidence = self._calculate_dynamic_confidence(
            df, current_index, features, breakout_type, timeframe
        )

        # Минимальный порог confidence
        if confidence < 0.5:
            logger.debug(
                f"{symbol}: Confidence {confidence:.2f} ниже порога 0.5")
            return None

        # Обновление метрик
        self.metrics.avg_confidence = (
            (self.metrics.avg_confidence *
             (self.metrics.breakout_signals - 1) + confidence)
            / self.metrics.breakout_signals
        )
        self.metrics.avg_breakout_strength = (
            (self.metrics.avg_breakout_strength * (self.metrics.breakout_signals - 1)
             + features.breakout_strength) / self.metrics.breakout_signals
        )

        # Создание сигнала
        signal_type = SignalType.BUY if breakout_type == BreakoutType.UPPER_BREAKOUT else SignalType.SELL

        signal = TradeSignal(
            type=signal_type,
            confidence=round(confidence, 3),
            symbol=symbol,
            strategy_name=self.__class__.__name__,
            entry_price=current_price,
            stop_loss=self._calculate_stop_loss(
                df, current_index, features, signal_type),
            take_profit=self._calculate_take_profit(
                df, current_index, features, signal_type)
        )

        return signal

    def _determine_breakout_type(
        self,
        current_price: float,
        prev_price: float,
        channel_high: float,
        channel_low: float
    ) -> Optional[BreakoutType]:
        """Определение типа пробоя."""
        # Пробой вверх
        if current_price > channel_high and prev_price <= channel_high:
            return BreakoutType.UPPER_BREAKOUT

        # Пробой вниз
        if current_price < channel_low and prev_price >= channel_low:
            return BreakoutType.LOWER_BREAKOUT

        return None

    def _filter_false_breakout(
        self,
        df: pd.DataFrame,
        current_index: int,
        features: BreakoutFeatures,
        breakout_type: BreakoutType
    ) -> bool:
        """
        Фильтр ложных пробоев на основе множественных факторов.

        Returns:
            True если пробой валидный, False если ложный
        """
        # Фактор 1: Вероятность ложного пробоя (из BreakoutFeatureEngine)
        if features.false_breakout_probability > 0.7:
            logger.debug(
                f"Высокая вероятность ложного пробоя: {features.false_breakout_probability:.2f}")
            return False

        # Фактор 2: Подтверждение объёмом (если доступно)
        if 'volume_ratio' in df.columns:
            volume_ratio = df['volume_ratio'].iloc[current_index]
            if volume_ratio < 0.8:  # Объём ниже 80% от среднего
                logger.debug(f"Слабый объём: {volume_ratio:.2f}")
                # Не блокируем полностью, но учитываем в confidence

        # Фактор 3: ADX (сила тренда)
        if 'adx' in df.columns:
            adx = df['adx'].iloc[current_index]
            if adx < 15:  # Очень слабый тренд
                logger.debug(f"Слабый ADX: {adx:.1f}")
                return False

        # Фактор 4: RSI (перекупленность/перепроданность)
        if 'rsi' in df.columns:
            rsi = df['rsi'].iloc[current_index]
            if breakout_type == BreakoutType.UPPER_BREAKOUT and rsi > 80:
                logger.debug(f"RSI перекуплен: {rsi:.1f}")
                return False
            if breakout_type == BreakoutType.LOWER_BREAKOUT and rsi < 20:
                logger.debug(f"RSI перепродан: {rsi:.1f}")
                return False

        # Фактор 5: Сила пробоя
        if features.breakout_strength < 0.05:  # Пробой менее 0.05%
            logger.debug(f"Слабый пробой: {features.breakout_strength:.3f}%")
            return False

        # Фактор 6: Волатильность
        if not features.volatility_adjusted:
            logger.debug("Высокая волатильность (ATR > 2x среднего)")
            return False

        return True

    def _calculate_dynamic_confidence(
        self,
        df: pd.DataFrame,
        current_index: int,
        features: BreakoutFeatures,
        breakout_type: BreakoutType,
        timeframe: int
    ) -> float:
        """
        Расчет динамического confidence на основе 7 факторов.

        Факторы:
        1. Сила пробоя (25%)
        2. Подтверждение объёмом (15%)
        3. Сила тренда (ADX) (15%)
        4. Волатильность (10%)
        5. Время в канале (10%)
        6. Таймфрейм (10%)
        7. RSI (15%)

        Returns:
            Confidence в диапазоне [0, 1]
        """
        # Веса факторов
        weights = {
            'breakout_strength': 0.25,
            'volume': 0.15,
            'trend_strength': 0.15,
            'volatility': 0.10,
            'channel_time': 0.10,
            'timeframe': 0.10,
            'rsi': 0.15
        }

        scores = {}

        # 1. Сила пробоя (0-1)
        strength_score = min(
            1.0, features.breakout_strength / 0.5)  # 0.5% = максимум
        scores['breakout_strength'] = strength_score

        # 2. Объём (0-1)
        volume_score = 0.5  # Базовый score
        if 'volume_ratio' in df.columns:
            volume_ratio = df['volume_ratio'].iloc[current_index]
            if volume_ratio > 1.5:
                volume_score = 1.0
            elif volume_ratio > 1.2:
                volume_score = 0.8
            elif volume_ratio > 1.0:
                volume_score = 0.6
            elif volume_ratio > 0.8:
                volume_score = 0.4
            else:
                volume_score = 0.2
        scores['volume'] = volume_score

        # 3. Сила тренда (ADX) (0-1)
        adx_score = 0.5
        if 'adx' in df.columns:
            adx = df['adx'].iloc[current_index]
            if adx > 40:
                adx_score = 1.0
            elif adx > 30:
                adx_score = 0.8
            elif adx > 20:
                adx_score = 0.6
            elif adx > 15:
                adx_score = 0.4
            else:
                adx_score = 0.2
        scores['trend_strength'] = adx_score

        # 4. Волатильность (0-1) - предпочитаем умеренную
        vol_score = 0.7 if features.volatility_adjusted else 0.3
        scores['volatility'] = vol_score

        # 5. Время в канале (0-1) - чем дольше, тем сильнее пробой
        channel_time_score = min(1.0, self.window / 20)  # 20 баров = максимум
        scores['channel_time'] = channel_time_score

        # 6. Таймфрейм (0-1) - старшие таймфреймы надёжнее
        timeframe_scores = {
            1: 0.3,    # M1
            5: 0.5,    # M5
            15: 0.7,   # M15
            30: 0.8,   # M30
            60: 0.9,   # H1
            240: 1.0,  # H4
            1440: 1.0  # D1
        }
        scores['timeframe'] = timeframe_scores.get(timeframe, 0.5)

        # 7. RSI (0-1) - предпочитаем нейтральный RSI
        rsi_score = 0.5
        if 'rsi' in df.columns:
            rsi = df['rsi'].iloc[current_index]
            if 40 <= rsi <= 60:
                rsi_score = 1.0
            elif 30 <= rsi <= 70:
                rsi_score = 0.7
            elif 20 <= rsi <= 80:
                rsi_score = 0.4
            else:
                rsi_score = 0.2
        scores['rsi'] = rsi_score

        # Расчет взвешенного confidence
        confidence = sum(scores[k] * weights[k] for k in weights.keys())

        # Коррекция на вероятность ложного пробоя
        confidence *= (1.0 - features.false_breakout_probability * 0.3)

        # Ограничение диапазона
        confidence = max(0.0, min(1.0, confidence))

        return confidence

    def _calculate_stop_loss(
        self,
        df: pd.DataFrame,
        current_index: int,
        features: BreakoutFeatures,
        signal_type: SignalType
    ) -> float:
        """Расчет stop loss на основе ATR."""
        current_price = df['close'].iloc[current_index]

        # ATR-based stop loss
        if 'atr' in df.columns:
            atr = df['atr'].iloc[current_index]
            if signal_type == SignalType.BUY:
                stop_loss = current_price - atr * self.atr_stop_multiplier
            else:
                stop_loss = current_price + atr * self.atr_stop_multiplier
        else:
            # Fallback: на основе канала
            if signal_type == SignalType.BUY:
                stop_loss = features.channel_low
            else:
                stop_loss = features.channel_high

        return round(stop_loss, 5)

    def _calculate_take_profit(
        self,
        df: pd.DataFrame,
        current_index: int,
        features: BreakoutFeatures,
        signal_type: SignalType
    ) -> float:
        """Расчет take profit на основе risk-reward ratio."""
        current_price = df['close'].iloc[current_index]

        # Расчет риска
        if 'atr' in df.columns:
            atr = df['atr'].iloc[current_index]
            risk = atr * self.atr_stop_multiplier
        else:
            risk = abs(features.channel_high - features.channel_low)

        # Take profit = entry + risk × reward_ratio
        if signal_type == SignalType.BUY:
            take_profit = current_price + risk * self.risk_reward_ratio
        else:
            take_profit = current_price - risk * self.risk_reward_ratio

        return round(take_profit, 5)

    def check_exit_conditions(
        self,
        df: pd.DataFrame,
        current_index: int,
        position: Position
    ) -> Optional[ExitSignal]:
        """
        Проверка условий для выхода из позиции.

        Args:
            df: DataFrame с данными
            current_index: Индекс текущей свечи
            position: Активная позиция

        Returns:
            ExitSignal или None
        """
        if position.symbol not in [df['symbol'].iloc[current_index] if 'symbol' in df.columns else 'UNKNOWN']:
            return None

        current_price = df['close'].iloc[current_index]

        # Проверка stop loss
        if position.stop_loss:
            if position.type == SignalType.BUY and current_price <= position.stop_loss:
                return ExitSignal(
                    type=SignalType.SELL,
                    reason="stop_loss",
                    confidence=1.0,
                    price=current_price
                )
            if position.type == SignalType.SELL and current_price >= position.stop_loss:
                return ExitSignal(
                    type=SignalType.BUY,
                    reason="stop_loss",
                    confidence=1.0,
                    price=current_price
                )

        # Проверка take profit
        if position.take_profit:
            if position.type == SignalType.BUY and current_price >= position.take_profit:
                return ExitSignal(
                    type=SignalType.SELL,
                    reason="take_profit",
                    confidence=1.0,
                    price=current_price
                )
            if position.type == SignalType.SELL and current_price <= position.take_profit:
                return ExitSignal(
                    type=SignalType.BUY,
                    reason="take_profit",
                    confidence=1.0,
                    price=current_price
                )

        # Проверка trailing stop (если позиция в прибыли)
        trailing_signal = self._check_trailing_stop(
            df, current_index, position)
        if trailing_signal:
            return trailing_signal

        # Проверка разворота (exit при противоположном сигнале)
        reversal_signal = self._check_reversal_exit(
            df, current_index, position)
        if reversal_signal:
            return reversal_signal

        return None

    def _check_trailing_stop(
        self,
        df: pd.DataFrame,
        current_index: int,
        position: Position
    ) -> Optional[ExitSignal]:
        """Проверка trailing stop."""
        if not position.take_profit:
            return None

        current_price = df['close'].iloc[current_index]
        profit_distance = abs(current_price - position.entry_price)
        tp_distance = abs(position.take_profit - position.entry_price)

        # Активация trailing stop при 50% движения к TP
        if profit_distance < tp_distance * self.trailing_stop_activation:
            return None

        # Расчет trailing stop
        if 'atr' in df.columns:
            atr = df['atr'].iloc[current_index]
            trailing_stop = current_price - atr * \
                1.5 if position.type == SignalType.BUY else current_price + atr * 1.5

            # Проверка активации trailing stop
            if position.type == SignalType.BUY and current_price <= trailing_stop:
                return ExitSignal(
                    type=SignalType.SELL,
                    reason="trailing_stop",
                    confidence=0.9,
                    price=current_price
                )
            if position.type == SignalType.SELL and current_price >= trailing_stop:
                return ExitSignal(
                    type=SignalType.BUY,
                    reason="trailing_stop",
                    confidence=0.9,
                    price=current_price
                )

        return None

    def _check_reversal_exit(
        self,
        df: pd.DataFrame,
        current_index: int,
        position: Position
    ) -> Optional[ExitSignal]:
        """Проверка на разворот стратегии."""
        # Проверка на противоположный сигнал
        symbol = position.symbol if hasattr(position, 'symbol') else None
        opposite_signal = self.check_entry_conditions(df, current_index, 60, symbol)

        if opposite_signal:
            if position.type == SignalType.BUY and opposite_signal.type == SignalType.SELL:
                return ExitSignal(
                    type=SignalType.SELL,
                    reason="reversal",
                    confidence=opposite_signal.confidence * 0.8,
                    price=df['close'].iloc[current_index]
                )
            if position.type == SignalType.SELL and opposite_signal.type == SignalType.BUY:
                return ExitSignal(
                    type=SignalType.BUY,
                    reason="reversal",
                    confidence=opposite_signal.confidence * 0.8,
                    price=df['close'].iloc[current_index]
                )

        return None

    def _log_signal_decision(
        self,
        signal: TradeSignal,
        features: BreakoutFeatures,
        df: pd.DataFrame,
        current_index: int
    ):
        """Расширенное логирование решения о сигнале."""
        current_price = df['close'].iloc[current_index]

        # Дополнительные данные для лога
        adx = df['adx'].iloc[current_index] if 'adx' in df.columns else 'N/A'
        rsi = df['rsi'].iloc[current_index] if 'rsi' in df.columns else 'N/A'
        atr = df['atr'].iloc[current_index] if 'atr' in df.columns else 'N/A'
        volume_ratio = df['volume_ratio'].iloc[current_index] if 'volume_ratio' in df.columns else 'N/A'

        logger.info(
            f"🎯 {self.strategy_name} | {signal.symbol} | {signal.type.name} | "
            f"Confidence: {signal.confidence:.2f} | "
            f"Price: {current_price:.5f} | "
            f"SL: {signal.stop_loss:.5f} | "
            f"TP: {signal.take_profit:.5f} | "
            f"Breakout: {features.breakout_strength:.3f}% | "
            f"False Prob: {features.false_breakout_probability:.2f} | "
            f"ADX: {adx} | RSI: {rsi} | ATR: {atr} | Vol: {volume_ratio}"
        )

    def update_metrics(self, pnl: float, is_win: bool):
        """
        Обновление метрик после закрытия позиции.

        Args:
            pnl: Прибыль/убыток от сделки
            is_win: Была ли сделка прибыльной
        """
        self.metrics.total_pnl += pnl

        if is_win:
            self.metrics._win_trades.append(pnl)
            self.metrics.successful_breakouts += 1
        else:
            self.metrics._loss_trades.append(pnl)

        # Пересчет win rate
        total_trades = len(self.metrics._win_trades) + \
            len(self.metrics._loss_trades)
        if total_trades > 0:
            self.metrics.win_rate = len(
                self.metrics._win_trades) / total_trades

        # Пересчет profit factor
        gross_profit = sum(t for t in self.metrics._win_trades if t > 0)
        gross_loss = abs(sum(t for t in self.metrics._loss_trades if t < 0))
        if gross_loss > 0:
            self.metrics.profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            self.metrics.profit_factor = float('inf')

    def get_metrics(self) -> Dict[str, Any]:
        """Получение текущих метрик стратегии."""
        return self.metrics.to_dict()

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса стратегии."""
        return {
            'name': self.strategy_name,
            'window': self.window,
            'active_positions': len(self._active_positions),
            'metrics': self.get_metrics(),
            'last_signals': {
                k: {'type': v.type.name,
                    'confidence': v.confidence, 'symbol': v.symbol}
                for k, v in self._last_signals.items()
            }
        }
