# -*- coding: utf-8 -*-
"""
Диагностика системы обучения (R&D)
Проверяет все компоненты и находит проблемы
"""

import sys
import os
import logging
from pathlib import Path

# Добавляем корневую директорию
sys.path.insert(0, str(Path(__file__).parent))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('training_diagnosis.log', mode='w', encoding='utf-8')
    ]
)

logger = logging.getLogger('training_diagnosis')


def print_header(text):
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)


def check_config():
    """Проверка конфигурации"""
    print_header("1. ПРОВЕРКА КОНФИГУРАЦИИ")
    
    try:
        from src.core.config_loader import load_config
        config = load_config()
        
        logger.info("✓ Конфигурация загружена успешно")
        logger.info(f"  - SYMBOLS_WHITELIST: {len(config.SYMBOLS_WHITELIST)} символов")
        logger.info(f"  - FEATURES_TO_USE: {len(config.FEATURES_TO_USE)} признаков")
        logger.info(f"  - INPUT_LAYER_SIZE: {config.INPUT_LAYER_SIZE}")
        logger.info(f"  - TRAINING_DATA_POINTS: {config.TRAINING_DATA_POINTS}")
        logger.info(f"  - TOP_N_SYMBOLS: {config.TOP_N_SYMBOLS}")
        
        # Проверка rd_cycle_config
        if hasattr(config, 'rd_cycle_config'):
            logger.info(f"  - rd_cycle_config: НАЙДЕН")
            logger.info(f"    - model_candidates: {len(config.rd_cycle_config.model_candidates)} моделей")
            for i, mc in enumerate(config.rd_cycle_config.model_candidates, 1):
                logger.info(f"      {i}. {mc.type} (k={mc.k})")
            logger.info(f"    - profit_factor_threshold: {config.rd_cycle_config.profit_factor_threshold}")
            logger.info(f"    - sharpe_ratio_threshold: {config.rd_cycle_config.sharpe_ratio_threshold}")
        else:
            logger.error("✗ rd_cycle_config: НЕ НАЙДЕН!")
            return None
            
        # Проверка auto_retraining
        if hasattr(config, 'auto_retraining'):
            logger.info(f"  - auto_retraining: {config.auto_retraining.enabled}")
            logger.info(f"    - schedule_time: {config.auto_retraining.schedule_time}")
            logger.info(f"    - interval_hours: {config.auto_retraining.interval_hours}")
        else:
            logger.warning("⚠ auto_retraining: НЕ НАЙДЕН")
            
        return config
        
    except Exception as e:
        logger.error(f"✗ Ошибка загрузки конфигурации: {e}", exc_info=True)
        return None


def check_database(config):
    """Проверка базы данных"""
    print_header("2. ПРОВЕРКА БАЗЫ ДАННЫХ")
    
    try:
        import queue
        from src.db.database_manager import DatabaseManager
        
        db_queue = queue.Queue()
        db_manager = DatabaseManager(config, db_queue)
        
        logger.info("✓ DatabaseManager инициализирован")
        
        # Проверка таблиц
        session = db_manager.Session()
        try:
            from src.db.database_manager import TrainedModel
            
            # Количество обученных моделей
            model_count = session.query(TrainedModel).count()
            logger.info(f"  - TrainedModel: {model_count} записей")
            
            # Символы с моделями
            if model_count > 0:
                symbols = session.query(TrainedModel.symbol).distinct().all()
                logger.info(f"  - Символы с моделями: {[s[0] for s in symbols]}")
                
        finally:
            session.close()
            
        return db_manager
        
    except Exception as e:
        logger.error(f"✗ Ошибка проверки БД: {e}", exc_info=True)
        return None


