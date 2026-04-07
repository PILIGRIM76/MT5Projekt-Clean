# src/social/network_transport.py
"""
Сетевой транспорт для социальной торговли через ZeroMQ.
Поддерживает передачу сигналов между ПК через интернет/локальную сеть.
"""

import json
import logging
import threading
from typing import Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import zmq
    ZMQ_AVAILABLE = True
except ImportError:
    logger.warning("pyzmq не установлен. Сетевой режим недоступен. Установите: pip install pyzmq")
    ZMQ_AVAILABLE = False


class ZMQTradePublisher:
    """
    Издатель торговых сигналов (сторона Мастера).
    Отправляет сигналы через ZeroMQ всем подключенным подписчикам.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 5555):
        self.host = host
        self.port = port
        self.context = None
        self.socket = None
        self.running = False
        self.thread = None
    
    def start(self):
        """Запуск сервера публикации."""
        if not ZMQ_AVAILABLE:
            logger.error("[ZMQ] ZeroMQ недоступен. Сетевой режим невозможен.")
            return False
        
        try:
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.PUB)
            self.socket.bind(f"tcp://{self.host}:{self.port}")
            self.running = True
            
            logger.info(f"[ZMQ] Сервер публикации запущен на tcp://{self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"[ZMQ] Ошибка запуска сервера: {e}")
            return False
    
    def publish(self, signal_data: dict):
        """Публикация торгового сигнала."""
        if not self.running or not self.socket:
            return
        
        try:
            # Добавляем timestamp если нет
            if 'timestamp' not in signal_data:
                signal_data['timestamp'] = datetime.now().isoformat()
            
            # Сериализуем в JSON и отправляем
            message = json.dumps(signal_data, ensure_ascii=False)
            self.socket.send_string(message)
            logger.debug(f"[ZMQ] Опубликован сигнал: {signal_data.get('action')} {signal_data.get('symbol')}")
        except Exception as e:
            logger.error(f"[ZMQ] Ошибка публикации: {e}")
    
    def stop(self):
        """Остановка сервера."""
        self.running = False
        if self.socket:
            self.socket.close()
        if self.context:
            self.context.term()
        logger.info("[ZMQ] Сервер публикации остановлен")


class ZMQTradeSubscriber:
    """
    Подписчик на торговые сигналы (сторона Подписчика).
    Принимает сигналы от удаленного Мастера через ZeroMQ.
    """
    
    def __init__(self, master_host: str = "localhost", master_port: int = 5555, 
                 on_signal: Optional[Callable] = None):
        self.master_host = master_host
        self.master_port = master_port
        self.on_signal = on_signal  # Callback для обработки сигнала
        self.context = None
        self.socket = None
        self.running = False
        self.thread = None
    
    def start(self):
        """Запуск подписки на сигналы."""
        if not ZMQ_AVAILABLE:
            logger.error("[ZMQ] ZeroMQ недоступен.")
            return False
        
        try:
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.SUB)
            self.socket.connect(f"tcp://{self.master_host}:{self.master_port}")
            self.socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Подписка на все сообщения
            self.running = True
            
            # Запускаем поток чтения
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            
            logger.info(f"[ZMQ] Подключено к серверу Мастера: tcp://{self.master_host}:{self.master_port}")
            return True
        except Exception as e:
            logger.error(f"[ZMQ] Ошибка подключения к Мастеру: {e}")
            return False
    
    def _listen_loop(self):
        """Цикл прослушивания сигналов."""
        while self.running:
            try:
                # Ждем сообщение с таймаутом
                message = self.socket.recv_string(zmq.NOBLOCK)
                if message:
                    signal_data = json.loads(message)
                    logger.info(f"[ZMQ] Получен сигнал: {signal_data.get('action')} {signal_data.get('symbol')}")
                    
                    if self.on_signal:
                        self.on_signal(signal_data)
            except zmq.Again:
                # Нет данных, ждем
                import time
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"[ZMQ] Ошибка чтения: {e}")
                import time
                time.sleep(1)
    
    def stop(self):
        """Остановка подписки."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.socket:
            self.socket.close()
        if self.context:
            self.context.term()
        logger.info("[ZMQ] Подписка остановлена")
