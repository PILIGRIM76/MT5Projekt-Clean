"""
Скрипт для переобучения моделей конкретных символов
Удаляет старые модели из базы данных, после чего R&D цикл автоматически переобучит их.

Использование: python retrain_symbols.py BITCOIN USDJPY
"""
import sys
import logging
import queue
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from src.core.config_loader import load_config
from src.db.database_manager import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Принудительный вывод для отладки
logger.info("=== СКРИПТ ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ ===")


def retrain_symbols(symbols: list):
    """
    Удаляет модели для указанных символов из базы данных.
    R&D цикл автоматически переобучит их при следующем запуске.
    
    Args:
        symbols: Список символов для переобучения (например, ['BITCOIN', 'USDJPY'])
    """
    logger.info(f"Начало процесса переобучения моделей для символов: {symbols}")
    logger.info("="*60)
    
    # Инициализация
    logger.info("Загрузка конфигурации...")
    config = load_config()
    
    # Создаем очередь для DatabaseManager
    write_queue = queue.Queue()
    
    # Инициализация DatabaseManager
    logger.info("Инициализация базы данных...")
    db_manager = DatabaseManager(config, write_queue)
    
    total_deleted = 0
    
    for symbol in symbols:
        logger.info(f"\n{'='*60}")
        logger.info(f"Обработка символа: {symbol}")
        logger.info(f"{'='*60}")
        
        try:
            # Проверяем, сколько моделей есть для этого символа
            check_query = "SELECT COUNT(*) as count FROM champion_models WHERE symbol = ?"
            result = db_manager.execute_query(check_query, (symbol,), fetch_one=True)
            
            if result and result[0] > 0:
                count_before = result[0]
                logger.info(f"Найдено моделей для {symbol}: {count_before}")
                
                # Удаляем модели
                logger.info(f"Удаление моделей для {symbol}...")
                delete_query = "DELETE FROM champion_models WHERE symbol = ?"
                db_manager.execute_query(delete_query, (symbol,))
                
                # Проверяем результат
                result_after = db_manager.execute_query(check_query, (symbol,), fetch_one=True)
                count_after = result_after[0] if result_after else 0
                
                deleted = count_before - count_after
                total_deleted += deleted
                
                logger.info(f"✓ Удалено моделей для {symbol}: {deleted}")
            else:
                logger.warning(f"Модели для {symbol} не найдены в базе данных")
            
        except Exception as e:
            logger.error(f"✗ Ошибка при обработке {symbol}: {e}", exc_info=True)
    
    logger.info("\n" + "="*60)
    logger.info(f"Процесс завершен!")
    logger.info(f"Всего удалено моделей: {total_deleted}")
    logger.info("="*60)
    logger.info("\nСледующие шаги:")
    logger.info("1. Запустите торговую систему: python main_pyside.py")
    logger.info("2. R&D цикл автоматически переобучит модели для указанных символов")
    logger.info("3. Новые модели будут использовать правильный набор признаков (20 без KG)")
    logger.info("4. Проверьте логи на наличие сообщений '[R&D]' для отслеживания прогресса")


if __name__ == "__main__":
    logger.info("=== MAIN BLOCK EXECUTED ===")
    # Получаем символы из аргументов командной строки
    if len(sys.argv) < 2:
        logger.error("ERROR: No symbols provided")
        logger.error("Использование: python retrain_symbols.py SYMBOL1 SYMBOL2 ...")
        logger.error("Пример: python retrain_symbols.py BITCOIN USDJPY")
        sys.exit(1)
    
    logger.info(f"Arguments: {sys.argv}")
    symbols = sys.argv[1:]
    logger.info(f"Symbols to retrain: {symbols}")
    retrain_symbols(symbols)
