# src/analysis/event_driven_backtester.py
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List
import asyncio

from src.core.trading_system import TradingSystem
from src.core.config_models import Settings
from src.analysis.simulators import SimulatedBroker
from src.data.data_provider import DataProvider
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MockDataProvider(DataProvider):
    """
    Поддельный провайдер данных, который отдает исторические данные
    до 'текущего' момента симуляции.
    """

    def __init__(self, config, broker, full_history: Dict[str, pd.DataFrame]):
        self.config = config
        self.broker = broker
        self.full_history = full_history
        self.current_time = None
        self.symbols_whitelist = config.SYMBOLS_WHITELIST

    def set_current_time(self, time):
        self.current_time = time

    async def get_all_symbols_data_async(self, symbols, timeframes, num_bars_override=None):
        result = {}
        # Оптимизация: используем searchsorted для быстрого поиска индекса
        for symbol in symbols:
            if symbol in self.full_history:
                df = self.full_history[symbol]

                # Находим позицию текущего времени
                if self.current_time in df.index:
                    idx = df.index.get_loc(self.current_time)
                    # Если get_loc вернул slice или массив (дубликаты), берем последний
                    if isinstance(idx, slice):
                        idx = idx.stop - 1
                    elif isinstance(idx, np.ndarray):
                        idx = np.where(idx)[0][-1]

                    # Берем срез данных (окно назад)
                    window_size = self.config.INPUT_LAYER_SIZE + 200
                    start_idx = max(0, idx - window_size + 1)
                    df_slice = df.iloc[start_idx: idx + 1]

                    if not df_slice.empty:
                        for tf in timeframes:
                            result[f"{symbol}_{tf}"] = df_slice
        return result

    def get_available_symbols(self):
        return list(self.full_history.keys())

    def get_conversion_rate(self, from_currency: str, to_currency: str) -> float:
        # Упрощение для симулятора
        return 1.0


class EventDrivenBacktester:
    def __init__(self, config: Settings, historical_data: Dict[str, pd.DataFrame]):
        self.config = config
        self.historical_data = historical_data
        self.broker = SimulatedBroker(initial_balance=config.backtester_initial_balance)

        # Инициализируем систему
        # Важно: передаем bridge=None, так как GUI обновления нам здесь не нужны напрямую
        self.system = TradingSystem(config, bridge=None)

        # --- ВНЕДРЕНИЕ ЗАВИСИМОСТЕЙ ---
        self.system.terminal_connector = self.broker
        self.system.data_provider = MockDataProvider(config, self.broker, historical_data)

        # Отключаем лишнее
        self.system.auto_updater = None
        self.system.sound_manager = None

        # Перенаправляем компоненты на симулятор
        self.system.risk_engine.mt5_lock = self.system.mt5_lock  # Используем тот же лок (хотя в симуляции он не критичен)
        self.system.risk_engine.trading_system = self.system  # Обновляем ссылку

        # Важно: RiskEngine должен знать, что это симуляция, чтобы не делать лишних проверок
        self.system.risk_engine.is_simulation = True

        self.results = []

    async def run(self):
        logger.info("Запуск Event-Driven бэктеста...")

        # 1. Подготовка временной шкалы
        all_timestamps = sorted(list(set().union(*[df.index for df in self.historical_data.values()])))
        if not all_timestamps:
            return {'error': 'No data'}

        # Пропускаем первые N баров для разогрева индикаторов
        warmup_bars = max(
            self.config.INPUT_LAYER_SIZE + 50,
            self.config.market_regime.volatility_rank_window + 20
        )
        if len(all_timestamps) < warmup_bars:
            return {'error': 'Not enough data for warmup'}

        sim_timestamps = all_timestamps[warmup_bars:]
        logger.info(f"Старт симуляции: {sim_timestamps[0]} -> {sim_timestamps[-1]}")

        # 2. Основной цикл
        for i, current_time in enumerate(sim_timestamps):
            # А. Обновляем рынок в брокере
            for symbol, df in self.historical_data.items():
                if current_time in df.index:
                    row = df.loc[current_time]
                    self.broker.update_market_data(symbol, current_time, row['close'])

            # Б. Обновляем время в провайдере
            self.system.data_provider.set_current_time(current_time)

            # В. Шаг системы
            await self.system.run_single_iteration()

            # Г. Логирование (раз в час или день, чтобы не забивать память)
            if i % 1 == 0:  # Каждый бар
                self.results.append({
                    'time': current_time,
                    'equity': self.broker.equity,
                    'balance': self.broker.balance,
                    'positions': len(self.broker.positions)
                })

            if i % 100 == 0:
                logger.info(f"Simulating: {current_time} | Eq: {self.broker.equity:.0f}")

        # 3. Генерация отчета
        return self._generate_report()

    def _generate_report(self):
        df_res = pd.DataFrame(self.results)
        if df_res.empty:
            return {'total_trades': 0}, pd.DataFrame()

        trades = self.broker.history_deals
        # Фильтруем только выходы для статистики
        exit_trades = [t for t in trades if t['entry'] == 1]

        total_trades = len(exit_trades)
        net_pnl = sum(t['profit'] for t in exit_trades)
        wins = len([t for t in exit_trades if t['profit'] > 0])

        win_rate = wins / total_trades if total_trades > 0 else 0
        profit_factor = abs(sum(t['profit'] for t in exit_trades if t['profit'] > 0) /
                            (sum(t['profit'] for t in exit_trades if t['profit'] < 0) or 1))

        # Максимальная просадка по Эквити
        equity_curve = df_res['equity']
        peak = equity_curve.expanding(min_periods=1).max()
        drawdown = (equity_curve - peak) / peak
        max_drawdown = abs(drawdown.min()) * 100

        report = {
            'total_trades': total_trades,
            'net_pnl': round(net_pnl, 2),
            'win_rate': round(win_rate, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown_percent': round(max_drawdown, 2),
            'final_balance': round(self.broker.balance, 2)
        }

        return report, df_res