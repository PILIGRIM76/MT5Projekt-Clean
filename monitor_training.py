"""
Утилита для мониторинга процесса обучения моделей в режиме реального времени.
Показывает прогресс, статистику и не блокирует основную систему.
"""
import logging
import time
from datetime import datetime
from src.core.config_loader import load_config
from src.db.database_manager import DatabaseManager, TrainedModel
import queue

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_training_statistics():
    """Получает статистику обученных моделей."""
    config = load_config()
    write_queue = queue.Queue()
    db_manager = DatabaseManager(config, write_queue)
    
    session = db_manager.Session()
    try:
        # Общая статистика
        total_models = session.query(TrainedModel).count()
        champions = session.query(TrainedModel).filter_by(is_champion=True).count()
        
        # Модели за последние 24 часа
        from datetime import timedelta
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_models = session.query(TrainedModel).filter(
            TrainedModel.training_date >= yesterday
        ).count()
        
        # Статистика по символам
        symbols_with_models = session.query(TrainedModel.symbol).distinct().count()
        
        # Статистика по типам моделей
        model_types = session.query(
            TrainedModel.model_type, 
            session.query(TrainedModel).filter(
                TrainedModel.model_type == TrainedModel.model_type
            ).count()
        ).group_by(TrainedModel.model_type).all()
        
        logger.info(f"\n{'='*80}")
        logger.info(f"СТАТИСТИКА ОБУЧЕННЫХ МОДЕЛЕЙ")
        logger.info(f"{'='*80}")
        logger.info(f"Всего моделей в базе: {total_models}")
        logger.info(f"Активных чемпионов: {champions}")
        logger.info(f"Моделей обучено за 24 часа: {recent_models}")
        logger.info(f"Символов с моделями: {symbols_with_models}")
        logger.info(f"\nРаспределение по типам:")
        
        for model_type, count in model_types:
            logger.info(f"  - {model_type}: {count}")
        
        logger.info(f"{'='*80}\n")
        
        return {
            'total': total_models,
            'champions': champions,
            'recent': recent_models,
            'symbols': symbols_with_models,
            'types': dict(model_types)
        }
        
    finally:
        session.close()


def show_recent_training_batches(limit=10):
    """Показывает последние сессии обучения."""
    config = load_config()
    write_queue = queue.Queue()
    db_manager = DatabaseManager(config, write_queue)
    
    session = db_manager.Session()
    try:
        # Получаем уникальные training_batch_id
        recent_batches = session.query(
            TrainedModel.training_batch_id,
            TrainedModel.symbol,
            TrainedModel.training_date
        ).order_by(
            TrainedModel.training_date.desc()
        ).limit(limit).all()
        
        logger.info(f"\n{'='*80}")
        logger.info(f"ПОСЛЕДНИЕ {limit} СЕССИЙ ОБУЧЕНИЯ")
        logger.info(f"{'='*80}")
        
        for batch_id, symbol, training_date in recent_batches:
            trained_time = training_date.strftime('%Y-%m-%d %H:%M:%S') if training_date else 'N/A'
            logger.info(f"{trained_time} | {symbol:15s} | Batch: {batch_id}")
        
        logger.info(f"{'='*80}\n")
        
    finally:
        session.close()


def monitor_training_progress(refresh_interval=10, duration=300):
    """
    Мониторит прогресс обучения в реальном времени.
    
    Args:
        refresh_interval: Интервал обновления в секундах
        duration: Общая длительность мониторинга в секундах
    """
    logger.info(f"Начинаем мониторинг обучения (обновление каждые {refresh_interval} сек)")
    logger.info(f"Мониторинг будет работать {duration} секунд\n")
    
    start_time = time.time()
    last_count = 0
    
    while time.time() - start_time < duration:
        config = load_config()
        write_queue = queue.Queue()
        db_manager = DatabaseManager(config, write_queue)
        
        session = db_manager.Session()
        try:
            current_count = session.query(TrainedModel).count()
            new_models = current_count - last_count
            
            if new_models > 0:
                logger.info(f"⚡ Обучено новых моделей: +{new_models} (всего: {current_count})")
                
                # Показываем последние обученные модели
                latest = session.query(TrainedModel).order_by(
                    TrainedModel.training_date.desc()
                ).limit(new_models).all()
                
                for model in latest:
                    logger.info(f"   ✅ {model.symbol} | {model.model_type} | v{model.version}")
            
            last_count = current_count
            
        finally:
            session.close()
        
        time.sleep(refresh_interval)
    
    logger.info(f"\nМониторинг завершён")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Мониторинг процесса обучения моделей')
    parser.add_argument('--stats', action='store_true', help='Показать общую статистику')
    parser.add_argument('--recent', action='store_true', help='Показать последние сессии обучения')
    parser.add_argument('--monitor', action='store_true', help='Мониторить прогресс в реальном времени')
    parser.add_argument('--duration', type=int, default=300, help='Длительность мониторинга в секундах')
    
    args = parser.parse_args()
    
    if args.stats:
        get_training_statistics()
    
    if args.recent:
        show_recent_training_batches()
    
    if args.monitor:
        monitor_training_progress(duration=args.duration)
    
    # Если не указаны аргументы, показываем всё
    if not (args.stats or args.recent or args.monitor):
        get_training_statistics()
        show_recent_training_batches()
