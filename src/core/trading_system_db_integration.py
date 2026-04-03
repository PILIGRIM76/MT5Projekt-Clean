"""
Интеграция MultiDatabaseManager в TradingSystem.
Этот модуль расширяет TradingSystem поддержкой мульти-базовой архитектуры.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TradingSystemDBMixin:
    """
    Миксин для добавления поддержки мульти-баз данных в TradingSystem.

    Использование:
        class TradingSystem(TradingSystemDBMixin, QObject):
            ...
    """

    def __init__(self, *args, **kwargs):
        # Инициализация мульти-БД менеджера
        self.multi_db_manager = None
        self._multi_db_enabled = False

        # Вызов родительского __init__
        super().__init__(*args, **kwargs)

    def initialize_multi_database(self, config) -> bool:
        """
        Инициализация мульти-базовой архитектуры.

        Args:
            config: Конфигурация TradingSystem

        Returns:
            bool: True если успешно инициализировано
        """
        try:
            from src.db.multi_database_manager import DatabaseConfig, MultiDatabaseManager

            logger.info("Инициализация MultiDatabaseManager...")

            # Создание конфигурации из переменных окружения
            self.multi_db_manager = MultiDatabaseManager.from_env()

            # Проверка доступности БД
            status = self.multi_db_manager.get_status()

            logger.info("Статус подключения к БД:")
            for db_name, is_available in status.items():
                status_icon = "✓" if is_available else "✗"
                logger.info(f"  {status_icon} {db_name}")

            # Включение мульти-БД режима если хотя бы 3 БД доступны
            available_count = sum(status.values())
            self._multi_db_enabled = available_count >= 3

            if self._multi_db_enabled:
                logger.info(f"✓ Мульти-БД режим активирован ({available_count}/6 БД доступно)")

                # Интеграция с существующими компонентами
                self._integrate_with_components()

                return True
            else:
                logger.warning(f"⚠ Мульти-БД режим отключен (только {available_count}/6 БД доступно)")
                logger.warning("  Используется режим обратной совместимости (SQLite + FAISS)")
                return False

        except Exception as e:
            logger.error(f"Ошибка инициализации MultiDatabaseManager: {e}")
            logger.debug("Откат к SQLite + FAISS")
            return False

    def _integrate_with_components(self):
        """Интеграция мульти-БД с существующими компонентами."""

        if not self._multi_db_enabled or not self.multi_db_manager:
            return

        logger.info("Интеграция MultiDatabaseManager с компонентами...")

        # 1. Интеграция с DatabaseManager
        if hasattr(self, "db_manager") and self.db_manager:
            logger.info("  → Интеграция с DatabaseManager")
            self.db_manager.multi_db_manager = self.multi_db_manager

        # 2. Интеграция с VectorDBManager
        if hasattr(self, "vector_db_manager") and self.vector_db_manager:
            logger.info("  → Интеграция с VectorDBManager")

            # Проверка доступности Qdrant
            if self.multi_db_manager.is_available("qdrant"):
                qdrant = self.multi_db_manager.get_qdrant()
                self.vector_db_manager.qdrant_adapter = qdrant
                logger.info("    ✓ Qdrant подключен к VectorDBManager")
            else:
                logger.warning("    ⚠ Qdrant недоступен, используется локальный FAISS")

        # 3. Интеграция с DataProvider
        if hasattr(self, "data_provider") and self.data_provider:
            logger.info("  → Интеграция с DataProvider")

            # Проверка доступности TimescaleDB/QuestDB
            if self.multi_db_manager.is_available("timescaledb"):
                self.data_provider.timescaledb_adapter = self.multi_db_manager.get_timescaledb()
                logger.info("    ✓ TimescaleDB подключен для свечных данных")

            elif self.multi_db_manager.is_available("questdb"):
                self.data_provider.questdb_adapter = self.multi_db_manager.get_questdb()
                logger.info("    ✓ QuestDB подключен для свечных данных")

        # 4. Интеграция с ConsensusEngine
        if hasattr(self, "consensus_engine") and self.consensus_engine:
            logger.info("  → Интеграция с ConsensusEngine")

            # Проверка доступности Redis
            if self.multi_db_manager.is_available("redis"):
                self.consensus_engine.redis_adapter = self.multi_db_manager.get_redis()
                logger.info("    ✓ Redis подключен для кэширования сигналов")

        # 5. Интеграция с KnowledgeGraphQuerier
        if hasattr(self, "knowledge_graph_querier") and self.knowledge_graph_querier:
            logger.info("  → Интеграция с KnowledgeGraphQuerier")

            if self.multi_db_manager.is_available("neo4j"):
                self.knowledge_graph_querier.neo4j_driver = self.multi_db_manager.get_neo4j_driver()
                logger.info("    ✓ Neo4j подключен для графа знаний")

        logger.info("✓ Интеграция компонентов завершена")

    def get_db_statistics(self) -> dict:
        """
        Получение статистики по всем базам данных.

        Returns:
            dict: Статистика по БД
        """
        if not self._multi_db_enabled or not self.multi_db_manager:
            return {"multi_db_enabled": False}

        try:
            stats = self.multi_db_manager.get_stats()
            stats["multi_db_enabled"] = True
            return stats
        except Exception as e:
            logger.error(f"Ошибка получения статистики БД: {e}")
            return {"error": str(e), "multi_db_enabled": True}

    def close_multi_database(self):
        """Закрытие всех подключений к базам данных."""
        if self.multi_db_manager:
            logger.info("Закрытие мульти-базовой архитектуры...")
            self.multi_db_manager.close_all()
            logger.info("✓ Все подключения к БД закрыты")


# Функции расширения для существующих классов


def extend_database_manager(db_manager, multi_db_manager):
    """
    Расширение DatabaseManager методами для работы с мульти-БД.

    Args:
        db_manager: Исходный DatabaseManager
        multi_db_manager: MultiDatabaseManager
    """

    # Добавление ссылки на мульти-БД менеджер
    db_manager.multi_db_manager = multi_db_manager

    # Метод для получения адаптера временных рядов
    def get_time_series_adapter():
        if hasattr(db_manager, "multi_db_manager") and db_manager.multi_db_manager:
            return db_manager.multi_db_manager.get_time_series_adapter()
        return None

    db_manager.get_time_series_adapter = get_time_series_adapter

    # Метод для массовой вставки свечей
    def insert_candles_bulk(symbol: str, timeframe: str, candles_df, use_multi_db: bool = True):
        """
        Массовая вставка свечных данных с использованием TimescaleDB/QuestDB.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм
            candles_df: DataFrame со свечами
            use_multi_db: Использовать ли мульти-БД
        """
        if use_multi_db and hasattr(db_manager, "multi_db_manager"):
            ts_adapter = db_manager.multi_db_manager.get_time_series_adapter()
            if ts_adapter:
                # Преобразование timeframe
                timeframe_seconds = _timeframe_to_seconds(timeframe)

                # Вставка в TimescaleDB/QuestDB
                success = ts_adapter.insert_candles(
                    table_name="candle_data",
                    candles=candles_df,
                    symbol=symbol,
                    timeframe=timeframe_seconds,
                )

                if success:
                    logger.debug(f"✓ Свечи вставлены в TimescaleDB/QuestDB: {symbol} {timeframe}")
                    return True

        # Fallback: вставка в SQLite
        logger.debug("→ Вставка свечей в SQLite (fallback)")
        return _insert_candles_sqlite(db_manager, symbol, timeframe, candles_df)

    db_manager.insert_candles_bulk = insert_candles_bulk

    logger.info("DatabaseManager расширен методами мульти-БД")


def extend_vector_db_manager(vector_db_manager, multi_db_manager):
    """
    Расширение VectorDBManager методами для работы с Qdrant.

    Args:
        vector_db_manager: Исходный VectorDBManager
        multi_db_manager: MultiDatabaseManager
    """

    # Добавление адаптера Qdrant
    if multi_db_manager.is_available("qdrant"):
        vector_db_manager.qdrant_adapter = multi_db_manager.get_qdrant()
        vector_db_manager.use_qdrant = True
        logger.info("VectorDBManager расширен: Qdrant активирован")
    else:
        vector_db_manager.use_qdrant = False
        logger.info("VectorDBManager расширен: используется локальный FAISS")

    # Метод для поиска с приоритетом Qdrant
    def search_with_qdrant(query_text: str, embedding_model, limit: int = 10, **kwargs):
        """
        Поиск с использованием Qdrant (если доступен) или FAISS.

        Args:
            query_text: Текст запроса
            embedding_model: Модель для эмбеддингов
            limit: Количество результатов
            **kwargs: Дополнительные параметры фильтрации

        Returns:
            List[Tuple[dict, float]]: Результаты поиска (payload, score)
        """
        if hasattr(vector_db_manager, "qdrant_adapter") and vector_db_manager.qdrant_adapter:
            try:
                logger.debug("Поиск через Qdrant")
                return vector_db_manager.qdrant_adapter.search_by_text(
                    query_text=query_text, embedding_model=embedding_model, limit=limit, **kwargs
                )
            except Exception as e:
                logger.error(f"Ошибка поиска в Qdrant: {e}")
                # Fallback на FAISS

        # FAISS поиск
        logger.debug("Поиск через FAISS (fallback)")
        return vector_db_manager.search(query_text, embedding_model, limit)

    vector_db_manager.search_with_qdrant = search_with_qdrant
    logger.info("VectorDBManager расширен методом search_with_qdrant")


def extend_data_provider(data_provider, multi_db_manager):
    """
    Расширение DataProvider методами для записи в TimescaleDB/QuestDB.

    Args:
        data_provider: Исходный DataProvider
        multi_db_manager: MultiDatabaseManager
    """

    # Сохранение оригинального метода save_candle_data
    original_save = getattr(data_provider, "save_candle_data", None)

    # Добавление адаптеров
    if multi_db_manager.is_available("timescaledb"):
        data_provider.timescaledb_adapter = multi_db_manager.get_timescaledb()
        logger.info("DataProvider расширен: TimescaleDB подключен")

    if multi_db_manager.is_available("questdb"):
        data_provider.questdb_adapter = multi_db_manager.get_questdb()
        logger.info("DataProvider расширен: QuestDB подключен")

    # Новый метод для сохранения с использованием TimescaleDB/QuestDB
    def save_candle_data_enhanced(symbol: str, timeframe: str, candles_df, use_multi_db: bool = True):
        """
        Сохранение свечных данных с приоритетом TimescaleDB/QuestDB.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм
            candles_df: DataFrame со свечами
            use_multi_db: Использовать ли мульти-БД
        """
        if use_multi_db:
            # Попытка вставки в TimescaleDB
            if hasattr(data_provider, "timescaledb_adapter") and data_provider.timescaledb_adapter:
                try:
                    timeframe_seconds = _timeframe_to_seconds(timeframe)
                    success = data_provider.timescaledb_adapter.insert_candles(
                        table_name="candle_data",
                        candles=candles_df,
                        symbol=symbol,
                        timeframe=timeframe_seconds,
                    )
                    if success:
                        logger.debug(f"✓ Свечи сохранены в TimescaleDB: {symbol} {timeframe}")
                        return True
                except Exception as e:
                    logger.error(f"Ошибка записи в TimescaleDB: {e}")

            # Попытка вставки в QuestDB
            if hasattr(data_provider, "questdb_adapter") and data_provider.questdb_adapter:
                try:
                    timeframe_seconds = _timeframe_to_seconds(timeframe)
                    success = data_provider.questdb_adapter.insert_candles(
                        table_name="candle_data",
                        candles=candles_df,
                        symbol=symbol,
                        timeframe=timeframe_seconds,
                    )
                    if success:
                        logger.debug(f"✓ Свечи сохранены в QuestDB: {symbol} {timeframe}")
                        return True
                except Exception as e:
                    logger.error(f"Ошибка записи в QuestDB: {e}")

        # Fallback: SQLite
        if original_save:
            logger.debug(f"→ Сохранение свечей в SQLite (fallback): {symbol} {timeframe}")
            return original_save(symbol, timeframe, candles_df)

        return False

    data_provider.save_candle_data_enhanced = save_candle_data_enhanced

    # Переопределение оригинального метода
    data_provider.save_candle_data = save_candle_data_enhanced

    logger.info("DataProvider расширен: save_candle_data использует мульти-БД")


def _timeframe_to_seconds(timeframe: str) -> int:
    """Преобразование таймфрейма в секунды."""
    mapping = {
        "M1": 60,
        "M5": 300,
        "M15": 900,
        "M30": 1800,
        "H1": 3600,
        "H4": 14400,
        "D1": 86400,
        "W1": 604800,
        "MN1": 2592000,
    }
    return mapping.get(timeframe, 60)


def _insert_candles_sqlite(db_manager, symbol: str, timeframe: str, candles_df):
    """Вставка свечей в SQLite (fallback метод)."""
    try:
        session = db_manager.Session()

        for _, row in candles_df.iterrows():
            from src.db.database_manager import CandleData

            candle = CandleData(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=row.get("timestamp") or row.name,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_volume=int(row.get("tick_volume", 0)),
            )
            session.merge(candle)  # merge вместо add для обновления существующих

        session.commit()
        session.close()
        return True

    except Exception as e:
        logger.error(f"Ошибка вставки в SQLite: {e}")
        return False
