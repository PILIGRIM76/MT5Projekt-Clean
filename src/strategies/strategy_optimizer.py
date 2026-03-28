# src/strategies/strategy_optimizer.py
"""
Walk-Forward Оптимизатор Параметров Стратегий

Назначение:
- Автоматическая оптимизация параметров стратегий на скользящем окне
- Валидация на out-of-sample данных
- Адаптация к изменяющимся рыночным условиям
- Предотвращение переобучения

Алгоритм:
1. Разделение данных на in-sample (обучение) и out-of-sample (валидация)
2. Оптимизация параметров на in-sample
3. Валидация на out-of-sample
4. Скольжение окна вперед
5. Повторение шагов 1-4
6. Выбор параметров с лучшей out-of-sample производительностью

Автор: Genesis Trading System
Версия: 1.0.0
"""
import logging
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class OptimizationMetric(Enum):
    """Метрики для оптимизации."""
    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    CALMAR_RATIO = "calmar_ratio"
    PROFIT_FACTOR = "profit_factor"
    TOTAL_RETURN = "total_return"
    WIN_RATE = "win_rate"
    EXPECTANCY = "expectancy"
    COMPOSITE = "composite"  # Комбинация метрик


@dataclass
class ParameterRange:
    """Диапазон параметра для оптимизации."""
    name: str
    min_value: int | float
    max_value: int | float
    step: int | float = 1
    log_scale: bool = False  # Логарифмическая шкала
    
    def get_values(self) -> List[int | float]:
        """Получить список значений параметра."""
        if self.log_scale:
            # Логарифмическая шкала
            values = np.logspace(
                np.log10(self.min_value),
                np.log10(self.max_value),
                num=int((self.max_value - self.min_value) / self.step) + 1
            )
        else:
            # Линейная шкала
            values = np.arange(self.min_value, self.max_value + self.step, self.step)
        
        return [float(v) if isinstance(self.step, float) else int(v) for v in values]


@dataclass
class WalkForwardResult:
    """Результат Walk-Forward оптимизации."""
    optimal_parameters: Dict[str, float]
    in_sample_metrics: Dict[str, float]
    out_of_sample_metrics: Dict[str, float]
    walk_forward_scores: List[Dict[str, Any]] = field(default_factory=list)
    overfitting_coefficient: float = 0.0
    robustness_score: float = 0.0
    recommended: bool = False
    recommendation_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь."""
        return {
            'optimal_parameters': self.optimal_parameters,
            'in_sample_metrics': self.in_sample_metrics,
            'out_of_sample_metrics': self.out_of_sample_metrics,
            'overfitting_coefficient': round(self.overfitting_coefficient, 3),
            'robustness_score': round(self.robustness_score, 3),
            'recommended': self.recommended,
            'recommendation_reason': self.recommendation_reason,
            'walk_forward_iterations': len(self.walk_forward_scores)
        }


@dataclass
class StrategyPerformance:
    """Метрики производительности стратегии."""
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    total_trades: int = 0
    avg_trade_pnl: float = 0.0
    std_trade_pnl: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь."""
        return {
            'total_return': round(self.total_return, 4),
            'sharpe_ratio': round(self.sharpe_ratio, 3),
            'sortino_ratio': round(self.sortino_ratio, 3),
            'calmar_ratio': round(self.calmar_ratio, 3),
            'max_drawdown': round(self.max_drawdown, 4),
            'win_rate': round(self.win_rate, 3),
            'profit_factor': round(self.profit_factor, 3),
            'expectancy': round(self.expectancy, 4),
            'total_trades': self.total_trades,
            'avg_trade_pnl': round(self.avg_trade_pnl, 4),
            'std_trade_pnl': round(self.std_trade_pnl, 4)
        }


