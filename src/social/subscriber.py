# src/social/subscriber.py
"""
Подписчик торговых сигналов.
Принимает сигналы от Мастера, адаптирует риски и исполняет сделки.
"""

import asyncio
import logging
import MetaTrader5 as mt5
from .models import SocialTradeSignal, TradeAction
from .bus import trade_bus

logger = logging.getLogger(__name__)

class TradeSubscriber:
    def __init__(self, config):
        self.config = config
        self.is_running = False
        self.task = None

        # Настройки из конфига (по умолчанию)
        # Если секции social_trading нет, используем дефолт
        social_cfg = getattr(config, 'social_trading', {})
        self.risk_multiplier = social_cfg.get('risk_multiplier', 1.0)
        self.max_lot = social_cfg.get('max_lot_per_trade', 0.1)
        self.allowed_symbols = social_cfg.get('allowed_symbols', [])
        self.master_id = social_cfg.get('master_account_hash', None)

    async def start(self):
        """Запуск прослушивания шины."""
        if self.is_running:
            return

        logger.info("[SocialSubscriber] Запуск подписчика...")
        self.is_running = True
        
        # Получаем личную очередь из шины
        self.queue = trade_bus.subscribe()
        
        # Запускаем цикл обработки
        self.task = asyncio.create_task(self._listen_loop())

    async def stop(self):
        """Остановка подписчика."""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if hasattr(self, 'queue'):
            trade_bus.unsubscribe(self.queue)
        logger.info("[SocialSubscriber] Подписчик остановлен")

    async def _listen_loop(self):
        """Основной цикл обработки сигналов."""
        while self.is_running:
            try:
                # Ждем сигнал с таймаутом, чтобы можно было корректно выйти
                signal: SocialTradeSignal = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self._process_signal(signal)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[SocialSubscriber] Ошибка в цикле: {e}", exc_info=True)

    async def _process_signal(self, signal: SocialTradeSignal):
        """Обработка входящего сигнала."""
        # 1. Фильтрация по ID мастера (если настроено)
        if self.master_id and signal.master_account_id != self.master_id:
            return

        # 2. Фильтрация по символам
        if self.allowed_symbols and signal.symbol not in self.allowed_symbols:
            return

        logger.info(f"[SocialSubscriber] Получен сигнал: {signal.action} {signal.symbol}")

        if signal.action == TradeAction.OPEN:
            await self._handle_open(signal)
        elif signal.action == TradeAction.CLOSE:
            # Пока не реализуем, так как нет маппинга тикетов
            pass

    async def _handle_open(self, signal: SocialTradeSignal):
        """Открытие сделки на основе сигнала Мастера."""
        
        # 1. Рассчитываем объем
        volume = self._calculate_volume(signal)
        if volume <= 0:
            logger.warning(f"[SocialSubscriber] Объем 0, пропускаем {signal.symbol}")
            return

        # 2. Формируем запрос
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": signal.symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if signal.type == 0 else mt5.ORDER_TYPE_SELL,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "deviation": 20,
            "magic": 234000, # Magic для подписчика
            "comment": f"Copy:{signal.ticket}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # 3. Исполнение
        # Вызываем напрямую mt5, так как ExecutionService может требовать сложных объектов
        result = mt5.order_send(request)
        
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[SocialSubscriber] Сделка открыта: {result.order}, Vol: {volume}, Price: {result.price}")
        else:
            logger.error(f"[SocialSubscriber] Ошибка открытия: {result.comment} (Code: {result.retcode})")

    def _calculate_volume(self, signal: SocialTradeSignal) -> float:
        """
        Расчет объема сделки подписчика.
        Формула: Лот_Мастера * Коэффициент_Риска.
        """
        vol = signal.volume * self.risk_multiplier
        
        # Проверка на минимальный лот
        sym_info = mt5.symbol_info(signal.symbol)
        if sym_info:
            if vol < sym_info.volume_min:
                vol = sym_info.volume_min
            
            # Округление до шага
            if sym_info.volume_step > 0:
                import math
                vol = math.floor(vol / sym_info.volume_step) * sym_info.volume_step
        
        if vol > self.max_lot:
            vol = self.max_lot
            
        return vol
