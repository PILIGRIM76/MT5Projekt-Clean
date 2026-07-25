"""
Обучение ML моделей для Genesis Trading System.
Запуск: python train_models.py
"""
import sys
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, r"F:\MT5Projekt-Clean")
sys.path.insert(0, r"F:\MT5Projekt-Clean\src")

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 1. Подключение к MT5
logger.info("Подключение к MT5...")
result = mt5.initialize(
    path=r"C:\Program Files\Alpari MT5\terminal64.exe",
    login=53057252,
    password="Zk*xS7Cc",
    server="Alpari-MT5-Demo",
    timeout=30000
)
if not result:
    logger.error(f"Ошибка MT5: {mt5.last_error()}")
    sys.exit(1)

acct = mt5.account_info()
logger.info(f"Подключено: #{acct.login} @ {acct.server}")

# 2. Получение данных
symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BITCOIN", "ETHEREUM"]
model_dir = Path(r"F:\MT5Projekt-Clean\ai_models")
model_dir.mkdir(exist_ok=True)

results = {}

for symbol in symbols:
    logger.info(f"\n{'='*60}")
    logger.info(f"Обучение модели для {symbol}")
    logger.info(f"{'='*60}")

    # Получаем исторические данные (1000 баров H1)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 1000)
    if rates is None or len(rates) < 200:
        logger.warning(f"{symbol}: недостаточно данных ({len(rates) if rates is not None else 0} баров)")
        continue

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    # 3. Генерация признаков
    logger.info(f"Генерация признаков для {len(df)} баров...")

    # Базовые признаки
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))

    # скользящие средние
    df['ma_5'] = df['close'].rolling(5).mean()
    df['ma_20'] = df['close'].rolling(20).mean()
    df['ma_50'] = df['close'].rolling(50).mean()

    # Волатильность
    df['volatility_20'] = df['returns'].rolling(20).std()
    df['volatility_50'] = df['returns'].rolling(50).std()

    # ATR
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            np.abs(df['high'] - df['close'].shift(1)),
            np.abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr_14'] = df['tr'].rolling(14).mean()

    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # Bollinger Bands
    df['bb_middle'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']

    # Объём
    df['volume_ma'] = df['tick_volume'].rolling(20).mean()
    df['volume_ratio'] = df['tick_volume'] / df['volume_ma']

    # Целевая переменная: через 5 баров цена вырастет?
    df['target'] = (df['close'].shift(-5) > df['close']).astype(int)

    # Удаляем NaN
    df = df.dropna()

    if len(df) < 100:
        logger.warning(f"{symbol}: недостаточно данных после генерации признаков ({len(df)} баров)")
        continue

    # 4. Обучение модели
    feature_cols = [
        'returns', 'log_returns', 'ma_5', 'ma_20', 'ma_50',
        'volatility_20', 'volatility_50', 'atr_14', 'rsi_14',
        'macd', 'macd_signal', 'macd_hist', 'bb_width', 'volume_ratio'
    ]

    X = df[feature_cols].values
    y = df['target'].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    logger.info(f"Обучающая выборка: {len(X_train)}, тестовая: {len(X_test)}")

    model = lgb.LGBMClassifier(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        verbose=-1,
        random_state=42
    )

    model.fit(X_train, y_train)

    # 5. Оценка
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    y_proba = model.predict_proba(X_test)
    avg_confidence = np.mean(np.max(y_proba, axis=1))

    logger.info(f"Точность: {accuracy:.2%}")
    logger.info(f"Средняя уверенность: {avg_confidence:.2%}")

    # 6. Сохранение модели
    model_path = model_dir / f"{symbol}_model.joblib"
    import joblib
    joblib.dump({
        'model': model,
        'features': feature_cols,
        'symbol': symbol,
        'accuracy': accuracy,
        'trained_at': datetime.now().isoformat(),
        'train_size': len(X_train),
        'test_size': len(X_test),
    }, model_path)
    logger.info(f"Модель сохранена: {model_path}")

    results[symbol] = {
        'accuracy': accuracy,
        'confidence': avg_confidence,
        'train_size': len(X_train),
        'test_size': len(X_test),
        'model_path': str(model_path),
    }

# 7. Итоги
logger.info(f"\n{'='*60}")
logger.info("ИТОГИ ОБУЧЕНИЯ")
logger.info(f"{'='*60}")
for symbol, r in results.items():
    logger.info(f"  {symbol}: точность={r['accuracy']:.2%}, уверенность={r['confidence']:.2%}, модель={r['model_path']}")

mt5.shutdown()
logger.info("Обучение завершено!")
