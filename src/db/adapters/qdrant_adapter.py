# src/db/adapters/qdrant_adapter.py
"""
Адаптер для Qdrant - высокоскоростная векторная база данных на Rust.
Используется для RAG поиска, семантического поиска новостей и похожих паттернов.
Производительность: 100k+ векторов в памяти, продвинутая фильтрация.
"""

import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from qdrant_client.http.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        Range,
        VectorParams,
    )

    QDRANT_AVAILABLE = True
except ImportError as e:
    QDRANT_AVAILABLE = False
    logger.warning(f"qdrant-client не установлен или ошибка импорта: {e}. Qdrant адаптер отключен.")


class QdrantAdapter:
    """
    Адаптер для Qdrant vector database.
    Поддерживает локальный режим (in-memory/SQLite) и серверный режим.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        grpc_port: int = 6334,
        collection_name: str = "trading_rag",
        vector_size: int = 384,  # all-MiniLM-L6-v2
        db_path: Optional[str] = None,
        enabled: bool = True,
    ):
        self.enabled = enabled and QDRANT_AVAILABLE
        self.host = host
        self.port = port
        self.grpc_port = grpc_port
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.db_path = db_path

        self._client: Optional[QdrantClient] = None

        if self.enabled:
            try:
                self._init_client()
                logger.info(f"QdrantAdapter инициализирован: {host}:{port}")
            except Exception as e:
                logger.error(f"Ошибка подключения к Qdrant: {e}")
                self.enabled = False

    def _init_client(self):
        """Инициализация клиента Qdrant."""
        if self.db_path:
            # Локальный режим (persistent storage)
            self._client = QdrantClient(
                path=self.db_path,
                force_disable_check_same_thread=True,
            )
            logger.info(f"Qdrant локальный режим: {self.db_path}")
        else:
            # Серверный режим
            self._client = QdrantClient(
                host=self.host,
                port=self.port,
                grpc_port=self.grpc_port,
            )
            logger.info(f"Qdrant серверный режим: {self.host}:{self.port}")

    def create_collection(self) -> bool:
        """
        Создание коллекции для векторного поиска.
        """
        if not self.enabled or not self._client:
            return False

        try:
            # Проверяем существует ли коллекция
            collections = self._client.get_collections()
            if any(c.name == self.collection_name for c in collections.collections):
                logger.info(f"Коллекция '{self.collection_name}' уже существует")
                return True

            # Создаем коллекцию
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE,  # Косинусное сходство
                ),
                # Оптимизация для частых запросов с фильтрацией
                optimizers_config=models.OptimizersConfig(
                    indexing_threshold=20000,  # Порог индексации
                ),
            )

            # Создаем индексы для часто используемых полей фильтрации
            self._client.create_payload_index(
                collection_name=self.collection_name,
                field_name="timestamp",
                field_schema=models.PayloadSchemaType.INTEGER,
            )
            self._client.create_payload_index(
                collection_name=self.collection_name,
                field_name="symbol",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            self._client.create_payload_index(
                collection_name=self.collection_name,
                field_name="content_type",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

            logger.info(f"Коллекция '{self.collection_name}' создана")
            return True

        except Exception as e:
            logger.error(f"Ошибка создания коллекции Qdrant: {e}")
            return False

    def upsert(
        self,
        vectors: Union[List[List[float]], np.ndarray],
        payloads: List[Dict[str, Any]],
        ids: Optional[List[int]] = None,
    ) -> bool:
        """
        Добавление векторов с метаданными.
        """
        if not self.enabled or not self._client:
            return False

        try:
            if isinstance(vectors, np.ndarray):
                vectors = vectors.tolist()

            # Генерируем ID если не предоставлены
            if ids is None:
                # Используем текущий timestamp как основу для ID
                base_id = int(datetime.now().timestamp() * 1000)
                ids = list(range(base_id, base_id + len(vectors)))

            # Создаем точки для вставки
            points = [
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
                for point_id, vector, payload in zip(ids, vectors, payloads)
            ]

            # Массовая вставка
            result = self._client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )

            logger.debug(f"Qdrant: Вставлено {len(points)} векторов")
            return result.status == models.UpdateStatus.COMPLETED

        except Exception as e:
            logger.error(f"Ошибка вставки в Qdrant: {e}")
            return False

    def search(
        self,
        query_vector: Union[List[float], np.ndarray],
        limit: int = 10,
        score_threshold: float = 0.5,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Поиск похожих векторов с фильтрацией.
        Возвращает список (payload, score).
        """
        if not self.enabled or not self._client:
            return []

        try:
            if isinstance(query_vector, np.ndarray):
                query_vector = query_vector.tolist()

            # Построение фильтра
            query_filter = None
            if filter_conditions:
                conditions = []

                # Фильтр по символу
                if "symbol" in filter_conditions:
                    conditions.append(
                        FieldCondition(
                            key="symbol",
                            match=MatchValue(value=filter_conditions["symbol"]),
                        )
                    )

                # Фильтр по типу контента
                if "content_type" in filter_conditions:
                    conditions.append(
                        FieldCondition(
                            key="content_type",
                            match=MatchValue(value=filter_conditions["content_type"]),
                        )
                    )

                # Фильтр по временному диапазону
                if "timestamp_from" in filter_conditions:
                    conditions.append(
                        FieldCondition(
                            key="timestamp",
                            range=Range(gte=filter_conditions["timestamp_from"]),
                        )
                    )
                if "timestamp_to" in filter_conditions:
                    conditions.append(
                        FieldCondition(
                            key="timestamp",
                            range=Range(lte=filter_conditions["timestamp_to"]),
                        )
                    )

                if conditions:
                    query_filter = Filter(must=conditions)

            # Поиск
            results = self._client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            )

            # Форматирование результатов
            return [(result.payload, result.score) for result in results]

        except Exception as e:
            logger.error(f"Ошибка поиска в Qdrant: {e}")
            return []

    def search_by_text(
        self,
        query_text: str,
        embedding_model: Any,
        limit: int = 10,
        **filter_conditions,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Семантический поиск по тексту с использованием embedding модели.
        """
        try:
            # Генерация эмбеддинга для запроса
            query_embedding = embedding_model.encode(
                query_text,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )

            return self.search(
                query_vector=query_embedding,
                limit=limit,
                filter_conditions=filter_conditions,
            )

        except Exception as e:
            logger.error(f"Ошибка текстового поиска в Qdrant: {e}")
            return []

    def find_similar_patterns(
        self,
        pattern_vector: Union[List[float], np.ndarray],
        symbol: str,
        timeframe: int,
        limit: int = 5,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Поиск похожих рыночных паттернов для конкретного символа.
        """
        return self.search(
            query_vector=pattern_vector,
            limit=limit,
            filter_conditions={
                "symbol": symbol,
                "timeframe": timeframe,
                "content_type": "market_pattern",
            },
        )

    def find_similar_news(
        self,
        query_text: str,
        embedding_model: Any,
        symbol: Optional[str] = None,
        days_back: int = 7,
        limit: int = 10,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Поиск похожих новостей с фильтрацией по символу и времени.
        """
        filter_conditions = {
            "content_type": "news",
            "timestamp_from": int((datetime.now() - timedelta(days=days_back)).timestamp()),
        }

        if symbol:
            filter_conditions["symbol"] = symbol

        return self.search_by_text(
            query_text=query_text,
            embedding_model=embedding_model,
            limit=limit,
            **filter_conditions,
        )

    def delete_old_documents(
        self,
        older_than_days: int,
        content_type: Optional[str] = None,
    ) -> int:
        """Удаление старых документов."""
        if not self.enabled or not self._client:
            return 0

        try:
            from qdrant_client.http.models import FieldCondition, Filter, Range

            timestamp_threshold = int((datetime.now() - timedelta(days=older_than_days)).timestamp())

            conditions = [
                FieldCondition(
                    key="timestamp",
                    range=Range(lt=timestamp_threshold),
                )
            ]

            if content_type:
                conditions.append(
                    FieldCondition(
                        key="content_type",
                        match=MatchValue(value=content_type),
                    )
                )

            # Получаем ID точек для удаления
            results = self._client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(must=conditions),
                limit=10000,  # Максимальный лимит
            )

            points_to_delete = [point.id for point in results[0]]

            if not points_to_delete:
                return 0

            # Массовое удаление
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=points_to_delete),
            )

            logger.info(f"Qdrant: Удалено {len(points_to_delete)} старых документов")
            return len(points_to_delete)

        except Exception as e:
            logger.error(f"Ошибка удаления документов из Qdrant: {e}")
            return 0

    def get_collection_stats(self) -> Dict[str, Any]:
        """Получение статистики коллекции."""
        if not self.enabled or not self._client:
            return {}

        try:
            info = self._client.get_collection(self.collection_name)

            return {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики Qdrant: {e}")
            return {}

    def batch_search(
        self,
        query_vectors: List[Union[List[float], np.ndarray]],
        limit: int = 5,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[List[Tuple[Dict[str, Any], float]]]:
        """
        Пакетный поиск нескольких векторов.
        """
        if not self.enabled or not self._client:
            return []

        try:
            # Конвертация в list если numpy
            vectors = [v.tolist() if isinstance(v, np.ndarray) else v for v in query_vectors]

            results = self._client.search_batch(
                collection_name=self.collection_name,
                requests=[
                    models.SearchRequest(
                        vector=vector,
                        limit=limit,
                        filter=(
                            Filter(
                                must=[
                                    FieldCondition(key=k, match=MatchValue(value=v))
                                    for k, v in (filter_conditions or {}).items()
                                ]
                            )
                            if filter_conditions
                            else None
                        ),
                    )
                    for vector in vectors
                ],
            )

            # Форматирование результатов
            return [[(result.payload, result.score) for result in batch_results] for batch_results in results]

        except Exception as e:
            logger.error(f"Ошибка пакетного поиска в Qdrant: {e}")
            return []

    def close(self):
        """Закрытие соединений."""
        if self._client:
            # Qdrant client не имеет явного метода close
            logger.info("Qdrant client закрыт")
