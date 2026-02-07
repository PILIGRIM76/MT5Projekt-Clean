"""
Скрипт для исправления метаданных моделей в базе данных.
Добавляет KG признаки (KG_CB_SENTIMENT, KG_INFLATION_SURPRISE) к features_json всех моделей.
"""
import json
import logging
import queue
from src.db.database_manager import DatabaseManager
from src.core.config_loader import load_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fix_model_features():
    """Исправляет список признаков в метаданных всех моделей."""
    
    # Загрузка конфигурации
    config = load_config()
    
    # Инициализация DatabaseManager с пустой очередью (не нужна для чтения)
    write_queue = queue.Queue()
    db_manager = DatabaseManager(config, write_queue)
    
    # KG признаки, которые нужно добавить
    kg_features = ['KG_CB_SENTIMENT', 'KG_INFLATION_SURPRISE']
    
    session = db_manager.Session()
    try:
        # Получаем все модели из базы данных
        from src.db.database_manager import TrainedModel
        models = session.query(TrainedModel).all()
        
        updated_count = 0
        
        for model in models:
            if not model.features_json:
                logger.warning(f"Модель {model.id} ({model.symbol}, {model.model_type}) не имеет features_json. Пропуск.")
                continue
            
            try:
                # Парсим текущий список признаков
                current_features = json.loads(model.features_json)
                
                # Проверяем, нужно ли обновление
                needs_update = False
                for kg_feat in kg_features:
                    if kg_feat not in current_features:
                        current_features.append(kg_feat)
                        needs_update = True
                
                if needs_update:
                    # Обновляем features_json
                    model.features_json = json.dumps(current_features)
                    updated_count += 1
                    logger.info(f"✅ Обновлена модель {model.id} ({model.symbol}, {model.model_type} v{model.version})")
                    logger.info(f"   Новый список признаков ({len(current_features)}): {current_features}")
                else:
                    logger.info(f"⏭️  Модель {model.id} ({model.symbol}, {model.model_type}) уже содержит KG признаки.")
            
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга features_json для модели {model.id}: {e}")
                continue
        
        # Сохраняем изменения
        session.commit()
        logger.info(f"\n{'='*60}")
        logger.info(f"✅ ГОТОВО! Обновлено моделей: {updated_count} из {len(models)}")
        logger.info(f"{'='*60}")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Критическая ошибка при обновлении моделей: {e}", exc_info=True)
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("="*60)
    logger.info("Запуск скрипта исправления метаданных моделей...")
    logger.info("="*60)
    fix_model_features()
