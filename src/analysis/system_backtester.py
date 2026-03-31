# src/analysis/system_backtester.py
import logging
import queue
import threading
from typing import Any, Dict, List, Optional

import pandas as pd

from src.analysis.backtester import StrategyBacktester
from src.analysis.gp_rd_manager import GPRDManager
from src.analysis.market_regime_manager import MarketRegimeManager
from src.core.config_models import Settings

# --- ИМПОРТЫ для продвинутой симуляции ---
from src.core.orchestrator import Orchestrator
from src.data.data_provider import DataProvider
from src.data_models import SignalType, TradeSignal
from src.db.database_manager import DatabaseManager
from src.risk.risk_engine import RiskEngine
from src.strategies.strategy_loader import StrategyLoader
from src.strategies.StrategyInterface import BaseStrategy

logger = logging.getLogger(__name__)


# ---ИМИТАТОР для Оркестратора ---
class FakeTradingSystemForBacktest:
    """
    Имитационный класс TradingSystem, который предоставляет необходимый интерфейс
    для OrchestratorEnv и других компонентов во время бэктеста. Он читает свое
    состояние из экземпляра SystemBacktester.
    """

    def __init__(self, backtester_ref: "SystemBacktester"):
        self.backtester = backtester_ref
        self.config = backtester_ref.config
        # Имитируем необходимые атрибуты
        self.strategies = backtester_ref.strategies
        self.news_cache = None  # Новости в этой версии не симулируются
        self.account_currency = "USD"
        # Имитируем необходимые менеджеры
        self.gp_rd_manager = backtester_ref.gp_rd_manager
        self.data_provider = backtester_ref.data_provider  # Для RiskEngine

    def _get_current_market_regime_name(self) -> str:
        """
        Возвращает режим рынка для текущего шага симуляции.
        Используется средой OrchestratorEnv.
        """
        # Если бэктест еще не запущен (инициализация), берем начало данных
        if self.backtester.current_df_slice is None or self.backtester.current_df_slice.empty:
            # Берем первые 300 баров для "разогрева"
            df = self.backtester.full_data.iloc[:300]
        else:
            df = self.backtester.current_df_slice

        return self.backtester.market_regime_manager.get_regime(df)

    def get_rl_orchestrator_state(self) -> Dict[str, float]:
        """Этот метод получает данные о производительности из состояния бэктестера."""
        trade_series = pd.Series(self.backtester.closed_trades)
        if len(trade_series) < 20:
            return {
                "portfolio_var": 0.0,
                "weekly_pnl": 0.0,
                "sharpe_ratio": 0.0,
                "win_rate": 0.0,
                "news_sentiment": 0.0,
                "market_volatility": 0.5,
            }

        pnl = trade_series.sum()
        sharpe = (trade_series.mean() / trade_series.std()) if trade_series.std() > 0 else 0.0
        win_rate = (trade_series > 0).sum() / len(trade_series) if len(trade_series) > 0 else 0.0

        return {
            "portfolio_var": 0.0,  # Упрощено для бэктеста
            "weekly_pnl": pnl,
            "sharpe_ratio": sharpe,
            "win_rate": win_rate,
            "news_sentiment": 0.0,  # Упрощено
            "market_volatility": trade_series.std() or 0.5,
        }

    def apply_orchestrator_action(self, capital_allocation: Dict[str, float]):
        """Применяет распределение капитала к RiskEngine бэктестера."""
        # В симуляции мы просто логируем это, так как RiskEngine пересоздается или обновляется
        # Но для корректности можно обновлять атрибут в RiskEngine
        if hasattr(self.backtester, "risk_engine"):
            # Поддержка нового формата (матрица режимов) или старого (словарь)
            if isinstance(capital_allocation, dict) and any(isinstance(v, dict) for v in capital_allocation.values()):
                self.backtester.risk_engine.update_regime_capital_allocation(capital_allocation)
            else:
                self.backtester.risk_engine.update_capital_allocation(capital_allocation)

        logger.info(f"[BACKTEST] Оркестратор обновил распределение капитала.")

    def get_account_info(self):
        """Имитирует account_info для Оркестратора."""

        class FakeAccountInfo:
            def __init__(self, balance):
                self.balance = balance

        return FakeAccountInfo(self.backtester.balance)