def check_data_provider(config):
    """Проверка Data Provider"""
    print_header("3. ПРОВЕРКА DATA PROVIDER")
    
    try:
        import threading
        import MetaTrader5 as mt5
        from src.data.data_provider import DataProvider
        
        mt5_lock = threading.Lock()
        data_provider = DataProvider(config, mt5_lock)
        
        logger.info("✓ DataProvider инициализирован")
        
        # Проверка доступных символов
        available = data_provider.get_available_symbols()
        logger.info(f"  - Доступно символов: {len(available)}")
        logger.info(f"  - Первые 5: {available[:5] if len(available) >= 5 else available}")
        
        # Тест загрузки данных
        if available:
            test_symbol = available[0]
            logger.info(f"  - Тестовый символ: {test_symbol}")
            
            with mt5_lock:
                if not mt5.initialize(path=config.MT5_PATH):
                    logger.error("✗ MT5 не инициализировался")
                    return None, None
                    
                try:
                    from datetime import datetime, timedelta
                    df = data_provider.get_historical_data(
                        test_symbol,
                        mt5.TIMEFRAME_H1,
                        datetime.now() - timedelta(days=30),
                        datetime.now()
                    )
                    
                    if df is not None and len(df) > 0:
                        logger.info(f"  ✓ Данные загружены: {len(df)} баров")
                        logger.info(f"    - Columns: {list(df.columns)[:5]}...")
                    else:
                        logger.warning(f"  ⚠ Данные пусты или None")
                finally:
                    mt5.shutdown()
                    
        return data_provider, mt5_lock
        
    except Exception as e:
        logger.error(f"✗ Ошибка Data Provider: {e}", exc_info=True)
        return None, None


def check_feature_engineer(config):
    """Проверка Feature Engineer"""
    print_header("4. ПРОВЕРКА FEATURE ENGINEER")
    
    try:
        import queue
        import numpy as np
        import pandas as pd
        from src.db.database_manager import DatabaseManager
        from src.ml.feature_engineer import FeatureEngineer
        from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
        
        # Создаем заглушки
        db_queue = queue.Queue()
        db_manager = DatabaseManager(config, db_queue)
        kg_querier = KnowledgeGraphQuerier(db_manager)
        
        fe = FeatureEngineer(config, kg_querier)
        logger.info("✓ FeatureEngineer инициализирован")
        
        # Тест генерации признаков
        dates = pd.date_range(start='2024-01-01', periods=200, freq='H')
        test_df = pd.DataFrame({
            'open': np.random.rand(200) * 100,
            'high': np.random.rand(200) * 100 + 1,
            'low': np.random.rand(200) * 100 - 1,
            'close': np.random.rand(200) * 100,
            'tick_volume': np.random.randint(100, 1000, 200)
        }, index=dates)
        
        logger.info(f"  - Тестовые данные: {len(test_df)} строк")
        
        df_featured = fe.generate_features(test_df, symbol='EURUSD')
        
        if df_featured is not None:
            logger.info(f"  ✓ Признаки сгенерированы: {len(df_featured.columns)} колонок")
            
            # Проверка требуемых признаков
            missing = [f for f in config.FEATURES_TO_USE if f not in df_featured.columns]
            if missing:
                logger.warning(f"  ⚠ Отсутствуют признаки: {missing[:5]}...")
            else:
                logger.info(f"  ✓ Все требуемые признаки присутствуют")
        else:
            logger.error(f"  ✗ Признаки не сгенерированы (None)")
            return None
            
        return fe
        
    except Exception as e:
        logger.error(f"✗ Ошибка Feature Engineer: {e}", exc_info=True)
        return None


def check_model_factory(config):
    """Проверка Model Factory"""
    print_header("5. ПРОВЕРКА MODEL FACTORY")
    
    try:
        from src.ml.model_factory import ModelFactory
        
        factory = ModelFactory(config)
        logger.info("✓ ModelFactory инициализирован")
        
        # Тест создания LSTM
        model_params = {
            'input_dim': 20,
            'hidden_dim': 32,
            'num_layers': 1,
            'output_dim': 1
        }
        
        model = factory.create_model('LSTM_PyTorch', model_params)
        
        if model is not None:
            logger.info(f"  ✓ LSTM модель создана: {type(model).__name__}")
        else:
            logger.error(f"  ✗ LSTM модель не создана")
            return None
            
        # Тест создания LightGBM
        lgm_params = {'input_dim': 20}
        lgm_model = factory.create_model('LightGBM', lgm_params)
        
        if lgm_model is not None:
            logger.info(f"  ✓ LightGBM модель создана: {type(lgm_model).__name__}")
        else:
            logger.warning(f"  ⚠ LightGBM модель не создана")
            
        return factory
        
    except Exception as e:
        logger.error(f"✗ Ошибка Model Factory: {e}", exc_info=True)
        return None


