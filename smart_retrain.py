"""
Умная система переобучения моделей с автоматическим отбором символов.
Особенности:
1. Автоматический отбор ликвидных символов из всех доступных в MT5 (500+)
2. Параллельное обучение моделей для ускорения процесса
3. Приоритизация символов по объёму торгов и волатильности
4. Асинхронная обработка без зависания системы
"""
import logging
import time
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import MetaTrader5 as mt5
import pandas as pd
import numpy as np

from src.core.config_loader import load_config
from src.data.data_provider import DataProvider
from src.ml.feature_engineer import FeatureEngineer
from src.db.database_manager import DatabaseManager
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.ml.model_factory import ModelFactory
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SmartSymbolSelector:
    """Умный отбор символов на основе ликвидности и торговых характеристик."""
    
    def __init__(self, config, mt5_lock):
        self.config = config
        self.mt5_lock = mt5_lock
        
    def get_all_available_symbols(self) -> List[str]:
        """Получает ВСЕ доступные символы из MT5."""
        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error("Не удалось инициализировать MT5")
                return []
            
            try:
                all_symbols = mt5.symbols_get()
                if not all_symbols:
                    return []
                
                # Фильтруем только торгуемые символы
                tradable = [
                    s.name for s in all_symbols 
                    if s.visible and s.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL
                ]
                
                logger.info(f"Найдено {len(tradable)} торгуемых символов из {len(all_symbols)} всего")
                return tradable
            finally:
                mt5.shutdown()
    
    def analyze_symbol_liquidity(self, symbol: str, timeframe=mt5.TIMEFRAME_H1, days=30) -> Optional[Dict]:
        """
        Анализирует ликвидность символа по объёму торгов и волатильности.
        Возвращает метрики для ранжирования.
        """
        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                return None
            
            try:
                # Получаем последние N дней данных
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
                
                rates = mt5.copy_rates_range(symbol, timeframe, start_date, end_date)
                
                if rates is None or len(rates) < 100:
                    return None
                
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                
                # Рассчитываем метрики ликвидности
                avg_volume = df['tick_volume'].mean()
                avg_spread = df['spread'].mean() if 'spread' in df.columns else 0
                
                # Волатильность (ATR)
                high_low = df['high'] - df['low']
                atr = high_low.mean()
                atr_percent = (atr / df['close'].mean()) * 100 if df['close'].mean() > 0 else 0
                
                # Количество баров с нулевым объёмом (признак неликвидности)
                zero_volume_ratio = (df['tick_volume'] == 0).sum() / len(df)
                
                # Получаем информацию о символе
                symbol_info = mt5.symbol_info(symbol)
                if not symbol_info:
                    return None
                
                return {
                    'symbol': symbol,
                    'avg_volume': avg_volume,
                    'avg_spread': avg_spread,
                    'atr_percent': atr_percent,
                    'zero_volume_ratio': zero_volume_ratio,
                    'bars_count': len(df),
                    'category': self._categorize_symbol(symbol),
                    'trade_contract_size': symbol_info.trade_contract_size,
                    'volume_min': symbol_info.volume_min,
                    'currency_base': symbol_info.currency_base,
                    'currency_profit': symbol_info.currency_profit,
                }
                
            except Exception as e:
                logger.debug(f"Ошибка анализа {symbol}: {e}")
                return None
            finally:
                mt5.shutdown()
    
    def _categorize_symbol(self, symbol: str) -> str:
        """Определяет категорию символа (Forex, Crypto, Metal, Stock и т.д.)."""
        symbol_upper = symbol.upper()
        
        # Forex валютные пары
        forex_currencies = ['EUR', 'USD', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD']
        if any(symbol_upper.startswith(c) for c in forex_currencies):
            return 'FOREX'
        
        # Металлы
        if any(metal in symbol_upper for metal in ['XAU', 'XAG', 'GOLD', 'SILVER']):
            return 'METAL'
        
        # Криптовалюты
        if any(crypto in symbol_upper for crypto in ['BTC', 'ETH', 'BITCOIN', 'ETHEREUM']):
            return 'CRYPTO'
        
        # Индексы
        if any(idx in symbol_upper for idx in ['SPX', 'NDX', 'US30', 'US100', 'US500', 'DAX', 'FTSE']):
            return 'INDEX'
        
        # Нефть и энергоносители
        if any(oil in symbol_upper for oil in ['WTI', 'BRENT', 'CL', 'NG', 'OIL']):
            return 'ENERGY'
        
        return 'OTHER'
    
    def select_best_symbols(self, max_symbols: int = 30, min_bars: int = 500) -> List[str]:
        """
        Выбирает лучшие символы для обучения на основе ликвидности.
        
        Args:
            max_symbols: Максимальное количество символов для отбора
            min_bars: Минимальное количество баров для обучения
        
        Returns:
            Список отобранных символов, отсортированных по приоритету
        """
        logger.info(f"Начинаем умный отбор символов (макс: {max_symbols})...")
        
        # 1. Получаем все доступные символы
        all_symbols = self.get_all_available_symbols()
        if not all_symbols:
            logger.warning("Не найдено доступных символов")
            return []
        
        logger.info(f"Анализируем {len(all_symbols)} символов...")
        
        # 2. Анализируем каждый символ (параллельно для скорости)
        symbol_metrics = []
        
        # Используем ThreadPoolExecutor для параллельного анализа
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_symbol = {
                executor.submit(self.analyze_symbol_liquidity, symbol): symbol 
                for symbol in all_symbols
            }
            
            completed = 0
            for future in as_completed(future_to_symbol):
                completed += 1
                if completed % 50 == 0:
                    logger.info(f"Проанализировано {completed}/{len(all_symbols)} символов...")
                
                metrics = future.result()
                if metrics and metrics['bars_count'] >= min_bars:
                    symbol_metrics.append(metrics)
        
        logger.info(f"Из {len(all_symbols)} символов подходят для обучения: {len(symbol_metrics)}")
        
        if not symbol_metrics:
            logger.warning("Не найдено подходящих символов")
            return []
        
        # 3. РассчитываемScore для ранжирования
        for metrics in symbol_metrics:
            # Формула: высокий объём + низкий spread + хорошая волатильность
            volume_score = np.log1p(metrics['avg_volume'])  # log для нормализации
            spread_score = 1 / (1 + metrics['avg_spread'])  # Чем меньше спред, тем лучше
            volatility_score = metrics['atr_percent']  # Умеренная волатильность хороша
            data_quality_score = 1 - metrics['zero_volume_ratio']  # Меньше нулевых баров
            
            # Бонусы для популярных категорий
            category_bonus = {
                'FOREX': 2.0,
                'METAL': 1.8,
                'CRYPTO': 1.5,
                'INDEX': 1.3,
                'ENERGY': 1.2,
                'OTHER': 1.0
            }
            
            total_score = (
                volume_score * 0.3 +
                spread_score * 0.2 +
                volatility_score * 0.2 +
                data_quality_score * 0.3
            ) * category_bonus.get(metrics['category'], 1.0)
            
            metrics['score'] = total_score
        
        # 4. Сортируем по Score
        symbol_metrics.sort(key=lambda x: x['score'], reverse=True)
        
        # 5. Отбираем топ-N символов
        selected = symbol_metrics[:max_symbols]
        
        # Логируем результаты
        logger.info(f"\n{'='*80}")
        logger.info(f"ТОП-{len(selected)} ОТОБРАННЫХ СИМВОЛОВ ДЛЯ ОБУЧЕНИЯ:")
        logger.info(f"{'='*80}")
        
        for i, metrics in enumerate(selected, 1):
            logger.info(
                f"{i:2d}. {metrics['symbol']:15s} | "
                f"Категория: {metrics['category']:8s} | "
                f"Score: {metrics['score']:6.2f} | "
                f"Vol: {metrics['avg_volume']:8.0f} | "
                f"ATR%: {metrics['atr_percent']:5.2f}% | "
                f"Bars: {metrics['bars_count']}"
            )
        
        logger.info(f"{'='*80}\n")
        
        return [m['symbol'] for m in selected]


class ParallelModelTrainer:
    """Параллельный тренер моделей для ускорения процесса."""
    
    def __init__(self, config, max_workers: int = 3):
        self.config = config
        self.max_workers = max_workers
        self.write_queue = queue.Queue()
        self.mt5_lock = threading.Lock()
        
        # Инициализация компонентов
        self.db_manager = DatabaseManager(config, self.write_queue)
        self.data_provider = DataProvider(config, self.mt5_lock)
        self.kg_querier = KnowledgeGraphQuerier(self.db_manager)
        self.feature_engineer = FeatureEngineer(config, self.kg_querier)
        self.model_factory = ModelFactory(config)
    
    def train_symbol(self, symbol: str, timeframe=mt5.TIMEFRAME_H1) -> Tuple[str, bool, str]:
        """
        Обучает модели для одного символа.
        
        Returns:
            (symbol, success, message)
        """
        try:
            logger.info(f"[{symbol}] Начинаем обучение...")
            
            # 1. Загрузка данных
            with self.mt5_lock:
                if not mt5.initialize(path=self.config.MT5_PATH):
                    return (symbol, False, "MT5 init failed")
                
                try:
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=self.config.TRAINING_DATA_POINTS / 12)
                    df_full = self.data_provider.get_historical_data(symbol, timeframe, start_date, end_date)
                finally:
                    mt5.shutdown()
            
            if df_full is None or len(df_full) < 1000:
                return (symbol, False, f"Insufficient data: {len(df_full) if df_full is not None else 0} bars")
            
            # 2. Генерация признаков
            df_featured = self.feature_engineer.generate_features(df_full, symbol=symbol)
            if df_featured is None or df_featured.empty:
                return (symbol, False, "Feature generation failed")
            
            # Формируем список признаков
            unique_features = list(dict.fromkeys(self.config.FEATURES_TO_USE))
            kg_features = ['KG_CB_SENTIMENT', 'KG_INFLATION_SURPRISE']
            actual_features_to_use = [f for f in unique_features if f in df_featured.columns]
            actual_features_to_use.extend([f for f in kg_features if f in df_featured.columns])
            
            # 3. Разделение данных
            train_val_df, holdout_df = train_test_split(df_featured, test_size=0.15, shuffle=False)
            train_df, val_df = train_test_split(train_val_df, test_size=0.176, shuffle=False)
            
            # 4. Обучение моделей
            training_batch_id = f"smart_retrain_{symbol}_{int(time.time())}"
            trained_model_ids = []
            
            for candidate_config in self.config.rd_cycle_config.model_candidates:
                model_id = self._train_single_model(
                    symbol, candidate_config.type, train_df, val_df, 
                    actual_features_to_use, training_batch_id, timeframe
                )
                if model_id:
                    trained_model_ids.append(model_id)
            
            # 5. Назначение чемпионов
            if trained_model_ids:
                self._promote_champions(symbol, timeframe, trained_model_ids)
                return (symbol, True, f"Trained {len(trained_model_ids)} models")
            else:
                return (symbol, False, "No models trained")
        
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка: {e}", exc_info=True)
            return (symbol, False, str(e))
    
    def _train_single_model(self, symbol, model_type, train_df, val_df, 
                           features_list, training_batch_id, timeframe):
        """Обучает одну модель."""
        try:
            import torch
            import lightgbm as lgb
            from torch.utils.data import TensorDataset, DataLoader
            
            # Подготовка данных
            train_df_copy = train_df.loc[:, ~train_df.columns.duplicated()].copy()
            val_df_copy = val_df.loc[:, ~val_df.columns.duplicated()].copy()
            
            features_available = [f for f in features_list if f in train_df_copy.columns]
            
            x_scaler = StandardScaler()
            y_scaler = StandardScaler()
            
            train_features = np.nan_to_num(train_df_copy[features_available].values, nan=0.0)
            val_features = np.nan_to_num(val_df_copy[features_available].values, nan=0.0)
            
            train_scaled = x_scaler.fit_transform(train_features)
            val_scaled = x_scaler.transform(val_features)
            
            train_target = y_scaler.fit_transform(train_df_copy[['close']])
            val_target = y_scaler.transform(val_df_copy[['close']])
            
            # Создание модели
            input_dim = len(features_available)
            
            if model_type.upper() == 'LSTM_PYTORCH':
                model_params = {'input_dim': input_dim, 'hidden_dim': 32, 'num_layers': 1, 'output_dim': 1}
                model = self.model_factory.create_model(model_type, model_params)
                
                # Создание последовательностей
                def create_sequences(data, n_steps):
                    X = []
                    if len(data) < n_steps + 1:
                        return None, None
                    for i in range(len(data) - n_steps):
                        X.append(data[i:(i + n_steps)])
                    return np.array(X), None
                
                X_train, _ = create_sequences(train_scaled, self.config.INPUT_LAYER_SIZE)
                if X_train is None:
                    return None
                
                y_train_seq = train_target[self.config.INPUT_LAYER_SIZE:]
                
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
            
            elif model_type.upper() == 'LIGHTGBM':
                model_params = {'input_dim': input_dim}
                model = self.model_factory.create_model(model_type, model_params)
                
                model.fit(train_scaled, train_target.ravel(), 
                         eval_set=[(val_scaled, val_target.ravel())], 
                         eval_metric='rmse',
                         callbacks=[lgb.early_stopping(10, verbose=False)])
            else:
                return None
            
            # Сохранение модели
            model_id = self.db_manager._save_model_and_scalers_internal(
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
            
            return model_id
        
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка обучения {model_type}: {e}")
            return None
    
    def _promote_champions(self, symbol, timeframe, trained_model_ids):
        """Назначает обученные модели чемпионами."""
        from src.db.database_manager import TrainedModel
        
        session = self.db_manager.Session()
        try:
            # Разжалуем старых чемпионов
            old_champions = session.query(TrainedModel).filter_by(
                symbol=symbol,
                timeframe=timeframe,
                is_champion=True
            ).all()
            
            for old_champ in old_champions:
                old_champ.is_champion = False
            
            # Назначаем новых чемпионов
            for model_id in trained_model_ids:
                new_champion = session.query(TrainedModel).filter_by(id=model_id).first()
                if new_champion:
                    new_champion.is_champion = True
            
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"[{symbol}] Ошибка назначения чемпиона: {e}")
        finally:
            session.close()
    
    def train_multiple_symbols_parallel(self, symbols: List[str]) -> Dict:
        """
        Обучает модели для нескольких символов параллельно.
        
        Returns:
            Статистика обучения
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"ПАРАЛЛЕЛЬНОЕ ОБУЧЕНИЕ {len(symbols)} СИМВОЛОВ")
        logger.info(f"Количество параллельных потоков: {self.max_workers}")
        logger.info(f"{'='*80}\n")
        
        results = {
            'successful': [],
            'failed': [],
            'total': len(symbols),
            'start_time': time.time()
        }
        
        # Параллельное обучение
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_symbol = {
                executor.submit(self.train_symbol, symbol): symbol 
                for symbol in symbols
            }
            
            completed = 0
            for future in as_completed(future_to_symbol):
                completed += 1
                symbol, success, message = future.result()
                
                if success:
                    results['successful'].append(symbol)
                    logger.info(f"✅ [{completed}/{len(symbols)}] {symbol}: {message}")
                else:
                    results['failed'].append((symbol, message))
                    logger.warning(f"❌ [{completed}/{len(symbols)}] {symbol}: {message}")
        
        results['end_time'] = time.time()
        results['duration'] = results['end_time'] - results['start_time']
        
        return results


def smart_retrain_models(max_symbols: int = 30, max_workers: int = 3):
    """
    Умное переобучение моделей с автоматическим отбором символов.
    
    Args:
        max_symbols: Максимальное количество символов для обучения
        max_workers: Количество параллельных потоков обучения
    """
    config = load_config()
    mt5_lock = threading.Lock()
    
    # 1. Отбор лучших символов
    selector = SmartSymbolSelector(config, mt5_lock)
    selected_symbols = selector.select_best_symbols(max_symbols=max_symbols)
    
    if not selected_symbols:
        logger.error("Не удалось отобрать символы для обучения")
        return
    
    # 2. Параллельное обучение
    trainer = ParallelModelTrainer(config, max_workers=max_workers)
    results = trainer.train_multiple_symbols_parallel(selected_symbols)
    
    # 3. Итоговый отчёт
    logger.info(f"\n{'='*80}")
    logger.info(f"ИТОГОВЫЙ ОТЧЁТ УМНОГО ПЕРЕОБУЧЕНИЯ")
    logger.info(f"{'='*80}")
    logger.info(f"Всего символов обработано: {results['total']}")
    logger.info(f"✅ Успешно обучено: {len(results['successful'])}")
    logger.info(f"❌ Не удалось обучить: {len(results['failed'])}")
    logger.info(f"⏱️  Время выполнения: {results['duration']:.1f} сек ({results['duration']/60:.1f} мин)")
    
    if results['successful']:
        logger.info(f"\nУспешно обученные символы:")
        for symbol in results['successful']:
            logger.info(f"  ✅ {symbol}")
    
    if results['failed']:
        logger.info(f"\nНе удалось обучить:")
        for symbol, reason in results['failed']:
            logger.info(f"  ❌ {symbol}: {reason}")
    
    logger.info(f"{'='*80}\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Умное переобучение моделей с автоматическим отбором символов')
    parser.add_argument('--max-symbols', type=int, default=30, 
                       help='Максимальное количество символов для обучения (по умолчанию: 30)')
    parser.add_argument('--max-workers', type=int, default=3, 
                       help='Количество параллельных потоков (по умолчанию: 3)')
    
    args = parser.parse_args()
    
    logger.info("="*80)
    logger.info("ЗАПУСК УМНОЙ СИСТЕМЫ ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
    logger.info("="*80)
    
    smart_retrain_models(max_symbols=args.max_symbols, max_workers=args.max_workers)
