# src/ml/genetic_programming_core.py
from datetime import datetime
import random
import logging
import pickle
import copy
from pathlib import Path
from typing import List, Any, Tuple, Optional
import operator
import numpy as np
import pandas as pd

from transformers.models import mt5 as transformers_mt5

from src.data_models import TradeSignal, SignalType
from src.strategies.StrategyInterface import BaseStrategy
from src.core.config_models import Settings
from src.analysis.backtester import StrategyBacktester
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

OPERATORS = {'AND': (operator.and_, 2), 'OR': (operator.or_, 2), '>': (operator.gt, 2), '<': (operator.lt, 2)}


def get_indicator(df: pd.DataFrame, name: str, params: tuple) -> pd.Series:
    """
    Извлекает или рассчитывает индикатор.
    """
    try:
        # Если индикатор уже рассчитан в DataFrame (как в TradingSystem)
        if name in df.columns:
            return df[name]

        # Если нужно рассчитать на лету (для GP)
        if name == 'SMA':
            return df['close'].rolling(window=params[0]).mean()
        if name == 'RSI':
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=params[0]).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=params[0]).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))
        if name == 'ATR':
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            return tr.ewm(alpha=1 / params[0], adjust=False).mean()
        if name == 'CLOSE':
            return df['close']

    except Exception:
        # Возвращаем серию NaN, чтобы не сломать оценку
        return pd.Series(float('nan'), index=df.index)
    return pd.Series(float('nan'), index=df.index)


# --- SIM.2: РАСШИРЕННЫЙ НАБОР ТЕРМИНАЛОВ ---
TERMINALS = {
    # Цены и объемы
    'CLOSE': lambda df: get_indicator(df, 'CLOSE', ()),
    'OPEN': lambda df: df['open'],
    'HIGH': lambda df: df['high'],
    'LOW': lambda df: df['low'],
    'VOLUME': lambda df: df['tick_volume'],

    # Скользящие средние
    'SMA(20)': lambda df: get_indicator(df, 'SMA', (20,)),
    'SMA(50)': lambda df: get_indicator(df, 'SMA', (50,)),
    'SMA(200)': lambda df: get_indicator(df, 'SMA', (200,)),

    # Осцилляторы и волатильность
    'RSI(14)': lambda df: get_indicator(df, 'RSI', (14,)),
    'ATR(14)': lambda df: get_indicator(df, 'ATR', (14,)),

# --- GP.1: ДОБАВЛЕНИЕ ГИБРИДНОГО ТЕРМИНАЛА ---
    # Предполагаем, что AI-модель уже добавила свою предсказанную цену
    # в колонку 'AI_PREDICT_VALUE' в DataFrame.
    'AI_PREDICT': lambda df: df['AI_PREDICT_VALUE'] if 'AI_PREDICT_VALUE' in df.columns else pd.Series(0.0, index=df.index),
    'AI_PREDICT_CHANGE': lambda df: df['AI_PREDICT_VALUE'].pct_change() if 'AI_PREDICT_VALUE' in df.columns else pd.Series(0.0, index=df.index),

    # Константы (для сравнения)
    '70': lambda df: pd.Series(70, index=df.index),
    '30': lambda df: pd.Series(30, index=df.index),
    '1.0': lambda df: pd.Series(1.0, index=df.index),
    '0.0': lambda df: pd.Series(0.0, index=df.index),
}



class Node:
    def __init__(self, value: Any, children: List['Node'] = None):
        self.value = value
        self.children = children if children is not None else []

    def __str__(self):
        if not self.children: return str(self.value)
        if self.value in ['>', '<', 'AND', 'OR']: return f"({self.children[0]} {self.value} {self.children[1]})"
        return f"{self.value}({', '.join(map(str, self.children))})"

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        if self.value in TERMINALS:
            return TERMINALS[self.value](df)
        op, _ = OPERATORS[self.value]
        if self.value in ['AND', 'OR']:
            child_results = [child.evaluate(df) for child in self.children]
            bool_children = [res.astype(bool) for res in child_results]
            return op(*bool_children)
        else:
            evaluated_children = [child.evaluate(df) for child in self.children]
            return op(*evaluated_children)


