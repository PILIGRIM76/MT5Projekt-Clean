"""
Риск-менеджер (RiskManager)
Контролирует просадку, экспозицию и рассчитывает безопасный лот.
"""

import logging
import math
from typing import Tuple

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Управляет рисками торговли:
    - Проверка просадки (Drawdown)
    - Расчёт размера позиции (Position Sizing)
    - Контроль экспозиции (макс. кол-во сделок)
    - Проверка свободной маржи
    """

    def __init__(self, config):
        self.config = config

        # Настройки из конфига
        self.max_drawdown_pct = getattr(config, "max_drawdown_pct", 5.0)  # %
        self.risk_per_trade_pct = getattr(config, "risk_per_trade_pct", 1.0)  # %
        self.max_open_trades = getattr(config, "max_open_trades", 3)
        self.min_lot = getattr(config, "min_lot", 0.01)
        self.max_lot = getattr(config, "max_lot", 1.0)
        self.slippage_points = getattr(config, "slippage_points", 10)

        # Динамические параметры
        self.is_active = True
        self._last_check_time = None
        self._consecutive_losses = 0

        logger.info(
            f"RiskManager инициализирован: "
            f"max_dd={self.max_drawdown_pct}%, "
            f"risk/trade={self.risk_per_trade_pct}%, "
            f"max_trades={self.max_open_trades}"
        )

    def check_safety(self) -> Tuple[bool, str]:
        """
        Проверка безопасности перед сделкой.

        Returns:
            Tuple[bool, str]: (Разрешено?, Причина отказа)
        """
        try:
            # 1. Проверка инициализации MT5
            if not mt5.initialize():
                logger.error("MT5 не инициализирован для проверки безопасности")
                return False, "MT5 не инициализирован"

            # 2. Проверка доступа к счёту
            account_info = mt5.account_info()
            if not account_info:
                logger.error("Нет доступа к информации о счёте")
                return False, "Нет доступа к счёту"

            # 3. Проверка свободной маржи (минимум 100 валюты депозита)
            if account_info.margin_free < 100:
                logger.warning(f"Недостаточно свободной маржи: {account_info.margin_free:.2f}")
                return False, f"Недостаточно свободной маржи ({account_info.margin_free:.2f})"

            # 4. Проверка просадки (Equity / Balance)
            if account_info.balance > 0:
                drawdown = (1 - (account_info.equity / account_info.balance)) * 100
                if drawdown > self.max_drawdown_pct:
                    logger.warning(f"Превышена макс. просадка: {drawdown:.2f}% > {self.max_drawdown_pct}%")
                    return False, f"Превышена макс. просадка ({drawdown:.2f}% > {self.max_drawdown_pct}%)"

            # 5. Проверка кол-ва открытых ордеров
            positions = mt5.positions_get()
            if positions:
                if len(positions) >= self.max_open_trades:
                    logger.warning(f"Лимит позиций исчерпан: {len(positions)}/{self.max_open_trades}")
                    return False, f"Лимит позиций ({self.max_open_trades}) исчерпан"
            else:
                positions = []

            # 6. Проверка на连续ные убытки (защита от "tilt")
            if self._consecutive_losses >= 3:
                logger.warning(f"Серия убытков: {self._consecutive_losses}. Пауза в торговле.")
                return False, f"Серия убытков ({self._consecutive_losses}). Пауза в торговле."

            logger.debug("Safety check passed ✓")
            return True, "OK"

        except Exception as e:
            logger.error(f"Ошибка в check_safety: {e}", exc_info=True)
            return False, f"Ошибка проверки: {e}"

    def calculate_lot(self, symbol: str, stop_loss_price: float, entry_price: float) -> float:
        """
        Рассчитывает лот на основе риска на сделку (%) и расстояния до SL.

        Args:
            symbol: Торговый символ (EURUSD, GBPJPY и т.д.)
            stop_loss_price: Цена стоп-лосса
            entry_price: Цена входа

        Returns:
            float: Рассчитанный размер лота (нормализованный под брокера)
        """
        try:
            # 1. Получение информации о счёте
            account_info = mt5.account_info()
            if not account_info:
                logger.error("Не удалось получить информацию о счёте для расчёта лота")
                return self.min_lot

            # 2. Получение информации о символе
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                logger.error(f"Символ {symbol} не найден для расчёта лота")
                return self.min_lot

            # 3. Стоимость пункта и размер тика
            tick_value = symbol_info.trade_tick_value  # Стоимость одного тика
            tick_size = symbol_info.trade_tick_size  # Размер тика (шаг цены)

            # 4. Расстояние до стопа в пунктах
            sl_distance = abs(entry_price - stop_loss_price)
            if sl_distance == 0:
                # Защита от деления на 0 - используем дефолтное расстояние
                sl_points = 100
                logger.warning(f"SL расстояние = 0, используется дефолт: {sl_points} пунктов")
            else:
                sl_points = sl_distance / tick_size

            # 5. Риск в деньгах (сколько готовы потерять)
            risk_amount = account_info.balance * (self.risk_per_trade_pct / 100)

            # 6. Формула лота: Risk / (SL_Points * Tick_Value)
            # Пример: Risk=$100, SL=50 пунктов, TickValue=$10 → Lot = 100/(50*10) = 0.20
            raw_lot = risk_amount / (sl_points * tick_value)

            # 7. Нормализация лота под требования брокера
            lot_step = symbol_info.volume_step  # Шаг изменения лота (обычно 0.01)
            min_lot = symbol_info.volume_min  # Минимальный лот (обычно 0.01)
            max_lot = symbol_info.volume_max  # Максимальный лот (обычно 100.0)

            # Округляем лот вниз до ближайшего шага
            final_lot = math.floor(raw_lot / lot_step) * lot_step

            # Ограничиваем минимальным и максимальным лотами
            final_lot = max(min_lot, min(final_lot, max_lot, self.max_lot))

            # Округляем до 2 знаков после запятой (стандарт для MT5)
            final_lot = round(final_lot, 2)

            logger.info(
                f"Lot calculation: {symbol} | "
                f"Risk=${risk_amount:.2f} | "
                f"SL={sl_points:.0f}pts | "
                f"Raw={raw_lot:.2f} → Final={final_lot:.2f}"
            )

            return final_lot

        except Exception as e:
            logger.error(f"Ошибка в calculate_lot: {e}", exc_info=True)
            return self.min_lot

    def record_trade_outcome(self, profit: float):
        """
        Записывает результат сделки для отслеживания серии убытков.

        Args:
            profit: Прибыль/убыток сделки в валюте депозита
        """
        if profit < 0:
            self._consecutive_losses += 1
            logger.info(f"❌ Убыток. Серия убытков: {self._consecutive_losses}")
        else:
            if self._consecutive_losses > 0:
                logger.info(f"✅ Прибыль. Серия убытков сброшена (было {self._consecutive_losses})")
            self._consecutive_losses = 0

    def get_risk_status(self) -> dict:
        """
        Получает текущий статус риск-менеджера.

        Returns:
            dict: Статус с метриками
        """
        try:
            account_info = mt5.account_info()
            if not account_info:
                return {"active": self.is_active, "error": "Нет доступа к счёту"}

            drawdown = 0.0
            if account_info.balance > 0:
                drawdown = (1 - (account_info.equity / account_info.balance)) * 100

            positions = mt5.positions_get()
            open_trades = len(positions) if positions else 0

            return {
                "active": self.is_active,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "drawdown_pct": round(drawdown, 2),
                "max_drawdown_pct": self.max_drawdown_pct,
                "margin_free": account_info.margin_free,
                "open_trades": open_trades,
                "max_open_trades": self.max_open_trades,
                "consecutive_losses": self._consecutive_losses,
                "risk_per_trade_pct": self.risk_per_trade_pct,
            }

        except Exception as e:
            logger.error(f"Ошибка в get_risk_status: {e}", exc_info=True)
            return {"active": self.is_active, "error": str(e)}

    def update_configuration(self, config):
        """
        Обновляет настройки риск-менеджера на лету.

        Args:
            config: Новая конфигурация
        """
        try:
            old_max_dd = self.max_drawdown_pct
            old_risk = self.risk_per_trade_pct
            old_max_trades = self.max_open_trades

            self.max_drawdown_pct = getattr(config, "max_drawdown_pct", self.max_drawdown_pct)
            self.risk_per_trade_pct = getattr(config, "risk_per_trade_pct", self.risk_per_trade_pct)
            self.max_open_trades = getattr(config, "max_open_trades", self.max_open_trades)
            self.min_lot = getattr(config, "min_lot", self.min_lot)
            self.max_lot = getattr(config, "max_lot", self.max_lot)

            logger.info(
                f"RiskManager настройки обновлены: "
                f"max_dd: {old_max_dd}% → {self.max_drawdown_pct}%, "
                f"risk: {old_risk}% → {self.risk_per_trade_pct}%, "
                f"max_trades: {old_max_trades} → {self.max_open_trades}"
            )

        except Exception as e:
            logger.error(f"Ошибка обновления настроек RiskManager: {e}", exc_info=True)
