# src/data/knowledge_graph_querier.py

import logging
from datetime import datetime, timedelta
from operator import or_
from typing import Dict, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import aliased

from src.db.database_manager import DatabaseManager, Entity, Relation

#  Импортируем модели и SQLAlchemy компоненты ---


logger = logging.getLogger(__name__)


class KnowledgeGraphQuerier:
    """
    Предоставляет высокоуровневый интерфейс для выполнения запросов
    к графу знаний, эмулированному на реляционной БД.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def find_events_affecting_entities(
        self, target_entities: List[str], source_types: List[str], time_window: timedelta, source_entity_name=None
    ) -> List[Dict]:
        """
        Находит все связи, исходящие от указанной сущности.
        Пример: что происходит, когда "ФРС" что-то делает?

        Args:
            source_entity_name: Имя исходной сущности (например, "FED").

        Returns:
            Список словарей, каждый из которых описывает связь и целевую сущность.
        """
        session = self.db_manager.Session()
        try:
            # Создаем псевдонимы (aliases) для таблицы Entity, чтобы различать источник и цель
            source_entity = aliased(Entity)
            target_entity = aliased(Entity)

            # Строим запрос с помощью SQLAlchemy ORM
            results = (
                session.query(
                    Relation.relation_type,
                    target_entity.name.label("target_name"),
                    target_entity.entity_type.label("target_type"),
                    Relation.timestamp,
                    Relation.context_json,
                )
                .join(source_entity, Relation.source_id == source_entity.id)
                .join(target_entity, Relation.target_id == target_entity.id)
                .filter(source_entity.name == source_entity_name)
                .order_by(Relation.timestamp.desc())
                .limit(20)
                .all()
            )

            # Преобразуем результаты в более удобный формат
            return [row._asdict() for row in results]

        except Exception as e:
            logger.error(f"Ошибка при поиске исходящих связей для '{source_entity_name}': {e}")
            return []
        finally:
            session.close()

    def find_upstream_relations(self, target_entity_name: str) -> List[Dict]:
        """
        Находит все связи, входящие в указанную сущность.
        Пример: что влияет на "EURUSD"?
        """
        session = self.db_manager.Session()
        try:
            source_entity = aliased(Entity)
            target_entity = aliased(Entity)

            results = (
                session.query(
                    Relation.relation_type,
                    source_entity.name.label("source_name"),
                    source_entity.entity_type.label("source_type"),
                    Relation.timestamp,
                    Relation.context_json,
                )
                .join(source_entity, Relation.source_id == source_entity.id)
                .join(target_entity, Relation.target_id == target_entity.id)
                .filter(target_entity.name == target_entity_name)
                .order_by(Relation.timestamp.desc())
                .limit(20)
                .all()
            )
            return [row._asdict() for row in results]
        except Exception as e:
            logger.error(f"Ошибка при поиске входящих связей для '{target_entity_name}': {e}")
            return []
        finally:
            session.close()

    def find_events_affecting_entities(
        self, target_entities: List[str], source_types: List[str], time_window: timedelta
    ) -> List[Dict]:
        """
        Находит недавние события от источников определенных типов, влияющие на целевые сущности.

        Args:
            target_entities (List[str]): Список имен целевых сущностей (напр., ['USD', 'EUR']).
            source_types (List[str]): Список типов источников (напр., ['CentralBank', 'EconomicIndicator']).
            time_window (timedelta): Временное окно для поиска (напр., timedelta(hours=4)).

        Returns:
            Список словарей с информацией о найденных событиях.
        """
        session = self.db_manager.Session()
        try:
            time_threshold = datetime.utcnow() - time_window

            source_entity = aliased(Entity)
            target_entity = aliased(Entity)

            results = (
                session.query(
                    source_entity.name.label("source_name"),
                    Relation.relation_type,
                    target_entity.name.label("target_name"),
                    Relation.timestamp,
                )
                .join(source_entity, Relation.source_id == source_entity.id)
                .join(target_entity, Relation.target_id == target_entity.id)
                .filter(
                    Relation.timestamp >= time_threshold,
                    source_entity.entity_type.in_(source_types),
                    target_entity.name.in_(target_entities),
                )
                .order_by(Relation.timestamp.desc())
                .all()
            )

            return [row._asdict() for row in results]

        except Exception as e:
            logger.error(f"Ошибка при поиске влияющих событий в графе знаний: {e}")
            return []
        finally:
            session.close()

    def get_events_in_range(self, entities: List[str], start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Получает все события (связи), где участвуют указанные сущности (как источник или цель),
        в заданном диапазоне времени. Используется для генерации признаков.
        """
        session = self.db_manager.Session()
        try:
            source_entity = aliased(Entity)
            target_entity = aliased(Entity)

            # Ищем связи, где указанные сущности являются либо источником, либо целью
            results = (
                session.query(
                    Relation.timestamp,
                    Relation.relation_type,
                    source_entity.name.label("source_name"),
                    source_entity.entity_type.label("source_type"),
                    target_entity.name.label("target_name"),
                    Relation.context_json,
                )
                .join(source_entity, Relation.source_id == source_entity.id)
                .join(target_entity, Relation.target_id == target_entity.id)
                .filter(
                    Relation.timestamp >= start_date,
                    Relation.timestamp <= end_date,
                    or_(source_entity.name.in_(entities), target_entity.name.in_(entities)),
                )
                .order_by(Relation.timestamp.asc())
                .all()
            )

            return [row._asdict() for row in results]

        except Exception as e:
            logger.error(f"Ошибка при выборке исторических событий для признаков: {e}")
            return []
        finally:
            session.close()
