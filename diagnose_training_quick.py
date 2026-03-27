# -*- coding: utf-8 -*-
"""
Упрощенная диагностика системы обучения (без MT5)
"""

import sys
import os
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('training_quick_diagnosis.log', mode='w', encoding='utf-8')
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
        
        # Проверка rd_cycle_config
        if hasattr(config, 'rd_cycle_config'):
            logger.info(f"  ✓ rd_cycle_config: НАЙДЕН")
            logger.info(f"    - model_candidates: {len(config.rd_cycle_config.model_candidates)} моделей")
            for i, mc in enumerate(config.rd_cycle_config.model_candidates, 1):
                logger.info(f"      {i}. {mc.type} (k={mc.k})")
        else:
            logger.error("✗ rd_cycle_config: НЕ НАЙДЕН!")
            return None
            
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
        
        session = db_manager.Session()
        try:
            from src.db.database_manager import TrainedModel
            
            model_count = session.query(TrainedModel).count()
            logger.info(f"  - TrainedModel: {model_count} записей")
            
            if model_count > 0:
                symbols = session.query(TrainedModel.symbol).distinct().all()
                logger.info(f"  - Символы с моделями: {[s[0] for s in symbols]}")
                
                # Проверка champion моделей
                champions = session.query(TrainedModel).filter_by(is_champion=True).all()
                logger.info(f"  - Champion моделей: {len(champions)}")
                
                # Критично: если НЕТ champion моделей - это проблема!
                if len(champions) == 0:
                    logger.warning("  ⚠ ВНИМАНИЕ: НЕТ CHAMPION МОДЕЛЕЙ! Это может блокировать обучение.")
                else:
                    logger.info(f"  ✓ Champion модели найдены")
            
        finally:
            session.close()
            
        return db_manager
        
    except Exception as e:
        logger.error(f"✗ Ошибка проверки БД: {e}", exc_info=True)
        return None


def check_feature_engineer(config):
    """Проверка Feature Engineer"""
    print_header("3. ПРОВЕРКА FEATURE ENGINEER")
    
    try:
        import queue
        import numpy as np
        import pandas as pd
        from src.db.database_manager import DatabaseManager
        from src.ml.feature_engineer import FeatureEngineer
        from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
        
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
        
        df_featured = fe.generate_features(test_df, symbol='EURUSD')
        
        if df_featured is not None:
            logger.info(f"  ✓ Признаки сгенерированы: {len(df_featured.columns)} колонок")
            
            missing = [f for f in config.FEATURES_TO_USE if f not in df_featured.columns]
            if missing:
                logger.warning(f"  ⚠ Отсутствуют признаки ({len(missing)}): {missing[:3]}...")
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
    print_header("4. ПРОВЕРКА MODEL FACTORY")
    
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


def check_vector_db(config):
    """Проверка Vector DB"""
    print_header("5. ПРОВЕРКА VECTOR DB")
    
    try:
        from src.db.vector_db_manager import VectorDBManager
        
        vdb = VectorDBManager(config.vector_db, db_root_path="database/vector_db")
        
        if vdb.is_ready():
            logger.info(f"  ✓ VectorDB готов: {len(vdb.documents)} документов")
        else:
            logger.warning(f"  ⚠ VectorDB не готов")
            
        return vdb
        
    except Exception as e:
        logger.error(f"✗ Ошибка Vector DB: {e}", exc_info=True)
        return None


