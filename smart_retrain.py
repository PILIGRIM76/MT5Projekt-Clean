"""
Smart Retrain Module - Автоматическое переобучение моделей.
Удаляет устаревшие модели из базы данных, R&D цикл автоматически переобучит их.
"""
import sys
import logging
import queue
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from src.core.config_loader import load_config
from src.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)


def get_candidate_symbols(db_manager, max_symbols: int) -> list:
    """
    Выбирает лучшие символы для переобучения на основе:
    - Времени последнего обучения (старые - лучше)
    - Прибыльности (прибыльные - приоритет)
    - Волатильности (достаточная волатильность для обучения)
    
    Args:
        db_manager: DatabaseManager instance
        max_symbols: Максимальное количество символов
        
    Returns:
        Список символов для переобучения
    """
    try:
        # Получаем все символы с их последними метриками
        query = """
            SELECT 
                cm.symbol,
                cm.win_rate,
                cm.profit_factor,
                cm.total_trades,
                cm.last_trained_at,
                cm.model_accuracy
            FROM champion_models cm
            WHERE cm.last_trained_at IS NOT NULL
            ORDER BY 
                cm.last_trained_at ASC,
                cm.profit_factor DESC,
                cm.win_rate DESC
            LIMIT ?
        """
        results = db_manager.execute_query(query, (max_symbols,), fetch_all=True)
        
        if results:
            symbols = [row[0] for row in results]
            logger.info(f"Найдено {len(symbols)} кандидатов для переобучения: {symbols}")
            return symbols
        
    except Exception as e:
        logger.error(f"Ошибка при получении кандидатов: {e}")
    
    return []


def get_all_available_symbols(db_manager) -> list:
    """
    Получает все доступные символы из базы данных.
    
    Returns:
        Список всех доступных символов
    """
    try:
        query = "SELECT DISTINCT symbol FROM champion_models ORDER BY symbol"
        results = db_manager.execute_query(query, fetch_all=True)
        
        if results:
            symbols = [row[0] for row in results]
            return symbols
        
    except Exception as e:
        logger.error(f"Ошибка при получении символов: {e}")
    
    return []


def smart_retrain_models(max_symbols: int = 30, max_workers: int = 3) -> dict:
    """
    Умное переобучение моделей:
    1. Выбирает лучшие символы для переобучения
    2. Удаляет их модели из базы данных
    3. R&D цикл автоматически переобучит их при следующем запуске
    
    Args:
        max_symbols: Максимальное количество символов для переобучения
        max_workers: Количество параллельных потоков (для совместимости)
        
    Returns:
        Словарь с результатами переобучения
    """
    logger.info("="*80)
    logger.info("ЗАПУСК SMART ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
    logger.info(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Параметры: max_symbols={max_symbols}, max_workers={max_workers}")
    logger.info("="*80)
    
    start_time = datetime.now()
    results = {
        'status': 'started',
        'symbols_selected': 0,
        'models_deleted': 0,
        'errors': [],
        'duration_seconds': 0
    }
    
    try:
        # Загрузка конфигурации
        logger.info("Загрузка конфигурации...")
        config = load_config()
        
        # Создаем очередь для DatabaseManager
        write_queue = queue.Queue()
        
        # Инициализация DatabaseManager
        logger.info("Инициализация базы данных...")
        db_manager = DatabaseManager(config, write_queue)
        
        # Получаем символы для переобучения
        symbols = get_candidate_symbols(db_manager, max_symbols)
        
        if not symbols:
            # Если нет моделей, пробуем получить все доступные символы
            logger.info("Моделей не найдено, проверяем доступные символы...")
            symbols = get_all_available_symbols(db_manager)
            
            if not symbols:
                logger.warning("Нет доступных символов для переобучения")
                results['status'] = 'no_symbols'
                return results
        
        results['symbols_selected'] = len(symbols)
        logger.info(f"Выбрано символов для переобучения: {len(symbols)}")
        
        # Удаляем модели для выбранных символов
        total_deleted = 0
        for symbol in symbols:
            try:
                logger.info(f"\nОбработка символа: {symbol}")
                
                # Проверяем, сколько моделей есть для этого символа
                check_query = "SELECT COUNT(*) as count FROM champion_models WHERE symbol = ?"
                result = db_manager.execute_query(check_query, (symbol,), fetch_one=True)
                
                if result and result[0] > 0:
                    count_before = result[0]
                    
                    # Удаляем модели
                    delete_query = "DELETE FROM champion_models WHERE symbol = ?"
                    db_manager.execute_query(delete_query, (symbol,))
                    
                    # Проверяем результат
                    result_after = db_manager.execute_query(check_query, (symbol,), fetch_one=True)
                    count_after = result_after[0] if result_after else 0
                    
                    deleted = count_before - count_after
                    total_deleted += deleted
                    
                    logger.info(f"  ✓ Удалено моделей для {symbol}: {deleted}")
                else:
                    logger.info(f"  Модели для {symbol} не найдены")
                    
            except Exception as e:
                logger.error(f"  ✗ Ошибка при обработке {symbol}: {e}")
                results['errors'].append({'symbol': symbol, 'error': str(e)})
        
        results['models_deleted'] = total_deleted
        results['status'] = 'success'
        
        duration = (datetime.now() - start_time).total_seconds()
        results['duration_seconds'] = duration
        
        logger.info("\n" + "="*80)
        logger.info("SMART ПЕРЕОБУЧЕНИЕ ЗАВЕРШЕНО")
        logger.info(f"Символов обработано: {len(symbols)}")
        logger.info(f"Моделей удалено: {total_deleted}")
        logger.info(f"Длительность: {duration:.2f} сек")
        logger.info("="*80)
        logger.info("\nСледующие шаги:")
        logger.info("1. R&D цикл автоматически переобучит модели при следующем запуске")
        logger.info("2. Новые модели будут использовать текущие параметры")
        logger.info("3. Проверьте логи на наличие сообщений '[R&D]' для отслеживания прогресса")
        
    except Exception as e:
        logger.error(f"Критическая ошибка при smart переобучении: {e}", exc_info=True)
        results['status'] = 'error'
        results['errors'].append({'global': str(e)})
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Smart Retrain Models')
    parser.add_argument('--max_symbols', type=int, default=30, help='Max symbols to retrain')
    parser.add_argument('--max_workers', type=int, default=3, help='Number of parallel workers')
    
    args = parser.parse_args()
    
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    result = smart_retrain_models(
        max_symbols=args.max_symbols,
        max_workers=args.max_workers
    )
    
    print(f"\nРезультат: {result}")
    sys.exit(0 if result['status'] == 'success' else 1)