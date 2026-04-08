# src/core/services/signal_service.py
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import shap
import torch
import torch.nn as nn

try:
    import lightgbm as lgb
except ImportError:
    lgb = None
from shap import KernelExplainer

from src.analysis.market_regime_manager import MarketRegimeManager
from src.core.config_models import Settings
from src.data_models import SignalType, TradeSignal
from src.ml.consensus_engine import ConsensusEngine, ConsensusResult
from src.strategies.StrategyInterface import BaseStrategy

logger = logging.getLogger(__name__)


class SignalService:
    def __init__(
        self,
        config: Settings,
        market_regime_manager: MarketRegimeManager,
        strategies: List[BaseStrategy],
        models: Dict,
        x_scalers: Dict,
        y_scalers: Dict,
        strategy_performance: Dict,
        consensus_engine: ConsensusEngine,
        trading_system_ref: Any,
    ):
        self.config = config
        self.market_regime_manager = market_regime_manager
        self.strategies = strategies
        self.models = models
        self.x_scalers = x_scalers
        self.y_scalers = y_scalers
        self.strategy_performance = strategy_performance
        self.consensus_engine = consensus_engine
        self.n_steps = self.config.INPUT_LAYER_SIZE
        self.trading_system = trading_system_ref

    def _create_sequences_for_shap(self, data: np.ndarray, n_steps: int) -> Optional[np.ndarray]:
        """Создает набор последовательностей для фонового датасета SHAP."""
        X = []
        if len(data) < n_steps + 1:
            return None
        for i in range(len(data) - n_steps + 1):
            X.append(data[i : (i + n_steps)])
        return np.array(X)

    # --- НОВЫЙ МЕТОД: Сбор сигналов от классических стратегий ---
    def _get_classic_signals(
        self, df: pd.DataFrame, timeframe: int, market_regime: str, symbol: str = None
    ) -> List[TradeSignal]:
        """Собирает сигналы от всех классических стратегий, релевантных режиму."""
        signals = []
        if not self.strategies:
            logger.warning("CLASSIC SIGNALS: Нет загруженных стратегий!")
            return signals

        logger.info(f"CLASSIC SIGNALS: Режим рынка '{market_regime}', проверяем {len(self.strategies)} стратегий")

        for strategy in self.strategies:
            strategy_name = strategy.__class__.__name__

            # Проверяем, что стратегия релевантна режиму (или является базовой)
            is_relevant = (
                self.config.STRATEGY_REGIME_MAPPING.get(market_regime) == strategy_name
                or self.config.STRATEGY_REGIME_MAPPING.get("Default") == strategy_name
            )

            logger.debug(f"CLASSIC SIGNALS: Стратегия {strategy_name}, релевантна={is_relevant}")

            if is_relevant:
                signal = strategy.check_entry_conditions(df, len(df) - 1, timeframe, symbol)
                logger.info(
                    f"CLASSIC SIGNALS: {strategy_name}.check_entry_conditions() returned signal type={signal.type if signal else None}"
                )
                if signal and signal.type != SignalType.HOLD:
                    signals.append(signal)
                    # Исправление: type может быть строкой или SignalType
                    signal_type_name = (
                        signal.type
                        if isinstance(signal.type, str)
                        else (signal.type.name if hasattr(signal.type, "name") else str(signal.type))
                    )
                    logger.info(f"CLASSIC SIGNALS: Добавлен сигнал от {strategy_name}: {signal_type_name}")

        logger.info(f"CLASSIC SIGNALS: Собрано {len(signals)} сигналов")
        return signals

    # --- НОВЫЙ МЕТОД: Вычисление On-Chain Score (Делегирование) ---
    def _get_on_chain_score(self, df: pd.DataFrame) -> float:
        """
        Вычисляет унифицированный скор On-Chain данных, делегируя логику ConsensusEngine.
        """
        return self.consensus_engine.calculate_on_chain_score(df)

    def get_trade_signal(
        self, symbol: str, df: pd.DataFrame, timeframe: int, consensus_result: ConsensusResult
    ) -> Optional[Tuple[TradeSignal, str, Optional[Dict], Optional[np.ndarray], Optional[float]]]:
        """
        Основной метод сервиса. Анализирует символ и возвращает кортеж с финальным сигналом и метаданными.
        """
        if df is None or df.empty:
            logger.warning(f"[{symbol}] DataFrame пуст или None")
            return None

        # 1. Проверка на блокировку по важным новостям (из графа знаний)
        important_entities = self.config.IMPORTANT_NEWS_ENTITIES
        is_important_news_active = False
        if consensus_result and consensus_result.relations:
            for rel in consensus_result.relations:
                subj = rel.get("subject", "").upper()
                obj = rel.get("object", "").upper()
                if any(entity in subj for entity in important_entities) or any(entity in obj for entity in important_entities):
                    is_important_news_active = True
                    logger.warning(
                        f"[{symbol}] Обнаружена важная новость: {subj} -> {rel.get('relation')} -> {obj}. Сделки блокированы."
                    )
                    break

        if is_important_news_active:
            return None

        # 2. Определяем режим рынка.
        market_regime = self.market_regime_manager.get_regime(df)
        logger.info(f"[{symbol}] get_trade_signal: market_regime={market_regime}")
        primary_strategy_name = self.config.STRATEGY_REGIME_MAPPING.get(
            market_regime, self.config.STRATEGY_REGIME_MAPPING.get("Default", "AI_Model")
        )
        logger.info(f"[{symbol}] get_trade_signal: primary_strategy_name={primary_strategy_name}")

        # 3. Пробуем получить сигнал от основной (режимной) стратегии
        if primary_strategy_name != "AI_Model":
            logger.info(f"[{symbol}] Попытка получить сигнал от классической стратегии: {primary_strategy_name}")
            primary_signal, primary_name, _, primary_pred_input, primary_entry_price = self.get_primary_signal(
                symbol, df, timeframe, market_regime
            )
            logger.info(
                f"[{symbol}] get_primary_signal вернул: signal={primary_signal}, name={primary_name}, type={type(primary_signal)}"
            )

            # Исправление: проверяем тип signal.type (может быть строкой или SignalType)
            if primary_signal:
                # Если type это строка, сравниваем напрямую
                signal_type = primary_signal.type
                if isinstance(signal_type, str):
                    is_hold = signal_type == "HOLD"
                    type_name = signal_type
                else:
                    # Если type это SignalType enum
                    is_hold = signal_type == SignalType.HOLD
                    type_name = signal_type.name if hasattr(signal_type, "name") else str(signal_type)

                if not is_hold:
                    logger.info(f"[{symbol}] Получен сигнал от primary стратегии: {type_name}")
                confirmed_signal, confirmed_strategy_name, _ = self.get_confirmed_signal(
                    symbol, df, timeframe, primary_signal, primary_name, None
                )
                if confirmed_signal:
                    logger.info(f"[{symbol}] Используется классическая стратегия: {confirmed_strategy_name}")
                    return confirmed_signal, confirmed_strategy_name, None, primary_pred_input, primary_entry_price
        else:
            logger.info(f"[{symbol}] primary_strategy_name==AI_Model, пропускаем классическую стратегию")

        # 4. Если классика не дала рабочий сигнал, идём по AI + консенсус
        logger.info(f"[{symbol}] Классические стратегии не дали сигнала, переходим на AI+консенсус")
        ai_signal, pred_input, entry_price = self._get_ai_signal(symbol, df)
        logger.info(f"[{symbol}] _get_ai_signal вернул: signal={ai_signal}")

        # 5. Собираем все факторы для Консенсуса
        classic_signals = self._get_classic_signals(df, timeframe, market_regime, symbol)

        # Если нет AI-сигнала — используем классические стратегии напрямую
        if not ai_signal or ai_signal.type == SignalType.HOLD:
            logger.info(f"[{symbol}] AI-сигнал: {ai_signal}. Классических сигналов: {len(classic_signals)}")
            if not classic_signals:
                logger.info(f"[{symbol}] Нет классических сигналов и AI не дал сигнала. Возврат None.")
                return None
            classic_signal = classic_signals[0]
            strategy_name = classic_signal.__class__.__name__ if hasattr(classic_signal, "__class__") else "ClassicStrategy"
            entry_price = float(df["close"].iloc[-1]) if "close" in df.columns else None
            logger.info(f"[{symbol}] AI-модель недоступна. Торговля по классической стратегии: {market_regime}")
            return classic_signal, f"Classic_{market_regime}", None, None, entry_price

        # 4.2. Сентимент KG
        kg_sentiment_score = self.consensus_engine.get_historical_context_sentiment(symbol, market_regime) or 0.0

        # 4.3. On-Chain Score
        is_crypto = self.config.asset_types.get(symbol) == "CRYPTO"
        # --- ИЗМЕНЕНИЕ: Вычисляем On-Chain Score через ConsensusEngine ---
        on_chain_score = self._get_on_chain_score(df) if is_crypto else 0.0
        # -----------------------------------------------------------------

        # 5. Расчет Многофакторного Консенсуса
        final_signal_type, final_score = self.consensus_engine.calculate_multifactor_consensus(
            ai_signal=ai_signal,
            classic_signals=classic_signals,
            kg_sentiment_score=kg_sentiment_score,
            on_chain_score=on_chain_score,
            is_crypto=is_crypto,
        )

        # === AI-ONLY FALLBACK ===
        # Если консенсус не достигнут и классика молчит — проверяем AI уверенность
        if final_signal_type == SignalType.HOLD:
            no_classic = len(classic_signals) == 0

            # AI-ONLY: когда классика молчит + AI уверен на 20%+ → пропускаем AI сигнал
            if no_classic and ai_signal and ai_signal.confidence >= 0.2:
                logger.info(
                    f"[{symbol}] AI-ONLY FALLBACK: AI confidence={ai_signal.confidence:.2f} ≥ 0.2, "
                    f"классика молчит → пропускаем AI сигнал"
                )
                final_signal_type = ai_signal.type
                final_score = ai_signal.confidence * 0.7  # Слегка штрафован
            # Если есть сильные классические сигналы, используем их
            elif classic_signals:
                buy_count = sum(1 for s in classic_signals if s.type == SignalType.BUY)
                sell_count = sum(1 for s in classic_signals if s.type == SignalType.SELL)
                total = len(classic_signals)

                if buy_count >= total * 0.7:
                    logger.critical(
                        f"[{symbol}] КОНСЕНСУС не достигнут, но КЛАССИЧЕСКИЕ стратегии голосуют за BUY ({buy_count}/{total})"
                    )
                    return (
                        classic_signals[0],
                        f"Classic_Consensus ({buy_count}/{total})",
                        None,
                        None,
                        float(df["close"].iloc[-1]),
                    )
                elif sell_count >= total * 0.7:
                    logger.critical(
                        f"[{symbol}] КОНСЕНСУС не достигнут, но КЛАССИЧЕСКИЕ стратегии голосуют за SELL ({sell_count}/{total})"
                    )
                    return (
                        classic_signals[0],
                        f"Classic_Consensus ({sell_count}/{total})",
                        None,
                        None,
                        float(df["close"].iloc[-1]),
                    )
                else:
                    # Классика есть но нет единогласия
                    logger.info(f"[{symbol}] Многофакторный консенсус не достигнут (Score: {final_score:.2f}). Сигнал отклонен.")
                    return None
            else:
                # Ни AI, ни классика не дали сигнала
                logger.info(f"[{symbol}] Многофакторный консенсус не достигнут (Score: {final_score:.2f}). Сигнал отклонен.")
                return None

        # 6. Формирование финального сигнала
        # Pydantic требует confidence >= 0.3, поэтому для AI-ONLY fallback поднимаем до минимума
        pydantic_min_confidence = 0.3
        final_signal = TradeSignal(
            type=final_signal_type,
            confidence=max(final_score, pydantic_min_confidence),
            symbol=symbol,
            predicted_price=ai_signal.predicted_price,
        )
        final_strategy_name = f"AI_MF_Consensus"

        # Исправление: type может быть строкой или SignalType
        signal_type_name = (
            final_signal.type
            if isinstance(final_signal.type, str)
            else (final_signal.type.name if hasattr(final_signal.type, "name") else str(final_signal.type))
        )
        logger.critical(f"[{symbol}] ФИНАЛЬНЫЙ СИГНАЛ: {signal_type_name} (Score: {final_score:.2f})")

        return final_signal, final_strategy_name, None, pred_input, entry_price

    def get_primary_signal(
        self, symbol: str, df: pd.DataFrame, timeframe: int, market_regime: str
    ) -> Tuple[Optional[TradeSignal], Optional[str], Optional[Dict], Optional[np.ndarray], Optional[float]]:
        market_regime = self.market_regime_manager.get_regime(df)
        primary_strategy_name = self.config.STRATEGY_REGIME_MAPPING.get(
            market_regime, self.config.STRATEGY_REGIME_MAPPING.get("Default", "AI_Model")
        )
        logger.info(f"[{symbol}] Режим рынка: {market_regime}. Выбрана основная стратегия: '{primary_strategy_name}'")

        primary_strategy_instance = next((s for s in self.strategies if s.__class__.__name__ == primary_strategy_name), None)

        if (not primary_strategy_instance and primary_strategy_name != "AI_Model") or (
            primary_strategy_name == "AI_Model" and (symbol not in self.models or not self.models[symbol])
        ):
            fallback_strategy_name = "MovingAverageCrossoverStrategy"
            logger.warning(f"[{symbol}] Стратегия '{primary_strategy_name}' недоступна. Фолбэк к '{fallback_strategy_name}'.")
            primary_strategy_name = fallback_strategy_name
            primary_strategy_instance = next(
                (s for s in self.strategies if s.__class__.__name__ == fallback_strategy_name), None
            )

        if primary_strategy_name == "AI_Model":
            signal, pred_input, entry_price = self._get_ai_signal(symbol, df)
            return signal, "AI_Model", None, pred_input, entry_price
        elif primary_strategy_instance:
            signal = primary_strategy_instance.check_entry_conditions(df, len(df) - 1, timeframe, symbol)
            return signal, primary_strategy_name, None, None, None

        return None, None, None, None, None

    def get_confirmed_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
        timeframe: int,
        primary_signal: TradeSignal,
        primary_strategy: str,
        xai_data: Optional[Dict],
    ) -> Tuple[Optional[TradeSignal], str, Optional[Dict]]:
        market_regime = self.market_regime_manager.get_regime(df)

        # Вспомогательная функция для получения имени типа сигнала
        def get_signal_type_name(sig):
            if sig.type is None:
                return "UNKNOWN"
            if isinstance(sig.type, str):
                return sig.type
            return sig.type.name if hasattr(sig.type, "name") else str(sig.type)

        if primary_strategy == "AI_Model":
            confirming_strategy, best_score = self._find_best_confirming_strategy(primary_signal, df, market_regime, timeframe)
            if confirming_strategy:
                final_strategy_name = f"AI_Model_Confirmed_by_{confirming_strategy.__class__.__name__}"
                signal_type_name = get_signal_type_name(primary_signal)
                logger.info(
                    f"[{symbol}] AI-сигнал ({signal_type_name}) ПОДТВЕРЖДЕН '{confirming_strategy.__class__.__name__}' (Score: {best_score:.2f})."
                )
                return primary_signal, final_strategy_name, xai_data
            else:
                signal_type_name = get_signal_type_name(primary_signal)
                logger.info(f"[{symbol}] AI-сигнал ({signal_type_name}) НЕ ПОДТВЕРЖДЕН. Сигнал отклонен.")
                return None, primary_strategy, None
        else:
            confirming_signal, _, _ = self._get_ai_signal(symbol, df)
            # Сравниваем типы сигналов (может быть строкой или SignalType)
            primary_type = primary_signal.type
            confirming_type = confirming_signal.type if confirming_signal else None

            types_match = False
            if confirming_type is not None:
                if isinstance(primary_type, str) and isinstance(confirming_type, str):
                    types_match = primary_type == confirming_type
                elif hasattr(primary_type, "name") and hasattr(confirming_type, "name"):
                    types_match = primary_type == confirming_type
                else:
                    types_match = str(primary_type) == str(confirming_type)

            if confirming_signal and types_match:
                final_strategy_name = f"{primary_strategy}_Confirmed_by_AI"
                signal_type_name = get_signal_type_name(primary_signal)
                logger.info(f"[{symbol}] Сигнал '{primary_strategy}' ({signal_type_name}) ПОДТВЕРЖДЕН AI.")
                return primary_signal, final_strategy_name, xai_data
            else:
                signal_type_name = get_signal_type_name(primary_signal)
                logger.info(
                    f"[{symbol}] Сигнал '{primary_strategy}' ({signal_type_name}) НЕ подтвержден AI, но будет исполнен."
                )
                return primary_signal, primary_strategy, xai_data

    def _get_ai_signal(
        self, symbol: str, df: pd.DataFrame
    ) -> Tuple[Optional[TradeSignal], Optional[np.ndarray], Optional[float]]:

        logger.info(f"[{symbol}] _get_ai_signal: checking models...")

        if symbol not in self.models or not self.models[symbol]:
            logger.warning(f"[{symbol}] _get_ai_signal: модели отсутствуют в self.models")
            return None, None, None

        champion_committee = self.models.get(symbol, {})
        logger.info(
            f"[{symbol}] _get_ai_signal: champion_committee has {len(champion_committee)} models: {list(champion_committee.keys())}"
        )

        if not champion_committee:
            return None, None, None

        # === НОВЫЙ ПОДХОД: каждая модель предсказывает отдельно ===
        model_predictions = []
        model_confidences = []
        
        for model_type, model_data in champion_committee.items():
            try:
                pred, conf = self._predict_single_model(symbol, model_type, model_data, df)
                if pred is not None and conf is not None:
                    model_predictions.append(pred)
                    model_confidences.append(conf)
                    logger.debug(f"[{symbol}] {model_type}: pred={pred:.4f}, conf={conf:.4f}")
                else:
                    logger.warning(f"[{symbol}] {model_type}: не удалось получить предсказание")
            except Exception as e:
                logger.error(f"[{symbol}] Ошибка предсказания {model_type}: {e}")
        
        if not model_predictions:
            logger.warning(f"[{symbol}] Все модели не смогли сделать предсказание")
            return None, None, None
        
        # Усредняем предсказания и уверенности
        avg_prediction = float(np.mean(model_predictions))
        avg_confidence = float(np.mean(model_confidences))
        
        logger.info(f"[{symbol}] Усреднено {len(model_predictions)} моделей: pred={avg_prediction:.4f}, conf={avg_confidence:.4f}")
        
        # Определяем тип сигнала
        if avg_prediction > 0.55:
            signal_type = SignalType.BUY
        elif avg_prediction < 0.45:
            signal_type = SignalType.SELL
        else:
            signal_type = None
        
        if signal_type is None:
            return None, None, None

        # Минимальная уверенность — если ниже, не создаём сигнал
        if avg_confidence < 0.15:
            logger.debug(f"[{symbol}] AI уверенность слишком низкая: {avg_confidence:.3f} < 0.15")
            return None, None, None

        # Создаём TradeSignal
        entry_price = float(df["close"].iloc[-1])
        predicted_price = entry_price * (1 + (avg_prediction - 0.5) * 0.01)

        try:
            signal = TradeSignal(
                type=signal_type,
                confidence=max(avg_confidence, 0.15),  # Гарантируем минимум для валидации
                symbol=symbol,
                predicted_price=predicted_price,
            )
            return signal, None, entry_price
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка создания TradeSignal: {e}")
            return None, None, None
    
    def _predict_single_model(
        self, symbol: str, model_type: str, model_data: Dict, df: pd.DataFrame
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Делает предсказание ОДНОЙ модели с её собственными признаками и scaler.
        
        Returns:
            (prediction, confidence) или (None, None) при ошибке
        """
        # 1. Получаем признаки и scaler КОНКРЕТНОЙ модели
        model_features = model_data.get("features", [])
        if not model_features:
            logger.warning(f"[{symbol}] {model_type}: нет списка признаков")
            return None, None
        
        x_scaler = model_data.get("x_scaler") or self.x_scalers.get(symbol)
        y_scaler = model_data.get("y_scaler") or self.y_scalers.get(symbol)
        
        if x_scaler is None:
            logger.warning(f"[{symbol}] {model_type}: нет x_scaler")
            return None, None
        
        # 2. Проверяем размерность
        expected_features = x_scaler.n_features_in_ if hasattr(x_scaler, "n_features_in_") else len(model_features)
        
        if expected_features != len(model_features):
            logger.warning(
                f"[{symbol}] {model_type}: mismatch scaler({expected_features}) vs features({len(model_features)})"
            )
            return None, None
        
        # 3. Гарантируем наличие всех признаков в df
        df_processed = df.copy()
        missing = [f for f in model_features if f not in df_processed.columns]
        if missing:
            for feat in missing:
                df_processed[feat] = 0.0
            logger.debug(f"[{symbol}] {model_type}: добавлены нули для {missing}")
        
        # 4. Берём последние n_steps баров
        last_sequence = df_processed[model_features].tail(self.n_steps)
        if last_sequence.shape[0] < self.n_steps:
            logger.warning(f"[{symbol}] {model_type}: недостаточно данных ({last_sequence.shape[0]} < {self.n_steps})")
            return None, None
        
        last_sequence_raw = last_sequence.values
        
        # Очистка NaN/Inf
        if not np.all(np.isfinite(last_sequence_raw)):
            last_sequence_raw = np.nan_to_num(last_sequence_raw, nan=0.0, posinf=1e9, neginf=-1e9)
        
        # 5. Масштабирование
        try:
            last_sequence_scaled = x_scaler.transform(last_sequence_raw)
        except Exception as e:
            logger.error(f"[{symbol}] {model_type}: ошибка масштабирования: {e}")
            return None, None
        
        # 6. Предсказание
        model = model_data.get("model")
        if model is None:
            logger.warning(f"[{symbol}] {model_type}: модель не найдена")
            return None, None
        
        try:
            if hasattr(model, "predict"):
                # LightGBM / sklearn модели
                if hasattr(model, "n_features_in_"):
                    # Это sklearn/LightGBM модель — нужен только последний бар
                    last_bar = last_sequence_scaled[-1].reshape(1, -1)
                    
                    # КРИТИЧНО: для классификаторов используем predict_proba, а не predict
                    if hasattr(model, "predict_proba"):
                        # Классификатор → вероятности классов
                        proba = model.predict_proba(last_bar)
                        # Берём вероятность класса "1" (рост/BUY)
                        if proba.ndim == 2 and proba.shape[1] >= 2:
                            prediction = float(proba[0, 1])
                        else:
                            prediction = float(proba[0])
                    else:
                        # Регрессор → прямое предсказание
                        prediction_raw = model.predict(last_bar)
                        if hasattr(prediction_raw, "flatten"):
                            prediction_raw = prediction_raw.flatten()
                        prediction = float(prediction_raw[0])
                else:
                    # LSTM / sequence модель — нужна вся последовательность
                    prediction_raw = model.predict(last_sequence_scaled.reshape(1, -1))
                    if hasattr(prediction_raw, "flatten"):
                        prediction_raw = prediction_raw.flatten()
                    prediction = float(prediction_raw[0])
                
                # Clamp prediction to [0, 1] для вероятностей
                prediction = max(0.0, min(1.0, prediction))
            else:
                logger.warning(f"[{symbol}] {model_type}: модель не поддерживает predict()")
                return None, None
        except Exception as e:
            logger.error(f"[{symbol}] {model_type}: ошибка предсказания: {e}")
            return None, None
        
        # 7. Confidence = отклонение от 0.5 (чем дальше, тем увереннее)
        confidence = abs(prediction - 0.5) * 2  # Нормализация 0..1
        confidence = min(max(confidence, 0.01), 1.0)  # Clamp
        
        return prediction, confidence

    def calculate_shap_values(
        self,
        symbol: str,
        prediction_input: np.ndarray,
        df_for_background: pd.DataFrame,
        explainer=None,
        instance_to_explain=None,
        shap_values_dict=None,
    ) -> Optional[Dict]:
        champion_committee = self.models.get(symbol, {})
        x_scaler = self.x_scalers.get(symbol)
        y_scaler = self.y_scalers.get(symbol)
        main_model_key = next(iter(champion_committee), None)

        if not all([champion_committee, x_scaler, y_scaler, main_model_key]):
            return None

        main_model_data = champion_committee[main_model_key]
        main_model = main_model_data.get("model")
        features_to_use = main_model_data.get("features", [])
        # ВРЕМЕННО: НЕ удаляем дубликаты для совместимости со старыми моделями
        # features_to_use = list(dict.fromkeys(features_to_use))

        # --- Получаем устройство из TradingSystem ---
        device = self.trading_system.device if hasattr(self.trading_system, "device") else torch.device("cpu")
        # --------------------------------------------

        if not main_model or not features_to_use:
            return None

        try:
            # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: Гарантированное добавление заглушек ---
            df_background_copy = df_for_background.copy()

            # Проверяем и добавляем заглушки для всех признаков, которые нужны модели
            for feat in features_to_use:
                if feat not in df_background_copy.columns:
                    df_background_copy[feat] = 0.0
                    logger.warning(f"[{symbol}] XAI: Добавлена заглушка для отсутствующего признака: {feat}")
            # --------------------------------------------------------------------------

            if isinstance(main_model, nn.Module):
                # 1. Создаем фоновый набор данных (summary)
                background_data_raw = df_background_copy[features_to_use].tail(100).values
                background_scaled = x_scaler.transform(background_data_raw)

                # KernelExplainer работает с последним временным шагом, поэтому берем срез
                background_summary = shap.kmeans(background_scaled, 10)

                # 2. Создаем функцию-обертку для модели PyTorch
                def predict_fn(x):
                    # x будет иметь форму (n_samples, n_features)
                    n_samples = x.shape[0]
                    n_steps = self.config.INPUT_LAYER_SIZE

                    # Берем `n_steps-1` последних шагов из оригинального `prediction_input`
                    # prediction_input.shape: (1, n_steps, n_features)
                    prefix = np.tile(prediction_input[0, : n_steps - 1, :], (n_samples, 1, 1))

                    # Добавляем `x` как последний шаг
                    x_reshaped = np.concatenate([prefix, x[:, np.newaxis, :]], axis=1)

                    tensor = torch.from_numpy(x_reshaped).float()
                    tensor = tensor.to(device)  # Используем устройство
                    with torch.no_grad():
                        output = main_model(tensor)
                    return output.cpu().numpy()

                # 3. Создаем и используем KernelExplainer
                explainer = shap.KernelExplainer(predict_fn, background_summary)

                # Объясняем только последний временной шаг
                instance_to_explain = prediction_input[0, -1, :].reshape(1, -1)

                # Расчет SHAP values
                shap_values = explainer.shap_values(instance_to_explain, nsamples=50)

                if shap_values is None:
                    logger.error(f"[{symbol}] shap_values вернул None. Пропуск SHAP.")
                    return None

                # Обработка результатов
                shap_values_dict = {feature: value for feature, value in zip(features_to_use, shap_values[0])}

                base_value_scaled = explainer.expected_value
                if isinstance(base_value_scaled, np.ndarray):
                    base_value_scaled = base_value_scaled.item(0)

                base_value_unscaled = y_scaler.inverse_transform(np.array([[base_value_scaled]]))[0][0]

                xai_data = {
                    "shap_values": shap_values_dict,
                    "base_value": float(base_value_unscaled),
                    "features": features_to_use,
                }
                logger.info(f"[{symbol}] SHAP values (KernelExplainer) для PyTorch модели успешно рассчитаны.")
                return xai_data

            elif lgb and isinstance(main_model, lgb.LGBMRegressor):
                logger.warning(f"[{symbol}] Расчет SHAP для LightGBM пока не реализован. Возврат None.")
                return None

        except Exception as e:
            logger.error(f"[{symbol}] Ошибка при фоновом расчете SHAP values: {e}", exc_info=True)
            return None
        return None

    def _find_best_confirming_strategy(
        self, ai_signal: TradeSignal, df: pd.DataFrame, market_regime: str, timeframe: int
    ) -> Tuple[Optional[BaseStrategy], float]:
        best_strategy, highest_score = None, -1.0
        current_index = len(df) - 1
        if current_index < 0:
            return None, -1.0

        for strategy in self.strategies:
            strategy_name = strategy.__class__.__name__
            confirmation_signal = strategy.check_entry_conditions(df, current_index, timeframe, ai_signal.symbol)
            if not confirmation_signal or confirmation_signal.type != ai_signal.type:
                continue

            stats = self.strategy_performance.get(strategy_name, {})
            total_trades = stats.get("total_trades", 0)
            win_rate = (stats.get("wins", 0) / total_trades) if total_trades > 5 else 0.5

            if win_rate < self.config.STRATEGY_MIN_WIN_RATE_THRESHOLD and total_trades > 5:
                continue

            primary_for_regime = self.config.STRATEGY_REGIME_MAPPING.get(market_regime) == strategy_name
            regime_bonus = 1.5 if primary_for_regime else 1.0
            base_weight = self.config.STRATEGY_WEIGHTS.get(strategy_name, 1.0)
            final_score = win_rate * base_weight * regime_bonus

            if final_score > highest_score:
                highest_score, best_strategy = final_score, strategy

        return best_strategy, highest_score
