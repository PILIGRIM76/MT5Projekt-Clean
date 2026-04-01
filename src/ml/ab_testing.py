# src/ml/ab_testing.py
"""
A/B тестирование торговых стратегий для Genesis Trading System.

Поддерживает:
- Разделение капитала на контрольную и тестовую группы
- Статистическая значимость (t-test)
- Метрики сравнения (Sharpe, Sortino, Max DD)
- Автоматическое переключение на лучшую стратегию

Пример использования:
    ab_test = ABTestingFramework(db_manager, capital=10000)

    # Запуск теста
    ab_test.start_test(
        strategy_a="LightGBM_v1",
        strategy_b="LightGBM_v2",
        symbol="EURUSD",
        duration_days=30,
    )

    # Проверка результатов
    results = ab_test.get_test_results(test_id)
    if results["statistically_significant"]:
        ab_test.promote_winner()
"""

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from src.core.config_models import Settings
from src.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class TestStatus(Enum):
    """Статус A/B теста."""

    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class TestResult(Enum):
    """Результат A/B теста."""

    STRATEGY_A_WINS = "strategy_a_wins"
    STRATEGY_B_WINS = "strategy_b_wins"
    NO_SIGNIFICANT_DIFFERENCE = "no_significant_difference"
    INCONCLUSIVE = "inconclusive"


@dataclass
class ABTestConfig:
    """Конфигурация A/B теста."""

    strategy_a: str
    strategy_b: str
    symbol: str
    duration_days: int = 30
    capital_allocation_a: float = 0.5  # 50% капитала
    capital_allocation_b: float = 0.5  # 50% капитала
    confidence_level: float = 0.95  # 95% доверительный уровень
    min_trades: int = 30  # Минимальное количество сделок
    max_drawdown_stop: float = 0.10  # Остановка при просадке 10%


@dataclass
class ABTestResult:
    """Результаты A/B теста."""

    test_id: str
    status: TestStatus
    result: Optional[TestResult] = None
    p_value: float = 0.0
    confidence_interval: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))
    strategy_a_metrics: Dict[str, float] = field(default_factory=dict)
    strategy_b_metrics: Dict[str, float] = field(default_factory=dict)
    statistical_power: float = 0.0
    recommendation: str = ""


