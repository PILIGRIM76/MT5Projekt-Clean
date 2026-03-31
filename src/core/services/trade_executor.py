# src/core/services/trade_executor.py
import asyncio
import logging
from typing import Dict, Any, Optional, List
import threading
import time
from datetime import datetime, timedelta

# Используется только для констант (ORDER_TYPE_BUY и т.д.)
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
import time as standard_time

# from statsmodels.sandbox.regression.sympy_diff import df  # COMMENTED OUT - not used
# from torchgen.api.unboxing import connector  # COMMENTED OUT - not used

from src.core.config_models import Settings
from src.data_models import TradeSignal, SignalType
from src.risk.risk_engine import RiskEngine
from src.core.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self, config: Settings, risk_engine: RiskEngine, portfolio_service: PortfolioService,
                 mt5_lock: threading.Lock):
        self.config = config
        self.risk_engine = risk_engine
        self.portfolio_service = portfolio_service
        self.mt5_lock = mt5_lock
        self.filling_type_cache: Dict[str, int] = {}

        self.use_limit_entry = True  # Включаем Limit-to-Market по умолчанию
        self.limit_wait_seconds = 30
        self.min_lot_for_twap = 5.0  # [TZ 1.3] Порог для TWAP/VWAP

    def _is_market_open(self, symbol: str, symbol_info: Any) -> bool:
        """
        Проверяет, открыт ли рынок для торговли.

        Проверки:
        1. Режим торговли (trade_mode)
        2. День недели (выходные для Forex, но не для крипты)
        3. Время последнего тика (свежесть данных)

        Returns:
            True если рынок открыт, False если закрыт
        """
        # datetime уже импортирован глобально

        # Проверка 1: Режим торговли
        # trade_mode: 0 = disabled, 1 = longonly, 2 = shortonly, 3 = closeonly, 4 = full
        if symbol_info.trade_mode == 0:
            logger.debug(f"[{symbol}] Торговля отключена (trade_mode=0)")
            return False

        if symbol_info.trade_mode == 3:  # Close only
            logger.debug(f"[{symbol}] Только закрытие позиций (trade_mode=3)")
            return False

        # Проверка 2: Определяем тип инструмента
        # Криптовалюты и некоторые другие инструменты торгуются 24/7
        symbol_upper = symbol.upper()

        # Список инструментов, которые торгуются 24/7
        is_24_7_instrument = any([
            'BTC' in symbol_upper,
            'BITCOIN' in symbol_upper,
            'ETH' in symbol_upper,
            'ETHEREUM' in symbol_upper,
            'CRYPTO' in symbol_upper,
            'USDT' in symbol_upper,
            # Добавьте другие криптовалюты по необходимости
        ])

        # Проверка: торговля в соответствии с настройками рабочего времени
        if hasattr(self.risk_engine, 'trading_system') and self.risk_engine.trading_system:
            session_mgr = getattr(
                self.risk_engine.trading_system, 'session_manager', None)
            if session_mgr and not session_mgr.is_trading_hours(symbol):
                logger.debug(
                    f"[{symbol}] Трейдинг вне торгового времени (SessionManager).")
                return False

        # Для инструментов 24/7 пропускаем проверку выходных или если включена опция
        if not is_24_7_instrument and not self.risk_engine.trading_system.config.ALLOW_WEEKEND_TRADING:
            # Для Forex и других инструментов проверяем выходные
            current_time = datetime.now()
            weekday = current_time.weekday()  # 0=Monday, 6=Sunday

            # Суббота (5) - рынок закрыт
            if weekday == 5:
                logger.debug(
                    f"[{symbol}] Выходной день (суббота). Forex рынок закрыт.")
                return False

            # Воскресенье (6) до 23:00 - рынок закрыт
            if weekday == 6 and current_time.hour < 23:
                logger.debug(
                    f"[{symbol}] Выходной день (воскресенье до 23:00). Forex рынок закрыт.")
                return False

            # Пятница после 23:00 - рынок закрывается
            if weekday == 4 and current_time.hour >= 23:
                logger.debug(
                    f"[{symbol}] Конец недели (пятница после 23:00). Forex рынок закрыт.")
                return False
        else:
            if is_24_7_instrument:
                logger.debug(
                    f"[{symbol}] Инструмент 24/7 (криптовалюта). Проверка выходных пропущена.")
            else:
                logger.debug(
                    f"[{symbol}] Weekend trading разрешен конфигом. Проверка выходных пропущена.")

        # Проверка 3: Свежесть тика (последнее обновление цены)
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                tick_time = datetime.fromtimestamp(tick.time)
                time_diff = (datetime.now() - tick_time).total_seconds()

                # Если последний тик старше 5 минут - рынок вероятно закрыт
                if time_diff > 300:  # 5 минут
                    logger.debug(
                        f"[{symbol}] Последний тик {time_diff:.0f} сек назад. Рынок вероятно закрыт.")
                    return False
            else:
                logger.debug(
                    f"[{symbol}] Не удалось получить тик. Рынок вероятно закрыт.")
                return False
        except Exception as e:
            logger.warning(f"[{symbol}] Ошибка проверки тика: {e}")
            return False

        # Все проверки пройдены - рынок открыт
        return True

    def _calculate_fair_value_spread(self, df: pd.DataFrame, symbol_info: Any) -> float:
        """
        [TZ 1.2] Рассчитывает справедливый спред (в цене) как функцию от средней волатильности (ATR).
        """
        # ЗАЩИТА: Проверка symbol_info.point
        if symbol_info is None or symbol_info.point is None or symbol_info.point <= 0:
            logger.warning(
                f"_calculate_fair_value_spread: Invalid symbol_info.point={symbol_info.point if symbol_info else None}. Возврат default 0.0001")
            return 0.0001  # Default spread

        if df.empty or 'ATR_14' not in df.columns:
            return 10 * symbol_info.point  # Заглушка: 10 пипсов

        avg_atr = df['ATR_14'].iloc[-50:].mean()
        min_spread_price = 1.0 * symbol_info.point  # 1 пипс

        # Fair Value Spread = Max(Мин.Спред, 0.1 * Avg_ATR)
        fair_value_spread = max(min_spread_price, 0.1 * avg_atr)
        return fair_value_spread

    async def _execute_twap(self, symbol: str, signal_type: SignalType, lot_size: float,
                            stop_loss_in_price: float, timeframe: int, strategy_name: str,
                            df: pd.DataFrame, entry_price_for_learning: float) -> Optional[int]:
        """
        [TZ 1.3] Имитация исполнения TWAP: разбивает ордер на части.
        """
        num_parts = 5
        interval_seconds = 60

        connector = self.risk_engine.trading_system.terminal_connector

        # --- БЛОК 1: Получение общих параметров (вне цикла) ---
        # ОПТИМИЗАЦИЯ: Минимизируем время удержания lock
        symbol_info = None
        with self.mt5_lock:
            if not connector.initialize(path=self.config.MT5_PATH):
                return None
            try:
                symbol_info = connector.symbol_info(symbol)
            finally:
                connector.shutdown()

        if not symbol_info:
            return None

        # Расчеты вне блокировки
        volume_step = symbol_info.volume_step
        digits = symbol_info.digits
        stop_level_points = symbol_info.trade_stops_level or 0
        point = symbol_info.point or 0.00001

        # Для криптосимволов (BITCOIN, ETHEREUM и т.д.) MT5 часто возвращает trade_stops_level=0
        # Используем динамический fallback: 10 * point для крипто, или 1 * point как минимум
        if stop_level_points <= 0:
            is_crypto = any(x in symbol.upper()
                            for x in ['BTC', 'ETH', 'BIT', 'COIN'])
            stop_level_points = 10 if is_crypto else 1
            logger.debug(
                f"[{symbol}] TWAP: Используем динамический stop_level={stop_level_points} (крипто={is_crypto})")

        if point <= 0:
            logger.error(
                f"[{symbol}] TWAP: Invalid point={point}. Пропуск.")
            return None

        min_distance_price = max(stop_level_points * point, 1 * point)
        # ----------------------------------------------------------

        # ... (логика расчета part_lot без изменений) ...
        import math
        if volume_step > 0:
            decimals = int(max(0, -math.log10(volume_step))
                           ) if volume_step < 1 else 0
            part_lot = round(round(lot_size / num_parts /
                             volume_step) * volume_step, decimals)
        else:
            part_lot = round(lot_size / num_parts, 2)
        # -------------------------------------------------------------

        logger.critical(
            f"[{symbol}] TWAP EXECUTION: Разбивка лота {lot_size:.2f} на {num_parts} частей. Часть: {part_lot:.2f}")

        first_ticket = None

        for i in range(num_parts):
            result = None  # Инициализируем result для проверки после блока try/finally

            if not self.mt5_lock.acquire(timeout=0.5):
                logger.debug(
                    f"[{symbol}] TWAP: MT5 Lock недоступен (timeout 0.5s) на части {i + 1}.")
                continue
            try:
                if not connector.initialize(path=self.config.MT5_PATH):
                    logger.error(
                        f"[{symbol}] TWAP: Ошибка инициализации MT5 на части {i + 1}.")
                    break
                try:
                    tick = connector.symbol_info_tick(symbol)
                    if not tick:
                        logger.error(
                            f"[{symbol}] TWAP: Нет тика на части {i + 1}.")
                        break

                    # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: Пересчет SL/TP для каждой части ---
                    # Используем текущую цену тика для расчета SL/TP
                    price = tick.ask if signal_type == SignalType.BUY else tick.bid
                    sl_distance = stop_loss_in_price  # Расстояние SL берем из ATR

                    # Проверка на None перед сравнением
                    if sl_distance is None or sl_distance <= 0:
                        logger.error(
                            f"TWAP PART {i + 1}/{num_parts} ОШИБКА: stop_loss_in_price is None or <= 0. Пропуск TWAP.")
                        break
                    # Проверка на минимальную дистанцию (повторяем, чтобы быть уверенными)
                    if sl_distance < min_distance_price * 1.1:
                        logger.error(
                            f"TWAP PART {i + 1}/{num_parts} ОШИБКА: Рассчитанный SL ({sl_distance:.5f}) "
                            f"меньше мин. дистанции ({min_distance_price:.5f}). Пропуск TWAP.")
                        break  # Прерываем TWAP, так как SL невалиден

                    # Пересчитываем SL и TP на основе ТЕКУЩЕЙ цены
                    sl = price - sl_distance if signal_type == SignalType.BUY else price + sl_distance
                    tp = price + (
                        sl_distance * self.config.RISK_REWARD_RATIO) if signal_type == SignalType.BUY else price - (
                        sl_distance * self.config.RISK_REWARD_RATIO)

                    # Округление
                    sl = round(sl, digits)
                    tp = round(tp, digits)
                    price = round(price, digits)
                    # ------------------------------------------------------------------

                    # Используем округленный part_lot
                    request = self._build_request(symbol, part_lot, signal_type, price, sl, tp, timeframe,
                                                  strategy_name, digits)
                    result = connector.order_send(request)

                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        position_ticket = result.deal
                        if position_ticket is None or position_ticket == 0:
                            logger.error(
                                f"TWAP PART {i + 1}/{num_parts} ОШИБКА: MT5 вернул DONE, но deal=0. Пропуск.")
                            break

                        if first_ticket is None:
                            first_ticket = position_ticket
                        logger.critical(
                            f"TWAP PART {i + 1}/{num_parts} ИСПОЛНЕН. Ticket: {position_ticket}")
                        self._persist_entry_data(position_ticket, symbol, strategy_name, sl, None, None,
                                                 entry_price_for_learning, df.index[-1], timeframe, df)
                    else:
                        logger.error(
                            f"TWAP PART {i + 1}/{num_parts} ОШИБКА: {result.comment if result else 'None'}")
                        break
                finally:
                    connector.shutdown()
            finally:
                self.mt5_lock.release()

            if i < num_parts - 1:
                # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: Проверяем, что не было break в блоке try ---
                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    break
                # --------------------------------------------------------------------------
                await asyncio.sleep(float(interval_seconds))

        return first_ticket

    async def _execute_market_order(self, symbol: str, signal_type: SignalType, lot_size: float,
                                    stop_loss_in_price: float, timeframe: int, strategy_name: str,
                                    df: pd.DataFrame, entry_price_for_learning: float) -> Optional[int]:
        """
        Выполняет Market Execution (рыночный ордер).
        """
        connector = self.risk_engine.trading_system.terminal_connector

        if not self.mt5_lock.acquire(timeout=0.5):
            logger.debug(
                f"[{symbol}] _execute_market_order: MT5 Lock недоступен (timeout 0.5s). Пропуск.")
            return None
        try:
            if not connector.initialize(path=self.config.MT5_PATH):
                return None
            try:
                tick = connector.symbol_info_tick(symbol)
                symbol_info = connector.symbol_info(symbol)
                if not tick or not symbol_info:
                    return None

                # НОВАЯ ПРОВЕРКА: Проверяем, открыт ли рынок для торговли
                if not self._is_market_open(symbol, symbol_info):
                    logger.debug(
                        f"[{symbol}] Рынок закрыт. Ордер не отправляется.")
                    return None

                # --- ИСПРАВЛЕНИЕ 4: Корректное получение STOP_LEVEL в цене (с поддержкой крипто) ---
                stop_level_points = symbol_info.trade_stops_level or 0
                point = symbol_info.point or 0.00001  # Fallback для None

                # Для криптосимволов (BITCOIN, ETHEREUM и т.д.) MT5 часто возвращает trade_stops_level=0
                # Используем динамический fallback: 10 * point для крипто, или 1 * point как минимум
                if stop_level_points <= 0:
                    is_crypto = any(x in symbol.upper()
                                    for x in ['BTC', 'ETH', 'BIT', 'COIN'])
                    stop_level_points = 10 if is_crypto else 1
                    logger.debug(
                        f"[{symbol}] Используем динамический stop_level={stop_level_points} (крипто={is_crypto})")

                if point <= 0:
                    logger.error(
                        f"[{symbol}] MARKET ORDER: Invalid point={point}. Пропуск.")
                    return None

                min_distance_price = max(stop_level_points * point, 1 * point)
                # ----------------------------------------------------------

                # --- ИСПРАВЛЕНИЕ 5: Проверка SL_in_price ДО расчета SL/TP ---
                if stop_loss_in_price is None or stop_loss_in_price <= 0:
                    logger.error(
                        f"MARKET ОРДЕР ОШИБКА: stop_loss_in_price is None or <= 0. Пропуск ордера.")
                    return None
                if stop_loss_in_price < min_distance_price * 1.1:
                    logger.error(f"MARKET ОРДЕР ОШИБКА: Рассчитанный SL ({stop_loss_in_price:.5f}) "
                                 f"меньше мин. дистанции ({min_distance_price:.5f}). Пропуск ордера.")
                    return None
                # ----------------------------------------------------------

                price = tick.ask if signal_type == SignalType.BUY else tick.bid

                # --- ИСПРАВЛЕНИЕ 6: Округление SL/TP и цены ---
                digits = symbol_info.digits

                sl = price - stop_loss_in_price if signal_type == SignalType.BUY else price + \
                    stop_loss_in_price
                tp = price + (
                    stop_loss_in_price * self.config.RISK_REWARD_RATIO) if signal_type == SignalType.BUY else price - (
                    stop_loss_in_price * self.config.RISK_REWARD_RATIO)

                sl = round(sl, digits)
                tp = round(tp, digits)
                price = round(price, digits)
                # ----------------------------------------------------------

                request = self._build_request(symbol, lot_size, signal_type, price, sl, tp, timeframe, strategy_name,
                                              symbol_info.digits)

                # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ ПЕРЕД ОТПРАВКОЙ
                logger.info(f"[{symbol}] Отправка Market ордера:")
                logger.info(
                    f"  - Type: {'BUY' if signal_type == SignalType.BUY else 'SELL'}")
                logger.info(f"  - Lot: {lot_size}")
                logger.info(f"  - Price: {price}")
                logger.info(f"  - SL: {sl}, TP: {tp}")
                logger.info(
                    f"  - Symbol info: visible={symbol_info.visible}, trade_mode={symbol_info.trade_mode}")
                logger.info(f"  - Tick: ask={tick.ask}, bid={tick.bid}")

                # === ПРОВЕРКА АВТОТОРГОВЛИ ПЕРЕД ОТПРАВКОЙ ===
                try:
                    auto_trading_enabled = mt5.TerminalInfo(
                        mt5.TERMINAL_TRADE_ALLOWED)
                    if not auto_trading_enabled:
                        logger.critical(
                            f"[{symbol}] ⚠️ АВТОТОРГОВЛЯ ОТКЛЮЧЕНА! Ордер НЕ отправлен.")
                        logger.critical(
                            f"[{symbol}] Включите Algo Trading в MT5 (Ctrl+E)")
                        return None
                except Exception as check_error:
                    logger.warning(
                        f"[{symbol}] Не удалось проверить автоторговлю: {check_error}")
                # ============================================

                result = connector.order_send(request)

                # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ РЕЗУЛЬТАТА
                if result is None:
                    last_error = mt5.last_error()
                    logger.error(f"[{symbol}] MT5 order_send вернул None!")
                    logger.error(f"  - Last error: {last_error}")
                    logger.error(f"  - Request: {request}")
                    return None

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    position_ticket = result.deal
                    logger.critical(
                        f"MARKET ОРДЕР ИСПОЛНЕН: {result.comment}. Ticket: {position_ticket}")
                    self.risk_engine.trading_system.sound_manager.play(
                        "trade_open")
                    self._persist_entry_data(position_ticket, symbol, strategy_name, sl, None, None,
                                             entry_price_for_learning, df.index[-1], timeframe, df)
                    return position_ticket
                else:
                    # УЛУЧШЕННАЯ ОБРАБОТКА ОШИБОК: Не логируем как ERROR, если рынок закрыт
                    if result.retcode == 10018:  # Market closed
                        logger.debug(
                            f"[{symbol}] Рынок закрыт (retcode 10018). Ордер не исполнен.")
                    else:
                        logger.error(f"[{symbol}] Ошибка Market ордера:")
                        logger.error(f"  - Retcode: {result.retcode}")
                        logger.error(f"  - Comment: {result.comment}")
                        logger.error(f"  - Request: {request}")
                    return None
            finally:
                connector.shutdown()
        finally:
            self.mt5_lock.release()
        return None

    def _calculate_adaptive_offset(self, df: pd.DataFrame, tick: Any, symbol_info: Any) -> float:
        """
        Рассчитывает динамический офсет лимитного ордера в пипсах.
        Зависит от волатильности (ATR) и ликвидности (Spread).

        Логика:
        - Высокая волатильность/широкий спред -> больший офсет (ближе к рынку, быстрее исполнение).
        - Низкая волатильность/узкий спред -> меньший офсет (лучшая цена).
        """
        # 1. Волатильность (ATR)
        normalized_atr_percent = 0.0
        if 'ATR_14' in df.columns and not df.empty and df['close'].iloc[-1] > 0:
            last_atr = df['ATR_14'].iloc[-1]
            last_close = df['close'].iloc[-1]
            # Нормализованный ATR в процентах (ATR/Close * 100)
            normalized_atr_percent = (last_atr / last_close) * 100

        # 2. Ликвидность (Spread)
        if symbol_info.point is not None and symbol_info.point > 0:
            spread_pips = round((tick.ask - tick.bid) / symbol_info.point)
        else:
            spread_pips = 5

        # 3. Адаптивная формула: Max(Мин.Офсет, Компонент_Волатильности + Компонент_Ликвидности)
        # - Компонент Волатильности: 5 * Normalized_ATR_Percent
        # - Компонент Ликвидности: Spread_Pips / 2

        volatility_component = normalized_atr_percent * 5.0
        liquidity_component = spread_pips / 2.0

        # Минимальный офсет - 2 пипса, максимальный - 20 пипсов
        dynamic_offset_pips = max(
            2.0, min(20.0, volatility_component + liquidity_component))

        logger.info(f"[{symbol_info.name}] Адаптивный офсет: {dynamic_offset_pips:.2f} пипс. "
                    f"(ATR_Norm: {normalized_atr_percent:.2f}%, Spread: {spread_pips} пипс)")

        return dynamic_offset_pips

    async def execute_trade(self, symbol: str, signal: TradeSignal, lot_size: float, df: pd.DataFrame,
                            timeframe: int, strategy_name: str, stop_loss_in_price: float,
                            observer_mode: bool, prediction_input: Optional[Any] = None,
                            entry_price_for_learning: Optional[float] = None) -> Optional[int]:
        """
        [TZ 1.1, 1.2, 1.3] Исполняет торговый сигнал с адаптивной логикой.
        """
        # P0: Circuit Breaker — проверка перед торговлей
        if hasattr(self.risk_engine.trading_system, 'circuit_breaker'):
            cb = self.risk_engine.trading_system.circuit_breaker
            if cb.enabled and not cb.is_trading_allowed:
                logger.warning(
                    f"[{symbol}] 🚨 Circuit Breaker блокирует торговлю! "
                    f"Состояние: {cb.state.value}, Причина: последний триггер {cb.last_trip_time}"
                )
                # Записываем ошибку в Circuit Breaker
                cb.record_error()
                return None
        
        # НОВОЕ: Проверка доступности MT5 соединения
        if self.risk_engine.trading_system.mt5_connection_failed:
            # Исправление: type может быть строкой или SignalType
            signal_type_name = signal.type if isinstance(signal.type, str) else (signal.type.name if hasattr(signal.type, 'name') else str(signal.type))
            logger.warning(
                f"[{symbol}] ⚠️ MT5 соединение недоступно (Fallback Mode). "
                f"Сигнал {signal_type_name} будет кэширован для последующего исполнения. "
                f"Реального ордера отправлено не будет.")
            return None

        if observer_mode:
            # ... (логика режима наблюдателя) ...
            return int(standard_time.time() * 1000)

        # ОПТИМИЗАЦИЯ: Минимизируем время удержания lock (с timeout для избежания блокировки R&D)
        connector = self.risk_engine.trading_system.terminal_connector
        symbol_info = None
        tick = None
        if not self.mt5_lock.acquire(timeout=0.5):
            logger.debug(
                f"[{symbol}] execute_trade: MT5 Lock недоступен (timeout 0.5s). Пропуск.")
            return None
        try:
            if not connector.initialize(path=self.config.MT5_PATH):
                return None
            try:
                symbol_info = connector.symbol_info(symbol)
                tick = connector.symbol_info_tick(symbol)
            finally:
                connector.shutdown()
        finally:
            self.mt5_lock.release()

        if not symbol_info or not tick:
            return None

        if tick.ask == 0.0 or tick.bid == 0.0 or tick.ask == tick.bid:
            logger.critical(
                f"[{symbol}] СДЕЛКА ЗАБЛОКИРОВАНА: Рынок, вероятно, ЗАКРЫТ (Ask/Bid = 0 или Ask=Bid).")
            return None

        # --- TZ 1.2: Динамический Спред-Фильтр ---
        current_spread_price = tick.ask - tick.bid
        fair_spread = self._calculate_fair_value_spread(df, symbol_info)

        # ИСПРАВЛЕНИЕ: Проверка на None перед сравнением
        if fair_spread is None:
            logger.warning(
                f"[{symbol}] fair_spread is None. Пропуск спред-фильтра.")
            return None
        # ИСПРАВЛЕНИЕ: Увеличиваем множитель с 1.2 до 2.5
        if current_spread_price > 2.5 * fair_spread:
            logger.critical(
                f"[{symbol}] СДЕЛКА ЗАБЛОКИРОВАНА: Спред ({current_spread_price:.5f}) > 2.5 * FairValue ({fair_spread:.5f}).")
            return None
        # --------------------------------------------

        # --- TZ 1.3: TWAP/VWAP для Крупных Лотов ---
        if lot_size >= self.min_lot_for_twap:
            return await self._execute_twap(
                symbol, signal.type, lot_size, stop_loss_in_price, timeframe, strategy_name, df,
                entry_price_for_learning
            )
        # ----------------------------------------------

        # --- TZ 1.1: Адаптивный Taker/Maker (Limit-to-Market) ---
        normalized_atr_percent = (df['ATR_14'].iloc[-1] / df['close'].iloc[-1]) * \
            100 if 'ATR_14' in df.columns and df['close'].iloc[-1] > 0 else 1.0
        is_low_volatility = normalized_atr_percent < 0.15
        is_tight_spread = symbol_info.point is not None and current_spread_price < 1.5 * \
            symbol_info.point

        if is_low_volatility and is_tight_spread:
            logger.info(f"[{symbol}] Адаптивный вход: Maker (Limit Order).")
            position_ticket = await self._try_limit_entry_async(
                symbol, signal.type, lot_size, stop_loss_in_price, tick, symbol_info.digits, strategy_name, timeframe,
                symbol_info
            )
            if position_ticket:
                # Успешное исполнение Limit ордера
                self._persist_entry_data(position_ticket, symbol, strategy_name, stop_loss_in_price, prediction_input,
                                         prediction_input, entry_price_for_learning, df.index[-1], timeframe, df, signal.predicted_price)
                return position_ticket
            else:
                logger.warning(
                    f"[{symbol}] Limit-to-Market не сработал. Переход к Market Order.")

        # --- 6. Market Order (Taker) - Fallback ---
        logger.info(f"[{symbol}] Адаптивный вход: Taker (Market Order).")
        return await self._execute_market_order(
            symbol, signal.type, lot_size, stop_loss_in_price, timeframe, strategy_name, df, entry_price_for_learning
        )

    async def _try_limit_entry_async(self, symbol: str, signal_type: SignalType, lot: float, stop_loss_in_price: float,
                                     tick: Any, digits: int, strategy_name: str, timeframe: int, symbol_info: Any) -> \
            Optional[int]:
        """
        Асинхронная попытка входа лимитным ордером.
        """
        # ЗАЩИТА: Проверка symbol_info.point
        if symbol_info is None or symbol_info.point is None or symbol_info.point <= 0:
            logger.error(
                f"[{symbol}] _try_limit_entry_async: Invalid symbol_info.point={symbol_info.point if symbol_info else None}")
            return None

        connector = self.risk_engine.trading_system.terminal_connector

        # 1. Расчет цен для Limit ордера
        limit_offset_pips = 1.0  # Небольшой офсет в 1 пипс для Maker
        limit_offset_price = limit_offset_pips * symbol_info.point

        if signal_type == SignalType.BUY:
            limit_price = tick.bid - limit_offset_price
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
        else:
            limit_price = tick.ask + limit_offset_price
            order_type = mt5.ORDER_TYPE_SELL_LIMIT

        # Расчет SL/TP
        sl = limit_price - \
            stop_loss_in_price if signal_type == SignalType.BUY else limit_price + stop_loss_in_price
        tp = limit_price + (
            stop_loss_in_price * self.config.RISK_REWARD_RATIO) if signal_type == SignalType.BUY else limit_price - (
            stop_loss_in_price * self.config.RISK_REWARD_RATIO)

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": round(limit_price, digits),
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "deviation": 20,
            "magic": 202407,
            "comment": f"GNS-Limit-{self.risk_engine.trading_system._get_timeframe_str(timeframe)}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        # 2. Отправка ордера (синхронно под локом)
        order_ticket = None
        with self.mt5_lock:
            if connector.initialize(path=self.config.MT5_PATH):
                try:
                    result = connector.order_send(request)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        order_ticket = result.order
                        # Инициализируем историю для отслеживания повторного входа
                        if not hasattr(self.risk_engine.trading_system, 'trade_history'):
                            self.risk_engine.trading_system.trade_history = {}
                        self.risk_engine.trading_system.trade_history[symbol] = {
                            'last_profit_pct': 0,
                            'last_trade_time': datetime.now(),
                            'last_outcome': 'open'
                        }
                    else:
                        logger.warning(
                            f"[{symbol}] Не удалось выставить Limit ордер: {result.comment if result else 'Unknown'}")
                finally:
                    connector.shutdown()

        if not order_ticket:
            return None

        # 3. Асинхронное ожидание исполнения
        start_time = standard_time.time()
        while (standard_time.time() - start_time) < self.limit_wait_seconds:
            await asyncio.sleep(0.5)

            with self.mt5_lock:
                if connector.initialize(path=self.config.MT5_PATH):
                    try:
                        positions = connector.get_positions(symbol=symbol)
                        for pos in positions:
                            if pos.order == order_ticket:
                                logger.critical(
                                    f"[{symbol}] Limit ордер #{order_ticket} ИСПОЛНЕН! Position: {pos.ticket}")
                                return pos.ticket

                        hist_orders = connector.get_history_orders(
                            ticket=order_ticket)
                        if hist_orders:
                            state = hist_orders[0].state
                            if state in [mt5.ORDER_STATE_CANCELED, mt5.ORDER_STATE_EXPIRED]:
                                logger.warning(
                                    f"[{symbol}] Limit ордер #{order_ticket} был отменен/истек.")
                                return None
                    finally:
                        connector.shutdown()
                else:
                    await asyncio.sleep(1)  # Пауза при ошибке подключения

        # 4. Отмена ордера при тайм-ауте
        with self.mt5_lock:
            if connector.initialize(path=self.config.MT5_PATH):
                connector.order_send(
                    {"action": mt5.TRADE_ACTION_REMOVE, "order": order_ticket, "magic": 202407})
                connector.shutdown()

        return None

    def _try_limit_entry(self, connector, symbol: str, signal_type: SignalType, lot: float, stop_loss_in_price: float,
                         tick, digits: int, strategy_name: str, timeframe: int) -> Optional[int]:

        if signal_type == SignalType.BUY:
            limit_price = tick.bid
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
            sl = limit_price - stop_loss_in_price
            tp = limit_price + (stop_loss_in_price *
                                self.config.RISK_REWARD_RATIO)
        else:
            limit_price = tick.ask
            order_type = mt5.ORDER_TYPE_SELL_LIMIT
            sl = limit_price + stop_loss_in_price
            tp = limit_price - (stop_loss_in_price *
                                self.config.RISK_REWARD_RATIO)

        comment = f"GNS-Limit-{self.risk_engine.trading_system._get_timeframe_str(timeframe)}"

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": round(limit_price, digits),
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "deviation": 20,
            "magic": 202407,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        # Используем connector
        result = connector.order_send(request)

        if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning(
                f"[{symbol}] Не удалось выставить Limit ордер: {result.comment if result else 'Unknown'}")
            return None

        order_ticket = result.order
        logger.info(
            f"[{symbol}] Limit ордер #{order_ticket} выставлен по {limit_price}. Ждем {self.limit_wait_seconds} сек...")

        # Ожидание исполнения (используем connector для проверки)
        start_time = time.time()
        while (time.time() - start_time) < self.limit_wait_seconds:

            # Если это симулятор, мы не можем просто спать, время не идет.
            # В симуляторе лимитник либо исполнился сразу (если цена позволяет), либо висит.
            # Для простоты в симуляторе сразу возвращаем None, если не исполнился.
            if hasattr(connector, 'is_simulation') and connector.is_simulation:
                # Проверяем, есть ли позиция с таким тикетом (в симуляторе order_ticket = position_ticket)
                # Но лучше просто вернуть None, чтобы сработал Market Order
                return None

            orders = connector.get_orders(ticket=order_ticket)

            # Если ордер исчез из списка активных
            if not orders:
                hist_orders = connector.get_history_orders(ticket=order_ticket)
                if hist_orders:
                    state = hist_orders[0].state
                    if state == mt5.ORDER_STATE_FILLED or state == mt5.ORDER_STATE_PARTIAL:
                        logger.info(
                            f"[{symbol}] Limit ордер #{order_ticket} ИСПОЛНЕН!")
                        deal_id = hist_orders[0].deal
                        return self._wait_for_position_id(connector, deal_id)
                    elif state == mt5.ORDER_STATE_CANCELED:
                        logger.warning(
                            f"[{symbol}] Limit ордер #{order_ticket} был отменен.")
                        return None
                return None

            time.sleep(1)

        # Тайм-аут: Отмена ордера через connector
        logger.info(
            f"[{symbol}] Тайм-аут Limit ордера #{order_ticket}. Отмена...")
        cancel_request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": order_ticket,
            "magic": 202407,
        }
        connector.order_send(cancel_request)
        return None

    def _wait_for_position_id(self, connector, deal_id: int) -> int:
        """Ожидает появления позиции в истории сделок."""

        # Упрощение: в симуляторе позиция создается мгновенно и deal_id = position_id
        if hasattr(connector, 'is_simulation') and connector.is_simulation:
            return deal_id

        for i in range(20):
            # Используем метод с тикетом, если это реальный MT5 (через проверку типа или try/except)
            # Но наш интерфейс ITerminalConnector определяет get_history_deals(date_from, date_to, ticket=None)
            try:
                deals = connector.get_history_deals(
                    date_from=None, date_to=None, ticket=deal_id)
                if deals and len(deals) > 0 and deals[0].position_id > 0:
                    return deals[0].position_id
            except Exception:
                pass

            time.sleep(0.1)
        return 0

    def _send_order_with_retry(self, connector, request):
        if request is None:
            return None, None

        check_result = connector.order_check(request)
        if check_result and check_result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.info(
                f"Результат order_check для {request['symbol']} не 'DONE': {check_result.comment}")

        result = connector.order_send(request)
        return result, check_result

    def _build_request(self, symbol, lot, signal_type, price, sl, tp, timeframe, strategy_name, digits):
        # type_map = {SignalType.BUY: mt5.ORDER_TYPE_BUY,
        #            SignalType.SELL: mt5.ORDER_TYPE_SELL}
        
        # Поддержка как объектов SignalType, так и строк
        type_map = {
            SignalType.BUY: mt5.ORDER_TYPE_BUY,
            SignalType.SELL: mt5.ORDER_TYPE_SELL,
            'BUY': mt5.ORDER_TYPE_BUY,      # <-- Добавлена поддержка строк
            'SELL': mt5.ORDER_TYPE_SELL,    # <-- Добавлена поддержка строк
        }
        
        # Конвертируем numpy типы в Python float для MT5
        return {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(lot),
            "type": type_map[signal_type], "price": float(round(price, digits)), "sl": float(round(sl, digits)),
            "tp": float(round(tp, digits)),
            "deviation": 20, "magic": 202407, "comment": "GNS-Market", "type_time": mt5.ORDER_TIME_GTC,
        }

    def _persist_entry_data(self, pos_id, symbol, strategy, sl, xai, pred_in, entry_price, entry_time, timeframe, df, predicted_price=None):
        # Конвертируем entry_time в datetime если это pandas Timestamp
        if hasattr(entry_time, 'to_pydatetime'):
            entry_time = entry_time.to_pydatetime()

        logger.info(
            f"[{symbol}] Сохранение данных входа: ticket={pos_id}, entry_time={entry_time}, timeframe={timeframe}")

        market_context = {
            'market_regime': self.risk_engine.trading_system.market_regime_manager.get_regime(df),
            'news_sentiment': self.risk_engine.trading_system.news_cache.aggregated_sentiment if self.risk_engine.trading_system.news_cache else None,
        }
        entry_data = {
            "symbol": symbol, "strategy": strategy, "stop_loss_price": sl,
            "prediction_input_sequence": pred_in.tolist() if isinstance(pred_in, np.ndarray) else pred_in,
            "entry_price_for_learning": entry_price,
            "predicted_price_at_entry": predicted_price,
            "entry_bar_time": entry_time, "entry_timeframe": timeframe, "market_context": market_context
        }
        self.portfolio_service.add_trade_entry_data(pos_id, entry_data)

    def _log_order_error(self, symbol, result, check_result):
        retcode = result.retcode if result else "N/A"
        comment = result.comment if result else "N/A"
        check_comment = check_result.comment if check_result else "N/A"
        logger.error(
            f"Не удалось исполнить ордер для {symbol}. Код: {retcode}, Комментарий: {comment}, Проверка: {check_comment}")
        if self.risk_engine.trading_system.sound_manager:
            self.risk_engine.trading_system.sound_manager.play("error")

    def _emergency_close_position_internal(self, ticket: int):
        # Используем connector
        connector = self.risk_engine.trading_system.terminal_connector

        positions = connector.get_positions(ticket=ticket)
        if not positions:
            logger.error(f"Не удалось найти позицию #{ticket} для закрытия.")
            return

        pos = positions[0]
        tick = connector.symbol_info_tick(pos.symbol)
        if not tick:
            logger.error(f"Не удалось получить тик для {pos.symbol}.")
            return

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
            "position": pos.ticket,
            "price": tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask,
            "deviation": 20,
            "magic": 202407,
            "comment": "Emergency Close",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = connector.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                f"Команда на закрытие позиции #{ticket} успешно отправлена.")
            # Записываем исход сделки для контроля повторного входа
            self._track_trade_outcome(pos.symbol, pos.profit)
        else:
            logger.error(
                f"Не удалось закрыть позицию #{ticket}: {result.comment if result else 'Unknown error'}")

    def _track_trade_outcome(self, symbol: str, profit: float):
        """Записывает исход сделки для контроля повторного входа."""
        trading_system = self.risk_engine.trading_system

        # Определяем исход
        if profit is None:
            logger.warning(
                f"[{symbol}] profit is None. Пропуск записи исхода.")
            return
        if profit > 0:
            outcome = 'profit'
        elif profit < 0:
            outcome = 'loss'
        else:
            outcome = 'breakeven'

        # Записываем в историю
        if not hasattr(trading_system, 'trade_history'):
            trading_system.trade_history = {}

        trading_system.trade_history[symbol] = {
            'last_profit_pct': profit,
            'last_trade_time': datetime.now(),
            'last_outcome': outcome
        }

        logger.info(
            f"[{symbol}] Исход сделки записан: {outcome}, прибыль: {profit:.2f}")

    def emergency_close_position(self, ticket: int):
        logger.info(
            f"Запуск экстренного закрытия для одной позиции #{ticket}.")
        connector = self.risk_engine.trading_system.terminal_connector

        with self.mt5_lock:
            if not connector.initialize(path=self.config.MT5_PATH):
                logger.error(
                    "Не удалось подключиться к MT5 для закрытия позиции.")
                return
            try:
                self._emergency_close_position_internal(ticket)
            finally:
                connector.shutdown()

    def emergency_close_all_positions(self):
        logger.warning("Запуск экстренного закрытия ВСЕХ позиций.")
        connector = self.risk_engine.trading_system.terminal_connector
        positions_to_close = []

        with self.mt5_lock:
            if connector.initialize(path=self.config.MT5_PATH):
                try:
                    positions = connector.get_positions()
                    if positions:
                        positions_to_close = [pos.ticket for pos in positions]
                finally:
                    connector.shutdown()

        if not positions_to_close:
            logger.info("Нет открытых позиций для закрытия.")
            return

        logger.info(
            f"Обнаружено {len(positions_to_close)} позиций для закрытия. Начинаю процесс...")
        for ticket in positions_to_close:
            self.emergency_close_position(ticket)
            time.sleep(0.5)
            logger.info("Процесс закрытия всех позиций завершен.")

    def close_position_partial(self, position: Any):
        connector = self.risk_engine.trading_system.terminal_connector
        with self.mt5_lock:
            if not connector.initialize(path=self.config.MT5_PATH):
                return
            try:
                symbol_info = connector.symbol_info(position.symbol)
                if not symbol_info:
                    return

                close_volume = round(position.volume / 2, 2)
                if close_volume < symbol_info.volume_min:
                    return

                tick = connector.symbol_info_tick(position.symbol)
                if not tick:
                    return

                request = {
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": position.symbol, "volume": close_volume,
                    "type": mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                    "position": position.ticket, "price": tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask,
                    "deviation": 20, "magic": 202407, "comment": "Partial Close RL",
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                self._send_order_with_retry(connector, request)
            finally:
                connector.shutdown()

    def modify_position_sltp(self, ticket: int, new_sl: float, new_tp: float):
        connector = self.risk_engine.trading_system.terminal_connector
        with self.mt5_lock:
            if not connector.initialize(path=self.config.MT5_PATH):
                return
            try:
                request = {"action": mt5.TRADE_ACTION_SLTP,
                           "position": ticket, "sl": new_sl, "tp": new_tp}
                connector.order_send(request)
            finally:
                connector.shutdown()

    def modify_position_sltp_to_be(self, ticket: int, entry_price: float):
        """
        Переводит Stop Loss в безубыток (Break Even) с небольшим буфером.
        """
        connector = self.risk_engine.trading_system.terminal_connector

        with self.mt5_lock:
            if not connector.initialize(path=self.config.MT5_PATH):
                return
            try:
                positions = connector.get_positions(ticket=ticket)
                if not positions:
                    logger.warning(
                        f"Не удалось найти позицию #{ticket} для перевода в БУ.")
                    return

                pos = positions[0]
                symbol_info = connector.symbol_info(pos.symbol)
                if not symbol_info:
                    return

                # Буфер: 1 пипс (для покрытия комиссии/свопа)
                buffer_pips = 1.0
                buffer_price = buffer_pips * symbol_info.point

                # Новый SL: Цена открытия + буфер (для BUY) или Цена открытия - буфер (для SELL)
                if pos.type == mt5.ORDER_TYPE_BUY:
                    new_sl = entry_price + buffer_price
                else:  # SELL
                    new_sl = entry_price - buffer_price

                # Округляем до точности символа
                new_sl = round(new_sl, symbol_info.digits)

                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": ticket,
                    "sl": new_sl,
                    "tp": pos.tp,  # TP остается прежним
                    "magic": 202407,
                }

                result = connector.order_send(request)

                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.critical(
                        f"!!! SL to BE: Позиция #{ticket} переведена в безубыток ({new_sl:.{symbol_info.digits}f})!")
                else:
                    logger.error(
                        f"Не удалось перевести SL в БУ для #{ticket}: {result.comment if result else 'Unknown'}")

            finally:
                connector.shutdown()
