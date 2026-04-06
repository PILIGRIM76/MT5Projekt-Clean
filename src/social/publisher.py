# src/social/publisher.py
"""
Издатель торговых сигналов.
Вызывается после успешного исполнения ордера.
"""

import logging
import MetaTrader5 as mt5
from .bus import trade_db

logger = logging.getLogger(__name__)

def publish_trade_result(result, account_info):
    """
    Публикует результат сделки в социальную шину (SQLite).
    
    Args:
        result: Результат вызова mt5.order_send
        account_info: Информация о счете мастера
    """
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return

    # Определяем тип действия (по умолчанию OPEN)
    action = "OPEN" 
    if result.request.type == mt5.ORDER_TYPE_SELL:
        type_val = 1
    else:
        type_val = 0 # BUY

    # Подготовка данных для БД
    signal_data = {
        'ticket': result.order,
        'symbol': result.symbol,
        'action': action,
        'type': type_val,
        'volume': result.request.volume,
        'price': result.price,
        'sl': result.request.sl if result.request.sl > 0 else None,
        'tp': result.request.tp if result.request.tp > 0 else None
    }

    # Сохраняем в базу (теперь это IPC, работает между процессами)
    try:
        trade_db.publish(signal_data)
    except Exception as e:
        logger.error(f"[SocialPublisher] Ошибка записи в БД: {e}")

def publish_close(ticket, symbol):
    """Публикует сигнал на закрытие позиции."""
    signal_data = {
        'ticket': ticket,
        'symbol': symbol,
        'action': 'CLOSE',
        'type': 0,
        'volume': 0,
        'price': 0,
        'sl': None,
        'tp': None
    }
    try:
        trade_db.publish(signal_data)
    except Exception as e:
        logger.error(f"[SocialPublisher] Ошибка записи CLOSE в БД: {e}")

def publish_modify(ticket, symbol, sl, tp):
    """Публикует сигнал на модификацию."""
    signal_data = {
        'ticket': ticket,
        'symbol': symbol,
        'action': 'MODIFY',
        'type': 0,
        'volume': 0,
        'price': 0,
        'sl': sl if sl > 0 else None,
        'tp': tp if tp > 0 else None
    }
    try:
        trade_db.publish(signal_data)
    except Exception as e:
        logger.error(f"[SocialPublisher] Ошибка записи MODIFY в БД: {e}")
