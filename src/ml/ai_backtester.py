# src/ml/ai_backtester.py

import pandas as pd
import numpy as np
import logging
from typing import List, Any, Dict

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


class AIBacktester:
    """
    Универсальный бэктестер для AI-моделей (PyTorch и LightGBM).
    """

    def __init__(self,
                 data: pd.DataFrame,
                 model: Any,
                 model_features: List[str],
                 x_scaler: Any,
                 y_scaler: Any,
                 risk_config: Dict[str, Any],
                 initial_balance: float = 10000.0):
        self.data = data.copy()
        self.model = model
        self.model_features = model_features
        self.x_scaler = x_scaler
        self.y_scaler = y_scaler
        self.risk_config = risk_config
        self.initial_balance = initial_balance
        self.n_steps = risk_config.get('INPUT_LAYER_SIZE', 60)
        self.entry_threshold = risk_config.get('ENTRY_THRESHOLD', 0.001)
        self.stop_loss_atr_multiplier = risk_config.get('STOP_LOSS_ATR_MULTIPLIER', 2.0)
        self.risk_reward_ratio = risk_config.get('RISK_REWARD_RATIO', 2.0)

        # Проверяем, является ли модель PyTorch-моделью
        if isinstance(self.model, nn.Module):
            self.model.eval()  # Вызываем .eval() только для PyTorch

        logger.info(f"AIBacktester инициализирован с моделью {self.model.__class__.__name__}.")

    def run(self) -> dict:
        trades_pnl = []
        open_trade = None

        if 'ATR_14' not in self.data.columns:
            logger.error("[AIBacktester] Отсутствует колонка 'ATR_14' для расчета стоп-лосса.")
            return self._generate_report(pd.Series([]))

        # Убедимся, что все нужные фичи есть в данных
        if not all(feat in self.data.columns for feat in self.model_features):
            missing_feats = [feat for feat in self.model_features if feat not in self.data.columns]
            logger.error(f"[AIBacktester] В данных для бэктеста отсутствуют необходимые признаки: {missing_feats}")
            return self._generate_report(pd.Series([]))

        for i in range(self.n_steps, len(self.data)):
            current_candle = self.data.iloc[i]
            data_slice = self.data.iloc[:i + 1]

            if open_trade:
                exit_price = None
                if open_trade['type'] == 'BUY':
                    if current_candle['low'] <= open_trade['sl']:
                        exit_price = open_trade['sl']
                    elif current_candle['high'] >= open_trade['tp']:
                        exit_price = open_trade['tp']
                elif open_trade['type'] == 'SELL':
                    if current_candle['high'] >= open_trade['sl']:
                        exit_price = open_trade['sl']
                    elif current_candle['low'] <= open_trade['tp']:
                        exit_price = open_trade['tp']

                if exit_price is not None or i == len(self.data) - 1:
                    if exit_price is None: exit_price = current_candle['close']
                    pnl = (exit_price - open_trade['entry_price']) if open_trade['type'] == 'BUY' else (
                                open_trade['entry_price'] - exit_price)
                    trades_pnl.append(pnl)
                    open_trade = None

            if not open_trade:
                signal = self._get_ai_signal(data_slice)
                if signal != 'HOLD':
                    entry_price = current_candle['open']
                    sl_distance = self.data['ATR_14'].iloc[i] * self.stop_loss_atr_multiplier

                    if signal == 'BUY':
                        sl_price = entry_price - sl_distance
                        tp_price = entry_price + sl_distance * self.risk_reward_ratio
                    else:
                        sl_price = entry_price + sl_distance
                        tp_price = entry_price - sl_distance * self.risk_reward_ratio

                    open_trade = {'type': signal, 'entry_price': entry_price, 'sl': sl_price, 'tp': tp_price}

        trade_series = pd.Series(trades_pnl)
        return self._generate_report(trade_series)

    def _get_ai_signal(self, data_slice: pd.DataFrame) -> str:
        try:
            last_sequence_raw = data_slice[self.model_features].tail(self.n_steps).values
            if last_sequence_raw.shape[0] < self.n_steps:
                return 'HOLD'

            last_sequence_scaled = self.x_scaler.transform(last_sequence_raw)
            prediction_scaled = None

            if isinstance(self.model, nn.Module):  # Если это PyTorch
                with torch.no_grad():
                    prediction_input_tensor = torch.from_numpy(last_sequence_scaled).unsqueeze(0).float()
                    prediction_scaled_tensor = self.model(prediction_input_tensor)
                    prediction_scaled = prediction_scaled_tensor.cpu().numpy()
            else:  # Предполагаем, что это LightGBM или другая scikit-learn-совместимая модель
                last_features_scaled = last_sequence_scaled[-1].reshape(1, -1)
                prediction_scaled = self.model.predict(last_features_scaled).reshape(-1, 1)

            if prediction_scaled is None:
                return 'HOLD'

            predicted_price = self.y_scaler.inverse_transform(prediction_scaled)[0][0]
            current_price = data_slice['close'].iloc[-1]
            price_change_ratio = (predicted_price - current_price) / current_price

            if price_change_ratio > self.entry_threshold:
                return 'BUY'
            elif price_change_ratio < -self.entry_threshold:
                return 'SELL'
            return 'HOLD'
        except Exception as e:
            logger.error(f"Ошибка при получении сигнала AI в бэктестере: {e}")
            return 'HOLD'

    def _generate_report(self, trade_series: pd.Series) -> dict:
        if trade_series.empty:
            return {'total_trades': 0, 'profit_factor': 0, 'win_rate': 0, 'max_drawdown': 0, 'sharpe_ratio': 0,
                    'net_pnl': 0}

        total_trades = len(trade_series)
        wins = trade_series[trade_series > 0]
        losses = trade_series[trade_series <= 0]
        gross_profit = wins.sum()
        gross_loss = abs(losses.sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        win_rate = len(wins) / total_trades if total_trades > 0 else 0
        equity_curve = self.initial_balance + trade_series.cumsum()
        peak = equity_curve.expanding(min_periods=1).max()
        drawdown = (equity_curve - peak) / peak
        max_drawdown = abs(drawdown.min())
        sharpe_ratio = (trade_series.mean() / trade_series.std()) if trade_series.std() > 0 else 0

        return {
            'total_trades': total_trades, 'profit_factor': round(profit_factor, 2),
            'win_rate': round(win_rate, 2), 'max_drawdown': round(max_drawdown, 3),
            'sharpe_ratio': round(sharpe_ratio, 2), 'net_pnl': round(trade_series.sum(), 2)
        }