class SystemBacktester:
    """
    Продвинутый системный бэктестер, симулирующий работу всей экосистемы Genesis,
    включая циклы R&D и обучение Оркестратора на исторических данных.
    """

    def __init__(self, historical_data: pd.DataFrame, config: Settings, initial_balance: float = 10000.0):
        self.full_data = historical_data.copy()
        self.config = config
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance

        # Состояние бэктеста
        self.open_positions: List[Dict[str, Any]] = []
        self.closed_trades: List[float] = []
        self.symbol = self._get_symbol_from_data(historical_data)

        # +++ ДОБАВЛЕНО: Хранит текущий срез данных для FakeTradingSystem +++
        self.current_df_slice: Optional[pd.DataFrame] = None

        # --- Инициализация компонентов ---
        self.data_provider = DataProvider(config, threading.Lock())
        self.db_manager = DatabaseManager(config, queue.Queue())
        self.gp_rd_manager = GPRDManager(config, self.data_provider, self.db_manager)
        self.strategy_loader = StrategyLoader(config)
        self.strategies = {s.__class__.__name__: s for s in self.strategy_loader.load_strategies()}

        # --- Инициализация имитационной среды ---
        self.fake_trading_system = FakeTradingSystemForBacktest(self)

        # +++  MarketRegimeManager должен быть создан ДО Оркестратора +++
        self.market_regime_manager = MarketRegimeManager(config)

        # Теперь создаем Оркестратор (он вызовет env.reset -> fake_sys._get_regime -> market_regime_manager)
        self.orchestrator = Orchestrator(self.fake_trading_system, None, self.db_manager, self.data_provider)

        # Инициализируем RiskEngine с флагом is_simulation=True
        self.risk_engine = RiskEngine(
            config, trading_system_ref=self.fake_trading_system, querier=None, mt5_lock=threading.Lock(), is_simulation=True
        )

        # --- Параметры для симуляции R&D и обучения ---
        self.last_rd_check_bar = 0
        self.rd_check_interval = 2000
        self.last_orchestrator_training_bar = 0
        self.orchestrator_training_interval = 5000

        logger.info(f"Продвинутый SystemBacktester готов к работе. Символ: {self.symbol}")

    def _get_symbol_from_data(self, df: pd.DataFrame) -> str:
        for col in df.columns:
            if isinstance(col, str) and "_" in col:
                parts = col.split("_")
                if len(parts) > 1 and len(parts[-1]) == 6:
                    return parts[-1]
        return "UNKNOWN_SYMBOL"

    def run(self) -> Dict[str, Any]:
        logger.info(f"Запуск ПРОДВИНУТОГО системного бэктеста на {len(self.full_data)} свечах...")

        # Начинаем не с 1, а с достаточного количества баров для индикаторов
        start_bar = max(300, self.config.INPUT_LAYER_SIZE + 1)

        for i in range(start_bar, len(self.full_data)):
            current_candle = self.full_data.iloc[i]

            # +++  текущий срез для FakeTradingSystem +++
            df_slice = self.full_data.iloc[: i + 1]
            self.current_df_slice = df_slice

            self._update_open_positions(current_candle)

            if i - self.last_rd_check_bar > self.rd_check_interval:
                self._simulate_rd_cycle(i)
                self.last_rd_check_bar = i

            if i - self.last_orchestrator_training_bar > self.orchestrator_training_interval:
                self._simulate_orchestrator_training()
                self.last_orchestrator_training_bar = i

            # Если уже есть открытая позиция, пропускаем поиск новой (упрощение)
            if self.open_positions:
                continue

            current_regime = self.market_regime_manager.get_regime(df_slice)
            regime_allocations = self.risk_engine.capital_allocation.get(
                current_regime, self.risk_engine.default_capital_allocation
            )

            final_signal = None
            final_strategy_name = None

            # Передаем правильный индекс (последний элемент слайса)
            current_slice_index = len(df_slice) - 1
            symbol = df_slice["symbol"].iloc[current_slice_index] if "symbol" in df_slice.columns else None

            for name, strategy_instance in self.strategies.items():
                signal = strategy_instance.check_entry_conditions(df_slice, current_slice_index, timeframe=0, symbol=symbol)
                if signal and signal.type != SignalType.HOLD:
                    final_signal = signal
                    final_strategy_name = name
                    # logger.info(f"[BACKTEST] На баре {i} получен сигнал {signal.type.name} от стратегии '{name}'.")
                    break

            if final_signal and not self.open_positions:
                self._open_trade(final_signal, current_candle, df_slice, final_strategy_name)

        if self.open_positions:
            logger.warning(f"Бэктест завершен. Принудительное закрытие {len(self.open_positions)} открытой позиции...")
            last_close_price = self.full_data.iloc[-1]["close"]
            for pos in self.open_positions:
                self._close_trade(pos, last_close_price)

        logger.info("Продвинутый системный бэктест завершен. Генерация отчета...")
        report_generator = StrategyBacktester(
            strategy=None, data=pd.DataFrame(), timeframe=0, config=self.config, initial_balance=self.initial_balance
        )
        report = report_generator._generate_report(pd.Series(self.closed_trades))
        report["final_balance"] = self.balance
        return report

    def _simulate_rd_cycle(self, current_bar_index: int):
        """
        BT.2: Упрощенная симуляция R&D цикла.
        Имитируем, что R&D находит новую стратегию (например, GP_Hybrid_1).
        """
        logger.debug(f"[BACKTEST] Симуляция R&D цикла на баре {current_bar_index}...")

        # Имитируем, что R&D находит новую стратегию (например, GP_Hybrid_1)
        if "GP_Hybrid_1" not in self.strategies:

            class GP_Hybrid_1(BaseStrategy):
                def check_entry_conditions(
                    self, df: pd.DataFrame, current_index: int, timeframe: int, symbol: str = None
                ) -> Optional[TradeSignal]:
                    # Упрощенное правило: RSI < 30 ИЛИ EMA_50 > EMA_200
                    symbol = df["symbol"].iloc[current_index] if "symbol" in df.columns else (symbol if symbol else "UNKNOWN")
                    if "RSI_14" in df.columns and "EMA_50" in df.columns and "EMA_200" in df.columns:
                        if (
                            df["RSI_14"].iloc[current_index] < 30
                            or df["EMA_50"].iloc[current_index] > df["EMA_200"].iloc[current_index]
                        ):
                            return TradeSignal(type=SignalType.BUY, confidence=0.6, symbol=symbol)
                    return None

            self.strategies["GP_Hybrid_1"] = GP_Hybrid_1(self.config)
            self.fake_trading_system.strategies = self.strategies
            logger.warning(f"[BACKTEST] R&D: Добавлена новая стратегия 'GP_Hybrid_1'.")

    def _simulate_orchestrator_training(self):
        """
        BT.1: Выполняет цикл обучения Оркестратора.
        """
        logger.debug(f"[BACKTEST] Симуляция обучения Оркестратора...")

        if self.orchestrator.replay_buffer.size() > self.orchestrator.agent.batch_size:
            # Упрощенное обучение без потоков
            self.orchestrator.agent.learn(total_timesteps=self.orchestrator.agent.n_steps * 10)
            self.orchestrator.replay_buffer.reset()
            logger.warning(f"[BACKTEST] Оркестратор дообучен.")
        else:
            logger.debug("[BACKTEST] Недостаточно данных для обучения Оркестратора.")

    def _update_open_positions(self, candle: pd.Series):
        positions_to_close = []
        for pos in self.open_positions:
            exit_price = None
            if pos["type"] == SignalType.BUY:
                if candle["low"] <= pos["sl"]:
                    exit_price = pos["sl"]
                elif candle["high"] >= pos["tp"]:
                    exit_price = pos["tp"]
            elif pos["type"] == SignalType.SELL:
                if candle["high"] >= pos["sl"]:
                    exit_price = pos["sl"]
                elif candle["low"] <= pos["tp"]:
                    exit_price = pos["tp"]

            if exit_price:
                self._close_trade(pos, exit_price)
                positions_to_close.append(pos)
        self.open_positions = [p for p in self.open_positions if p not in positions_to_close]

    def _open_trade(self, signal: TradeSignal, candle: pd.Series, df_slice: pd.DataFrame, strategy_name: str):
        fake_account_info = type("AccountInfo", (object,), {"balance": self.balance, "equity": self.equity})()

        # 1. Расчет SL в цене (упрощенно)
        if "ATR_14" not in df_slice.columns:
            logger.error("[BACKTEST] ATR_14 отсутствует, пропуск сделки.")
            return

        atr = df_slice["ATR_14"].iloc[-1]
        stop_loss_in_price = atr * self.config.STOP_LOSS_ATR_MULTIPLIER

        if stop_loss_in_price <= 0:
            return

        # 2. Расчет лота (упрощенно: 1% риска на сделку)
        risk_percent = self.config.RISK_PERCENTAGE / 100.0

        # Учет аллокации Оркестратора
        current_regime = self.market_regime_manager.get_regime(df_slice)
        regime_allocations = self.risk_engine.capital_allocation.get(
            current_regime, self.risk_engine.default_capital_allocation
        )
        allocation_for_strategy = regime_allocations.get(strategy_name, 0.0)

        if allocation_for_strategy <= 0.01:
            allocation_for_strategy = 0.1  # Минимальная аллокация для теста

        risk_amount = self.balance * risk_percent * allocation_for_strategy

        # Для простоты, примем, что 1 лот = $100,000, и 1 пункт = $10
        # Лот = Риск / (SL_в_цене * 100000)
        lot_size = risk_amount / (stop_loss_in_price * 100000)
        lot_size = max(0.01, min(10.0, lot_size))  # Ограничиваем лот

        entry_price = candle["open"]
        rr_ratio = self.config.RISK_REWARD_RATIO

        if signal.type == SignalType.BUY:
            sl = entry_price - stop_loss_in_price
            tp = entry_price + stop_loss_in_price * rr_ratio
        else:  # SELL
            sl = entry_price + stop_loss_in_price
            tp = entry_price - stop_loss_in_price * rr_ratio

        position = {"type": signal.type, "entry_price": entry_price, "lot_size": lot_size, "sl": sl, "tp": tp}
        self.open_positions.append(position)

    def _close_trade(self, position: Dict, exit_price: float):
        pnl_points = (
            exit_price - position["entry_price"]
            if position["type"] == SignalType.BUY
            else position["entry_price"] - exit_price
        )
        # Примерная стоимость пункта для стандартного лота (100 000)
        pnl = pnl_points * position["lot_size"] * 100000
        self.balance += pnl
        self.equity = self.balance
        self.closed_trades.append(pnl)
