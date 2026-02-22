"""
Запуск торговой системы без GUI (headless mode)
Обходит проблему с крашем VCRUNTIME140.dll в PySide6
"""
import sys
import os
import time
import logging

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.config_loader import load_config
from src.core.trading_system import TradingSystem
from src.db.database_manager import DatabaseManager
from src.db.vector_db_manager import VectorDBManager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('F:\\Enjen\\logs\\headless_system.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Запуск системы без GUI"""
    try:
        logger.info("=== ЗАПУСК HEADLESS MODE ===")
        
        # Загрузка конфигурации
        config = load_config()
        logger.info("Конфигурация загружена")
        
        # Инициализация БД
        db_manager = DatabaseManager(config)
        vector_db = VectorDBManager(config)
        logger.info("Базы данных инициализированы")
        
        # Инициализация торговой системы
        trading_system = TradingSystem(
            config=config,
            db_manager=db_manager,
            vector_db_manager=vector_db
        )
        logger.info("Торговая система инициализирована")
        
        # Запуск всех потоков
        trading_system.start_all_threads()
        logger.info("Все потоки запущены")
        
        logger.info("=== СИСТЕМА РАБОТАЕТ ===")
        logger.info("Для остановки нажмите Ctrl+C")
        logger.info(f"Веб-дашборд: http://0.0.0.0:{config.web_dashboard['port']}")
        
        # Основной цикл
        while trading_system.running:
            time.sleep(10)
            
            # Периодический вывод статуса
            if int(time.time()) % 60 == 0:
                logger.info(f"Система работает. Потоков активно: {trading_system.running}")
                
    except KeyboardInterrupt:
        logger.info("\n=== ПОЛУЧЕН СИГНАЛ ОСТАНОВКИ ===")
        if 'trading_system' in locals():
            trading_system.initiate_graceful_shutdown()
            logger.info("Ожидание завершения потоков...")
            time.sleep(5)
        logger.info("Система остановлена")
        
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
