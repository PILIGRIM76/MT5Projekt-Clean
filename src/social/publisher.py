# src/social/publisher.py
"""
Издатель торговых сигналов.
Вызывается после успешного исполнения ордера.
"""

import asyncio
import logging
import MetaTrader5 as mt5
from .models import SocialTradeSignal, TradeAction
from .bus import trade_bus

logger = logging.getLogger(__name__)

async def publish_trade_result(result, account_info):
    """
    Публикует результат сделки в социальную шину.
    
    Args:
        result: Результат вызова mt5.order_send
        account_info: Информация о счете мастера (balance, login и т.д.)
    """
    if result is None:
        return

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        # Не публикуем неудачные сделки
        return

    # Определяем тип действия
    action = TradeAction.OPEN
    if result.request.type == mt5.ORDER_TYPE_SELL:
        type_val = 1
    else:
        type_val = 0 # BUY

    # Для упрощения считаем, что публикация происходит при открытии
    # Если нужно публиковать закрытие/модификацию, логику нужно расширить
    
    signal = SocialTradeSignal(
        master_account_id=account_info.login,
        master_balance=account_info.balance,
        master_equity=account_info.equity,
        ticket=result.order,
        symbol=result.symbol,
        action=action,
        type=type_val,
        open_price=result.price,
        current_price=result.price,
        stop_loss=result.request.sl,
        take_profit=result.request.tp,
        volume=result.request.volume,
        magic=result.request.magic,
        comment=result.comment
    )

    await trade_bus.publish(signal)
