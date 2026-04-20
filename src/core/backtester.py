"""
Backtester Module
Побаровая симуляция торговых стратегий на исторических данных MT5.
Публикует прогресс и финальные метрики через EventBus.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from src.core.event_bus import EventPriority, SystemEvent

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Результат бэктеста"""

    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_profit: float
    total_loss: float
    net_profit: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    avg_trade_duration: float
    trades: list


class Backtester:
    """
    Асинхронный бэктестер для тестирования стратегий без блокировки GUI.

    Особенности:
    - Асинхронный цикл с yield прогресса
    - Публикация событий через EventBus
    - Симуляция спредов, комиссий и SL/TP
    - Расчёт метрик: Sharpe, Drawdown, Win Rate, Profit Factor
    """

    def __init__(self, config, event_bus=None):
        """
        Args:
            config: Конфигурация системы
            event_bus: Шина событий для публикации прогресса и результатов
        """
        self.config = config
        self.event_bus = event_bus
        self.is_running = False
        self.progress = 0

    async def run(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: int,
        strategy_class,
        initial_balance: float = 10000.0,
        spread_points: float = 1.0,
        commission_per_lot: float = 7.0,
        lot_size: float = 0.1,
    ):
        """
        Запускает асинхронный бэктест.

        Args:
            symbol: Торговый символ (EURUSD, GBPJPY и т.д.)
            start_date: Дата начала (YYYY-MM-DD)
            end_date: Дата окончания (YYYY-MM-DD)
            timeframe: Таймфрейм MT5 (mt5.TIMEFRAME_H1, mt5.TIMEFRAME_D1 и т.д.)
            strategy_class: Класс стратегии (должен иметь метод on_bar)
            initial_balance: Стартовый баланс ($)
            spread_points: Спред в пунктах
            commission_per_lot: Комиссия за лот ($)
            lot_size: Размер лота для тестирования

        Returns:
            dict: Метрики производительности (публикуется через EventBus)
        """
        if self.is_running:
            logger.warning("⚠️ Бэктестер уже запущен")
            return

        self.is_running = True
        self.progress = 0

        logger.info(f"📊 Запуск бэктеста: {symbol} | {start_date} -> {end_date} | TF: {timeframe}")

        try:
            # 1. Загрузка исторических данных
            data = await self._load_data(symbol, start_date, end_date, timeframe)
            if data.empty:
                logger.error("❌ Нет исторических данных для бэктеста")
                return

            # 2. Инициализация контекста стратегии
            strategy = strategy_class()
            strategy.init_balance = initial_balance
            strategy.current_balance = initial_balance
            strategy.equity_curve = [initial_balance]
            strategy.trades = []
            strategy.open_position = None

            # 3. Побаровая симуляция
            await self._simulate_trades(data, strategy, spread_points, commission_per_lot, lot_size)

            # 4. Расчёт метрик
            metrics = self._calculate_metrics(strategy.trades, strategy.equity_curve)
            metrics.update(
                {
                    "symbol": symbol,
                    "period": f"{start_date} - {end_date}",
                    "strategy": strategy.__class__.__name__,
                    "timeframe": timeframe,
                }
            )

            # 5. Публикация результатов
            await self._publish_results(metrics)

            logger.info(f"✅ Бэктест завершен. Return: {metrics['total_return']}% | DD: {metrics['max_drawdown']}%")

            return metrics

        except Exception as e:
            logger.error(f"❌ Ошибка бэктеста: {e}", exc_info=True)
            return None

        finally:
            self.is_running = False
            self.progress = 100

    async def _load_data(self, symbol: str, start: str, end: str, timeframe: int) -> pd.DataFrame:
        """Загрузка баров из MT5"""
        logger.info(f"📥 Загрузка истории {symbol}...")

        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        if not mt5.initialize():
            raise RuntimeError("MT5 не инициализирован")

        rates = mt5.copy_rates_range(symbol, timeframe, start_dt, end_dt)

        if rates is None or len(rates) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)

        logger.info(f"✅ Загружено {len(df)} баров")
        return df

    async def _simulate_trades(self, df: pd.DataFrame, strategy, spread: float, commission: float, lot: float):
        """Основной цикл симуляции"""
        total_bars = len(df)
        point_value = 10.0  # Упрощённо для Forex (1 пункт = 10$ на стандартном лоте)

        for i in range(1, total_bars):
            if not self.is_running:
                break

            # Yield прогресса каждые 5%
            if i % max(1, total_bars // 20) == 0:
                self.progress = int((i / total_bars) * 100)
                await self._publish_progress(self.progress)
                await asyncio.sleep(0)  # Не блокируем GUI

            bar = df.iloc[i]

            # --- Логика закрытия по SL/TP ---
            if strategy.open_position:
                pos = strategy.open_position
                pnl = 0.0
                closed = False

                if pos["type"] == "BUY":
                    if bar["low"] <= pos["sl"]:
                        pnl = (pos["sl"] - pos["entry"]) * lot * point_value - (spread * lot * 10)
                        closed = True
                    elif bar["high"] >= pos["tp"]:
                        pnl = (pos["tp"] - pos["entry"]) * lot * point_value - (spread * lot * 10)
                        closed = True
                else:  # SELL
                    if bar["high"] >= pos["sl"]:
                        pnl = (pos["entry"] - pos["sl"]) * lot * point_value - (spread * lot * 10)
                        closed = True
                    elif bar["low"] <= pos["tp"]:
                        pnl = (pos["entry"] - pos["tp"]) * lot * point_value - (spread * lot * 10)
                        closed = True

                if closed:
                    strategy.current_balance += pnl
                    strategy.trades.append({"close_time": bar.name, "pnl": pnl, "type": pos["type"]})
                    strategy.open_position = None

            # --- Логика входа по стратегии ---
            if not strategy.open_position:
                # Ожидаемый интерфейс: strategy.on_bar(df_slice, current_time) -> {'action': 'BUY'/'SELL', 'sl': float, 'tp': float}
                signal = strategy.on_bar(df.iloc[: i + 1], bar.name)

                if signal and signal.get("action") in ["BUY", "SELL"]:
                    entry_price = bar["close"]
                    sl = signal.get("sl", entry_price * 0.99)
                    tp = signal.get("tp", entry_price * 1.02)

                    strategy.open_position = {
                        "type": signal["action"],
                        "entry": entry_price,
                        "sl": sl,
                        "tp": tp,
                        "time": bar.name,
                    }

                    strategy.current_balance -= commission * lot
                    strategy.equity_curve.append(strategy.current_balance)

        # Закрытие хвостовых позиций по окончании теста
        if strategy.open_position:
            last_bar = df.iloc[-1]
            pos = strategy.open_position
            pnl = (
                (last_bar["close"] - pos["entry"]) * lot * point_value
                if pos["type"] == "BUY"
                else (pos["entry"] - last_bar["close"]) * lot * point_value
            )
            pnl -= spread * lot * 10

            strategy.current_balance += pnl
            strategy.trades.append({"close_time": last_bar.name, "pnl": pnl, "type": pos["type"]})

    def _calculate_metrics(self, trades: list, equity: list) -> dict:
        """Расчёт итоговых метрик"""
        if not trades:
            return {
                "total_return": 0,
                "max_drawdown": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "sharpe_ratio": 0,
                "total_trades": 0,
            }

        equity_series = pd.Series(equity)
        returns = equity_series.pct_change().dropna()

        total_trades = len(trades)
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(wins) / total_trades if total_trades > 0 else 0

        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        total_return = (equity[-1] / equity[0] - 1) * 100

        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max * 100
        max_drawdown = drawdown.min()

        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

        return {
            "total_return": round(total_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "win_rate": round(win_rate * 100, 1),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_trades": total_trades,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "final_balance": round(equity[-1], 2),
        }

    async def _publish_progress(self, progress: int):
        """Публикация прогресса через EventBus"""
        if self.event_bus:
            await self.event_bus.publish(
                SystemEvent(type="backtest_progress", payload={"progress": progress}, priority=EventPriority.LOW)
            )

    async def _publish_results(self, metrics: dict):
        """Публикация результатов через EventBus"""
        if self.event_bus:
            await self.event_bus.publish(
                SystemEvent(type="backtest_completed", payload={"metrics": metrics}, priority=EventPriority.HIGH)
            )

    def run_backtest(
        self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime, strategy_callback, risk_manager=None
    ) -> BacktestResult:
        """
        Запускает бэктест стратегии на исторических данных.

        Args:
            symbol: Торговый символ (EURUSD, GBPJPY и т.д.)
            timeframe: Таймфрейм (M1, M5, H1, D1 и т.д.)
            start_date: Дата начала
            end_date: Дата окончания
            strategy_callback: Функция стратегии
                def strategy_callback(df: pd.DataFrame, current_bar: pd.Series) -> dict:
                    return {"signal": "BUY"/"SELL"/"HOLD", "score": 0.8, "sl": 1.0850, "tp": 1.1000}
            risk_manager: RiskManager (опционально, для расчёта лота)

        Returns:
            BacktestResult: Полная статистика бэктеста
        """
        logger.info(f"{'='*80}")
        logger.info(f"🧪 ЗАПУСК БЭКТЕСТА: {symbol} {timeframe}")
        logger.info(f"   Период: {start_date} → {end_date}")
        logger.info(f"   Баланс: ${self.initial_balance:.0f}")
        logger.info(f"{'='*80}")

        try:
            # 1. Получение исторических данных
            if not mt5.initialize():
                logger.error("MT5 не инициализирован")
                return self._create_empty_result(symbol, timeframe, start_date, end_date)

            timeframe_map = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
                "W1": mt5.TIMEFRAME_W1,
                "MN1": mt5.TIMEFRAME_MN1,
            }

            tf = timeframe_map.get(timeframe, mt5.TIMEFRAME_H1)

            rates = mt5.copy_rates_range(symbol, tf, start_date, end_date)

            if rates is None or len(rates) == 0:
                logger.error(f"Не удалось получить данные для {symbol} {timeframe}")
                return self._create_empty_result(symbol, timeframe, start_date, end_date)

            logger.info(f"✅ Получено {len(rates)} баров")

            # 2. Преобразование в DataFrame
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")

            # 3. Инициализация баланса
            balance = self.initial_balance
            equity = self.initial_balance
            self.balance_history = [balance]
            self.equity_history = [equity]
            self.trades = []
            self.current_positions = {}

            # 4. Проход по барам (симуляция торговли)
            for i in range(100, len(df)):  # Пропускаем первые 100 баров для индикаторов
                current_bar = df.iloc[i]
                prev_bars = df.iloc[:i]

                # Обновляем equity (по текущим позициям)
                equity = self._update_equity(balance, current_bar["close"])

                # Проверка открытия новых позиций
                signal = strategy_callback(prev_bars, current_bar)

                if signal and signal.get("signal") in ["BUY", "SELL"]:
                    self._process_signal(signal=signal, bar=current_bar, balance=balance, risk_manager=risk_manager)

                # Проверка закрытия позиций (TP/SL/сигнал на выход)
                self._check_position_exits(bar=current_bar, balance=balance)

                # Обновляем баланс после закрытия позиций
                balance = self._update_balance(balance)

                # Сохраняем историю
                self.balance_history.append(balance)
                self.equity_history.append(equity)

                # Прогресс
                if i % 100 == 0:
                    logger.debug(f"Бар {i}/{len(df)} | Bal: ${balance:.0f} | Eq: ${equity:.0f}")

            # 5. Закрытие всех оставшихся позиций в конце
            self._close_all_positions(df.iloc[-1]["close"], balance)

            # 6. Расчёт итоговых метрик
            result = self._calculate_metrics(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_balance=self.initial_balance,
                final_balance=balance,
            )

            logger.info(f"{'='*80}")
            logger.info(f"✅ БЭКТЕСТ ЗАВЕРШЁН")
            logger.info(f"   Net Profit: ${result.net_profit:.2f} ({(result.final_balance/self.initial_balance-1)*100:.1f}%)")
            logger.info(f"   Win Rate: {result.win_rate:.1f}%")
            logger.info(f"   Sharpe: {result.sharpe_ratio:.2f}")
            logger.info(f"   Max DD: {result.max_drawdown_pct:.1f}%")
            logger.info(f"{'='*80}")

            return result

        except Exception as e:
            logger.error(f"Ошибка в бэктесте: {e}", exc_info=True)
            return self._create_empty_result(symbol, timeframe, start_date, end_date)

    def _update_equity(self, balance: float, current_price: float) -> float:
        """Обновляет equity с учётом открытых позиций"""
        unrealized_pnl = 0.0

        for ticket, pos in self.current_positions.items():
            if pos["type"] == "BUY":
                pnl = (current_price - pos["entry_price"]) * pos["volume"] * 100000  # Форекс
            else:  # SELL
                pnl = (pos["entry_price"] - current_price) * pos["volume"] * 100000

            unrealized_pnl += pnl

        return balance + unrealized_pnl

    def _update_balance(self, balance: float) -> float:
        """Закрытые позиции обновляют баланс"""
        # В реальном коде здесь будет логика фиксации PnL
        # Пока оставляем упрощённую версию
        return balance

    def _process_signal(self, signal: Dict[str, Any], bar: pd.Series, balance: float, risk_manager=None):
        """Обработка сигнала на открытие позиции"""
        signal_type = signal.get("signal")
        sl = signal.get("sl", 0)
        tp = signal.get("tp", 0)

        # Проверка лимита позиций
        if len(self.current_positions) >= self.max_open_trades:
            logger.debug(f"Лимит позиций исчерпан ({len(self.current_positions)})")
            return

        # Расчёт лота
        if risk_manager:
            lot = risk_manager.calculate_lot(
                symbol=bar.name if hasattr(bar, "name") else "UNKNOWN", stop_loss_price=sl, entry_price=bar["close"]
            )
        else:
            # Fallback: фиксированный лот 0.01
            lot = 0.01

        # Создание позиции
        ticket = f"BT_{len(self.trades)}_{datetime.now().timestamp()}"
        position = {
            "ticket": ticket,
            "type": signal_type,
            "entry_price": bar["close"],
            "volume": lot,
            "sl": sl,
            "tp": tp,
            "open_time": bar["time"],
            "bars_opened": 0,
        }

        self.current_positions[ticket] = position
        logger.info(f"📈 Открыта позиция {signal_type} {lot:.2f} лот @ {bar['close']:.5f}")

    def _check_position_exits(self, bar: pd.Series, balance: float):
        """Проверка условий закрытия позиций (TP/SL)"""
        price = bar["close"]
        to_close = []

        for ticket, pos in self.current_positions.items():
            # Проверка Stop Loss
            if pos["sl"] > 0:
                if pos["type"] == "BUY" and price <= pos["sl"]:
                    to_close.append((ticket, "SL"))
                    continue
                elif pos["type"] == "SELL" and price >= pos["sl"]:
                    to_close.append((ticket, "SL"))
                    continue

            # Проверка Take Profit
            if pos["tp"] > 0:
                if pos["type"] == "BUY" and price >= pos["tp"]:
                    to_close.append((ticket, "TP"))
                    continue
                elif pos["type"] == "SELL" and price <= pos["tp"]:
                    to_close.append((ticket, "TP"))
                    continue

        # Закрытие позиций
        for ticket, exit_reason in to_close:
            self._close_position(ticket, price, bar["time"], exit_reason)

    def _close_position(self, ticket: str, exit_price: float, exit_time: datetime, reason: str):
        """Закрытие позиции и запись результата"""
        if ticket not in self.current_positions:
            return

        pos = self.current_positions[ticket]
        entry = pos["entry_price"]
        volume = pos["volume"]

        # Расчёт PnL
        if pos["type"] == "BUY":
            pnl = (exit_price - entry) * volume * 100000
        else:  # SELL
            pnl = (entry - exit_price) * volume * 100000

        # Комиссия
        commission = (entry * volume * 100000) * (self.commission_per_trade / 100)
        pnl -= commission

        # Расчёт спреда (вход по Ask/Bid)
        spread_cost = self.spread_points * 0.0001 * volume * 100000
        pnl -= spread_cost

        # Запись сделки
        trade_record = {
            "ticket": ticket,
            "type": pos["type"],
            "symbol": pos.get("symbol", "UNKNOWN"),
            "volume": volume,
            "entry_price": entry,
            "exit_price": exit_price,
            "sl": pos["sl"],
            "tp": pos["tp"],
            "pnl": pnl,
            "exit_reason": reason,
            "open_time": pos["open_time"],
            "close_time": exit_time,
            "bars_in_trade": (exit_time - pos["open_time"]).total_seconds() / 60,  # в минутах
        }

        self.trades.append(trade_record)

        # Удаление из открытых позиций
        del self.current_positions[ticket]

        logger.info(f"{'✅' if pnl > 0 else '❌'} Позиция закрыта: {pos['type']} " f"PnL=${pnl:.2f} ({reason})")

    def _close_all_positions(self, close_price: float, balance: float):
        """Закрытие всех оставшихся позиций в конце бэктеста"""
        for ticket in list(self.current_positions.keys()):
            self._close_position(ticket, close_price, datetime.now(), "END_OF_TEST")

    def _calculate_metrics(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        final_balance: float,
    ) -> BacktestResult:
        """Расчёт итоговых метрик бэктеста"""
        # Подсчёт сделок
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t["pnl"] > 0)
        losing_trades = sum(1 for t in self.trades if t["pnl"] <= 0)

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # PnL
        total_profit = sum(t["pnl"] for t in self.trades if t["pnl"] > 0)
        total_loss = sum(abs(t["pnl"]) for t in self.trades if t["pnl"] <= 0)
        net_profit = final_balance - initial_balance

        # Profit Factor
        profit_factor = (total_profit / total_loss) if total_loss > 0 else float("inf")

        # Максимальная просадка
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        peak = initial_balance

        for balance in self.balance_history:
            if balance > peak:
                peak = balance
            drawdown = peak - balance
            drawdown_pct = (drawdown / peak) * 100

            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct

        # Sharpe Ratio (annualized)
        if len(self.balance_history) > 1:
            returns = np.diff(self.balance_history) / self.balance_history[:-1]
            sharpe_ratio = np.sqrt(252 * 24) * np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Средняя длительность сделки
        if total_trades > 0:
            avg_duration = np.mean([t["bars_in_trade"] for t in self.trades])
        else:
            avg_duration = 0.0

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            initial_balance=initial_balance,
            final_balance=final_balance,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_profit=total_profit,
            total_loss=total_loss,
            net_profit=net_profit,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            avg_trade_duration=avg_duration,
            trades=self.trades,
        )

    def _create_empty_result(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime) -> BacktestResult:
        """Создание пустого результата при ошибке"""
        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            initial_balance=self.initial_balance,
            final_balance=self.initial_balance,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_profit=0.0,
            total_loss=0.0,
            net_profit=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            avg_trade_duration=0.0,
            trades=[],
        )

    def export_results(self, result: BacktestResult, filepath: str):
        """
        Экспорт результатов бэктеста в CSV/JSON.

        Args:
            result: BacktestResult
            filepath: Путь для сохранения (CSV или JSON)
        """
        import json

        if filepath.endswith(".json"):
            # JSON экспорт
            data = {
                "summary": {
                    "symbol": result.symbol,
                    "timeframe": result.timeframe,
                    "period": f"{result.start_date} to {result.end_date}",
                    "initial_balance": result.initial_balance,
                    "final_balance": result.final_balance,
                    "net_profit": result.net_profit,
                    "win_rate": result.win_rate,
                    "sharpe_ratio": result.sharpe_ratio,
                    "max_drawdown_pct": result.max_drawdown_pct,
                    "total_trades": result.total_trades,
                },
                "trades": result.trades,
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

            logger.info(f"✅ Результаты экспортированы в {filepath}")

        elif filepath.endswith(".csv"):
            # CSV экспорт сделок
            if result.trades:
                df = pd.DataFrame(result.trades)
                df.to_csv(filepath, index=False)
                logger.info(f"✅ Сделки экспортированы в {filepath}")
            else:
                logger.warning("Нет сделок для экспорта")

    def plot_equity_curve(self, result: BacktestResult, save_path: str = None):
        """
        Построение графика кривой прибыли (опционально).

        Args:
            result: BacktestResult
            save_path: Путь для сохранения графика (если None — не сохранять)
        """
        try:
            import matplotlib.pyplot as plt

            plt.figure(figsize=(12, 6))
            plt.plot(self.balance_history, label="Balance", color="#50fa7b", linewidth=2)
            plt.plot(self.equity_history, label="Equity", color="#8be9fd", linewidth=1, alpha=0.7)

            plt.title(
                f"Backtest: {result.symbol} {result.timeframe}\n"
                f"Net Profit: ${result.net_profit:.2f} | "
                f"Win Rate: {result.win_rate:.1f}% | "
                f"Sharpe: {result.sharpe_ratio:.2f}",
                fontsize=14,
            )

            plt.xlabel("Trade Number")
            plt.ylabel("Balance ($)")
            plt.legend()
            plt.grid(True, alpha=0.3)

            if save_path:
                plt.savefig(save_path, dpi=150, bbox_inches="tight")
                logger.info(f"✅ График сохранён: {save_path}")
            else:
                plt.show()

            plt.close()

        except ImportError:
            logger.warning("matplotlib не установлен, график не построен")
        except Exception as e:
            logger.error(f"Ошибка построения графика: {e}", exc_info=True)
