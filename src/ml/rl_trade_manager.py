# src/ml/rl_trade_manager.py
import logging
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from typing import Optional, List, Any
from pathlib import Path
import MetaTrader5 as mt5
from datetime import datetime, timedelta

from src.core.config_models import Settings
from src.data.data_provider import DataProvider

logger = logging.getLogger(__name__)


class TradingLifecycleEnv(gym.Env):
    """
    Среда, симулирующая полный торговый цикл: открытие, удержание и закрытие.
    Агент обучается принимать решения на каждом шаге.
    """
    metadata = {'render_modes': ['human']}

    def __init__(self, df: pd.DataFrame, config: Settings, features: List[str]):
        super(TradingLifecycleEnv, self).__init__()
        self.df = df
        self.config = config
        self.features = features
        self.n_features = len(features)
        self.n_steps = self.config.INPUT_LAYER_SIZE
        self.rewards_config = config.rl_manager.rewards

        # Пространство действий: 0 - HOLD, 1 - CLOSE_50%, 2 - MOVE_SL_TO_BE, 3 - CLOSE_100%
        self.action_space = spaces.Discrete(5)

        # Пространство состояний: (N_STEPS * N_FEATURES) рыночных данных + 3 параметра портфеля
        # 3 параметра: [Норм. PnL, Норм. BarsInTrade, Позиция (1/-1)]
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self.n_steps * self.n_features + 3,),
            dtype=np.float32
        )
        self.initial_balance = 10000
        self.reset()

    def _get_obs(self) -> np.ndarray:
        """Собирает состояние из рыночных данных и состояния портфеля."""
        # 1. Рыночные данные (последние N свечей)
        market_data = self.df[self.features].iloc[self.current_step - self.n_steps:self.current_step].values
        market_data_flat = market_data.flatten()

        # 2. Состояние портфеля
        current_price = self.df['close'].iloc[self.current_step]
        unrealized_pnl = 0
        if self.position == 1:  # Long
            unrealized_pnl = (current_price - self.entry_price) / self.entry_price
        elif self.position == -1:  # Short
            unrealized_pnl = (self.entry_price - current_price) / self.entry_price

        portfolio_state = np.array([
            self.position,
            np.clip(unrealized_pnl * 100, -5, 5),  # Нормализуем и ограничиваем PnL
            self.bars_in_trade / 100.0  # Нормализуем кол-во баров в сделке
        ], dtype=np.float32)

        return np.concatenate((market_data_flat, portfolio_state))

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        # Начинаем с рандомной точки, чтобы агент не переобучался на начале данных
        self.start_idx = np.random.randint(self.n_steps, len(self.df) - 200)
        self.current_step = self.start_idx
        self.balance = self.initial_balance
        self.position = 0  # 0: нет позиции, 1: long, -1: short
        self.entry_price = 0
        self.bars_in_trade = 0
        self.sl_moved_to_be = False
        self.current_sl = 0  # Добавлено для имитации трейлинг-стопа
        return self._get_obs(), {}

    def step(self, action):
        # --- ИЗВЛЕЧЕНИЕ ATR с защитой от ошибок ---
        current_atr = 0.0
        if 'ATR_14' in self.df.columns:
            atr_value = self.df['ATR_14'].iloc[self.current_step]
            if pd.notna(atr_value) and atr_value > 0:
                current_atr = atr_value
            else:
                logger.warning(f"ATR_14 недействителен на шаге {self.current_step}: {atr_value}, используется 0.0")
        # ----------------------
        
        self.current_step += 1
        done = self.current_step >= len(self.df) - 1
        reward = 0
        current_price = self.df['close'].iloc[self.current_step]

        # --- Расчет PnL и PnL_Norm для использования в наградах/штрафах ---
        unrealized_pnl_pct = 0
        if self.position == 1:  # Long
            unrealized_pnl_pct = (current_price - self.entry_price) / self.entry_price if self.entry_price != 0 else 0
        elif self.position == -1:  # Short
            unrealized_pnl_pct = (self.entry_price - current_price) / self.entry_price if self.entry_price != 0 else 0

        pnl_norm = unrealized_pnl_pct * 100
        # ------------------------------------------------------------------

        # 0: HOLD
        if action == 0:
            if self.position != 0:
                self.bars_in_trade += 1
                reward += unrealized_pnl_pct * self.rewards_config.hold_reward_multiplier

                # --- TZ 3.2: Штраф за "Пересиживание" ---
                if pnl_norm < 0 and self.bars_in_trade > 20:
                    # Penalty_Hold = -0.01 * PnL_Norm * exp(Bars / 20)
                    penalty_hold = -0.01 * pnl_norm * np.exp(self.bars_in_trade / 20.0)
                    reward -= penalty_hold
                # -----------------------------------------

        # 1: CLOSE_50%
        elif action == 4 and self.position != 0:
            reward += unrealized_pnl_pct * self.rewards_config.partial_close_multiplier

            # --- TZ 3.1: Награда за Частичный TP ---
            if current_atr > 0:
                # PnL в цене
                pnl_in_price = current_price - self.entry_price if self.position == 1 else self.entry_price - current_price

                # Проверка: PnL > 1.5 * ATR
                if pnl_in_price > 1.5 * current_atr:
                    reward += 0.2  # Фиксированный бонус
            # ---------------------------------------

            self.position = self.position / 2
            if abs(self.position) < 0.01: self.position = 0

        # 2: MOVE_SL_TO_BE
        elif action == 2 and self.position != 0:
            unrealized_pnl = (current_price - self.entry_price) / self.entry_price * self.position
            if unrealized_pnl > 0.001 and not self.sl_moved_to_be:
                reward += self.rewards_config.move_sl_to_be_reward
                self.sl_moved_to_be = True
            else:
                reward += self.rewards_config.move_sl_to_be_penalty

        # 3: CLOSE_100%
        elif action == 3 and self.position != 0:
            unrealized_pnl = (current_price - self.entry_price) / self.entry_price * self.position
            reward += unrealized_pnl * 1.0
            self.position = 0
            self.bars_in_trade = 0
            done = True

            # --- TZ 3.1: НОВОЕ ДЕЙСТВИЕ: PARTIAL_CLOSE_RISK (действие 4) ---
        elif action == 4 and self.position != 0:
            # Имитация VaR позиции: для простоты берем PnL_Norm
            # InitialRisk_Position = 1.0 (в нормализованных единицах)
            # CurrentVaR_Position (имитация) = -PnL_Norm (если в убытке)

            # Проверка: CurrentVaR_Position > 2.0 * InitialRisk_Position
            # (Т.е. убыток > 2% от цены входа)
            is_high_risk = pnl_norm < -2.0

            if is_high_risk:
                # Уменьшаем позицию на 25%
                self.position *= 0.75
                reward += 0.1  # Небольшая награда за дисциплину
                logger.info(f"[RL-Trader] PARTIAL_CLOSE_RISK: Убыток > 2%. Позиция уменьшена. Reward: 0.1")
            else:
                reward -= 0.1  # Штраф за ненужное закрытие

            if abs(self.position) < 0.01: self.position = 0

        # --- Имитация открытия позиции (если нет позиции) ---
        elif self.position == 0:
            if action == 1:  # BUY
                self.position = 1
                self.entry_price = current_price
                self.current_sl = current_price - self.config.STOP_LOSS_ATR_MULTIPLIER * current_atr
                reward -= 0.0005
            elif action == 2:  # SELL
                self.position = -1
                self.entry_price = current_price
                self.current_sl = current_price + self.config.STOP_LOSS_ATR_MULTIPLIER * current_atr
                reward -= 0.0005

        # --- Штраф за слишком долгое удержание (остается как дополнительный выход) ---
        if self.bars_in_trade > 200:
            reward -= 0.1
            done = True

        return self._get_obs(), reward, done, False, {}


