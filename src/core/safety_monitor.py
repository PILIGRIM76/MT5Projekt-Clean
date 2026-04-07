# src/core/safety_monitor.py
"""
CRITICAL SAFETY MONITOR
Continuously monitors system health and triggers emergency stops.

Защита от катастрофических потерь на реальном счёте.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class SafetyMonitor:
    """
    Monitors trading system for dangerous conditions and triggers emergency stops.

    Автоматически останавливает торговлю при:
    - Дневной просадке > 3%
    - Просадке от пика > 5%
    - 5 убыточных сделках подряд
    """

    def __init__(self, config, trading_system):
        self.config = config
        self.trading_system = trading_system

        # Safety thresholds (КРИТИЧЕСКИЕ ПОРОГИ)
        self.max_daily_loss_percent = 3.0  # CRITICAL: Stop at 3% daily loss
        self.max_consecutive_losses = 5
        self.max_drawdown_from_peak = 5.0

        # State tracking
        self.session_start_balance = 0.0
        self.peak_equity = 0.0
        self.consecutive_losses = 0
        self.emergency_stop_triggered = False
        self.last_check_time = datetime.now()

    def initialize(self):
        """Initialize monitoring at system start"""
        logger.critical("[SAFETY] 🔒 Начало инициализации Safety Monitor...")
        try:
            from src.core.mt5_connection_manager import mt5_ensure_connected, mt5_initialize

            with self.trading_system.mt5_lock:
                # Безопасная обработка MT5_LOGIN
                try:
                    mt5_login = int(self.config.MT5_LOGIN) if self.config.MT5_LOGIN else None
                except (ValueError, TypeError) as e:
                    logger.error(f"[SAFETY] Некорректный MT5_LOGIN: {self.config.MT5_LOGIN}, ошибка: {e}")
                    mt5_login = None

                # Мягкая инициализация - не требует логина/пароля если уже подключен
                if not mt5_ensure_connected(path=self.config.MT5_PATH):
                    # Пробуем полную инициализацию
                    logger.warning("[SAFETY] Мягкая инициализация не удалась, пробуем полную...")
                    if not mt5_initialize(
                        path=self.config.MT5_PATH,
                        login=mt5_login,
                        password=self.config.MT5_PASSWORD,
                        server=self.config.MT5_SERVER,
                    ):
                        logger.error("[SAFETY] ❌ Не удалось инициализировать MT5 для Safety Monitor")
                        logger.error("[SAFETY] ⚠️ Safety Monitor будет работать БЕЗ защиты!")
                        return

                account_info = mt5.account_info()
                if account_info:
                    self.session_start_balance = account_info.balance
                    self.peak_equity = account_info.equity
                    logger.critical(f"[SAFETY] ✅ Monitoring initialized. Start balance: ${self.session_start_balance:,.2f}")
                    logger.critical(f"[SAFETY] Emergency stop triggers:")
                    logger.critical(f"[SAFETY]   - Daily loss > {self.max_daily_loss_percent}%")
                    logger.critical(f"[SAFETY]   - Drawdown from peak > {self.max_drawdown_from_peak}%")
                    logger.critical(f"[SAFETY]   - Consecutive losses > {self.max_consecutive_losses}")
                else:
                    logger.error("[SAFETY] ❌ Не удалось получить информацию об аккаунте")
        except Exception as e:
            logger.error(f"[SAFETY] ❌ Ошибка инициализации: {e}", exc_info=True)

    def check_safety_conditions(self) -> bool:
        """
        CRITICAL: Check if trading should continue.
        Returns False if emergency stop is triggered.

        Вызывается перед каждым торговым циклом.
        """
        if self.emergency_stop_triggered:
            return False

        # Проверяем не чаще раза в 10 секунд (оптимизация)
        now = datetime.now()
        if (now - self.last_check_time).total_seconds() < 10:
            return True
        self.last_check_time = now

        # Кэшируем данные аккаунта — не вызываем initialize() каждый раз
        # Используем данные из мониторинг-потока который уже подключён
        try:
            with self.trading_system.mt5_lock:
                # Оптимизация: не вызываем initialize() — пробуем сразу account_info()
                account_info = mt5.account_info()
                if not account_info:
                    # Пробуем инициализацию только если account_info вернул None
                    if not mt5.initialize(path=self.config.MT5_PATH):
                        return True  # Не блокируем торговлю из-за ошибки подключения
                    account_info = mt5.account_info()
                    if not account_info:
                        return True

                current_equity = account_info.equity
                current_balance = account_info.balance

                # Update peak equity
                if current_equity > self.peak_equity:
                    self.peak_equity = current_equity

                # Check 1: Daily loss limit
                daily_loss = self.session_start_balance - current_balance
                daily_loss_percent = (daily_loss / self.session_start_balance) * 100 if self.session_start_balance > 0 else 0

                if daily_loss_percent > self.max_daily_loss_percent:
                    self._trigger_emergency_stop(
                        f"Daily loss {daily_loss_percent:.2f}% exceeds limit {self.max_daily_loss_percent}%"
                    )
                    return False

                # Check 2: Drawdown from peak
                drawdown_from_peak = (
                    ((self.peak_equity - current_equity) / self.peak_equity) * 100 if self.peak_equity > 0 else 0
                )

                if drawdown_from_peak > self.max_drawdown_from_peak:
                    self._trigger_emergency_stop(
                        f"Drawdown from peak {drawdown_from_peak:.2f}% exceeds limit {self.max_drawdown_from_peak}%"
                    )
                    return False

                # Check 3: Consecutive losses
                if self.consecutive_losses >= self.max_consecutive_losses:
                    self._trigger_emergency_stop(
                        f"Consecutive losses {self.consecutive_losses} exceeds limit {self.max_consecutive_losses}"
                    )
                    return False

                # Логируем статус каждые 5 минут
                if now.minute % 5 == 0 and now.second < 15:
                    logger.info(
                        f"[SAFETY] Status OK: Daily Loss={daily_loss_percent:.2f}%, DD from Peak={drawdown_from_peak:.2f}%, Consecutive Losses={self.consecutive_losses}"
                    )

                return True

        except Exception as e:
            logger.error(f"[SAFETY] Ошибка проверки условий: {e}", exc_info=True)
            return True  # Не блокируем торговлю из-за ошибки

    def record_trade_result(self, profit: float):
        """Record trade result for consecutive loss tracking"""
        if profit < 0:
            self.consecutive_losses += 1
            logger.warning(f"[SAFETY] Consecutive losses: {self.consecutive_losses}/{self.max_consecutive_losses}")
        else:
            if self.consecutive_losses > 0:
                logger.info(f"[SAFETY] Winning trade - consecutive losses reset from {self.consecutive_losses} to 0")
            self.consecutive_losses = 0

    def _trigger_emergency_stop(self, reason: str):
        """
        CRITICAL: Trigger emergency stop and close all positions.
        """
        self.emergency_stop_triggered = True

        logger.critical("=" * 80)
        logger.critical("!!! EMERGENCY STOP TRIGGERED !!!")
        logger.critical(f"Reason: {reason}")
        logger.critical("=" * 80)

        # Close all positions
        try:
            if self.trading_system.execution_service:
                logger.critical("[SAFETY] Closing all positions...")
                self.trading_system.execution_service.emergency_close_all_positions()
        except Exception as e:
            logger.error(f"[SAFETY] Ошибка закрытия позиций: {e}", exc_info=True)

        # Stop trading system
        try:
            logger.critical("[SAFETY] Stopping trading system...")
            self.trading_system.stop_event.set()
        except Exception as e:
            logger.error(f"[SAFETY] Ошибка остановки системы: {e}", exc_info=True)

        # Send alert to GUI
        try:
            if self.trading_system.gui:
                self.trading_system._safe_gui_update("update_status", f"⛔ EMERGENCY STOP: {reason}", is_error=True)

                # Play error sound
                if self.trading_system.sound_manager:
                    self.trading_system.sound_manager.play("error")
        except Exception as e:
            logger.error(f"[SAFETY] Ошибка отправки алерта в GUI: {e}", exc_info=True)

        logger.critical("[SAFETY] Emergency stop procedure completed.")
        logger.critical("[SAFETY] System will not resume trading until manually restarted.")
