# src/strategies/features.py
"""
Feature Store - Единое хранилище технических индикаторов и признаков.
Используется всеми стратегиями для избежания дублирования кода.
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FeatureConfig:
    """Конфигурация для расчёта признаков."""
    atr_period: int = 14
    rsi_period: int = 14
    adx_period: int = 14
    volume_period: int = 20
    volatility_window: int = 20
    support_resistance_window: int = 50


class FeatureStore:
    """
    Централизованное хранилище признаков для всех стратегий.

    Возможности:
    - Расчёт технических индикаторов (ATR, RSI, ADX, и т.д.)
    - Кэширование рассчитанных признаков
    - Валидация данных
    - Метрики качества признаков
    """

    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()
        self._cache: Dict[str, pd.DataFrame] = {}
        self._metrics: Dict[str, Dict] = {}

    def calculate_all_features(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Рассчитать все доступные признаки для данных.

        Args:
            df: DataFrame с колонками [open, high, low, close, volume]
            symbol: Символ инструмента

        Returns:
            DataFrame с добавленными признаками
        """
        if df.empty:
            logger.warning(f"Пустые данные для {symbol}")
            return df

        # Валидация данных
        df = self._validate_data(df, symbol)

        # Технические индикаторы
        df = self._add_atr(df)
        df = self._add_rsi(df)
        df = self._add_adx(df)
        df = self._add_volatility_metrics(df)
        df = self._add_volume_profile(df)
        df = self._add_support_resistance(df)
        df = self._add_price_position(df)
        df = self._add_momentum(df)

        # Кэширование
        cache_key = f"{symbol}_features"
        self._cache[cache_key] = df.copy()

        logger.debug(f"Рассчитано {len(df.columns)} признаков для {symbol}")
        return df

    def _validate_data(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Валидация входных данных."""
        required_cols = ['open', 'high', 'low', 'close']
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            raise ValueError(
                f"Отсутствуют колонки для {symbol}: {missing_cols}")

        # Проверка на NaN
        nan_count = df[required_cols].isna().sum().sum()
        if nan_count > 0:
            logger.warning(
                f"{symbol}: найдено {nan_count} NaN значений, заполняем forward-fill")
            df = df.ffill().bfill()

        # Проверка на отрицательные цены
        if (df['close'] <= 0).any():
            logger.error(f"{symbol}: обнаружены отрицательные цены!")
            df = df[df['close'] > 0]

        return df

    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить Average True Range."""
        period = self.config.atr_period

        high = df['high']
        low = df['low']
        close = df['close'].shift(1)

        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = true_range.rolling(window=period).mean()

        # Нормализованный ATR (в % от цены)
        df['atr_pct'] = (df['atr'] / df['close'] * 100)

        return df

    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить Relative Strength Index."""
        period = self.config.rsi_period

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / (loss + 1e-10)  # Защита от деления на 0
        df['rsi'] = 100 - (100 / (1 + rs))

        return df

    def _add_adx(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить Average Directional Index."""
        period = self.config.adx_period

        high = df['high']
        low = df['low']
        close = df['close']

        # +DM и -DM
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Сглаживание
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / (atr + 1e-10))
        minus_di = 100 * \
            (minus_dm.rolling(window=period).mean() / (atr + 1e-10))

        # DX и ADX
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10))
        df['adx'] = dx.rolling(window=period).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di

        return df

    def _add_volatility_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить метрики волатильности."""
        window = self.config.volatility_window

        # Историческая волатильность (std returns)
        df['returns'] = df['close'].pct_change()
        df['volatility'] = df['returns'].rolling(
            window=window).std() * np.sqrt(252)

        # Volatility regime (высокая/низкая)
        vol_median = df['volatility'].rolling(window=window*2).median()
        df['volatility_regime'] = (df['volatility'] > vol_median).astype(int)

        # ATR ratio (текущий ATR к среднему)
        if 'atr' in df.columns:
            df['atr_ratio'] = df['atr'] / \
                df['atr'].rolling(window=window).mean()

        return df

    def _add_volume_profile(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить метрики объёма."""
        period = self.config.volume_period

        if 'volume' not in df.columns:
            logger.debug("Нет данных объёма, пропускаем volume_profile")
            return df

        # Относительный объём
        avg_volume = df['volume'].rolling(window=period).mean()
        df['volume_ratio'] = df['volume'] / (avg_volume + 1e-10)

        # Volume spike (аномальный объём)
        volume_std = df['volume'].rolling(window=period).std()
        df['volume_zscore'] = (
            df['volume'] - avg_volume) / (volume_std + 1e-10)

        return df

    def _add_support_resistance(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить уровни поддержки и сопротивления."""
        window = self.config.support_resistance_window

        # Локальные максимумы и минимумы
        df['local_max'] = df['high'].rolling(window=window, center=True).max()
        df['local_min'] = df['low'].rolling(window=window, center=True).min()

        # Расстояние до уровней
        df['dist_to_resistance'] = (
            df['local_max'] - df['close']) / df['close'] * 100
        df['dist_to_support'] = (
            df['close'] - df['local_min']) / df['close'] * 100

        return df

    def _add_price_position(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить позицию цены относительно диапазона."""
        window = self.config.volatility_window

        # Позиция в диапазоне (0 = min, 1 = max)
        rolling_min = df['low'].rolling(window=window).min()
        rolling_max = df['high'].rolling(window=window).max()
        range_size = rolling_max - rolling_min

        df['price_position'] = (
            df['close'] - rolling_min) / (range_size + 1e-10)

        # Близость к максимуму/минимуму
        df['near_high'] = (df['price_position'] > 0.8).astype(int)
        df['near_low'] = (df['price_position'] < 0.2).astype(int)

        return df

    def _add_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """Добавить метрики момента."""
        # ROC (Rate of Change)
        for period in [5, 10, 20]:
            df[f'roc_{period}'] = df['close'].pct_change(periods=period) * 100

        # Ускорение цены
        df['momentum_accel'] = df['returns'].diff()

        return df

    def get_cached_features(self, symbol: str) -> Optional[pd.DataFrame]:
        """Получить кэшированные признаки для символа."""
        cache_key = f"{symbol}_features"
        return self._cache.get(cache_key)

    def get_feature_importance(self, df: pd.DataFrame, target: pd.Series) -> pd.Series:
        """
        Оценить важность признаков через корреляцию с целевой переменной.

        Args:
            df: DataFrame с признаками
            target: Целевая переменная (например, будущий return)

        Returns:
            Series с важностью признаков
        """
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        correlations = {}

        for col in numeric_cols:
            if col not in target.index:
                continue
            corr = df[col].corr(target)
            if not np.isnan(corr):
                correlations[col] = abs(corr)

        importance = pd.Series(correlations).sort_values(ascending=False)
        logger.info(f"Топ-5 признаков: {importance.head().to_dict()}")

        return importance

    def get_metrics(self) -> Dict[str, Dict]:
        """Получить метрики качества признаков."""
        return self._metrics.copy()


@dataclass
class BreakoutFeatures:
    """Специфичные признаки для стратегии пробоя."""
    channel_high: float = 0.0
    channel_low: float = 0.0
    channel_width: float = 0.0
    price_position_in_channel: float = 0.5
    breakout_strength: float = 0.0
    false_breakout_probability: float = 0.5
    volume_confirmation: bool = False
    volatility_adjusted: bool = False


class BreakoutFeatureEngine:
    """
    Специализированный движок признаков для стратегии пробоя.

    Расширяет FeatureStore дополнительными признаками для breakout-стратегии.
    """

    def __init__(self, feature_store: FeatureStore):
        self.feature_store = feature_store
        self.logger = logging.getLogger(__name__)

    def calculate_breakout_features(
        self,
        df: pd.DataFrame,
        window: int,
        current_index: int
    ) -> BreakoutFeatures:
        """
        Рассчитать признаки для breakout-стратегии.

        Args:
            df: DataFrame с данными (должен содержать признаки из FeatureStore)
            window: Окно канала
            current_index: Текущий индекс свечи

        Returns:
            BreakoutFeatures с рассчитанными признаками
        """
        if current_index < window + 1:
            self.logger.warning(
                f"Недостаточно данных для расчёта (index={current_index}, window={window})")
            return BreakoutFeatures()

        # Канал
        rolling_high = df['high'].iloc[current_index -
                                       window:current_index].max()
        rolling_low = df['low'].iloc[current_index -
                                     window:current_index].min()

        current_price = df['close'].iloc[current_index]
        prev_price = df['close'].iloc[current_index - 1]

        channel_width = rolling_high - rolling_low
        price_position = (current_price - rolling_low) / \
            (channel_width + 1e-10)

        # Сила пробоя
        breakout_strength = 0.0
        if current_price > rolling_high:
            breakout_strength = (
                current_price - rolling_high) / rolling_high * 100
        elif current_price < rolling_low:
            breakout_strength = (
                rolling_low - current_price) / rolling_low * 100

        # Подтверждение объёмом (если есть данные)
        volume_confirmed = False
        if 'volume_ratio' in df.columns:
            volume_ratio = df['volume_ratio'].iloc[current_index]
            volume_confirmed = volume_ratio > 1.2  # Объём выше среднего на 20%

        # Вероятность ложного пробоя (на основе волатильности и позиции)
        false_prob = self._estimate_false_breakout_probability(
            df, current_index, rolling_high, rolling_low
        )

        # Волатильность-аджастированный флаг
        vol_adjusted = False
        if 'atr_ratio' in df.columns:
            atr_ratio = df['atr_ratio'].iloc[current_index]
            vol_adjusted = atr_ratio < 2.0  # ATR не превышает 2x от среднего

        return BreakoutFeatures(
            channel_high=rolling_high,
            channel_low=rolling_low,
            channel_width=channel_width,
            price_position_in_channel=price_position,
            breakout_strength=breakout_strength,
            false_breakout_probability=false_prob,
            volume_confirmation=volume_confirmed,
            volatility_adjusted=vol_adjusted
        )

    def _estimate_false_breakout_probability(
        self,
        df: pd.DataFrame,
        current_index: int,
        resistance: float,
        support: float
    ) -> float:
        """
        Оценить вероятность ложного пробоя на основе эвристик.

        Факторы:
        - Слабый момент (низкий ROC)
        - Отсутствие объёмного подтверждения
        - Высокая волатильность
        - Близость к противоположному уровню
        """
        probability = 0.5  # Базовая вероятность

        # Фактор 1: Волатильность
        if 'volatility_regime' in df.columns:
            vol_regime = df['volatility_regime'].iloc[current_index]
            if vol_regime == 1:  # Высокая волатильность
                probability += 0.15

        # Фактор 2: RSI (перекупленность/перепроданность)
        if 'rsi' in df.columns:
            rsi = df['rsi'].iloc[current_index]
            if rsi > 70 or rsi < 30:
                probability += 0.1  # Экстремальный RSI

        # Фактор 3: ADX (сила тренда)
        if 'adx' in df.columns:
            adx = df['adx'].iloc[current_index]
            if adx < 20:  # Слабый тренд
                probability += 0.15

        # Фактор 4: Объём
        if 'volume_ratio' in df.columns:
            volume_ratio = df['volume_ratio'].iloc[current_index]
            if volume_ratio < 1.0:  # Объём ниже среднего
                probability += 0.1

        # Ограничение диапазона [0, 1]
        probability = max(0.0, min(1.0, probability))

        return probability
