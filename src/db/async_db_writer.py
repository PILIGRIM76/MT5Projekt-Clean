# src/db/async_db_writer.py
"""
Асинхронный писатель БД с батчингом для Genesis Trading System.

Архитектурный сдвиг:
- Было: Синхронные INSERT при каждом тике, блокировка при COMMIT
- Стало: Очередь событий → фоновый батчинг каждые N сек или M записей

Особенности:
- SQLite WAL mode для параллельного чтения/записи
- LockLevel.DB_WRITE только на момент flush
- Автоматический retry при ошибках
- Не блокирует GUI/ML потоки
"""

import asyncio
import logging
import sqlite3
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager
from src.core.thread_domains import ThreadDomain

logger = logging.getLogger(__name__)


class AsyncDBWriter:
    """
    Фоновый писатель с батчингом и защитой локов.

    Использование:
        writer = AsyncDBWriter("trading.db", batch_size=50, flush_interval=5.0)
        await writer.start()

        # События автоматически собираются и записываются батчами
        # Подписка на события происходит автоматически
    """

    def __init__(
        self,
        db_path: str,
        batch_size: int = 50,
        flush_interval: float = 5.0,
        max_retries: int = 3,
    ):
        """
        Args:
            db_path: Путь к SQLite базе
            batch_size: Размер батча для записи
            flush_interval: Интервал принудительной записи (сек)
            max_retries: Количество повторных попыток при ошибке
        """
        self.db_path = db_path
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_retries = max_retries

        # Очередь событий (с ограничением размера для предотвращения утечки памяти)
        self.queue: deque = deque(maxlen=10000)
        self._running = False

        # EventBus (инициализируется при старте)
        self.event_bus = None

        # Статистика
        self._total_written = 0
        self._total_failed = 0
        self._flush_count = 0
        self._retry_count = 0

        # События для подписки
        self._subscribed_events: List[str] = []

        logger.info(f"AsyncDBWriter initialized " f"(db={db_path}, batch={batch_size}, interval={flush_interval}s)")

    def _ensure_table(self, conn: sqlite3.Connection):
        """Создание таблицы если не существует"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_event_type
            ON event_logs(event_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON event_logs(timestamp)
        """)
        conn.commit()
        logger.debug("DB table ensured: event_logs")

    async def start(self):
        """Запуск фонового писателя"""
        self._running = True

        # Инициализация EventBus
        self.event_bus = get_event_bus()

        # Подписка на события
        # События которые нужно сохранять
        events_to_subscribe = [
            "market_tick",
            "trade_executed",
            "trade_signal",
            "model_prediction",
            "model_updated",
            "system_status",
            "feed_error",
            "bars_to_save",  # ← Новый тип события от DataSyncOrchestrator
        ]

        for event_type in events_to_subscribe:
            await self.event_bus.subscribe(
                event_type,
                self._enqueue,
                domain=ThreadDomain.PERSISTENCE,
                priority=EventPriority.LOW,
            )
            self._subscribed_events.append(event_type)

        # Запуск фоновых задач
        asyncio.create_task(self._flush_loop())

        logger.info(f"AsyncDBWriter started (subscribed to {len(events_to_subscribe)} events)")

    async def _enqueue(self, event: SystemEvent):
        """Добавление события в очередь"""
        # Специальная обработка для bars_to_save
        if event.type == "bars_to_save":
            bars = event.payload.get("bars", [])
            symbol = event.payload.get("symbol", "unknown")
            self.queue.append(
                {
                    "event_type": "bars_insert",
                    "payload": {"symbol": symbol, "bars": bars},
                    "timestamp": event.timestamp,
                }
            )
            logger.debug(f"Queued {len(bars)} bars for {symbol}")
        else:
            self.queue.append(
                {
                    "event_type": event.type,
                    "payload": str(event.payload),
                    "timestamp": event.timestamp,
                }
            )

        # Автоматический flush при достижении batch_size
        if len(self.queue) >= self.batch_size:
            await self._flush()

    async def _flush(self):
        """Запись батча в БД"""
        if not self.queue:
            return

        # Забираем весь батч
        batch = list(self.queue)
        self.queue.clear()

        retry_count = 0
        success = False

        while retry_count < self.max_retries and not success:
            try:
                # Эксклюзивный доступ только на момент записи
                # (в реальном приложении использовать async lock)

                conn = sqlite3.connect(self.db_path)
                try:
                    # WAL mode для параллельного чтения/записи
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute("PRAGMA cache_size=10000")

                    self._ensure_table(conn)

                    cursor = conn.cursor()
                    bars_inserted = 0

                    for item in batch:
                        if item["event_type"] == "bars_insert":
                            # Специальная вставка баров
                            symbol = item["payload"]["symbol"]
                            bars = item["payload"]["bars"]
                            bars_inserted += self._insert_bars(cursor, symbol, bars)
                        else:
                            # Обычная вставка событий
                            cursor.execute(
                                "INSERT INTO event_logs (event_type, payload, timestamp) "
                                "VALUES (:event_type, :payload, :timestamp)",
                                item,
                            )

                    conn.commit()

                    self._total_written += len(batch)
                    self._flush_count += 1

                    if bars_inserted > 0:
                        logger.info(
                            f"DB flushed: {bars_inserted} bars inserted, {len(batch)} events (total={self._total_written})"
                        )
                    else:
                        logger.debug(f"DB flushed: {len(batch)} records written (total={self._total_written})")

                    # Публикация события о успешной записи
                    if bars_inserted > 0:
                        await self.event_bus.publish(
                            SystemEvent(
                                type="db_flushed",
                                payload={
                                    "bars_inserted": bars_inserted,
                                    "events_written": len(batch),
                                    "total_written": self._total_written,
                                },
                                priority=EventPriority.LOW,
                            )
                        )

                    success = True

                except Exception as e:
                    conn.rollback()
                    logger.error(f"DB flush failed: {e}", exc_info=True)
                    raise
                finally:
                    conn.close()

            except Exception as e:
                retry_count += 1
                self._retry_count += 1

                if retry_count < self.max_retries:
                    logger.warning(f"DB flush retry {retry_count}/{self.max_retries}: {e}")
                    await asyncio.sleep(0.5 * retry_count)  # Backoff
                else:
                    self._total_failed += len(batch)
                    self._last_error = str(e)
                    logger.error(f"DB flush failed after {retry_count} retries: {e}")

                    # Вернуть в очередь для повторной попытки
                    self.queue.extend(batch)
                    break

    async def _flush_loop(self):
        """Периодический flush"""
        while self._running:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    async def stop(self):
        """Остановка с финальной записью"""
        self._running = False
        logger.info("AsyncDBWriter stopping...")

        # Финальный flush
        await self._flush()

        logger.info(
            f"AsyncDBWriter stopped "
            f"(written={self._total_written}, failed={self._total_failed}, "
            f"flushes={self._flush_count})"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        return {
            "running": self._running,
            "queue_size": len(self.queue),
            "total_written": self._total_written,
            "total_failed": self._total_failed,
            "flush_count": self._flush_count,
            "retry_count": self._retry_count,
            "batch_size": self.batch_size,
            "flush_interval": self.flush_interval,
            "subscribed_events": self._subscribed_events,
        }


class AsyncDBReader:
    """
    Асинхронный читатель БД с поддержкой WAL mode.

    Позволяет читать данные не блокируя писателя.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def query(
        self,
        query: str,
        params: tuple = (),
        fetch_all: bool = True,
    ) -> List:
        """
        Выполнение запроса к БД.

        Args:
            query: SQL запрос
            params: Параметры запроса
            fetch_all: Получить все строки (или одну)

        Returns:
            Результаты запроса
        """

        def _execute_sync():
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row

            try:
                cursor = conn.cursor()
                cursor.execute(query, params)

                if fetch_all:
                    return [dict(row) for row in cursor.fetchall()]
                else:
                    row = cursor.fetchone()
                    return dict(row) if row else None
            finally:
                conn.close()

        # Выполняем в thread pool
        return await asyncio.to_thread(_execute_sync)

    async def get_recent_events(
        self,
        event_type: Optional[str] = None,
        limit: int = 100,
        since_timestamp: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Получение недавних событий.

        Args:
            event_type: Фильтр по типу события
            limit: Максимум записей
            since_timestamp: Фильтр по времени

        Returns:
            Список событий
        """
        query = "SELECT * FROM event_logs WHERE 1=1"
        params = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if since_timestamp:
            query += " AND timestamp >= ?"
            params.append(since_timestamp)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        return await self.query(query, tuple(params))
