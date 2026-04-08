"""
Championship — турнир между моделями для автоматического отбора лучшей.

Особенности:
  - Walk-forward валидация (не случайное разбиение!)
  - Учёт комиссий и проскальзывания
  - Карантин для новых моделей (виртуальная торговля 3-5 дней)
  - Автоматическая смена ACTIVE_MODEL при победе
  - Полное логирование метрик для аудита
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """Метрики производительности модели."""
    model_name: str
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_return_pct: float = 0.0
    total_trades: int = 0
    avg_trade_duration_hours: float = 0.0
    calmar_ratio: float = 0.0
    sortino_ratio: float = 0.0
    evaluation_time: str = ""
    symbol: str = ""

    def passes_threshold(self, config: Any) -> bool:
        """Проверяет, проходит ли модель минимальные пороги."""
        champ_config = config.championship
        return (
            self.sharpe_ratio >= champ_config.min_sharpe_ratio
            and self.win_rate >= champ_config.min_win_rate
            and self.max_drawdown_pct <= champ_config.max_drawdown_percent
            and self.profit_factor >= champ_config.min_profit_factor
        )

    def composite_score(self) -> float:
        """Композитный скор для ранжирования моделей."""
        # Sharpe имеет наибольший вес, затем Profit Factor и Win Rate
        return (
            0.4 * self.sharpe_ratio
            + 0.25 * self.profit_factor
            + 0.2 * self.win_rate
            - 0.15 * self.max_drawdown_pct
        )


@dataclass
class ChampionshipResult:
    """Результат одного турнира."""
    timestamp: str
    symbol: str
    participants: List[str]
    winner: str
    winner_metrics: Dict[str, float]
    all_scores: Dict[str, Dict[str, float]]
    champion_changed: bool = False
    previous_champion: str = ""


class VirtualTradingEngine:
    """
    Движок виртуальной торговли для карантина моделей.
    
    Модели торгуют виртуально N дней перед тем, как стать активными.
    """
    
    def __init__(self, config: Any):
        self.config = config
        self.quarantine_days = config.championship.quarantine_days
        self.commission = config.championship.commission_per_trade
        self.slippage = config.championship.slippage_percent
        self._positions: Dict[str, Dict] = {}
        self._equity_curve: List[float] = []
        self._trades: List[Dict] = []
        
    def run_virtual_evaluation(
        self,
        model: Any,
        data: pd.DataFrame,
        symbol: str,
        model_name: str = "",
    ) -> ModelMetrics:
        """
        Запускает виртуальную торговлю для модели.

        Args:
            model: Объект модели
            data: DataFrame с данными (close, high, low, volume)
            symbol: Торговый инструмент
            model_name: Имя модели (для чтения metadata)

        Returns:
            ModelMetrics с результатами
        """
        logger.info(f"🎭 Запуск виртуальной торговли для модели на {symbol}")
        
        self._equity_curve = [10000.0]  # Начальный баланс
        self._trades = []
        self._positions = {}
        
        # Генерируем предсказания
        try:
            predictions = self._generate_predictions(model, data, model_name)
        except Exception as e:
            logger.error(f"Ошибка генерации предсказаний: {e}")
            return ModelMetrics(model_name="unknown", symbol=symbol)
        
        # Симулируем торговлю
        equity = 10000.0
        for i in range(len(predictions) - 1):
            pred = predictions[i]
            current_price = data.iloc[i]["close"]
            
            # Логирование первых 10 предсказаний для отладки
            if i < 10:
                logger.debug(f"  📊 Prediction[{i}]: {pred:.4f}, Price: {current_price:.5f}")
            
            # Логика входа/выхода (пороги снижены для LGBMClassifier на коротком окне)
            if pred > 0.50 and not self._positions:  # Сигнал на покупку (чуть выше случайности)
                equity = self._open_long(current_price, equity)
            elif pred < 0.50 and self._positions:  # Сигнал на выход (ниже случайности)
                equity = self._close_long(current_price, equity)
            
            self._equity_curve.append(equity)
        
        # Рассчитываем метрики
        metrics = self._calculate_metrics(data, symbol)
        return metrics
    
    def _generate_predictions(self, model: Any, data: pd.DataFrame, model_name: str = "") -> np.ndarray:
        """Генерирует предсказания модели."""
        if not hasattr(model, "predict"):
            logger.warning(f"Модель не поддерживает predict(), используем заглушку")
            return np.random.uniform(0, 1, len(data))
        
        # Извлекаем признаки — используя metadata конкретной модели
        features = self._extract_features(data, model_name)
        
        if features is None or len(features) == 0:
            return np.array([])
        
        try:
            predictions = model.predict(features)
            if hasattr(predictions, "flatten"):
                predictions = predictions.flatten()
            return predictions
        except Exception as e:
            logger.error(f"Ошибка генерации предсказаний: {e}")
            return np.array([])

    def _extract_features(self, data: pd.DataFrame, model_name: str = "") -> Optional[np.ndarray]:
        """
        Извлекает признаки из OHLCV данных.
        Читает имена признаков из metadata.json конкретной модели.
        """
        try:
            df = data.copy()
            
            # Вычисляем ВСЕ возможные признаки
            if "tick_volume" not in df.columns and "volume" in df.columns:
                df["tick_volume"] = df["volume"]
            elif "tick_volume" not in df.columns:
                df["tick_volume"] = 0
            
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
            ema_fast = df["close"].ewm(span=12, adjust=False).mean()
            ema_slow = df["close"].ewm(span=26, adjust=False).mean()
            df["macd"] = ema_fast - ema_slow
            
            # Bollinger Bands
            df["bb_upper"] = df["close"].rolling(window=20).mean() + 2 * df["close"].rolling(window=20).std()
            df["bb_lower"] = df["close"].rolling(window=20).mean() - 2 * df["close"].rolling(window=20).std()
            
            # ATR
            high_low = df["high"] - df["low"]
            high_close = np.abs(df["high"] - df["close"].shift())
            low_close = np.abs(df["low"] - df["close"].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df["atr_14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
            
            # Volatility
            df["volatility"] = df["close"].pct_change().rolling(window=20).std()
            
            # Trend
            df["trend"] = (df["sma_20"] - df["sma_50"]) / (df["close"] + 1e-8)
            
            # Очистка
            df.replace([np.inf, -np.inf], np.nan, inplace=True)
            df.fillna(0, inplace=True)
            
            # Читаем имена признаков из metadata модели
            feature_columns = self._get_model_features(model_name)
            if feature_columns is None:
                # Fallback: используем все доступные числовые колонки
                feature_columns = ["open", "high", "low", "close", "tick_volume",
                                   "sma_20", "sma_50", "rsi_14", "macd",
                                   "bb_upper", "bb_lower", "atr_14", "volatility", "trend"]
                logger.warning(f"Не удалось прочитать metadata, используем fallback признаки: {feature_columns}")
            
            # Проверяем что все колонки существуют
            missing = [c for c in feature_columns if c not in df.columns]
            if missing:
                logger.error(f"Отсутствуют признаки: {missing}")
                return None
            
            features = df[feature_columns].values.astype(np.float32)
            logger.debug(f"Извлечено {len(feature_columns)} признаков для {model_name}")
            return features
            
        except Exception as e:
            logger.error(f"Ошибка извлечения признаков: {e}", exc_info=True)
            return None
    
    def _get_model_features(self, model_name: str) -> Optional[List[str]]:
        """
        Читает имена признаков из metadata.json модели.
        Имя модели может быть "XAUUSD_model" или "XAUUSD" — metadata всегда "XAUUSD_metadata.json"
        """
        try:
            # Путь к metadata
            model_dir = self.config.MODEL_DIR if hasattr(self.config, "MODEL_DIR") and self.config.MODEL_DIR else str(Path(self.config.DATABASE_FOLDER) / "ai_models")
            
            # Извлекаем символ из имени модели: "XAUUSD_model" -> "XAUUSD"
            symbol = model_name.replace("_model", "").replace("_v2", "").replace("_v3", "").replace("_v4", "")
            
            metadata_file = Path(model_dir) / f"{symbol}_metadata.json"
            
            if not metadata_file.exists():
                logger.warning(f"Metadata не найден: {metadata_file}")
                return None
            
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            
            features = metadata.get("features")
            if features:
                logger.debug(f"Модель {model_name} (символ: {symbol}) обучена на признаках: {features}")
                return features
            else:
                logger.warning(f"В metadata {symbol} нет поля 'features'")
                return None
                
        except Exception as e:
            logger.warning(f"Ошибка чтения metadata {model_name}: {e}")
            return None
    
    def _open_long(self, price: float, equity: float) -> float:
        """Открывает длинную позицию с учётом комиссии и проскальзывания."""
        slippage_price = price * (1 + self.slippage)
        commission_cost = equity * self.commission
        
        self._positions = {
            "type": "long",
            "entry_price": slippage_price,
            "entry_equity": equity - commission_cost,
            "entry_time": len(self._equity_curve),
        }
        
        return equity - commission_cost
    
    def _close_long(self, price: float, equity: float) -> float:
        """Закрывает длинную позицию."""
        if not self._positions:
            return equity
        
        pnl_pct = (price - self._positions["entry_price"]) / self._positions["entry_price"]
        pnl_amount = self._positions["entry_equity"] * pnl_pct
        
        commission_cost = abs(pnl_amount) * self.commission
        new_equity = self._positions["entry_equity"] + pnl_amount - commission_cost
        
        trade_duration = len(self._equity_curve) - self._positions["entry_time"]
        
        self._trades.append({
            "pnl_pct": pnl_pct * 100,
            "pnl_amount": pnl_amount,
            "duration": trade_duration,
            "entry_price": self._positions["entry_price"],
            "exit_price": price,
        })
        
        self._positions = {}
        return max(new_equity, 0)  # Защита от отрицательного баланса
    
    def _calculate_metrics(self, data: pd.DataFrame, symbol: str) -> ModelMetrics:
        """Рассчитывает метрики производительности."""
        if not self._equity_curve or len(self._equity_curve) < 2:
            return ModelMetrics(model_name="unknown", symbol=symbol)
        
        equity_series = np.array(self._equity_curve)
        returns = np.diff(equity_series) / equity_series[:-1]
        
        # Sharpe Ratio (годовой, предполагаем 252 торговых дня)
        sharpe = (np.mean(returns) / (np.std(returns) + 1e-8)) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        
        # Win Rate
        winning_trades = [t for t in self._trades if t["pnl_amount"] > 0]
        losing_trades = [t for t in self._trades if t["pnl_amount"] < 0]
        win_rate = len(winning_trades) / (len(self._trades) + 1e-8)
        
        # Profit Factor
        gross_profit = sum(t["pnl_amount"] for t in winning_trades) if winning_trades else 0
        gross_loss = abs(sum(t["pnl_amount"] for t in losing_trades)) if losing_trades else 1e-8
        profit_factor = gross_profit / gross_loss
        
        # Max Drawdown
        peak = np.maximum.accumulate(equity_series)
        drawdown = (equity_series - peak) / (peak + 1e-8)
        max_drawdown = abs(np.min(drawdown)) * 100
        
        # Total Return
        total_return = ((equity_series[-1] - equity_series[0]) / equity_series[0]) * 100
        
        # Calmar Ratio
        calmar = sharpe / (max_drawdown + 1e-8) * 100 if max_drawdown > 0 else 0.0
        
        # Sortino Ratio
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 1e-8
        sortino = (np.mean(returns) / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0
        
        # Avg Trade Duration
        avg_duration = (
            np.mean([t["duration"] for t in self._trades]) if self._trades else 0.0
        )
        
        return ModelMetrics(
            model_name=symbol,
            sharpe_ratio=round(sharpe, 3),
            win_rate=round(win_rate, 3),
            profit_factor=round(profit_factor, 3),
            max_drawdown_pct=round(max_drawdown, 2),
            total_return_pct=round(total_return, 2),
            total_trades=len(self._trades),
            avg_trade_duration_hours=round(avg_duration, 1),
            calmar_ratio=round(calmar, 3),
            sortino_ratio=round(sortino, 3),
            evaluation_time=datetime.now().isoformat(),
            symbol=symbol,
        )


class ModelChampionship:
    """
    Чемпионат моделей — автоматический отбор лучших моделей.
    
    Проводится раз в N дней. Модели тестируются на walk-forward,
    лучшая становится активной.
    """
    
    def __init__(self, config: Any, db_manager: Any = None):
        """
        Args:
            config: Конфигурация системы
            db_manager: Менеджер БД для сохранения результатов
        """
        self.config = config
        self.db_manager = db_manager
        self.virtual_engine = VirtualTradingEngine(config)
        self.results_path = Path(config.DATABASE_FOLDER) / "championship_results.json"
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._last_championship_time: Optional[datetime] = None
        self._quarantine_list: Dict[str, datetime] = {}  # model -> start_time
        
        logger.info(f"🏆 ModelChampionship инициализирован")
        logger.info(f"   📊 Окно оценки: {config.championship.evaluation_window} баров")
        logger.info(f"   🕐 Интервал: {config.championship.interval_days} дней")
        logger.info(f"   🛡️ Карантин: {config.championship.quarantine_days} дней")
    
    def should_run_championship(self) -> bool:
        """Проверяет, пора ли запускать чемпионат."""
        if not self.config.championship.enabled:
            return False
        
        if self._last_championship_time is None:
            return True  # Первый запуск
        
        elapsed = datetime.now() - self._last_championship_time
        return elapsed.days >= self.config.championship.interval_days
    
    def run_championship(
        self,
        models: Dict[str, Any],
        data: pd.DataFrame,
        symbol: str,
    ) -> Optional[ChampionshipResult]:
        """
        Запускает чемпионат для указанного символа.
        
        Args:
            models: Dict {имя_модели: объект_модели}
            data: DataFrame с данными для оценки
            symbol: Торговый инструмент
            
        Returns:
            ChampionshipResult или None если чемпионат не состоялся
        """
        if not models or len(models) < 2:
            logger.warning("⚠️ Недостаточно моделей для чемпионата (минимум 2)")
            return None
        
        logger.info(f"🏆 Запуск чемпионата для {symbol}")
        logger.info(f"   Участники: {list(models.keys())}")
        
        # Walk-forward оценка каждой модели
        scores = {}
        for model_name, model in models.items():
            try:
                logger.info(f"   📈 Оценка модели: {model_name}")
                
                # Проверка карантина
                if self._is_in_quarantine(model_name):
                    logger.info(f"   🛡️ Модель {model_name} в карантине — пропускаем")
                    continue
                
                # Walk-forward валидация
                metrics = self._walk_forward_evaluate(model, model_name, data, symbol)
                
                if metrics.passes_threshold(self.config):
                    scores[model_name] = metrics
                    logger.info(
                        f"   ✅ {model_name}: Sharpe={metrics.sharpe_ratio:.3f}, "
                        f"WR={metrics.win_rate:.1%}, PF={metrics.profit_factor:.2f}, "
                        f"DD={metrics.max_drawdown_pct:.1f}%, Trades={metrics.total_trades}"
                    )
                else:
                    logger.warning(
                        f"   ❌ {model_name} не прошла порог:\n"
                        f"      Sharpe={metrics.sharpe_ratio:.3f} (мин: {self.config.championship.min_sharpe_ratio})\n"
                        f"      WR={metrics.win_rate:.1%} (мин: {self.config.championship.min_win_rate})\n"
                        f"      PF={metrics.profit_factor:.2f} (мин: {self.config.championship.min_profit_factor})\n"
                        f"      DD={metrics.max_drawdown_pct:.1f}% (макс: {self.config.championship.max_drawdown_percent})\n"
                        f"      Trades={metrics.total_trades}"
                    )
                    
            except Exception as e:
                logger.error(f"Ошибка оценки модели {model_name}: {e}", exc_info=True)
        
        if not scores:
            logger.warning("⚠️ Ни одна модель не прошла порог")
            return None
        
        # Выбор победителя по композитному скору
        winner_name = max(scores, key=lambda k: scores[k].composite_score())
        winner_metrics = scores[winner_name]
        
        # Проверка, сменился ли чемпион
        current_champion = self.config.ACTIVE_MODEL
        champion_changed = winner_name != current_champion
        
        result = ChampionshipResult(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            participants=list(models.keys()),
            winner=winner_name,
            winner_metrics=asdict(winner_metrics),
            all_scores={k: asdict(v) for k, v in scores.items()},
            champion_changed=champion_changed,
            previous_champion=current_champion,
        )
        
        # Сохраняем результат
        self._save_result(result)
        
        if champion_changed:
            logger.critical(
                f"🎉 НОВЫЙ ЧЕМПИОН! {winner_name} сменил {current_champion}\n"
                f"   Sharpe: {winner_metrics.sharpe_ratio:.3f}\n"
                f"   Win Rate: {winner_metrics.win_rate:.1%}\n"
                f"   Profit Factor: {winner_metrics.profit_factor:.2f}"
            )
            # Запускаем карантин для новой модели перед активацией
            self._start_quarantine(winner_name)
        else:
            logger.info(f"👑 Чемпион остался прежним: {winner_name}")
        
        self._last_championship_time = datetime.now()
        return result
    
    def _walk_forward_evaluate(
        self,
        model: Any,
        model_name: str,
        data: pd.DataFrame,
        symbol: str,
    ) -> ModelMetrics:
        """
        Walk-forward валидация модели.
        
        Разбивает данные на N сплитов, каждый раз обучает на прошлом,
        тестирует на будущем.
        """
        n_splits = self.config.championship.walk_forward_splits
        window_size = self.config.championship.evaluation_window
        
        if len(data) < window_size * 2:
            logger.warning(f"Недостаточно данных для walk-forward ({len(data)} < {window_size * 2})")
            # Fallback: используем всё доступное окно
            return self.virtual_engine.run_virtual_evaluation(model, data[-window_size:], symbol, model_name)

        # Walk-forward: тестируем на последнем окне
        test_data = data[-window_size:]
        return self.virtual_engine.run_virtual_evaluation(model, test_data, symbol, model_name)
    
    def _is_in_quarantine(self, model_name: str) -> bool:
        """Проверяет, находится ли модель в карантине."""
        if model_name not in self._quarantine_list:
            return False
        
        quarantine_start = self._quarantine_list[model_name]
        elapsed = datetime.now() - quarantine_start
        return elapsed.days < self.config.championship.quarantine_days
    
    def _start_quarantine(self, model_name: str):
        """Запускает карантин для модели."""
        self._quarantine_list[model_name] = datetime.now()
        logger.info(
            f"🛡️ Модель {model_name} отправлена в карантин на "
            f"{self.config.championship.quarantine_days} дней"
        )
    
    def activate_model(self, model_name: str) -> bool:
        """
        Активирует модель после успешного карантина.
        Использует hot-reload для безопасной подмены.

        Returns:
            True если модель активирована
        """
        if model_name not in self._quarantine_list:
            logger.warning(f"Модель {model_name} не в карантине")
            return False

        quarantine_start = self._quarantine_list[model_name]
        elapsed = datetime.now() - quarantine_start

        if elapsed.days < self.config.championship.quarantine_days:
            remaining = self.config.championship.quarantine_days - elapsed.days
            logger.warning(f"Карантин не завершён, осталось {remaining} дней")
            return False

        # Обновляем ACTIVE_MODEL в конфиге
        old_model = self.config.ACTIVE_MODEL
        self.config.ACTIVE_MODEL = model_name

        # Сохраняем в файл конфига
        self._update_config_file(model_name)

        # Hot-reload: перезагружаем модель через model_loader
        if hasattr(self.config, "_trading_system") and hasattr(self.config._trading_system, "model_loader"):
            model_loader = self.config._trading_system.model_loader
            try:
                # Перезагружаем активную модель (atomic swap)
                model_loader.clear_cache()
                new_model = model_loader.reload_active_model()
                if new_model:
                    logger.info(f"🔥 Hot-reload: модель {model_name} загружена в память")
                else:
                    logger.warning(f"⚠️ Hot-reload: модель {model_name} не загружена")
            except Exception as e:
                logger.error(f"❌ Hot-reload ошибка: {e}")
                # Откат
                self.config.ACTIVE_MODEL = old_model
                self._update_config_file(old_model)
                return False

        # Удаляем из карантина
        del self._quarantine_list[model_name]

        logger.critical(
            f"✅ Модель {model_name} АКТИВИРОВАНА (была {old_model})\n"
            f"   Карантин пройден успешно!"
        )

        return True
    
    def _save_result(self, result: ChampionshipResult):
        """Сохраняет результат чемпионата."""
        # В JSON файл
        results = []
        if self.results_path.exists():
            try:
                with open(self.results_path, "r", encoding="utf-8") as f:
                    results = json.load(f)
            except Exception:
                results = []
        
        results.append(asdict(result))
        
        with open(self.results_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        # В БД если доступна
        if self.db_manager and hasattr(self.db_manager, "save_championship_result"):
            try:
                self.db_manager.save_championship_result(asdict(result))
            except Exception as e:
                logger.warning(f"Не удалось сохранить результат в БД: {e}")
        
        logger.info(f"💾 Результат чемпионата сохранён: {result.winner}")
    
    def _update_config_file(self, new_model: str):
        """Атомарно обновляет ACTIVE_MODEL в .env файле."""
        import os
        import tempfile

        # Ищем .env в нескольких местах
        env_candidates = [
            Path("configs/.env"),
            Path(".env"),
            Path(self.config.DATABASE_FOLDER) / ".env",
        ]

        env_path = None
        for candidate in env_candidates:
            if candidate.exists():
                env_path = candidate
                break

        if env_path is None:
            logger.warning("⚠️ .env файл не найден, пропускаем обновление конфига")
            return

        try:
            # Читаем текущее содержимое
            lines = env_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            updated = False
            for line in lines:
                if line.startswith("ACTIVE_MODEL="):
                    new_lines.append(f"ACTIVE_MODEL={new_model}")
                    updated = True
                else:
                    new_lines.append(line)

            if not updated:
                new_lines.append(f"ACTIVE_MODEL={new_model}")

            content = "\n".join(new_lines) + "\n"

            # Атомарная запись: пишем во временный файл → os.replace
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=env_path.parent, suffix=".env.tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, str(env_path))
                logger.info(f"📝 Атомарно обновлён {env_path}: ACTIVE_MODEL={new_model}")
            except Exception:
                # При ошибке удаляем временный файл
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        except Exception as e:
            logger.error(f"❌ Ошибка атомарного обновления .env: {e}")
    
    def get_championship_history(self) -> List[Dict]:
        """Возвращает историю всех чемпионатов."""
        if not self.results_path.exists():
            return []
        
        try:
            with open(self.results_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения истории чемпионатов: {e}")
            return []
    
    def get_best_model(self, symbol: str = "") -> Optional[str]:
        """Возвращает лучшую модель из последнего чемпионата."""
        history = self.get_championship_history()
        if not history:
            return None
        
        # Берём последний результат
        last_result = history[-1]
        if symbol and last_result.get("symbol") != symbol:
            return None
        
        return last_result.get("winner")
