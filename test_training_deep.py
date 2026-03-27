#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тест для глубокой проверки системы обучения (R&D)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import logging
from datetime import datetime, timedelta
import pandas as pd

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger('training_test')

def test_step_1_config():
    """Шаг 1: Проверка конфигурации"""
    logger.info("=" * 80)
    logger.info("ШАГ 1: ПРОВЕРКА КОНФИГУРАЦИИ")
    logger.info("=" * 80)
    
    try:
        from src.core.config_loader import load_config
        config = load_config()
        
        logger.info(f"✓ Конфигурация загружена")
        logger.info(f"  - TRAINING_INTERVAL_SECONDS: {config.TRAINING_INTERVAL_SECONDS}")
        logger.info(f"  - TRAINING_DATA_POINTS: {config.TRAINING_DATA_POINTS}")
        logger.info(f"  - INPUT_LAYER_SIZE: {config.INPUT_LAYER_SIZE}")
        logger.info(f"  - FEATURES_TO_USE: {len(config.FEATURES_TO_USE)} признаков")
        logger.info(f"  - SYMBOLS_WHITELIST: {len(config.SYMBOLS_WHITELIST)} символов")
        logger.info(f"  - TOP_N_SYMBOLS: {config.TOP_N_SYMBOLS}")
        
        # Проверка model_candidates
        if hasattr(config, 'rd_cycle_config'):
            logger.info(f"  - model_candidates: {len(config.rd_cycle_config.model_candidates)} моделей")
            for i, candidate in enumerate(config.rd_cycle_config.model_candidates, 1):
                logger.info(f"    {i}. {candidate.type}")
        else:
            logger.error("✗ rd_cycle_config не найден!")
            return None
        
        logger.info("=" * 80)
        return config
        
    except Exception as e:
        logger.error(f"✗ Ошибка загрузки конфига: {e}", exc_info=True)
        return None

def test_step_2_database():
    """Шаг 2: Проверка БД"""
    logger.info("=" * 80)
    logger.info("ШАГ 2: ПРОВЕРКА БАЗЫ ДАННЫХ")
    logger.info("=" * 80)
    
    try:
        from src.core.config_loader import load_config
        from src.db.database_manager import DatabaseManager
        import queue
        
        config = load_config()
        db_queue = queue.Queue()
        db_manager = DatabaseManager(config, db_queue)
        
        logger.info(f"✓ База данных инициализирована")
        
        # Проверка количества моделей
        session = db_manager.Session()
        try:
            from src.db.database_manager import TrainedModel
            model_count = session.query(TrainedModel).count()
            logger.info(f"  - Всего моделей в БД: {model_count}")
            
            # Проверка символов с моделями
            symbols_with_models = session.query(TrainedModel.symbol).distinct().all()
            logger.info(f"  - Символы с моделями: {[s[0] for s in symbols_with_models]}")
        finally:
            session.close()
        
        logger.info("=" * 80)
        return db_manager
        
    except Exception as e:
        logger.error(f"✗ Ошибка БД: {e}", exc_info=True)
        return None

def test_step_3_data_provider(config):
    """Шаг 3: Проверка Data Provider"""
    logger.info("=" * 80)
    logger.info("ШАГ 3: ПРОВЕРКА DATA PROVIDER")
    logger.info("=" * 80)
    
    try:
        import threading
        from src.data.data_provider import DataProvider
        
        mt5_lock = threading.Lock()
        data_provider = DataProvider(config, mt5_lock)
        
        logger.info(f"✓ Data Provider инициализирован")
        
        # Проверка доступности символов
        available = data_provider.get_available_symbols()
        logger.info(f"  - Доступно символов: {len(available)}")
        logger.info(f"  - Первые 5: {available[:5]}")
        
        # Попытка загрузки данных для одного символа
        if available:
            test_symbol = available[0]
            logger.info(f"  - Тестовый символ: {test_symbol}")
            
            with mt5_lock:
                import MetaTrader5 as mt5
                if not mt5.initialize(path=config.MT5_PATH):
                    logger.error(f"✗ MT5 не инициализировался")
                    return None, None
                
                try:
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
        
        logger.info("=" * 80)
        return data_provider, mt5_lock
        
    except Exception as e:
        logger.error(f"✗ Ошибка Data Provider: {e}", exc_info=True)
        return None, None

