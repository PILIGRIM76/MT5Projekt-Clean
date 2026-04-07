# src/core/account_manager.py
"""
Account Manager — Автоопределение типа счета, валюты и адаптация рисков.

Функции:
- Определение типа счета (DEMO, CONTEST, REAL)
- Определение валюты счета (USD, EUR, RUB, и т.д.)
- Адаптивный расчет риска в зависимости от баланса
- Проверка доступной маржи перед торговлей
- Конвертация валют при необходимости
"""

import logging
from typing import Dict, Optional
import MetaTrader5 as mt5
from src.core.mt5_connection_manager import MT5ConnectionManager

logger = logging.getLogger(__name__)

# Курсы основных валют к USD (базовые, если не удалось получить из MT5)
DEFAULT_FX_RATES = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "RUB": 0.011,  # 1 RUB = 0.011 USD (примерно)
    "JPY": 0.0067,
    "CHF": 1.13,
    "CAD": 0.74,
    "AUD": 0.65,
    "NZD": 0.60,
    "CNY": 0.14,
}

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
        self.fx_rate_to_usd = 1.0  # Курс валюты счета к USD

    def update_info(self) -> bool:
        """Обновляет информацию о счете и определяет его тип."""
        acc = mt5.account_info()
        
        # Если не удалось получить инфо, пробуем инициализировать MT5
        if acc is None:
            logger.debug("[AccountManager] Нет связи с терминалом. Попытка инициализации через MT5ConnectionManager...")
            manager = MT5ConnectionManager.get_instance()
            if not manager.initialize():
                return False
        
        # Повторная попытка после инициализации
        acc = mt5.account_info()
        if acc is None:
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

        # Обновляем курс валюты счета к USD
        self._update_fx_rate()

        # Логируем только при успешном получении (уровень INFO)
        logger.info(
            f"[AccountManager] Счет: {self.account_type} | "
            f"Баланс: {self.balance} {self.currency} | "
            f"Курс к USD: {self.fx_rate_to_usd:.4f} | "
            f"Плечо: 1:{self.leverage}"
        )
        return True

    def _update_fx_rate(self):
        """Получает актуальный курс валюты счета к USD из MT5."""
        if self.currency == "USD":
            self.fx_rate_to_usd = 1.0
            return

        # Пробуем получить курс из MT5 (например, EURUSD)
        symbol_name = f"{self.currency}USD"
        if self.currency == "USD":
            symbol_name = "EURUSD"  # Fallback
        
        tick = mt5.symbol_info_tick(symbol_name)
        if tick and tick.bid > 0:
            self.fx_rate_to_usd = tick.bid
            logger.info(f"[AccountManager] Курс {symbol_name} из MT5: {self.fx_rate_to_usd}")
        else:
            # Если не удалось получить — используем дефолтный курс
            self.fx_rate_to_usd = DEFAULT_FX_RATES.get(self.currency, 1.0)
            logger.warning(
                f"[AccountManager] Не удалось получить курс {symbol_name} из MT5. "
                f"Используем приближенный: {self.fx_rate_to_usd}"
            )

    def get_balance_usd(self) -> float:
        """Возвращает баланс в эквиваленте USD."""
        return self.balance * self.fx_rate_to_usd

    def get_equity_usd(self) -> float:
        """Возвращает эквити в эквиваленте USD."""
        return self.equity * self.fx_rate_to_usd

    def get_adaptive_risk_percent(self) -> float:
        """
        Рассчитывает % риска на сделку в зависимости от размера счета (в USD эквиваленте).
        Маленькие счета требуют большего %, чтобы преодолеть порог мин. лота (0.01).
        Большие счета требуют меньшего % для безопасности.
        """
        balance_usd = self.get_balance_usd()

        if balance_usd < 100:
            return 2.0  # Для микро-счетов риск выше, чтобы открылся лот 0.01
        elif balance_usd < 500:
            return 1.0
        elif balance_usd < 2000:
            return 0.5
        elif balance_usd < 10000:
            return 0.2
        else:
            return 0.1  # Для крупных счетов риск минимальный

    def can_afford_lot(self, symbol: str, lot: float) -> bool:
        """Проверяет, хватает ли свободной маржи на открытие лота."""
        # Упрощенная проверка: берем маржу для 1.0 лота и умножаем
        margin_req = mt5.symbol_info(symbol).margin_initial if mt5.symbol_info(symbol) else 0
        required_margin = margin_req * lot
        
        if self.margin_free < required_margin:
            logger.warning(
                f"[AccountManager] Недостаточно маржи для {symbol} ({lot} лотов). "
                f"Нужно: {required_margin:.2f} {self.currency}, Есть: {self.margin_free:.2f} {self.currency}"
            )
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

