# -*- coding: utf-8 -*-
"""
src/ml/championship_retraining.py — Интеграция Championship в Auto Retraining

После обучения модели запускает валидацию через Championship.
Только лучшая модель сохраняется в F:\ai_models и подгружается системой.

Поток:
1. AutoTrainer тренирует новую модель
2. ChampionshipRetrainer запускает walk-forward валидацию
3. Сравнивает с текущим чемпионом
4. Если новая модель лучше — сохраняет и делает hot-reload
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.core.config_models import Settings
from src.ml.model_paths import ModelPathConfig

logger = logging.getLogger(__name__)


class ChampionshipRetrainer:
    """
    Связующее звено между Auto Retraining и Championship.

    Отвечает за:
    - Валидацию новой модели после обучения
    - Сравнение с текущим чемпионом
    - Сохранение лучшей модели в правильную директорию
    - Hot-reload через ModelLoader
    """

    def __init__(
        self,
        config: Settings,
        auto_trainer: Any = None,  # AutoTrainer
        championship: Any = None,  # ModelChampionship
        db_manager: Any = None,
    ):
        self.config = config
        self.auto_trainer = auto_trainer
        self.championship = championship
        self.db_manager = db_manager
        self.paths = ModelPathConfig(config)

        # Настройки валидации
        self.min_val_accuracy = getattr(config, "CHAMPIONSHIP_MIN_WIN_RATE", 0.52)
        self.min_sharpe = getattr(config, "CHAMPIONSHIP_MIN_SHARPE", 0.3)
        self.max_drawdown = getattr(config, "CHAMPIONSHIP_MAX_DRAWDOWN", 20.0)
        self.min_profit_factor = getattr(config, "CHAMPIONSHIP_MIN_PROFIT_FACTOR", 0.8)
        self.min_trades = getattr(config, "CHAMPIONSHIP_MIN_TRADES", 10)

        logger.info(f"[ChampionshipRetrainer] Инициализирован. Models: {self.paths.model_dir}")

    def validate_and_promote(
        self,
        symbol: str,
        model: Any,
        scaler: Any,
        metadata: Dict[str, Any],
        timeframe: str = "H1",
    ) -> Dict[str, Any]:
        """
        Валидирует модель через Championship и повышает до чемпиона если лучше.

        Args:
            symbol: Торговый символ
            model: Обученная модель
            scaler: Скалер
            metadata: Метаданные обучения
            timeframe: Таймфрейм

        Returns:
            Результат валидации: {promoted, reason, score, champion_score}
        """
        result = {
            "promoted": False,
            "reason": "validation_not_run",
            "score": 0.0,
            "champion_score": 0.0,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(f"[ChampionshipRetrainer] Начинаю валидацию {symbol} ({timeframe})")

        # 1. Walk-forward валидация через Championship
        val_result = self._run_walkforward_validation(symbol, model, scaler, metadata, timeframe)

        if not val_result.get("valid", False):
            result["reason"] = f"validation_failed: {val_result.get('error', 'unknown')}"
            logger.warning(f"[ChampionshipRetrainer] Валидация не пройдена: {result['reason']}")
            return result

        result["score"] = val_result.get("composite_score", 0.0)
        result["metrics"] = val_result.get("metrics", {})

        # 2. Проверка порогов
        if not self._passes_thresholds(val_result):
            result["reason"] = "below_threshold"
            logger.info(
                f"[ChampionshipRetrainer] {symbol} ниже порогов: "
                f"WR={val_result.get('win_rate', 0):.3f}, "
                f"Sharpe={val_result.get('sharpe', 0):.3f}"
            )
            return result

        # 3. Сравнение с чемпионом
        champion_result = self._get_current_champion(symbol, timeframe)

        if champion_result:
            result["champion_score"] = champion_result.get("composite_score", 0.0)

            if result["score"] <= result["champion_score"]:
                result["reason"] = "not_better_than_champion"
                logger.info(
                    f"[ChampionshipRetrainer] {symbol}: новая модель ({result['score']:.3f}) "
                    f"не лучше чемпиона ({result['champion_score']:.3f})"
                )
                return result

        # 4. Новая модель лучше — сохраняем и повышаем
        logger.info(
            f"[ChampionshipRetrainer] ✅ {symbol}: новая модель ЛУЧШАЯ! "
            f"Score={result['score']:.3f} vs champion={result['champion_score']:.3f}"
        )

        # 4a. Backup текущей модели
        self._backup_current_model(symbol, timeframe)

        # 4b. Сохраняем новую модель как чемпион
        save_path = self._save_champion_model(symbol, model, scaler, metadata, val_result, timeframe)

        if save_path:
            result["promoted"] = True
            result["model_path"] = str(save_path)
            result["reason"] = "promoted_to_champion"

            # 4c. Обновляем чемпион в БД
            self._update_champion_in_db(symbol, timeframe, val_result)

            # 4d. Hot-reload
            self._trigger_hot_reload(symbol)

            logger.info(f"[ChampionshipRetrainer] 🏆 {symbol} чемпион обновлён: {save_path}")
        else:
            result["reason"] = "save_failed"
            logger.error(f"[ChampionshipRetrainer] Не удалось сохранить чемпиона для {symbol}")

        return result

    def _run_walkforward_validation(
        self,
        symbol: str,
        model: Any,
        scaler: Any,
        metadata: Dict[str, Any],
        timeframe: str,
    ) -> Dict[str, Any]:
        """
        Запускает walk-forward валидацию.

        Если championship модуль доступен — используем его.
        Иначе — упрощённая backtest-валидация.
        """
        if self.championship is not None:
            try:
                return self.championship.validate_single_model(
                    symbol=symbol,
                    model=model,
                    scaler=scaler,
                    metadata=metadata,
                    timeframe=timeframe,
                )
            except Exception as e:
                logger.warning(f"[ChampionshipRetrainer] Championship validation error: {e}")

        # Fallback: упрощённая валидация
        return self._simple_validation(symbol, model, scaler, metadata, timeframe)

    def _simple_validation(
        self,
        symbol: str,
        model: Any,
        scaler: Any,
        metadata: Dict[str, Any],
        timeframe: str,
    ) -> Dict[str, Any]:
        """
        Упрощённая валидация без полного Championship.

        Загружает последние данные, создаёт признаки, делает предсказания, считает метрики.
        """
        if self.auto_trainer is None:
            return {"valid": False, "error": "auto_trainer not available"}

        try:
            # Загружаем сырые данные для валидации
            df_raw = self.auto_trainer.load_training_data(symbol, timeframe)
            if df_raw is None or len(df_raw) < 200:
                return {"valid": False, "error": "insufficient_data"}

            # СОЗДАЁМ ПРИЗНАКИ через prepare_features
            df = self.auto_trainer.prepare_features(df_raw)
            if len(df) < 50:  # После dropna может остаться мало данных
                return {"valid": False, "error": "insufficient_data_after_feature_engineering"}

            # Разделяем: последние 20% для валидации
            split = int(len(df) * 0.8)
            df_val = df.iloc[split:]

            feature_columns = metadata.get("features", [])
            if not feature_columns:
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

            # ПРОВЕРКА: убеждаемся что все признаки присутствуют
            missing_cols = [col for col in feature_columns if col not in df_val.columns]
            if missing_cols:
                logger.warning(
                    f"[{symbol}] Отсутствуют признаки: {missing_cols}. " f"Пропуск валидации или генерация дефолтных значений."
                )
                # Создаём缺失ющие колонки с дефолтными значениями
                for col in missing_cols:
                    df_val[col] = 0.0
                    logger.debug(f"[{symbol}] Создан дефолтный признак: {col}")

            # Используем DataFrame с именами колонок (не numpy array) для LightGBM
            X_val = df_val[feature_columns]  # DataFrame, не .values!
            y_val = df_val["target"].values if "target" in df_val.columns else np.zeros(len(df_val))

            # Скалирование — сохраняем имена колонок
            if hasattr(scaler, "feature_names_in_"):
                X_val_scaled = scaler.transform(X_val)
                # Восстанавливаем DataFrame после трансформации
                X_val_scaled = pd.DataFrame(X_val_scaled, columns=feature_columns, index=X_val.index)
            else:
                X_val_scaled = scaler.transform(X_val.values)
                X_val_scaled = pd.DataFrame(X_val_scaled, columns=feature_columns, index=X_val.index)

            # Предсказания
            predictions = model.predict(X_val_scaled)
            if hasattr(model, "predict_proba"):
                probabilities = model.predict_proba(X_val_scaled)
            else:
                probabilities = None

            # Метрики
            correct = (predictions == y_val).sum()
            accuracy = correct / len(y_val) if len(y_val) > 0 else 0.0

            # Простая симуляция торговли
            trades = self._simulate_trades(predictions, df_val, probabilities)

            sharpe = trades.get("sharpe_ratio", 0.0)
            win_rate = trades.get("win_rate", accuracy)
            profit_factor = trades.get("profit_factor", 1.0)
            max_dd = trades.get("max_drawdown", 0.0)

            composite = 0.4 * sharpe + 0.25 * profit_factor + 0.2 * win_rate - 0.15 * max_dd

            return {
                "valid": True,
                "accuracy": accuracy,
                "win_rate": win_rate,
                "sharpe": sharpe,
                "profit_factor": profit_factor,
                "max_drawdown": max_dd,
                "composite_score": composite,
                "n_trades": trades.get("n_trades", 0),
                "metrics": trades,
            }

        except Exception as e:
            logger.error(f"[ChampionshipRetrainer] Simple validation error: {e}", exc_info=True)
            return {"valid": False, "error": str(e)}

    def _simulate_trades(self, predictions, df_val, probabilities) -> Dict[str, float]:
        """Простая симуляция торговли для оценки модели."""
        if len(predictions) == 0:
            return {"sharpe_ratio": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0, "n_trades": 0}

        returns = []
        wins = 0
        total_trades = 0
        gross_profit = 0.0
        gross_loss = 0.0
        equity = 10000.0
        max_equity = 10000.0
        max_drawdown = 0.0

        for i, pred in enumerate(predictions):
            if pred == 0:  # HOLD
                continue

            # Размер движения цены
            if i < len(df_val) - 1:
                price_change = (df_val.iloc[i + 1]["close"] - df_val.iloc[i]["close"]) / df_val.iloc[i]["close"]
            else:
                continue

            # PnL позиции
            trade_return = price_change if pred == 1 else -price_change
            returns.append(trade_return)

            if trade_return > 0:
                wins += 1
                gross_profit += trade_return
            else:
                gross_loss += abs(trade_return)

            equity *= 1 + trade_return * 10  # 10x leverage для заметности
            max_equity = max(max_equity, equity)
            dd = (max_equity - equity) / max_equity * 100
            max_drawdown = max(max_drawdown, dd)

            total_trades += 1

        if total_trades == 0:
            return {"sharpe_ratio": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0, "n_trades": 0}

        win_rate = wins / total_trades
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

        if len(returns) > 1:
            sharpe = np.mean(returns) / (np.std(returns) + 1e-8) * np.sqrt(252)
        else:
            sharpe = 0.0

        return {
            "sharpe_ratio": sharpe,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "n_trades": total_trades,
            "final_equity": equity,
        }

    def _passes_thresholds(self, val_result: Dict[str, Any]) -> bool:
        """Проверяет что модель проходит пороги."""
        win_rate = val_result.get("win_rate", 0.0)
        sharpe = val_result.get("sharpe", 0.0)
        max_dd = val_result.get("max_drawdown", 100.0)
        profit_factor = val_result.get("profit_factor", 0.0)
        n_trades = val_result.get("n_trades", 0)

        return (
            win_rate >= self.min_val_accuracy
            and sharpe >= self.min_sharpe
            and max_dd <= self.max_drawdown
            and profit_factor >= self.min_profit_factor
            and n_trades >= self.min_trades
        )

    def _get_current_champion(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Получает метрики текущего чемпиона из БД."""
        if self.db_manager is None:
            return None

        try:
            session = self.db_manager.Session()
            from src.db.models import TrainedModel

            champion = (
                session.query(TrainedModel)
                .filter_by(
                    symbol=symbol,
                    timeframe=self._timeframe_to_int(timeframe),
                    is_champion=True,
                )
                .order_by(TrainedModel.trained_at.desc())
                .first()
            )

            if champion and champion.metadata:
                meta = json.loads(champion.metadata) if isinstance(champion.metadata, str) else champion.metadata
                return {
                    "model_id": champion.id,
                    "composite_score": meta.get("composite_score", 0.0),
                    "win_rate": meta.get("win_rate", 0.0),
                    "sharpe": meta.get("sharpe_ratio", 0.0),
                }

            return None
        except Exception as e:
            logger.debug(f"[ChampionshipRetrainer] Ошибка получения чемпиона: {e}")
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _backup_current_model(self, symbol: str, timeframe: str) -> None:
        """Создаёт backup текущей модели чемпиона."""
        try:
            model_path = self.paths.get_model_path(symbol)
            if model_path.exists():
                backup = self.paths.backup_model(model_path)
                logger.info(f"[ChampionshipRetrainer] Backup: {backup}")
        except Exception as e:
            logger.warning(f"[ChampionshipRetrainer] Ошибка backup: {e}")

    def _save_champion_model(
        self,
        symbol: str,
        model: Any,
        scaler: Any,
        metadata: Dict[str, Any],
        val_result: Dict[str, Any],
        timeframe: str,
    ) -> Optional[Path]:
        """Сохраняет модель как чемпион в F:\ai_models."""
        try:
            import joblib

            # Формируем имя чемпиона
            champion_name = f"{symbol}_champion"
            model_path = self.paths.model_dir / f"{champion_name}_model.joblib"
            scaler_path = self.paths.model_dir / f"{champion_name}_scaler.joblib"
            meta_path = self.paths.model_dir / f"{champion_name}_metadata.json"

            # Сохраняем
            joblib.dump(model, model_path)
            joblib.dump(scaler, scaler_path)

            # Обновляем метаданные
            metadata.update(
                {
                    "is_champion": True,
                    "champion_since": datetime.now().isoformat(),
                    "composite_score": val_result.get("composite_score", 0.0),
                    "win_rate": val_result.get("win_rate", 0.0),
                    "sharpe_ratio": val_result.get("sharpe", 0.0),
                    "profit_factor": val_result.get("profit_factor", 0.0),
                    "max_drawdown": val_result.get("max_drawdown", 0.0),
                    "timeframe": timeframe,
                }
            )

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"[ChampionshipRetrainer] Чемпион сохранён: {model_path}")
            return model_path

        except Exception as e:
            logger.error(f"[ChampionshipRetrainer] Ошибка сохранения чемпиона: {e}")
            return None

    def _update_champion_in_db(self, symbol: str, timeframe: str, val_result: Dict[str, Any]) -> None:
        """Обновляет чемпиона в БД."""
        if self.db_manager is None:
            return

        try:
            session = self.db_manager.Session()
            from src.db.models import TrainedModel

            # Снимаем чемпионство со всех текущих
            (
                session.query(TrainedModel)
                .filter_by(symbol=symbol, timeframe=self._timeframe_to_int(timeframe))
                .update({"is_champion": False})
            )
            session.commit()

            logger.info(f"[ChampionshipRetrainer] DB: старое чемпионство снято для {symbol}")
        except Exception as e:
            logger.warning(f"[ChampionshipRetrainer] Ошибка обновления чемпиона в DB: {e}")
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _trigger_hot_reload(self, symbol: str) -> None:
        """Запускает hot-reload модели."""
        try:
            from src.core.model_loader import get_model_loader

            loader = get_model_loader()
            if loader:
                loader.clear_cache()
                loader.reload_active_model()
                logger.info(f"[ChampionshipRetrainer] Hot-reload выполнен для {symbol}")
        except Exception as e:
            logger.warning(f"[ChampionshipRetrainer] Hot-reload не выполнен: {e}")

    def _timeframe_to_int(self, timeframe: str) -> int:
        """Преобразует строку таймфрейма в MT5 константу."""
        tf_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769}
        return tf_map.get(timeframe, 16385)

    def __repr__(self) -> str:
        return (
            f"ChampionshipRetrainer("
            f"min_wr={self.min_val_accuracy}, "
            f"min_sharpe={self.min_sharpe}, "
            f"max_dd={self.max_drawdown})"
        )
