# src/db/adapters/questdb_adapter.py
"""
Адаптер для QuestDB - высокоскоростная Time-Series база данных.
Используется для хранения тиковых данных, свечей и стакана заявок.
Производительность: 1M+ записей/сек, задержка <1 мс.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import execute_values

    QUESTDB_AVAILABLE = True
except ImportError:
    QUESTDB_AVAILABLE = False
    logger.warning("psycopg2 не установлен. QuestDB адаптер отключен.")


class QuestDBAdapter:
    """
    Адаптер для подключения к QuestDB через PostgreSQL wire protocol.
    QuestDB поддерживает PostgreSQL протокол на порту 9000.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9000,
        database: str = "questdb",
        user: str = "admin",
        password: str = "quest",
        pool_size: int = 5,
        enabled: bool = True,
    ):
        self.enabled = enabled and QUESTDB_AVAILABLE
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._pool: Optional[pool.SimpleConnectionPool] = None

        if self.enabled:
            try:
                self._init_pool(pool_size)
                logger.info(f"QuestDBAdapter инициализирован: {host}:{port}")
            except Exception as e:
                logger.error(f"Ошибка подключения к QuestDB: {e}")
                self.enabled = False

    def _init_pool(self, pool_size: int):
        """Инициализация пула соединений."""
        self._pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=pool_size,
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
        )
        logger.info(f"QuestDB connection pool создан (size: {pool_size})")

    def _get_connection(self):
        """Получение соединения из пула."""
        if not self._pool:
            raise RuntimeError("QuestDB pool не инициализирован")
        return self._pool.getconn()

    def _release_connection(self, conn):
        """Возврат соединения в пул."""
        if self._pool:
            self._pool.putconn(conn)

    def create_table(self, table_name: str, symbol: str):
        """
        Создание таблицы для символа с оптимизацией для временных рядов.
        Используем WAL (Write-Ahead Log) для надежности.
        """
        if not self.enabled:
            return False

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                # QuestDB использует специфичный синтаксис для временных рядов
                query = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    symbol SYMBOL,
                    timeframe INT,
                    timestamp TIMESTAMP,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume LONG,
                    tick_volume LONG,
                    spread INT,
                    created_at TIMESTAMP
                ) TIMESTAMP(timestamp) PARTITION BY DAY WAL;
                """
                cur.execute(query)
                conn.commit()
                logger.info(f"Таблица QuestDB '{table_name}' создана/проверена")
                return True
        except Exception as e:
            logger.error(f"Ошибка создания таблицы QuestDB: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self._release_connection(conn)

    def insert_candles(
        self,
        table_name: str,
        candles: pd.DataFrame,
        symbol: str,
        timeframe: int,
    ) -> bool:
        """
        Пакетная вставка свечных данных.
        Оптимизировано для высокой производительности.
        """
        if not self.enabled or candles.empty:
            return False

        conn = None
        try:
            conn = self._get_connection()

            # Подготовка данных
            records = []
            for _, row in candles.iterrows():
                records.append(
                    (
                        symbol,
                        timeframe,
                        row["timestamp"],
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        int(row.get("volume", 0)),
                        int(row.get("tick_volume", 0)),
                        int(row.get("spread", 0)),
                        datetime.utcnow(),
                    )
                )

            # Массовая вставка
            with conn.cursor() as cur:
                query = f"""
                INSERT INTO {table_name}
                (symbol, timeframe, timestamp, open, high, low, close, volume, tick_volume, spread, created_at)
                VALUES %s
                """
                execute_values(cur, query, records)
                conn.commit()

            logger.debug(f"QuestDB: Вставлено {len(records)} свечей в {table_name}")
            return True

        except Exception as e:
            logger.error(f"Ошибка вставки в QuestDB: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self._release_connection(conn)

    def get_candles(
        self,
        table_name: str,
        symbol: str,
        timeframe: int,
        start_time: datetime,
        end_time: datetime,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Получение свечных данных за период.
        """
        if not self.enabled:
            return pd.DataFrame()

        conn = None
        try:
            conn = self._get_connection()

            query = f"""
            SELECT timestamp, open, high, low, close, volume, tick_volume, spread
            FROM {table_name}
            WHERE symbol = %s
              AND timeframe = %s
              AND timestamp >= %s
              AND timestamp <= %s
            ORDER BY timestamp ASC
            """

            params = [symbol, timeframe, start_time, end_time]

            if limit:
                query += " LIMIT %s"
                params.append(limit)

            with conn.cursor() as cur:
                cur.execute(query, params)
                columns = [desc[0] for desc in cur.description]
                data = cur.fetchall()

            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data, columns=columns)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.set_index("timestamp", inplace=True)

            return df

        except Exception as e:
            logger.error(f"Ошибка чтения из QuestDB: {e}")
            return pd.DataFrame()
        finally:
            if conn:
                self._release_connection(conn)

    def get_latest_candle(
        self,
        table_name: str,
        symbol: str,
        timeframe: int,
    ) -> Optional[Dict[str, Any]]:
        """Получение последней свечи."""
        if not self.enabled:
            return None

        conn = None
        try:
            conn = self._get_connection()

            query = f"""
            SELECT timestamp, open, high, low, close, volume, tick_volume, spread
            FROM {table_name}
            WHERE symbol = %s AND timeframe = %s
            ORDER BY timestamp DESC
            LIMIT 1
            """

            with conn.cursor() as cur:
                cur.execute(query, (symbol, timeframe))
                row = cur.fetchone()

            if not row:
                return None

            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))

        except Exception as e:
            logger.error(f"Ошибка чтения последней свечи из QuestDB: {e}")
            return None
        finally:
            if conn:
                self._release_connection(conn)

    def delete_old_data(self, table_name: str, older_than_days: int) -> int:
        """Удаление старых данных для экономии места."""
        if not self.enabled:
            return 0

        conn = None
        try:
            conn = self._get_connection()

            query = f"""
            DELETE FROM {table_name}
            WHERE timestamp < NOW() - INTERVAL '{older_than_days} DAYS'
            """

            with conn.cursor() as cur:
                cur.execute(query)
                deleted_count = cur.rowcount
                conn.commit()

            logger.info(f"QuestDB: Удалено {deleted_count} старых записей из {table_name}")
            return deleted_count

        except Exception as e:
            logger.error(f"Ошибка удаления данных из QuestDB: {e}")
            if conn:
                conn.rollback()
            return 0
        finally:
            if conn:
                self._release_connection(conn)

    def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """Получение статистики по таблице."""
        if not self.enabled:
            return {}

        conn = None
        try:
            conn = self._get_connection()

            query = f"""
            SELECT
                COUNT(*) as total_rows,
                MIN(timestamp) as first_timestamp,
                MAX(timestamp) as last_timestamp,
                COUNT(DISTINCT symbol) as unique_symbols
            FROM {table_name}
            """

            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()

            if not row:
                return {}

            return {
                "total_rows": row[0],
                "first_timestamp": row[1],
                "last_timestamp": row[2],
                "unique_symbols": row[3],
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики QuestDB: {e}")
            return {}
        finally:
            if conn:
                self._release_connection(conn)

    def close(self):
        """Закрытие всех соединений."""
        if self._pool:
            self._pool.closeall()
            logger.info("QuestDB connection pool закрыт")