class ABTestingFramework:
    """
    Фреймворк A/B тестирования стратегий.

    Атрибуты:
        db_manager: Менеджер базы данных
        config: Конфигурация системы
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        config: Optional[Settings] = None,
        total_capital: float = 10000.0,
    ):
        """
        Инициализация фреймворка.

        Args:
            db_manager: Менеджер базы данных
            config: Конфигурация системы
            total_capital: Общий капитал для тестирования
        """
        self.db_manager = db_manager
        self.config = config
        self.total_capital = total_capital

        # Активные тесты
        self.active_tests: Dict[str, ABTestConfig] = {}

        # Результаты тестов
        self.test_results: Dict[str, ABTestResult] = {}

        logger.info(f"ABTestingFramework инициализирован (капитал: ${total_capital:.2f})")

    def start_test(
        self,
        strategy_a: str,
        strategy_b: str,
        symbol: str,
        duration_days: int = 30,
        capital_allocation_a: float = 0.5,
        capital_allocation_b: float = 0.5,
        confidence_level: float = 0.95,
    ) -> str:
        """
        Запуск A/B теста.

        Args:
            strategy_a: Контрольная стратегия
            strategy_b: Тестовая стратегия
            symbol: Символ для торговли
            duration_days: Длительность теста в днях
            capital_allocation_a: Доля капитала для стратегии A
            capital_allocation_b: Доля капитала для стратегии B
            confidence_level: Доверительный уровень

        Returns:
            ID теста
        """
        # Генерируем ID теста
        test_id = f"ab_{symbol}_{strategy_a[:3]}_{strategy_b[:3]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Создаём конфигурацию
        config = ABTestConfig(
            strategy_a=strategy_a,
            strategy_b=strategy_b,
            symbol=symbol,
            duration_days=duration_days,
            capital_allocation_a=capital_allocation_a,
            capital_allocation_b=capital_allocation_b,
            confidence_level=confidence_level,
        )

        # Сохраняем тест
        self.active_tests[test_id] = config

        # Сохраняем в БД
        self._save_test_to_db(test_id, config)

        logger.info(
            f"Запущен A/B тест {test_id}: "
            f"{strategy_a} vs {strategy_b} на {symbol} "
            f"(длительность: {duration_days} дней)"
        )

        return test_id

    def _save_test_to_db(self, test_id: str, config: ABTestConfig) -> None:
        """Сохранение теста в БД."""
        from sqlalchemy import Column, DateTime, Float, Integer, String, Text
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class ABTest(Base):
            __tablename__ = "ab_tests"

            id = Column(Integer, primary_key=True)
            test_id = Column(String, unique=True, nullable=False, index=True)
            strategy_a = Column(String, nullable=False)
            strategy_b = Column(String, nullable=False)
            symbol = Column(String, nullable=False)
            start_date = Column(DateTime, default=datetime.utcnow)
            end_date = Column(DateTime, nullable=True)
            duration_days = Column(Integer, nullable=False)
            capital_allocation_a = Column(Float, nullable=False)
            capital_allocation_b = Column(Float, nullable=False)
            confidence_level = Column(Float, nullable=False)
            status = Column(String, default="running")
            results_json = Column(Text, nullable=True)

        # Создаём таблицу
        Base.metadata.create_all(self.db_manager.engine)

        # Сохраняем
        session = self.db_manager.Session()

        try:
            ab_test = ABTest(
                test_id=test_id,
                strategy_a=config.strategy_a,
                strategy_b=config.strategy_b,
                symbol=config.symbol,
                duration_days=config.duration_days,
                capital_allocation_a=config.capital_allocation_a,
                capital_allocation_b=config.capital_allocation_b,
                confidence_level=config.confidence_level,
            )

            session.add(ab_test)
            session.commit()

        finally:
            session.close()

    def record_trade(
        self,
        test_id: str,
        strategy: str,
        pnl: float,
        trade_duration: int,
        max_drawdown: float = 0.0,
    ) -> None:
        """
        Запись результата сделки в тест.

        Args:
            test_id: ID теста
            strategy: Стратегия (A или B)
            pnl: Прибыль/убыток
            trade_duration: Длительность сделки (в барах)
            max_drawdown: Максимальная просадка во время сделки
        """
        if test_id not in self.active_tests:
            logger.error(f"Тест {test_id} не найден")
            return

        from sqlalchemy import Column, DateTime, Float, Integer, String
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class ABTestTrade(Base):
            __tablename__ = "ab_test_trades"

            id = Column(Integer, primary_key=True)
            test_id = Column(String, nullable=False, index=True)
            strategy = Column(String, nullable=False)  # "A" или "B"
            pnl = Column(Float, nullable=False)
            trade_duration = Column(Integer, nullable=True)
            max_drawdown = Column(Float, nullable=True)
            timestamp = Column(DateTime, default=datetime.utcnow)

        # Создаём таблицу
        Base.metadata.create_all(self.db_manager.engine)

        # Сохраняем сделку
        session = self.db_manager.Session()

        try:
            trade = ABTestTrade(
                test_id=test_id,
                strategy=strategy,
                pnl=pnl,
                trade_duration=trade_duration,
                max_drawdown=max_drawdown,
            )

            session.add(trade)
            session.commit()

        finally:
            session.close()

    def analyze_test(self, test_id: str) -> ABTestResult:
        """
        Анализ результатов A/B теста.

        Args:
            test_id: ID теста

        Returns:
            Результаты теста
        """
        if test_id not in self.active_tests:
            return ABTestResult(
                test_id=test_id,
                status=TestStatus.FAILED,
                recommendation="Test not found",
            )

        config = self.active_tests[test_id]

        # Получаем сделки из БД
        trades_a, trades_b = self._get_test_trades(test_id)

        if len(trades_a) < config.min_trades or len(trades_b) < config.min_trades:
            return ABTestResult(
                test_id=test_id,
                status=TestStatus.RUNNING,
                recommendation=f"Недостаточно сделок (A: {len(trades_a)}, B: {len(trades_b)})",
            )

        # Вычисляем метрики
        metrics_a = self._compute_metrics(trades_a)
        metrics_b = self._compute_metrics(trades_b)

        # Статистический тест (t-test для Sharpe ratio)
        t_stat, p_value = stats.ttest_ind(trades_a, trades_b)

        # Доверительный интервал разницы
        diff = np.mean(trades_a) - np.mean(trades_b)
        se = statistics.stdev(trades_a) / np.sqrt(len(trades_a)) + statistics.stdev(trades_b) / np.sqrt(len(trades_b))
        ci_low = diff - 1.96 * se
        ci_high = diff + 1.96 * se

        # Определяем победителя
        alpha = 1 - config.confidence_level

        if p_value < alpha:
            if np.mean(trades_a) > np.mean(trades_b):
                result = TestResult.STRATEGY_A_WINS
                recommendation = f"Стратегия A ({config.strategy_a}) статистически значимо лучше (p={p_value:.4f})"
            else:
                result = TestResult.STRATEGY_B_WINS
                recommendation = f"Стратегия B ({config.strategy_b}) статистически значимо лучше (p={p_value:.4f})"
        else:
            result = TestResult.NO_SIGNIFICANT_DIFFERENCE
            recommendation = f"Нет статистически значимой разницы (p={p_value:.4f})"

        # Статистическая сила
        power = self._compute_statistical_power(trades_a, trades_b, alpha)

        # Создаём результат
        test_result = ABTestResult(
            test_id=test_id,
            status=TestStatus.COMPLETED,
            result=result,
            p_value=round(p_value, 4),
            confidence_interval=(round(ci_low, 4), round(ci_high, 4)),
            strategy_a_metrics=metrics_a,
            strategy_b_metrics=metrics_b,
            statistical_power=round(power, 3),
            recommendation=recommendation,
        )

        # Сохраняем результат
        self.test_results[test_id] = test_result
        self._update_test_in_db(test_id, test_result)

        logger.info(f"Анализ теста {test_id}: {recommendation}")

        return test_result

    def _get_test_trades(self, test_id: str) -> Tuple[np.ndarray, np.ndarray]:
        """Получение сделок из БД."""
        from sqlalchemy import Column, DateTime, Float, Integer, String
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class ABTestTrade(Base):
            __tablename__ = "ab_test_trades"

            id = Column(Integer, primary_key=True)
            test_id = Column(String, nullable=False)
            strategy = Column(String, nullable=False)
            pnl = Column(Float, nullable=False)
            timestamp = Column(DateTime, nullable=False)

        session = self.db_manager.Session()

        try:
            trades_a = (
                session.query(ABTestTrade.pnl)
                .filter(
                    ABTestTrade.test_id == test_id,
                    ABTestTrade.strategy == "A",
                )
                .all()
            )

            trades_b = (
                session.query(ABTestTrade.pnl)
                .filter(
                    ABTestTrade.test_id == test_id,
                    ABTestTrade.strategy == "B",
                )
                .all()
            )

            return (
                np.array([t[0] for t in trades_a]),
                np.array([t[0] for t in trades_b]),
            )

        finally:
            session.close()

    def _compute_metrics(self, trades: np.ndarray) -> Dict[str, float]:
        """Вычисление метрик для сделок."""
        if len(trades) == 0:
            return {}

        # Основные метрики
        total_pnl = np.sum(trades)
        mean_pnl = np.mean(trades)
        std_pnl = np.std(trades)

        # Sharpe ratio (предполагаем 252 торговых дня)
        sharpe = (mean_pnl / std_pnl) * np.sqrt(252) if std_pnl > 0 else 0

        # Sortino ratio (только downside волатильность)
        downside_trades = trades[trades < 0]
        downside_std = np.std(downside_trades) if len(downside_trades) > 0 else 0.001
        sortino = (mean_pnl / downside_std) * np.sqrt(252)

        # Win rate
        win_rate = np.sum(trades > 0) / len(trades)

        # Profit factor
        gross_profit = np.sum(trades[trades > 0])
        gross_loss = abs(np.sum(trades[trades < 0]))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Max drawdown
        cumulative = np.cumsum(trades)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / peak
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0

        return {
            "total_pnl": round(total_pnl, 2),
            "mean_pnl": round(mean_pnl, 4),
            "std_pnl": round(std_pnl, 4),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "win_rate": round(win_rate, 3),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else 999.99,
            "max_drawdown": round(max_drawdown, 3),
            "total_trades": len(trades),
        }

    def _compute_statistical_power(
        self,
        trades_a: np.ndarray,
        trades_b: np.ndarray,
        alpha: float,
    ) -> float:
        """Вычисление статистической силы теста."""
        from statsmodels.stats.power import TTestIndPower

        try:
            # Эффект размера
            n1, n2 = len(trades_a), len(trades_b)
            mean1, mean2 = np.mean(trades_a), np.mean(trades_b)
            std1, std2 = np.std(trades_a), np.std(trades_b)

            # Объединённое стандартное отклонение
            pooled_std = np.sqrt(((n1 - 1) * std1**2 + (n2 - 1) * std2**2) / (n1 + n2 - 2))

            # Эффект размера (Cohen's d)
            effect_size = abs(mean1 - mean2) / pooled_std if pooled_std > 0 else 0

            # Вычисление мощности
            analysis = TTestIndPower()
            power = analysis.solve_power(
                effect_size=effect_size,
                nobs1=n1,
                ratio=n2 / n1,
                alpha=alpha,
            )

            return power

        except Exception as e:
            logger.debug(f"Ошибка вычисления мощности: {e}")
            return 0.5  # Дефолтное значение

    def _update_test_in_db(self, test_id: str, result: ABTestResult) -> None:
        """Обновление теста в БД."""
        from sqlalchemy import Column, DateTime, Float, Integer, String, Text
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class ABTest(Base):
            __tablename__ = "ab_tests"

            id = Column(Integer, primary_key=True)
            test_id = Column(String, unique=True, nullable=False)
            status = Column(String, nullable=False)
            results_json = Column(Text, nullable=True)
            end_date = Column(DateTime, nullable=True)

        session = self.db_manager.Session()

        try:
            ab_test = session.query(ABTest).filter(ABTest.test_id == test_id).first()

            if ab_test:
                ab_test.status = result.status.value
                ab_test.end_date = datetime.now()
                ab_test.results_json = json.dumps(
                    {
                        "result": result.result.value if result.result else None,
                        "p_value": result.p_value,
                        "confidence_interval": result.confidence_interval,
                        "strategy_a_metrics": result.strategy_a_metrics,
                        "strategy_b_metrics": result.strategy_b_metrics,
                        "statistical_power": result.statistical_power,
                        "recommendation": result.recommendation,
                    }
                )

                session.commit()

        finally:
            session.close()

    def get_test_results(self, test_id: str) -> Optional[Dict[str, Any]]:
        """Получение результатов теста."""
        if test_id in self.test_results:
            result = self.test_results[test_id]
            return {
                "test_id": result.test_id,
                "status": result.status.value,
                "result": result.result.value if result.result else None,
                "p_value": result.p_value,
                "confidence_interval": result.confidence_interval,
                "strategy_a_metrics": result.strategy_a_metrics,
                "strategy_b_metrics": result.strategy_b_metrics,
                "statistical_power": result.statistical_power,
                "recommendation": result.recommendation,
            }

        # Пытаемся загрузить из БД
        from sqlalchemy import Column, DateTime, Integer, String, Text
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class ABTest(Base):
            __tablename__ = "ab_tests"

            id = Column(Integer, primary_key=True)
            test_id = Column(String, unique=True, nullable=False)
            status = Column(String, nullable=False)
            results_json = Column(Text, nullable=True)

        session = self.db_manager.Session()

        try:
            ab_test = session.query(ABTest).filter(ABTest.test_id == test_id).first()

            if ab_test and ab_test.results_json:
                try:
                    return json.loads(ab_test.results_json)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Не удалось распарсить results_json для теста {test_id}")
                    return None

            return None

        finally:
            session.close()

    def stop_test(self, test_id: str, reason: str = "") -> bool:
        """Остановка теста."""
        if test_id not in self.active_tests:
            return False

        # Удаляем из активных
        del self.active_tests[test_id]

        # Обновляем в БД
        from sqlalchemy import Column, DateTime, Integer, String, Text
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class ABTest(Base):
            __tablename__ = "ab_tests"

            id = Column(Integer, primary_key=True)
            test_id = Column(String, unique=True, nullable=False)
            status = Column(String, nullable=False)
            results_json = Column(Text, nullable=True)

        session = self.db_manager.Session()

        try:
            ab_test = session.query(ABTest).filter(ABTest.test_id == test_id).first()

            if ab_test:
                ab_test.status = "stopped"
                ab_test.results_json = json.dumps({"reason": reason})
                session.commit()

                logger.info(f"Тест {test_id} остановлен: {reason}")
                return True

            return False

        finally:
            session.close()

    def get_active_tests(self) -> List[Dict[str, Any]]:
        """Получение списка активных тестов."""
        return [
            {
                "test_id": test_id,
                "strategy_a": config.strategy_a,
                "strategy_b": config.strategy_b,
                "symbol": config.symbol,
                "duration_days": config.duration_days,
            }
            for test_id, config in self.active_tests.items()
        ]
