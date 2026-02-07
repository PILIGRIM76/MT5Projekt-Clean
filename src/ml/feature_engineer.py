# src/ml/feature_engineer.py
import logging
import pandas as pd
import numpy as np
from typing import Optional, List
from src.core.config_models import Settings
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Автономно генерирует и расширяет набор признаков для моделей.
    """

    def __init__(self, config: Settings, querier: Optional[KnowledgeGraphQuerier] = None):
        self.config = config
        self.querier = querier

        # Словарь маппинга отношений в сентимент центральных банков
        # +1 = Ястребиный (Hawkish) / Позитив для валюты
        # -1 = Голубиный (Dovish) / Негатив для валюты
        self.cb_sentiment_map = {
            "RAISES_RATE": 1.0,
            "HIKES_RATE": 1.0,
            "HAWKISH_TONE": 0.5,
            "CUTS_RATE": -1.0,
            "LOWERS_RATE": -1.0,
            "DOVISH_TONE": -0.5,
            "QE_EXPANSION": -0.5,
            "QT_TIGHTENING": 0.5
        }

        # Словарь маппинга инфляционных сюрпризов
        self.inflation_map = {
            "HIGHER_THAN_FORECAST": 1.0,
            "LOWER_THAN_FORECAST": -1.0,
            "RISES": 0.5,
            "FALLS": -0.5
        }

    def _get_related_entities(self, symbol: str) -> List[str]:
        """Определяет список сущностей, влияющих на символ."""
        entities = [symbol]
        if len(symbol) == 6:
            base, quote = symbol[:3], symbol[3:]
            entities.extend([base, quote])
            if "USD" in entities: entities.extend(["FED", "POWELL", "FOMC"])
            if "EUR" in entities: entities.extend(["ECB", "LAGARDE"])
            if "GBP" in entities: entities.extend(["BOE"])
            if "JPY" in entities: entities.extend(["BOJ"])
            # Добавляем общие экономические индикаторы
        entities.extend(["INFLATION", "CPI", "RATE"])
        return entities

    def generate_graph_features(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Генерирует фундаментальные признаки на основе Графа Знаний."""
        # Всегда добавляем признаки, даже если нет querier
        if df.empty:
            # Если нет данных, добавляем пустые колонки и возвращаем
            df['KG_CB_SENTIMENT'] = 0.0
            df['KG_INFLATION_SURPRISE'] = 0.0
            return df
        
        if not self.querier:
            # Если нет querier, добавляем нулевые значения
            df['KG_CB_SENTIMENT'] = 0.0
            df['KG_INFLATION_SURPRISE'] = 0.0
            return df

        try:
            start_date = df.index[0].to_pydatetime()
            end_date = df.index[-1].to_pydatetime()
            entities = self._get_related_entities(symbol)

            # 1. Получение всех релевантных событий из БД
            events = self.querier.get_events_in_range(entities, start_date, end_date)

            if not events:
                df['KG_CB_SENTIMENT'] = 0.0
                df['KG_INFLATION_SURPRISE'] = 0.0
                return df

            events_df = pd.DataFrame(events)
            events_df['timestamp'] = pd.to_datetime(events_df['timestamp'])
            events_df = events_df.sort_values('timestamp')

            # 2. Расчет скоров для каждого события
            events_df['cb_score'] = events_df['relation_type'].map(self.cb_sentiment_map).fillna(0.0)

            def get_inf_score(row):
                # Проверяем, относится ли событие к инфляции/CPI
                is_inflation_event = any(
                    x in row['source_name'] or x in row['target_name'] for x in ["INFLATION", "CPI"])
                if is_inflation_event:
                    return self.inflation_map.get(row['relation_type'], 0.0)
                return 0.0

            events_df['inf_score'] = events_df.apply(get_inf_score, axis=1)

            # 3. Агрегация по времени (Merge As Of)
            # Создаем DF с признаками
            features_df = pd.DataFrame(index=events_df['timestamp'].unique())
            features_df['raw_cb'] = events_df.groupby('timestamp')['cb_score'].sum()
            features_df['raw_inf'] = events_df.groupby('timestamp')['inf_score'].sum()

            # Используем merge_asof для привязки новостей к ближайшей ПРЕДЫДУЩЕЙ свече
            df_merged = pd.merge_asof(
                df.sort_index(), features_df.sort_index(),
                left_index=True, right_index=True,
                direction='backward', tolerance=pd.Timedelta(days=7)
            )

            # 4. Пост-обработка: Заполнение NaN и Экспоненциальное затухание (Decay)
            df_merged['raw_cb'] = df_merged['raw_cb'].fillna(0)
            df_merged['raw_inf'] = df_merged['raw_inf'].fillna(0)

            # --- ИЗМЕНЕНИЕ: Применение Экспоненциального Затухания (EWMA) ---
            # EWMA с span=100 баров (примерно 4 дня на H1)
            df_merged['KG_CB_SENTIMENT'] = df_merged['raw_cb'].ewm(span=100, adjust=False).mean()
            df_merged['KG_INFLATION_SURPRISE'] = df_merged['raw_inf'].ewm(span=50, adjust=False).mean()
            # ----------------------------------------------------------------

            df_merged.drop(columns=['raw_cb', 'raw_inf'], inplace=True, errors='ignore')

            # 5. Финальная очистка и возврат
            return df_merged

        except Exception as e:
            logger.error(f"Ошибка генерации графовых признаков: {e}", exc_info=True)
            # В случае ошибки возвращаем исходный DF с пустыми колонками
            df['KG_CB_SENTIMENT'] = 0.0
            df['KG_INFLATION_SURPRISE'] = 0.0
            return df

    def generate_features(self, df: pd.DataFrame, onchain_data: Optional[pd.DataFrame] = None,
                          lunarcrush_data: Optional[pd.DataFrame] = None, # <-- НОВЫЙ АРГУМЕНТ
                          symbol: str = None) -> pd.DataFrame:
        """
        Принимает базовый DataFrame и опционально DataFrame с on-chain и LunarCrush данными,
        возвращает его с новыми, производными признаками.
        """
        logger.info("Запуск инжиниринга признаков...")
        df_out = df.copy()

        try:
            # 1. Признаки волатильности, MA, статистики и времени (остаются без изменений)
            if 'ATR_14' in df_out.columns and 'close' in df_out.columns:
                df_out['ATR_NORM'] = df_out['ATR_14'] / df_out['close']

            for length in [50, 200]:
                ema_col = f'EMA_{length}'
                if ema_col in df_out.columns:
                    df_out[f'DIST_{ema_col}'] = (df_out['close'] / df_out[ema_col]) - 1

            for length in [20, 60]:
                if len(df_out) > length:
                    returns = df_out['close'].pct_change()
                    df_out[f'SKEW_{length}'] = returns.rolling(window=length).skew()
                    df_out[f'KURT_{length}'] = returns.rolling(window=length).kurt()
                    df_out[f'VOLA_{length}'] = returns.rolling(window=length).std() * np.sqrt(252)

            df_out['HOUR'] = df_out.index.hour
            df_out['DAY_OF_WEEK'] = df_out.index.dayofweek
            df_out['hour_sin'] = np.sin(2 * np.pi * df_out['HOUR'] / 24)
            df_out['hour_cos'] = np.cos(2 * np.pi * df_out['HOUR'] / 24)
            df_out['day_of_week_sin'] = np.sin(2 * np.pi * df_out['DAY_OF_WEEK'] / 7)
            df_out['day_of_week_cos'] = np.cos(2 * np.pi * df_out['DAY_OF_WEEK'] / 7)

            # --- 5. Интеграция on-chain данных (Santiment/Заглушка) ---
            if onchain_data is not None and not onchain_data.empty:
                logger.info(f"Интеграция {len(onchain_data.columns)} on-chain признаков...")

                onchain_data = onchain_data.rename(columns={
                    'mvrv_ratio': 'ONCHAIN_MVRV',
                    'funding_rate': 'ONCHAIN_FUNDING_RATE'
                })

                if 'ONCHAIN_MVRV' in onchain_data.columns:
                    onchain_data['ONCHAIN_MVRV_ZSCORE'] = (onchain_data['ONCHAIN_MVRV'] - onchain_data[
                        'ONCHAIN_MVRV'].mean()) / onchain_data['ONCHAIN_MVRV'].std()

                if 'ONCHAIN_FUNDING_RATE' in onchain_data.columns:
                    onchain_data['ONCHAIN_FUNDING_RATE_EWMA'] = onchain_data['ONCHAIN_FUNDING_RATE'].ewm(span=7).mean()

                df_out = pd.merge_asof(
                    df_out.sort_index(),
                    onchain_data.sort_index(),
                    left_index=True,
                    right_index=True,
                    direction='backward'
                )
                df_out.fillna(0, inplace=True)
            # ------------------------------------------------------

            # --- 6. ИНТЕГРАЦИЯ LUNARCRUSH ДАННЫХ (НОВЫЙ БЛОК) ---
            if lunarcrush_data is not None and not lunarcrush_data.empty:
                logger.info(f"Интеграция {len(lunarcrush_data.columns)} LunarCrush признаков...")

                # LunarCrush данные уже должны быть очищены и иметь префиксы (LC_)
                # Добавляем производные признаки (например, нормализованный социальный объем)
                if 'LC_SOCIAL_VOLUME' in lunarcrush_data.columns:
                    # Нормализация: Z-Score для социального объема
                    lunarcrush_data['LC_SOCIAL_VOLUME_Z'] = (lunarcrush_data['LC_SOCIAL_VOLUME'] - lunarcrush_data[
                        'LC_SOCIAL_VOLUME'].mean()) / lunarcrush_data['LC_SOCIAL_VOLUME'].std()

                # Объединяем LunarCrush данные
                df_out = pd.merge_asof(
                    df_out.sort_index(),
                    lunarcrush_data.sort_index(),
                    left_index=True,
                    right_index=True,
                    direction='backward'
                )
                df_out.fillna(0, inplace=True) # Заполняем NaN после merge
            # ------------------------------------------------------

            # 7. Интеграция признаков из Графа Знаний
            if symbol:
                df_out = self.generate_graph_features(df_out, symbol)
            # ------------------------------------------------------

            # Финальная очистка перед возвратом данных
            initial_rows = len(df_out)
            df_out.replace([np.inf, -np.inf], np.nan, inplace=True)

            features_to_check = self.config.FEATURES_TO_USE
            existing_features_to_check = [f for f in features_to_check if f in df_out.columns]
            df_out.dropna(subset=existing_features_to_check, inplace=True)

            final_rows = len(df_out)

            logger.info(
                f"Инжиниринг признаков завершен. Добавлено {len(df_out.columns) - len(df.columns)} новых признаков. Удалено {initial_rows - final_rows} строк с NaN/Inf.")

        except Exception as e:
            logger.error(f"Ошибка в процессе инжиниринга признаков: {e}", exc_info=True)
            return df

        return df_out