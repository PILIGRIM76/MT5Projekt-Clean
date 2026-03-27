# src/risk/circuit_breaker.py
"""
Circuit Breaker System — Система аварийной остановки торговли.

Компонент для автоматической остановки торговли при обнаружении аномальных условий:
- Потеря связи с MT5
- Аномальный спред
- Высокая волатильность
- Ошибки исполнения ордеров
- Превышение дневного убытка

Состояния:
- CLOSED (нормальная работа)
- OPEN (торговля заблокирована)
- HALF_OPEN (проверка условий для возобновления)
"""

import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any
from threading import Lock

import MetaTrader5 as mt5
import pandas as pd
import numpy as np

from src.core.config_models import Settings
from src.data_models import SignalType

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Состояния Circuit Breaker."""
    CLOSED = "CLOSED"      # Нормальная работа, торговля разрешена
    OPEN = "OPEN"          # Торговля заблокирована
    HALF_OPEN = "HALF_OPEN"  # Проверка условий для возобновления


class CircuitBreakerReason(Enum):
    """Причины срабатывания Circuit Breaker."""
    MT5_CONNECTION_LOST = "MT5_CONNECTION_LOST"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    CONSECUTIVE_ERRORS = "CONSECUTIVE_ERRORS"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MANUAL_TRIGGER = "MANUAL_TRIGGER"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class CircuitBreakerTrip:
    """Запись о срабатывании Circuit Breaker."""
    
    def __init__(self, reason: CircuitBreakerReason, timestamp: datetime, 
                 context: Optional[Dict[str, Any]] = None):
        self.reason = reason
        self.timestamp = timestamp
        self.context = context or {}
        self.duration_seconds: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует в словарь для сериализации."""
        return {
            'reason': self.reason.value,
            'timestamp': self.timestamp.isoformat(),
            'duration_seconds': self.duration_seconds,
            'context': self.context
        }