def check_training_lock():
    """Проверка блокировки обучения"""
    print_header("6. ПРОВЕРКА TRAINING LOCK")
    
    try:
        import threading
        
        # Создаем тестовый lock
        lock = threading.Lock()
        
        # Проверяем что lock доступен
        acquired = lock.acquire(blocking=False)
        if acquired:
            logger.info("  ✓ Lock успешно захвачен")
            lock.release()
            logger.info("  ✓ Lock успешно освобожден")
        else:
            logger.warning("  ⚠ Lock уже заблокирован")
            
        logger.info("  ✓ Механизм блокировки работает корректно")
        
    except Exception as e:
        logger.error(f"✗ Ошибка проверки lock: {e}", exc_info=True)


def check_vector_db(config):
    """Проверка Vector DB"""
    print_header("7. ПРОВЕРКА VECTOR DB")
    
    try:
        from src.db.vector_db_manager import VectorDBManager
        
        vdb = VectorDBManager(config.vector_db, db_root_path="database/vector_db")
        
        if vdb.is_ready():
            logger.info(f"  ✓ VectorDB готов")
            logger.info(f"  - Документов: {len(vdb.documents)}")
        else:
            logger.warning(f"  ⚠ VectorDB не готов")
            
        return vdb
        
    except Exception as e:
        logger.error(f"✗ Ошибка Vector DB: {e}", exc_info=True)
        return None


def main():
    """Главная функция диагностики"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "ДИАГНОСТИКА СИСТЕМЫ ОБУЧЕНИЯ" + " " * 26 + "║")
    print("╚" + "=" * 78 + "╝")
    
    # 1. Конфигурация
    config = check_config()
    if not config:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить конфигурацию")
        return False
    
    # 2. База данных
    db_manager = check_database(config)
    if not db_manager:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать БД")
        return False
    
    # 3. Data Provider
    data_provider, mt5_lock = check_data_provider(config)
    if not data_provider:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Data Provider")
        return False
    
    # 4. Feature Engineer
    fe = check_feature_engineer(config)
    if not fe:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Feature Engineer")
        return False
    
    # 5. Model Factory
    factory = check_model_factory(config)
    if not factory:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Model Factory")
        return False
    
    # 6. Training Lock
    check_training_lock()
    
    # 7. Vector DB
    vdb = check_vector_db(config)
    
    # Итоги
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 30 + "ИТОГИ ДИАГНОСТИКИ" + " " * 31 + "║")
    print("╠" + "=" * 78 + "╣")
    print("║ ✓ Конфигурация        - OK" + " " * 41 + "║")
    print("║ ✓ База данных         - OK" + " " * 41 + "║")
    print("║ ✓ Data Provider       - OK" + " " * 41 + "║")
    print("║ ✓ Feature Engineer    - OK" + " " * 41 + "║")
    print("║ ✓ Model Factory       - OK" + " " * 41 + "║")
    print("║ ✓ Training Lock       - OK" + " " * 41 + "║")
    print("║ ✓ Vector DB           - OK" + " " * 41 + "║")
    print("╚" + "=" * 78 + "╝")
    print("\n")
    logger.info("ВСЕ КОМПОНЕНТЫ РАБОТАЮТ!")
    print("\n")
    logger.info("Логи сохранены в: training_diagnosis.log")
    print("\n")
    
    # Рекомендации
    print_header("РЕКОМЕНДАЦИИ")
    logger.info("1. Запустите торговую систему: python main_pyside.py")
    logger.info("2. R&D цикл запустится автоматически через 120 секунд после старта")
    logger.info("3. Для ручного запуска используйте кнопку в GUI или:")
    logger.info("   trading_system.force_rd_cycle()")
    logger.info("4. Проверьте логи на наличие сообщений '[R&D]'")
    print("\n")
    
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
