# src/db/vector_db_manager.py
import logging
import threading
from datetime import datetime, timedelta, timezone

# import logger  # Закомментировано, так как не используется напрямую
import numpy as np
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from src.core.config_models import VectorDBSettings

logger = logging.getLogger(__name__)
# ----------------------------------------------------------------------

try:
    import faiss
    # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: Ограничение FAISS одним потоком ---
    if faiss:
        faiss.omp_set_num_threads(1)
        logger.info("FAISS OMP threads set to 1 for stability.")
    # ------------------------------------------------------------------
except ImportError:
    faiss = None
from src.core.config_models import VectorDBSettings


class VectorDBManager:
    """
    Управляет взаимодействием с векторной базой данных FAISS.
    Хранит индекс, документы и метаданные локально.
    """

    def __init__(self, config: VectorDBSettings, db_root_path=None):
        self.config = config
        # ... (пропуск инициализации переменных) ...

        # --- ИСПРАВЛЕНИЕ ЛОГИКИ ПУТИ ---
        if db_root_path is not None:
            # Используем ПЕРЕДАННЫЙ полный путь (из TradingSystem)
            self.db_path = db_root_path
        else:
            # Используем путь из конфига (для автономного запуска vector.py)
            self.db_path = Path(self.config.path).resolve()
        # -------------------------------

        self.index_file = self.db_path / "faiss.index"
        self.meta_file = self.db_path / "faiss.meta"
        self._save_lock = threading.Lock()

        if not faiss:
            logger.error("Библиотека 'faiss-cpu' не найдена. Установите ее: pip install faiss-cpu")
            self.config.enabled = False
            return

        # --- ИСПРАВЛЕНИЕ СИНТАКСИСА: Оборачиваем в try/except ---
        if self.config.enabled:
            try:
                # ... (остальной код) ...
                self._load()
                logger.info(f"VectorDBManager (FAISS) инициализирован. Загружено {len(self.documents)} документов.")

            except Exception as e:
                # ... (остальной код) ...
                logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось создать папку VectorDB или проверить права: {e}")
                self.config.enabled = False
                return

    def cleanup_old_documents(self):
        if not self.is_ready() or not self.config.cleanup_enabled:
            logger.debug("VectorDB Cleanup: Отключено или не готово.")
            return

        logger.warning("VectorDB Cleanup: Запуск очистки устаревших документов...")

        # 1. Определяем порог времени
        # --- ИСПРАВЛЕНИЕ 2: Используем datetime.now(timezone.utc) для создания AWARE-объекта ---
        time_threshold = datetime.now(timezone.utc) - timedelta(days=self.config.max_age_days)

        # 2. Идентифицируем индексы для сохранения
        indices_to_keep = []
        new_ids = []
        new_documents = []
        new_metadatas = []

        for i, metadata in enumerate(self.metadatas):
            timestamp_str = metadata.get('timestamp_iso')
            if timestamp_str:
                try:
                    # doc_time уже AWARE (UTC)
                    doc_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                    # Сравнение AWARE-объектов теперь корректно
                    if doc_time >= time_threshold:
                        indices_to_keep.append(i)
                        new_ids.append(self.ids[i])
                        new_documents.append(self.documents[i])
                        new_metadatas.append(metadata)
                except ValueError:
                    # Если дата не парсится, сохраняем документ (на всякий случай)
                    indices_to_keep.append(i)
                    new_ids.append(self.ids[i])
                    new_documents.append(self.documents[i])
                    new_metadatas.append(metadata)

        # 3. Проверяем, есть ли что удалять
        if self.index is None:
            logger.error("VectorDB Cleanup: Индекс FAISS не инициализирован.")
            return

        if len(indices_to_keep) == self.index.ntotal:
            logger.info("VectorDB Cleanup: Старых документов не найдено.")
            return

        deleted_count = self.index.ntotal - len(indices_to_keep)
        logger.critical(f"VectorDB Cleanup: Удаление {deleted_count} старых документов. Перестроение индекса...")

        # 4. Извлекаем векторы для сохранения и перестраиваем индекс
        if not indices_to_keep:
            # Если ничего не осталось, создаем пустой индекс
            self.index = faiss.IndexFlatL2(self.dimension)
        else:
            # Создаем IndexSubset для извлечения нужных векторов
            subset_index = faiss.extract_index_subset(self.index, np.array(indices_to_keep, dtype='int64'))
            self.index = subset_index

        # Обновляем индекс и метаданные
        self.ids = new_ids
        self.documents = new_documents
        self.metadatas = new_metadatas
        self._id_to_idx = {id_val: i for i, id_val in enumerate(self.ids)}

        # 5. Сохраняем
        self._save()
        logger.critical(f"VectorDB Cleanup: Очистка завершена. Осталось {self.index.ntotal} документов.")

    def is_ready(self) -> bool:
        return self.config.enabled and self.index is not None

    def _load(self):
        # --- 1. Инициализация всех атрибутов (для гарантии) ---
        # Размерность 384 - это размерность all-MiniLM-L6-v2
        self.dimension = 384
        self.index = None
        self.documents = []
        self.metadatas = []
        self.ids = []
        self._id_to_idx = {}
        
        # ОПТИМИЗАЦИЯ: Счётчики для уменьшения частоты сохранения
        self._unsaved_changes = 0
        self._last_save_time = datetime.now()
        self._save_threshold = 50  # Сохранять каждые 50 документов
        self._save_interval_seconds = 300  # Или каждые 5 минут
        # ------------------------------------------------------

        if not self.config.enabled:
            return

        try:
            if self.index_file.exists() and self.meta_file.exists():
                # --- Логика загрузки существующего индекса ---
                self.index = faiss.read_index(str(self.index_file))
                with open(self.meta_file, 'rb') as f:
                    meta_data = pickle.load(f)
                    self.documents = meta_data['documents']
                    self.metadatas = meta_data['metadatas']
                    self.ids = meta_data['ids']
                    self._id_to_idx = {id_val: i for i, id_val in enumerate(self.ids)}
                self.dimension = self.index.d
                logger.info(
                    f"Индекс FAISS и метаданные успешно загружены из {self.db_path}. Документов: {self.index.ntotal}")

            # --- 2. Если индекс не загружен (файл не существует), создаем новый ---
            if self.index is None:
                self.index = faiss.IndexFlatL2(self.dimension)
                logger.warning(f"Файлы индекса не найдены. Создан новый ПУСТОЙ индекс FAISS (D={self.dimension}).")


        except Exception as e:
            # --- 3. Если произошла ошибка при загрузке (поврежден файл), пересоздаем ---
            logger.error(f"Не удалось загрузить существующий индекс FAISS, будет создан новый. Ошибка: {e}")
            self.index = faiss.IndexFlatL2(self.dimension)
            self.documents = []
            self.metadatas = []
            self.ids = []
            self._id_to_idx = {}
            logger.warning(f"Индекс FAISS был пересоздан после ошибки загрузки.")

    def _save(self):
        if self.index is None:
            return
        with self._save_lock:
            try:
                if self.index.ntotal == 0:
                    logger.warning("VectorDB: Индекс пуст, сохранение пропущено.")
                    return

                logger.critical(f"VectorDB: НАЧАЛО СОХРАНЕНИЯ {self.index.ntotal} документов в {self.index_file}")

                # --- Попытка записи FAISS ---
                faiss.write_index(self.index, str(self.index_file))

                # --- Попытка записи метаданных ---
                meta_data = {
                    'documents': self.documents,
                    'metadatas': self.metadatas,
                    'ids': self.ids
                }
                with open(self.meta_file, 'wb') as f:
                    pickle.dump(meta_data, f)

                logger.critical("VectorDB: ФАЙЛЫ УСПЕШНО СОЗДАНЫ.")

            except Exception as e:
                # --- КРИТИЧЕСКИЙ ЛОГ ОШИБКИ ЗАПИСИ ---
                logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА ПРИ СОХРАНЕНИИ ИНДЕКСА FAISS: {e}")
                logger.critical(f"Проверьте права доступа к папке: {self.db_path}")
    
    def force_save(self):
        """
        ОПТИМИЗАЦИЯ: Принудительное сохранение индекса (вызывается при остановке системы).
        """
        if self._unsaved_changes > 0:
            logger.info(f"[VectorDB] Принудительное сохранение {self._unsaved_changes} несохранённых изменений...")
            self._save()
            self._unsaved_changes = 0
            self._last_save_time = datetime.now()
        else:
            logger.debug("[VectorDB] Нет несохранённых изменений для принудительного сохранения")

    def add_documents(self, ids: List[str], embeddings: List[List[float]], metadatas: List[Dict[str, Any]],
                      documents: List[str]):
        if not embeddings:
            return

        # --- ИСПРАВЛЕНИЕ: Принудительная инициализация индекса, если он None ---
        if self.index is None and self.config.enabled:
            self.dimension = len(embeddings[0])
            # IndexFlatL2 - простой индекс, который не требует обучения
            self.index = faiss.IndexFlatL2(self.dimension)
            logger.info(f"[VectorDB] Создан новый индекс FAISS с размерностью {self.dimension}.")

        if self.index is None:
            logger.error("[VectorDB] FAISS Index is None. Cannot add documents.")
            return
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        embeddings_np = np.array(embeddings, dtype='float32')

        # FAISS требует нормализации для косинусного сходства
        faiss.normalize_L2(embeddings_np)

        added_count = 0
        for i, doc_id in enumerate(ids):
            if doc_id in self._id_to_idx:
                continue

            self.index.add(embeddings_np[i:i + 1])
            self.documents.append(documents[i])
            self.metadatas.append(metadatas[i])
            self.ids.append(doc_id)
            self._id_to_idx[doc_id] = len(self.ids) - 1
            added_count += 1

        if added_count > 0:
            logger.info(f"[VectorDB] Добавлено {added_count} новых документов. Всего: {self.index.ntotal}")
            self._unsaved_changes += added_count
            
            # ОПТИМИЗАЦИЯ: Сохраняем только если накопилось достаточно изменений ИЛИ прошло достаточно времени
            now = datetime.now()
            time_since_last_save = (now - self._last_save_time).total_seconds()
            
            should_save = (
                self._unsaved_changes >= self._save_threshold or
                time_since_last_save >= self._save_interval_seconds
            )
            
            if should_save:
                logger.info(f"[VectorDB] Сохранение: {self._unsaved_changes} несохранённых изменений, {time_since_last_save:.0f}с с последнего сохранения")
                self._save()
                self._unsaved_changes = 0
                self._last_save_time = now
            else:
                logger.debug(f"[VectorDB] Отложено сохранение: {self._unsaved_changes}/{self._save_threshold} изменений, {time_since_last_save:.0f}/{self._save_interval_seconds}с")
        else:
            logger.debug(f"[VectorDB] Все {len(ids)} документов уже существуют в индексе")

    def query_similar(self, query_embedding: List[float], n_results: int = 5) -> Optional[Dict[str, Any]]:
        if not self.is_ready() or self.index.ntotal == 0:
            logger.debug(f"[VectorDB] Поиск невозможен: готов={self.is_ready()}, документов={self.index.ntotal if self.index else 0}")
            return None

        query_np = np.array([query_embedding], dtype='float32')
        faiss.normalize_L2(query_np)

        try:
            distances, indices = self.index.search(query_np, n_results)

            results = {
                'ids': [[]],
                'documents': [[]],
                'metadatas': [[]],
                'distances': [[]]
            }

            if indices.size > 0:
                for i, idx in enumerate(indices[0]):
                    if idx != -1:
                        results['ids'][0].append(self.ids[idx])
                        results['documents'][0].append(self.documents[idx])
                        results['metadatas'][0].append(self.metadatas[idx])
                        results['distances'][0].append(distances[0][i])

            logger.debug(f"[VectorDB] Найдено {len(results['ids'][0])} результатов")
            return results
        except Exception as e:
            logger.error(f"[VectorDB] Ошибка при поиске в FAISS: {e}", exc_info=True)
            return None