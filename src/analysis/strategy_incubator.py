# src/analysis/strategy_incubator.py
"""
Strategy Incubator — Система оценки и контроля качества стратегий.

Критерии выпуска в "live":
- Минимум 50 сделок
- Win Rate > 45%
- Profit Factor > 1.2
- Max Drawdown < 15%
- Sharpe Ratio > 0.5
- 30+ дней торговли

Обеспечивает:
- Оценку готовности стратегии
- Рекомендации по улучшению
- Авто-блокировку при ухудшении метрик
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Any

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class IncubationStatus(Enum):
    """Статусы стратегии в инкубаторе."""
    INCUBATING = "incubating"  # В процессе оценки
    READY_FOR_LIVE = "ready_for_live"  # Готова к выпуску
    REJECTED = "rejected"  # Отклонена
    GRADUATED = "graduated"  # Выпущена в live
    BLOCKED = "blocked"  # Заблокирована (ухудшение метрик)


@dataclass
class IncubationCriteria:
    """Критерии выпуска стратегии."""
    min_trades: int = 50
    min_days: int = 30
    min_win_rate: float = 0.45
    min_profit_factor: float = 1.2
    max_drawdown: float = 0.15
    min_sharpe_ratio: float = 0.5
    min_total_profit: float = 0.0


@dataclass
class StrategyEvaluation:
    """Результат оценки стратегии."""
    strategy_name: str
    status: IncubationStatus
    evaluation_date: datetime
    criteria_passed: Dict[str, bool] = field(default_factory=dict)
    actual_values: Dict[str, float] = field(default_factory=dict)
    recommendation: str = ""
    blocking_reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует в словарь."""
        return {
            'strategy_name': self.strategy_name,
            'status': self.status.value,
            'evaluation_date': self.evaluation_date.isoformat(),
            'criteria_passed': self.criteria_passed,
            'actual_values': self.actual_values,
            'recommendation': self.recommendation,
            'blocking_reasons': self.blocking_reasons
        }


