# src/social/subscriber.py
"""
Подписчик торговых сигналов.
Поддерживает как локальный (SQLite), так и сетевой (ZeroMQ) режимы.
"""

import asyncio
import logging
import time
import math
import MetaTrader5 as mt5
from typing import Dict, Optional
from .bus import trade_db
from .network_transport import ZMQTradeSubscriber, ZMQ_AVAILABLE

logger = logging.getLogger(__name__)

class TradeSubscriber:
    def __init__(self, config, signal_emitter=None):
        self.config = config
        self.is_running = False
        self.task = None
        self.active_trades: Dict[int, int] = {}  # {master_ticket: follower_ticket}
        self.signal_emitter = signal_emitter
        
        # Социальные настройки
        social_cfg = getattr(config, 'social_trading', {})
        self.risk_multiplier = social_cfg.get('risk_multiplier', 1.0)
        self.max_lot = social_cfg.get('max_lot_per_trade', 1.0)
        self.allowed_symbols = social_cfg.get('allowed_symbols', [])
        
        # Настройки режима работы
        self.mode = social_cfg.get('mode', 'local')  # 'local', 'network', 'hybrid'
        self.master_host = social_cfg.get('master_host', 'localhost')
        self.master_port = social_cfg.get('master_port', 5555)
        
        # Сетевой подписчик (ZeroMQ)
        self.zmq_subscriber: Optional[ZMQTradeSubscriber] = None

    async def start(self):
        """Запуск подписчика."""
        if self.is_running:
            return

        logger.info(f"[SocialSubscriber] Запуск в режиме: {self.mode}")
        self.is_running = True

        # 1. Запуск локального режима (SQLite)
        if self.mode in ['local', 'hybrid']:
            self.task = asyncio.create_task(self._local_listen_loop())
            logger.info("[SocialSubscriber] Локальный режим активен")

        # 2. Запуск сетевого режима (ZeroMQ)
        if self.mode in ['network', 'hybrid']:
            if ZMQ_AVAILABLE:
                self.zmq_subscriber = ZMQTradeSubscriber(
                    master_host=self.master_host,
                    master_port=self.master_port,
                    on_signal=self._on_zmq_signal
                )
                if self.zmq_subscriber.start():
                    logger.info(f"[SocialSubscriber] Сетевой режим активен: {self.master_host}:{self.master_port}")
                else:
                    logger.error("[SocialSubscriber] Не удалось запустить сетевой режим")
            else:
                logger.error("[SocialSubscriber] ZeroMQ недоступен, сетевой режим невозможен")

        if self.signal_emitter:
            self.signal_emitter.emit("✅ Подписчик активен")
        
        logger.info("[SocialSubscriber] Подписчик запущен и ожидает сигналы...")

    async def stop(self):
        """Остановка подписчика."""
        self.is_running = False
        
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        if self.zmq_subscriber:
            self.zmq_subscriber.stop()
        
        logger.info("[SocialSubscriber] Подписчик остановлен")

    async def _local_listen_loop(self):
        """Цикл прослушивания локальных сигналов (SQLite)."""
        while self.is_running:
            try:
                signals = trade_db.get_new_signals()
                for sig in signals:
                    await self._process_signal(sig)
                    trade_db.mark_processed(sig['db_id'])
                
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SocialSubscriber] Ошибка в локальном цикле: {e}", exc_info=True)
                await asyncio.sleep(1)

    def _on_zmq_signal(self, signal_data: dict):
        """Обработка сигнала от ZeroMQ (вызывается из отдельного потока)."""
        try:
            # Преобразуем в формат, совместимый с локальным
            signal = {
                'db_id': 0,  # Для сетевых сигналов нет db_id
                'master_ticket': signal_data.get('ticket'),
                'action': signal_data.get('action'),
                'symbol': signal_data.get('symbol'),
                'type': signal_data.get('type'),
                'volume': signal_data.get('volume'),
                'price': signal_data.get('price'),
                'sl': signal_data.get('sl'),
                'tp': signal_data.get('tp'),
                'timestamp': signal_data.get('timestamp')
            }
            
            # Запускаем обработку в asyncio
            asyncio.run_coroutine_threadsafe(self._process_signal(signal), asyncio.get_event_loop())
        except Exception as e:
            logger.error(f"[ZMQ] Ошибка обработки сигнала: {e}")

    async def _process_signal(self, signal):
        """Обработка входящего сигнала."""
        # 1. Фильтрация по символам
        if self.allowed_symbols and signal['symbol'] not in self.allowed_symbols:
            return

        logger.info(f"[SocialSubscriber] Получен сигнал: {signal['action']} {signal['symbol']} (Ticket: {signal['master_ticket']})")

        action = signal['action']
        if action == 'OPEN':
            await self._handle_open(signal)
        elif action == 'CLOSE':
            await self._handle_close(signal)
        elif action == 'MODIFY':
            await self._handle_modify(signal)

    async def _handle_open(self, signal):
        """Открытие сделки на основе сигнала Мастера."""
        
        volume = self._calculate_volume(signal)
        if volume <= 0:
            logger.warning(f"[SocialSubscriber] Объем 0, пропускаем {signal['symbol']}")
            return

        order_type = mt5.ORDER_TYPE_BUY if signal['type'] == 0 else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": signal['symbol'],
            "volume": volume,
            "type": order_type,
            "price": 0.0,
            "sl": signal['sl'],
            "tp": signal['tp'],
            "deviation": 20,
            "magic": 234000,
            "comment": f"Copy:{signal['master_ticket']}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[SocialSubscriber] Сделка открыта: {result.order}, Vol: {volume}, Price: {result.price}")
            self.active_trades[signal['master_ticket']] = result.order
        else:
            logger.error(f"[SocialSubscriber] Ошибка открытия: {result.comment} (Code: {result.retcode})")

    async def _handle_close(self, signal):
        """Закрытие сделки подписчика при закрытии сделки Мастера."""
        follower_ticket = self.active_trades.pop(signal['master_ticket'], None)
        if not follower_ticket:
            logger.debug(f"[SocialSubscriber] Тикет {signal['master_ticket']} не найден")
            return

        pos = mt5.positions_get(ticket=follower_ticket)
        if not pos:
            logger.warning(f"[SocialSubscriber] Позиция {follower_ticket} уже закрыта")
            return

        pos = pos[0]
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
            "position": follower_ticket,
            "price": 0.0,
            "deviation": 20,
            "magic": 234000,
            "comment": f"CopyClose:{signal['master_ticket']}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[SocialSubscriber] Позиция {follower_ticket} закрыта")
        else:
            logger.error(f"[SocialSubscriber] Ошибка закрытия: {result.comment}")

    async def _handle_modify(self, signal):
        """Изменение SL/TP позиции подписчика."""
        follower_ticket = self.active_trades.get(signal['master_ticket'])
        if not follower_ticket:
            return

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": signal['symbol'],
            "position": follower_ticket,
            "sl": signal['sl'] if signal['sl'] else 0.0,
            "tp": signal['tp'] if signal['tp'] else 0.0,
        }

        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[SocialSubscriber] Позиция {follower_ticket} модифицирована")
        else:
            logger.warning(f"[SocialSubscriber] Ошибка модификации: {result.comment}")

    def _calculate_volume(self, signal) -> float:
        """Расчет объема сделки подписчика."""
        vol = signal['volume'] * self.risk_multiplier
        
        sym_info = mt5.symbol_info(signal['symbol'])
        if sym_info:
            if vol < sym_info.volume_min:
                vol = sym_info.volume_min
            
            if sym_info.volume_step > 0:
                vol = math.floor(vol / sym_info.volume_step) * sym_info.volume_step
        
        if vol > self.max_lot:
            vol = self.max_lot
            
        return vol