class WalkForwardOptimizer:
    """
    Walk-Forward оптимизатор параметров стратегий.
    
    Пример использования:
        optimizer = WalkForwardOptimizer(
            strategy_class=BreakoutStrategy,
            config=settings,
            parameter_ranges=[
                ParameterRange('window', 10, 50, 5),
            ],
            in_sample_ratio=0.7,
            n_folds=5
        )
        
        result = optimizer.optimize(historical_data)
        
        if result.recommended:
            save_optimized_params(result.optimal_parameters)
    """
    
    def __init__(
        self,
        strategy_class: Any,
        config: Settings,
        parameter_ranges: List[ParameterRange],
        in_sample_ratio: float = 0.7,
        n_folds: int = 5,
        optimization_metric: OptimizationMetric = OptimizationMetric.SHARPE_RATIO,
        min_trades: int = 20,
        n_jobs: int = -1,
        random_state: int = 42
    ):
        """
        Инициализация оптимизатора.
        
        Args:
            strategy_class: Класс стратегии для оптимизации
            config: Конфигурация системы
            parameter_ranges: Диапазоны параметров для оптимизации
            in_sample_ratio: Доля данных для in-sample (0.5-0.9)
            n_folds: Количество folds для walk-forward
            optimization_metric: Метрика для оптимизации
            min_trades: Минимальное количество сделок для валидности
            n_jobs: Количество потоков (-1 = все доступные)
            random_state: Seed для воспроизводимости
        """
        self.strategy_class = strategy_class
        self.config = config
        self.parameter_ranges = parameter_ranges
        self.in_sample_ratio = max(0.5, min(0.9, in_sample_ratio))
        self.n_folds = n_folds
        self.optimization_metric = optimization_metric
        self.min_trades = min_trades
        self.n_jobs = n_jobs if n_jobs > 0 else multiprocessing.cpu_count()
        self.random_state = random_state
        
        np.random.seed(random_state)
        
        logger.info(
            f"WalkForwardOptimizer инициализирован: "
            f"{len(parameter_ranges)} параметров, {n_folds} folds, "
            f"{self.n_jobs} потоков"
        )
    
    def optimize(
        self,
        data: pd.DataFrame,
        strategy_backtest_func: Callable
    ) -> WalkForwardResult:
        """
        Запуск Walk-Forward оптимизации.
        
        Args:
            data: Исторические данные
            strategy_backtest_func: Функция для бэктеста стратегии
            
        Returns:
            WalkForwardResult с результатами
        """
        logger.info(f"Запуск Walk-Forward оптимизации на {len(data)} барах")
        
        # Валидация данных
        if len(data) < self.n_folds * 20:
            raise ValueError(
                f"Недостаточно данных: {len(data)} баров, "
                f"минимум {self.n_folds * 20} требуется"
            )
        
        # Разделение на folds
        folds = self._create_walk_forward_folds(data)
        
        # Оптимизация на каждом fold
        all_results = []
        for fold_idx, (train_idx, test_idx) in enumerate(folds):
            logger.info(f"Fold {fold_idx + 1}/{self.n_folds}")
            
            train_data = data.iloc[train_idx].copy()
            test_data = data.iloc[test_idx].copy()
            
            # Оптимизация на train данных
            fold_result = self._optimize_fold(
                train_data, test_data, strategy_backtest_func, fold_idx
            )
            
            all_results.append(fold_result)
        
        # Агрегация результатов
        result = self._aggregate_results(all_results, data)
        
        logger.info(
            f"Оптимизация завершена. "
            f"Рекомендуемые параметры: {result.optimal_parameters}"
        )
        
        return result
    
    def _create_walk_forward_folds(
        self,
        data: pd.DataFrame
    ) -> List[Tuple[List[int], List[int]]]:
        """
        Создание скользящих окон для Walk-Forward.
        
        Returns:
            Список кортежей (train_indices, test_indices)
        """
        n_samples = len(data)
        fold_size = n_samples // self.n_folds
        
        folds = []
        for i in range(self.n_folds):
            # In-sample данные
            is_start = i * fold_size // self.n_folds
            is_end = is_start + int(fold_size * self.in_sample_ratio)
            
            # Out-of-sample данные
            os_start = is_end
            os_end = os_start + int(fold_size * (1 - self.in_sample_ratio))
            
            if os_end > n_samples:
                os_end = n_samples
            
            train_indices = list(range(is_start, is_end))
            test_indices = list(range(os_start, os_end))
            
            if len(train_indices) > 0 and len(test_indices) > 0:
                folds.append((train_indices, test_indices))
        
        logger.info(f"Создано {len(folds)} Walk-Forward окон")
        return folds
    
    def _optimize_fold(
        self,
        train_data: pd.DataFrame,
        test_data: pd.DataFrame,
        backtest_func: Callable,
        fold_idx: int
    ) -> Dict[str, Any]:
        """
        Оптимизация на одном fold.
        
        Returns:
            Словарь с результатами fold
        """
        # Генерация комбинаций параметров
        param_combinations = self._generate_param_combinations()
        
        logger.info(f"Тестирование {len(param_combinations)} комбинаций параметров")
        
        # Оценка каждой комбинации
        results = []
        for params in param_combinations:
            # In-sample производительность
            is_metrics = self._evaluate_parameters(
                params, train_data, backtest_func
            )
            
            # Out-of-sample производительность
            os_metrics = self._evaluate_parameters(
                params, test_data, backtest_func
            )
            
            results.append({
                'parameters': params,
                'is_metrics': is_metrics,
                'os_metrics': os_metrics
            })
        
        # Выбор лучших параметров по out-of-sample метрике
        best_result = self._select_best_parameters(results)
        
        return {
            'fold_idx': fold_idx,
            'train_size': len(train_data),
            'test_size': len(test_data),
            'best_params': best_result['parameters'],
            'is_metrics': best_result['is_metrics'].to_dict(),
            'os_metrics': best_result['os_metrics'].to_dict()
        }
    
    def _generate_param_combinations(self) -> List[Dict[str, float]]:
        """
        Генерация всех комбинаций параметров.
        
        Returns:
            Список словарей с параметрами
        """
        import itertools
        
        param_values = {
            param.name: param.get_values()
            for param in self.parameter_ranges
        }
        
        combinations = []
        for values in itertools.product(*param_values.values()):
            combinations.append(dict(zip(param_values.keys(), values)))
        
        logger.debug(f"Сгенерировано {len(combinations)} комбинаций")
        return combinations
    
    def _evaluate_parameters(
        self,
        params: Dict[str, float],
        data: pd.DataFrame,
        backtest_func: Callable
    ) -> StrategyPerformance:
        """
        Оценка производительности параметров.
        
        Args:
            params: Параметры для оценки
            data: Данные для бэктеста
            backtest_func: Функция бэктеста
            
        Returns:
            StrategyPerformance с метриками
        """
        try:
            # Запуск бэктеста
            trades = backtest_func(self.strategy_class, self.config, params, data)
            
            if len(trades) < self.min_trades:
                # Недостаточно сделок
                return StrategyPerformance(
                    sharpe_ratio=-999,
                    total_trades=len(trades)
                )
            
            # Расчет метрик
            pnls = [t['pnl'] for t in trades]
            returns = pd.Series(pnls)
            
            # Основные метрики
            total_return = returns.sum()
            sharpe = self._calculate_sharpe(returns)
            sortino = self._calculate_sortino(returns)
            max_dd = self._calculate_max_drawdown(returns)
            calmar = total_return / (abs(max_dd) + 1e-10)
            
            win_trades = [p for p in pnls if p > 0]
            loss_trades = [p for p in pnls if p < 0]
            
            win_rate = len(win_trades) / len(pnls) if pnls else 0
            gross_profit = sum(win_trades) if win_trades else 0
            gross_loss = abs(sum(loss_trades)) if loss_trades else 1
            profit_factor = gross_profit / (gross_loss + 1e-10)
            
            expectancy = returns.mean()
            
            return StrategyPerformance(
                total_return=total_return,
                sharpe_ratio=sharpe,
                sortino_ratio=sortino,
                calmar_ratio=calmar,
                max_drawdown=max_dd,
                win_rate=win_rate,
                profit_factor=profit_factor,
                expectancy=expectancy,
                total_trades=len(trades),
                avg_trade_pnl=returns.mean(),
                std_trade_pnl=returns.std()
            )
        
        except Exception as e:
            logger.error(f"Ошибка оценки параметров: {e}")
            return StrategyPerformance(sharpe_ratio=-999)
    
    def _select_best_parameters(
        self,
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Выбор лучших параметров по целевой метрике.
        
        Returns:
            Лучший результат
        """
        if not results:
            raise ValueError("Нет результатов для выбора")
        
        # Сортировка по целевой метрике out-of-sample
        def get_metric_score(result: Dict) -> float:
            metrics = result['os_metrics']
            
            metric_map = {
                OptimizationMetric.SHARPE_RATIO: metrics.sharpe_ratio,
                OptimizationMetric.SORTINO_RATIO: metrics.sortino_ratio,
                OptimizationMetric.CALMAR_RATIO: metrics.calmar_ratio,
                OptimizationMetric.PROFIT_FACTOR: metrics.profit_factor,
                OptimizationMetric.TOTAL_RETURN: metrics.total_return,
                OptimizationMetric.WIN_RATE: metrics.win_rate,
                OptimizationMetric.EXPECTANCY: metrics.expectancy,
                OptimizationMetric.COMPOSITE: self._calculate_composite_score(metrics)
            }
            
            return metric_map.get(self.optimization_metric, 0)
        
        results_sorted = sorted(results, key=get_metric_score, reverse=True)
        return results_sorted[0]
    
    def _calculate_composite_score(self, metrics: StrategyPerformance) -> float:
        """
        Расчет композитной метрики.
        
        Формула:
        Composite = Sharpe × 0.4 + (ProfitFactor - 1) × 0.3 + WinRate × 0.2 + (1 - MaxDD) × 0.1
        """
        sharpe_normalized = min(3, max(-3, metrics.sharpe_ratio)) / 3  # [-1, 1]
        pf_normalized = min(2, max(0, metrics.profit_factor - 1)) / 2  # [0, 1]
        winrate_normalized = metrics.win_rate  # [0, 1]
        dd_normalized = 1 - min(1, abs(metrics.max_drawdown))  # [0, 1]
        
        composite = (
            sharpe_normalized * 0.4 +
            pf_normalized * 0.3 +
            winrate_normalized * 0.2 +
            dd_normalized * 0.1
        )
        
        return composite
    
    def _aggregate_results(
        self,
        fold_results: List[Dict[str, Any]],
        data: pd.DataFrame
    ) -> WalkForwardResult:
        """
        Агрегация результатов всех folds.
        
        Returns:
            WalkForwardResult с итоговыми результатами
        """
        # Извлечение лучших параметров из каждого fold
        all_best_params = [r['best_params'] for r in fold_results]
        
        # Усреднение параметров
        avg_params = {}
        for param_name in self.parameter_ranges:
            values = [p[param_name.name] for p in all_best_params]
            avg_params[param_name.name] = float(np.median(values))
        
        # Округление до целых для дискретных параметров
        for param_name in self.parameter_ranges:
            if isinstance(param_name.step, int):
                avg_params[param_name.name] = int(round(avg_params[param_name.name]))
        
        # Агрегация метрик
        is_metrics = self._aggregate_metrics_across_folds(fold_results, 'is_metrics')
        os_metrics = self._aggregate_metrics_across_folds(fold_results, 'os_metrics')
        
        # Расчет коэффициента переобучения
        overfitting_coeff = self._calculate_overfitting_coefficient(fold_results)
        
        # Расчет robustness score
        robustness = self._calculate_robustness_score(fold_results)
        
        # Рекомендация
        recommended, reason = self._make_recommendation(
            os_metrics, overfitting_coeff, robustness
        )
        
        return WalkForwardResult(
            optimal_parameters=avg_params,
            in_sample_metrics=is_metrics,
            out_of_sample_metrics=os_metrics,
            walk_forward_scores=fold_results,
            overfitting_coefficient=overfitting_coeff,
            robustness_score=robustness,
            recommended=recommended,
            recommendation_reason=reason
        )
    
    def _aggregate_metrics_across_folds(
        self,
        fold_results: List[Dict[str, Any]],
        metrics_key: str
    ) -> Dict[str, float]:
        """Агрегация метрик по всем folds."""
        all_metrics = [r[metrics_key] for r in fold_results]
        
        aggregated = {}
        for key in all_metrics[0].keys():
            values = [m[key] for m in all_metrics if isinstance(m[key], (int, float))]
            if values:
                aggregated[key] = float(np.mean(values))
        
        return aggregated
    
    def _calculate_overfitting_coefficient(
        self,
        fold_results: List[Dict[str, Any]]
    ) -> float:
        """
        Расчет коэффициента переобучения.
        
        Формула:
        Overfitting = (IS_Sharp - OS_Sharp) / IS_Sharp
        
        Возвращает:
            0 = нет переобучения
            > 0.5 = сильное переобучение
        """
        is_sharpes = [r['is_metrics']['sharpe_ratio'] for r in fold_results]
        os_sharpes = [r['os_metrics']['sharpe_ratio'] for r in fold_results]
        
        avg_is = np.mean(is_sharpes)
        avg_os = np.mean(os_sharpes)
        
        if avg_is <= 0:
            return 1.0
        
        overfitting = (avg_is - avg_os) / avg_is
        return max(0, min(1, overfitting))
    
    def _calculate_robustness_score(
        self,
        fold_results: List[Dict[str, Any]]
    ) -> float:
        """
        Расчет устойчивости результатов.
        
        Учитывает:
        - Стабильность Sharpe ratio across folds
        - Процент прибыльных folds
        - Консистентность лучших параметров
        
        Returns:
            Robustness score [0, 1]
        """
        os_sharpes = [r['os_metrics']['sharpe_ratio'] for r in fold_results]
        
        # Стабильность (обратная величина от стандартного отклонения)
        sharpe_std = np.std(os_sharpes)
        sharpe_mean = np.mean(os_sharpes)
        
        if sharpe_mean == 0:
            stability = 0
        else:
            cv = sharpe_std / abs(sharpe_mean)  # Коэффициент вариации
            stability = max(0, 1 - cv)
        
        # Процент прибыльных folds
        profitable_folds = sum(1 for s in os_sharpes if s > 0) / len(os_sharpes)
        
        # Итоговый score
        robustness = stability * 0.6 + profitable_folds * 0.4
        
        return robustness
    
    def _make_recommendation(
        self,
        os_metrics: Dict[str, float],
        overfitting_coeff: float,
        robustness: float
    ) -> Tuple[bool, str]:
        """
        Принятие решения о рекомендации параметров.
        
        Критерии:
        - OS Sharpe > 0.5
        - Overfitting < 0.5
        - Robustness > 0.6
        """
        sharpe = os_metrics.get('sharpe_ratio', 0)
        
        reasons = []
        recommended = True
        
        if sharpe < 0.5:
            recommended = False
            reasons.append(f"Низкий Sharpe ({sharpe:.2f})")
        
        if overfitting_coeff > 0.5:
            recommended = False
            reasons.append(f"Высокое переобучение ({overfitting_coeff:.2f})")
        
        if robustness < 0.6:
            recommended = False
            reasons.append(f"Низкая устойчивость ({robustness:.2f})")
        
        if recommended:
            reason = "Параметры рекомендуются к использованию"
        else:
            reason = "; ".join(reasons)
        
        return recommended, reason
    
    # ========================================================================
    # Вспомогательные методы
    # ========================================================================
    
    def _calculate_sharpe(self, returns: pd.Series) -> float:
        """Расчет Sharpe ratio."""
        if len(returns) < 2 or returns.std() == 0:
            return 0.0
        return (returns.mean() / returns.std()) * np.sqrt(252)
    
    def _calculate_sortino(self, returns: pd.Series) -> float:
        """Расчет Sortino ratio."""
        if len(returns) < 2:
            return 0.0
        
        downside_returns = returns[returns < 0]
        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return 0.0
        
        return (returns.mean() / downside_returns.std()) * np.sqrt(252)
    
    def _calculate_max_drawdown(self, returns: pd.Series) -> float:
        """Расчет максимальной просадки."""
        if len(returns) == 0:
            return 0.0
        
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        
        return drawdown.min()
    
    def save_results(self, result: WalkForwardResult, filepath: str):
        """Сохранение результатов в файл."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Результаты сохранены в {filepath}")
    
    def load_results(self, filepath: str) -> Dict[str, Any]:
        """Загрузка результатов из файла."""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)


