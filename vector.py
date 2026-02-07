# F:\MT5Projekt\vector.py

import asyncio
import threading
import logging
import os
from pathlib import Path
from datetime import datetime
import sys
import queue
import torch
from sentence_transformers import SentenceTransformer

# Установка пути к корню проекта для корректных импортов
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Установка переменной окружения для кэша HF (как в main_pyside.py)
# Используем путь из конфига, но для запуска здесь просто устанавливаем
os.environ['HF_HOME'] = str(Path("F:/ai_models").resolve())

# Импорты из вашего проекта
from src.core.config_loader import load_config
from src.data.multi_source_aggregator import MultiSourceDataAggregator
from src.db.database_manager import DatabaseManager
from src.db.vector_db_manager import VectorDBManager
from src.analysis.nlp_processor import CausalNLPProcessor
# from sentence_transformers import SentenceTransformer # Уже импортирован

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [VECTOR_POPULATOR] - %(message)s')
logger = logging.getLogger(__name__)


# --- АСИНХРОННАЯ ФУНКЦИЯ ДЛЯ НАПОЛНЕНИЯ ---
async def populate_vector_db_manually():
    logger.info("--- НАЧАЛО РУЧНОГО НАПОЛНЕНИЯ ВЕКТОРНОЙ БД ---")

    # 1. Загрузка конфигурации
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        return

    # 2. Инициализация менеджеров
    import queue
    dummy_queue = queue.Queue()
    db_manager = DatabaseManager(config, dummy_queue)

    vector_db_full_path = Path(config.DATABASE_FOLDER) / config.vector_db.path
    vector_db_manager = VectorDBManager(config.vector_db, db_root_path=vector_db_full_path)

    # 3.1. Загрузка модели эмбеддингов (SentenceTransformer)
    try:
        logger.info(f"Загрузка модели эмбеддингов: {config.vector_db.embedding_model}...")
        embedding_model = SentenceTransformer(config.vector_db.embedding_model, device='cpu')
    except Exception as e:
        logger.error(f"Не удалось загрузить SentenceTransformer: {e}. Наполнение невозможно.")
        return

    # 3.2. Инициализация NLP Processor
    nlp_processor = CausalNLPProcessor(config, db_manager, vector_db_manager)
    nlp_processor.embedding_model = embedding_model
    nlp_processor.device = torch.device("cpu")
    nlp_processor.load_models()  # Загрузит Flan-T5 и FinBERT

    # 4. Сбор данных
    aggregator = MultiSourceDataAggregator(config)
    news_result = await aggregator.aggregate_all_sources_async()
    all_news_items, _, _ = news_result

    if not all_news_items:
        logger.warning("Не удалось собрать ни одной новости. Проверьте настройки RSS/API.")
        return

    logger.info(f"Собрано {len(all_news_items)} новостей. Начинается векторизация и сохранение...")

    # 5. Векторизация и сохранение
    for i, item in enumerate(all_news_items):
        if i % 50 == 0:
            logger.info(f"Прогресс: {i}/{len(all_news_items)} новостей обработано.")

        # Вызываем метод, который выполняет векторизацию и сохранение в FAISS
        nlp_processor.process_and_store_text(
            text=item.text,
            context={"source": item.source, "timestamp": item.timestamp.isoformat()}
        )

    # 6. Финальное сохранение и отчет
    vector_db_manager._save()
    logger.critical(f"--- НАПОЛНЕНИЕ ЗАВЕРШЕНО ---")
    logger.critical(f"Векторная БД содержит {vector_db_manager.index.ntotal} документов.")


if __name__ == '__main__':
    # Запуск асинхронной функции
    # ВАЖНО: Убедитесь, что вы запускаете этот код в отдельном процессе/консоли,
    # а не внутри уже запущенного main_pyside.py
    import sys
    import queue
    import torch
    from sentence_transformers import SentenceTransformer

    # Убедитесь, что путь к корню проекта добавлен в sys.path
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Запуск асинхронной функции
    try:
        asyncio.run(populate_vector_db_manually())
    except RuntimeError as e:
        if "cannot run non-async" in str(e):
            logger.error(
                "Ошибка: Попытка запустить asyncio.run() внутри уже запущенного цикла событий. Запустите этот скрипт в отдельной консоли.")
        else:
            logger.error(f"Критическая ошибка при запуске: {e}")