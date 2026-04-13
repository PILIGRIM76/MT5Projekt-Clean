# src/ml/auto_trainer.py
"""
Auto Trainer — Автоматическое переобучение моделей на новых данных.

Функции:
- Отслеживание новых данных
- Автоматическое переобучение по расписанию
- Инкрементальное обучение
- Валидация качества моделей
- Бесплатное обучение (CPU оптимизированное)
"""

import json
import logging
import multiprocessing
import pickle
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.core.config_models import Settings
from src.db.database_manager import DatabaseManager

# LightGBM импортируем опционально
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

logger = logging.getLogger(__name__)


class AutoTrainer:
    """
    Автоматическое переобучение AI моделей.

    Атрибуты:
        config: Конфигурация системы
        db_manager: Менеджер базы данных
        models_path: Путь к сохранённым моделям
    """

    def __init__(self, config: Settings, db_manager: DatabaseManager):
        """
        Инициализация авто-тренера.

        Args:
            config: Конфигурация системы
            db_manager: Менеджер базы данных
        """
        self.config = config
        self.db_manager = db_manager

        # Пути — используем MODEL_DIR из конфига или fallback на DATABASE_FOLDER/ai_models
        if hasattr(config, "MODEL_DIR") and config.MODEL_DIR:
            self.models_path = Path(config.MODEL_DIR)
        else:
            self.models_path = Path(config.DATABASE_FOLDER) / "ai_models"
        self.models_path.mkdir(parents=True, exist_ok=True)

        # Настройки обучения - ЧАСТОЕ ПЕРЕОБУЧЕНИЕ!
        # Приоритет: config.auto_retraining.interval_hours > AUTO_RETRAIN_INTERVAL_HOURS > 1 час
        if hasattr(config, "auto_retraining") and config.auto_retraining:
            self.retrain_interval_hours = getattr(config.auto_retraining, "interval_hours", 1)
            logger.info(f"📅 Интервал переобучения из auto_retraining: {self.retrain_interval_hours} ч")
        else:
            self.retrain_interval_hours = getattr(config, "AUTO_RETRAIN_INTERVAL_HOURS", 1)
            logger.info(f"📅 Интервал переобучения из AUTO_RETRAIN_INTERVAL_HOURS: {self.retrain_interval_hours} ч")

        # Минимальное количество сэмплов для обучения
        self.min_samples_for_retrain = getattr(config, "MIN_SAMPLES_FOR_RETRAIN", 500)  # Уменьшено с 1000 до 500
        self.validation_split = getattr(config, "VALIDATION_SPLIT", 0.2)

        # ДОПОЛНИТЕЛЬНЫЕ ТРИГГЕРЫ ПЕРЕОБУЧЕНИЯ:
        # 1. По количеству новых баров
        self.min_new_bars_for_retrain = getattr(config, "MIN_NEW_BARS_FOR_RETRAIN", 50)  # Каждые 50 новых баров H1
        # 2. По изменению волатильности
        self.volatility_change_threshold = getattr(config, "VOLATILITY_CHANGE_THRESHOLD", 0.3)  # 30% изменение
        # 3. По ухудшению точности модели
        self.accuracy_drop_threshold = getattr(config, "ACCURACY_DROP_THRESHOLD", 0.15)  # Падение на 15%

        # Кэш моделей
        self.models: Dict[str, Any] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.model_metadata: Dict[str, Dict[str, Any]] = {}

        # Кэш для отслеживания изменений рынка
        self._last_volatility: Dict[str, float] = {}
        self._last_bars_count: Dict[str, int] = {}
        self._last_accuracy: Dict[str, float] = {}

        # Порог запуска переобучения (процент символов)
        # Приоритет: config.auto_retraining.threshold_percent > AUTO_RETRAIN_THRESHOLD_PERCENT > 0.30
        if hasattr(config, "auto_retraining") and config.auto_retraining:
            self.retrain_threshold_percent = getattr(config.auto_retraining, "threshold_percent", 0.30)
            logger.info(f"  🎯 Порог запуска переобучения из auto_retraining: {self.retrain_threshold_percent:.0%}")
        else:
            self.retrain_threshold_percent = getattr(config, "AUTO_RETRAIN_THRESHOLD_PERCENT", 0.30)
            logger.info(
                f"  🎯 Порог запуска переобучения из AUTO_RETRAIN_THRESHOLD_PERCENT: {self.retrain_threshold_percent:.0%}"
            )

        # Статистика
        self.stats = {"last_training_time": None, "models_trained": 0, "training_errors": 0}

        # Время последнего переобучения (для адаптивного триггера)
        self._last_retrain_time: Dict[str, datetime] = {}
        self._peak_sharpe: Dict[str, float] = {}  # Пиковый Sharpe для отслеживания деградации

        # Блокировка
        self._lock = threading.Lock()

        # Callback для отправки прогресса обучения в GUI
        self._training_progress_callback = None  # Функция(history_object)

        logger.info("Auto Trainer инициализирован")
        logger.info(f"  ⚡ Интервал переобучения: {self.retrain_interval_hours} ч (адаптивный)")
        logger.info(f"  📊 Мин. сэмплов: {self.min_samples_for_retrain}")
        logger.info(f"  📈 Мин. новых баров для триггера: {self.min_new_bars_for_retrain}")
        logger.info(f"  📉 Порог падения точности: {self.accuracy_drop_threshold:.0%}")
        logger.info(f"  🎯 Порог запуска переобучения: {self.retrain_threshold_percent:.0%}")
        logger.info(f"  💾 Путь к моделям: {self.models_path}")

    def should_retrain_adaptive(
        self,
        symbol: str,
        current_sharpe: float = 0.0,
        volatility_regime: str = "normal",
        performance_decay: float = 0.0,
    ) -> bool:
        """
        Адаптивный триггер переобучения вместо жёсткого таймера.

        Ретренинг если:
        1. Sharpe упал на >15% от пика за окно
        2. Рынок перешёл в high_vol regime
        3. Прошло минимум 12ч с последнего ретрена

        Args:
            symbol: Торговый инструмент
            current_sharpe: Текущий Sharpe ratio модели
            volatility_regime: Текущий режим волатильности
            performance_decay: Степень деградации производительности (0..1)

        Returns:
            True если нужно переобучить
        """
        from datetime import datetime, timedelta

        # Минимальное время между переобучениями (12 часов)
        min_hours_between = 12

        last_retrain = self._last_retrain_time.get(symbol)
        if last_retrain:
            hours_since = (datetime.now() - last_retrain).total_seconds() / 3600
            if hours_since < min_hours_between:
                return False  # Слишком рано

        # Обновляем пиковый Sharpe
        peak_sharpe = self._peak_sharpe.get(symbol, current_sharpe)
        if current_sharpe > peak_sharpe:
            self._peak_sharpe[symbol] = current_sharpe
            peak_sharpe = current_sharpe

        # Проверяем условия для переобучения
        needs_retrain = False
        reasons = []

        # 1. Деградация Sharpe > 15% от пика
        if peak_sharpe > 0 and current_sharpe < peak_sharpe * 0.85:
            needs_retrain = True
            reasons.append(f"Sharpe деградация: {current_sharpe:.2f} vs пик {peak_sharpe:.2f}")

        # 2. Высокая волатильность — модель может устареть
        if volatility_regime in ("high", "High Volatility Range"):
            needs_retrain = True
            reasons.append(f"High vol regime: {volatility_regime}")

        # 3. Performance decay > 15%
        if performance_decay > 0.15:
            needs_retrain = True
            reasons.append(f"Performance decay: {performance_decay:.1%}")

        # 4. Fallback: если прошло больше interval_hours с последнего обучения
        if last_retrain:
            hours_since = (datetime.now() - last_retrain).total_seconds() / 3600
            if hours_since >= self.retrain_interval_hours:
                needs_retrain = True
                reasons.append(f"Timer: {hours_since:.0f}ч >= {self.retrain_interval_hours}ч")
        else:
            needs_retrain = True  # Первое обучение
            reasons.append("Нет истории обучения")

        if needs_retrain:
            logger.info(f"🔄 [{symbol}] Адаптивный ретренинг: {', '.join(reasons)}")

        return needs_retrain

    def check_scaler_mismatch(self, symbol: str) -> dict:
        """
        Проверяет mismatch между scaler и текущим конфигом признаков.

        Returns:
            dict: {'needs_fix': bool, 'scaler_features': int, 'config_features': int, 'has_names': bool}
        """
        import joblib

        result = {"needs_fix": False, "scaler_features": 0, "config_features": 0, "has_names": False, "scaler_exists": False}

        try:
            scaler_path = self.models_path / f"{symbol}_scaler.joblib"
            result["config_features"] = len(self.config.FEATURES_TO_USE)

            if not scaler_path.exists():
                logger.debug(f"[{symbol}] Скалер не найден — требуется обучение")
                result["needs_fix"] = True
                return result

            result["scaler_exists"] = True
            scaler = joblib.load(scaler_path)

            result["scaler_features"] = getattr(scaler, "n_features_in_", 0)
            result["has_names"] = hasattr(scaler, "feature_names_in_")

            # Проверяем mismatch
            if result["scaler_features"] != result["config_features"]:
                result["needs_fix"] = True
                logger.warning(
                    f"⚠️ [{symbol}] Scaler mismatch: "
                    f"scaler={result['scaler_features']}, "
                    f"config={result['config_features']}"
                )

            # Проверяем наличие feature_names_in_
            if not result["has_names"]:
                result["needs_fix"] = True
                logger.warning(f"⚠️ [{symbol}] Scaler без feature_names_in_")

        except Exception as e:
            logger.error(f"[{symbol}] Ошибка проверки scaler: {e}")
            result["needs_fix"] = True

        return result

    def get_symbols_needing_retrain(self, symbols: list = None) -> list:
        """
        Возвращает список символов требующих переобучения.

        Проверяет:
        1. Scaler mismatch (14 vs 20 признаков)
        2. Отсутствие scaler
        3. Истекшее время с последнего обучения
        4. Деградацию производительности

        Args:
            symbols: Список символов для проверки (если None — все из конфига)

        Returns:
            list: Символы требующие переобучения
        """
        if symbols is None:
            symbols = self.config.SYMBOLS_WHITELIST

        needs_retrain = []

        for symbol in symbols:
            # 1. Проверяем scaler mismatch
            scaler_check = self.check_scaler_mismatch(symbol)

            if scaler_check["needs_fix"]:
                reasons = []
                if not scaler_check["scaler_exists"]:
                    reasons.append("scaler отсутствует")
                elif scaler_check["scaler_features"] != scaler_check["config_features"]:
                    reasons.append(f"mismatch: {scaler_check['scaler_features']} vs {scaler_check['config_features']}")
                if not scaler_check["has_names"]:
                    reasons.append("нет feature_names_in_")

                logger.info(f"🔧 [{symbol}] Требуется переобучение: {', '.join(reasons)}")
                needs_retrain.append(symbol)
                continue

            # 2. Проверяем время последнего обучения
            metadata_path = self.models_path / f"{symbol}_metadata.json"
            if metadata_path.exists():
                import json

                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)

                    trained_at = datetime.fromisoformat(metadata.get("trained_at", metadata.get("created_at")))
                    hours_since = (datetime.now() - trained_at).total_seconds() / 3600

                    if hours_since >= self.retrain_interval_hours:
                        logger.info(f"⏰ [{symbol}] Прошло {hours_since:.0f}ч (порог: {self.retrain_interval_hours}ч)")
                        needs_retrain.append(symbol)
                except Exception as e:
                    logger.error(f"[{symbol}] Ошибка чтения metadata: {e}")
                    needs_retrain.append(symbol)
            else:
                logger.info(f"📁 [{symbol}] Metadata отсутствует")
                needs_retrain.append(symbol)

        logger.info(f"📊 Найдено {len(needs_retrain)}/{len(symbols)} символов требующих переобучения")
        return needs_retrain

    def mark_retrained(self, symbol: str):
        """Отмечает что модель была переобучена (для адаптивного триггера)."""
        from datetime import datetime

        self._last_retrain_time[symbol] = datetime.now()
        logger.info(f"✅ [{symbol}] Отмечено время переобучения")

    def set_training_progress_callback(self, callback):
        """
        Устанавливает callback для отправки прогресса обучения в GUI.

        Args:
            callback: Функция(history_object) где history_object.history = {'loss': [...]}
        """
        self._training_progress_callback = callback
        logger.info("📡 [AutoTrainer] Callback прогресса обучения установлен")

    def load_training_data(self, symbol: str, timeframe: str = "D1") -> Optional[pd.DataFrame]:
        """
        Загружает данные для обучения из базы или MT5.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм (по умолчанию D1 — наиболее доступен в БД)

        Returns:
            DataFrame с данными или None
        """
        import MetaTrader5 as mt5

        # Сначала пробуем загрузить из БД (candle_data)
        try:
            query = """
                SELECT timestamp, open, high, low, close, tick_volume
                FROM candle_data
                WHERE symbol LIKE ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            # Оптимизация: используем LIKE для поиска символа с суффиксами (EURUSD -> EURUSD=X)
            df = pd.read_sql_query(
                query, self.db_manager.engine, params=(f"{symbol}%", timeframe, self.min_samples_for_retrain * 2)
            )

            if len(df) >= self.min_samples_for_retrain:
                df.rename(columns={"timestamp": "time"}, inplace=True)
                logger.info(f"Загружено {len(df)} баров из БД для {symbol} ({timeframe})")
                return df
            else:
                logger.info(f"В БД недостаточно данных для {symbol}: {len(df)} баров")

        except Exception as db_error:
            logger.warning(f"Не удалось загрузить из БД: {db_error}")

        # Если в БД нет данных, загружаем напрямую из MT5
        logger.info(f"Загрузка данных из MT5 для {symbol}...")
        try:
            # Убедимся что MT5 инициализирован в этом потоке
            from src.core.mt5_connection_manager import MT5ConnectionManager

            manager = MT5ConnectionManager.get_instance()
            if not manager.is_connected():
                logger.warning(f"MT5 не подключен для {symbol}")
                return None

            # Выбираем символ (может отличаться от имени в whitelist)
            select_symbol = symbol
            rates = mt5.symbol_info_tick(symbol)
            if rates is None:
                # Пробуем распространённые варианты имени
                for alt in [symbol, f"{symbol}c", f"{symbol}.", f"{symbol}m", f"{symbol}pro"]:
                    if mt5.symbol_info_tick(alt):
                        select_symbol = alt
                        logger.info(f"Найден альтернативный символ: {symbol} -> {alt}")
                        break

            # Преобразуем timeframe строку в MT5 константу
            tf_map = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
                "W1": mt5.TIMEFRAME_W1,
            }
            mt5_timeframe = tf_map.get(timeframe, mt5.TIMEFRAME_D1)

            # Получаем последние бары
            rates = mt5.copy_rates_from_pos(select_symbol, mt5_timeframe, 0, self.min_samples_for_retrain * 2)

            if rates is None or len(rates) == 0:
                logger.warning(f"MT5 не вернул данные для {symbol} (пробовал {select_symbol})")
                return None

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)
            df["symbol"] = symbol

            if "tick_volume" not in df.columns:
                df["tick_volume"] = 0

            logger.info(f"Загружено {len(df)} баров из MT5 для {symbol} ({timeframe})")
            return df

        except Exception as mt5_error:
            logger.error(f"Ошибка загрузки из MT5: {mt5_error}", exc_info=True)
            return None

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Создаёт признаки для обучения.

        Args:
            df: DataFrame с данными

        Returns:
            DataFrame с признаками
        """
        df = df.copy()

        # Технические индикаторы
        # SMA
        df["sma_20"] = df["close"].rolling(window=20).mean()
        df["sma_50"] = df["close"].rolling(window=50).mean()

        # RSI
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df["close"].ewm(span=12, adjust=False).mean()
        exp2 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = exp1 - exp2

        # Bollinger Bands
        df["bb_middle"] = df["close"].rolling(window=20).mean()
        df["bb_std"] = df["close"].rolling(window=20).std()
        df["bb_upper"] = df["bb_middle"] + (df["bb_std"] * 2)
        df["bb_lower"] = df["bb_middle"] - (df["bb_std"] * 2)

        # ATR
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr_14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

        # Волатильность
        df["volatility"] = df["close"].pct_change().rolling(window=20).std()

        # Тренд
        df["trend"] = df["close"] / df["close"].shift(20) - 1

        # Целевая переменная (предсказание направления)
        df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)

        # Удаляем NaN
        df = df.dropna()

        return df

    def train_model(self, symbol: str, timeframe: str = "H1") -> bool:
        """
        Обучает модель для символа.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм

        Returns:
            True если успешно
        """
        logger.info(f"Начало обучения модели для {symbol}...")
        start_time = time.time()

        try:
            # Загружаем данные
            df = self.load_training_data(symbol, timeframe)
            if df is None:
                return False

            # Создаём признаки
            df_features = self.prepare_features(df)

            if len(df_features) < self.min_samples_for_retrain:
                logger.warning(f"Недостаточно данных после обработки признаков")
                return False

            # Разделяем на признаки и цель
            feature_columns = [
                "open",
                "high",
                "low",
                "close",
                "tick_volume",
                "sma_20",
                "sma_50",
                "rsi_14",
                "macd",
                "bb_upper",
                "bb_lower",
                "atr_14",
                "volatility",
                "trend",
            ]

            X = df_features[feature_columns].values
            y = df_features["target"].values

            # Разделяем на train/validation
            X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=self.validation_split, shuffle=False)

            # Скалирование — сохраняем имена признаков в scaler
            scaler = StandardScaler()
            # Устанавливаем feature_names_in_ вручную (StandardScaler хранит его)
            scaler.feature_names_in_ = np.array(feature_columns)
            scaler.n_features_in_ = len(feature_columns)
            X_train_scaled = scaler.fit_transform(X_train)
            X_val_scaled = scaler.transform(X_val)

            # Обучаем простую модель (LightGBM для скорости)
            evals_result = {}  # ДЛЯ ОТСЛЕЖИВАНИЯ ПРОГРЕССА
            try:
                import lightgbm as lgb

                # Оптимизация: n_jobs=2 вместо -1 (все ядра) для снижения нагрузки на CPU
                n_jobs_lightgbm = min(2, multiprocessing.cpu_count())

                # GPU параметры (если CUDA доступна и GPU режим включён в настройках)
                gpu_params = {}
                use_gpu = getattr(self, "use_gpu_training", False)
                if use_gpu:
                    try:
                        import subprocess

                        subprocess.check_output(["nvidia-smi"], stderr=subprocess.DEVNULL)
                        # CUDA доступна — включаем GPU
                        gpu_params = {
                            "device": "gpu",
                            "gpu_platform_id": 0,
                            "gpu_device_id": 0,
                        }
                        logger.info("🚀 LightGBM: GPU режим (CUDA)")
                    except Exception:
                        logger.warning("⚠️ GPU включён в настройках, но CUDA недоступна")
                else:
                    logger.info("💡 LightGBM: CPU режим (GPU отключён в настройках)")

                model = lgb.LGBMClassifier(
                    n_estimators=100,
                    learning_rate=0.05,
                    max_depth=5,
                    num_leaves=31,
                    random_state=42,
                    verbose=-1,
                    n_jobs=n_jobs_lightgbm,
                    **gpu_params,
                )

                # ДОБАВЛЕНО: callbacks для отслеживания прогресса
                # Early Stopping + Real-time Loss Tracking
                callbacks_list = [
                    lgb.record_evaluation(evals_result),
                    lgb.early_stopping(stopping_rounds=15, verbose=False),  # Early stopping после 15 эпох без улучшений
                ]

                # ДОБАВЛЯЕМ CUSTOM CALLBACK ДЛЯ REAL-TIME ОТПРАВКИ LOSS
                if self._training_progress_callback:
                    logger.info(f"[AutoTrainer] ✅ Callback установлен для {symbol}, создаем RealTimeLossCallback")

                    class RealTimeLossCallback:
                        """Real-time callback для отправки loss после каждой итерации"""

                        def __init__(self, callback_func, total_estimators=100):
                            self.callback_func = callback_func
                            self.total_estimators = total_estimators
                            self.iteration = 0
                            self.loss_history = []

                        def __call__(self, env):
                            self.iteration += 1
                            # Получаем loss из evals_result
                            if "valid_0" in evals_result and "log_loss" in evals_result["valid_0"]:
                                current_loss = evals_result["valid_0"]["log_loss"][-1]
                                self.loss_history.append(current_loss)

                                # Отправляем прогресс после каждой итерации
                                progress_percent = int((self.iteration / self.total_estimators) * 100)
                                status_text = f"Итерация {self.iteration}/{self.total_estimators}, Loss: {current_loss:.4f}"

                                logger.info(
                                    f"[AutoTrainer.Callback] ✅ Итерация {self.iteration}/{self.total_estimators}, loss={current_loss:.4f}"
                                )

                                # Создаём history object совместимый с GUI
                                history_obj = type(
                                    "History",
                                    (),
                                    {
                                        "history": {
                                            "loss": self.loss_history.copy(),
                                            "epoch": self.iteration,
                                            "total_epochs": self.total_estimators,
                                            "progress_percent": progress_percent,
                                            "status_text": status_text,
                                        }
                                    },
                                )()

                                try:
                                    self.callback_func(history_obj)
                                    logger.debug(f"[AutoTrainer.Callback] Callback вызван успешно")
                                except Exception as e:
                                    logger.error(
                                        f"[AutoTrainer.Callback] ❌ Ошибка отправки real-time loss: {e}", exc_info=True
                                    )

                    # Добавляем custom callback в список
                    real_time_callback = RealTimeLossCallback(self._training_progress_callback, total_estimators=100)
                    callbacks_list.append(real_time_callback)

                model.fit(
                    X_train_scaled,
                    y_train,
                    eval_set=[(X_val_scaled, y_val)],
                    callbacks=callbacks_list,
                )

                # Валидация
                train_pred = model.predict(X_train_scaled)
                val_pred = model.predict(X_val_scaled)

                train_acc = (train_pred == y_train).mean()
                val_acc = (val_pred == y_val).mean()

                logger.info(f"Модель обучена: Train Acc={train_acc:.3f}, Val Acc={val_acc:.3f}")

                # ФИНАЛЬНАЯ ОТПРАВКА ПРОГРЕССА ОБУЧЕНИЯ В GUI (через callback)
                # Теперь это дублирует real-time отправку, но гарантирует доставку
                if self._training_progress_callback:
                    try:
                        if "valid_0" in evals_result and "log_loss" in evals_result["valid_0"]:
                            loss_history = evals_result["valid_0"]["log_loss"]
                            final_loss = loss_history[-1] if loss_history else 0.0

                            # Определяем было ли early stopping
                            actual_iterations = len(loss_history)
                            early_stopped = actual_iterations < 100  # Если меньше 100, было early stopping

                            history_obj = type(
                                "History",
                                (),
                                {
                                    "history": {
                                        "loss": loss_history,
                                        "epoch": actual_iterations,
                                        "total_epochs": 100,
                                        "progress_percent": 100,
                                        "status_text": f"Завершено: {actual_iterations}/100 итераций, Loss: {final_loss:.4f}",
                                        "final_loss": final_loss,
                                        "early_stopped": early_stopped,
                                        "train_accuracy": train_acc,
                                        "val_accuracy": val_acc,
                                    }
                                },
                            )()
                            self._training_progress_callback(history_obj)
                            logger.info(
                                f"📊 [AutoTrainer] Отправлен финальный прогресс: {actual_iterations} итераций, "
                                f"loss={final_loss:.4f}, val_acc={val_acc:.3f}"
                                + (" (Early Stopping)" if early_stopped else "")
                            )
                    except Exception as progress_error:
                        logger.warning(f"⚠️ Не удалось отправить прогресс обучения: {progress_error}")

            except ImportError:
                logger.warning("LightGBM не установлен, используем RandomForest")
                from sklearn.ensemble import RandomForestClassifier

                # Оптимизация: n_jobs=2 вместо -1
                model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=2)

                model.fit(X_train_scaled, y_train)

                val_pred = model.predict(X_val_scaled)
                val_acc = (val_pred == y_val).mean()

                train_acc = 0.0  # Не вычисляем для скорости
                logger.info(f"Модель обучена: Val Acc={val_acc:.3f}")

            # Сохраняем модель
            save_metadata = {
                "train_accuracy": train_acc,
                "val_accuracy": val_acc,
                "training_samples": len(X_train),
                "validation_samples": len(X_val),
                "features": feature_columns,
            }

            # ДОБАВЛЕНО: Сохраняем loss history для анализа
            if "valid_0" in evals_result and "log_loss" in evals_result["valid_0"]:
                loss_history = evals_result["valid_0"]["log_loss"]
                save_metadata["loss_history"] = loss_history
                save_metadata["final_loss"] = loss_history[-1] if loss_history else None
                save_metadata["training_iterations"] = len(loss_history)
                save_metadata["early_stopped"] = len(loss_history) < 100  # Было ли early stopping

                logger.info(
                    f"📈 Loss history: {len(loss_history)} итераций, "
                    f"final={loss_history[-1]:.4f}, "
                    f"initial={loss_history[0]:.4f if loss_history else 'N/A'}"
                )
            self._save_model(
                symbol,
                model,
                scaler,
                save_metadata,
                timeframe=timeframe,
            )

            # === ИНТЕГРАЦИЯ CHAMPIONSHIP: валидация и повышение ===
            self._championship_validation_if_enabled(symbol, model, scaler, save_metadata, timeframe)

            elapsed = time.time() - start_time
            logger.info(f"Обучение завершено за {elapsed:.1f} сек")

            self.stats["last_training_time"] = datetime.now()
            self.stats["models_trained"] += 1

            # ОЧИСТКА ПАМЯТИ после обучения
            try:
                from src.core.memory_utils import cleanup_resources

                cleanup_resources(force_gc=True, clear_cuda_cache=True, log_memory=True)
            except Exception as cleanup_error:
                logger.warning(f"⚠️ Ошибка очистки памяти после обучения: {cleanup_error}")

            return True

        except Exception as e:
            logger.error(f"Ошибка при обучении модели: {e}")
            self.stats["training_errors"] += 1
            return False

    def _save_model(self, symbol: str, model: Any, scaler: StandardScaler, metadata: Dict[str, Any], timeframe: str = "H1"):
        """
        Сохраняет модель на диск и в базу данных.

        Args:
            symbol: Торговый инструмент
            model: Обученная модель
            scaler: Скалер признаков
            metadata: Метаданные обучения
        """
        try:
            # Путь к файлам
            model_file = self.models_path / f"{symbol}_model.joblib"
            scaler_file = self.models_path / f"{symbol}_scaler.joblib"
            metadata_file = self.models_path / f"{symbol}_metadata.json"

            # Сохраняем на диск
            joblib.dump(model, model_file)
            joblib.dump(scaler, scaler_file)

            metadata["symbol"] = symbol
            metadata["trained_at"] = datetime.now().isoformat()
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Модель {symbol} сохранена на диск")

            # Сохраняем в базу данных синхронно с получением ID
            try:
                import uuid

                # Преобразуем timeframe строки в MT5 константу
                mt5_timeframe = 16385  # H1 default
                try:
                    import MetaTrader5 as mt5

                    tf_map = {
                        "M1": mt5.TIMEFRAME_M1,
                        "M5": mt5.TIMEFRAME_M5,
                        "M15": mt5.TIMEFRAME_M15,
                        "M30": mt5.TIMEFRAME_M30,
                        "H1": mt5.TIMEFRAME_H1,
                        "H4": mt5.TIMEFRAME_H4,
                        "D1": mt5.TIMEFRAME_D1,
                        "W1": mt5.TIMEFRAME_W1,
                    }
                    mt5_timeframe = tf_map.get(timeframe, mt5.TIMEFRAME_H1)
                except Exception:
                    # Оставляем дефолт H1
                    pass

                model_id = self.db_manager.save_model_and_scalers_sync(
                    symbol=symbol,
                    timeframe=mt5_timeframe,
                    model=model,
                    model_type="LightGBM",
                    x_scaler=scaler,
                    y_scaler=None,
                    features_list=metadata.get("features", []),
                    training_batch_id=f"auto_{uuid.uuid4().hex[:8]}",
                    hyperparameters=metadata,
                )
                if model_id:
                    logger.info(f"Модель {symbol} сохранена в БД с ID={model_id}")
                    # Если чемпиона нет — повышаем новую модель до чемпиона автоматически
                    try:
                        session = self.db_manager.Session()
                        from src.db.models import TrainedModel

                        has_champion = (
                            session.query(TrainedModel)
                            .filter_by(symbol=symbol, timeframe=mt5_timeframe, model_type="LightGBM", is_champion=True)
                            .first()
                            is not None
                        )
                    finally:
                        session.close()

                    if not has_champion:
                        logger.warning(f"[AutoTrainer] Чемпион не найден для {symbol} ({mt5_timeframe}). Продвигаем модель.")
                        report = {
                            "auto_promoted": True,
                            "train_accuracy": metadata.get("train_accuracy"),
                            "val_accuracy": metadata.get("val_accuracy"),
                            "training_samples": metadata.get("training_samples"),
                            "validation_samples": metadata.get("validation_samples"),
                        }
                        try:
                            self.db_manager._promote_challenger_to_champion_internal(model_id, report)
                        except Exception as promote_error:
                            logger.error(f"Ошибка автопродвижения в чемпионы: {promote_error}", exc_info=True)
                else:
                    logger.warning(f"Модель {symbol} сохранена на диск, но НЕ сохранена в БД (ID=None)")
            except Exception as db_error:
                logger.error(f"Не удалось сохранить модель {symbol} в БД: {db_error}", exc_info=True)
                # Не блокируем работу, если БД недоступна

            # Обновляем кэш
            self.models[symbol] = model
            self.scalers[symbol] = scaler
            self.model_metadata[symbol] = metadata

        except Exception as e:
            logger.error(f"Ошибка сохранения модели: {e}")

    def _championship_validation_if_enabled(
        self,
        symbol: str,
        model: Any,
        scaler: Any,
        metadata: Dict[str, Any],
        timeframe: str = "H1",
    ) -> None:
        """
        Запускает валидацию через Championship если модуль доступен.
        Вызывается автоматически после train_model().
        """
        try:
            from src.ml.championship_retraining import ChampionshipRetrainer

            retrainer = ChampionshipRetrainer(
                config=self.config,
                auto_trainer=self,
                championship=None,  # championship модуль опционален
                db_manager=self.db_manager,
            )

            result = retrainer.validate_and_promote(symbol, model, scaler, metadata, timeframe)

            if result.get("promoted"):
                logger.info(
                    f"🏆 [AutoTrainer->Championship] {symbol} повышен до чемпиона! " f"Score={result.get('score', 0):.3f}"
                )
            else:
                logger.debug(f"[AutoTrainer->Championship] {symbol} не повышен: {result.get('reason', 'unknown')}")

        except ImportError:
            logger.debug("[AutoTrainer] championship_retraining модуль недоступен, пропускаю")
        except Exception as e:
            logger.warning(f"[AutoTrainer->Championship] Ошибка: {e}")

    def load_model(self, symbol: str) -> Optional[tuple]:
        """
        Загружает модель с диска.

        Args:
            symbol: Торговый инструмент

        Returns:
            (model, scaler, metadata) или None
        """
        try:
            # Проверяем кэш
            if symbol in self.models:
                return self.models[symbol], self.scalers[symbol], self.model_metadata[symbol]

            # Путь к файлам
            model_file = self.models_path / f"{symbol}_model.joblib"
            scaler_file = self.models_path / f"{symbol}_scaler.joblib"
            metadata_file = self.models_path / f"{symbol}_metadata.json"

            if not model_file.exists():
                logger.warning(f"Модель {symbol} не найдена")
                return None

            # Загружаем
            model = joblib.load(model_file)
            scaler = joblib.load(scaler_file)

            with open(metadata_file, "r") as f:
                metadata = json.load(f)

            # Обновляем кэш
            self.models[symbol] = model
            self.scalers[symbol] = scaler
            self.model_metadata[symbol] = metadata

            logger.info(f"Модель {symbol} загружена")

            return model, scaler, metadata

        except Exception as e:
            logger.error(f"Ошибка загрузки модели: {e}")
            return None

    def predict(self, symbol: str, features: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """
        Делает предсказание используя обученную модель.

        Args:
            symbol: Торговый инструмент
            features: Словарь с признаками

        Returns:
            Предсказание или None
        """
        result = self.load_model(symbol)
        if result is None:
            return None

        model, scaler, metadata = result

        try:
            # Создаём вектор признаков
            feature_columns = metadata.get("features", [])
            X = np.array([[features.get(col, 0.0) for col in feature_columns]])

            # Скалируем
            X_scaled = scaler.transform(X)

            # Предсказываем
            prediction = model.predict(X_scaled)[0]
            probability = model.predict_proba(X_scaled)[0]

            return {
                "prediction": int(prediction),
                "probability": float(probability[prediction]),
                "confidence": float(max(probability)),
                "model_accuracy": metadata.get("val_accuracy", 0.0),
            }

        except Exception as e:
            logger.error(f"Ошибка предсказания: {e}")
            return None

    def should_retrain(self, symbol: str, current_data: Optional[pd.DataFrame] = None) -> bool:
        """
        Проверяет, нужно ли переобучать модель по НЕСКОЛЬКИМ КРИТЕРИЯМ.

        Критерии переобучения:
        1. Время с последнего обучения (interval_hours)
        2. Количество новых баров (min_new_bars_for_retrain)
        3. Изменение волатильности (volatility_change_threshold)
        4. Падение точности модели (accuracy_drop_threshold)

        Args:
            symbol: Торговый инструмент
            current_data: Текущие данные для проверки (опционально)

        Returns:
            True если нужно переобучить
        """
        metadata_file = self.models_path / f"{symbol}_metadata.json"

        if not metadata_file.exists():
            logger.info(f"🔴 {symbol}: Модели нет - ТРЕБУЕТСЯ обучение")
            return True  # Модели нет, нужно обучить

        try:
            with open(metadata_file, "r") as f:
                metadata = json.load(f)

            trained_at = datetime.fromisoformat(metadata["trained_at"])
            hours_since_training = (datetime.now() - trained_at).total_seconds() / 3600

            # КРИТЕРИЙ 1: Время с последнего обучения
            if hours_since_training >= self.retrain_interval_hours:
                logger.info(
                    f"🕐 {symbol}: Прошло {hours_since_training:.1f} ч (порог: {self.retrain_interval_hours} ч) - ТРЕБУЕТСЯ переобучение"
                )
                return True

            # КРИТЕРИЙ 2: Количество новых баров
            if current_data is not None and symbol in self._last_bars_count:
                new_bars = len(current_data) - self._last_bars_count[symbol]
                if new_bars >= self.min_new_bars_for_retrain:
                    logger.info(
                        f"📊 {symbol}: {new_bars} новых баров (порог: {self.min_new_bars_for_retrain}) - ТРЕБУЕТСЯ переобучение"
                    )
                    return True

            # КРИТЕРИЙ 3: Изменение волатильности
            if current_data is not None and symbol in self._last_volatility:
                current_volatility = current_data["close"].pct_change().std()
                if not pd.isna(current_volatility):
                    volatility_change = abs(current_volatility - self._last_volatility[symbol]) / (
                        self._last_volatility[symbol] + 1e-9
                    )
                    if volatility_change >= self.volatility_change_threshold:
                        logger.info(
                            f"📈 {symbol}: Волатильность изменилась на {volatility_change:.1%} (порог: {self.volatility_change_threshold:.0%}) - ТРЕБУЕТСЯ переобучение"
                        )
                        return True

            # КРИТЕРИЙ 4: Падение точности модели (если есть данные для проверки)
            if symbol in self._last_accuracy:
                current_accuracy = metadata.get("val_accuracy", 0)
                accuracy_drop = self._last_accuracy[symbol] - current_accuracy
                if accuracy_drop >= self.accuracy_drop_threshold:
                    logger.info(
                        f"📉 {symbol}: Точность упала на {accuracy_drop:.1%} (порог: {self.accuracy_drop_threshold:.0%}) - ТРЕБУЕТСЯ переобучение"
                    )
                    return True

            # Обновляем кэш
            if current_data is not None:
                self._last_bars_count[symbol] = len(current_data)
                self._last_volatility[symbol] = current_data["close"].pct_change().std()
                self._last_accuracy[symbol] = metadata.get("val_accuracy", 0)

            logger.debug(f"🟢 {symbol}: Переобучение не требуется (прошло {hours_since_training:.1f} ч)")
            return False

        except Exception as e:
            logger.error(f"Ошибка проверки необходимости переобучения для {symbol}: {e}")
            return True  # При ошибке возвращаем True для безопасности

    def auto_train_all(self, threshold_percent: float = 0.30) -> Dict[str, bool]:
        """
        Автоматически переобучает все модели когда 30%+ символов нуждаются в переобучении.

        Args:
            threshold_percent: Порог символов для запуска переобучения (0.30 = 30%)

        Returns:
            Словарь {symbol: успех} или пустой dict если порог не достигнут
        """
        logger.info("🔍 Запуск проверки необходимости переобучения...")

        # ШАГ 1: Сначала проверяем какие символы нуждаются в переобучении
        symbols_needing_retrain = []
        symbols_ok = []

        for symbol in self.config.SYMBOLS_WHITELIST:
            # Загружаем текущие данные для проверки триггеров
            current_data = self.load_training_data(symbol)

            if self.should_retrain(symbol, current_data):
                symbols_needing_retrain.append(symbol)
            else:
                symbols_ok.append(symbol)

        total_symbols = len(self.config.SYMBOLS_WHITELIST)
        needs_count = len(symbols_needing_retrain)
        needs_percent = needs_count / total_symbols if total_symbols > 0 else 0

        logger.info(
            f"📊 Прогресс переобучения: {needs_count}/{total_symbols} ({needs_percent:.1%}) символов требуют переобучения"
        )

        # ШАГ 2: Проверяем порог - если меньше 30%, НЕ переобучаем
        if needs_percent < self.retrain_threshold_percent:
            logger.info(
                f"⏸️ Переобучение ОТМЕНЕНО: {needs_percent:.1%} < {self.retrain_threshold_percent:.0%} порога\n"
                f"   ✅ Готовы: {len(symbols_ok)} символов\n"
                f"   ⏳ Требуют: {needs_count} символов\n"
                f"   📊 Прогресс: {needs_percent:.1%}"
            )
            return {}

        logger.info(
            f"🚀 ПОРОГ ДОСТИГНУТ: {needs_percent:.1%} >= {threshold_percent:.0%}\n"
            f"   Запускаем переобучение {needs_count} символов..."
        )

        # ШАГ 3: Переобучаем все символы которые нуждаются
        results = {}
        retrain_count = 0
        error_count = 0

        for symbol in symbols_needing_retrain:
            logger.info(f"🔄 {symbol}: Начало переобучения...")
            success = self.train_model(symbol)
            results[symbol] = success
            if success:
                retrain_count += 1
            else:
                error_count += 1

        # Отмечаем все переобученные символы
        for symbol in symbols_needing_retrain:
            self.mark_retrained(symbol)

        logger.info(
            f"✅ Переобучение завершено:\n"
            f"   📊 Всего символов: {total_symbols}\n"
            f"   ✅ Было готово: {len(symbols_ok)}\n"
            f"   🔄 Переобучено: {retrain_count}/{needs_count}\n"
            f"   ❌ Ошибок: {error_count}\n"
            f"   📈 Новый прогресс: {(len(symbols_ok) + retrain_count)}/{total_symbols} "
            f"({(len(symbols_ok) + retrain_count) / total_symbols:.1%})"
        )

        logger.info(f"📊 Успешность: {sum(results.values())}/{len(results)}")

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику авто-тренера."""
        return {**self.stats, "models_cached": len(self.models), "retrain_interval_hours": self.retrain_interval_hours}

    def get_retrain_progress(self) -> Dict[str, Any]:
        """
        Возвращает прогресс переобучения для GUI.

        Returns:
            Dict с информацией о прогрессе:
            - total_symbols: Общее количество символов
            - symbols_needing_retrain: Список символов требующих переобучения
            - count_needing_retrain: Количество требующих переобучения
            - progress_percent: Процент символов требующих переобучения
            - threshold_percent: Порог запуска переобучения
            - threshold_reached: Достигнут ли порог
            - can_start_retrain: Можно ли запустить переобучение
        """
        symbols_needing_retrain = []

        for symbol in self.config.SYMBOLS_WHITELIST:
            current_data = self.load_training_data(symbol)
            if self.should_retrain(symbol, current_data):
                symbols_needing_retrain.append(symbol)

        total_symbols = len(self.config.SYMBOLS_WHITELIST)
        count_needing = len(symbols_needing_retrain)
        progress_percent = count_needing / total_symbols if total_symbols > 0 else 0
        threshold_reached = progress_percent >= self.retrain_threshold_percent

        return {
            "total_symbols": total_symbols,
            "symbols_needing_retrain": symbols_needing_retrain,
            "count_needing_retrain": count_needing,
            "progress_percent": round(progress_percent, 3),
            "threshold_percent": self.retrain_threshold_percent,
            "threshold_reached": threshold_reached,
            "can_start_retrain": threshold_reached,
        }


class AutoTrainerScheduler:
    """
    Планировщик для автоматического переобучения.
    """

    def __init__(self, auto_trainer: AutoTrainer, config: Settings):
        """
        Инициализация планировщика.

        Args:
            auto_trainer: Авто-тренер
            config: Конфигурация системы
        """
        self.auto_trainer = auto_trainer
        self.config = config

        # Интервал проверки (в минутах) - УМЕНЬШЕНО с 60 до 15 минут
        self.check_interval_minutes = getattr(config, "AUTO_RETRAIN_CHECK_INTERVAL_MINUTES", 15)

        # Флаг работы
        self._running = False
        self._thread: Optional[threading.Thread] = None

        logger.info(f"⏰ Auto Trainer Scheduler инициализирован (проверка каждые {self.check_interval_minutes} мин)")
        logger.info(f"   Интервал переобучения: {self.auto_trainer.retrain_interval_hours} ч")
        logger.info(f"   Мин. баров для триггера: {self.auto_trainer.min_new_bars_for_retrain}")

    def start(self):
        """Запускает планировщик."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("Auto Trainer Scheduler запущен")

    def stop(self):
        """Останавливает планировщик."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Auto Trainer Scheduler остановлен")

    def _run_loop(self):
        """Основной цикл планировщика."""
        while self._running:
            try:
                # Проверяем необходимость переобучения
                self.auto_trainer.auto_train_all()

                # Пауза
                for _ in range(self.check_interval_minutes * 60):
                    if not self._running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Ошибка в цикле авто-обучения: {e}")
                time.sleep(60)

    def train_now(self, symbol: str) -> bool:
        """
        Запускает обучение немедленно.

        Args:
            symbol: Торговый инструмент

        Returns:
            True если успешно
        """
        logger.info(f"Немедленное обучение для {symbol}...")
        return self.auto_trainer.train_model(symbol)
