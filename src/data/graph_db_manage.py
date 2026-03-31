# Этот блок кода не будет выполнен, так как он определяет класс,
# который будет использоваться в последующих шагах разработки.
# Это демонстрация реализации коннектора.

# Файл: src/data/graph_db_manager.py

import logging
from typing import Any, Dict, List

from neo4j import GraphDatabase, exceptions

logger = logging.getLogger(__name__)


class GraphDBManager:
    """
    Сервис для управления подключением и выполнением запросов
    к графовой базе данных Neo4j.
    """

    def __init__(self, uri: str, user: str, password: str, db_name: str):
        self.db_name = db_name
        try:
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            self._driver.verify_connectivity()
            logger.info("Успешное подключение к Neo4j.")
            self._create_constraints()
        except exceptions.AuthError as e:
            logger.error(f"Ошибка аутентификации в Neo4j: {e}")
            self._driver = None
        except exceptions.ServiceUnavailable as e:
            logger.error(f"Не удалось подключиться к Neo4j. Сервер недоступен: {e}")
            self._driver = None

    def close(self):
        if self._driver is not None:
            self._driver.close()
            logger.info("Соединение с Neo4j закрыто.")

    def _create_constraints(self):
        """Создает уникальные ограничения для узлов, чтобы избежать дубликатов."""
        with self._driver.session(database=self.db_name) as session:
            session.run("CREATE CONSTRAINT entity_name_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.name IS UNIQUE")
        logger.info("Уникальное ограничение для :Entity(name) создано или уже существует.")

    def execute_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Выполняет произвольный Cypher-запрос."""
        if self._driver is None:
            logger.error("Драйвер Neo4j не инициализирован. Запрос не может быть выполнен.")
            return []

        with self._driver.session(database=self.db_name) as session:
            try:
                result = session.run(query, parameters)
                return [record.data() for record in result]
            except exceptions.CypherSyntaxError as e:
                logger.error(f"Синтаксическая ошибка в Cypher-запросе: {e}")
                return []

    def add_relation(
        self, source_entity: str, relation: str, target_entity: str, source_label: str = "Entity", target_label: str = "Entity"
    ):
        """
        Создает два узла (если они не существуют) и связь между ними.
        Пример: add_relation("ФРС", "ПОВЫШАЕТ_СТАВКУ", "USD")
        """
        query = (
            f"MERGE (a:{source_label} {{name: $source_name}}) "
            f"MERGE (b:{target_label} {{name: $target_name}}) "
            f"MERGE (a)-[r:{relation}]->(b) "
            "RETURN a.name, type(r), b.name"
        )
        params = {"source_name": source_entity, "target_name": target_entity}
        result = self.execute_query(query, params)
        if result:
            logger.info(f"Создана или обновлена связь: {result[0]}")
        else:
            logger.error(f"Не удалось создать связь: {source_entity} -> {relation} -> {target_entity}")


# Пример того, как этот класс будет инициализироваться в TradingSystem
# config = load_config()
# graph_db_manager = GraphDBManager(
#     uri=os.getenv("NEO4J_URI"),
#     user=os.getenv("NEO4J_USER"),
#     password=os.getenv("NEO4J_PASSWORD"),
#     db_name=config.graph_database.db_name
# )
