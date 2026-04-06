# src/social/bus.py
"""
Асинхронная шина данных для социального трейдинга.
Использует asyncio.Queue для локальной передачи сигналов.
"""

import asyncio
import logging
from typing import List
from .models import SocialTradeSignal

logger = logging.getLogger(__name__)

class SocialTradeBus:
    """
    Очередь торговых сигналов.
    Публикатор пишет сюда, Подписчик читает.
    """
    
    def __init__(self):
        # Создаем очередь. Limit=0 означает неограниченный размер.
        self.queue = asyncio.Queue()
        self._subscribers: List[asyncio.Queue] = []
    
    async def publish(self, signal: SocialTradeSignal):
        """Опубликовать сигнал для всех подписчиков."""
        logger.info(f"[SocialBus] Публикация сигнала: {signal.action.value} {signal.symbol} (Ticket: {signal.ticket})")
        
        # Кладем в основную очередь (для логирования/сохранения)
        await self.queue.put(signal)
        
        # Рассылаем активным подписчикам
        for sub_queue in self._subscribers:
            await sub_queue.put(signal)
            
    def subscribe(self) -> asyncio.Queue:
        """Создать канал для нового подписчика."""
        q = asyncio.Queue()
        self._subscribers.append(q)
        logger.info("[SocialBus] Новый подписчик подключен")
        return q
        
    def unsubscribe(self, q: asyncio.Queue):
        """Отключить подписчика."""
        if q in self._subscribers:
            self._subscribers.remove(q)
            logger.info("[SocialBus] Подписчик отключен")

# Глобальный экземпляр шины (Singleton)
trade_bus = SocialTradeBus()