class CircuitBreaker:
    """
    Система аварийной остановки торговли.
    
    Атрибуты:
        state: Текущее состояние Circuit Breaker
        trip_count: Количество срабатываний за сессию
        last_trip_time: Время последнего срабатывания
    """
    
    def __init__(self, config: Settings, trading_system_ref=None):
        """
        Инициализация Circuit Breaker.
        
        Args:
            config: Конфигурация системы
            trading_system_ref: Ссылка на TradingSystem для закрытия позиций
        """
        self.config = config
        self.trading_system = trading_system_ref
        
        # Конфигурация из settings
        cb_config = getattr(config, 'circuit_breaker', {})
        self.enabled = cb_config.get('enabled', True)
        self.mt5_timeout_seconds = cb_config.get('mt5_timeout_seconds', 30)
        self.spread_multiplier_threshold = cb_config.get('spread_multiplier_threshold', 5.0)
        self.volatility_threshold_percent = cb_config.get('volatility_threshold_percent', 2.0)
        self.volatility_window_minutes = cb_config.get('volatility_window_minutes', 5)
        self.max_consecutive_errors = cb_config.get('max_consecutive_errors', 3)
        self.daily_loss_threshold_percent = cb_config.get('daily_loss_threshold_percent', 5.0)
        self.auto_close_positions = cb_config.get('auto_close_positions', True)
        self.cooldown_minutes = cb_config.get('cooldown_minutes', 15)
        
        # Состояние
        self._state = CircuitBreakerState.CLOSED
        self._state_lock = Lock()
        
        # Счётчики и таймеры
        self.trip_count = 0
        self.last_trip_time: Optional[datetime] = None
        self.consecutive_errors = 0
        self.last_error_time: Optional[datetime] = None
        
        # История срабатываний
        self.trip_history: List[CircuitBreakerTrip] = []
        
        # Для расчёта среднего спреда
        self._spread_history: List[float] = []
        self._spread_history_max = 1000  # Максимум записей в истории
        self._last_spread_update: Optional[datetime] = None
        
        # Для расчёта дневного PnL
        self._session_start_balance: Optional[float] = None
        self._session_start_time: Optional[datetime] = None
        
        # Таймер cooldown
        self._cooldown_until: Optional[datetime] = None
        
        logger.info("Circuit Breaker инициализирован")
        logger.info(f"  - Enabled: {self.enabled}")
        logger.info(f"  - MT5 Timeout: {self.mt5_timeout_seconds}s")
        logger.info(f"  - Spread Threshold: {self.spread_multiplier_threshold}x")
        logger.info(f"  - Volatility Threshold: {self.volatility_threshold_percent}%")
        logger.info(f"  - Daily Loss Threshold: {self.daily_loss_threshold_percent}%")
    
    def initialize_session(self, initial_balance: float) -> None:
        """
        Инициализация новой торговой сессии.
        
        Args:
            initial_balance: Начальный баланс сессии
        """
        self._session_start_balance = initial_balance
        self._session_start_time = datetime.now()
        self._spread_history.clear()
        self.trip_count = 0
        self.consecutive_errors = 0
        self._state = CircuitBreakerState.CLOSED
        
        logger.info(f"Circuit Breaker сессия инициализирована. Баланс: {initial_balance}")
    
    @property
    def state(self) -> CircuitBreakerState:
        """Возвращает текущее состояние."""
        return self._state
    
    @property
    def is_trading_allowed(self) -> bool:
        """Проверяет, разрешена ли торговля."""
        if not self.enabled:
            return True
        
        with self._state_lock:
            if self._state == CircuitBreakerState.CLOSED:
                return True
            
            # Проверка cooldown для HALF_OPEN
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._cooldown_until and datetime.now() >= self._cooldown_until:
                    logger.info("Cooldown завершён, попытка возобновления торговли...")
                    if self.check_conditions():
                        self._reset_state()
                        return True
                return False
            
            return False
    
    def check_conditions(self) -> bool:
        """
        Проверка всех условий торговли.
        
        Returns:
            True если торговля безопасна, False иначе
        """
        if not self.enabled:
            return True
        
        checks = [
            ("MT5 Connection", self._check_mt5_connection),
            ("Spread Normal", self._check_spread_normal),
            ("Volatility Normal", self._check_volatility_normal),
            ("Errors Count", self._check_consecutive_errors),
            ("Daily Loss", self._check_daily_loss_limit),
        ]
        
        all_safe = True
        
        for check_name, check_func in checks:
            try:
                is_safe = check_func()
                if not is_safe:
                    logger.warning(f"Проверка '{check_name}' не пройдена!")
                    all_safe = False
            except Exception as e:
                logger.error(f"Ошибка при проверке '{check_name}': {e}")
                all_safe = False
        
        return all_safe
    
    def _check_mt5_connection(self) -> bool:
        """Проверка подключения к MT5."""
        try:
            # Проверяем последний известный статус
            if not mt5.last_error():
                return True
            
            # Пытаемся получить информацию о счёте
            with self._mt5_lock():
                account_info = mt5.account_info()
            
            if account_info is None:
                return False
            
            # Проверяем, что соединение активно
            return account_info.login > 0
            
        except Exception as e:
            logger.debug(f"MT5 connection check failed: {e}")
            return False
    
    def _check_spread_normal(self) -> bool:
        """Проверка аномального спреда."""
        try:
            # Получаем текущие спреды по активным символам
            if not self.trading_system:
                return True
            
            symbols = self.trading_system.config.SYMBOLS_WHITELIST[:5]  # Проверяем топ-5
            
            current_spreads = []
            for symbol in symbols:
                with self._mt5_lock():
                    tick = mt5.symbol_info_tick(symbol)
                
                if tick and tick.ask > 0 and tick.bid > 0:
                    spread = (tick.ask - tick.bid) / tick.bid * 10000  # В пунктах
                    current_spreads.append(spread)
                    
                    # Обновляем историю
                    self._update_spread_history(spread)
            
            if not current_spreads or not self._spread_history:
                return True
            
            # Вычисляем средний спред за историю
            avg_spread = np.mean(self._spread_history)
            max_current_spread = max(current_spreads)
            
            # Проверяем порог
            if avg_spread > 0 and max_current_spread > avg_spread * self.spread_multiplier_threshold:
                logger.warning(
                    f"Аномальный спред обнаружен! "
                    f"Текущий: {max_current_spread:.2f}, Средний: {avg_spread:.2f}"
                )
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Spread check failed: {e}")
            return True  # Разрешаем торговлю при ошибке проверки
    
    def _check_volatility_normal(self) -> bool:
        """Проверка аномальной волатильности."""
        try:
            if not self.trading_system:
                return True
            
            symbols = self.trading_system.config.SYMBOLS_WHITELIST[:3]  # Проверяем топ-3
            
            for symbol in symbols:
                # Получаем данные за последние N минут
                with self._mt5_lock():
                    rates = mt5.copy_rates_from_pos(
                        symbol, 
                        mt5.TIMEFRAME_M1,
                        0,
                        self.volatility_window_minutes
                    )
                
                if rates is None or len(rates) < 2:
                    continue
                
                df = pd.DataFrame(rates)
                
                # Вычисляем изменение цены за окно
                price_change = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
                
                if abs(price_change) > self.volatility_threshold_percent:
                    logger.warning(
                        f"Высокая волатильность на {symbol}! "
                        f"Изменение: {price_change:.2f}% за {self.volatility_window_minutes} мин"
                    )
                    return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Volatility check failed: {e}")
            return True
    
    def _check_consecutive_errors(self) -> bool:
        """Проверка количества последовательных ошибок."""
        # Сбрасываем счётчик если прошло достаточно времени
        if self.last_error_time:
            time_since_error = (datetime.now() - self.last_error_time).total_seconds()
            if time_since_error > 60:  # 1 минута без ошибок
                self.consecutive_errors = 0
        
        return self.consecutive_errors < self.max_consecutive_errors
    
    def _check_daily_loss_limit(self) -> bool:
        """Проверка дневного лимита убытка."""
        if not self._session_start_balance or not self.trading_system:
            return True
        
        try:
            # Получаем текущий баланс и equity
            with self._mt5_lock():
                account_info = mt5.account_info()
            
            if account_info is None:
                return True
            
            current_equity = account_info.equity
            daily_loss = self._session_start_balance - current_equity
            daily_loss_percent = (daily_loss / self._session_start_balance) * 100
            
            if daily_loss_percent > self.daily_loss_threshold_percent:
                logger.critical(
                    f"Дневной лимит убытка превышен! "
                    f"Убыток: {daily_loss:.2f} ({daily_loss_percent:.2f}%), "
                    f"Лимит: {self.daily_loss_threshold_percent}%"
                )
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Daily loss check failed: {e}")
            return True
    
    def trip(self, reason: CircuitBreakerReason, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Срабатывание Circuit Breaker.
        
        Args:
            reason: Причина срабатывания
            context: Дополнительный контекст
        """
        with self._state_lock:
            previous_state = self._state
            self._state = CircuitBreakerState.OPEN
            
            self.trip_count += 1
            self.last_trip_time = datetime.now()
            
            # Создаём запись о срабатывании
            trip = CircuitBreakerTrip(
                reason=reason,
                timestamp=self.last_trip_time,
                context=context
            )
            self.trip_history.append(trip)
            
            logger.critical(
                f"🚨 CIRCUIT BREAKER СРАБОТАЛ! "
                f"Причина: {reason.value}, "
                f"Срабатываний за сессию: {self.trip_count}"
            )
            
            # Автоматическое закрытие позиций
            if self.auto_close_positions and self.trading_system:
                logger.critical("Автоматическое закрытие всех позиций...")
                self._close_all_positions()
            
            # Блокировка на cooldown
            self._cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
            
            # Отправка уведомления (если есть AlertManager)
            if hasattr(self.trading_system, 'alert_manager'):
                self.trading_system.alert_manager.send_alert(
                    level='CRITICAL',
                    message=f"🚨 Circuit Breaker сработал: {reason.value}",
                    context=context
                )
            
            # Тройное срабатывание — полная остановка
            if self.trip_count >= 3:
                logger.critical("🚨 Тройное срабатывание! Полная остановка системы.")
                self._emergency_shutdown()
    
    def _close_all_positions(self) -> None:
        """Закрывает все открытые позиции."""
        if not self.trading_system:
            return
        
        try:
            with self._mt5_lock():
                positions = mt5.positions_get()
            
            if not positions:
                return
            
            for position in positions:
                try:
                    # Закрываем позицию
                    if position.type == mt5.POSITION_TYPE_BUY:
                        order_type = mt5.ORDER_TYPE_SELL
                    else:
                        order_type = mt5.ORDER_TYPE_BUY
                    
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": position.symbol,
                        "volume": position.volume,
                        "type": order_type,
                        "position": position.ticket,
                        "magic": position.magic,
                        "comment": "Circuit Breaker Close",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                    
                    with self._mt5_lock():
                        result = mt5.order_send(request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        logger.info(f"Позиция {position.ticket} ({position.symbol}) закрыта")
                    else:
                        logger.error(f"Ошибка закрытия позиции {position.ticket}: {result}")
                        
                except Exception as e:
                    logger.error(f"Ошибка при закрытии позиции {position.ticket}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка при закрытии всех позиций: {e}")
    
    def _emergency_shutdown(self) -> None:
        """Аварийная остановка системы."""
        if self.trading_system:
            try:
                # Останавливаем торговлю
                self.trading_system.running = False
                logger.critical("Торговая система остановлена")
            except Exception as e:
                logger.error(f"Ошибка при аварийной остановке: {e}")
    
    def reset(self) -> None:
        """Сброс Circuit Breaker в состояние CLOSED."""
        with self._state_lock:
            previous_state = self._state
            self._state = CircuitBreakerState.CLOSED
            self._cooldown_until = None
            
            logger.info(f"Circuit Breaker сброшен: {previous_state.value} → CLOSED")
            
            # Уведомление
            if hasattr(self.trading_system, 'alert_manager'):
                self.trading_system.alert_manager.send_alert(
                    level='INFO',
                    message="✅ Circuit Breaker сброшен, торговля возобновлена"
                )
    
    def _reset_state(self) -> None:
        """Внутренний сброс состояния (без уведомлений)."""
        self._state = CircuitBreakerState.CLOSED
        self._cooldown_until = None
    
    def record_error(self) -> None:
        """Записывает ошибку исполнения."""
        self.consecutive_errors += 1
        self.last_error_time = datetime.now()
        
        logger.warning(f"Записана ошибка исполнения. Всего: {self.consecutive_errors}")
        
        # Проверяем, не превышен ли лимит
        if self.consecutive_errors >= self.max_consecutive_errors:
            self.trip(
                CircuitBreakerReason.CONSECUTIVE_ERRORS,
                context={'error_count': self.consecutive_errors}
            )
    
    def _update_spread_history(self, spread: float) -> None:
        """Обновляет историю спредов."""
        self._spread_history.append(spread)
        
        # Ограничиваем размер истории
        if len(self._spread_history) > self._spread_history_max:
            self._spread_history = self._spread_history[-self._spread_history_max:]
    
    def _mt5_lock(self):
        """Возвращает контекстный менеджер для блокировки MT5."""
        if self.trading_system and hasattr(self.trading_system, 'mt5_lock'):
            return self.trading_system.mt5_lock
        else:
            # Fallback — простой контекстный менеджер
            from contextlib import contextmanager
            
            @contextmanager
            def null_lock():
                yield
            
            return null_lock()
    
    def get_status(self) -> Dict[str, Any]:
        """
        Возвращает текущий статус Circuit Breaker.
        
        Returns:
            Словарь со статусом и статистикой
        """
        return {
            'state': self._state.value,
            'is_trading_allowed': self.is_trading_allowed,
            'trip_count': self.trip_count,
            'last_trip_time': self.last_trip_time.isoformat() if self.last_trip_time else None,
            'consecutive_errors': self.consecutive_errors,
            'cooldown_until': self._cooldown_until.isoformat() if self._cooldown_until else None,
            'avg_spread': np.mean(self._spread_history) if self._spread_history else 0,
            'session_start_balance': self._session_start_balance,
            'session_start_time': self._session_start_time.isoformat() if self._session_start_time else None,
        }
    
    def get_trip_history(self) -> List[Dict[str, Any]]:
        """Возвращает историю срабатываний."""
        return [trip.to_dict() for trip in self.trip_history]
