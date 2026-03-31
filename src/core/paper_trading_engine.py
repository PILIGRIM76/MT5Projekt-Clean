# src/core/paper_trading_engine.py
"""
Paper Trading Engine — Режим симуляции торговли.

Компонент для тестирования стратегии на реальных данных без финансового риска.

Функции:
- Виртуальный баланс и позиции
- Симуляция исполнения ордеров с задержкой
- Симуляция проскальзывания и спреда
- Расчёт комиссий брокера
- Полная статистика как для реальной торговли
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5
import numpy as np

from src.core.config_models import Settings
from src.data_models import SignalType, TradeSignal

logger = logging.getLogger(__name__)


class OrderExecutionState(Enum):
    """Состояния исполнения ордера."""

    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class VirtualPosition:
    """
    Виртуальная позиция для Paper Trading.

    Атрибуты:
        ticket: Уникальный идентификатор позиции
        symbol: Торговый инструмент
        type: Тип позиции (BUY/SELL)
        lot: Объем позиции
        entry_price: Цена входа
        entry_time: Время открытия
        stop_loss: Стоп-лосс (опционально)
        take_profit: Тейк-профит (опционально)
        commission: Комиссия брокера
        slippage: Проскальзывание при открытии
        close_price: Цена закрытия (если позиция закрыта)
        close_time: Время закрытия (если позиция закрыта)
        close_reason: Причина закрытия
        pnl: Реализованный PnL (если позиция закрыта)
        pnl_percent: Процентный PnL (если позиция закрыта)
    """

    ticket: str
    symbol: str
    type: SignalType
    lot: float
    entry_price: float
    entry_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    commission: float = 0.0
    slippage: float = 0.0
    spread_cost: float = 0.0

    # Заполняется при закрытии
    close_price: Optional[float] = None
    close_time: Optional[datetime] = None
    close_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_percent: float = 0.0

    def unrealized_pnl(self, current_price: float) -> float:
        """Расчёт нереализованного PnL."""
        if self.type == SignalType.BUY:
            price_diff = current_price - self.entry_price
        else:
            price_diff = self.entry_price - current_price

        # PnL в валюте депозита (упрощённо)
        raw_pnl = price_diff * self.lot * 100000  # Стандартный лот
        return raw_pnl - self.commission - self.spread_cost

    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует в словарь для сериализации."""
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "type": self.type.value if isinstance(self.type, SignalType) else self.type,
            "lot": self.lot,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "commission": self.commission,
            "slippage": self.slippage,
            "spread_cost": self.spread_cost,
            "close_price": self.close_price,
            "close_time": self.close_time.isoformat() if self.close_time else None,
            "close_reason": self.close_reason,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
        }


@dataclass
class VirtualOrder:
    """
    Виртуальный ордер для симуляции исполнения.

    Атрибуты:
        ticket: Уникальный идентификатор
        symbol: Торговый инструмент
        type: Тип ордера (BUY/SELL)
        lot: Объем
        state: Состояние исполнения
        requested_price: Запрошенная цена
        execution_price: Цена исполнения
        execution_time: Время исполнения
        delay_ms: Задержка исполнения в мс
    """

    ticket: str
    symbol: str
    type: SignalType
    lot: float
    requested_price: float
    state: OrderExecutionState = OrderExecutionState.PENDING
    execution_price: Optional[float] = None
    execution_time: Optional[datetime] = None
    delay_ms: int = 0
    reject_reason: Optional[str] = None


