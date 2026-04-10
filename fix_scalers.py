#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_scalers.py - Переобучение моделей с 20 признаками

Проблема:
- Старые скалеры: 14 признаков, без feature_names_in_
- Текущий код: 20 признаков из FEATURES_TO_USE
- Ошибка: mismatch scaler(14) vs actual(20)

Решение:
- Загружает реальные данные из MT5
- Генерирует все 20 признаков через FeatureEngineer
- Обучает LightGBM модели
- Сохраняет с feature_names_in_

Запуск:
    python fix_scalers.py EURUSD GBPUSD AUDJPY
    python fix_scalers.py --all  # все символы из конфига
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Добавляем проект в path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("fix_scalers.log", encoding="utf-8")],
)
logger = logging.getLogger(__name__)


def load_config():
    """Загружает конфигурацию."""
    from src.core.config_loader import load_config as _load_config

    return _load_config()


def initialize_mt5():
    """Инициализирует MT5."""
    import MetaTrader5 as mt5

    config = load_config()

    if not mt5.initialize(
        path=config.MT5_PATH,
        login=int(config.MT5_LOGIN) if config.MT5_LOGIN else None,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
    ):
        logger.error(f"MT5 initialization failed: {mt5.last_error()}")
        return False

    logger.info(f"✓ MT5 connected: Account #{mt5.account_info().login}")
    return True


def download_data(symbol: str, n_bars: int = 3000) -> pd.DataFrame:
    """Загружает реальные данные из MT5."""
    import MetaTrader5 as mt5

    logger.info(f"📥 Загрузка {n_bars} баров для {symbol}...")

    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, n_bars)
    if rates is None or len(rates) == 0:
        logger.error(f"✗ Не удалось загрузить данные для {symbol}")
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "tick_volume"}, inplace=True)

    logger.info(f"✓ Загружено {len(df)} баров: {df.index[0]} → {df.index[-1]}")
    return df


