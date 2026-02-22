"""
Скрипт для немедленного обучения моделей BITCOIN
"""
import sys
import logging
import queue
from pathlib import Path
from datetime import datetime, timedelta
import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).parent))

from src.core.config_loader import load_config
from src.data.data_provider import DataProvider
from src.db.database_manager import DatabaseManager
from src.ml.feature_engineer import FeatureEngineer
from src.ml.model_factory import ModelFactory
from sklearn.model_selection import train_test_split
import uuid

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def train_bitcoin():
    """Обучает модели для BITCOIN"""
    symbol = "BITCOIN"
    logger.info(f"="*60)
    logger.info(f"НАЧАЛО ОБУЧЕНИЯ МОДЕЛЕЙ ДЛЯ {symbol}")
    logger.info(f"="*60)
    
    # Загрузка конфигурации
    logger.info("Загрузка конфигурации...")
    config = load_config()
    
    # Инициализация MT5
    logger.info("Подключение к MT5...")
    if not mt5.initialize(
        path=config.MT5_PATH,
        login=int(config.MT5_LOGIN),
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER
    ):
        logger.error(f"Ошибка подключения к MT5: {mt5.last_error()}")
        return False
    
    # Инициализация компонентов
    write_queue = queue.Queue()
    db_manager = DatabaseManager(config, write_queue)
    data_provider = DataProvider(config)
    feature_engineer = FeatureEngineer(config, kg_querier=None)
    model_factory = ModelFactory(config)
    
    try:
        # 1. Загрузка данных
        logger.info(f"Загрузка исторических данных для {symbol}...")
        timeframe = mt5.TIMEFRAME_H1
        end_date = datetime.now()
        start_date = end_date - timedelta(days=config.TRAINING_DATA_POINTS / 12)
        
        df_full = data_provider.get_historical_data(symbol, timeframe, start_date, end_date)
        
        if df_full is None or len(df_full) < 1000:
            logger.error(f"Недостаточно данных для {symbol}: {len(df_full) if df_full else 0} баров")
            return False
        
        logger.info(f"Загружено {len(df_full)} баров")
        
        # 2. Генерация признаков
        logger.info("Генерация признаков...")
        df_featured = feature_engineer.generate_features(df_full, symbol=symbol)
        
        # Используем только базовые признаки (без KG)
        unique_features = list(dict.fromkeys(config.FEATURES_TO_USE))
        actual_features = [f for f in unique_features if f in df_featured.columns]
        
        # Ограничиваем до 20 признаков
        if len(actual_features) > 20:
            actual_features = actual_features[:20]
        
        logger.info(f"Используется {len(actual_features)} признаков")
        
        # 3. Разделение данных
        logger.info("Разделение данных на train/val/test...")
        train_val_df, holdout_df = train_test_split(df_featured, test_size=0.15, shuffle=False)
        train_df, val_df = train_test_split(train_val_df, test_size=0.176, shuffle=False)
        
        logger.info(f"Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(holdout_df)}")
        
        # 4. Обучение моделей
        training_batch_id = f"batch-{uuid.uuid4()}"
        model_types = ['LightGBM', 'LSTM_PyTorch']
        
        trained_models = []
        
        for model_type in model_types:
            logger.info(f"\n{'='*60}")
            logger.info(f"Обучение модели: {model_type}")
            logger.info(f"{'='*60}")
            
            try:
                # Подготовка данных
                from sklearn.preprocessing import StandardScaler
                import numpy as np
                import pandas as pd
                import torch
                
                target_col = 'close'
                
                # Скалирование
                x_scaler = StandardScaler()
                y_scaler = StandardScaler()
                
                train_features = train_df[actual_features].values
                val_features = val_df[actual_features].values
                
                train_features = np.nan_to_num(train_features, nan=0.0)
                val_features = np.nan_to_num(val_features, nan=0.0)
                
                train_scaled = x_scaler.fit_transform(train_features)
                val_scaled = x_scaler.transform(val_features)
                
                train_df_scaled = pd.DataFrame(train_scaled, index=train_df.index, columns=actual_features)
                val_df_scaled = pd.DataFrame(val_scaled, index=val_df.index, columns=actual_features)
                
                train_df_scaled[target_col] = y_scaler.fit_transform(train_df[[target_col]])
                val_df_scaled[target_col] = y_scaler.transform(val_df[[target_col]])
                
                # Создание модели
                input_dim = len(actual_features)
                
                if model_type == 'LSTM_PyTorch':
                    model_params = {'input_dim': input_dim, 'hidden_dim': 32, 'num_layers': 1, 'output_dim': 1}
                else:
                    model_params = {'input_dim': input_dim}
                
                model = model_factory.create_model(model_type, model_params)
                
                if not model:
                    logger.error(f"Не удалось создать модель {model_type}")
                    continue
                
                # Обучение
                if model_type == 'LSTM_PyTorch':
                    from torch.utils.data import TensorDataset, DataLoader
                    
                    # Создание последовательностей
                    def create_sequences(data, seq_length):
                        X, y = [], []
                        for i in range(len(data) - seq_length):
                            X.append(data[i:i + seq_length])
                            y.append(data[i + seq_length])
                        return np.array(X), np.array(y)
                    
                    X_train, _ = create_sequences(train_df_scaled[actual_features].values, config.INPUT_LAYER_SIZE)
                    y_train = train_df_scaled[target_col].values[config.INPUT_LAYER_SIZE:]
                    
                    X_train_tensor = torch.from_numpy(X_train).float()
                    y_train_tensor = torch.from_numpy(y_train).float().unsqueeze(1)
                    
                    train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
                    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
                    
                    criterion = torch.nn.MSELoss()
                    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
                    
                    logger.info("Обучение LSTM (20 эпох)...")
                    for epoch in range(20):
                        for X_batch, y_batch in train_loader:
                            optimizer.zero_grad()
                            y_pred = model(X_batch)
                            loss = criterion(y_pred, y_batch)
                            loss.backward()
                            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                            optimizer.step()
                        
                        if epoch % 5 == 0:
                            logger.info(f"  Эпоха {epoch}/20, Loss: {loss.item():.4f}")
                
                else:  # LightGBM
                    import lightgbm as lgb
                    
                    X_train = train_df_scaled[actual_features]
                    y_train = train_df_scaled[target_col]
                    X_val = val_df_scaled[actual_features]
                    y_val = val_df_scaled[target_col]
                    
                    logger.info("Обучение LightGBM...")
                    model.fit(
                        X_train, y_train,
                        eval_set=[(X_val, y_val)],
                        eval_metric='rmse',
                        callbacks=[lgb.early_stopping(10, verbose=False)]
                    )
                
                # Сохранение модели
                logger.info(f"Сохранение модели {model_type}...")
                model_id = db_manager._save_model_and_scalers_internal(
                    symbol=symbol,
                    timeframe=timeframe,
                    model=model,
                    model_type=model_type,
                    x_scaler=x_scaler,
                    y_scaler=y_scaler,
                    features_list=actual_features,
                    training_batch_id=training_batch_id,
                    hyperparameters=model_params if model_type == 'LSTM_PyTorch' else None
                )
                
                if model_id:
                    logger.info(f"✓ Модель {model_type} успешно сохранена (ID: {model_id})")
                    trained_models.append(model_id)
                else:
                    logger.error(f"✗ Не удалось сохранить модель {model_type}")
                
            except Exception as e:
                logger.error(f"✗ Ошибка при обучении {model_type}: {e}", exc_info=True)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"ОБУЧЕНИЕ ЗАВЕРШЕНО")
        logger.info(f"Обучено моделей: {len(trained_models)}")
        logger.info(f"{'='*60}")
        
        return len(trained_models) > 0
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        return False
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    success = train_bitcoin()
    sys.exit(0 if success else 1)
