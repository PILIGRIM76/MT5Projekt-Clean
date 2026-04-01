# -*- coding: utf-8 -*-
"""
Unit тесты для моделей конфигурации (config_models.py).

Тестирует:
- Валидация Pydantic моделей
- Значения по умолчанию
- Сериализация/десериализация
"""

import pytest
from pydantic import ValidationError

from src.core.config_models import (
    BreakoutStrategyParams,
    MACrossoverStrategyParams,
    MACrossoverTimeframeParams,
    MeanReversionStrategyParams,
    ModelCandidate,
    RDCycleSettings,
    ScreenerLiquiditySettings,
    ScreenerTrendSettings,
    ScreenerVolatilitySettings,
    ScreenerWeightsSettings,
    StrategiesParams,
)


class TestScreenerSettings:
    """Тесты настроек скринера."""

    def test_volatility_settings_defaults(self):
        """Проверка значений по умолчанию."""
        settings = ScreenerVolatilitySettings()

        assert settings.ideal_min_percent == 0.05
        assert settings.ideal_max_percent == 0.5

    def test_volatility_settings_custom(self):
        """Проверка кастомных значений."""
        settings = ScreenerVolatilitySettings(ideal_min_percent=0.1, ideal_max_percent=0.6)

        assert settings.ideal_min_percent == 0.1
        assert settings.ideal_max_percent == 0.6

    def test_trend_settings_defaults(self):
        """Проверка настроек тренда."""
        settings = ScreenerTrendSettings()

        assert settings.adx_threshold == 20

    def test_liquidity_settings_defaults(self):
        """Проверка настроек ликвидности."""
        settings = ScreenerLiquiditySettings()

        assert settings.ideal_max_spread_pips == 5.0

    def test_weights_settings_defaults(self):
        """Проверка настроек весов."""
        settings = ScreenerWeightsSettings()

        assert settings.volatility == 0.6
        assert settings.trend == 0.3
        assert settings.liquidity == 0.1

    def test_weights_sum(self):
        """Проверка что сумма весов близка к 1.0."""
        settings = ScreenerWeightsSettings()

        assert abs(settings.volatility + settings.trend + settings.liquidity - 1.0) < 0.01


class TestStrategyParams:
    """Тесты параметров стратегий."""

    def test_breakout_strategy_defaults(self):
        """Проверка настроек стратегии пробоя."""
        params = BreakoutStrategyParams()

        assert params.window == 15

    def test_breakout_strategy_custom(self):
        """Проверка кастомных настроек пробоя."""
        params = BreakoutStrategyParams(window=20)

        assert params.window == 20

    def test_mean_reversion_defaults(self):
        """Проверка настроек mean reversion."""
        params = MeanReversionStrategyParams()

        assert params.window == 50
        assert params.std_dev_multiplier == 1.9
        assert params.confirmation_buffer_std_dev_fraction == 0.05

    def test_ma_crossover_timeframe_defaults(self):
        """Проверка настроек MA кроссовера."""
        params = MACrossoverTimeframeParams()

        assert params.short_window == 15
        assert params.long_window == 35

    def test_ma_crossover_strategy_defaults(self):
        """Проверка стратегии MA кроссовера."""
        params = MACrossoverStrategyParams()

        assert "default" in params.timeframe_params
        assert "low" in params.timeframe_params
        assert "high" in params.timeframe_params

    def test_ma_crossover_strategy_custom(self):
        """Проверка кастомных настроек MA кроссовера."""
        custom_params = {
            "default": MACrossoverTimeframeParams(short_window=10, long_window=20),
        }
        params = MACrossoverStrategyParams(timeframe_params=custom_params)

        assert params.timeframe_params["default"].short_window == 10
        assert params.timeframe_params["default"].long_window == 20

    def test_strategies_params_defaults(self):
        """Проверка всех стратегий."""
        params = StrategiesParams()

        assert isinstance(params.breakout, BreakoutStrategyParams)
        assert isinstance(params.mean_reversion, MeanReversionStrategyParams)
        assert isinstance(params.ma_crossover, MACrossoverStrategyParams)


class TestModelCandidate:
    """Тесты модели кандидата."""

    def test_model_candidate_defaults(self):
        """Проверка значений по умолчанию."""
        candidate = ModelCandidate()

        assert candidate.type == "LSTM_PyTorch"
        assert candidate.k == "all"

    def test_model_candidate_custom(self):
        """Проверка кастомных значений."""
        candidate = ModelCandidate(type="LightGBM", k=10)

        assert candidate.type == "LightGBM"
        assert candidate.k == 10


class TestRDCycleSettings:
    """Тесты настроек R&D цикла."""

    def test_rd_settings_defaults(self):
        """Проверка значений по умолчанию."""
        settings = RDCycleSettings()

        assert settings.sharpe_ratio_threshold == 1.2
        assert settings.max_drawdown_threshold == 15.0

    def test_rd_settings_custom(self):
        """Проверка кастомных значений."""
        settings = RDCycleSettings(sharpe_ratio_threshold=1.5, max_drawdown_threshold=10.0)

        assert settings.sharpe_ratio_threshold == 1.5
        assert settings.max_drawdown_threshold == 10.0


class TestConfigModelsValidation:
    """Тесты валидации моделей."""

    def test_volatility_settings_negative_value(self):
        """Проверка отрицательных значений."""
        # Pydantic должен принять отрицательное значение (нет валидации)
        settings = ScreenerVolatilitySettings(ideal_min_percent=-0.1)

        assert settings.ideal_min_percent == -0.1

    def test_breakout_strategy_zero_window(self):
        """Проверка нулевого окна."""
        params = BreakoutStrategyParams(window=0)

        assert params.window == 0

    def test_model_candidate_empty_type(self):
        """Проверка пустого типа."""
        candidate = ModelCandidate(type="")

        assert candidate.type == ""

    def test_serialization_deserialization(self):
        """Проверка сериализации/десериализации."""
        params = BreakoutStrategyParams(window=25)

        # Сериализация
        data = params.model_dump()

        assert data["window"] == 25

        # Десериализация
        params_restored = BreakoutStrategyParams.model_validate(data)

        assert params_restored.window == 25

    def test_json_serialization(self):
        """Проверка JSON сериализации."""
        import json

        params = BreakoutStrategyParams(window=30)

        # JSON сериализация
        json_str = params.model_dump_json()
        data = json.loads(json_str)

        assert data["window"] == 30
