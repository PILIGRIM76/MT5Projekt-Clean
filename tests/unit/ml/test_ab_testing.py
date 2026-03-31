# -*- coding: utf-8 -*-
"""
Тесты для ABTestingFramework.

Проверяет:
- Запуск A/B теста
- Запись сделок
- Статистический анализ
- Определение победителя
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ml.ab_testing import (
    ABTestConfig,
    ABTestingFramework,
    ABTestResult,
    TestResult,
    TestStatus,
)

# ===========================================
# Фикстуры
# ===========================================


@pytest.fixture
def mock_db_manager():
    """Мок DatabaseManager."""
    db_manager = MagicMock()
    db_manager.Session = MagicMock()
    db_manager.engine = MagicMock()

    session = MagicMock()
    db_manager.Session.return_value = session

    return db_manager


@pytest.fixture
def ab_framework(mock_db_manager):
    """Фикстура ABTestingFramework."""
    return ABTestingFramework(
        db_manager=mock_db_manager,
        total_capital=10000.0,
    )


# ===========================================
# Тесты ABTestConfig
# ===========================================


class TestABTestConfig:
    """Тесты ABTestConfig dataclass."""

    def test_default_values(self):
        """Тест значений по умолчанию."""
        config = ABTestConfig(
            strategy_a="StrategyA",
            strategy_b="StrategyB",
            symbol="EURUSD",
        )

        assert config.duration_days == 30
        assert config.capital_allocation_a == 0.5
        assert config.capital_allocation_b == 0.5
        assert config.confidence_level == 0.95
        assert config.min_trades == 30

    def test_custom_values(self):
        """Тест кастомных значений."""
        config = ABTestConfig(
            strategy_a="LightGBM",
            strategy_b="LSTM",
            symbol="GBPUSD",
            duration_days=60,
            capital_allocation_a=0.6,
            capital_allocation_b=0.4,
        )

        assert config.duration_days == 60
        assert config.capital_allocation_a == 0.6
        assert config.capital_allocation_b == 0.4


# ===========================================
# Тесты start_test
# ===========================================


class TestStartTest:
    """Тесты start_test."""

    def test_start_test(self, ab_framework):
        """Тест запуска теста."""
        test_id = ab_framework.start_test(
            strategy_a="StrategyA",
            strategy_b="StrategyB",
            symbol="EURUSD",
            duration_days=30,
        )

        assert test_id.startswith("ab_EURUSD_")
        assert test_id in ab_framework.active_tests

        config = ab_framework.active_tests[test_id]
        assert config.strategy_a == "StrategyA"
        assert config.strategy_b == "StrategyB"
        assert config.symbol == "EURUSD"

    def test_start_test_custom_allocation(self, ab_framework):
        """Тест с кастомным распределением капитала."""
        test_id = ab_framework.start_test(
            strategy_a="A",
            strategy_b="B",
            symbol="USDJPY",
            capital_allocation_a=0.7,
            capital_allocation_b=0.3,
        )

        config = ab_framework.active_tests[test_id]
        assert config.capital_allocation_a == 0.7
        assert config.capital_allocation_b == 0.3


# ===========================================
# Тесты record_trade
# ===========================================


class TestRecordTrade:
    """Тесты record_trade."""

    def test_record_trade(self, ab_framework):
        """Тест записи сделки."""
        test_id = ab_framework.start_test("A", "B", "EURUSD")

        ab_framework.record_trade(
            test_id=test_id,
            strategy="A",
            pnl=50.0,
            trade_duration=10,
            max_drawdown=0.02,
        )

        # Проверяем что сделка записана (через мок БД)
        ab_framework.db_manager.Session.assert_called()

    def test_record_trade_invalid_test(self, ab_framework):
        """Тест записи в несуществующий тест."""
        ab_framework.record_trade(
            test_id="invalid_test",
            strategy="A",
            pnl=50.0,
            trade_duration=10,
        )
        # Не должно выбрасывать исключение


# ===========================================
# Тесты analyze_test
# ===========================================


class TestAnalyzeTest:
    """Тесты analyze_test."""

    def test_analyze_test_not_found(self, ab_framework):
        """Тест анализа несуществующего теста."""
        result = ab_framework.analyze_test("invalid_test")

        assert result.status == TestStatus.FAILED
        assert "not found" in result.recommendation.lower()

    @patch.object(ABTestingFramework, "_get_test_trades")
    def test_analyze_test_insufficient_trades(self, mock_get_trades, ab_framework):
        """Тест с недостаточным количеством сделок."""
        test_id = ab_framework.start_test("A", "B", "EURUSD")

        # Возвращаем мало сделок
        mock_get_trades.return_value = (
            np.array([10.0, 20.0]),  # Strategy A: 2 сделки
            np.array([15.0, 25.0]),  # Strategy B: 2 сделки
        )

        result = ab_framework.analyze_test(test_id)

        assert result.status == TestStatus.RUNNING
        assert "Недостаточно сделок" in result.recommendation

    @patch.object(ABTestingFramework, "_get_test_trades")
    def test_analyze_test_strategy_a_wins(self, mock_get_trades, ab_framework):
        """Тест когда стратегия A выигрывает."""
        test_id = ab_framework.start_test("A", "B", "EURUSD")

        # Стратегия A значительно лучше
        mock_get_trades.return_value = (
            np.array([50.0, 60.0, 55.0, 65.0, 58.0] * 10),  # A: ~57.6 средняя
            np.array([10.0, 15.0, 12.0, 18.0, 14.0] * 10),  # B: ~13.8 средняя
        )

        result = ab_framework.analyze_test(test_id)

        assert result.status == TestStatus.COMPLETED
        assert result.result == TestResult.STRATEGY_A_WINS
        assert result.p_value < 0.05  # Статистически значимо

    @patch.object(ABTestingFramework, "_get_test_trades")
    def test_analyze_test_no_significant_difference(self, mock_get_trades, ab_framework):
        """Тест без значимой разницы."""
        test_id = ab_framework.start_test("A", "B", "EURUSD")

        # Одинаковые стратегии
        mock_get_trades.return_value = (
            np.random.randn(50) * 10 + 20,  # A: mean=20
            np.random.randn(50) * 10 + 20,  # B: mean=20
        )

        result = ab_framework.analyze_test(test_id)

        assert result.status == TestStatus.COMPLETED
        assert result.result == TestResult.NO_SIGNIFICANT_DIFFERENCE
        assert result.p_value > 0.05  # Не значимо


# ===========================================
# Тесты _compute_metrics
# ===========================================


class TestComputeMetrics:
    """Тесты _compute_metrics."""

    def test_compute_metrics_basic(self, ab_framework):
        """Тест вычисления метрик."""
        trades = np.array([50.0, -20.0, 30.0, -10.0, 40.0])

        metrics = ab_framework._compute_metrics(trades)

        assert "total_pnl" in metrics
        assert "sharpe_ratio" in metrics
        assert "win_rate" in metrics
        assert "profit_factor" in metrics
        assert "max_drawdown" in metrics
        assert metrics["total_trades"] == 5

    def test_compute_metrics_empty(self, ab_framework):
        """Тест с пустыми сделками."""
        trades = np.array([])

        metrics = ab_framework._compute_metrics(trades)

        assert metrics == {}

    def test_compute_metrics_all_wins(self, ab_framework):
        """Тест с выигрышными сделками."""
        trades = np.array([10.0, 20.0, 30.0])

        metrics = ab_framework._compute_metrics(trades)

        assert metrics["win_rate"] == 1.0
        assert metrics["profit_factor"] == float("inf") or metrics["profit_factor"] == 999.99

    def test_compute_metrics_all_losses(self, ab_framework):
        """Тест с убыточными сделками."""
        trades = np.array([-10.0, -20.0, -30.0])

        metrics = ab_framework._compute_metrics(trades)

        assert metrics["win_rate"] == 0.0


# ===========================================
# Тесты stop_test
# ===========================================


class TestStopTest:
    """Тесты stop_test."""

    def test_stop_test(self, ab_framework):
        """Тест остановки теста."""
        test_id = ab_framework.start_test("A", "B", "EURUSD")

        result = ab_framework.stop_test(test_id, reason="Manual stop")

        assert result is True
        assert test_id not in ab_framework.active_tests

    def test_stop_test_invalid(self, ab_framework):
        """Тест остановки несуществующего теста."""
        result = ab_framework.stop_test("invalid_test")

        assert result is False


# ===========================================
# Тесты get_test_results
# ===========================================


class TestGetTestResults:
    """Тесты get_test_results."""

    def test_get_test_results_not_started(self, ab_framework):
        """Тест получения результатов незапущенного теста."""
        results = ab_framework.get_test_results("invalid_test")

        assert results is None


# ===========================================
# Тесты get_active_tests
# ===========================================


class TestGetActiveTests:
    """Тесты get_active_tests."""

    def test_get_active_tests_empty(self, ab_framework):
        """Тест пустого списка."""
        tests = ab_framework.get_active_tests()

        assert tests == []

    def test_get_active_tests_with_tests(self, ab_framework):
        """Тест с активными тестами."""
        test_id1 = ab_framework.start_test("A", "B", "EURUSD")
        test_id2 = ab_framework.start_test("C", "D", "GBPUSD")

        tests = ab_framework.get_active_tests()

        assert len(tests) == 2
        test_ids = [t["test_id"] for t in tests]
        assert test_id1 in test_ids
        assert test_id2 in test_ids


# ===========================================
# Интеграционные тесты
# ===========================================


class TestABTestingIntegration:
    """Интеграционные тесты ABTestingFramework."""

    @patch.object(ABTestingFramework, "_get_test_trades")
    def test_full_ab_test_workflow(self, mock_get_trades, ab_framework):
        """Тест полного рабочего процесса A/B теста."""
        # 1. Запуск теста
        test_id = ab_framework.start_test(
            strategy_a="LightGBM_v1",
            strategy_b="LightGBM_v2",
            symbol="EURUSD",
            duration_days=30,
        )

        assert test_id in ab_framework.active_tests

        # 2. Запись сделок
        for i in range(35):
            ab_framework.record_trade(
                test_id=test_id,
                strategy="A",
                pnl=np.random.randn() * 10 + 5,
                trade_duration=5,
            )
            ab_framework.record_trade(
                test_id=test_id,
                strategy="B",
                pnl=np.random.randn() * 10 + 15,  # B лучше
                trade_duration=5,
            )

        # 3. Мок получения сделок
        mock_get_trades.return_value = (
            np.random.randn(35) * 10 + 5,  # A: mean=5
            np.random.randn(35) * 10 + 15,  # B: mean=15
        )

        # 4. Анализ
        result = ab_framework.analyze_test(test_id)

        assert result.status == TestStatus.COMPLETED
        assert "strategy_b_metrics" in result.strategy_b_metrics
        assert result.strategy_b_metrics["total_trades"] == 35

        # 5. Получение результатов
        results = ab_framework.get_test_results(test_id)

        assert results is not None
        assert results["status"] == "completed"