def analyze_training_issues(config, db_manager):
    """Анализ проблем обучения"""
    print_header("6. АНАЛИЗ ПРОБЛЕМ ОБУЧЕНИЯ")
    
    issues = []
    
    try:
        session = db_manager.Session()
        try:
            from src.db.database_manager import TrainedModel
            
            # 1. Проверка champion моделей
            champions = session.query(TrainedModel).filter_by(is_champion=True).all()
            
            if len(champions) == 0:
                issues.append({
                    'severity': 'CRITICAL',
                    'message': 'НЕТ CHAMPION МОДЕЛЕЙ',
                    'solution': 'R&D цикл не может выбрать challenger модели без существующих champion'
                })
                logger.error("✗ CRITICAL: НЕТ CHAMPION МОДЕЛЕЙ!")
                logger.error("  Решение: Удалите старые модели или запустите принудительное обучение")
            else:
                logger.info(f"  ✓ Champion модели найдены: {len(champions)}")
            
            # 2. Проверка количества данных для обучения
            logger.info(f"  - TRAINING_DATA_POINTS: {config.TRAINING_DATA_POINTS}")
            logger.info(f"  - INPUT_LAYER_SIZE: {config.INPUT_LAYER_SIZE}")
            
            min_required = config.INPUT_LAYER_SIZE + 100
            if config.TRAINING_DATA_POINTS < min_required:
                issues.append({
                    'severity': 'WARNING',
                    'message': f'Недостаточно данных для обучения',
                    'solution': f'Увеличьте TRAINING_DATA_POINTS до {min_required}+'
                })
                logger.warning(f"  ⚠ TRAINING_DATA_POINTS ({config.TRAINING_DATA_POINTS}) < {min_required}")
            else:
                logger.info(f"  ✓ Данных достаточно")
            
            # 3. Проверка порогов для R&D
            logger.info(f"  - profit_factor_threshold: {config.rd_cycle_config.profit_factor_threshold}")
            logger.info(f"  - sharpe_ratio_threshold: {config.rd_cycle_config.sharpe_ratio_threshold}")
            
            if config.rd_cycle_config.profit_factor_threshold > 2.0:
                issues.append({
                    'severity': 'WARNING',
                    'message': 'Слишком высокий порог profit factor',
                    'solution': 'Снизьте до 1.2-1.5 для начала'
                })
                logger.warning(f"  ⚠ profit_factor_threshold ({config.rd_cycle_config.profit_factor_threshold}) слишком высокий")
            else:
                logger.info(f"  ✓ Пороги в норме")
                
            # 4. Проверка model_candidates
            if len(config.rd_cycle_config.model_candidates) == 0:
                issues.append({
                    'severity': 'CRITICAL',
                    'message': 'Нет моделей-кандидатов',
                    'solution': 'Добавьте model_candidates в rd_cycle_config'
                })
                logger.error("✗ CRITICAL: НЕТ МОДЕЛЕЙ-КАНДИДАТОВ!")
            else:
                logger.info(f"  ✓ Моделей-кандидатов: {len(config.rd_cycle_config.model_candidates)}")
                
        finally:
            session.close()
            
        # Итоги анализа
        print("\n")
        if issues:
            logger.warning(f"  НАЙДЕНО ПРОБЛЕМ: {len(issues)}")
            for i, issue in enumerate(issues, 1):
                logger.warning(f"  {i}. [{issue['severity']}] {issue['message']}")
                logger.warning(f"     Решение: {issue['solution']}")
        else:
            logger.info("  ✓ Проблем не обнаружено")
            
        return issues
        
    except Exception as e:
        logger.error(f"✗ Ошибка анализа: {e}", exc_info=True)
        return []


def main():
    """Главная функция"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 15 + "БЫСТРАЯ ДИАГНОСТИКА СИСТЕМЫ ОБУЧЕНИЯ" + " " * 23 + "║")
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
    
    # 3. Feature Engineer
    fe = check_feature_engineer(config)
    if not fe:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Feature Engineer")
        return False
    
    # 4. Model Factory
    factory = check_model_factory(config)
    if not factory:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать Model Factory")
        return False
    
    # 5. Vector DB
    vdb = check_vector_db(config)
    
    # 6. Анализ проблем
    issues = analyze_training_issues(config, db_manager)
    
    # Итоги
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 35 + "ИТОГИ" + " " * 38 + "║")
    print("╠" + "=" * 78 + "╣")
    
    if issues:
        critical_issues = [i for i in issues if i['severity'] == 'CRITICAL']
        if critical_issues:
            print("║ ⚠ НАЙДЕНЫ КРИТИЧЕСКИЕ ПРОБЛЕМЫ!" + " " * 44 + "║")
            print("║ Обучение НЕ СМОЖЕТ работать до их устранения" + " " * 31 + "║")
        else:
            print("║ ⚠ НАЙДЕНЫ ПРЕДУПРЕЖДЕНИЯ" + " " * 51 + "║")
            print("║ Обучение может работать некорректно" + " " * 40 + "║")
    else:
        print("║ ✓ ВСЕ КОМПОНЕНТЫ В НОРМЕ" + " " * 51 + "║")
        print("║ Обучение готово к запуску" + " " * 50 + "║")
    
    print("╚" + "=" * 78 + "╝")
    print("\n")
    
    logger.info("Логи сохранены в: training_quick_diagnosis.log")
    print("\n")
    
    # Рекомендации
    print_header("СЛЕДУЮЩИЕ ШАГИ")
    
    if any(i['severity'] == 'CRITICAL' for i in issues):
        logger.info("1. ❗ Устраните критические проблемы (см. выше)")
        logger.info("2. Запустите: python retrain_symbols.py EURUSD")
        logger.info("3. После перезапустите систему: python main_pyside.py")
    else:
        logger.info("1. Запустите систему: python main_pyside.py")
        logger.info("2. R&D цикл запустится через 120 секунд после старта")
        logger.info("3. Для ручного запуска используйте кнопку в GUI")
        logger.info("4. Проверьте логи на наличие '[R&D]'")
    
    print("\n")
    
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