# ============================================================================
# Утилиты для сохранения оптимизированных параметров
# ============================================================================

def save_optimized_params(
    params: Dict[str, float],
    strategy_name: str,
    output_file: str = "configs/optimized_params.json"
):
    """
    Сохранение оптимизированных параметров в файл.
    
    Args:
        params: Оптимизированные параметры
        strategy_name: Имя стратегии
        output_file: Путь к файлу
    """
    output_path = Path(output_file)
    
    # Загрузка существующих параметров
    existing_params = {}
    if output_path.exists():
        with open(output_path, 'r', encoding='utf-8') as f:
            existing_params = json.load(f)
    
    # Обновление параметров стратегии
    existing_params[strategy_name] = {
        k: int(v) if isinstance(v, float) and v.is_integer() else v
        for k, v in params.items()
    }
    
    # Сохранение
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(existing_params, f, indent=2, ensure_ascii=False)
    
    logger.info(
        f"Оптимизированные параметры для {strategy_name} сохранены в {output_file}"
    )


def load_optimized_params(
    strategy_name: str,
    input_file: str = "configs/optimized_params.json"
) -> Optional[Dict[str, float]]:
    """
    Загрузка оптимизированных параметров из файла.
    
    Args:
        strategy_name: Имя стратегии
        input_file: Путь к файлу
        
    Returns:
        Параметры или None
    """
    input_path = Path(input_file)
    
    if not input_path.exists():
        logger.warning(f"Файл {input_file} не найден")
        return None
    
    with open(input_path, 'r', encoding='utf-8') as f:
        all_params = json.load(f)
    
    return all_params.get(strategy_name)
