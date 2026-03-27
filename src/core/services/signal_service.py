# src/core/services/signal_service.py
import logging
from typing import Dict, Any, List, Optional, Tuple

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
from src.core.config_models import Settings
from src.data_models import TradeSignal, SignalType
from src.ml.consensus_engine import ConsensusResult
from src.analysis.market_regime_manager import MarketRegimeManager
from src.strategies.StrategyInterface import BaseStrategy
from src.ml.consensus_engine import ConsensusEngine

logger = logging.getLogger(__name__)


class SignalService:
    def __init__(self, config: Settings, market_regime_manager: MarketRegimeManager, strategies: List[BaseStrategy],
                 models: Dict, x_scalers: Dict, y_scalers: Dict, strategy_performance: Dict,
                 consensus_engine: ConsensusEngine,
                 trading_system_ref: Any):
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
            X.append(data[i:(i + n_steps)])
        return np.array(X)

    # --- НОВЫЙ МЕТОД: Сбор сигналов от классических стратегий ---
    def _get_classic_signals(self, df: pd.DataFrame, timeframe: int, market_regime: str) -> List[TradeSignal]:
        """Собирает сигналы от всех классических стратегий, релевантных режиму."""
        signals = []
        if not self.strategies:
            logger.warning("CLASSIC SIGNALS: Нет загруженных стратегий!")
            return signals

        logger.info(
            f"CLASSIC SIGNALS: Режим рынка '{market_regime}', проверяем {len(self.strategies)} стратегий")

        for strategy in self.strategies:
            strategy_name = strategy.__class__.__name__

            # Проверяем, что стратегия релевантна режиму (или является базовой)
            is_relevant = self.config.STRATEGY_REGIME_MAPPING.get(market_regime) == strategy_name or \
                self.config.STRATEGY_REGIME_MAPPING.get(
                    "Default") == strategy_name

            logger.debug(
                f"CLASSIC SIGNALS: Стратегия {strategy_name}, релевантна={is_relevant}")

            if is_relevant:
                signal = strategy.check_entry_conditions(
                    df, len(df) - 1, timeframe)
                logger.info(
                    f"CLASSIC SIGNALS: {strategy_name}.check_entry_conditions() returned signal type={signal.type if signal else None}")
                if signal and signal.type != SignalType.HOLD:
                    signals.append(signal)
                    logger.info(
                        f"CLASSIC SIGNALS: Добавлен сигнал от {strategy_name}: {signal.type.name}")

        logger.info(f"CLASSIC SIGNALS: Собрано {len(signals)} сигналов")
        return signals

    # --- НОВЫЙ МЕТОД: Вычисление On-Chain Score (Делегирование) ---
    def _get_on_chain_score(self, df: pd.DataFrame) -> float:
        """
        Вычисляет унифицированный скор On-Chain данных, делегируя логику ConsensusEngine.
        """
        return self.consensus_engine.calculate_on_chain_score(df)

    def get_trade_signal(self, symbol: str, df: pd.DataFrame, timeframe: int,
                         consensus_result: ConsensusResult) -> Optional[
            Tuple[TradeSignal, str, Optional[Dict], Optional[np.ndarray], Optional[float]]]:
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
                subj = rel.get('subject', '').upper()
                obj = rel.get('object', '').upper()
                if any(entity in subj for entity in important_entities) or any(
                        entity in obj for entity in important_entities):
                    is_important_news_active = True
                    logger.warning(
                        f"[{symbol}] Обнаружена важная новость: {subj} -> {rel.get('relation')} -> {obj}. Сделки блокированы.")
                    break

        if is_important_news_active:
            return None

        # 2. Определяем режим рынка.
        market_regime = self.market_regime_manager.get_regime(df)
        logger.info(
            f"[{symbol}] get_trade_signal: market_regime={market_regime}")
        primary_strategy_name = self.config.STRATEGY_REGIME_MAPPING.get(market_regime,
                                                                        self.config.STRATEGY_REGIME_MAPPING.get("Default", "AI_Model"))
        logger.info(
            f"[{symbol}] get_trade_signal: primary_strategy_name={primary_strategy_name}")

        # 3. Пробуем получить сигнал от основной (режимной) стратегии
        if primary_strategy_name != "AI_Model":
            logger.info(
                f"[{symbol}] Попытка получить сигнал от классической стратегии: {primary_strategy_name}")
            primary_signal, primary_name, _, primary_pred_input, primary_entry_price = self.get_primary_signal(
                symbol, df, timeframe, market_regime)
            logger.info(
                f"[{symbol}] get_primary_signal вернул: signal={primary_signal}, name={primary_name}")
            if primary_signal and primary_signal.type != SignalType.HOLD:
                logger.info(
                    f"[{symbol}] Получен сигнал от primary стратегии: {primary_signal.type.name}")
                confirmed_signal, confirmed_strategy_name, _ = self.get_confirmed_signal(
                    symbol, df, timeframe, primary_signal, primary_name, None)
                if confirmed_signal:
                    logger.info(
                        f"[{symbol}] Используется классическая стратегия: {confirmed_strategy_name}")
                    return confirmed_signal, confirmed_strategy_name, None, primary_pred_input, primary_entry_price
        else:
            logger.info(
                f"[{symbol}] primary_strategy_name==AI_Model, пропускаем классическую стратегию")

        # 4. Если классика не дала рабочий сигнал, идём по AI + консенсус
        logger.info(
            f"[{symbol}] Классические стратегии не дали сигнала, переходим на AI+консенсус")
        ai_signal, pred_input, entry_price = self._get_ai_signal(symbol, df)
        logger.info(f"[{symbol}] _get_ai_signal вернул: signal={ai_signal}")

        # 5. Собираем все факторы для Консенсуса
        classic_signals = self._get_classic_signals(
            df, timeframe, market_regime)

        # Если нет AI-сигнала — используем классические стратегии напрямую
        if not ai_signal or ai_signal.type == SignalType.HOLD:
            logger.info(
                f"[{symbol}] AI-сигнал: {ai_signal}. Классических сигналов: {len(classic_signals)}")
            if not classic_signals:
                logger.info(
                    f"[{symbol}] Нет классических сигналов и AI не дал сигнала. Возврат None.")
                return None
            classic_signal = classic_signals[0]
            strategy_name = classic_signal.__class__.__name__ if hasattr(
                classic_signal, '__class__') else "ClassicStrategy"
            entry_price = float(df['close'].iloc[-1]
                                ) if 'close' in df.columns else None
            logger.info(
                f"[{symbol}] AI-модель недоступна. Торговля по классической стратегии: {market_regime}")
            return classic_signal, f"Classic_{market_regime}", None, None, entry_price

        # 4.2. Сентимент KG
        kg_sentiment_score = self.consensus_engine.get_historical_context_sentiment(
            symbol, market_regime) or 0.0

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
            is_crypto=is_crypto
        )

        # === ИЗМЕНЕНИЕ: Если консенсус не достигнут, проверяем классические стратегии отдельно ===
        if final_signal_type == SignalType.HOLD:
            # Если есть сильные классические сигналы, используем их
            if classic_signals:
                # Проверяем, есть ли единогласие среди классических стратегий
                buy_count = sum(
                    1 for s in classic_signals if s.type == SignalType.BUY)
                sell_count = sum(
                    1 for s in classic_signals if s.type == SignalType.SELL)
                total = len(classic_signals)

                # Если 70%+ стратегий согласны, используем классический сигнал
                if buy_count >= total * 0.7:
                    logger.critical(
                        f"[{symbol}] КОНСЕНСУС не достигнут, но КЛАССИЧЕСКИЕ стратегии голосуют за BUY ({buy_count}/{total})")
                    return classic_signals[0], f"Classic_Consensus ({buy_count}/{total})", None, None, float(df['close'].iloc[-1])
                elif sell_count >= total * 0.7:
                    logger.critical(
                        f"[{symbol}] КОНСЕНСУС не достигнут, но КЛАССИЧЕСКИЕ стратегии голосуют за SELL ({sell_count}/{total})")
                    return classic_signals[0], f"Classic_Consensus ({sell_count}/{total})", None, None, float(df['close'].iloc[-1])

            logger.info(
                f"[{symbol}] Многофакторный консенсус не достигнут (Score: {final_score:.2f}). Сигнал отклонен.")
            return None

        # 6. Формирование финального сигнала
        final_signal = TradeSignal(type=final_signal_type, confidence=final_score,
                                   predicted_price=ai_signal.predicted_price)
        final_strategy_name = f"AI_MF_Consensus"

        logger.critical(
            f"[{symbol}] ФИНАЛЬНЫЙ СИГНАЛ: {final_signal.type.name} (Score: {final_score:.2f})")

        return final_signal, final_strategy_name, None, pred_input, entry_price

    def get_primary_signal(self, symbol: str, df: pd.DataFrame, timeframe: int, market_regime: str) -> \
            Tuple[Optional[TradeSignal], Optional[str], Optional[Dict], Optional[np.ndarray], Optional[float]]:
        market_regime = self.market_regime_manager.get_regime(df)
        primary_strategy_name = self.config.STRATEGY_REGIME_MAPPING.get(market_regime,
                                                                        self.config.STRATEGY_REGIME_MAPPING.get(
                                                                            "Default", "AI_Model"))
        logger.info(
            f"[{symbol}] Режим рынка: {market_regime}. Выбрана основная стратегия: '{primary_strategy_name}'")

        primary_strategy_instance = next((s for s in self.strategies if s.__class__.__name__ == primary_strategy_name),
                                         None)

        if (not primary_strategy_instance and primary_strategy_name != "AI_Model") or \
                (primary_strategy_name == "AI_Model" and (symbol not in self.models or not self.models[symbol])):
            fallback_strategy_name = "MovingAverageCrossoverStrategy"
            logger.warning(
                f"[{symbol}] Стратегия '{primary_strategy_name}' недоступна. Фолбэк к '{fallback_strategy_name}'.")
            primary_strategy_name = fallback_strategy_name
            primary_strategy_instance = next(
                (s for s in self.strategies if s.__class__.__name__ == fallback_strategy_name), None)

        if primary_strategy_name == "AI_Model":
            signal, pred_input, entry_price = self._get_ai_signal(symbol, df)
            return signal, "AI_Model", None, pred_input, entry_price
        elif primary_strategy_instance:
            signal = primary_strategy_instance.check_entry_conditions(
                df, len(df) - 1, timeframe)
            return signal, primary_strategy_name, None, None, None

        return None, None, None, None, None

    def get_confirmed_signal(self, symbol: str, df: pd.DataFrame, timeframe: int,
                             primary_signal: TradeSignal, primary_strategy: str,
                             xai_data: Optional[Dict]) -> Tuple[Optional[TradeSignal], str, Optional[Dict]]:
        market_regime = self.market_regime_manager.get_regime(df)

        if primary_strategy == "AI_Model":
            confirming_strategy, best_score = self._find_best_confirming_strategy(primary_signal, df, market_regime,
                                                                                  timeframe)
            if confirming_strategy:
                final_strategy_name = f"AI_Model_Confirmed_by_{confirming_strategy.__class__.__name__}"
                logger.info(
                    f"[{symbol}] AI-сигнал ({primary_signal.type.name}) ПОДТВЕРЖДЕН '{confirming_strategy.__class__.__name__}' (Score: {best_score:.2f}).")
                return primary_signal, final_strategy_name, xai_data
            else:
                logger.info(
                    f"[{symbol}] AI-сигнал ({primary_signal.type.name}) НЕ ПОДТВЕРЖДЕН. Сигнал отклонен.")
                return None, primary_strategy, None
        else:
            confirming_signal, _, _ = self._get_ai_signal(symbol, df)
            if confirming_signal and confirming_signal.type == primary_signal.type:
                final_strategy_name = f"{primary_strategy}_Confirmed_by_AI"
                logger.info(
                    f"[{symbol}] Сигнал '{primary_strategy}' ({primary_signal.type.name}) ПОДТВЕРЖДЕН AI.")
                return primary_signal, final_strategy_name, xai_data
            else:
                logger.info(
                    f"[{symbol}] Сигнал '{primary_strategy}' ({primary_signal.type.name}) НЕ подтвержден AI, но будет исполнен.")
                return primary_signal, primary_strategy, xai_data

    def _get_ai_signal(self, symbol: str, df: pd.DataFrame) -> Tuple[
            Optional[TradeSignal], Optional[np.ndarray], Optional[float]]:

        if symbol not in self.models or not self.models[symbol]:
            return None, None, None

        champion_committee = self.models.get(symbol, {})

        # ИСПРАВЛЕНИЕ: НЕ берем scalers из глобального хранилища сразу
        # Сначала проверим совместимость моделей, потом возьмем правильные scalers
        x_scaler = None
        y_scaler = None

        if not champion_committee:
            return None, None, None

        # 1. Динамически получаем список признаков ИЗ МОДЕЛИ
        # Проверяем, что все модели используют одинаковые признаки
        model_features = {}
        for model_type, model_data in champion_committee.items():
            features = model_data.get('features', [])
            model_features[model_type] = features
            logger.debug(
                f"[{symbol}] Модель {model_type} ожидает признаки: {features}")

        # Берем признаки первой модели как основные
        main_model_data = next(iter(champion_committee.values()), {})
        features_to_use = main_model_data.get(
            'features', self.config.FEATURES_TO_USE)

        # ВРЕМЕННО: НЕ удаляем дубликаты для совместимости со старыми моделями
        # TODO: Удалить после переобучения всех моделей
        # features_to_use = list(dict.fromkeys(features_to_use))

        # Проверяем согласованность признаков между моделями
        inconsistent_models = []
        for model_type, features in model_features.items():
            if set(features) != set(features_to_use):
                inconsistent_models.append(model_type)
                logger.warning(
                    f"[{symbol}] Несогласованность признаков: {model_type} использует {features}, основная модель использует {features_to_use}")

        # ИСПРАВЛЕНИЕ: Удаляем несовместимые модели из комитета вместо отклонения всего сигнала
        if inconsistent_models:
            logger.warning(
                f"[{symbol}] Удаление несовместимых моделей из комитета: {inconsistent_models}")
            for model_type in inconsistent_models:
                if model_type in champion_committee:
                    del champion_committee[model_type]

            # Если не осталось моделей, возвращаем None
            if not champion_committee:
                logger.error(
                    f"[{symbol}] Все модели несовместимы. Сигнал отклонен.")
                return None, None, None

            # Обновляем features_to_use на основе оставшихся моделей
            main_model_data = next(iter(champion_committee.values()), {})
            features_to_use = main_model_data.get(
                'features', self.config.FEATURES_TO_USE)

        # КРИТИЧНО: Пытаемся взять scalers из model_data, если нет - из глобального хранилища
        main_model_data = next(iter(champion_committee.values()), {})
        x_scaler = main_model_data.get(
            'x_scaler') or self.x_scalers.get(symbol)
        y_scaler = main_model_data.get(
            'y_scaler') or self.y_scalers.get(symbol)

        # Проверяем наличие scalers
        if not x_scaler or not y_scaler:
            logger.error(
                f"[{symbol}] Отсутствуют scalers (ни в model_data, ни в глобальном хранилище)")
            return None, None, None

        # КРИТИЧЕСКАЯ ПРОВЕРКА: Размерность scaler должна совпадать с features_to_use
        expected_features = x_scaler.n_features_in_ if hasattr(
            x_scaler, 'n_features_in_') else len(features_to_use)
        if expected_features != len(features_to_use):
            logger.warning(
                f"[{symbol}] Размерность scaler ({expected_features}) не совпадает с features_to_use ({len(features_to_use)})")

            # Шаг 1: Удаляем дубликаты из features_to_use
            unique_features = list(dict.fromkeys(features_to_use))

            if expected_features == len(unique_features):
                logger.info(
                    f"[{symbol}] Используем уникальные признаки ({len(unique_features)}) вместо дубликатов ({len(features_to_use)})")
                features_to_use = unique_features
            elif expected_features < len(unique_features):
                # Шаг 2: Если все еще не совпадает, удаляем KG-признаки (старые модели без них)
                features_without_kg = [
                    f for f in unique_features if not f.startswith('KG_')]
                if expected_features == len(features_without_kg):
                    logger.info(
                        f"[{symbol}] Используем признаки без KG ({len(features_without_kg)}) для совместимости со старой моделью")
                    features_to_use = features_without_kg
                else:
                    logger.error(
                        f"[{symbol}] Невозможно согласовать размерности: scaler={expected_features}, unique={len(unique_features)}, no_kg={len(features_without_kg)}. Пропуск.")
                    return None, None, None
            else:
                logger.error(
                    f"[{symbol}] Scaler ожидает больше признаков ({expected_features}) чем доступно ({len(unique_features)}). Пропуск.")
                return None, None, None

        # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Удаляем модели, несовместимые с финальным набором признаков
        # ВАЖНО: Проверяем совместимость по КОЛИЧЕСТВУ признаков, а не по составу
        models_to_remove = []
        for model_type, model_data in champion_committee.items():
            model_features = model_data.get('features', [])

            # Проверяем, совпадает ли количество признаков
            if len(model_features) != len(features_to_use):
                models_to_remove.append(model_type)
                logger.warning(
                    f"[{symbol}] Модель {model_type} несовместима: ожидает {len(model_features)} признаков, доступно {len(features_to_use)}")

        # НЕ удаляем модели, если это приведет к пустому комитету
        if models_to_remove and len(models_to_remove) < len(champion_committee):
            for model_type in models_to_remove:
                del champion_committee[model_type]
            logger.info(
                f"[{symbol}] Удалены несовместимые модели: {models_to_remove}. Осталось моделей: {len(champion_committee)}")
        elif models_to_remove:
            logger.warning(
                f"[{symbol}] Все модели несовместимы, но оставляем их для попытки прогноза")

        if not champion_committee:
            logger.error(f"[{symbol}] Комитет моделей пуст. Пропуск.")
            return None, None, None
        # ----------------------------------------------------------------------

        # 2. ГАРАНТИРУЕМ НАЛИЧИЕ ВСЕХ ПРИЗНАКОВ В ТЕКУЩЕМ DF
        df_processed = df.copy()
        missing_features = []

        for feat in features_to_use:
            if feat not in df_processed.columns:
                # Если признак отсутствует (например, KG-признак), добавляем его и заполняем нулями.
                df_processed[feat] = 0.0
                missing_features.append(feat)

        if missing_features:
            logger.warning(f"[{symbol}] Добавлены нулевые заглушки для недостающих признаков: {missing_features}. "
                           f"Размерность: {len(features_to_use)}.")

        # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Убеждаемся, что все признаки присутствуют
        actual_features = [
            feat for feat in features_to_use if feat in df_processed.columns]
        if len(actual_features) != len(features_to_use):
            missing = set(features_to_use) - set(actual_features)
            logger.error(
                f"[{symbol}] КРИТИЧЕСКАЯ ОШИБКА: Не все признаки доступны! Отсутствуют: {missing}")
            return None, None, None

        # 3. Создаем последовательность, используя ТОЧНО тот же порядок признаков
        # ИСПРАВЛЕНИЕ: Обрабатываем дубликаты признаков для совместимости со старыми моделями
        unique_features = list(dict.fromkeys(
            features_to_use))  # Уникальные признаки
        last_sequence_df = df_processed[unique_features].tail(self.n_steps)

        # Если есть дубликаты, создаем массив с повторениями
        if len(features_to_use) != len(unique_features):
            # Создаем маппинг индексов
            feature_indices = [unique_features.index(
                feat) for feat in features_to_use]
            last_sequence_raw = last_sequence_df.values[:, feature_indices]
        else:
            last_sequence_raw = last_sequence_df.values

        if last_sequence_raw.shape[0] < self.n_steps:
            return None, None, None

        # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: Принудительная очистка NaN/Inf в сырых данных ---
        if not np.all(np.isfinite(last_sequence_raw)):
            logger.warning(
                f"[{symbol}] Обнаружены NaN/inf в сырых данных. Принудительная очистка.")
            last_sequence_raw = np.nan_to_num(
                last_sequence_raw, nan=0.0, posinf=1e9, neginf=-1e9)

        # 4. Масштабирование
        try:
            last_sequence_scaled = x_scaler.transform(last_sequence_raw)
        except ValueError as e:
            logger.error(f"[{symbol}] Ошибка масштабирования: {e}")
            logger.error(
                f"[{symbol}] Размерность входных данных: {last_sequence_raw.shape}")
            logger.error(
                f"[{symbol}] Ожидаемая размерность scaler: {x_scaler.n_features_in_ if hasattr(x_scaler, 'n_features_in_') else 'unknown'}")
            logger.error(
                f"[{symbol}] Признаки в данных: {list(df_processed[features_to_use].columns)}")
            logger.error(f"[{symbol}] Ожидаемые признаки: {features_to_use}")

            # Если размерность не совпадает, пропускаем этот символ
            if "features" in str(e).lower() or last_sequence_raw.shape[1] != len(features_to_use):
                logger.warning(
                    f"[{symbol}] Пропуск обработки из-за несовпадения размерности признаков.")
                return None, None, None

            return None, None, None

        predictions = []
        prediction_input_numpy = None

        # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: ПРИНУДИТЕЛЬНОЕ ИСПОЛЬЗОВАНИЕ CPU ДЛЯ INFERENCE ---
        # Это устраняет ошибку "Input and parameter tensors are not at the same device"
        # и предотвращает конфликт с QWebEngineView.
        inference_device = torch.device("cpu")
        # ---------------------------------------------------------------------------------

        for model_type, model_data in champion_committee.items():
            model = model_data.get('model')
            if not model:
                continue

            try:
                if isinstance(model, nn.Module):
                    model.eval()
                    with torch.no_grad():
                        # 1. ПЕРЕНОС ВХОДНОГО ТЕНЗОРА НА CPU
                        prediction_input_tensor = torch.from_numpy(last_sequence_scaled).unsqueeze(0).float().to(
                            inference_device)

                        # 2. ПЕРЕНОС МОДЕЛИ НА CPU (на всякий случай, если она была перемещена)
                        model.to(inference_device)

                        prediction_scaled_tensor = model(
                            prediction_input_tensor)

                        # 3. ПЕРЕНОС РЕЗУЛЬТАТА ОБРАТНО НА CPU ДЛЯ SCALER (уже на CPU)
                        predicted_price = y_scaler.inverse_transform(
                            prediction_scaled_tensor.cpu().numpy())[0][0]
                        predictions.append(predicted_price)
                        prediction_input_numpy = prediction_input_tensor.cpu().numpy()

                elif lgb and isinstance(model, lgb.LGBMRegressor):
                    # Для LightGBM берем только последнюю строку признаков
                    last_features_scaled = last_sequence_scaled[-1].reshape(
                        1, -1)
                    prediction_scaled = model.predict(last_features_scaled)
                    # ИСПРАВЛЕНИЕ: ИСПОЛЬЗУЕМ ЛОКАЛЬНУЮ y_scaler
                    predicted_price = y_scaler.inverse_transform(
                        prediction_scaled.reshape(-1, 1))[0][0]
                    predictions.append(predicted_price)
                    # Сохраняем всю последовательность для возможного XAI анализа
                    prediction_input_numpy = last_sequence_scaled.reshape(
                        1, self.n_steps, -1)
                # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

            except Exception as e:
                logger.error(
                    f"[{symbol}] Ошибка прогноза от модели '{model_type}': {e}", exc_info=True)

        if not predictions:
            return None, None, None

        final_predicted_price = np.mean(predictions)
        current_price = df['close'].iloc[-1]
        price_change_ratio = (final_predicted_price -
                              current_price) / current_price

        signal_type = SignalType.HOLD
        if price_change_ratio > self.config.ENTRY_THRESHOLD:
            signal_type = SignalType.BUY
        elif price_change_ratio < -self.config.ENTRY_THRESHOLD:
            signal_type = SignalType.SELL

        signal = TradeSignal(type=signal_type, confidence=abs(price_change_ratio),
                             predicted_price=final_predicted_price)

        return signal, prediction_input_numpy, current_price

    def calculate_shap_values(self, symbol: str, prediction_input: np.ndarray, df_for_background: pd.DataFrame,
                              explainer=None, instance_to_explain=None, shap_values_dict=None) -> \
            Optional[Dict]:
        champion_committee = self.models.get(symbol, {})
        x_scaler = self.x_scalers.get(symbol)
        y_scaler = self.y_scalers.get(symbol)
        main_model_key = next(iter(champion_committee), None)

        if not all([champion_committee, x_scaler, y_scaler, main_model_key]):
            return None

        main_model_data = champion_committee[main_model_key]
        main_model = main_model_data.get('model')
        features_to_use = main_model_data.get('features', [])
        # ВРЕМЕННО: НЕ удаляем дубликаты для совместимости со старыми моделями
        # features_to_use = list(dict.fromkeys(features_to_use))

        # --- Получаем устройство из TradingSystem ---
        device = self.trading_system.device if hasattr(
            self.trading_system, 'device') else torch.device("cpu")
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
                    logger.warning(
                        f"[{symbol}] XAI: Добавлена заглушка для отсутствующего признака: {feat}")
            # --------------------------------------------------------------------------

            if isinstance(main_model, nn.Module):
                # 1. Создаем фоновый набор данных (summary)
                background_data_raw = df_background_copy[features_to_use].tail(
                    100).values
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
                    prefix = np.tile(
                        prediction_input[0, :n_steps - 1, :], (n_samples, 1, 1))

                    # Добавляем `x` как последний шаг
                    x_reshaped = np.concatenate(
                        [prefix, x[:, np.newaxis, :]], axis=1)

                    tensor = torch.from_numpy(x_reshaped).float()
                    tensor = tensor.to(device)  # Используем устройство
                    with torch.no_grad():
                        output = main_model(tensor)
                    return output.cpu().numpy()

                # 3. Создаем и используем KernelExplainer
                explainer = shap.KernelExplainer(
                    predict_fn, background_summary)

                # Объясняем только последний временной шаг
                instance_to_explain = prediction_input[0, -1, :].reshape(1, -1)

                # Расчет SHAP values
                shap_values = explainer.shap_values(
                    instance_to_explain, nsamples=50)

                if shap_values is None:
                    logger.error(
                        f"[{symbol}] shap_values вернул None. Пропуск SHAP.")
                    return None

                # Обработка результатов
                shap_values_dict = {feature: value for feature,
                                    value in zip(features_to_use, shap_values[0])}

                base_value_scaled = explainer.expected_value
                if isinstance(base_value_scaled, np.ndarray):
                    base_value_scaled = base_value_scaled.item(0)

                base_value_unscaled = y_scaler.inverse_transform(
                    np.array([[base_value_scaled]]))[0][0]

                xai_data = {
                    "shap_values": shap_values_dict,
                    "base_value": float(base_value_unscaled),
                    "features": features_to_use
                }
                logger.info(
                    f"[{symbol}] SHAP values (KernelExplainer) для PyTorch модели успешно рассчитаны.")
                return xai_data

            elif lgb and isinstance(main_model, lgb.LGBMRegressor):
                logger.warning(
                    f"[{symbol}] Расчет SHAP для LightGBM пока не реализован. Возврат None.")
                return None

        except Exception as e:
            logger.error(
                f"[{symbol}] Ошибка при фоновом расчете SHAP values: {e}", exc_info=True)
            return None
        return None

    def _find_best_confirming_strategy(self, ai_signal: TradeSignal, df: pd.DataFrame, market_regime: str,
                                       timeframe: int) -> Tuple[Optional[BaseStrategy], float]:
        best_strategy, highest_score = None, -1.0
        current_index = len(df) - 1
        if current_index < 0:
            return None, -1.0

        for strategy in self.strategies:
            strategy_name = strategy.__class__.__name__
            confirmation_signal = strategy.check_entry_conditions(
                df, current_index, timeframe)
            if not confirmation_signal or confirmation_signal.type != ai_signal.type:
                continue

            stats = self.strategy_performance.get(strategy_name, {})
            total_trades = stats.get('total_trades', 0)
            win_rate = (stats.get('wins', 0) /
                        total_trades) if total_trades > 5 else 0.5

            if win_rate < self.config.STRATEGY_MIN_WIN_RATE_THRESHOLD and total_trades > 5:
                continue

            primary_for_regime = self.config.STRATEGY_REGIME_MAPPING.get(
                market_regime) == strategy_name
            regime_bonus = 1.5 if primary_for_regime else 1.0
            base_weight = self.config.STRATEGY_WEIGHTS.get(strategy_name, 1.0)
            final_score = win_rate * base_weight * regime_bonus

            if final_score > highest_score:
                highest_score, best_strategy = final_score, strategy

        return best_strategy, highest_score
