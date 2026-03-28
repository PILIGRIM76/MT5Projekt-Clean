# src/strategies/adaptive.py
"""
Adaptive Strategy v2.0 - Адаптивная стратегия с динамическим переключением.

Особенности:
- Динамическое переключение между breakout и mean reversion
- Учёт режима рынка для выбора стратегии
- Взвешенный консенсус стратегий
- Расширенное логирование решений
- Метрики производительности

Автор: Genesis Trading System
Версия: 2.0.0
"""
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
import pandas as pd

from src.data_models import TradeSignal, SignalType
from src.core.config_models import Settings
from .StrategyInterface import BaseStrategy
from .breakout import BreakoutStrategy
from .mean_reversion import MeanReversionStrategy

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveMetrics:
    """Метрики адаптивной стратегии."""
    total_signals: int = 0
    consensus_signals: int = 0
    breakout_only_signals: int = 0
    reversion_only_signals: int = 0
    successful_predictions: int = 0
    avg_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь."""
        return {
            'total_signals': self.total_signals,
            'consensus_signals': self.consensus_signals,
            'breakout_only_signals': self.breakout_only_signals,
            'reversion_only_signals': self.reversion_only_signals,
            'avg_confidence': round(self.avg_confidence, 3)
        }


class AdaptiveStrategy(BaseStrategy):
    """
    Адаптивная стратегия с динамическим выбором подхода.

    Принципы работы:
    1. Получение сигналов от breakout и mean reversion стратегий
    2. Проверка консенсуса между стратегиями
    3. Динамическое взвешивание на основе режима рынка
    4. Возврат сигнала с наивысшей уверенностью
    """

    def __init__(self, config: Settings):
        super().__init__(config)

        # Инициализация под-стратегий
        self.strategies = {
            'breakout': BreakoutStrategy(config),
            'mean_reversion': MeanReversionStrategy(config)
        }

        # Базовые веса
        self.weights = {'breakout': 0.5, 'mean_reversion': 0.5}

        # Метрики
        self.metrics = AdaptiveMetrics()

        # Кэш последних сигналов
        self._last_signals: Dict[str,
                                 Tuple[Optional[TradeSignal], Optional[TradeSignal]]] = {}

        logger.info("AdaptiveStrategy инициализирована")

    def check_entry_conditions(
        self,
        df: pd.DataFrame,
        current_index: int,
        timeframe: int,
        symbol: str = None
    ) -> Optional[TradeSignal]:
        """
        Проверка условий для входа с адаптивным выбором стратегии.

        Args:
            df: DataFrame с данными
            current_index: Индекс текущей свечи
            timeframe: Таймфрейм в минутах
            symbol: Символ для торговли (опционально)

        Returns:
            TradeSignal или None
        """
        # Получение сигналов от под-стратегий с передачей symbol
        breakout_signal = self.strategies['breakout'].check_entry_conditions(
            df, current_index, timeframe, symbol
        )
        reversion_signal = self.strategies['mean_reversion'].check_entry_conditions(
            df, current_index, timeframe, symbol
        )

        # Сохранение в кэш
        self._last_signals[f"{df['symbol'].iloc[current_index] if 'symbol' in df.columns else (symbol if symbol else 'UNKNOWN')}_{current_index}"] = (
            breakout_signal,
            reversion_signal
        )

        # Получение символа с использованием default_symbol
        symbol = self._get_symbol_from_dataframe(df, current_index, default_symbol=symbol)
        if symbol == 'UNKNOWN':
            logger.warning(
                f"Не удалось определить символ для Adaptive стратегии")
            return None

        # Обновление метрик
        self.metrics.total_signals += 1

        # Проверка консенсуса
        if breakout_signal and reversion_signal:
            if breakout_signal.type == reversion_signal.type:
                # Полный консенсус - максимальная уверенность
                self.metrics.consensus_signals += 1
                avg_confidence = (breakout_signal.confidence +
                                  reversion_signal.confidence) / 2
                enhanced_confidence = min(
                    0.95, avg_confidence * 1.2)  # Бонус за консенсус

                logger.info(
                    f"AdaptiveStrategy | {symbol} | КОНСЕНСУС | {breakout_signal.type.name} | "
                    f"Confidence: {enhanced_confidence:.2f} | "
                    f"Breakout: {breakout_signal.confidence:.2f} | "
                    f"MeanRev: {reversion_signal.confidence:.2f}"
                )

                return TradeSignal(
                    type=breakout_signal.type,
                    confidence=round(enhanced_confidence, 3),
                    symbol=symbol,
                    strategy_name=self.__class__.__name__,
                    entry_price=breakout_signal.entry_price or reversion_signal.entry_price,
                    stop_loss=breakout_signal.stop_loss or reversion_signal.stop_loss,
                    take_profit=breakout_signal.take_profit or reversion_signal.take_profit
                )
            else:
                # Противоположные сигналы - логирование конфликта
                logger.debug(
                    f"AdaptiveStrategy | {symbol} | КОНФЛИКТ | "
                    f"Breakout: {breakout_signal.type.name} ({breakout_signal.confidence:.2f}) | "
                    f"MeanRev: {reversion_signal.type.name} ({reversion_signal.confidence:.2f})"
                )
                # Возвращаем сигнал с более высокой уверенностью
                return self._select_best_signal(breakout_signal, reversion_signal, symbol)

        # Только один сигнал
        if breakout_signal:
            self.metrics.breakout_only_signals += 1
            logger.debug(
                f"AdaptiveStrategy | {symbol} | Breakout сигнал | {breakout_signal.type.name}")
            return breakout_signal

        if reversion_signal:
            self.metrics.reversion_only_signals += 1
            logger.debug(
                f"AdaptiveStrategy | {symbol} | Mean Reversion сигнал | {reversion_signal.type.name}")
            return reversion_signal

        # Нет сигналов
        logger.debug(f"AdaptiveStrategy | {symbol} | Нет сигналов")
        return None

    def _select_best_signal(
        self,
        breakout: TradeSignal,
        reversion: TradeSignal,
        symbol: str
    ) -> TradeSignal:
        """
        Выбор лучшего сигнала при конфликте.

        Критерии:
        1. Более высокая уверенность
        2. Предпочтение breakout в тренде
        3. Предпочтение mean reversion во флэте
        """
        # Базовое правило - выбор по уверенности
        if breakout.confidence >= reversion.confidence:
            best_signal = breakout
            strategy_name = "Breakout"
        else:
            best_signal = reversion
            strategy_name = "Mean Reversion"

        # Корректировка весов на основе уверенности
        adjusted_confidence = best_signal.confidence * \
            0.9  # Штраф за отсутствие консенсуса

        logger.info(
            f"AdaptiveStrategy | {symbol} | Выбор | {strategy_name} | "
            f"{best_signal.type.name} | Confidence: {adjusted_confidence:.2f}"
        )

        # Возвращаем сигнал с откорректированной уверенностью
        return TradeSignal(
            type=best_signal.type,
            confidence=round(adjusted_confidence, 3),
            symbol=symbol,
            strategy_name=self.__class__.__name__,
            entry_price=best_signal.entry_price,
            stop_loss=best_signal.stop_loss,
            take_profit=best_signal.take_profit
        )

    def adjust_weights(self, market_regime: str):
        """
        Динамическая корректировка весов стратегий на основе режима рынка.

        Args:
            market_regime: Режим рынка
        """
        regime_mapping = {
            'Strong Trend': {'breakout': 0.7, 'mean_reversion': 0.3},
            'Weak Trend': {'breakout': 0.6, 'mean_reversion': 0.4},
            'Low Volatility Range': {'breakout': 0.3, 'mean_reversion': 0.7},
            'High Volatility': {'breakout': 0.5, 'mean_reversion': 0.5},
            # Минимальная активность
            'Toxic': {'breakout': 0.2, 'mean_reversion': 0.2}
        }

        if market_regime in regime_mapping:
            self.weights = regime_mapping[market_regime]
            logger.info(
                f"AdaptiveStrategy | Режим: {market_regime} | "
                f"Веса: Breakout={self.weights['breakout']:.1f}, "
                f"MeanRev={self.weights['mean_reversion']:.1f}"
            )
        else:
            # Режим по умолчанию
            self.weights = {'breakout': 0.5, 'mean_reversion': 0.5}
            logger.info(
                f"AdaptiveStrategy | Неизвестный режим: {market_regime} | Веса по умолчанию")

    def get_metrics(self) -> Dict[str, Any]:
        """Получение текущих метрик."""
        return {
            'name': 'AdaptiveStrategy',
            'metrics': self.metrics.to_dict(),
            'weights': self.weights,
            'last_signals_count': len(self._last_signals)
        }

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса стратегии."""
        return {
            'name': 'AdaptiveStrategy',
            'active': True,
            'strategies': list(self.strategies.keys()),
            'weights': self.weights,
            'metrics': self.get_metrics()
        }
