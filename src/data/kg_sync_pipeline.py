# -*- coding: utf-8 -*-
"""
src/data/kg_sync_pipeline.py — Синхронизация данных с Knowledge Graph

Поток:
1. Новые данные от коннекторов (новости, Binance, RSS)
2. Извлечение entities и связей
3. Обновление SQLite KG (Entity/Relation таблицы)
4. Обновление FAISS индекса для семантического поиска
5. Уведомление ConsensusEngine об изменениях
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.data.unified_news_connector import NewsItem

logger = logging.getLogger(__name__)


class KGSyncPipeline:
    """
    Pipeline для синхронизации внешних данных с Knowledge Graph.

    Использует:
    - SQLite Entity/Relation таблицы (эмулированный KG)
    - FAISS индекс для семантического поиска
    - Symbol map для связывания новостей с инструментами
    """

    # Паттерны для извлечения entities
    _ENTITY_PATTERNS = {
        "currency": re.compile(r"\b(EUR|GBP|JPY|USD|CHF|CAD|AUD|NZD)\b", re.IGNORECASE),
        "crypto": re.compile(r"\b(BTC|ETH|BNB|SOL|XRP|ADA|DOGE|DOT|MATIC)\b", re.IGNORECASE),
        "commodity": re.compile(r"\b(GOLD|SILVER|OIL|GAS|WHEAT|SUGAR)\b", re.IGNORECASE),
        "institution": re.compile(r"\b(Fed|ECB|BOJ|BOE|SNB|RBA|IMF|World Bank)\b"),
        "event": re.compile(r"\b(rate decision|CPI|NFP|GDP|inflation|unemployment|PMI)\b", re.IGNORECASE),
    }

    def __init__(
        self,
        db_manager: Optional[Any] = None,
        vector_db_manager: Optional[Any] = None,
        kg_querier: Optional[Any] = None,
    ):
        self.db_manager = db_manager
        self.vector_db_manager = vector_db_manager
        self.kg_querier = kg_querier

        # Статистика
        self._stats = {
            "items_processed": 0,
            "entities_extracted": 0,
            "relations_created": 0,
            "vdb_documents_added": 0,
            "errors": 0,
        }

        logger.info("[KG-Sync] Pipeline инициализирован")

    # ===================================================================
    # Основной pipeline
    # ===================================================================

    def process_news_batch(self, news_items: List[NewsItem]) -> Dict[str, int]:
        """
        Обрабатывает пачку новостей через весь pipeline.

        Args:
            news_items: Список NewsItem от UnifiedNewsConnector

        Returns:
            Статистика обработки
        """
        start = time.time()
        local_stats = {"entities": 0, "relations": 0, "vdb_docs": 0, "errors": 0}

        for item in news_items:
            try:
                # 1. Извлечение entities
                entities = self._extract_entities(item)
                local_stats["entities"] += len(entities)

                # 2. Создание связей
                relations = self._create_relations(item, entities)
                local_stats["relations"] += len(relations)

                # 3. Сохранение в KG (SQLite)
                self._save_to_kg(item, entities, relations)

                # 4. Добавление в FAISS
                vdb_added = self._add_to_vector_db(item)
                local_stats["vdb_docs"] += vdb_added

                self._stats["items_processed"] += 1

            except Exception as e:
                logger.warning(f"[KG-Sync] Ошибка обработки новости: {e}")
                local_stats["errors"] += 1
                self._stats["errors"] += 1

        elapsed = time.time() - start
        logger.info(
            f"[KG-Sync] Обработано {len(news_items)} новостей за {elapsed:.2f}s: "
            f"entities={local_stats['entities']}, relations={local_stats['relations']}, "
            f"vdb={local_stats['vdb_docs']}"
        )

        return local_stats

    def process_binance_event(self, data: Dict[str, Any]) -> None:
        """
        Обрабатывает событие от BinanceDataStream.

        Args:
            data: Распарсенное WS сообщение или REST ответ
        """
        try:
            event_type = data.get("type", "unknown")
            symbol = data.get("symbol", "")

            # Для значимых событий создаём KG запись
            if event_type == "ticker":
                change_pct = abs(data.get("price_change_pct", 0))
                if change_pct > 3.0:  # Только значимые движения (>3%)
                    self._record_price_movement(symbol, data)
            elif event_type == "kline" and data.get("is_closed"):
                self._record_candle_close(symbol, data)

        except Exception as e:
            logger.debug(f"[KG-Sync] Binance event error: {e}")

    # ===================================================================
    # Извлечение entities
    # ===================================================================

    def _extract_entities(self, item: NewsItem) -> List[Dict[str, str]]:
        """Извлекает entities из новости."""
        text = item.headline + " " + item.content
        entities = []
        seen = set()

        for entity_type, pattern in self._ENTITY_PATTERNS.items():
            for match in pattern.finditer(text):
                name = match.group(0).upper()
                if name not in seen:
                    seen.add(name)
                    entities.append(
                        {
                            "name": name,
                            "type": entity_type,
                            "source": item.source,
                            "timestamp": item.timestamp.isoformat(),
                        }
                    )

        # Добавляем символы из news item
        for sym in item.symbols:
            if sym not in seen:
                seen.add(sym)
                entities.append(
                    {
                        "name": sym,
                        "type": "symbol",
                        "source": item.source,
                        "timestamp": item.timestamp.isoformat(),
                    }
                )

        self._stats["entities_extracted"] += len(entities)
        return entities

    # ===================================================================
    # Создание связей
    # ===================================================================

    def _create_relations(self, item: NewsItem, entities: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Создаёт связи между entities.

        Связи:
        - news → entity (AFFECTS)
        - entity → entity (CORRELATED, если оба в одной новости)
        """
        relations = []

        # Связь новость → entity
        for entity in entities:
            relations.append(
                {
                    "source": f"news_{item.timestamp.strftime('%Y%m%d%H%M%S')}",
                    "target": entity["name"],
                    "type": "AFFECTS",
                    "weight": abs(item.sentiment),
                    "timestamp": item.timestamp.isoformat(),
                }
            )

        # Связи между entities (correlation)
        for i, e1 in enumerate(entities):
            for e2 in entities[i + 1 :]:
                relations.append(
                    {
                        "source": e1["name"],
                        "target": e2["name"],
                        "type": "CORRELATED",
                        "weight": 0.5,
                        "timestamp": item.timestamp.isoformat(),
                    }
                )

        return relations

    # ===================================================================
    # Сохранение в KG (SQLite)
    # ===================================================================

    def _save_to_kg(
        self,
        item: NewsItem,
        entities: List[Dict[str, str]],
        relations: List[Dict[str, str]],
    ) -> None:
        """Сохраняет entities и relations в SQLite KG таблицы."""
        if not self.db_manager:
            return

        try:
            session = self.db_manager.Session()

            # Сохраняем entities
            from src.db.models import Entity, Relation

            for entity in entities:
                existing = session.query(Entity).filter_by(name=entity["name"], entity_type=entity["type"]).first()
                if not existing:
                    session.add(
                        Entity(
                            name=entity["name"],
                            entity_type=entity["type"],
                            metadata=json.dumps(
                                {
                                    "source": entity["source"],
                                    "first_seen": entity["timestamp"],
                                }
                            ),
                        )
                    )

            # Сохраняем relations
            for rel in relations:
                source_entity = session.query(Entity).filter_by(name=rel["source"]).first()
                target_entity = session.query(Entity).filter_by(name=rel["target"]).first()

                if source_entity and target_entity:
                    session.add(
                        Relation(
                            source_entity_id=source_entity.id,
                            target_entity_id=target_entity.id,
                            relation_type=rel["type"],
                            weight=rel["weight"],
                            metadata=json.dumps(
                                {
                                    "timestamp": rel["timestamp"],
                                    "source": item.source_name,
                                }
                            ),
                        )
                    )

            session.commit()
            self._stats["relations_created"] += len(relations)

        except Exception as e:
            try:
                session.rollback()
            except Exception:
                pass
            logger.debug(f"[KG-Sync] SQLite save error: {e}")
        finally:
            try:
                session.close()
            except Exception:
                pass

    # ===================================================================
    # FAISS / Vector DB
    # ===================================================================

    def _add_to_vector_db(self, item: NewsItem) -> int:
        """Добавляет новость в FAISS индекс."""
        if not self.vector_db_manager:
            return 0

        try:
            text = f"{item.headline}. {item.content[:200]}"
            metadata = {
                "symbol": ",".join(item.symbols),
                "source": item.source_name,
                "sentiment": item.sentiment,
                "category": item.category,
                "timestamp": item.timestamp.isoformat(),
                "url": item.url,
            }

            # Добавляем в VectorDB
            doc_id = self.vector_db_manager.add_document(
                text=text,
                metadata=metadata,
                doc_type="news",
                symbols=item.symbols,
            )

            if doc_id:
                self._stats["vdb_documents_added"] += 1
                return 1

        except Exception as e:
            logger.debug(f"[KG-Sync] VectorDB add error: {e}")

        return 0

    # ===================================================================
    # Binance события
    # ===================================================================

    def _record_price_movement(self, symbol: str, data: Dict) -> None:
        """Записывает значимое движение цены в KG."""
        try:
            change = data.get("price_change_pct", 0)
            direction = "SURGE" if change > 0 else "PLUNGE"

            # Создаём entity для движения
            entity_name = f"{symbol}_{direction}_{abs(change):.1f}%"

            if self.db_manager:
                session = self.db_manager.Session()
                try:
                    from src.db.models import Entity, Relation

                    # Entity
                    session.add(
                        Entity(
                            name=entity_name,
                            entity_type="price_movement",
                            metadata=json.dumps(
                                {
                                    "symbol": symbol,
                                    "change_pct": change,
                                    "price": data.get("price", 0),
                                    "volume": data.get("volume", 0),
                                    "timestamp": data.get("timestamp", datetime.now(timezone.utc)).isoformat(),
                                }
                            ),
                        )
                    )

                    # Связь с базовым символом
                    base_entity = session.query(Entity).filter_by(name=symbol).first()
                    if base_entity:
                        new_entity = session.query(Entity).filter_by(name=entity_name).first()
                        if new_entity:
                            session.add(
                                Relation(
                                    source_entity_id=base_entity.id,
                                    target_entity_id=new_entity.id,
                                    relation_type="EXPERIENCED",
                                    weight=min(abs(change) / 10, 1.0),
                                    metadata=json.dumps({"type": direction}),
                                )
                            )

                    session.commit()
                    logger.info(f"[KG-Sync] Записано движение {symbol}: {change:+.1f}%")
                except Exception:
                    session.rollback()
                finally:
                    session.close()

        except Exception as e:
            logger.debug(f"[KG-Sync] Price movement error: {e}")

    def _record_candle_close(self, symbol: str, data: Dict) -> None:
        """Записывает закрытие свечи для KG контекста."""
        # Можно добавить свечные паттерны в KG
        pass  # Заглушка для будущего расширения

    # ===================================================================
    # Статистика
    # ===================================================================

    def get_stats(self) -> Dict[str, int]:
        """Возвращает статистику pipeline."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Сбрасывает статистику."""
        self._stats = {
            "items_processed": 0,
            "entities_extracted": 0,
            "relations_created": 0,
            "vdb_documents_added": 0,
            "errors": 0,
        }

    def __repr__(self) -> str:
        return (
            f"KGSyncPipeline(processed={self._stats['items_processed']}, "
            f"entities={self._stats['entities_extracted']}, "
            f"relations={self._stats['relations_created']})"
        )