class StrategyIncubator:
    """
    Инкубатор стратегий для Genesis Trading System.
    
    Атрибуты:
        criteria: Критерии выпуска
        strategies: Статистика стратегий в инкубаторе
    """
    
    def __init__(self, config: Settings):
        """
        Инициализация инкубатора.
        
        Args:
            config: Конфигурация системы
        """
        self.config = config
        
        # Конфигурация из settings
        inc_config = getattr(config, 'strategy_incubator', {})
        
        self.criteria = IncubationCriteria(
            min_trades=inc_config.get('min_trades', 50),
            min_days=inc_config.get('min_days', 30),
            min_win_rate=inc_config.get('min_win_rate', 0.45),
            min_profit_factor=inc_config.get('min_profit_factor', 1.2),
            max_drawdown=inc_config.get('max_drawdown', 0.15),
            min_sharpe_ratio=inc_config.get('min_sharpe_ratio', 0.5),
            min_total_profit=inc_config.get('min_total_profit', 0.0)
        )
        
        # Статистика стратегий
        self.strategies: Dict[str, Dict[str, Any]] = {}
        
        # История оценок
        self.evaluation_history: List[StrategyEvaluation] = []
        
        logger.info("Strategy Incubator инициализирован")
        logger.info(f"  - Min Trades: {self.criteria.min_trades}")
        logger.info(f"  - Min Win Rate: {self.criteria.min_win_rate*100}%")
        logger.info(f"  - Min Profit Factor: {self.criteria.min_profit_factor}")
        logger.info(f"  - Max Drawdown: {self.criteria.max_drawdown*100}%")
    
    def register_strategy(self, strategy_name: str, start_date: Optional[datetime] = None) -> None:
        """
        Регистрирует стратегию в инкубаторе.
        
        Args:
            strategy_name: Название стратегии
            start_date: Дата начала (по умолчанию сегодня)
        """
        if strategy_name in self.strategies:
            logger.warning(f"Стратегия {strategy_name} уже зарегистрирована")
            return
        
        self.strategies[strategy_name] = {
            'start_date': start_date or datetime.now(),
            'status': IncubationStatus.INCUBATING,
            'stats': {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_pnl': 0.0,
                'gross_profit': 0.0,
                'gross_loss': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'profit_factor': 0.0,
                'win_rate': 0.0
            },
            'last_update': datetime.now(),
            'evaluation_history': []
        }
        
        logger.info(f"Стратегия {strategy_name} зарегистрирована в инкубаторе")
    
    def update_stats(self, strategy_name: str, trade_result: Dict[str, Any]) -> None:
        """
        Обновляет статистику стратегии.
        
        Args:
            strategy_name: Название стратегии
            trade_result: Результат сделки
        """
        if strategy_name not in self.strategies:
            self.register_strategy(strategy_name)
        
        strategy = self.strategies[strategy_name]
        stats = strategy['stats']
        
        # Обновляем счётчики
        stats['total_trades'] += 1
        stats['total_pnl'] += trade_result.get('pnl', 0.0)
        
        if trade_result.get('pnl', 0.0) > 0:
            stats['winning_trades'] += 1
            stats['gross_profit'] += abs(trade_result.get('pnl', 0.0))
        elif trade_result.get('pnl', 0.0) < 0:
            stats['losing_trades'] += 1
            stats['gross_loss'] += abs(trade_result.get('pnl', 0.0))
        
        # Обновляем просадку
        current_drawdown = self._calculate_current_drawdown(stats)
        if current_drawdown > stats['max_drawdown']:
            stats['max_drawdown'] = current_drawdown
        
        # Пересчитываем метрики
        stats['win_rate'] = stats['winning_trades'] / stats['total_trades'] if stats['total_trades'] > 0 else 0
        stats['profit_factor'] = stats['gross_profit'] / stats['gross_loss'] if stats['gross_loss'] > 0 else float('inf')
        stats['sharpe_ratio'] = self._calculate_sharpe_ratio(stats)
        
        strategy['last_update'] = datetime.now()
        
        # Авто-оценка при достижении порогов
        if stats['total_trades'] % 10 == 0:  # Каждые 10 сделок
            self.evaluate_strategy(strategy_name)
    
    def evaluate_strategy(self, strategy_name: str) -> StrategyEvaluation:
        """
        Оценивает стратегию на готовность к выпуску.
        
        Args:
            strategy_name: Название стратегии
            
        Returns:
            Результат оценки
        """
        if strategy_name not in self.strategies:
            raise ValueError(f"Стратегия {strategy_name} не найдена")
        
        strategy = self.strategies[strategy_name]
        stats = strategy['stats']
        start_date = strategy['start_date']
        
        # Дней торговли
        days_trading = (datetime.now() - start_date).days
        
        # Проверка критериев
        criteria_passed = {
            'min_trades': stats['total_trades'] >= self.criteria.min_trades,
            'min_days': days_trading >= self.criteria.min_days,
            'min_win_rate': stats['win_rate'] >= self.criteria.min_win_rate,
            'min_profit_factor': stats['profit_factor'] >= self.criteria.min_profit_factor,
            'max_drawdown': stats['max_drawdown'] <= self.criteria.max_drawdown,
            'min_sharpe_ratio': stats['sharpe_ratio'] >= self.criteria.min_sharpe_ratio,
            'min_total_profit': stats['total_pnl'] >= self.criteria.min_total_profit
        }
        
        # Фактические значения
        actual_values = {
            'total_trades': stats['total_trades'],
            'days_trading': days_trading,
            'win_rate': stats['win_rate'],
            'profit_factor': stats['profit_factor'],
            'max_drawdown': stats['max_drawdown'],
            'sharpe_ratio': stats['sharpe_ratio'],
            'total_pnl': stats['total_pnl']
        }
        
        # Определяем статус
        all_passed = all(criteria_passed.values())
        blocking_reasons = []
        
        if not all_passed:
            # Определяем какие критерии не пройдены
            for criterion, passed in criteria_passed.items():
                if not passed:
                    blocking_reasons.append(f"Не пройден {criterion}")
        
        # Рекомендация
        recommendation = self._generate_recommendation(criteria_passed, stats, days_trading)
        
        # Определяем итоговый статус
        if all_passed:
            status = IncubationStatus.READY_FOR_LIVE
        elif stats['max_drawdown'] > self.criteria.max_drawdown * 1.5:
            status = IncubationStatus.BLOCKED
        elif days_trading >= self.criteria.min_days * 2 and stats['total_trades'] >= self.criteria.min_trades:
            if sum(criteria_passed.values()) >= 5:  # Большинство пройдено
                status = IncubationStatus.READY_FOR_LIVE
            else:
                status = IncubationStatus.REJECTED
        else:
            status = IncubationStatus.INCUBATING
        
        # Создаём оценку
        evaluation = StrategyEvaluation(
            strategy_name=strategy_name,
            status=status,
            evaluation_date=datetime.now(),
            criteria_passed=criteria_passed,
            actual_values=actual_values,
            recommendation=recommendation,
            blocking_reasons=blocking_reasons
        )
        
        # Сохраняем в историю
        self.evaluation_history.append(evaluation)
        strategy['evaluation_history'].append(evaluation)
        
        # Обновляем статус стратегии
        strategy['status'] = status
        
        logger.info(f"Оценка стратегии {strategy_name}: {status.value}")
        
        return evaluation
    
    def graduate_strategy(self, strategy_name: str) -> bool:
        """
        Выпускает стратегию в live.
        
        Args:
            strategy_name: Название стратегии
            
        Returns:
            True если успешно
        """
        if strategy_name not in self.strategies:
            return False
        
        strategy = self.strategies[strategy_name]
        
        # Проверяем готовность
        evaluation = self.evaluate_strategy(strategy_name)
        
        if evaluation.status != IncubationStatus.READY_FOR_LIVE:
            logger.warning(f"Стратегия {strategy_name} не готова к выпуску")
            return False
        
        strategy['status'] = IncubationStatus.GRADUATED
        logger.info(f"Стратегия {strategy_name} выпущена в LIVE")
        
        return True
    
    def block_strategy(self, strategy_name: str, reason: str) -> None:
        """
        Блокирует стратегию.
        
        Args:
            strategy_name: Название стратегии
            reason: Причина блокировки
        """
        if strategy_name in self.strategies:
            self.strategies[strategy_name]['status'] = IncubationStatus.BLOCKED
            logger.warning(f"Стратегия {strategy_name} заблокирована: {reason}")
    
    def get_strategy_status(self, strategy_name: str) -> Optional[IncubationStatus]:
        """Возвращает статус стратегии."""
        if strategy_name in self.strategies:
            return self.strategies[strategy_name]['status']
        return None
    
    def get_graduated_strategies(self) -> List[str]:
        """Возвращает список выпущенных стратегий."""
        return [
            name for name, data in self.strategies.items()
            if data['status'] == IncubationStatus.GRADUATED
        ]
    
    def get_incubating_strategies(self) -> List[str]:
        """Возвращает список стратегий в инкубаторе."""
        return [
            name for name, data in self.strategies.items()
            if data['status'] == IncubationStatus.INCUBATING
        ]
    
    def _generate_recommendation(self, criteria_passed: Dict[str, bool], 
                                  stats: Dict[str, Any], days_trading: int) -> str:
        """Генерирует рекомендации по улучшению."""
        passed_count = sum(criteria_passed.values())
        total_count = len(criteria_passed)
        
        if passed_count == total_count:
            return "✅ Стратегия готова к выпуску в live!"
        
        recommendations = []
        
        if not criteria_passed['min_trades']:
            needed = self.criteria.min_trades - stats['total_trades']
            recommendations.append(f"Нужно ещё {needed} сделок")
        
        if not criteria_passed['min_win_rate']:
            diff = self.criteria.min_win_rate - stats['win_rate']
            recommendations.append(f"Увеличить win rate на {diff*100:.1f}%")
        
        if not criteria_passed['min_profit_factor']:
            diff = self.criteria.min_profit_factor - stats['profit_factor']
            recommendations.append(f"Увеличить profit factor на {diff:.2f}")
        
        if not criteria_passed['max_drawdown']:
            diff = stats['max_drawdown'] - self.criteria.max_drawdown
            recommendations.append(f"Снизить drawdown на {diff*100:.1f}%")
        
        if not criteria_passed['min_days']:
            needed = self.criteria.min_days - days_trading
            recommendations.append(f"Поторговать ещё {needed} дней")
        
        if recommendations:
            return "🔧 " + "; ".join(recommendations)
        else:
            return "✅ Стратегия показывает хорошие результаты"
    
    def _calculate_current_drawdown(self, stats: Dict[str, Any]) -> float:
        """Рассчитывает текущую просадку."""
        # Упрощённая реализация
        if stats['total_pnl'] <= 0:
            return abs(stats['total_pnl']) / max(stats['gross_profit'], 1)
        return 0.0
    
    def _calculate_sharpe_ratio(self, stats: Dict[str, Any]) -> float:
        """Рассчитывает коэффициент Шарпа."""
        # Упрощённая реализация
        if stats['total_trades'] < 10:
            return 0.0
        
        avg_return = stats['total_pnl'] / stats['total_trades']
        volatility = abs(stats['gross_loss']) / stats['losing_trades'] if stats['losing_trades'] > 0 else 1.0
        
        if volatility == 0:
            return 0.0
        
        return avg_return / volatility
