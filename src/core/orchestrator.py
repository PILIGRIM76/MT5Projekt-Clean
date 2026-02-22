# src/core/orchestrator.py
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Dict, Any, Optional
import pandas as pd
import numpy as np
from pathlib import Path
import asyncio
import os
import MetaTrader5 as mt5
#from networkx import config

from src.core.config_writer import write_config
from src.core.config_loader import load_config
from src.ml.orchestrator_env import OrchestratorEnv
from stable_baselines3 import PPO
from stable_baselines3.common.buffers import ReplayBuffer
from stable_baselines3.common.vec_env import DummyVecEnv

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem
    from src.analysis.strategy_optimizer import StrategyOptimizer
    from src.db.database_manager import DatabaseManager
    from src.data.data_provider import DataProvider

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, trading_system: 'TradingSystem', strategy_optimizer: 'StrategyOptimizer',
                 db_manager: 'DatabaseManager', data_provider: 'DataProvider'):
        self.trading_system = trading_system
        self.config = trading_system.config
        self.orchestrator_config = self.config.orchestrator_settings
        self.last_training_time = time.time()
        self.training_interval = self.orchestrator_config.training_interval_seconds
        self.strategy_optimizer = strategy_optimizer
        self.db_manager = db_manager
        self.data_provider = data_provider
        self.last_decision_time = 0
        self.decision_interval = 3600 * 4  # 4 часа

        # --- Передаем ссылку на систему в среду ---
        self.env = OrchestratorEnv(self.trading_system)
        self.vec_env = DummyVecEnv([lambda: self.env])

        # ---  Инициализация режимов и стратегий из ENV ---
        self.strategy_names = self.env.strategy_names
        self.regime_names = self.env.regime_names
        self.num_strategies = len(self.strategy_names)
        self.num_regimes = len(self.regime_names)
        # -----------------------------------------------------------

        self.model_path = Path(self.config.DATABASE_FOLDER) / "orchestrator_ppo_model.zip"

        if self.model_path.exists():
            try:
                logger.info(f"Загрузка обученной модели Оркестратора из {self.model_path}...")
                # ИСПРАВЛЕНИЕ: Добавляем device="cpu" при загрузке
                self.agent = PPO.load(self.model_path, self.vec_env, device="cpu")
            except Exception as e:
                # ... (логика обработки ошибки загрузки) ...
                # ИСПРАВЛЕНИЕ: Добавляем device="cpu" при создании новой модели
                self.agent = PPO("MlpPolicy", self.vec_env, verbose=0, n_steps=64, batch_size=32,
                                 tensorboard_log="./orchestrator_logs/", device="cpu")
        else:
            logger.warning("Обученная модель Оркестратора не найдена. Создание новой модели PPO...")
            # ИСПРАВЛЕНИЕ: Добавляем device="cpu" при создании новой модели
            self.agent = PPO("MlpPolicy", self.vec_env, verbose=0, n_steps=64, batch_size=32,
                             tensorboard_log="./orchestrator_logs/", device="cpu")



        buffer_size = 1000
        # ... (Настройка буфера воспроизведения остается прежней, принимая новую форму действия)  ...
        self.replay_buffer = ReplayBuffer(
            buffer_size=buffer_size,
            observation_space=self.env.observation_space,
            action_space=self.env.action_space,
            handle_timeout_termination=False
        )
        self.last_obs, _ = self.env.reset()
        self.training_lock = threading.Lock()
        self.agent_lock = threading.Lock()
        self.last_training_time = time.time()
        self.training_interval = 86400 * 7

        logger.info("Мета-обучающийся Оркестратор (v3.0 - Regime-Oriented) инициализирован.")

    def _check_incubation_status(self):
        """
        Проверяет стратегии в инкубаторе и переводит их в 'live' при истечении срока (30 дней).
        """
        incubation_period = timedelta(days=30)

        # Используем новый метод db_manager
        incubating_strategies = self.db_manager.get_strategies_by_status('incubating')

        for strategy_stats in incubating_strategies:
            name = strategy_stats['strategy_name']
            start_date = strategy_stats.get('incubation_start_date')

            if start_date and datetime.utcnow() - start_date >= incubation_period:
                logger.critical(f"[Orchestrator HR] ИНКУБАЦИЯ ЗАВЕРШЕНА! Стратегия '{name}' переведена в LIVE.")
                self.db_manager.update_strategy_status(name, 'live')
                # Принудительно перезагружаем стратегии в TradingSystem
                self.trading_system.strategies = self.trading_system.strategy_loader.load_strategies()
            elif start_date:
                remaining = incubation_period - (datetime.utcnow() - start_date)
                logger.debug(f"[Orchestrator HR] Стратегия '{name}' в инкубации. Осталось: {remaining.days} дней.")
            else:
                logger.warning(f"[Orchestrator HR] Стратегия '{name}' в статусе 'incubating', но без даты старта.")


    def apply_drift_penalty(self, strategy_name: str, symbol: str):
        """
        Мягкая реакция: Регистрирует штраф для стратегии/модели из-за дрейфа.
        """
        key = f"{strategy_name}_{symbol}"  # Можно детализировать до символа, если стратегия специфична
        # В текущей архитектуре стратегии общие, но AI_Model специфична для символа.
        # Для простоты будем штрафовать стратегию "AI_Model" глобально или использовать более сложный маппинг.

        # Если это AI модель, мы можем уменьшить вес "AI_Model" в аллокации
        if "AI_Model" in strategy_name:
            logger.warning(f"[Orchestrator] Применен штраф за дрейф к {strategy_name} ({symbol}).")
            self.drift_penalties[symbol] = 0.5  # Снижаем риск в 2 раза для этого символа

            # Обновляем директиву риска для конкретного символа через RiskEngine (нужна доработка RiskEngine для по-символьного риска)
            # В текущей версии RiskEngine управляет общим распределением.
            # Мы можем добавить директиву блокировки или снижения риска.

            self.trading_system.add_directive(
                directive_type=f"REDUCE_RISK_{symbol}",
                reason="Concept Drift Detected",
                duration_hours=24,
                value=0.5
            )

    def clear_drift_penalty(self, symbol: str):
        """Снимает штраф после переобучения."""
        self.trading_system.delete_directive(f"REDUCE_RISK_{symbol}")
        if symbol in self.drift_penalties:
            del self.drift_penalties[symbol]

    def run_cycle(self):
        current_time = time.time()
        if current_time - self.last_decision_time < self.decision_interval:
            return

        logger.info("[Orchestrator 3.0] Запуск нового цикла принятия решений (Режимно-ориентированный)...")

        self._manage_strategy_pool()
        self._check_incubation_status()

        # --- RL.3: АДАПТИВНЫЙ R&D ТРИГГЕР (Новая логика) ---
        should_force_rd = False

        # 1. Проверка Дрейфа Концепции (Concept Drift)
        if self.trading_system.has_active_drift():
            logger.critical("[Orchestrator] АДАПТИВНЫЙ ТРИГГЕР: Обнаружен активный ДРЕЙФ КОНЦЕПЦИИ. Запуск R&D.")
            should_force_rd = True

        # 2. Проверка высокого VaR (VaR > 1.5 * Max_VaR_Config)
        state = self.trading_system.get_rl_orchestrator_state()
        current_var = state.get('portfolio_var', 0.0)
        max_var_config = self.trading_system.config.MAX_PORTFOLIO_VAR_PERCENT

        # Проверяем, что VaR превышает лимит с запасом 50%
        if current_var > max_var_config * 1.5:
            logger.critical(f"[Orchestrator] АДАПТИВНЫЙ ТРИГГЕР: Высокий VaR ({current_var:.2%}). Запуск R&D.")
            should_force_rd = True

        if should_force_rd:
            # Вызываем метод, который запустит R&D в отдельном потоке
            self.trading_system.force_rd_cycle()
            # Продолжаем цикл, чтобы применить новое распределение капитала
        # -------------------------------------------------

        # 3. Проверка существования агента перед вызовом
        if not hasattr(self, 'agent') or self.agent is None:
            logger.error("[Orchestrator] Агент не инициализирован, пропуск цикла.")
            return
            
        # 3. Агент предсказывает матрицу распределения (N_regimes x N_strategies)
        try:
            action_matrix, _ = self.agent.predict(self.last_obs, deterministic=True)
        except Exception as e:
            logger.error(f"[Orchestrator] Ошибка при предсказании агента: {e}")
            return

        # 4. Выполняем шаг. apply_orchestrator_action вызывается внутри env.step.
        new_obs, reward, terminated, truncated, info = self.env.step(action_matrix)

        # 5. Добавляем в буфер. Action теперь - это матрица.
        self.replay_buffer.add(self.last_obs, new_obs, action_matrix, np.array([reward]), np.array([terminated]),
                               [info])

        self.last_obs = new_obs
        self.last_decision_time = current_time

        if current_time - self.last_training_time > self.training_interval:
            if self.replay_buffer.size() > self.agent.batch_size:
                logger.warning("[Orchestrator 3.0] Накоплено достаточно опыта. Запуск дообучения.")
                training_thread = threading.Thread(target=self._train_agent, daemon=True)
                training_thread.start()
                self.last_training_time = current_time

    def _manage_strategy_pool(self):
        logger.info("[Orchestrator HR] Анализ производительности пула стратегий...")

        live_strategies = self.db_manager.get_all_live_strategy_performance()
        min_trades_for_review = self.config.rd_cycle_config.performance_check_trades_min

        for strategy_stats in live_strategies:
            name = strategy_stats['strategy_name']
            pf = strategy_stats['profit_factor']
            trades = strategy_stats['trade_count']

            if pf < 1.0 and trades > min_trades_for_review:
                logger.critical(f"[Orchestrator HR] УВОЛЬНЕНИЕ! Стратегия '{name}' показывает стабильно плохие "
                                f"результаты (PF: {pf:.2f} на {trades} сделках). Деактивация...")
                self.db_manager.deactivate_strategy(name)

        weak_spots = self.db_manager.find_weak_spots(
            profit_factor_threshold=self.config.rd_cycle_config.profit_factor_threshold
        )
        if weak_spots:
            spot = weak_spots[0]
            symbol = spot['symbol']
            regime = spot['market_regime']

            logger.critical(f"[Orchestrator HR] НАЕМ! Обнаружено слабое место: нет эффективной стратегии "
                            f"для '{symbol}' в режиме '{regime}'. Формирование заказа для R&D...")

            rd_thread = threading.Thread(
                target=self.trading_system.gp_rd_manager.run_cycle,
                args=(symbol, mt5.TIMEFRAME_H1, regime),
                daemon=True
            )
            rd_thread.start()
        else:
            logger.info("[Orchestrator HR] 'Слабых мест' для найма новых стратегий не обнаружено.")

    def _train_agent(self):
        if not self.training_lock.acquire(blocking=False):
            logger.info("[Orchestrator 3.2] Обучение уже запущено, пропуск.")
            return

        try:
            state = self.trading_system.get_rl_orchestrator_state()
            sharpe_ratio = state.get('sharpe_ratio', 0.0)
            final_reward = sharpe_ratio

            logger.info(f"[Orchestrator 3.2] Расчетная награда за период: {final_reward:.2f}")

            if self.replay_buffer.size() > 0:
                last_experience_index = (self.replay_buffer.pos - 1) % self.replay_buffer.buffer_size
                self.replay_buffer.rewards[last_experience_index] = np.array([final_reward])
            with self.agent_lock:
                self.agent.learn(total_timesteps=self.agent.n_steps * 10)
                self.agent.save(self.model_path)
            logger.warning(f"Оркестратор дообучен. Модель сохранена в {self.model_path}")

            self.replay_buffer.reset()

        except Exception as e:
            logger.error(f"Ошибка в процессе обучения Оркестратора: {e}", exc_info=True)
        finally:
            self.training_lock.release()