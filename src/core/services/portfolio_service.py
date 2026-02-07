# src/core/services/portfolio_service.py
import asyncio
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple  # <--- ИСПРАВЛЕНИЕ: Добавлен импорт Tuple

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from src.core.config_models import Settings
from src.data.data_provider import DataProvider
from src.ml.rl_trade_manager import RLTradeManager

logger = logging.getLogger(__name__)


class PortfolioService:
    """
    Отвечает за управление состоянием портфеля, включая открытые позиции,
    данные о входах и применение RL-логики для управления сделками.
    """

    def __init__(self, config: Settings, rl_manager: RLTradeManager, data_provider: DataProvider,
                 mt5_lock: threading.Lock):
        self.portfolio_service = None
        self.risk_engine = None
        self.config = config
        self.rl_manager = rl_manager
        self.data_provider = data_provider
        self.mt5_lock = mt5_lock
        self.trade_entry_data: Dict[int, Any] = {}
        self.entry_data_persistence_file = Path(self.config.DATABASE_FOLDER) / "trade_entry_data.json"
        self.data_lock = threading.Lock()  # Блокировка для защиты данных
        self._load_trade_entry_data()
        self.n_steps = self.config.INPUT_LAYER_SIZE
        self.features = self.config.FEATURES_TO_USE

    def _save_trade_entry_data(self):
        with self.data_lock:
            try:
                data_to_save = {}

                # --- Вспомогательная рекурсивная функция для преобразования типов ---
                def convert_to_serializable(obj):
                    """Рекурсивно преобразует типы NumPy/Pandas в стандартные Python-типы."""
                    if isinstance(obj, (np.float32, np.float64, np.generic)):
                        return float(obj)
                    if isinstance(obj, (np.ndarray)):
                        return [convert_to_serializable(x) for x in obj.tolist()]
                    if isinstance(obj, (pd.Timestamp, datetime)): # <--- ДОБАВЛЕНО: pd.Timestamp и datetime
                        return obj.isoformat()
                    if isinstance(obj, list):
                        return [convert_to_serializable(x) for x in obj]
                    if isinstance(obj, dict):
                        return {k: convert_to_serializable(v) for k, v in obj.items()}
                    return obj

                # ------------------------------------------------------------------

                for k, v in self.trade_entry_data.items():
                    item_copy = v.copy()

                    # --- ИСПРАВЛЕНИЕ: Применяем рекурсивное преобразование ко всей копии элемента ---
                    data_to_save[str(k)] = convert_to_serializable(item_copy)
                    # ------------------------------------------------------------------------------

                # --- ИСПРАВЛЕНИЕ: Добавляем временный файл для атомарной записи ---
                temp_file = self.entry_data_persistence_file.with_suffix('.tmp')

                with open(temp_file, 'w') as f:
                    json.dump(data_to_save, f, indent=4)

                    # Атомарная запись
                temp_file = self.entry_data_persistence_file.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    json.dump(data_to_save, f, indent=4)
                os.replace(temp_file, self.entry_data_persistence_file)

            except Exception as e:
                logger.error(f"Не удалось сохранить данные о входах в сделки: {e}")

    def _load_trade_entry_data(self):
        with self.data_lock:
            if not self.entry_data_persistence_file.exists():
                return
            try:
                with open(self.entry_data_persistence_file, 'r') as f:
                    loaded_data = json.load(f)
                    self.trade_entry_data = {int(k): v for k, v in loaded_data.items()}

                    # --- ИСПРАВЛЕНИЕ: Рекурсивное преобразование списков обратно в np.ndarray ---
                    for ticket, data in self.trade_entry_data.items():
                        if 'entry_bar_time' in data and isinstance(data['entry_bar_time'], str):
                            data['entry_bar_time'] = pd.to_datetime(data['entry_bar_time'])

                        # Рекурсивная функция для преобразования списков в np.ndarray
                        def convert_to_numpy(obj):
                            if isinstance(obj, list):
                                # Проверяем, является ли список массивом чисел
                                if all(isinstance(x, (int, float)) for x in obj):
                                    return np.array(obj, dtype=np.float32)
                                # Если это вложенный список (например, последовательность), рекурсивно обрабатываем
                                return [convert_to_numpy(x) for x in obj]
                            if isinstance(obj, dict):
                                return {k: convert_to_numpy(v) for k, v in obj.items()}
                            return obj

                        # Применяем преобразование к ключевым полям
                        if 'prediction_input_sequence' in data and isinstance(data['prediction_input_sequence'], list):
                            data['prediction_input_sequence'] = convert_to_numpy(data['prediction_input_sequence'])
                    # ---------------------------------------------------------------------------------

                logger.info(f"Данные о {len(self.trade_entry_data)} активных сделках успешно загружены.")
            except json.JSONDecodeError as e:
                logger.error(
                    f"Не удалось загрузить данные о входах в сделки: Файл поврежден (JSONDecodeError: {e}). Файл будет проигнорирован.")
                # Если файл поврежден, мы его игнорируем, чтобы система могла запуститься
                self.trade_entry_data = {}
            except Exception as e:
                logger.error(f"Не удалось загрузить данные о входах в сделки: {e}")

    def add_trade_entry_data(self, position_id: int, data: dict):
        with self.data_lock:
            self.trade_entry_data[position_id] = data
        self._save_trade_entry_data()

    def remove_trade_entry_data(self, position_id: int):
        with self.data_lock:
            if position_id in self.trade_entry_data:
                del self.trade_entry_data[position_id]
        self._save_trade_entry_data()

    def get_entry_data(self, position_id: int) -> Dict:
        """
        Потокобезопасно получает данные о входе для одной сделки.
        """
        with self.data_lock:
            return self.trade_entry_data.get(position_id, {}).copy()

    def update_trade_with_xai_data(self, position_id: int, xai_data: dict):
        """
        Добавляет XAI-данные к существующей записи об активной сделке.
        """
        with self.data_lock:
            if position_id in self.trade_entry_data:
                self.trade_entry_data[position_id]['xai_data'] = xai_data
                logger.info(f"XAI-данные успешно добавлены в память для активной сделки #{position_id}.")
                # Сразу сохраняем обновленные данные на диск
                self._save_trade_entry_data()
            else:
                logger.warning(f"Не удалось найти активную сделку #{position_id} для добавления XAI-данных.")

    async def manage_all_open_positions(self, open_positions: List[Any], execution_service):
        if not open_positions or not self.rl_manager.is_trained:
            return

        management_tasks = [self._manage_single_position(pos, execution_service) for pos in open_positions]
        await asyncio.gather(*management_tasks)

    async def _manage_single_position(self, position: Any, execution_service):
        position_id = position.ticket
        state_data = self.get_entry_data(position_id)
        entry_timeframe = state_data.get("entry_timeframe")

        if not entry_timeframe:
            logger.warning(f"[{position.symbol}] Пропуск управления: нет данных о таймфрейме входа.")
            return

        # 1. Загрузка данных для RL-агента
        df_dict = await self.data_provider.get_all_symbols_data_async(
            [position.symbol],
            [entry_timeframe],
            num_bars_override=self.config.INPUT_LAYER_SIZE + 5
        )
        df = df_dict.get(f"{position.symbol}_{entry_timeframe}")

        if df is None or df.empty or len(df) < self.config.INPUT_LAYER_SIZE:
            logger.warning(f"[{position.symbol}] Пропуск управления: недостаточно данных для RL-агента.")
            return

        # --- 2. ЛОГИКА ЗАЩИТЫ ПРИБЫЛИ (TRAILING PROFIT) ---
        # ... (логика Trailing Profit остается без изменений) ...
        trailing_config = self.config.risk.trailing_profit

        if trailing_config.enabled:
            current_price = df['close'].iloc[-1]
            entry_price = position.price_open

            if position.type == mt5.ORDER_TYPE_BUY:
                current_profit_pct = (current_price - entry_price) / entry_price * 100
            else:
                current_profit_pct = (entry_price - current_price) / entry_price * 100

            max_profit_pct = state_data.get('max_reached_profit_pct', 0.0)
            if current_profit_pct > max_profit_pct:
                max_profit_pct = current_profit_pct
                state_data['max_reached_profit_pct'] = max_profit_pct
                self.add_trade_entry_data(position_id, state_data)

            if max_profit_pct >= trailing_config.activation_threshold_percent:
                drawdown_limit = max_profit_pct - trailing_config.pullback_percent

                if current_profit_pct <= drawdown_limit:
                    logger.warning(
                        f"[Trailing Profit] Закрытие позиции #{position_id} ({position.symbol}). "
                        f"Причина: Прибыль упала с пика {max_profit_pct:.2f}% до {current_profit_pct:.2f}%."
                    )
                    await execution_service.emergency_close_position(position.ticket)
                    return

        # --- 3. ЛОГИКА RL-АГЕНТА ---
        if self.rl_manager.is_trained:
            try:
                # 3.1. Формируем вектор состояния
                state_vector, portfolio_state = self._calculate_state_vector(position, df, state_data)

                # 3.2. Получаем действие
                action = self.rl_manager.get_action(state_vector, portfolio_state)
                action_map = {0: "HOLD", 1: "CLOSE_50%", 2: "MOVE_SL_TO_BE", 3: "CLOSE_100%"}

                logger.info(
                    f"[RL Manager] Позиция #{position_id} ({position.symbol}): Решение: {action_map.get(action, 'UNKNOWN')}")

                # 3.3. Исполняем действие
                if action == 1:  # CLOSE_50%
                    await execution_service.close_position_partial(position)
                elif action == 2:  # MOVE_SL_TO_BE
                    # --- НОВАЯ ПРОВЕРКА: Должна быть прибыль > 1 ATR ---
                    if 'ATR_14' in df.columns:
                        current_atr = df['ATR_14'].iloc[-1]
                        min_profit_for_be = current_atr * 0.5  # Минимальная прибыль в 0.5 ATR

                        current_profit_in_price = position.profit / position.volume / 100000  # Прибыль в цене

                        if current_profit_in_price >= min_profit_for_be and not state_data.get('sl_moved_to_be', False):
                            # Вызываем модификацию с ценой открытия
                            await execution_service.modify_position_sltp_to_be(position.ticket, position.price_open)
                            state_data['sl_moved_to_be'] = True
                            self.add_trade_entry_data(position_id, state_data)
                        elif current_profit_in_price < min_profit_for_be:
                            logger.info(
                                f"[{position.symbol}] SL to BE отклонен: прибыль ({current_profit_in_price:.5f}) < 0.5 ATR ({min_profit_for_be:.5f}).")

                elif action == 3:  # CLOSE_100%
                    await execution_service.emergency_close_position(position.ticket)

            except Exception as e:
                logger.error(f"Ошибка в RL-управлении позицией #{position_id}: {e}", exc_info=True)

    def _calculate_state_vector(self, position: Any, df: pd.DataFrame, state_data: dict) -> Tuple[
        np.ndarray, np.ndarray]:
        """
        Формирует полный вектор состояния для RLTradeManager.

        Возвращает:
            Tuple[np.ndarray, np.ndarray]: (market_state_vector, portfolio_state_vector)
        """

        # --- 1. Вектор рыночного состояния (Market State Vector) ---

        # Проверяем, что все необходимые фичи есть и данных достаточно
        if not all(f in df.columns for f in self.features) or len(df) < self.n_steps:
            # Возвращаем векторы из нулей, чтобы не сломать RL-агента
            market_state_vector = np.zeros(self.n_steps * len(self.features), dtype=np.float32)
            portfolio_state_vector = np.zeros(3, dtype=np.float32)
            return market_state_vector, portfolio_state_vector

        # Берем последние N баров и сглаживаем их в один вектор
        market_data = df[self.features].tail(self.n_steps).values
        market_state_vector = market_data.flatten()

        # --- 2. Вектор состояния позиции (Portfolio State Vector) ---

        current_price = df['close'].iloc[-1]
        trade_type_multiplier = 1 if position.type == mt5.ORDER_TYPE_BUY else -1

        # Нормализованная прибыль (PnL / Initial Risk)
        initial_risk_price = abs(position.price_open - position.sl)
        profit = (current_price - position.price_open) * trade_type_multiplier
        norm_profit = profit / initial_risk_price if initial_risk_price > 0 else 0

        # Нормализованное время в сделке
        entry_bar_time = state_data.get("entry_bar_time")
        bars_in_trade = (datetime.now() - entry_bar_time).total_seconds() / 3600 if entry_bar_time else 0
        norm_bars_in_trade = bars_in_trade / 100.0  # Нормализация по 100 часам

        # Вектор для RLTradeManager (3 элемента)
        portfolio_state_vector = np.array([
            trade_type_multiplier,  # 1 или -1
            np.clip(norm_profit * 100, -5, 5),  # Нормализованный PnL (в % от риска, клиппинг)
            np.clip(norm_bars_in_trade, 0, 5)  # Нормализованное время в сделке
        ], dtype=np.float32)

        return market_state_vector, portfolio_state_vector

    def _persist_entry_data(self, pos_id, symbol, strategy, sl, xai, pred_in, entry_price, entry_time, timeframe, df,
                            predicted_price=None):
        market_context = {
            'market_regime': self.risk_engine.trading_system.market_regime_manager.get_regime(df),
            'news_sentiment': self.risk_engine.trading_system.news_cache.aggregated_sentiment if self.risk_engine.trading_system.news_cache else None,
            # --- ДОБАВЛЕНО: Сохраняем текущие KG-признаки ---
            'kg_cb_sentiment': df['KG_CB_SENTIMENT'].iloc[-1] if 'KG_CB_SENTIMENT' in df.columns else 0.0,
            'kg_inflation_surprise': df['KG_INFLATION_SURPRISE'].iloc[
                -1] if 'KG_INFLATION_SURPRISE' in df.columns else 0.0,
            # -------------------------------------------------
        }
        entry_data = {
            "symbol": symbol, "strategy": strategy, "stop_loss_price": sl,
            "prediction_input_sequence": pred_in.tolist() if isinstance(pred_in, np.ndarray) else pred_in,
            "entry_price_for_learning": entry_price,
            "predicted_price_at_entry": predicted_price,
            "entry_bar_time": entry_time, "entry_timeframe": timeframe, "market_context": market_context
        }
        self.portfolio_service.add_trade_entry_data(pos_id, entry_data)