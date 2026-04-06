# src/core/account_manager.py
"""
Account Manager — Автоопределение типа счета и адаптация рисков.

Функции:
- Определение типа счета (DEMO, CONTEST, REAL)
- Адаптивный расчет риска в зависимости от баланса
- Проверка доступной маржи перед торговлей
"""

import logging
from typing import Dict, Optional
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

class AccountType:
    DEMO = "DEMO"
    CONTEST = "CONTEST"
    REAL = "REAL"
    UNKNOWN = "UNKNOWN"

class AccountManager:
    def __init__(self):
        self.account_type = AccountType.UNKNOWN
        self.balance = 0.0
        self.equity = 0.0
        self.currency = "USD"
        self.leverage = 0
        self.margin_free = 0.0

    def update_info(self) -> bool:
        """Обновляет информацию о счете и определяет его тип."""
        acc = mt5.account_info()
        if acc is None:
            logger.error("[AccountManager] Не удалось получить info о счете")
            return False

        self.balance = acc.balance
        self.equity = acc.equity
        self.currency = acc.currency
        self.leverage = acc.leverage
        self.margin_free = acc.margin_free

        # Определение типа счета
        trade_mode = acc.trade_mode
        if trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            self.account_type = AccountType.DEMO
        elif trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            self.account_type = AccountType.CONTEST
        elif trade_mode in [mt5.ACCOUNT_TRADE_MODE_REAL, mt5.ACCOUNT_TRADE_MODE_MARGINAL]:
            self.account_type = AccountType.REAL
        else:
            self.account_type = AccountType.UNKNOWN

        logger.info(f"[AccountManager] Счет: {self.account_type} | Баланс: {self.balance} {self.currency} | Плечо: 1:{self.leverage}")
        return True

    def get_adaptive_risk_percent(self) -> float:
        """
        Рассчитывает % риска на сделку в зависимости от размера счета.
        Маленькие счета требуют большего %, чтобы преодолеть порог мин. лота (0.01).
        Большие счета требуют меньшего % для безопасности.
        """
        if self.balance < 100:
            return 2.0  # Для микро-счетов риск выше, чтобы открылся лот 0.01
        elif self.balance < 500:
            return 1.0
        elif self.balance < 2000:
            return 0.5
        elif self.balance < 10000:
            return 0.2
        else:
            return 0.1  # Для крупных счетов риск минимальный

    def can_afford_lot(self, symbol: str, lot: float) -> bool:
        """Проверяет, хватает ли свободной маржи на открытие лота."""
        # Упрощенная проверка: берем маржу для 1.0 лота и умножаем
        margin_req = mt5.symbol_info(symbol).margin_initial if mt5.symbol_info(symbol) else 0
        required_margin = margin_req * lot
        
        if self.margin_free < required_margin:
            logger.warning(f"[AccountManager] Недостаточно маржи для {symbol} ({lot} лотов). Нужно: {required_margin}, Есть: {self.margin_free}")
            return False
        return True

    def adjust_lot_for_min(self, symbol: str, calculated_lot: float) -> float:
        """Корректирует лот до минимально допустимого брокером."""
        if calculated_lot <= 0:
            return 0.0
        
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return 0.0

        min_lot = sym_info.volume_min
        lot_step = sym_info.volume_step

        if calculated_lot < min_lot:
            # Если расчетный лот меньше минимального, ставим минимум (если хватает маржи)
            if self.can_afford_lot(symbol, min_lot):
                return min_lot
            else:
                return 0.0 # Не можем открыть даже минимум
        
        # Округляем до шага лота
        lots = int((calculated_lot - min_lot) / lot_step) * lot_step + min_lot
        return lots