class RLTradeManager:
    def __init__(self, config: Settings, data_provider: DataProvider):
        self.config = config
        self.data_provider = data_provider
        self.model_path = Path(self.config.DATABASE_FOLDER) / "rl_trader_ppo.zip"
        self.is_trained = False
        self.model: Optional[PPO] = None
        self.load_model()

    def load_model(self):
        if self.model_path.exists():
            try:
                # Загружаем модель без среды, так как среда создается в train()
                self.model = PPO.load(self.model_path, device='cpu')
                self.is_trained = True
                logger.info(f"RL-модель ТРЕЙДЕРА успешно загружена на CPU из {self.model_path}")
            except Exception as e:
                logger.error(f"Не удалось загрузить RL-модель трейдера: {e}. Требуется обучение.")
                self.model = None
                self.is_trained = False
        else:
            logger.warning("Обученная RL-модель трейдера не найдена. Требуется обучение.")

    def train(self):
        if not self.data_provider:
            logger.error("DataProvider не доступен, обучение RL-агента невозможно.")
            return

        logger.warning("[RL Trader] Запуск полного цикла обучения RL-трейдера...")

        # 1. Загрузка данных
        df_featured = self.data_provider.get_historical_data(
            "EURUSD", mt5.TIMEFRAME_H1,
            datetime.now() - timedelta(days=730),  # 2 года данных
            datetime.now()
        )

        if df_featured is None or df_featured.empty or len(df_featured) < self.config.INPUT_LAYER_SIZE + 100:
            logger.error("Недостаточно данных для обучения RL-трейдера.")
            return

        # 2. Создание среды
        env = TradingLifecycleEnv(df_featured, self.config, self.config.FEATURES_TO_USE)
        vec_env = DummyVecEnv([lambda: env])

        # 3. Инициализация/Дообучение модели
        if self.model is None:
            # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: Принудительное создание на CPU ---
            self.model = PPO("MlpPolicy", vec_env, verbose=0, n_steps=2048, batch_size=64, device='cpu')
        else:
            # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 3: Установка среды на CPU-модель ---
            self.model.set_env(vec_env)
            self.model.policy.to('cpu')  # Гарантируем, что политика на CPU
            self.model.device = 'cpu'

        # 4. Обучение
        self.model.learn(total_timesteps=self.config.rl_manager.training_timesteps_per_trade)
        self.model.save(self.model_path)
        self.is_trained = True
        logger.critical(f"Обучение RL-трейдера завершено. Модель сохранена в {self.model_path}")

    def get_action(self, state_vector: np.ndarray, portfolio_state: np.ndarray) -> int:
        """
        Получает действие от RL-агента.

        Args:
            state_vector (np.ndarray): Вектор рыночного состояния (N_STEPS * N_FEATURES).
            portfolio_state (np.ndarray): Вектор состояния позиции (3 элемента).

        Returns:
            int: Действие (0: HOLD, 1: CLOSE_50%, 2: MOVE_SL_TO_BE, 3: CLOSE_100%).
        """
        if not self.is_trained or self.model is None:
            return 0  # HOLD по умолчанию

        # Собираем полное наблюдение
        obs = np.concatenate((state_vector.flatten(), portfolio_state))

        # Модель ожидает (1, N)
        action, _ = self.model.predict(obs, deterministic=True)
        return int(action)