def test_step_4_feature_engineer(config):
    """Шаг 4: Проверка Feature Engineer"""
    logger.info("=" * 80)
    logger.info("ШАГ 4: ПРОВЕРКА FEATURE ENGINEER")
    logger.info("=" * 80)
    
    try:
        from src.ml.feature_engineer import FeatureEngineer
        from src.db.database_manager import DatabaseManager
        import queue
        
        # Создаем заглушки
        db_queue = queue.Queue()
        db_manager = DatabaseManager(config, db_queue)
        from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
        kg_querier = KnowledgeGraphQuerier(db_manager)
        
        fe = FeatureEngineer(config, kg_querier)
        logger.info(f"✓ Feature Engineer инициализирован")
        
        # Создаем тестовые данные
        import numpy as np
        dates = pd.date_range(start='2024-01-01', periods=100, freq='H')
        test_df = pd.DataFrame({
            'open': np.random.rand(100) * 100,
            'high': np.random.rand(100) * 100 + 1,
            'low': np.random.rand(100) * 100 - 1,
            'close': np.random.rand(100) * 100,
            'tick_volume': np.random.randint(100, 1000, 100)
        }, index=dates)
        
        logger.info(f"  - Тестовые данные: {len(test_df)} строк")
        
        # Генерация признаков
        df_featured = fe.generate_features(test_df, symbol='EURUSD')
        
        if df_featured is not None:
            logger.info(f"  ✓ Признаки сгенерированы: {len(df_featured.columns)} колонок")
            logger.info(f"    - Первые 10: {list(df_featured.columns)[:10]}")
        else:
            logger.warning(f"  ⚠ Признаки не сгенерированы (None)")
        
        logger.info("=" * 80)
        return fe
        
    except Exception as e:
        logger.error(f"✗ Ошибка Feature Engineer: {e}", exc_info=True)
        return None

def test_step_5_model_factory(config):
    """Шаг 5: Проверка Model Factory"""
    logger.info("=" * 80)
    logger.info("ШАГ 5: ПРОВЕРКА MODEL FACTORY")
    logger.info("=" * 80)
    
    try:
        from src.ml.model_factory import ModelFactory
        
        factory = ModelFactory(config)
        logger.info(f"✓ Model Factory инициализирован")
        
        # Тест создания модели
        model_params = {
            'input_dim': 20,
            'hidden_dim': 32,
            'num_layers': 1,
            'output_dim': 1
        }
        
        model = factory.create_model('LSTM_PyTorch', model_params)
        
        if model is not None:
            logger.info(f"  ✓ Модель LSTM создана: {type(model).__name__}")
        else:
            logger.warning(f"  ⚠ Модель не создана (None)")
        
        logger.info("=" * 80)
        return factory
        
    except Exception as e:
        logger.error(f"✗ Ошибка Model Factory: {e}", exc_info=True)
        return None

def main():
    """Главная функция"""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 20 + "ТЕСТ СИСТЕМЫ ОБУЧЕНИЯ (R&D)" + " " * 27 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")
    
    # Шаг 1: Конфигурация
    config = test_step_1_config()
    if not config:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить конфигурацию")
        return False
    
    # Шаг 2: База данных
    db_manager = test_step_2_database()
    if not db_manager:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать БД")
        return False
    
    # Шаг 3: Data Provider
    data_provider, mt5_lock = test_step_3_data_provider(config)
    if not data_provider:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Data Provider")
        return False
    
    # Шаг 4: Feature Engineer
    fe = test_step_4_feature_engineer(config)
    if not fe:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Feature Engineer")
        return False
    
    # Шаг 5: Model Factory
    factory = test_step_5_model_factory(config)
    if not factory:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Model Factory")
        return False
    
    # Итоги
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 25 + "ИТОГИ ТЕСТИРОВАНИЯ" + " " * 33 + "║")
    logger.info("╠" + "=" * 78 + "╣")
    logger.info("║ ✓ Конфигурация        - OK" + " " * 41 + "║")
    logger.info("║ ✓ База данных         - OK" + " " * 41 + "║")
    logger.info("║ ✓ Data Provider       - OK" + " " * 41 + "║")
    logger.info("║ ✓ Feature Engineer    - OK" + " " * 41 + "║")
    logger.info("║ ✓ Model Factory       - OK" + " " * 41 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")
    logger.info("ВСЕ КОМПОНЕНТЫ РАБОТАЮТ!")
    logger.info("\n")
    logger.info("Следующий шаг: Запустить полный цикл обучения через GUI или:")
    logger.info("  trading_system.force_training_cycle()")
    logger.info("\n")
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