def generate_features(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Генерирует 20 признаков через FeatureEngineer."""
    from src.ml.feature_engineer import FeatureEngineer

    config = load_config()
    fe = FeatureEngineer(config)

    logger.info("🔧 Генерация признаков...")
    df_featured = fe.generate_features(df, symbol=symbol)

    # Фильтруем признаки из конфига
    features_to_use = config.FEATURES_TO_USE
    available = [f for f in features_to_use if f in df_featured.columns]

    missing = set(features_to_use) - set(available)
    if missing:
        logger.warning(f"⚠ Отсутствуют признаки: {missing}")
        for f in missing:
            df_featured[f] = 0.0

    df_featured = df_featured[features_to_use].dropna()

    logger.info(f"✓ Сгенерировано {len(features_to_use)} признаков")
    logger.info(f"   Датасет: {len(df_featured)} строк после очистки")

    return df_featured


def train_and_save_model(symbol: str, X: pd.DataFrame, y: pd.Series, model_dir: Path):
    """Обучает LightGBM и сохраняет артефакты."""
    try:
        import json

        import joblib
        import lightgbm as lgb
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler

        logger.info(f"🤖 Обучение LightGBM для {symbol}...")

        # Очистка данных
        X = X.replace([np.inf, -np.inf], np.nan)
        for col in X.columns:
            if X[col].isna().any():
                X[col] = X[col].fillna(X[col].median())

        y = y.fillna(0)

        if len(X) < 100:
            logger.error(f"✗ Недостаточно данных: {len(X)}")
            return False

        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)

        # Скалеры
        x_scaler = StandardScaler()
        y_scaler = StandardScaler()

        X_train_scaled = x_scaler.fit_transform(X_train)
        X_test_scaled = x_scaler.transform(X_test)
        y_train_scaled = y_scaler.fit_transform(y_train.values.reshape(-1, 1)).ravel()

        # КРИТИЧЕСКИ ВАЖНО: сохраняем имена признаков
        x_scaler.feature_names_in_ = np.array(X.columns.tolist())
        x_scaler.n_features_in_ = len(X.columns)

        # Обучение LightGBM
        params = {
            "objective": "regression",
            "metric": "rmse",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.9,
            "verbose": -1,
            "n_jobs": -1,
        }

        train_data = lgb.Dataset(X_train_scaled, label=y_train_scaled)
        model = lgb.train(params, train_data, num_boost_round=200)

        # Оценка
        y_pred = y_scaler.inverse_transform(model.predict(X_test_scaled).reshape(-1, 1)).ravel()

        rmse = np.sqrt(np.mean((y_test - y_pred) ** 2))
        accuracy = np.mean((y_test > 0) == (y_pred > 0))

        logger.info(f"✓ Модель обучена")
        logger.info(f"   RMSE: {rmse:.6f}")
        logger.info(f"   Accuracy: {accuracy:.2%}")
        logger.info(f"   Признаков: {x_scaler.n_features_in_}")

        # Сохранение
        model_path = model_dir / f"{symbol}_model.joblib"
        scaler_path = model_dir / f"{symbol}_scaler.joblib"
        metadata_path = model_dir / f"{symbol}_metadata.json"

        joblib.dump(model, model_path)
        joblib.dump(x_scaler, scaler_path)

        metadata = {
            "symbol": symbol,
            "n_features": int(x_scaler.n_features_in_),
            "features": list(x_scaler.feature_names_in_),
            "trained_at": datetime.now().isoformat(),
            "model_type": "lightgbm",
            "rmse": float(rmse),
            "accuracy": float(accuracy),
        }

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info(f"✓ Сохранено:")
        logger.info(f"   Модель: {model_path.name}")
        logger.info(f"   Скалер: {scaler_path.name}")
        logger.info(f"   Metadata: {metadata_path.name}")

        return True

    except Exception as e:
        logger.error(f"✗ Ошибка обучения: {e}", exc_info=True)
        return False


def verify_model(symbol: str, model_dir: Path, expected_features: int) -> bool:
    """Проверяет сохраненную модель."""
    try:
        import joblib

        scaler_path = model_dir / f"{symbol}_scaler.joblib"
        if not scaler_path.exists():
            logger.error(f"✗ Скалер не найден: {scaler_path}")
            return False

        scaler = joblib.load(scaler_path)
        n_features = getattr(scaler, "n_features_in_", None)
        has_names = hasattr(scaler, "feature_names_in_")

        logger.info(f"🔍 Верификация {symbol}:")
        logger.info(f"   n_features_in_: {n_features}")
        logger.info(f"   feature_names_in_: {'✓' if has_names else '✗'}")

        if n_features == expected_features:
            logger.info(f"✓ Признаки совпадают: {n_features}")
            return True
        else:
            logger.error(f"✗ MISMATCH: ожидалось {expected_features}, получено {n_features}")
            return False

    except Exception as e:
        logger.error(f"✗ Ошибка верификации: {e}")
        return False


def main():
    """Главная функция."""
    print("=" * 70)
    print(" FIX_SCALERS.PY - Переобучение моделей с 20 признаками")
    print("=" * 70)

    # Определяем символы
    config = load_config()
    symbols = config.SYMBOLS_WHITELIST

    if "--all" not in sys.argv and len(sys.argv) > 1:
        symbols = [s for s in sys.argv[1:] if not s.startswith("--")]

    model_dir = Path(config.MODEL_DIR) if config.MODEL_DIR else Path(config.DATABASE_FOLDER) / "ai_models"
    model_dir.mkdir(parents=True, exist_ok=True)

    expected_features = len(config.FEATURES_TO_USE)

    logger.info(f"📁 Директория моделей: {model_dir}")
    logger.info(f"📊 Признаков в конфиге: {expected_features}")
    logger.info(f"🎯 Символы для переобучения: {len(symbols)}")

    # Инициализация MT5
    if not initialize_mt5():
        return 1

    success_count = 0

    try:
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"[{i}/{len(symbols)}] ОБРАБОТКА: {symbol}")
            logger.info(f"{'='*60}")

            # Загрузка данных
            df = download_data(symbol, n_bars=3000)
            if df is None:
                continue

            # Генерация признаков
            df_featured = generate_features(df, symbol)
            if df_featured.empty:
                logger.error(f"✗ Пустой датасет после генерации признаков")
                continue

            # Target: изменение цены на 1 бар вперед
            y = df_featured["close"].shift(-1) - df_featured["close"]
            X = df_featured

            mask = ~y.isna()
            X = X[mask]
            y = y[mask]

            if len(X) < 100:
                logger.error(f"✗ Недостаточно данных: {len(X)}")
                continue

            logger.info(f"   X: {X.shape}, y: {len(y)}")

            # Обучение и сохранение
            if train_and_save_model(symbol, X, y, model_dir):
                # Верификация
                if verify_model(symbol, model_dir, expected_features):
                    success_count += 1
                    logger.info(f"✅ {symbol}: УСПЕШНО")
                else:
                    logger.error(f"❌ {symbol}: ОШИБКА ВЕРИФИКАЦИИ")
            else:
                logger.error(f"❌ {symbol}: ОШИБКА ОБУЧЕНИЯ")

    finally:
        import MetaTrader5 as mt5

        mt5.shutdown()

    # Итог
    print("\n" + "=" * 70)
    print(" ИТОГОВЫЙ ОТЧЁТ")
    print("=" * 70)
    logger.info(f"Всего символов: {len(symbols)}")
    logger.info(f"✅ Успешно: {success_count}")
    logger.info(f"❌ Не удалось: {len(symbols) - success_count}")

    if success_count == len(symbols):
        logger.info("\n✅ Все модели успешно переобучены!")
        logger.info("\nСледующие шаги:")
        logger.info("1. Перезапустите Genesis Trading System")
        logger.info("2. Проверьте логи - ошибок mismatch больше не будет")
        logger.info("3. Протестируйте торговлю")
        return 0
    else:
        logger.warning(f"\n⚠ Переобучено {success_count}/{len(symbols)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