class GeneticProgrammingCore:
    def __init__(self, historical_data: pd.DataFrame, config: Settings, trading_system_ref):
        self.data = historical_data
        self.config = config
        self.trading_system = trading_system_ref
        # --- ИСПРАВЛЕНИЕ: Прямой доступ к атрибутам ---
        self.population_size = self.config.GP_POPULATION_SIZE
        self.generations = self.config.GP_GENERATIONS
        self.mutation_rate = self.config.GP_MUTATION_RATE
        self.crossover_rate = self.config.GP_CROSSOVER_RATE
        self.elitism_size = self.config.GP_ELITISM_SIZE
        self.tournament_size = self.config.GP_TOURNAMENT_SIZE
        self.generated_strategies_directory = "data/generated_strategies"
        self.strategies_path = Path(self.generated_strategies_directory)
        self.strategies_path.mkdir(parents=True, exist_ok=True)

    def _create_random_tree(self, depth=0, max_depth=4) -> Node:
        if depth >= max_depth or random.random() < 0.5:
            return Node(random.choice(list(TERMINALS.keys())))
        else:
            op_name, op_details = random.choice(list(OPERATORS.items()))
            arity = op_details[1]
            children = [self._create_random_tree(depth + 1, max_depth) for _ in range(arity)]
            return Node(op_name, children)

    def _fitness(self, individual: dict) -> float:
        """
        [TZ 1.1 & 1.2] Расчет риск-скорректированной приспособленности с 3-сегментной Walk-Forward валидацией.
        Fitness = (SharpeRatio * ProfitFactor) - (10 * MaxDrawdown^2)
        Метрики рассчитываются на Out-of-Sample данных (каждый сегмент).
        """
        full_data = self.data
        data_len = len(full_data)

        # [TZ 1.2] Разделение данных на 3 последовательных, непересекающихся сегмента
        segment_size = data_len // 3

        # Проверка минимального размера для валидации
        if segment_size < self.config.GP_MIN_TRADES_SAMPLE * 2:
            logger.warning("[GP] Недостаточно данных для 3-сегментной валидации.")
            return -100.0

        segments = [
            full_data.iloc[0:segment_size],
            full_data.iloc[segment_size:2 * segment_size],
            full_data.iloc[2 * segment_size:3 * segment_size]
        ]

        fitness_scores = []

        # Используем H1 как стандартный таймфрейм для бэктеста GP
        timeframe = mt5.TIMEFRAME_H1

        # Вспомогательный класс для оценки дерева
        class VirtualTreeStrategy(BaseStrategy):
            def __init__(self, individual: dict, config: Settings):
                super().__init__(config)
                self.buy_tree = individual.get('buy_tree')
                self.sell_tree = individual.get('sell_tree')

            def check_entry_conditions(self, df: pd.DataFrame, current_index: int, timeframe: int) -> Optional[TradeSignal]:
                try:
                    buy_signal = self.buy_tree.evaluate(df).iloc[current_index] if self.buy_tree else False
                    sell_signal = self.sell_tree.evaluate(df).iloc[current_index] if self.sell_tree else False
                    if buy_signal and sell_signal: return None
                    if buy_signal: return TradeSignal(type=SignalType.BUY, confidence=1.0)
                    if sell_signal: return TradeSignal(type=SignalType.SELL, confidence=1.0)
                except IndexError:
                    return None
                return None

        temp_strategy = VirtualTreeStrategy(individual, self.config)

        for i, segment_data in enumerate(segments):
            if len(segment_data) < self.config.GP_MIN_TRADES_SAMPLE * 2:
                logger.warning(f"[GP] Сегмент {i + 1} слишком мал. Пропуск.")
                continue

            # Запуск бэктеста на сегменте (Out-of-Sample)
            backtester = StrategyBacktester(
                strategy=temp_strategy,
                data=segment_data,
                timeframe=timeframe,
                config=self.config
            )
            report = backtester.run()

            total_trades = report.get('total_trades', 0)
            
            # Проверка на деление на ноль для метрик
            sharpe_ratio = report.get('sharpe_ratio', 0.0)
            if pd.isna(sharpe_ratio) or np.isinf(sharpe_ratio):
                sharpe_ratio = 0.0
                
            profit_factor = report.get('profit_factor', 0.0)
            if pd.isna(profit_factor) or np.isinf(profit_factor) or profit_factor < 0:
                profit_factor = 0.0
                
            # MaxDrawdown возвращается как десятичная дробь (например, 0.15)
            max_drawdown = report.get('max_drawdown', 1.0)
            if pd.isna(max_drawdown) or np.isinf(max_drawdown) or max_drawdown < 0:
                max_drawdown = 1.0

            # [TZ 1.1] Применение композитной формулы приспособленности
            if total_trades < self.config.GP_MIN_TRADES_SAMPLE or profit_factor < 1.0:
                segment_fitness = -100.0  # Жесткий штраф
            else:
                # Fitness = (SharpeRatio * ProfitFactor) - (10 * MaxDrawdown^2)
                segment_fitness = (sharpe_ratio * profit_factor) - (10 * (max_drawdown ** 2))

            fitness_scores.append(segment_fitness)

        if not fitness_scores:
            return -100.0

        # [TZ 1.2] Итоговый _fitness - среднее значение по 3 сегментам
        final_fitness = sum(fitness_scores) / len(fitness_scores)

        # Защита от NaN
        return final_fitness if pd.notna(final_fitness) else -100.0

    def _get_all_nodes(self, node: Node) -> List[Node]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._get_all_nodes(child))
        return nodes

    def _tournament_selection(self, fitness_scores: list) -> dict:
        selection = random.sample(fitness_scores, self.tournament_size)
        return max(selection, key=lambda x: x[0])[1]

    def _crossover(self, parent1: dict, parent2: dict) -> Tuple[dict, dict]:
        child1 = copy.deepcopy(parent1)
        child2 = copy.deepcopy(parent2)

        nodes1_buy = self._get_all_nodes(child1['buy_tree'])
        nodes2_buy = self._get_all_nodes(child2['buy_tree'])
        if nodes1_buy and nodes2_buy:
            crossover_point1 = random.choice(nodes1_buy)
            crossover_point2 = random.choice(nodes2_buy)
            crossover_point1.value, crossover_point2.value = crossover_point2.value, crossover_point1.value
            crossover_point1.children, crossover_point2.children = crossover_point2.children, crossover_point1.children

        nodes1_sell = self._get_all_nodes(child1['sell_tree'])
        nodes2_sell = self._get_all_nodes(child2['sell_tree'])
        if nodes1_sell and nodes2_sell:
            crossover_point1 = random.choice(nodes1_sell)
            crossover_point2 = random.choice(nodes2_sell)
            crossover_point1.value, crossover_point2.value = crossover_point2.value, crossover_point1.value
            crossover_point1.children, crossover_point2.children = crossover_point2.children, crossover_point1.children

        return child1, child2

    def _mutate(self, individual: dict) -> dict:
        tree_to_mutate = random.choice(['buy_tree', 'sell_tree'])
        nodes = self._get_all_nodes(individual[tree_to_mutate])
        if not nodes: return individual
        mutation_point = random.choice(nodes)
        new_subtree = self._create_random_tree()
        mutation_point.value = new_subtree.value
        mutation_point.children = new_subtree.children
        return individual

    def evolve(self):
        logger.info("Запуск генетического программирования (Dual-Tree)...")
        population = [{'buy_tree': self._create_random_tree(), 'sell_tree': self._create_random_tree()} for _ in
                      range(self.population_size)]

        for gen in range(self.generations):
            if self.trading_system.stop_event.is_set():
                logger.warning("[GP] Эволюция прервана из-за остановки системы.");
                return

            fitness_scores = sorted([(self._fitness(ind), ind) for ind in population], key=lambda x: x[0], reverse=True)

            best_individual = fitness_scores[0][1]
            best_fitness = fitness_scores[0][0]
            strategy_str = f"BUY: {best_individual['buy_tree']} | SELL: {best_individual['sell_tree']}"
            progress_data = {'generation': gen + 1, 'best_fitness': best_fitness, 'strategy_str': strategy_str}
            if hasattr(self.trading_system, 'rd_progress_updated'):
                self.trading_system.rd_progress_updated.emit(progress_data)
            logger.info(f"Поколение {gen + 1}/{self.generations}: Лучший Fitness: {best_fitness:.4f}")

            next_generation = []
            elite = [ind for fitness, ind in fitness_scores[:self.elitism_size]]
            next_generation.extend(elite)

            while len(next_generation) < self.population_size:
                parent1 = self._tournament_selection(fitness_scores)
                parent2 = self._tournament_selection(fitness_scores)
                if random.random() < self.crossover_rate:
                    child1, child2 = self._crossover(parent1, parent2)
                else:
                    child1, child2 = copy.deepcopy(parent1), copy.deepcopy(parent2)
                if random.random() < self.mutation_rate:
                    child1 = self._mutate(child1)
                if random.random() < self.mutation_rate:
                    child2 = self._mutate(child2)
                next_generation.append(child1)
                if len(next_generation) < self.population_size:
                    next_generation.append(child2)
            population = next_generation

        final_fitness_scores = sorted([(self._fitness(ind), ind) for ind in population], key=lambda x: x[0],
                                      reverse=True)
        best_overall_individual = final_fitness_scores[0][1]
        logger.info(
            f"GP завершен. Лучшая стратегия: BUY: {best_overall_individual['buy_tree']} | SELL: {best_overall_individual['sell_tree']}")
        self._save_strategy(best_overall_individual)

    def _save_strategy(self, individual: dict):
        try:
            strategy_name = f"GP_Strategy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
            file_path = self.strategies_path / strategy_name
            with open(file_path, "wb") as f:
                pickle.dump(individual, f)
            logger.info(f"Лучшая стратегия сохранена в файл: {file_path}")
        except Exception as e:
            logger.error(f"Не удалось сохранить сгенерированную стратегию: {e}")
            return None