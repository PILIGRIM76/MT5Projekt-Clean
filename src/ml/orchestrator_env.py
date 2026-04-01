# src/ml/orchestrator_env.py
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem

logger = logging.getLogger(__name__)


class OrchestratorEnv(gym.Env):
    metadata = {"render_modes": None}

    def __init__(self, trading_system_ref: "TradingSystem"):

        # --- 1. Определение всех атрибутов, включая spaces ---
        self.trading_system = trading_system_ref

        strategy_class_names = [s.__class__.__name__ for s in self.trading_system.strategies]
        self.strategy_names = ["AI_Model", "RLTradeManager"] + strategy_class_names
        self.strategy_names = sorted(list(set(self.strategy_names)))
        self.num_strategies = len(self.strategy_names)

        self.regime_names = ["Strong Trend", "Weak Trend", "High Volatility Range", "Low Volatility Range", "Default"]
        self.num_regimes = len(self.regime_names)

        # --- RL.1: ДИНАМИЧЕСКОЕ ПРОСТРАНСТВО ДЕЙСТВИЙ (Enable/Disable + Weight) ---
        # Action space shape: (num_regimes, num_strategies * 2)
        self.action_space = spaces.Box(low=0, high=1, shape=(self.num_regimes, self.num_strategies * 2), dtype=np.float32)

        # --- RL.1: РАСШИРЕННОЕ ПРОСТРАНСТВО НАБЛЮДЕНИЙ (8 + Num Regimes) ---
        self.observation_space = spaces.Box(low=-1, high=1, shape=(8 + self.num_regimes,), dtype=np.float32)

        self.start_balance = 10000
        self.last_sharpe = 0.0

        logger.info(f"OrchestratorEnv v3.0 инициализирована. Стратегий: {self.num_strategies}, Режимов: {self.num_regimes}")

        # --- 2. Вызов родительского конструктора (ПЕРЕМЕЩЕНО В КОНЕЦ) ---
        super(OrchestratorEnv, self).__init__()

    def _get_current_regime_one_hot(self) -> Tuple[str, np.ndarray]:
        """Получает текущий режим рынка и его One-Hot кодировку."""
        regime = self.trading_system._get_current_market_regime_name()

        try:
            regime_index = self.regime_names.index(regime)
        except ValueError:
            regime = "Default"
            regime_index = self.regime_names.index(regime)

        one_hot = np.zeros(self.num_regimes, dtype=np.float32)
        one_hot[regime_index] = 1.0
        return regime, one_hot

    def _get_obs(self) -> np.ndarray:
        """Собирает и нормализует состояние системы, включая текущий режим."""
        state = self.trading_system.get_rl_orchestrator_state()
        _, regime_one_hot = self._get_current_regime_one_hot()

        obs_sys = np.zeros(8, dtype=np.float32)

        # Существующие метрики (Индексы 0-4)
        obs_sys[0] = np.clip(state.get("portfolio_var", 0) / self.trading_system.config.MAX_PORTFOLIO_VAR_PERCENT, 0, 1)
        obs_sys[1] = np.clip(state.get("weekly_pnl", 0) / (self.start_balance * 0.1), -1, 1)
        obs_sys[2] = np.clip(state.get("sharpe_ratio", 0) / 3.0, -1, 1)
        obs_sys[3] = np.clip(state.get("win_rate", 0), 0, 1)
        obs_sys[4] = np.clip(state.get("market_volatility", 0), 0, 1)

        # --- RL.1: НОВЫЕ КОГНИТИВНЫЕ ЭЛЕМЕНТЫ (Индексы 5-7) ---
        obs_sys[5] = np.clip(state.get("kg_sentiment", 0), -1, 1)
        obs_sys[6] = np.clip(state.get("drift_status", 0), 0, 1)
        obs_sys[7] = np.clip(state.get("news_sentiment", 0), -1, 1)

        return np.concatenate((obs_sys, regime_one_hot))

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        account_info = self.trading_system.get_account_info()
        if account_info:
            self.start_balance = account_info.balance
        self.last_sharpe = 0.0
        return self._get_obs(), {}

    def step(self, action: np.ndarray):
        # --- ИСПРАВЛЕНИЕ КРИТИЧЕСКОЙ ОШИБКИ: Правильное разделение action_matrix ---

        # action.shape теперь (5, 12) (5 режимов, 6 стратегий * 2)
        logger.info(f"[OrchestratorEnv] Получено действие shape={action.shape}")
        logger.debug(f"[OrchestratorEnv] Action matrix:\n{action}")

        # Разделяем на Enable/Disable и Weight
        enable_actions = action[:, : self.num_strategies]  # Shape: (5, 6)
        weight_actions = action[:, self.num_strategies :]  # Shape: (5, 6)

        logger.debug(f"[OrchestratorEnv] Enable actions:\n{enable_actions}")
        logger.debug(f"[OrchestratorEnv] Weight actions:\n{weight_actions}")

        regime_allocations = {}
        for i in range(self.num_regimes):
            regime = self.regime_names[i]

            # Получаем веса стратегий для данного режима
            raw_weights = weight_actions[i, :]  # Shape: (6,)

            # 🔍 ДИАГНОСТИКА
            logger.info(f"[OrchestratorEnv] Режим {regime}:")
            logger.info(f"  Raw weights от PPO: {raw_weights}")

            # АВТОНОМНОЕ РЕШЕНИЕ: Нормализуем веса как есть
            # PPO модель сама решает какие стратегии выбрать и их веса
            sum_weights = np.sum(raw_weights)
            logger.info(f"  Sum of weights: {sum_weights:.6f}")

            if sum_weights > 1e-6:
                # Нормализуем веса PPO
                normalized_weights = raw_weights / sum_weights
                logger.info(f"  Normalized weights: {normalized_weights}")
            else:
                # КРАЙНИЙ СЛУЧАЙ: Если PPO выдала нулевые веса, используем равномерное распределение
                normalized_weights = np.ones_like(raw_weights) / self.num_strategies
                logger.warning(
                    f"[OrchestratorEnv] ⚠️ PPO выдала нулевые веса для режима '{regime}'! "
                    f"Используется равномерное распределение: {normalized_weights}"
                )

            allocation = {name: float(weight) for name, weight in zip(self.strategy_names, normalized_weights)}
            regime_allocations[regime] = allocation

            logger.info(f"  Allocation: {allocation}")

        # 4. Передаем полную матрицу распределения в TradingSystem
        logger.info(f"[OrchestratorEnv] Передаём распределение в TradingSystem: {len(regime_allocations)} режимов")
        self.trading_system.apply_orchestrator_action(regime_allocations)

        # 5. Расчет награды (Reward)
        new_obs = self._get_obs()
        state = self.trading_system.get_rl_orchestrator_state()
        current_sharpe = state.get("sharpe_ratio", 0.0)
        current_var = state.get("portfolio_var", 0.0)
        max_var_config = self.trading_system.config.MAX_PORTFOLIO_VAR_PERCENT
        kg_sentiment = new_obs[5]  # KG Sentiment находится в obs[5]

        # Базовая награда: изменение коэффициента Шарпа
        reward = current_sharpe - self.last_sharpe
        self.last_sharpe = current_sharpe

        # --- TZ 2.1: Награда за Низкий VaR ---
        reward_var = 0.5 * np.maximum(0, 1 - current_var / max_var_config)
        reward += reward_var
        # -------------------------------------

        # --- TZ 2.2: Награда за KG-Согласие ---
        total_applied_allocation = np.sum(action[:, self.num_strategies :]) / self.num_regimes  # Используем только веса
        reward_kg = 0.1 * total_applied_allocation * np.maximum(0, kg_sentiment)
        reward += reward_kg
        # -------------------------------------

        # Дополнительные бонусы и штрафы (остаются без изменений)
        diversity_reward = 0.0
        if self.trading_system.risk_engine:
            diversity_reward = self.trading_system.risk_engine.calculate_diversity_reward(regime_allocations)
        reward += diversity_reward * 0.2

        if current_var > max_var_config:
            reward -= 0.5 * (current_var / max_var_config)

        reward += np.clip(state.get("weekly_pnl", 0) / self.start_balance, -0.01, 0.01) * 100

        drift_status = new_obs[6]
        if drift_status > 0.5:
            total_allocation_sum = np.sum(action) / self.num_regimes
            reward -= total_allocation_sum * 0.5 * drift_status

        kg_sentiment = new_obs[5]
        if np.abs(kg_sentiment) > 0.5:
            total_allocation_sum = np.sum(action) / self.num_regimes
            reward -= total_allocation_sum * np.abs(kg_sentiment) * 0.2

        terminated = False
        truncated = False

        return new_obs, reward, terminated, truncated, {}

    def render(self, mode="human"):
        pass
