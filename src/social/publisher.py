# src/social/publisher.py
"""
Издатель торговых сигналов.
Поддерживает как локальную (SQLite), так и сетевую (ZeroMQ) публикацию.
"""

import logging
import MetaTrader5 as mt5
from .bus import trade_db
from .network_transport import ZMQTradePublisher, ZMQ_AVAILABLE

logger = logging.getLogger(__name__)

# Глобальный экземпляр сетевого издателя (создается при необходимости)
zmq_publisher = None


def init_zmq_publisher(host: str = "0.0.0.0", port: int = 5555):
    """Инициализация сетевого издателя."""
    global zmq_publisher
    
    if not ZMQ_AVAILABLE:
        logger.warning("[ZMQ] ZeroMQ недоступен. Сетевой режим отключен.")
        return False
    
    try:
        if zmq_publisher is None:
            zmq_publisher = ZMQTradePublisher(host, port)
        
        if not zmq_publisher.running:
            return zmq_publisher.start()
        
        return True
    except Exception as e:
        logger.error(f"[ZMQ] Ошибка инициализации издателя: {e}")
        return False


def publish_trade_result(result, account_info, use_network: bool = False):
    """
    Публикует результат сделки в локальную и/или сетевую шину.
    
    Args:
        result: Результат вызова mt5.order_send
        account_info: Информация о счете мастера
        use_network: Если True, отправлять сигнал через сеть (ZeroMQ)
    """
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return

    action = "OPEN" 
    if result.request.type == mt5.ORDER_TYPE_SELL:
        type_val = 1
    else:
        type_val = 0  # BUY

    signal_data = {
        'ticket': result.order,
        'symbol': result.symbol,
        'action': action,
        'type': type_val,
        'volume': result.request.volume,
        'price': result.price,
        'sl': result.request.sl if result.request.sl > 0 else None,
        'tp': result.request.tp if result.request.tp > 0 else None,
        'master_account': account_info.login if account_info else 0,
        'master_balance': account_info.balance if account_info else 0,
    }

    # 1. Всегда пишем в локальную БД (для локальных подписчиков)
    try:
        trade_db.publish(signal_data)
        logger.debug(f"[Social] Сигнал сохранен локально: {action} {signal_data['symbol']}")
    except Exception as e:
        logger.error(f"[Social] Ошибка записи в локальную БД: {e}")

    # 2. Если включен сетевой режим — отправляем через ZeroMQ
    if use_network and ZMQ_AVAILABLE and zmq_publisher and zmq_publisher.running:
        try:
            zmq_publisher.publish(signal_data)
            logger.info(f"[ZMQ] Сигнал отправлен в сеть: {action} {signal_data['symbol']}")
        except Exception as e:
            logger.error(f"[ZMQ] Ошибка сетевой публикации: {e}")


def publish_close(ticket, symbol, use_network: bool = False):
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
        logger.error(f"[Social] Ошибка записи CLOSE в БД: {e}")

    if use_network and ZMQ_AVAILABLE and zmq_publisher and zmq_publisher.running:
        try:
            zmq_publisher.publish(signal_data)
        except Exception as e:
            logger.error(f"[ZMQ] Ошибка отправки CLOSE: {e}")


def publish_modify(ticket, symbol, sl, tp, use_network: bool = False):
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
        logger.error(f"[Social] Ошибка записи MODIFY в БД: {e}")

    if use_network and ZMQ_AVAILABLE and zmq_publisher and zmq_publisher.running:
        try:
            zmq_publisher.publish(signal_data)
        except Exception as e:
            logger.error(f"[ZMQ] Ошибка отправки MODIFY: {e}")
