# src/analysis/ai_backtester.py
import logging
from abc import ABC
from typing import Optional

import pandas as pd

from src.core.config_models import Settings
from src.data_models import SignalType, TradeSignal
from src.strategies.StrategyInterface import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyBacktester(ABC):
    """
    Бэктестер для классических, не-AI стратегий.
    """

    def __init__(
        self, strategy: BaseStrategy, data: pd.DataFrame, timeframe: int, config: Settings, initial_balance: float = 10000.0
    ):
        self.strategy = strategy
        self.data = data.copy()
        self.timeframe = timeframe
        self.config = config
        self.initial_balance = initial_balance if initial_balance is not None else self.config.backtester_initial_balance

        self.stop_loss_atr_multiplier = self.config.STOP_LOSS_ATR_MULTIPLIER
        self.risk_reward_ratio = self.config.RISK_REWARD_RATIO

    def run(self) -> dict:
        trades_pnl = []
        open_trade = None

        if "ATR_14" not in self.data.columns:
            logger.error("[StrategyBacktester] Отсутствует колонка 'ATR_14' для расчета стоп-лосса.")
            return self._generate_report(pd.Series([]))

        for i in range(1, len(self.data)):
            current_candle = self.data.iloc[i]

            # Управление открытой позицией
            if open_trade:
                exit_price = None
                if open_trade["type"] == SignalType.BUY:
                    if current_candle["low"] <= open_trade["sl"]:
                        exit_price = open_trade["sl"]
                    elif current_candle["high"] >= open_trade["tp"]:
                        exit_price = open_trade["tp"]
                elif open_trade["type"] == SignalType.SELL:
                    if current_candle["high"] >= open_trade["sl"]:
                        exit_price = open_trade["sl"]
                    elif current_candle["low"] <= open_trade["tp"]:
                        exit_price = open_trade["tp"]

                if exit_price is not None or i == len(self.data) - 1:
                    if exit_price is None:
                        exit_price = current_candle["close"]
                    pnl = (
                        (exit_price - open_trade["entry_price"])
                        if open_trade["type"] == SignalType.BUY
                        else (open_trade["entry_price"] - exit_price)
                    )
                    trades_pnl.append(pnl)
                    open_trade = None

            # Поиск нового сигнала
            if not open_trade:
                symbol = self.data["symbol"].iloc[i] if "symbol" in self.data.columns else None
                signal = self.strategy.check_entry_conditions(self.data, i, self.timeframe, symbol)
                if signal and signal.type != SignalType.HOLD:
                    entry_price = current_candle["open"]
                    sl_distance = self.data["ATR_14"].iloc[i] * self.stop_loss_atr_multiplier

                    if signal.type == SignalType.BUY:
                        sl_price = entry_price - sl_distance
                        tp_price = entry_price + sl_distance * self.risk_reward_ratio
                    else:  # SELL
                        sl_price = entry_price + sl_distance
                        tp_price = entry_price - sl_distance * self.risk_reward_ratio

                    open_trade = {"type": signal.type, "entry_price": entry_price, "sl": sl_price, "tp": tp_price}

        trade_series = pd.Series(trades_pnl)
        return self._generate_report(trade_series)

    def _generate_report(self, trade_series: pd.Series) -> dict:
        if trade_series.empty:
            return {"total_trades": 0, "profit_factor": 0, "win_rate": 0, "max_drawdown": 0, "sharpe_ratio": 0, "net_pnl": 0}

        total_trades = len(trade_series)
        wins = trade_series[trade_series > 0]
        losses = trade_series[trade_series <= 0]
        gross_profit = wins.sum()
        gross_loss = abs(losses.sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        win_rate = len(wins) / total_trades if total_trades > 0 else 0
        equity_curve = self.initial_balance + trade_series.cumsum()
        peak = equity_curve.expanding(min_periods=1).max()
        drawdown = (equity_curve - peak) / peak
        max_drawdown = abs(drawdown.min())
        sharpe_ratio = (trade_series.mean() / trade_series.std()) if trade_series.std() > 0 else 0

        return {
            "total_trades": total_trades,
            "profit_factor": round(profit_factor, 2),
            "win_rate": round(win_rate, 2),
            "max_drawdown": round(max_drawdown, 3),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "net_pnl": round(trade_series.sum(), 2),
        }
