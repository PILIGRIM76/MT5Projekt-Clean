# src/core/trading/trading_engine.py
"""
TradingEngine — ядро торговой логики.
Извлечён из TradingSystem God Object (Фаза 3).

Отвечает за:
- Закрытие позиций по SL/TP
- Обработку команд (CLOSE_ALL, CLOSE_ONE)
- Проверку условий безопасности перед торговлей
- Выбор таймфрейма и символов для торговли
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    Ядро торговой логики — вынесено из TradingSystem.

    Атрибуты:
        trading_system: Ссылка на TradingSystem для доступа к сервисам
    """

    def __init__(self, trading_system):
        self.trading_system = trading_system
        self._last_gui_updates: Dict[str, float] = {}
        self._min_gui_interval = 0.3  # Мин. интервал GUI обновлений

    def can_trade(self) -> bool:
        """
        Проверка условий для торговли.
        Заменяет начало run_cycle.

        Returns:
            True если можно торговать
        """
        ts = self.trading_system
        if ts.stop_event.is_set() or not ts.is_heavy_init_complete or ts.update_pending:
            logger.warning(
                f"[can_trade] Пропуск: stop={ts.stop_event.is_set()}, "
                f"init={ts.is_heavy_init_complete}, update={ts.update_pending}"
            )
            return False
        return True

    def close_positions_if_needed(self, symbols_to_close: Optional[List[str]] = None) -> bool:
        """
        Закрыть позиции по символам или все.

        Args:
            symbols_to_close: Список символов для закрытия (None = все)

        Returns:
            True если позиции были закрыты
        """
        ts = self.trading_system
        closed = False

        try:
            if not ts.mt5_lock.acquire(timeout=0.5):
                logger.warning("[close_positions] MT5 Lock недоступен")
                return False

            try:
                positions = mt5.positions_get()
                if not positions:
                    return False

                for pos in positions:
                    if symbols_to_close and pos.symbol not in symbols_to_close:
                        continue

                    # Закрываем позицию
                    close_request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "position": pos.ticket,
                        "symbol": pos.symbol,
                        "volume": pos.volume,
                        "deviation": 20,
                        "magic": 234000,
                        "comment": "Close by TradingEngine",
                        "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                    }

                    result = mt5.order_send(close_request)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        logger.info(f"[close_positions] Закрыта позиция {pos.ticket} ({pos.symbol})")
                        closed = True
                    else:
                        logger.warning(f"[close_positions] Ошибка закрытия {pos.ticket}: {result}")
            finally:
                ts.mt5_lock.release()

        except Exception as e:
            logger.error(f"[close_positions] Ошибка: {e}", exc_info=True)

        return closed

    def get_available_symbols(self, fallback_symbols: Optional[List[str]] = None) -> List[str]:
        """
        Получить список символов для торговли.

        Args:
            fallback_symbols: Fallback если сканер не работал

        Returns:
            Список символов
        """
        ts = self.trading_system

        # Приоритет: топ символов из сканера
        if hasattr(ts, "latest_ranked_list") and ts.latest_ranked_list:
            top_n = ts.config.TOP_N_SYMBOLS
            symbols = [item["symbol"] for item in ts.latest_ranked_list[:top_n]]
            logger.info(f"[get_available_symbols] Топ-{len(symbols)} из сканера: {symbols}")
            return symbols

        # Fallback: whitelist из конфига
        symbols = fallback_symbols or ts.config.SYMBOLS_WHITELIST
        logger.warning(f"[get_available_symbols] Сканер не работал, используем {len(symbols)} символов")
        return symbols

    def process_commands(self) -> None:
        """
        Обработать команды из очереди (CLOSE_ALL, CLOSE_ONE).
        """
        ts = self.trading_system
        while not ts.command_queue.empty():
            try:
                command = ts.command_queue.get_nowait()
                cmd_type = command.get("type")

                if cmd_type == "CLOSE_ALL":
                    logger.warning("[commands] Закрытие ВСЕХ позиций по команде")
                    self.close_positions_if_needed()
                elif cmd_type == "CLOSE_ONE":
                    ticket = command.get("ticket")
                    logger.warning(f"[commands] Закрытие позиции {ticket} по команде")
                    self.close_positions_if_needed()
            except Exception as e:
                logger.error(f"[commands] Ошибка обработки команды: {e}")

    def get_timeframe_for_trading(self) -> int:
        """
        Получить таймфрейм для торговли (H1).

        Returns:
            MT5 timeframe constant
        """
        return mt5.TIMEFRAME_H1

    def safe_gui_update(self, method_name: str, *args) -> bool:
        """
        Rate-limited GUI update.

        Args:
            method_name: Имя метода обновления
            *args: Аргументы для сигнала

        Returns:
            True если обновление выполнено
        """
        now = time.time()
        last = self._last_gui_updates.get(method_name, 0)
        if now - last < self._min_gui_interval:
            return False

        self._last_gui_updates[method_name] = now

        if hasattr(self.trading_system, "_gui_coordinator") and self.trading_system._gui_coordinator:
            return self.trading_system._gui_coordinator.safe_gui_update(method_name, *args)

        return False
