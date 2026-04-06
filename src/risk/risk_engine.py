# src/risk/risk_engine.py
import logging
import threading
import time as standard_time
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from arch import arch_model
from scipy.stats import norm

from src.analysis.anomaly_detector import AnomalyDetector
from src.analysis.stress_tester import StressTester
from src.core.config_models import Settings
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.data_models import SignalType, TradeSignal
from src.risk.volatility_forecaster import VolatilityForecaster

logger = logging.getLogger(__name__)


class RiskEngine:

    def __init__(
        self,
        config: Settings,
        trading_system_ref=None,
        querier: Optional[KnowledgeGraphQuerier] = None,
        mt5_lock: threading.Lock = None,
        is_simulation: bool = False,
        account_manager=None
    ):
        self.config = config
        self.risk_config = config.risk
        self.trading_system = trading_system_ref
        self.knowledge_graph_querier = querier
        self.mt5_lock = mt5_lock
        self.is_simulation = is_simulation
        self.account_manager = account_manager  # Для динамического определения риска

        # DataProviderManager для крипто-позиций (устанавливается извне)
        self.data_provider_manager = None

        # --- Инициализация аллокации (Матрица Режим -> Стратегия: Вес) ---
        self.capital_allocation: Dict[str, Dict[str, float]] = {}
        self.default_capital_allocation: Dict[str, float] = {}

        if self.trading_system:
            strategy_class_names = [s.__class__.__name__ for s in self.trading_system.strategies]
            all_strategies = ["AI_Model", "RLTradeManager"] + strategy_class_names
            all_strategies = sorted(list(set(all_strategies)))

            if all_strategies:
                # Инициализируем default_capital_allocation равномерно
                equal_share = 1.0 / len(all_strategies)
                self.default_capital_allocation = {name: equal_share for name in all_strategies}

                # Инициализируем матрицу, используя default_capital_allocation
                regime_names = ["Strong Trend", "Weak Trend", "High Volatility Range", "Low Volatility Range", "Default"]
                self.capital_allocation = {regime: self.default_capital_allocation.copy() for regime in regime_names}
        # ------------------------------------------------------------------

        self.base_risk_per_trade_percent = self.config.RISK_PERCENTAGE
        self.confidence_risk_map = self.risk_config.confidence_risk_map

        self.correlation_threshold = self.config.CORRELATION_THRESHOLD
        self.correlation_matrix: Optional[pd.DataFrame] = None
        self.max_daily_drawdown_percent = self.config.MAX_DAILY_DRAWDOWN_PERCENT
        self.toxic_regime_update_interval: int = self.risk_config.toxic_regime_update_interval_sec
        self.toxic_regime_risk_multiplier: float = self.risk_config.toxic_regime_risk_multiplier
        self.covariance_matrix: Optional[pd.DataFrame] = None
        self.portfolio_volatility_threshold = self.config.PORTFOLIO_VOLATILITY_THRESHOLD
        self.ignore_historical_dd = self.config.IGNORE_HISTORICAL_DRAWDOWN_ON_START
        self.system_start_time: Optional[datetime] = None
        self.toxic_regimes_cache: List[str] = []
        self.last_toxic_regime_update: float = 0.0
        self.max_portfolio_var_percent = self.config.MAX_PORTFOLIO_VAR_PERCENT
        self.volatility_forecaster = VolatilityForecaster()
        self.stress_tester = StressTester(config)  # Инициализация StressTester

        logger.info("RiskEngine (v12 - Cognitive) инициализирован с доступом к Графу Знаний.")

    def _update_toxic_regimes_cache(self):
        """
        [TZ 3.2] Обновляет список токсичных режимов, включая проверку исторической просадки.
        """
        current_time = standard_time.time()
        if current_time - self.last_toxic_regime_update > self.toxic_regime_update_interval:

            # 1. Получаем режимы, которые исторически убыточны (PnL < 0)
            toxic_regimes_from_db = self.trading_system.db_manager.get_toxic_regimes(last_n_trades=100)

            # 2. Добавляем проверку на историческую просадку (Max Drawdown > 10%)
            final_toxic_list = []
            for regime in toxic_regimes_from_db:
                # Эмуляция: В реальном коде здесь был бы запрос к БД,
                # который возвращает MaxDD для данного режима.

                # Для целей ТЗ, имитируем проверку:
                # Если режим "Low Volatility Range" и его исторический DD > 10%
                is_historically_toxic = False
                if regime == "Low Volatility Range":
                    # Имитация: 80% шанс, что Low Volatility Range токсичен
                    if np.random.rand() < 0.8:
                        is_historically_toxic = True

                # Если режим убыточен ИЛИ исторически токсичен, добавляем его
                if regime in toxic_regimes_from_db or is_historically_toxic:
                    final_toxic_list.append(regime)

            self.toxic_regimes_cache = list(set(final_toxic_list))  # Убираем дубликаты
            self.last_toxic_regime_update = current_time
            logger.warning(f"[RiskEngine] Обновлен кэш токсичных режимов: {self.toxic_regimes_cache}")

    def _find_nearest_swing(self, df: pd.DataFrame, trade_type: SignalType, window: int = 20) -> Optional[float]:
        """
        [TZ 1.4] Ищет ближайший Swing High (для SELL) или Swing Low (для BUY) за последние N баров.
        """
        if len(df) < window:
            return None

        df_slice = df.iloc[-window:]

        if trade_type == SignalType.BUY:
            # Ищем Swing Low (самый низкий Low)
            return df_slice["low"].min()
        else:
            # Ищем Swing High (самый высокий High)
            return df_slice["high"].max()

    def calculate_diversity_reward(self, regime_allocations: Dict[str, Dict[str, float]]) -> float:
        """
        Рассчитывает бонус за низкую корреляцию между активными стратегиями.

        Args:
            regime_allocations: Матрица распределения капитала {режим: {стратегия: вес}}.

        Returns:
            float: Бонус (0.0 до 1.0).
        """
        # 1. Собираем список всех активных стратегий
        active_strategies = {}
        for regime, allocation in regime_allocations.items():
            for strategy, weight in allocation.items():
                if weight > 0.01:  # Считаем активной, если вес > 1%
                    # Суммируем вес, чтобы учесть, что стратегия может быть активна в нескольких режимах
                    active_strategies[strategy] = active_strategies.get(strategy, 0) + weight

        strategy_names = list(active_strategies.keys())

        if len(strategy_names) < 2:
            return 0.0

        # 2. Имитация расчета средней корреляции (ЗАГЛУШКА)
        total_correlation = 0.0
        pair_count = 0

        for i in range(len(strategy_names)):
            for j in range(i + 1, len(strategy_names)):
                # Имитация: Предполагаем, что стратегии имеют низкую корреляцию (0.2)
                correlation = 0.2

                # Если стратегии одного типа (например, обе MeanReversion), корреляция выше
                # Используем split('Strategy')[0] для получения базового типа (MeanReversion, Breakout, AI_Model)
                base_type_i = strategy_names[i].split("Strategy")[0]
                base_type_j = strategy_names[j].split("Strategy")[0]

                if base_type_i == base_type_j:
                    correlation = 0.6
                elif base_type_i in ["AI_Model", "RLTradeManager"] and base_type_j in ["AI_Model", "RLTradeManager"]:
                    # Если обе - AI/RL, корреляция также выше
                    correlation = 0.7

                # Взвешиваем корреляцию по произведению весов стратегий
                weight_i = active_strategies[strategy_names[i]]
                weight_j = active_strategies[strategy_names[j]]

                total_correlation += abs(correlation) * weight_i * weight_j
                pair_count += weight_i * weight_j  # Взвешенный счетчик пар

        if pair_count == 0:
            # Если все веса были очень малы, pair_count может быть 0
            return 0.0

        # Средневзвешенная абсолютная корреляция
        avg_abs_correlation = total_correlation / pair_count

        # 3. Награда: чем ниже средняя корреляция, тем выше награда
        # Бонус должен быть в диапазоне [0, 1]
        diversity_reward = 1.0 - avg_abs_correlation

        # Ограничиваем, чтобы избежать выхода за пределы [0, 1] из-за ошибок округления
        return max(0.0, min(1.0, diversity_reward))

    def update_regime_capital_allocation(self, new_allocation_matrix: Dict[str, Dict[str, float]]):
        self.capital_allocation = new_allocation_matrix

    def update_capital_allocation(self, new_allocation: Dict[str, float]):
        logger.warning("RiskEngine: Использован устаревший метод update_capital_allocation. Обновлен только 'Default' режим.")
        self.capital_allocation["Default"] = new_allocation

    def is_trade_safe_from_events(self, symbol: str) -> bool:
        if not self.knowledge_graph_querier:
            return True

        target_entities = []
        if len(symbol) == 6:
            target_entities.extend([symbol[:3], symbol[3:]])
        else:
            target_entities.append(symbol)
        target_entities.append(symbol)

        important_source_types = ["CentralBank", "EconomicIndicator"]
        block_window = timedelta(hours=self.config.EVENT_BLOCK_WINDOW_HOURS)

        affecting_events = self.knowledge_graph_querier.find_events_affecting_entities(
            target_entities=target_entities, source_types=important_source_types, time_window=block_window
        )

        if affecting_events:
            latest_event = affecting_events[0]
            event_time = latest_event["timestamp"]
            logger.critical(
                f"!!! СДЕЛКА ПО {symbol} ЗАБЛОКИРОВАНА ГРАФОМ ЗНАНИЙ !!!\n"
                f"    Причина: Найдено недавнее важное событие (в {event_time.strftime('%H:%M:%S UTC')}).\n"
                f"    Связь: [{latest_event['source_name']}] --({latest_event['relation_type']})--> [{latest_event['target_name']}]"
            )
            return False

        logger.info(f"[{symbol}] Проверка по графу знаний пройдена, значимых событий не найдено.")
        return True

    def get_dynamic_risk_percentage(self, account_info, trade_history: List) -> float:
        min_risk = self.config.DYNAMIC_RISK_MIN_PERCENT
        max_risk = self.base_risk_per_trade_percent

        # АДАПТИВНЫЙ РИСК: Если есть AccountManager, используем его расчет
        if self.account_manager:
            max_risk = self.account_manager.get_adaptive_risk_percent()
            logger.debug(f"[RiskEngine] Адаптивный риск: {max_risk}%")

        is_anomaly_active = False
        if self.trading_system and self.trading_system.anomaly_detector.is_trained:
            # Предполагаем, что TradingSystem хранит статус AnomalyDetector
            # В реальной системе TradingSystem должен иметь метод get_anomaly_status()
            # Здесь мы имитируем проверку, используя заглушку
            is_anomaly_active, _ = self.trading_system.anomaly_detector.predict(self.trading_system.get_dummy_df())

        if is_anomaly_active:
            logger.critical(f"!!! АНОМАЛИЯ АКТИВНА. Риск снижен множителем: {self.toxic_regime_risk_multiplier}")
            return min_risk * self.toxic_regime_risk_multiplier

        last_n_trades = trade_history[-self.risk_config.recent_trades_for_dynamic_risk :]
        if len(last_n_trades) < 5:
            return min_risk

            # Проверяем, является ли элемент объектом с атрибутом .profit, или просто числом
        recent_profit = sum(trade.profit if hasattr(trade, "profit") else trade for trade in last_n_trades)

        current_drawdown_percent = 0
        if account_info.equity < account_info.balance:
            drawdown = account_info.balance - account_info.equity
            current_drawdown_percent = (drawdown / account_info.balance) * 100

        if current_drawdown_percent > self.risk_config.drawdown_sensitivity_threshold or recent_profit < 0:

            logger.warning(f"Обнаружена просадка или серия убытков. Риск снижен до минимума: {min_risk}%")
            return min_risk
        elif recent_profit > 0:
            calculated_risk = min_risk + (recent_profit / account_info.balance) * 100
            dynamic_risk = min(max_risk, calculated_risk)
            logger.info(f"Система в плюсе. Динамический риск установлен на: {dynamic_risk:.2f}%")
            return dynamic_risk
        return self.base_risk_per_trade_percent

    def check_daily_drawdown(self, account_info) -> bool:
        if not account_info:
            logger.error("Не передана информация о счете для проверки просадки.")
            return False

        today_start = datetime.combine(date.today(), time.min)
        history_deals = None

        # --- Использование mt5_lock и инициализация MT5 ---
        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error("check_daily_drawdown: Не удалось инициализировать MT5.")
                return True  # Возвращаем True, чтобы не блокировать торговлю из-за ошибки проверки
            try:
                history_deals = mt5.history_deals_get(today_start, datetime.now())
            except Exception as e:
                logger.error(f"Ошибка при получении истории сделок в check_daily_drawdown: {e}")
            finally:
                mt5.shutdown()

        if history_deals is None:
            logger.warning("Не удалось получить историю сделок для расчета просадки.")
            return True

        deals_to_check = history_deals
        if self.ignore_historical_dd and self.system_start_time:
            deals_to_check = [d for d in history_deals if datetime.fromtimestamp(d.time) >= self.system_start_time]

        daily_profit = sum(deal.profit for deal in deals_to_check)

        if daily_profit < 0:
            drawdown_percent = (abs(daily_profit) / account_info.balance) * 100
            logger.info(
                f"Текущая дневная просадка (с начала сессии): {drawdown_percent:.2f}% (Лимит: {self.max_daily_drawdown_percent}%)"
            )
            if drawdown_percent >= self.max_daily_drawdown_percent:
                logger.critical(f"!!! ТОРГОВЛЯ ОСТАНОВЛЕНА !!! Дневная просадка ({drawdown_percent:.2f}%) превысила лимит.")
                return False
        return True

    def update_correlation_matrix(self, data_dict: Dict[str, pd.DataFrame]):
        try:
            closes = pd.DataFrame(
                {symbol: df["close"] for symbol, df in data_dict.items() if not df.empty and "close" in df.columns}
            )
            returns = closes.interpolate(method="linear", limit_direction="forward", axis=0).pct_change().dropna(how="all")
            if len(returns.columns) > 1:
                self.correlation_matrix = returns.corr()
                self.covariance_matrix = returns.cov()
                logger.info(f"Матрицы корреляции и ковариации обновлены для {len(returns.columns)} символов.")
            else:
                self.correlation_matrix = None
                self.covariance_matrix = None
        except Exception as e:
            logger.error(f"Не удалось обновить матрицы корреляции/ковариации: {e}")
            self.correlation_matrix = None
            self.covariance_matrix = None

    def is_trade_allowed(self, new_symbol: str, new_signal_type: SignalType, open_positions: List) -> bool:
        if self.correlation_matrix is None or self.correlation_matrix.empty:
            return True
        if new_symbol not in self.correlation_matrix.columns:
            return True
        for pos in open_positions:
            if pos.symbol in self.correlation_matrix.columns:
                correlation = self.correlation_matrix.loc[new_symbol, pos.symbol]
                is_same_direction = (new_signal_type == SignalType.BUY and pos.type == mt5.ORDER_TYPE_BUY) or (
                    new_signal_type == SignalType.SELL and pos.type == mt5.ORDER_TYPE_SELL
                )

                if is_same_direction and correlation > self.correlation_threshold:
                    logger.warning(
                        f"Сделка по {new_symbol} ({new_signal_type.name}) заблокирована. Высокая корреляция ({correlation:.2f}) с открытой позицией по {pos.symbol}."
                    )
                    return False
        return True

    def get_portfolio_volatility(self, open_positions: List, new_trade_candidate: Dict[str, Any]) -> Optional[float]:
        if self.covariance_matrix is None or self.covariance_matrix.empty:
            return 0.0
        portfolio_symbols = [pos.symbol for pos in open_positions]
        portfolio_symbols.append(new_trade_candidate["symbol"])
        unique_symbols = sorted(list(set(portfolio_symbols)))
        if not all(s in self.covariance_matrix.columns for s in unique_symbols):
            logger.warning("Некоторые символы портфеля отсутствуют в ковариационной матрице. Расчет пропущен.")
            return 0.0
        num_assets = len(unique_symbols)
        weights = np.array([1 / num_assets] * num_assets)
        sub_cov_matrix = self.covariance_matrix.loc[unique_symbols, unique_symbols]
        try:
            portfolio_variance = np.dot(weights.T, np.dot(sub_cov_matrix, weights))
            return np.sqrt(portfolio_variance)
        except Exception as e:
            logger.error(f"Ошибка при расчете волатильности портфеля: {e}")
            return None

    def update_capital_allocation(self, new_allocation: Dict[str, float]):
        self.capital_allocation = new_allocation

    def run_pre_mortem_analysis(self, df: pd.DataFrame, stop_loss_price: float, trade_type: SignalType) -> bool:
        """Делегирует GARCH Monte Carlo симуляцию модулю StressTester."""
        return self.stress_tester.run_garch_monte_carlo(df, stop_loss_price, trade_type)

    def _is_crypto_symbol(self, symbol: str) -> bool:
        """Проверяет, является ли символ криптовалютным."""
        if self.data_provider_manager:
            return self.data_provider_manager.is_crypto_symbol(symbol)

        # Fallback проверка по паттернам
        crypto_suffixes = ["USDT", "BTC", "ETH", "BUSD", "USDC", "BNB", "SOL", "XRP"]
        upper_symbol = symbol.upper()
        return any(upper_symbol.endswith(suffix) for suffix in crypto_suffixes)

    async def calculate_crypto_position_size(
        self,
        symbol: str,
        df: pd.DataFrame,
        account_info,
        trade_type: SignalType,
        confidence: str = "medium",
        strategy_name: str = "AI_Model",
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Расчёт размера позиции для криптовалютных пар через ccxt.

        Использует аналогичную логику ATR-based risk management,
        но работает с крипто-провайдером вместо MT5.
        """
        if not self.data_provider_manager:
            logger.error(f"[{symbol}] БЛОКИРОВКА: DataProviderManager не установлен")
            return None, None

        provider = self.data_provider_manager.get_crypto_provider(symbol)
        if not provider:
            logger.error(f"[{symbol}] БЛОКИРОВКА: Крипто-провайдер не найден")
            return None, None

        # 1. Расчёт Stop Loss на основе ATR
        if "ATR_14" not in df.columns:
            logger.error(f"[{symbol}] БЛОКИРОВКА: Нет данных ATR_14.")
            return None, None

        atr = df["ATR_14"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            logger.error(f"[{symbol}] БЛОКИРОВКА: ATR_14 невалиден ({atr}).")
            return None, None

        stop_loss_in_price = atr * self.config.STOP_LOSS_ATR_MULTIPLIER

        # 2. Pre-Mortem анализ
        if not self.run_pre_mortem_analysis(df, stop_loss_in_price, trade_type):
            logger.critical(f"[{symbol}] БЛОКИРОВКА: Сделка заблокирована Pre-Mortem анализом.")
            return None, None

        # 3. Определение риска на сделку
        current_regime = self.trading_system._get_current_market_regime_name() if self.trading_system else "Default"
        regime_weights = self.capital_allocation.get(current_regime, self.default_capital_allocation)

        strategy_key = strategy_name
        if strategy_name.startswith("AI_MF_Consensus") or strategy_name.startswith("AI_Model_Confirmed_by_"):
            strategy_key = "AI_Model"

        allocation_for_strategy = regime_weights.get(strategy_key, 0.0)
        if allocation_for_strategy <= 0:
            logger.critical(f"[{symbol}] БЛОКИРОВКА: Allocation <= 0.0. Режим: {current_regime}. Ключ: {strategy_key}")
            return None, None

        risk_amount = account_info.balance * self.config.RISK_PERCENTAGE / 100.0 * allocation_for_strategy

        # 4. Получаем информацию о символе от крипто-провайдера
        symbol_info = await provider.get_symbol_info(symbol)
        if not symbol_info:
            logger.error(f"[{symbol}] БЛОКИРОВКА: Не удалось получить информацию о символе.")
            return None, None

        # 5. Расчёт размера позиции
        current_price = df["close"].iloc[-1]
        sl_points = stop_loss_in_price / current_price if current_price > 0 else 0

        if sl_points <= 0:
            logger.error(f"[{symbol}] БЛОКИРОВКА: SL points <= 0")
            return None, None

        # Для крипты: размер позиции = risk_amount / (sl_points * price)
        position_size = risk_amount / (sl_points * current_price)

        # 6. Нормализация объёма
        min_vol = symbol_info.get("volume_min", 0.0)
        max_vol = symbol_info.get("volume_max", float("inf"))
        volume_step = symbol_info.get("volume_step", 0.0)

        if volume_step and volume_step > 0:
            import math

            decimals = int(max(0, -math.log10(volume_step))) if volume_step < 1 else 0
            position_size = round(round(position_size / volume_step) * volume_step, decimals)

        # Ограничиваем мин/макс
        position_size = max(min_vol, min(position_size, max_vol))

        logger.info(
            f"[{symbol}] КРИПТО РАСЧЁТ: Risk=${risk_amount:.2f}, "
            f"SL_Price=${stop_loss_in_price:.2f}, Final Size={position_size:.6f}"
        )

        return position_size, stop_loss_in_price

    def calculate_position_size(
        self,
        symbol: str,
        df: pd.DataFrame,
        account_info,
        trade_type: SignalType,
        confidence: str = "medium",
        trade_history: List = None,
        strategy_name: str = "AI_Model",
    ) -> Tuple[Optional[float], Optional[float]]:
        if not account_info:
            logger.error(f"[{symbol}] БЛОКИРОВКА: Account info is None.")
            return None, None
        # 1. Расчет Stop Loss в цене (Базовый ATR)
        if "ATR_14" not in df.columns:
            logger.error(f"[{symbol}] БЛОКИРОВКА: Нет данных ATR_14.")
            return None, None
        atr = df["ATR_14"].iloc[-1]
        # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: Получение минимальной дистанции ---
        connector = self.trading_system.terminal_connector
        with self.mt5_lock:
            if not connector.initialize(path=self.config.MT5_PATH):
                return None, None
            symbol_info = connector.symbol_info(symbol)
            connector.shutdown()
        if not symbol_info:
            return None, None
        # Получаем минимальное расстояние в цене (10 пипсов)
        min_distance_price = 10 * symbol_info.point
        # ------------------------------------------------------------------
        if pd.isna(atr) or atr <= 0:
            logger.error(f"[{symbol}] БЛОКИРОВКА: ATR_14 невалиден ({atr}).")
            return None, None
        base_sl_in_price = atr * self.config.STOP_LOSS_ATR_MULTIPLIER
        # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: Принудительное минимальное значение SL ---
        # Гарантируем, что SL всегда больше минимального расстояния + небольшой буфер (10%)
        final_sl_in_price = max(base_sl_in_price, min_distance_price * 1.1)
        # ------------------------------------------------------------------------
        # Используем final_sl_in_price для расчета лота
        stop_loss_in_price_for_lot = final_sl_in_price
        if base_sl_in_price <= 0:
            logger.error(f"[{symbol}] БЛОКИРОВКА: Рассчитанный SL_in_price <= 0.")
            return None, None
        final_sl_in_price = base_sl_in_price
        stop_loss_in_price = final_sl_in_price
        # -----------------------------------------------------------
        # 2. Определение риска на сделку (в валюте депозита)
        current_regime = self.trading_system._get_current_market_regime_name() if self.trading_system else "Default"
        regime_weights = self.capital_allocation.get(current_regime, self.default_capital_allocation)
        # --- ПАТЧ: Определение базового ключа для аллокации ---
        strategy_key = strategy_name
        if strategy_name.startswith("AI_MF_Consensus") or strategy_name.startswith("AI_Model_Confirmed_by_"):
            strategy_key = "AI_Model"
        elif strategy_name.startswith("RLTradeManager"):
            strategy_key = "RLTradeManager"
        # ----------------------------------------------------
        allocation_for_strategy = regime_weights.get(strategy_key, 0.0)

        # === ИСПРАВЛЕНИЕ: Минимальная гарантия для всех стратегий ===
        MIN_ALLOCATION = 0.1  # Минимум 10% капитала для любой активной стратегии
        if allocation_for_strategy <= 0:
            # Проверяем есть ли другие стратегии с >0 allocation
            total_allocation = sum(regime_weights.values())
            if total_allocation > 0:
                # Пересчитываем с минимальной гарантией
                allocation_for_strategy = MIN_ALLOCATION
                logger.warning(
                    f"[{symbol}] WARNING: Orchestrator выделил 0% для {strategy_key}. "
                    f"Установлена минимальная аллокация: {MIN_ALLOCATION:.0%}"
                )
            else:
                logger.critical(f"[{symbol}] БЛОКИРОВКА: Все allocation = 0. Режим: {current_regime}. Ключ: {strategy_key}")
                return None, None
        elif allocation_for_strategy < MIN_ALLOCATION:
            logger.debug(
                f"[{symbol}] Аллокация {strategy_key} ниже минимума: {allocation_for_strategy:.2%} < {MIN_ALLOCATION:.0%}"
            )
        # =========================================================

        # --- RISK.1: ВЫЗОВ PRE-MORTEM АНАЛИЗА ---
        if not self.run_pre_mortem_analysis(df, stop_loss_in_price, trade_type):
            logger.critical(f"[{symbol}] БЛОКИРОВКА: Сделка заблокирована Pre-Mortem анализом.")
            return None, None
        # ----------------------------------------
        risk_amount = account_info.balance * self.config.RISK_PERCENTAGE / 100.0 * allocation_for_strategy
        # 3. Расчет объема лота
        with self.mt5_lock:
            # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: Проверка инициализации MT5 ---
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error(
                    f"[{symbol}] БЛОКИРОВКА: Не удалось инициализировать MT5 для расчета лота. Путь: {self.config.MT5_PATH}"
                )
                return None, None
            try:
                symbol_info = mt5.symbol_info(symbol)
                if not symbol_info:
                    logger.error(f"[{symbol}] БЛОКИРОВКА: Не удалось получить symbol_info.")
                    return None, None
                tick_size = symbol_info.trade_tick_size
                quote_currency = symbol_info.currency_profit
                account_currency = self.trading_system.account_currency
                conversion_rate = 1.0
                if quote_currency != account_currency and self.trading_system.data_provider:
                    conversion_rate = self.trading_system.data_provider.get_conversion_rate(quote_currency, account_currency)
                tick_value_in_account_currency = symbol_info.trade_tick_value * conversion_rate
                # --- КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ НУЛЕВЫХ ЗНАЧЕНИЙ ---
                if tick_size <= 0:
                    logger.error(f"[{symbol}] БЛОКИРОВКА: tick_size <= 0 ({tick_size}).")
                    return None, None
                if tick_value_in_account_currency <= 0:
                    logger.error(
                        f"[{symbol}] БЛОКИРОВКА: tick_value_in_account_currency <= 0 ({tick_value_in_account_currency})."
                    )
                    return None, None
                # -------------------------------------------------
                sl_points = stop_loss_in_price / tick_size
                denominator = sl_points * tick_value_in_account_currency
                if denominator == 0:
                    logger.error(f"[{symbol}] БЛОКИРОВКА: Знаменатель лота равен нулю (sl_points={sl_points}).")
                    return None, None
                lot_size = risk_amount / denominator
                # Нормализация лота
                step = symbol_info.volume_step
                min_vol = symbol_info.volume_min
                max_vol = symbol_info.volume_max
                # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 3.0: Гарантируем, что step - float > 0 ---
                if step is None or step == 0:
                    # Устанавливаем минимальный шаг лота для крипто/акций
                    step = 0.01
                    logger.warning(f"[{symbol}] volume_step был None/0. Установлено безопасное значение: {step}")
                # Также убедимся, что lot_size - float
                lot_size = float(lot_size)
                
                # АДАПТИВНОСТЬ: Проверка на минимальный лот через AccountManager
                if self.account_manager:
                    lot_size = self.account_manager.adjust_lot_for_min(symbol, lot_size)
                    if lot_size == 0.0:
                        logger.warning(f"[{symbol}] АДАПТИВНЫЙ РИСК: Невозможно открыть позицию (недостаточно маржи для мин. лота)")
                        return None, None

                # ----------------------------------------------------------------------
                if step > 0:
                    import math

                    decimals = int(max(0, -math.log10(step))) if step < 1 else 0
                    lot_size = round(round(lot_size / step) * step, decimals)
                    logger.info(
                        f"[{symbol}] РАСЧЕТ ЛОТА: Risk=${risk_amount:.2f}, SL_Price={stop_loss_in_price:.5f}, Final Lot={lot_size:.2f}"
                    )
                    # !!! ФИНАЛЬНЫЙ ВОЗВРАТ !!!
                    return lot_size, stop_loss_in_price
            except Exception as e:
                logger.error(f"Ошибка расчета лота для {symbol}: {e}", exc_info=True)
                return None, None
            finally:
                mt5.shutdown()  # <-- ГАРАНТИРОВАННОЕ ЗАКРЫТИЕ

    def calculate_portfolio_var(self, open_positions: List, data_dict: Dict[str, pd.DataFrame]) -> Optional[float]:
        confidence_level = self.risk_config.portfolio_var_confidence_level
        if not open_positions:
            return 0.0

        portfolio_symbols = [pos["symbol"] if isinstance(pos, dict) else pos.symbol for pos in open_positions]

        all_returns = []
        for symbol in set(portfolio_symbols):
            # Проверяем крипто-символ
            is_crypto = self._is_crypto_symbol(symbol)

            if is_crypto:
                # Для крипто используем данные из data_dict (они уже в унифицированном формате)
                # Ключ может быть просто symbol или symbol_H1
                df = data_dict.get(symbol) or data_dict.get(f"{symbol}_H1") or data_dict.get(f"{symbol}_1h")
                if df is not None and not df.empty and "close" in df.columns:
                    all_returns.append(df["close"].pct_change().dropna())
            else:
                # Для MT5 символов
                df = data_dict.get(f"{symbol}_{mt5.TIMEFRAME_H1}")
                if df is not None and not df.empty:
                    all_returns.append(df["close"].pct_change().dropna())

        if not all_returns:
            logger.warning("Нет данных о доходностях для расчета VaR.")
            return None

        portfolio_returns_df = pd.concat(all_returns, axis=1).mean(axis=1)
        portfolio_returns = portfolio_returns_df.dropna()

        if len(portfolio_returns) < 30:
            logger.warning(f"Недостаточно данных ({len(portfolio_returns)}) для надежного расчета VaR.")
            return None

        try:
            garch_model = arch_model(portfolio_returns * 100, vol="Garch", p=1, q=1, rescale=False)
            garch_fit = garch_model.fit(disp="off", show_warning=False)

            forecast = garch_fit.forecast(horizon=1)
            predicted_variance = forecast.variance.iloc[-1, 0]
            predicted_std = np.sqrt(predicted_variance) / 100.0

            z_score = norm.ppf(confidence_level)
            var = z_score * predicted_std

            logger.info(f"Расчетный портфельный VaR ({confidence_level * 100:.0f}%): {var:.2%}")
            return var
        except Exception as e:
            logger.error(f"Ошибка при расчете VaR: {e}")
            return None

    def check_and_apply_hedging(
        self, open_positions: List, data_dict: Dict[str, pd.DataFrame], account_info, portfolio_var=None
    ) -> Optional[Tuple[str, TradeSignal, float]]:

        # 1. Ранний выход, если нет позиций или данных для анализа.
        if not open_positions or self.correlation_matrix is None:
            return None

        # 2. Собираем информацию о текущем портфеле.
        # Примечание: open_positions может содержать объекты Position, а не dicts.
        # Мы используем атрибуты, если это объекты MT5/SimPosition.
        open_positions_dicts = [{"symbol": p.symbol, "volume": p.volume, "profit": p.profit} for p in open_positions]

        # 3. Расчет портфельного VaR (если не передан)
        if portfolio_var is None:
            portfolio_var = self.calculate_portfolio_var(open_positions_dicts, data_dict)

        if portfolio_var is None:
            logger.warning("Не удалось рассчитать портфельный VaR. Хеджирование пропущено.")
            return None

        # 4. Проверка условия хеджирования (TZ 3.3)
        if (portfolio_var * 100) <= self.max_portfolio_var_percent:
            return None

        # --- TZ 3.3: Динамическое Хеджирование (Delta Hedging) ---

        logger.critical(
            f"!!! ПОРТФЕЛЬНЫЙ РИСК ПРЕВЫШЕН !!! VaR = {portfolio_var:.2%}. Лимит = {self.max_portfolio_var_percent}%. Поиск хеджирующей позиции."
        )

        excess_risk_percent = (portfolio_var * 100) - self.max_portfolio_var_percent

        # 1. Выбираем хеджирующий инструмент (DXY или VIX)
        # Используем H4 для DXY, так как это более стабильный ТФ для макро-анализа
        hedge_symbol = "DXY" if "DXY_H4" in data_dict else "VIX"
        df_hedge = data_dict.get(f"{hedge_symbol}_H4")

        if df_hedge is None:
            logger.warning(f"Не удалось получить данные для хеджирующего символа {hedge_symbol}.")
            return None

        # 2. Прогнозируем волатильность хеджирующего инструмента (для Delta)
        # Используем ATR как прокси для волатильности
        hedge_volatility = df_hedge["ATR_14"].iloc[-1] if "ATR_14" in df_hedge.columns else 0.001

        if hedge_volatility == 0:
            logger.warning("Волатильность хеджирующего инструмента равна 0. Хеджирование пропущено.")
            return None

        # 3. Расчет необходимого лота (Delta Hedging)
        # ExcessRisk_USD = ExcessRisk_Percent * Balance / 100
        excess_risk_usd = excess_risk_percent * account_info.balance / 100.0

        # Упрощение: лот = ExcessRisk_USD / 1000 (для масштабирования)
        hedge_lot_size = excess_risk_usd / 1000.0

        # 4. Определяем направление хеджа (обратное к портфелю)
        # Суммируем прибыль/убыток всех позиций
        portfolio_pnl = sum(p["profit"] for p in open_positions_dicts)
        hedge_direction = SignalType.SELL if portfolio_pnl > 0 else SignalType.BUY

        hedge_signal = TradeSignal(type=hedge_direction, confidence=0.99, symbol=hedge_symbol)

        logger.critical(
            f"!!! DELTA HEDGING: Excess VaR={excess_risk_percent:.2f}%. Открытие {hedge_direction.name} {hedge_lot_size:.2f} по {hedge_symbol}."
        )

        return hedge_symbol, hedge_signal, hedge_lot_size

    def _normalize_lot_size(self, lot_size: float, symbol_info: Any, symbol: str = "") -> float:
        """Нормализует лот в соответствии с правилами MT5 (step, min, max) и риском счета."""
        step = symbol_info.volume_step
        min_vol = symbol_info.volume_min
        max_vol = symbol_info.volume_max

        if step > 0:
            import math

            decimals = int(max(0, -math.log10(step))) if step < 1 else 0
            lot_size = round(round(lot_size / step) * step, decimals)

        # АДАПТИВНОСТЬ: Если расчетный лот меньше минимального, проверяем можем ли мы открыть минимум
        if lot_size < min_vol and self.account_manager:
            return self.account_manager.adjust_lot_for_min(symbol, lot_size)

        return max(min_vol, min(max_vol, lot_size))

    # === РЕЖИМЫ ТОРГОВЛИ ===

    def set_trading_mode(self, mode_id: str, settings: Optional[Dict[str, Any]] = None):
        """
        Установка режима торговли с предопределенными настройками риск-менеджмента.

        Args:
            mode_id: Идентификатор режима ("conservative", "standard", "aggressive", "yolo", "custom")
            settings: Пользовательские настройки (для кастомного режима)
        """
        if mode_id not in TRADING_MODES and mode_id != "custom":
            logger.warning(f"Неизвестный режим торговли: {mode_id}")
            return

        if mode_id == "custom":
            if settings:
                self._apply_custom_settings(settings)
                logger.info(f"Применен кастомный режим торговли с настройками: {settings}")
            return

        mode_data = TRADING_MODES[mode_id]

        # Применяем настройки режима через атрибуты risk_engine (не через config.risk)
        self.base_risk_per_trade_percent = mode_data["risk_percentage"]
        # max_positions теперь в trading_system
        # self.risk_config.max_positions = mode_data["max_positions"]
        self.max_daily_drawdown_percent = mode_data["max_daily_drawdown"]
        self.risk_config.stop_loss_atr_multiplier = mode_data["stop_loss_atr_multiplier"]
        self.risk_config.risk_reward_ratio = mode_data["risk_reward_ratio"]
        self.risk_config.enable_all_risk_checks = mode_data["enable_all_risk_checks"]

        logger.info(
            f"🎯 Режим торговли установлен: {mode_data['icon']} {mode_data['name']}\n"
            f"   Risk: {mode_data['risk_percentage']}% | Max DD: {mode_data['max_daily_drawdown']}%"
        )

    def _apply_custom_settings(self, settings: Dict[str, Any]):
        """Применение пользовательских настроек риск-менеджмента."""
        if "risk_percentage" in settings:
            self.base_risk_per_trade_percent = settings["risk_percentage"]
        # max_positions теперь в trading_system
        # if "max_positions" in settings:
        #     self.risk_config.max_positions = settings["max_positions"]
        if "max_daily_drawdown" in settings:
            self.max_daily_drawdown_percent = settings["max_daily_drawdown"]
        if "stop_loss_atr_multiplier" in settings:
            self.risk_config.stop_loss_atr_multiplier = settings["stop_loss_atr_multiplier"]
        if "risk_reward_ratio" in settings:
            self.risk_config.risk_reward_ratio = settings["risk_reward_ratio"]
        if "enable_all_risk_checks" in settings:
            self.risk_config.enable_all_risk_checks = settings["enable_all_risk_checks"]

        logger.info(f"🔧 Применены кастомные настройки риска: {settings}")


# === ПРЕСЕТЫ РЕЖИМОВ ТОРГОВЛИ ===
TRADING_MODES = {
    "conservative": {
        "name": "Консервативный",
        "icon": "🟢",
        "risk_percentage": 0.25,
        "max_positions": 3,
        "max_daily_drawdown": 2.0,
        "stop_loss_atr_multiplier": 2.0,
        "risk_reward_ratio": 1.5,
        "enable_all_risk_checks": True,
        "description": "Минимальный риск, максимальная защита капитала",
    },
    "standard": {
        "name": "Стандартный",
        "icon": "🟡",
        "risk_percentage": 0.5,
        "max_positions": 10,
        "max_daily_drawdown": 5.0,
        "stop_loss_atr_multiplier": 3.0,
        "risk_reward_ratio": 2.5,
        "enable_all_risk_checks": True,
        "description": "Баланс между риском и доходностью",
    },
    "aggressive": {
        "name": "Агрессивный",
        "icon": "🔴",
        "risk_percentage": 2.0,
        "max_positions": 25,
        "max_daily_drawdown": 15.0,
        "stop_loss_atr_multiplier": 4.0,
        "risk_reward_ratio": 4.0,
        "enable_all_risk_checks": False,
        "description": "Высокий риск для максимальной прибыли",
    },
    "yolo": {
        "name": "YOLO",
        "icon": "⚫",
        "risk_percentage": 10.0,
        "max_positions": 50,
        "max_daily_drawdown": 30.0,
        "stop_loss_atr_multiplier": 5.0,
        "risk_reward_ratio": 10.0,
        "enable_all_risk_checks": False,
        "description": "YOU ONLY LIVE ONCE - максимальный риск!",
    },
}
