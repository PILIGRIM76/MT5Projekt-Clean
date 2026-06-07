# src/core/services/position_manager.py
"""
PositionManager — Высокоуровневый менеджер управления позициями.

Объединяет TradeExecutor, PositionSizer, RiskEngine в единый API:
- Открытие позиций (BUY/SELL)
- Закрытие позиций (по тикету / все)
- Модификация SL/TP
- Расчёт объёма позиции
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5

from src.core.config_models import Settings
from src.core.mt5_connection_manager import mt5_ensure_connected
from src.data_models import SignalType

logger = logging.getLogger(__name__)


class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class PositionInfo:
    ticket: int
    symbol: str
    order_type: OrderType
    volume: float
    price_open: float
    price_current: float
    sl: float
    tp: float
    profit: float
    swap: float
    commission: float
    time_open: datetime
    comment: str

    @classmethod
    def from_mt5(cls, pos) -> "PositionInfo":
        return cls(
            ticket=pos.ticket,
            symbol=pos.symbol,
            order_type=OrderType.BUY if pos.type == mt5.ORDER_TYPE_BUY else OrderType.SELL,
            volume=pos.volume,
            price_open=pos.price_open,
            price_current=pos.price_current,
            sl=pos.sl,
            tp=pos.tp,
            profit=pos.profit,
            swap=pos.swap,
            commission=getattr(pos, "commission", 0.0),
            time_open=datetime.fromtimestamp(pos.time),
            comment=getattr(pos, "comment", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "type": self.order_type.value,
            "volume": self.volume,
            "price_open": self.price_open,
            "price_current": self.price_current,
            "sl": self.sl,
            "tp": self.tp,
            "profit": self.profit,
            "swap": self.swap,
            "commission": self.commission,
            "time_open": self.time_open.isoformat(),
            "comment": self.comment,
        }


@dataclass
class ModifyResult:
    success: bool
    ticket: int
    message: str
    old_sl: float = 0.0
    new_sl: float = 0.0
    old_tp: float = 0.0
    new_tp: float = 0.0


@dataclass
class OpenPositionResult:
    success: bool
    ticket: Optional[int] = None
    symbol: str = ""
    order_type: Optional[OrderType] = None
    volume: float = 0.0
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    message: str = ""


@dataclass
class ClosePositionResult:
    success: bool
    ticket: int = 0
    profit: float = 0.0
    message: str = ""


class PositionManager:
    """Менеджер управления позициями MT5."""

    def __init__(self, config: Settings, mt5_lock: threading.Lock):
        self.config = config
        self.mt5_lock = mt5_lock
        logger.info("PositionManager инициализирован")

    def open_position(
        self,
        symbol: str,
        volume: float,
        order_type: OrderType,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        deviation: int = 20,
        magic: int = 0,
        comment: str = "",
    ) -> OpenPositionResult:
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                return OpenPositionResult(success=False, symbol=symbol, message="MT5 недоступен")

            try:
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    return OpenPositionResult(success=False, symbol=symbol, message=f"{symbol} не найден")

                if not symbol_info.visible:
                    mt5.symbol_select(symbol, True)

                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    return OpenPositionResult(success=False, symbol=symbol, message=f"Нет тика для {symbol}")

                digits = symbol_info.digits
                entry_price = tick.ask if order_type == OrderType.BUY else tick.bid
                mt5_type = mt5.ORDER_TYPE_BUY if order_type == OrderType.BUY else mt5.ORDER_TYPE_SELL

                if price is not None:
                    entry_price = round(price, digits)

                sl_r = round(sl, digits) if sl is not None else 0.0
                tp_r = round(tp, digits) if tp is not None else 0.0

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": float(volume),
                    "type": mt5_type,
                    "price": entry_price,
                    "sl": sl_r,
                    "tp": tp_r,
                    "deviation": deviation,
                    "magic": magic,
                    "comment": comment,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                result = mt5.order_send(request)
                if result is None:
                    return OpenPositionResult(success=False, symbol=symbol, message=f"None: {mt5.last_error()}")
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    return OpenPositionResult(success=False, symbol=symbol, message=f"retcode={result.retcode}")

                logger.info(f"Открыта: {order_type.value} {symbol} {volume} @ {entry_price}, ticket={result.deal}")
                return OpenPositionResult(
                    success=True,
                    ticket=result.deal,
                    symbol=symbol,
                    order_type=order_type,
                    volume=volume,
                    price=entry_price,
                    sl=sl_r,
                    tp=tp_r,
                    message="OK",
                )
            except Exception as e:
                logger.error(f"Ошибка открытия: {e}", exc_info=True)
                return OpenPositionResult(success=False, symbol=symbol, message=str(e))

    def close_position(self, ticket: int, deviation: int = 20) -> ClosePositionResult:
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                return ClosePositionResult(success=False, ticket=ticket, message="MT5 недоступен")
            try:
                position = mt5.positions_get(ticket=ticket)
                if not position:
                    return ClosePositionResult(success=False, ticket=ticket, message="Не найдена")

                pos = position[0]
                tick = mt5.symbol_info_tick(pos.symbol)
                if tick is None:
                    return ClosePositionResult(success=False, ticket=ticket, message="Нет тика")

                close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": ticket,
                    "price": close_price,
                    "deviation": deviation,
                    "magic": 0,
                    "comment": "close by PositionManager",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                result = mt5.order_send(request)
                if result is None:
                    return ClosePositionResult(success=False, ticket=ticket, message=f"None: {mt5.last_error()}")
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    return ClosePositionResult(success=False, ticket=ticket, message=f"retcode={result.retcode}")

                logger.info(f"Закрыта #{ticket}. Profit: {pos.profit:.2f}")
                return ClosePositionResult(success=True, ticket=ticket, profit=pos.profit, message="OK")
            except Exception as e:
                logger.error(f"Ошибка закрытия #{ticket}: {e}", exc_info=True)
                return ClosePositionResult(success=False, ticket=ticket, message=str(e))

    def close_all_positions(self, symbol: Optional[str] = None) -> List[ClosePositionResult]:
        positions = self.get_positions(symbol=symbol)
        results = [self.close_position(p.ticket) for p in positions]
        closed = sum(1 for r in results if r.success)
        logger.info(f"Закрыто {closed}/{len(results)} позиций")
        return results

    def modify_position(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> ModifyResult:
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                return ModifyResult(success=False, ticket=ticket, message="MT5 недоступен")
            try:
                position = mt5.positions_get(ticket=ticket)
                if not position:
                    return ModifyResult(success=False, ticket=ticket, message="Не найдена")

                pos = position[0]
                symbol_info = mt5.symbol_info(pos.symbol)
                digits = symbol_info.digits if symbol_info else 5

                old_sl, old_tp = pos.sl, pos.tp
                new_sl = round(sl, digits) if sl is not None else old_sl
                new_tp = round(tp, digits) if tp is not None else old_tp

                if new_sl == old_sl and new_tp == old_tp:
                    return ModifyResult(
                        success=True,
                        ticket=ticket,
                        message="Без изменений",
                        old_sl=old_sl,
                        new_sl=new_sl,
                        old_tp=old_tp,
                        new_tp=new_tp,
                    )

                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": pos.symbol,
                    "position": ticket,
                    "sl": new_sl,
                    "tp": new_tp,
                }
                result = mt5.order_send(request)

                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    msg = f"None: {mt5.last_error()}" if result is None else f"retcode={result.retcode}"
                    return ModifyResult(success=False, ticket=ticket, message=msg, old_sl=old_sl, old_tp=old_tp)

                logger.info(f"Модифицирована #{ticket}: SL {old_sl}→{new_sl}, TP {old_tp}→{new_tp}")
                return ModifyResult(
                    success=True, ticket=ticket, message="OK", old_sl=old_sl, new_sl=new_sl, old_tp=old_tp, new_tp=new_tp
                )
            except Exception as e:
                logger.error(f"Ошибка модификации #{ticket}: {e}", exc_info=True)
                return ModifyResult(success=False, ticket=ticket, message=str(e))

    def calculate_volume(self, symbol: str, risk_amount_usd: float, stop_loss_pips: float) -> float:
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                return 0.0
            try:
                info = mt5.symbol_info(symbol)
                if info is None:
                    return 0.0
                pip_value = info.trade_tick_value * 10
                if stop_loss_pips <= 0 or pip_value <= 0:
                    return info.volume_min
                raw = risk_amount_usd / (stop_loss_pips * pip_value)
                step = info.volume_step
                if step > 0:
                    vol = max(info.volume_min, min(info.volume_max, round(raw / step) * step))
                else:
                    vol = max(info.volume_min, min(info.volume_max, round(raw, 2)))
                return vol
            except Exception as e:
                logger.error(f"Ошибка расчёта объёма: {e}", exc_info=True)
                return 0.0

    def get_positions(self, symbol: Optional[str] = None) -> List[PositionInfo]:
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                return []
            try:
                positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
                return [PositionInfo.from_mt5(p) for p in positions] if positions else []
            except Exception as e:
                logger.error(f"Ошибка получения позиций: {e}", exc_info=True)
                return []

    def get_position(self, ticket: int) -> Optional[PositionInfo]:
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                return None
            try:
                positions = mt5.positions_get(ticket=ticket)
                return PositionInfo.from_mt5(positions[0]) if positions else None
            except Exception as e:
                logger.error(f"Ошибка получения #{ticket}: {e}", exc_info=True)
                return None

    def get_total_profit(self, symbol: Optional[str] = None) -> float:
        return sum(p.profit for p in self.get_positions(symbol=symbol))

    def get_positions_count(self, symbol: Optional[str] = None) -> int:
        return len(self.get_positions(symbol=symbol))

    def __repr__(self) -> str:
        return f"PositionManager(positions={self.get_positions_count()})"
