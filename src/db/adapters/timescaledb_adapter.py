# src/db/adapters/timescaledb_adapter.py
"""
Адаптер для TimescaleDB - PostgreSQL extension для временных рядов.
Используется как альтернатива QuestDB с полной SQL совместимостью.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class TimescaleDBAdapter:
    """
    Адаптер для TimescaleDB через SQLAlchemy.
    TimescaleDB - это extension для PostgreSQL, добавляющий автоматическое
    партиционирование (hypertables) и функции для временных рядов.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "trading",
        user: str = "trading_user",
        password: str = "secure_password",
        enabled: bool = True,
    ):
        self.enabled = enabled
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password

        # Connection URL для SQLAlchemy
        self._connection_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

        self._engine = None
        self._session_factory = None

        if self.enabled:
            try:
                self._init_engine()
                logger.info(f"TimescaleDBAdapter инициализирован: {host}:{port}")
            except Exception as e:
                logger.error(f"Ошибка подключения к TimescaleDB: {e}")
                self.enabled = False

    def _init_engine(self):
        """Инициализация SQLAlchemy engine."""
        self._engine = create_engine(
            self._connection_url,
            pool_size=20,
            max_overflow=40,
            pool_pre_ping=True,  # Проверка соединений перед использованием
            echo=False,
        )
        self._session_factory = sessionmaker(bind=self._engine)
        logger.info("TimescaleDB SQLAlchemy engine создан")

    def _get_session(self):
        """Получение сессии SQLAlchemy."""
        return self._session_factory()

    def create_hypertable(self, table_name: str):
        """
        Создание hypertable для временных рядов.
        Hypertable автоматически партиционируется по времени.
        """
        if not self.enabled:
            return False

        session = None
        try:
            session = self._get_session()

            # Сначала создаем обычную таблицу
            create_table_query = text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id BIGSERIAL,
                symbol VARCHAR(50) NOT NULL,
                timeframe INTEGER NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume BIGINT,
                tick_volume BIGINT,
                spread INTEGER,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """)
            session.execute(create_table_query)

            # Создаем индекс для эффективного поиска
            index_query = text(f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_symbol_time
            ON {table_name} (symbol, timestamp DESC);
            """)
            session.execute(index_query)

            # Превращаем в hypertable (TimescaleDB специфика)
            hypertable_query = text(f"""
            SELECT create_hypertable('{table_name}', 'timestamp', if_not_exists => TRUE);
            """)
            session.execute(hypertable_query)

            # Добавляем compression policy (сжатие старых данных)
            compression_query = text(f"""
            ALTER TABLE {table_name} SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'symbol'
            );
            """)
            session.execute(compression_query)

            # Политика сжатия для данных старше 7 дней
            compress_policy_query = text(f"""
            SELECT add_compression_policy('{table_name}', INTERVAL '7 days', if_not_exists => TRUE);
            """)
            session.execute(compress_policy_query)

            session.commit()
            logger.info(f"Hypertable '{table_name}' создан/проверен")
            return True

        except Exception as e:
            logger.error(f"Ошибка создания hypertable: {e}")
            if session:
                session.rollback()
            return False
        finally:
            if session:
                session.close()

    def insert_candles(
        self,
        table_name: str,
        candles: pd.DataFrame,
        symbol: str,
        timeframe: int,
    ) -> bool:
        """
        Пакетная вставка свечных данных с использованием COPY.
        """
        if not self.enabled or candles.empty:
            return False

        session = None
        try:
            session = self._get_session()

            # Подготовка данных
            candles_copy = candles.copy()
            candles_copy["symbol"] = symbol
            candles_copy["timeframe"] = timeframe
            candles_copy["created_at"] = datetime.utcnow()

            # Массовая вставка через pandas to_sql
            candles_copy.to_sql(
                table_name,
                self._engine,
                if_exists="append",
                index=True,
                index_label="timestamp",
                method="multi",  # Пакетная вставка
                chunksize=1000,
            )

            logger.debug(f"TimescaleDB: Вставлено {len(candles)} свечей в {table_name}")
            return True

        except Exception as e:
            logger.error(f"Ошибка вставки в TimescaleDB: {e}")
            if session:
                session.rollback()
            return False
        finally:
            if session:
                session.close()

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
        Получение свечных данных за период с использованием time_bucket.
        """
        if not self.enabled:
            return pd.DataFrame()

        session = None
        try:
            query = text(f"""
            SELECT timestamp, open, high, low, close, volume, tick_volume, spread
            FROM {table_name}
            WHERE symbol = :symbol
              AND timeframe = :timeframe
              AND timestamp >= :start_time
              AND timestamp <= :end_time
            ORDER BY timestamp ASC
            {'LIMIT :limit' if limit else ''}
            """)

            params = {
                "symbol": symbol,
                "timeframe": timeframe,
                "start_time": start_time,
                "end_time": end_time,
            }
            if limit:
                params["limit"] = limit

            df = pd.read_sql(query, self._engine, params=params)

            if not df.empty:
                df.set_index("timestamp", inplace=True)

            return df

        except Exception as e:
            logger.error(f"Ошибка чтения из TimescaleDB: {e}")
            return pd.DataFrame()
        finally:
            if session:
                session.close()

    def get_candles_time_bucket(
        self,
        table_name: str,
        symbol: str,
        timeframe: int,
        bucket_width: str,  # '1 minute', '5 minutes', '1 hour', etc.
        start_time: datetime,
        end_time: datetime,
    ) -> pd.DataFrame:
        """
        Агрегация свечных данных с использованием time_bucket (TimescaleDB функция).
        Полезно для даунсемплинга данных.
        """
        if not self.enabled:
            return pd.DataFrame()

        session = None
        try:
            query = text(f"""
            SELECT
                time_bucket('{bucket_width}', timestamp) AS bucket,
                first(open, timestamp) AS open,
                max(high) AS high,
                min(low) AS low,
                last(close, timestamp) AS close,
                sum(volume) AS volume,
                sum(tick_volume) AS tick_volume
            FROM {table_name}
            WHERE symbol = :symbol
              AND timeframe = :timeframe
              AND timestamp >= :start_time
              AND timestamp <= :end_time
            GROUP BY bucket
            ORDER BY bucket ASC
            """)

            params = {
                "symbol": symbol,
                "timeframe": timeframe,
                "start_time": start_time,
                "end_time": end_time,
            }

            df = pd.read_sql(query, self._engine, params=params)

            if not df.empty:
                df.set_index("bucket", inplace=True)
                df.rename(columns={"bucket": "timestamp"}, inplace=True)

            return df

        except Exception as e:
            logger.error(f"Ошибка time_bucket запроса: {e}")
            return pd.DataFrame()
        finally:
            if session:
                session.close()

    def get_latest_candle(
        self,
        table_name: str,
        symbol: str,
        timeframe: int,
    ) -> Optional[Dict[str, Any]]:
        """Получение последней свечи."""
        if not self.enabled:
            return None

        session = None
        try:
            query = text(f"""
            SELECT timestamp, open, high, low, close, volume, tick_volume, spread
            FROM {table_name}
            WHERE symbol = :symbol AND timeframe = :timeframe
            ORDER BY timestamp DESC
            LIMIT 1
            """)

            result = session.execute(query, {"symbol": symbol, "timeframe": timeframe}).fetchone()

            if not result:
                return None

            return {
                "timestamp": result.timestamp,
                "open": result.open,
                "high": result.high,
                "low": result.low,
                "close": result.close,
                "volume": result.volume,
                "tick_volume": result.tick_volume,
                "spread": result.spread,
            }

        except Exception as e:
            logger.error(f"Ошибка чтения последней свечи: {e}")
            return None
        finally:
            if session:
                session.close()

    def delete_old_data(self, table_name: str, older_than_days: int) -> int:
        """Удаление старых данных."""
        if not self.enabled:
            return 0

        session = None
        try:
            query = text(f"""
            DELETE FROM {table_name}
            WHERE timestamp < NOW() - INTERVAL '{older_than_days} days'
            """)

            result = session.execute(query)
            deleted_count = result.rowcount
            session.commit()

            logger.info(f"TimescaleDB: Удалено {deleted_count} старых записей")
            return deleted_count

        except Exception as e:
            logger.error(f"Ошибка удаления данных: {e}")
            if session:
                session.rollback()
            return 0
        finally:
            if session:
                session.close()

    def get_continuous_agrate(
        self,
        table_name: str,
        symbol: str,
        timeframe: int,
        bucket_width: str,
        start_time: datetime,
        end_time: datetime,
    ) -> pd.DataFrame:
        """
        Получение агрегированных данных с использованием continuous aggregates.
        Continuous aggregates автоматически обновляются и очень быстрые.
        """
        if not self.enabled:
            return pd.DataFrame()

        session = None
        try:
            # Создание continuous aggregate (если не существует)
            mat_table = f"{table_name}_agg_{bucket_width.replace(' ', '_')}"

            create_agg_query = text(f"""
            CREATE MATERIALIZED VIEW IF NOT EXISTS {mat_table}
            WITH (timescaledb.continuous) AS
            SELECT
                symbol,
                timeframe,
                time_bucket('{bucket_width}', timestamp) AS bucket,
                first(open, timestamp) AS open,
                max(high) AS high,
                min(low) AS low,
                last(close, timestamp) AS close,
                sum(volume) AS volume
            FROM {table_name}
            GROUP BY symbol, timeframe, bucket
            WITH NO DATA;
            """)
            session.execute(create_agg_query)
            session.commit()

            # Запрос к агрегату
            query = text(f"""
            SELECT bucket AS timestamp, open, high, low, close, volume
            FROM {mat_table}
            WHERE symbol = :symbol
              AND timeframe = :timeframe
              AND bucket >= :start_time
              AND bucket <= :end_time
            ORDER BY bucket ASC
            """)

            params = {
                "symbol": symbol,
                "timeframe": timeframe,
                "start_time": start_time,
                "end_time": end_time,
            }

            df = pd.read_sql(query, self._engine, params=params)

            if not df.empty:
                df.set_index("timestamp", inplace=True)

            return df

        except Exception as e:
            logger.error(f"Ошибка continuous aggregate: {e}")
            if session:
                session.rollback()
            return pd.DataFrame()
        finally:
            if session:
                session.close()

    def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """Получение статистики по hypertable."""
        if not self.enabled:
            return {}

        session = None
        try:
            query = text(f"""
            SELECT
                COUNT(*) as total_rows,
                MIN(timestamp) as first_timestamp,
                MAX(timestamp) as last_timestamp,
                COUNT(DISTINCT symbol) as unique_symbols
            FROM {table_name}
            """)

            result = session.execute(query).fetchone()

            return {
                "total_rows": result.total_rows,
                "first_timestamp": result.first_timestamp,
                "last_timestamp": result.last_timestamp,
                "unique_symbols": result.unique_symbols,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}
        finally:
            if session:
                session.close()

    def close(self):
        """Закрытие соединений."""
        if self._engine:
            self._engine.dispose()
            logger.info("TimescaleDB engine закрыт")
