# src/analysis/nlp_processor.py
import logging
import os
import re
import uuid
# from cgitb import text  # Закомментировано, так как не используется
# from lib2to3.fixes.fix_input import context  # Закомментировано, так как не используется
from typing import TYPE_CHECKING, Optional, Dict
from sentence_transformers import SentenceTransformer

from anyio import Path
from huggingface_hub import HfFolder
from transformers import AutoTokenizer, T5ForConditionalGeneration
import torch


if TYPE_CHECKING:
    from src.db.database_manager import DatabaseManager
    from src.db.vector_db_manager import VectorDBManager
    from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class CausalNLPProcessor:
    def __init__(self, config: "Settings", db_manager: "DatabaseManager", vector_db_manager: "VectorDBManager"):
        self.config = config
        self.db_manager = db_manager
        self.vector_db_manager = vector_db_manager
        self.embedding_model: Optional[SentenceTransformer] = None
        self.model_names = ['google/flan-t5-base']
        self.models = {}
        self.is_ready = False
        self.entity_types = {
            "FED": "CentralBank", "ECB": "CentralBank", "ФРС": "CentralBank", "ЕЦБ": "CentralBank",
            "POWELL": "Person", "LAGARDE": "Person",
            "USD": "Currency", "EUR": "Currency", "JPY": "Currency", "GBP": "Currency",
            "EURUSD": "Asset", "GBPUSD": "Asset", "XAUUSD": "Asset",
            "INFLATION": "EconomicIndicator", "RATE": "EconomicIndicator", "CPI": "EconomicIndicator"
        }
        # Устройство для NLP-моделей (будет переопределено в TradingSystem)
        self.device = torch.device("cpu")
        logger.info(f"Causal NLP Processor инициализирован с моделями: {self.model_names}")

    def load_models(self):
        if self.is_ready:
            return

        hf_home = os.environ.get('HF_HOME')
        if hf_home:
            logger.info(f"Используется кастомная директория для кэша Hugging Face: {hf_home}")
        else:
            home_dir = os.path.expanduser('~')
            default_cache_path = os.path.join(home_dir, ".cache", "huggingface", "hub")
            logger.info(f"Используется стандартная директория для кэша Hugging Face: {default_cache_path}")

        # --- Этап 1: Загрузка основных моделей для генерации связей ---
        for model_name in self.model_names:
            try:
                logger.info(f"Загрузка NLP-модели: '{model_name}'... (Это может занять время при первом запуске!)")
                tokenizer = AutoTokenizer.from_pretrained(model_name)

                # --- ИСПРАВЛЕНИЕ: Принудительная загрузка на CPU для стабильности ---
                # Примечание: Убираем load_in_8bit, так как он конфликтует с принудительным CPU
                model = T5ForConditionalGeneration.from_pretrained(model_name)

                # Принудительно переносим на CPU, чтобы избежать исчерпания VRAM
                # Если self.device == 'cuda', модель все равно будет перенесена на GPU,
                # но для Flan-T5 лучше принудительно использовать CPU, если VRAM ограничена.
                # В TradingSystem.initialize_heavy_components мы установили self.device = 'cuda'/'cpu'.
                # Для максимальной безопасности, используем torch.device("cpu") здесь.
                model.to(torch.device("cpu"))  # <-- ПРИНУДИТЕЛЬНО CPU ДЛЯ СТАБИЛЬНОСТИ

                self.models[model_name] = {'tokenizer': tokenizer, 'model': model}
                logger.info(f"Модель '{model_name}' успешно загружена.")
            except Exception as e:
                logger.error(f"Не удалось загрузить модель '{model_name}': {e}", exc_info=True)

        # --- Этап 2: Загрузка модели для эмбеддингов (для векторной БД) ---
        if self.config.vector_db.enabled and self.embedding_model is None:
            logger.warning(
                "VectorDB включен, но embedding_model не была передана. Отключение VectorDB.")
            # Принудительно отключаем, если модель не пришла
            self.config.vector_db.enabled = False

            # --- Этап 3: Финальная проверка готовности ---
        if self.models:
            self.is_ready = True
            logger.info("NLP Processor готов к работе.")
        else:
            self.is_ready = False
            logger.error("Не удалось загрузить ни одну основную NLP-модель. Анализ текста будет невозможен.")

    def _parse_relations(self, generated_text: str) -> Optional[Dict[str, str]]:
        try:
            text = generated_text.lower()
            subject_match = re.search(r'subject:\s*(.*?)\s*\|', text)
            relation_match = re.search(r'relation:\s*(.*?)\s*\|', text)
            object_match = re.search(r'object:\s*(.*)', text)

            if subject_match and relation_match and object_match:
                subject = subject_match.group(1).strip()
                relation = relation_match.group(1).strip()
                obj = object_match.group(1).strip()

                if subject and relation and obj and len(relation) > 2 and '[subject]' not in subject:
                    return {"subject": subject, "object": obj, "relation": relation}
        except Exception as e:
            logger.error(f"Ошибка парсинга сгенерированного текста '{generated_text}': {e}")
        return None

    def process_and_store_text(self, text: str, context: dict = None):
        if not self.is_ready:
            logger.warning("NLP-модель не загружена, обработка текста пропущена.")
            return


        # 1. Формируем промпт (Few-shot prompting)
        prompt = (
            "Extract one clear causal financial relationship from the text. "
            "The output format MUST BE: subject: [subject] | relation: [relation] | object: [object]\n\n"
            "GOOD EXAMPLES:\n"
            "Text: 'The ECB raises interest rates to combat inflation.'\n"
            "Output: subject: ECB | relation: raises | object: interest rates\n\n"
            "Text: 'Strong US jobs report boosts the dollar.'\n"
            "Output: subject: US jobs report | relation: boosts | object: the dollar\n\n"
            "BAD EXAMPLES (what to avoid):\n"
            "Text: 'JP Morgan and Goldman Sachs are in the news.'\n"
            "Output: subject: [subject] | relation: [relation] | object: [object]\n\n"
            "---\n\n"
            f"Text: '{text}'\n"
            "Output:"
        )

        # 2. Векторизация и сохранение документа (ВЫПОЛНЯЕТСЯ ОДИН РАЗ)
        if self.vector_db_manager and self.vector_db_manager.is_ready() and self.embedding_model:
            try:
                vector_id = str(uuid.uuid4())

                # 1. КОДИРОВАНИЕ
                # Убедитесь, что кодирование происходит корректно
                embedding = self.embedding_model.encode(text, convert_to_tensor=False).tolist()

                # 2. СОХРАНЕНИЕ В SQL (через очередь)
                self.db_manager.add_news_article(
                    vector_id=vector_id,
                    content=text,
                    source=context.get('source', 'Unknown'),
                    timestamp=context.get('timestamp')
                )

                # 3. СОХРАНЕНИЕ В FAISS (СИНХРОННО)
                metadata = {
                    "source": context.get('source', 'Unknown'),
                    "timestamp_iso": context.get('timestamp', '')
                }
                self.vector_db_manager.add_documents(
                    ids=[vector_id],
                    embeddings=[embedding],
                    metadatas=[metadata],
                    documents=[text]
                )
                logger.info(f"Векторная БД: Добавлен документ ID: {vector_id} из {context.get('source')}")
            except Exception as e:
                logger.error(f"Ошибка при векторизации и сохранении текста: {e}", exc_info=True)

        # 3. Генерация связей (LLM Inference)
        generated_relations = []
        for model_name, components in self.models.items():
            try:
                tokenizer = components['tokenizer']
                model = components['model']

                input_ids = tokenizer.encode(prompt, return_tensors="pt", max_length=512, truncation=True).to(
                    self.device)

                # Переносим модель на CPU перед генерацией (если она не была перенесена ранее)

                model.to(self.device)

                outputs = model.generate(input_ids, max_length=128, num_beams=2, early_stopping=True)
                generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

                parsed_relation = self._parse_relations(generated_text)
                if parsed_relation:
                    generated_relations.append(parsed_relation)
            except Exception as e:
                logger.error(f"Ошибка при генерации связей моделью '{model_name}': {e}")

        if not generated_relations:
            return

        # 4. Сохранение лучшей связи в Граф Знаний
        best_relation = max(generated_relations,
                            key=lambda r: len(r['subject']) + len(r['relation']) + len(r['object']))

        logger.info(f"NLP модель нашла связь: {best_relation}")

        source_name_upper = best_relation["subject"].upper()
        target_name_upper = best_relation["object"].upper()

        source_type = "Unknown"
        for key, type_val in self.entity_types.items():
            if key in source_name_upper:
                source_type = type_val
                break

        target_type = "Unknown"
        for key, type_val in self.entity_types.items():
            if key in target_name_upper:
                target_type = type_val
                break

        self.db_manager.add_relation(
            source_name=best_relation["subject"],
            relation_type=best_relation["relation"],
            target_name=best_relation["object"],
            source_type=source_type,
            target_type=target_type,
            context=context
        )