class PaperTradingEngine:
    """
    Движок Paper Trading для симуляции торговли.

    Атрибуты:
        enabled: Включён ли режим Paper Trading
        initial_balance: Начальный баланс
        current_balance: Текущий баланс
        current_equity: Текущая equity (баланс + нереализованный PnL)
    """

    def __init__(self, config: Settings, trading_system_ref=None):
        """
        Инициализация Paper Trading Engine.

        Args:
            config: Конфигурация системы
            trading_system_ref: Ссылка на TradingSystem
        """
        self.config = config
        self.trading_system = trading_system_ref

        # Конфигурация из settings
        pt_config = getattr(config, "paper_trading", {})
        self.enabled = pt_config.get("enabled", False)
        self.initial_balance = pt_config.get("initial_balance", 100000)
        self.currency = pt_config.get("currency", "USD")

        # Симуляция параметров
        sim_config = pt_config.get("simulation", {})
        self.slippage_model = sim_config.get("slippage_model", "volatility_based")
        self.slippage_max_pips = sim_config.get("slippage_max_pips", 3)
        self.spread_source = sim_config.get("spread_source", "real_time")
        self.commission_per_lot = sim_config.get("commission_per_lot", 7.0)

        execution_delay = sim_config.get("execution_delay_ms", {})
        self.delay_market = execution_delay.get("market", 100)
        self.delay_limit = execution_delay.get("limit", 500)
        self.delay_stop = execution_delay.get("stop", 200)

        self.auto_close_on_exit = pt_config.get("auto_close_on_exit", False)

        # Состояние
        self._lock = Lock()
        self.current_balance = self.initial_balance
        self.current_equity = self.initial_balance

        # Позиции и ордера
        self.positions: Dict[str, VirtualPosition] = {}  # ticket -> position
        self.closed_positions: List[VirtualPosition] = []
        self.pending_orders: Dict[str, VirtualOrder] = {}  # ticket -> order

        # Статистика
        self.stats = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "total_commission": 0.0,
            "total_slippage": 0.0,
            "max_drawdown": 0.0,
            "peak_equity": self.initial_balance,
            "start_time": datetime.now(),
        }

        # История equity для расчёта просадки
        self._equity_history: List[float] = []

        logger.info("Paper Trading Engine инициализирован")
        logger.info(f"  - Enabled: {self.enabled}")
        logger.info(f"  - Initial Balance: {self.initial_balance} {self.currency}")
        logger.info(f"  - Slippage Model: {self.slippage_model}")
        logger.info(f"  - Commission per Lot: {self.commission_per_lot}")

    def reset(self) -> None:
        """Сброс статистики и позиций."""
        with self._lock:
            self.current_balance = self.initial_balance
            self.current_equity = self.initial_balance
            self.positions.clear()
            self.closed_positions.clear()
            self.pending_orders.clear()

            self.stats = {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "total_commission": 0.0,
                "total_slippage": 0.0,
                "max_drawdown": 0.0,
                "peak_equity": self.initial_balance,
                "start_time": datetime.now(),
            }

            self._equity_history.clear()

            logger.info("Paper Trading Engine сброшен")

    def execute_trade(
        self,
        signal: TradeSignal,
        lot_size: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[str]:
        """
        Симулирует исполнение торгового сигнала.

        Args:
            signal: Торговый сигнал
            lot_size: Объем сделки (если None, берётся из риск-менеджмента)
            stop_loss: Стоп-лосс
            take_profit: Тейк-профит

        Returns:
            Ticket позиции или None если ошибка
        """
        if not self.enabled:
            logger.warning("Paper Trading отключён")
            return None

        if signal.type not in [SignalType.BUY, SignalType.SELL]:
            logger.warning(f"Неверный тип сигнала: {signal.type}")
            return None

        # Получаем текущую цену
        current_price = self._get_current_price(signal.symbol)
        if current_price is None:
            logger.error(f"Не удалось получить цену для {signal.symbol}")
            return None

        # Создаём ордер
        order_ticket = self._generate_ticket()
        order = VirtualOrder(
            ticket=order_ticket,
            symbol=signal.symbol,
            type=signal.type,
            lot=lot_size or 0.1,  # Default 0.1 lot
            requested_price=current_price,
            state=OrderExecutionState.PENDING,
        )

        # Симулируем задержку исполнения
        delay_ms = self._simulate_execution_delay()
        time.sleep(delay_ms / 1000.0)  # Конвертируем в секунды
        order.delay_ms = delay_ms

        # Симулируем проскальзывание
        slippage = self._simulate_slippage(signal.symbol, signal.type, lot_size or 0.1)

        # Вычисляем цену исполнения
        if signal.type == SignalType.BUY:
            execution_price = current_price + slippage + self._get_spread(signal.symbol)
        else:
            execution_price = current_price - slippage

        order.execution_price = execution_price
        order.execution_time = datetime.now()
        order.state = OrderExecutionState.EXECUTED

        # Рассчитываем комиссию
        commission = self._calculate_commission(signal.symbol, lot_size or 0.1)

        # Создаём позицию
        position = VirtualPosition(
            ticket=order_ticket,
            symbol=signal.symbol,
            type=signal.type,
            lot=lot_size or 0.1,
            entry_price=execution_price,
            entry_time=datetime.now(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            commission=commission,
            slippage=slippage,
            spread_cost=self._get_spread(signal.symbol) * (lot_size or 0.1) * 100000,
        )

        # Сохраняем
        with self._lock:
            self.positions[order_ticket] = position
            self.pending_orders[order_ticket] = order

            # Обновляем статистику
            self.stats["total_trades"] += 1
            self.stats["total_commission"] += commission
            self.stats["total_slippage"] += abs(slippage) * (lot_size or 0.1) * 100000

        logger.info(
            f"📄 PAPER TRADE OPENED: {signal.type.value} {signal.symbol} "
            f"@ {execution_price:.5f} (lot: {lot_size or 0.1}, slippage: {slippage:.5f})"
        )

        # Отправляем алерт если есть
        if hasattr(self.trading_system, "alert_manager"):
            self.trading_system.alert_manager.send_alert(
                level="INFO",
                message=f"📄 Paper Trade: {signal.type.value} {signal.symbol} @ {execution_price:.5f}",
                context={"lot": lot_size or 0.1, "slippage": slippage, "commission": commission},
            )

        return order_ticket

    def close_position(self, ticket: str, reason: str = "MANUAL") -> bool:
        """
        Симулирует закрытие позиции.

        Args:
            ticket: Тикет позиции для закрытия
            reason: Причина закрытия

        Returns:
            True если успешно
        """
        if not self.enabled:
            return False

        with self._lock:
            if ticket not in self.positions:
                logger.error(f"Позиция {ticket} не найдена")
                return False

            position = self.positions[ticket]

        # Получаем текущую цену
        current_price = self._get_current_price(position.symbol)
        if current_price is None:
            logger.error(f"Не удалось получить цену для {position.symbol}")
            return False

        # Рассчитываем PnL
        pnl = position.unrealized_pnl(current_price)
        pnl_percent = (pnl / self.initial_balance) * 100

        # Обновляем позицию
        position.close_price = current_price
        position.close_time = datetime.now()
        position.close_reason = reason
        position.pnl = pnl
        position.pnl_percent = pnl_percent

        # Обновляем баланс
        with self._lock:
            self.current_balance += pnl
            self.current_equity = self.current_balance + self._calculate_unrealized_pnl()

            # Перемещаем в закрытые
            self.closed_positions.append(position)
            del self.positions[ticket]

            # Обновляем статистику
            self.stats["total_pnl"] += pnl
            self.stats["total_commission"] += position.commission

            if pnl > 0:
                self.stats["winning_trades"] += 1
                self.stats["gross_profit"] += pnl
            elif pnl < 0:
                self.stats["losing_trades"] += 1
                self.stats["gross_loss"] += abs(pnl)

            # Обновляем peak equity и drawdown
            if self.current_equity > self.stats["peak_equity"]:
                self.stats["peak_equity"] = self.current_equity

            drawdown = (self.stats["peak_equity"] - self.current_equity) / self.stats["peak_equity"] * 100
            if drawdown > self.stats["max_drawdown"]:
                self.stats["max_drawdown"] = drawdown

            # Сохраняем в историю
            self._equity_history.append(self.current_equity)

        logger.info(
            f"📄 PAPER TRADE CLOSED: {position.ticket} ({position.symbol}) "
            f"PnL: {pnl:.2f} ({pnl_percent:.2f}%), Reason: {reason}"
        )

        # Отправляем алерт
        if hasattr(self.trading_system, "alert_manager"):
            self.trading_system.alert_manager.send_alert(
                level="INFO",
                message=f"📄 Paper Trade Closed: {position.symbol} PnL: {pnl:.2f}",
                context={"pnl": pnl, "pnl_percent": pnl_percent, "reason": reason},
            )

        return True

    def check_stop_loss_take_profit(self) -> List[str]:
        """
        Проверяет срабатывание стоп-лоссов и тейк-профитов.

        Returns:
            Список закрытых позиций
        """
        closed_tickets = []

        for ticket, position in list(self.positions.items()):
            current_price = self._get_current_price(position.symbol)
            if current_price is None:
                continue

            # Проверка стоп-лосса
            if position.stop_loss:
                if position.type == SignalType.BUY and current_price <= position.stop_loss:
                    self.close_position(ticket, reason="STOP_LOSS")
                    closed_tickets.append(ticket)
                    continue
                elif position.type == SignalType.SELL and current_price >= position.stop_loss:
                    self.close_position(ticket, reason="STOP_LOSS")
                    closed_tickets.append(ticket)
                    continue

            # Проверка тейк-профита
            if position.take_profit:
                if position.type == SignalType.BUY and current_price >= position.take_profit:
                    self.close_position(ticket, reason="TAKE_PROFIT")
                    closed_tickets.append(ticket)
                    continue
                elif position.type == SignalType.SELL and current_price <= position.take_profit:
                    self.close_position(ticket, reason="TAKE_PROFIT")
                    closed_tickets.append(ticket)
                    continue

        return closed_tickets

    def get_virtual_balance(self) -> float:
        """Возвращает виртуальный баланс."""
        return self.current_balance

    def get_virtual_equity(self) -> float:
        """Возвращает виртуальную equity."""
        with self._lock:
            return self.current_balance + self._calculate_unrealized_pnl()

    def get_virtual_positions(self) -> List[VirtualPosition]:
        """Возвращает список открытых позиций."""
        with self._lock:
            return list(self.positions.values())

    def get_virtual_pnl(self) -> float:
        """Возвращает нереализованный PnL."""
        return self._calculate_unrealized_pnl()

    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику Paper Trading."""
        with self._lock:
            stats = self.stats.copy()

            # Рассчитываем дополнительные метрики
            total_trades = stats["winning_trades"] + stats["losing_trades"]
            stats["win_rate"] = (stats["winning_trades"] / total_trades * 100) if total_trades > 0 else 0
            stats["profit_factor"] = (stats["gross_profit"] / stats["gross_loss"]) if stats["gross_loss"] > 0 else float("inf")
            stats["avg_winner"] = (stats["gross_profit"] / stats["winning_trades"]) if stats["winning_trades"] > 0 else 0
            stats["avg_loser"] = (stats["gross_loss"] / stats["losing_trades"]) if stats["losing_trades"] > 0 else 0

            # Длительность сессии
            stats["session_duration"] = (datetime.now() - stats["start_time"]).total_seconds() / 3600  # В часах

            # Количество открытых позиций
            stats["open_positions"] = len(self.positions)

            return stats

    def export_to_csv(self, filepath: str) -> bool:
        """
        Экспортирует историю сделок в CSV.

        Args:
            filepath: Путь к файлу

        Returns:
            True если успешно
        """
        import csv

        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # Заголовок
                writer.writerow(
                    [
                        "Ticket",
                        "Symbol",
                        "Type",
                        "Lot",
                        "Entry Price",
                        "Entry Time",
                        "Close Price",
                        "Close Time",
                        "PnL",
                        "PnL %",
                        "Commission",
                        "Reason",
                    ]
                )

                # Данные
                for position in self.closed_positions:
                    writer.writerow(
                        [
                            position.ticket,
                            position.symbol,
                            position.type.value if isinstance(position.type, SignalType) else position.type,
                            position.lot,
                            position.entry_price,
                            position.entry_time.isoformat(),
                            position.close_price,
                            position.close_time.isoformat() if position.close_time else None,
                            f"{position.pnl:.2f}",
                            f"{position.pnl_percent:.2f}",
                            f"{position.commission:.2f}",
                            position.close_reason,
                        ]
                    )

            logger.info(f"Paper Trading история экспортирована в {filepath}")
            return True

        except Exception as e:
            logger.error(f"Ошибка экспорта в CSV: {e}")
            return False

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Получает текущую цену из MT5."""
        try:
            if self.trading_system and hasattr(self.trading_system, "mt5_lock"):
                with self.trading_system.mt5_lock:
                    tick = mt5.symbol_info_tick(symbol)
            else:
                tick = mt5.symbol_info_tick(symbol)

            if tick and tick.bid > 0 and tick.ask > 0:
                # Возвращаем среднюю цену
                return (tick.bid + tick.ask) / 2

            return None

        except Exception as e:
            logger.error(f"Ошибка получения цены для {symbol}: {e}")
            return None

    def _get_spread(self, symbol: str) -> float:
        """Получает текущий спред."""
        try:
            if self.trading_system and hasattr(self.trading_system, "mt5_lock"):
                with self.trading_system.mt5_lock:
                    tick = mt5.symbol_info_tick(symbol)
            else:
                tick = mt5.symbol_info_tick(symbol)

            if tick and tick.ask > 0 and tick.bid > 0:
                return tick.ask - tick.bid

            return 0.00001  # Минимальный спред по умолчанию

        except Exception:
            return 0.00001

    def _simulate_slippage(self, symbol: str, signal_type: SignalType, lot: float) -> float:
        """
        Симулирует проскальзывание.

        Модели:
        - volatility_based: Зависит от волатильности
        - random: Случайное в диапазоне
        - fixed: Фиксированное
        """
        if self.slippage_model == "fixed":
            return 0.0001  # 1 pip фиксированно

        elif self.slippage_model == "random":
            direction = 1 if signal_type == SignalType.BUY else -1
            return direction * np.random.uniform(0, self.slippage_max_pips * 0.00001)

        else:  # volatility_based
            # Получаем волатильность (упрощённо)
            try:
                if self.trading_system and hasattr(self.trading_system, "data_provider"):
                    # Можно получить ATR или другую метрику волатильности
                    volatility = 0.0001  # Default
                else:
                    volatility = 0.0001
            except Exception:
                volatility = 0.0001

            direction = 1 if signal_type == SignalType.BUY else -1
            max_slippage = self.slippage_max_pips * 0.00001

            # Проскальзывание пропорционально волатильности и лоту
            slippage = direction * volatility * lot * np.random.uniform(0.5, 1.0)

            # Ограничиваем максимум
            return np.clip(slippage, -max_slippage, max_slippage)

    def _simulate_execution_delay(self) -> int:
        """Симулирует задержку исполнения."""
        # Возвращаем случайную задержку в диапазоне
        return np.random.randint(50, 150)  # 50-150 мс

    def _calculate_commission(self, symbol: str, lot: float) -> float:
        """Рассчитывает комиссию брокера."""
        # Упрощённая модель: фиксированная комиссия за лот
        return self.commission_per_lot * lot

    def _calculate_unrealized_pnl(self) -> float:
        """Рассчитывает нереализованный PnL по всем позициям."""
        total_pnl = 0.0

        for position in self.positions.values():
            current_price = self._get_current_price(position.symbol)
            if current_price:
                total_pnl += position.unrealized_pnl(current_price)

        return total_pnl

    def _generate_ticket(self) -> str:
        """Генерирует уникальный тикет."""
        return f"PT_{uuid.uuid4().hex[:8].upper()}"

    def get_position(self, ticket: str) -> Optional[VirtualPosition]:
        """Возвращает позицию по тикету."""
        with self._lock:
            return self.positions.get(ticket)

    def get_closed_positions(self, limit: int = 100) -> List[VirtualPosition]:
        """Возвращает список закрытых позиций."""
        with self._lock:
            return self.closed_positions[-limit:]
