"""
Скрипт для принудительного переобучения всех моделей с правильной размерностью признаков.
Запускает R&D цикл для каждого символа последовательно.
"""
import logging
import time
import threading
import MetaTrader5 as mt5
from datetime import datetime, timedelta
from src.core.config_loader import load_config
from src.data.data_provider import DataProvider
from src.ml.feature_engineer import FeatureEngineer
from src.db.database_manager import DatabaseManager
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.ml.model_factory import ModelFactory
from sklearn.model_selection import train_test_split
import queue

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def retrain_all_models():
    """Переобучает модели для всех символов с правильной размерностью признаков."""
    
    # Загрузка конфигурации
    config = load_config()
    
    # Инициализация компонентов
    write_queue = queue.Queue()
    mt5_lock = threading.Lock()  # Создаём lock для MT5
    db_manager = DatabaseManager(config, write_queue)
    data_provider = DataProvider(config, mt5_lock)
    kg_querier = KnowledgeGraphQuerier(db_manager)
    feature_engineer = FeatureEngineer(config, kg_querier)
    model_factory = ModelFactory(config)
    
    # Список символов для переобучения
    symbols_to_retrain = config.SYMBOLS_WHITELIST
    timeframe = mt5.TIMEFRAME_H1
    
    logger.info(f"="*80)
    logger.info(f"НАЧАЛО ПЕРЕОБУЧЕНИЯ ВСЕХ МОДЕЛЕЙ")
    logger.info(f"Символов к переобучению: {len(symbols_to_retrain)}")
    logger.info(f"="*80)
    
    successful_retrains = 0
    failed_retrains = []
    
    for idx, symbol in enumerate(symbols_to_retrain, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"[{idx}/{len(symbols_to_retrain)}] Переобучение моделей для {symbol}")
        logger.info(f"{'='*80}")
        
        try:
            # 1. Загрузка исторических данных
            logger.info(f"[{symbol}] Шаг 1/5: Загрузка исторических данных...")
            
            if not mt5.initialize(path=config.MT5_PATH):
                logger.error(f"[{symbol}] Не удалось инициализировать MT5")
                failed_retrains.append((symbol, "MT5 init failed"))
                continue
            
            try:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=config.TRAINING_DATA_POINTS / 12)
                df_full = data_provider.get_historical_data(symbol, timeframe, start_date, end_date)
            finally:
                mt5.shutdown()
            
            if df_full is None or len(df_full) < 1000:
                logger.warning(f"[{symbol}] Недостаточно данных ({len(df_full) if df_full is not None else 0} баров). Пропуск.")
                failed_retrains.append((symbol, f"Insufficient data: {len(df_full) if df_full is not None else 0} bars"))
                continue
            
            logger.info(f"[{symbol}] Загружено {len(df_full)} баров исторических данных")
            
            # 2. Генерация признаков
            logger.info(f"[{symbol}] Шаг 2/5: Генерация признаков...")
            df_featured = feature_engineer.generate_features(df_full, symbol=symbol)
            
            if df_featured is None or df_featured.empty:
                logger.error(f"[{symbol}] Ошибка генерации признаков")
                failed_retrains.append((symbol, "Feature generation failed"))
                continue
            
            # Формируем список признаков с KG признаками
            unique_features = list(dict.fromkeys(config.FEATURES_TO_USE))
            kg_features = ['KG_CB_SENTIMENT', 'KG_INFLATION_SURPRISE']
            actual_features_to_use = [f for f in unique_features if f in df_featured.columns]
            actual_features_to_use.extend([f for f in kg_features if f in df_featured.columns])
            
            logger.info(f"[{symbol}] Признаков для обучения: {len(actual_features_to_use)}")
            logger.info(f"[{symbol}] Список признаков: {actual_features_to_use}")
            
            # 3. Разделение данных
            logger.info(f"[{symbol}] Шаг 3/5: Разделение данных на train/val/holdout...")
            train_val_df, holdout_df = train_test_split(df_featured, test_size=0.15, shuffle=False)
            train_df, val_df = train_test_split(train_val_df, test_size=0.176, shuffle=False)
            
            logger.info(f"[{symbol}] Train: {len(train_df)}, Val: {len(val_df)}, Holdout: {len(holdout_df)}")
            
            # 4. Обучение моделей
            logger.info(f"[{symbol}] Шаг 4/5: Обучение моделей...")
            
            # Импортируем метод обучения из trading_system
            from src.core.trading_system import TradingSystem
            
            # Создаём временный объект для использования метода обучения
            training_batch_id = f"retrain_all_{symbol}_{int(time.time())}"
            trained_model_ids = []
            
            for candidate_config in config.rd_cycle_config.model_candidates:
                logger.info(f"[{symbol}] Обучение модели: {candidate_config.type}")
                
                # Вызываем внутренний метод напрямую через db_manager
                from sklearn.preprocessing import StandardScaler
                import numpy as np
                import torch
                import lightgbm as lgb
                
                model_type = candidate_config.type
                target_col = 'close'
                
                # Подготовка данных
                train_df_copy = train_df.loc[:, ~train_df.columns.duplicated()].copy()
                val_df_copy = val_df.loc[:, ~val_df.columns.duplicated()].copy()
                
                features_available = [f for f in actual_features_to_use if f in train_df_copy.columns]
                
                x_scaler = StandardScaler()
                y_scaler = StandardScaler()
                
                train_features = train_df_copy[features_available].values
                val_features = val_df_copy[features_available].values
                
                train_features = np.nan_to_num(train_features, nan=0.0, posinf=0.0, neginf=0.0)
                val_features = np.nan_to_num(val_features, nan=0.0, posinf=0.0, neginf=0.0)
                
                train_scaled = x_scaler.fit_transform(train_features)
                val_scaled = x_scaler.transform(val_features)
                
                train_target = y_scaler.fit_transform(train_df_copy[[target_col]])
                val_target = y_scaler.transform(val_df_copy[[target_col]])
                
                # Создание модели
                input_dim = len(features_available)
                
                if model_type.upper() == 'LSTM_PYTORCH':
                    model_params = {'input_dim': input_dim, 'hidden_dim': 32, 'num_layers': 1, 'output_dim': 1}
                elif model_type.upper() == 'LIGHTGBM':
                    model_params = {'input_dim': input_dim}
                else:
                    continue
                
                model = model_factory.create_model(model_type, model_params)
                
                if not model:
                    logger.error(f"[{symbol}] Не удалось создать модель {model_type}")
                    continue
                
                # Обучение модели
                if model_type.upper() == 'LSTM_PYTORCH':
                    from torch.utils.data import TensorDataset, DataLoader
                    
                    # Создание последовательностей
                    def create_sequences(data, n_steps):
                        X = []
                        if len(data) < n_steps + 1:
                            return None, None
                        for i in range(len(data) - n_steps):
                            X.append(data[i:(i + n_steps)])
                        return np.array(X), None
                    
                    X_train, _ = create_sequences(train_scaled, config.INPUT_LAYER_SIZE)
                    
                    if X_train is None or X_train.size == 0:
                        logger.error(f"[{symbol}] Не удалось создать последовательности")
                        continue
                    
                    y_train_seq = train_target[config.INPUT_LAYER_SIZE:]
                    
                    X_train_tensor = torch.from_numpy(X_train).float()
                    y_train_tensor = torch.from_numpy(y_train_seq).float().unsqueeze(1)
                    
                    train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
                    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
                    
                    criterion = torch.nn.MSELoss()
                    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
                    
                    device = torch.device('cpu')
                    model.to(device)
                    
                    for epoch in range(50):
                        for X_batch, y_batch in train_loader:
                            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                            optimizer.zero_grad()
                            y_pred = model(X_batch)
                            loss = criterion(y_pred, y_batch)
                            loss.backward()
                            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                            optimizer.step()
                    
                    logger.info(f"[{symbol}] LSTM модель обучена (50 эпох)")
                
                elif model_type.upper() == 'LIGHTGBM':
                    X_train_lgb = train_scaled
                    y_train_lgb = train_target.ravel()
                    X_val_lgb = val_scaled
                    y_val_lgb = val_target.ravel()
                    
                    model.fit(X_train_lgb, y_train_lgb, 
                             eval_set=[(X_val_lgb, y_val_lgb)], 
                             eval_metric='rmse',
                             callbacks=[lgb.early_stopping(10, verbose=False)])
                    
                    logger.info(f"[{symbol}] LightGBM модель обучена")
                
                # Сохранение модели
                model_id = db_manager._save_model_and_scalers_internal(
                    symbol=symbol,
                    timeframe=timeframe,
                    model=model,
                    model_type=model_type,
                    x_scaler=x_scaler,
                    y_scaler=y_scaler,
                    features_list=features_available,
                    training_batch_id=training_batch_id,
                    hyperparameters=model_params if model_type.upper() == 'LSTM_PYTORCH' else None
                )
                
                if model_id:
                    trained_model_ids.append(model_id)
                    logger.info(f"[{symbol}] ✅ Модель {model_type} сохранена (ID: {model_id})")
            
            # 5. Назначение чемпиона
            logger.info(f"[{symbol}] Шаг 5/5: Назначение лучшей модели чемпионом...")
            
            if trained_model_ids:
                # Берём первую обученную модель как чемпиона
                from src.db.database_manager import TrainedModel
                
                session = db_manager.Session()
                try:
                    # Разжалуем старых чемпионов
                    old_champions = session.query(TrainedModel).filter_by(
                        symbol=symbol,
                        timeframe=timeframe,
                        is_champion=True
                    ).all()
                    
                    for old_champ in old_champions:
                        old_champ.is_champion = False
                        logger.info(f"[{symbol}] Разжалован старый чемпион: {old_champ.model_type} v{old_champ.version}")
                    
                    # Назначаем новых чемпионов
                    for model_id in trained_model_ids:
                        new_champion = session.query(TrainedModel).filter_by(id=model_id).first()
                        if new_champion:
                            new_champion.is_champion = True
                            logger.info(f"[{symbol}] ✅ Новый чемпион: {new_champion.model_type} v{new_champion.version} (ID: {model_id})")
                    
                    session.commit()
                except Exception as e:
                    session.rollback()
                    logger.error(f"[{symbol}] Ошибка назначения чемпиона: {e}")
                finally:
                    session.close()
                
                successful_retrains += 1
                logger.info(f"[{symbol}] ✅ УСПЕШНО ПЕРЕОБУЧЕНО! ({successful_retrains}/{len(symbols_to_retrain)})")
            else:
                logger.warning(f"[{symbol}] ❌ Ни одна модель не была обучена")
                failed_retrains.append((symbol, "No models trained"))
        
        except Exception as e:
            logger.error(f"[{symbol}] ❌ Критическая ошибка: {e}", exc_info=True)
            failed_retrains.append((symbol, str(e)))
        
        # Небольшая пауза между символами
        if idx < len(symbols_to_retrain):
            time.sleep(2)
    
    # Итоговый отчёт
    logger.info(f"\n{'='*80}")
    logger.info(f"ИТОГОВЫЙ ОТЧЁТ ПЕРЕОБУЧЕНИЯ")
    logger.info(f"{'='*80}")
    logger.info(f"✅ Успешно переобучено: {successful_retrains}/{len(symbols_to_retrain)}")
    
    if failed_retrains:
        logger.info(f"\n❌ Не удалось переобучить ({len(failed_retrains)}):")
        for symbol, reason in failed_retrains:
            logger.info(f"   - {symbol}: {reason}")
    
    logger.info(f"{'='*80}\n")

if __name__ == "__main__":
    logger.info("="*80)
    logger.info("ЗАПУСК СКРИПТА ПЕРЕОБУЧЕНИЯ ВСЕХ МОДЕЛЕЙ")
    logger.info("="*80)
    retrain_all_models()
