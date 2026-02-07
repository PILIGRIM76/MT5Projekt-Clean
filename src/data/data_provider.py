# src/data/data_provider.py
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import time
import asyncio
import httpx
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from src.core.config_models import Settings
from datetime import datetime, timedelta, timezone
from src.data_models import NewsItem

logger = logging.getLogger(__name__)


class DataProvider:
    def __init__(self, config: Settings, mt5_lock: threading.Lock):
        self.config = config
        self.mt5_lock = mt5_lock
        self.finnhub_api_key = self.config.FINNHUB_API_KEY
        self.alpha_vantage_api_key = self.config.ALPHA_VANTAGE_API_KEY
        self.polygon_api_key = os.getenv("POLYGON_API_KEY")
        self.max_retries = 3
        self.retry_delay_seconds = 2
        self._finnhub_403_blacklist = set()
        self.training_bars = self.config.TRAINING_DATA_POINTS
        self.prediction_bars = self.config.PREDICTION_DATA_POINTS
        self.excluded_symbols = self.config.EXCLUDED_SYMBOLS
        self.symbols_whitelist = self.config.SYMBOLS_WHITELIST
        
        # Ограничиваем количество параллельных запросов к MT5
        self.mt5_semaphore = asyncio.Semaphore(5)  # Максимум 5 одновременных подключений

        # ИСПРАВЛЕНИЕ: Ограничение ThreadPoolExecutor до 4-х потоков (для 8-ядерного CPU)
        #self.executor = ThreadPoolExecutor(max_workers=4)

        # Инициализация last_news_timestamp для get_mt5_news
        self.last_news_timestamp = datetime.now(timezone.utc) - timedelta(days=1)

    def filter_available_symbols(self, requested_symbols: List[str]) -> List[str]:
        """
        Проверяет список символов на наличие у брокера.
        Возвращает только те, которые реально существуют в терминале.
        """
        logger.info("Проверка доступности символов в терминале...")
        valid_symbols = []

        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error("Не удалось подключиться к MT5 для проверки символов.")
                return requested_symbols  # Возвращаем как есть, если нет связи

            try:
                # Получаем ВСЕ символы брокера одним запросом (это быстро)
                all_broker_symbols = mt5.symbols_get()
                if not all_broker_symbols:
                    logger.warning("MT5 вернул пустой список символов.")
                    return requested_symbols

                # Создаем множество имен для быстрого поиска
                broker_symbol_names = {s.name for s in all_broker_symbols}

                # Фильтруем
                for sym in requested_symbols:
                    if sym in broker_symbol_names:
                        valid_symbols.append(sym)
                        # Пытаемся включить его в Market Watch
                        if not mt5.symbol_select(sym, True):
                            logger.warning(f"Символ {sym} найден, но не удалось включить в Market Watch.")
                    else:
                        # Тихо пропускаем или логируем в debug
                        logger.debug(f"Символ {sym} отсутствует у брокера. Исключен из списка.")

            finally:
                mt5.shutdown()

        logger.info(f"Фильтрация завершена. Из {len(requested_symbols)} символов доступно: {len(valid_symbols)}")
        return valid_symbols

    def get_conversion_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Получает курс конвертации, используя прямые, обратные пары или USD как кросс-валюту.
        """
        if from_currency == to_currency:
            return 1.0

        # 1. Поиск прямой или обратной пары
        def _get_rate_from_mt5(pair: str) -> Optional[float]:
            with self.mt5_lock:
                if not mt5.initialize(path=self.config.MT5_PATH):
                    return None
                try:
                    tick = mt5.symbol_info_tick(pair)
                    if tick and tick.ask > 0:
                        return tick.ask
                finally:
                    mt5.shutdown()
            return None

        # Поиск прямой пары (e.g., USDRUB)
        pair_direct = f"{from_currency}{to_currency}"
        rate = _get_rate_from_mt5(pair_direct)
        if rate is not None:
            return rate

        # Поиск обратной пары (e.g., RUBUSD)
        pair_inverse = f"{to_currency}{from_currency}"
        rate = _get_rate_from_mt5(pair_inverse)
        if rate is not None and rate > 0:
            return 1.0 / rate

        # 2. Поиск через USD (Кросс-курс)
        if from_currency != "USD" and to_currency != "USD":
            logger.info(f"Поиск кросс-курса для {from_currency}/{to_currency} через USD...")

            # Получаем курс из FROM_CURRENCY в USD
            rate_to_usd = self.get_conversion_rate(from_currency, "USD")

            # Получаем курс из USD в TO_CURRENCY
            rate_usd_to_final = self.get_conversion_rate("USD", to_currency)

            if rate_to_usd != 1.0 and rate_usd_to_final != 1.0:
                return rate_to_usd * rate_usd_to_final

        # 3. Неудача
        logger.warning(
            f"Не удалось найти курс конвертации для {from_currency} -> {to_currency}. Используется курс 1.0.")
        return 1.0

    def get_available_symbols(self) -> List[str]:
        if self.symbols_whitelist:
            return self.symbols_whitelist
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return []
        return [s.name for s in all_symbols if s.visible and s.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL]

    def _add_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        df_out = df.copy()

        try:
            # --- БЛОК 1: Базовые индикаторы ---
            high_low = df_out['high'] - df_out['low']
            high_close = np.abs(df_out['high'] - df_out['close'].shift())
            low_close = np.abs(df_out['low'] - df_out['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df_out['ATR_14'] = tr.ewm(alpha=1 / 14, adjust=False).mean()

            plus_dm = df_out['high'].diff()
            minus_dm = df_out['low'].diff() * -1
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            tr_adx = pd.concat([df_out['high'] - df_out['low'], np.abs(df_out['high'] - df_out['close'].shift()),
                                np.abs(df_out['low'] - df_out['close'].shift())], axis=1).max(axis=1)
            atr_adx = tr_adx.ewm(alpha=1 / 14, adjust=False).mean()
            plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_adx)
            minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_adx)
            dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di))
            df_out['ADX_14'] = dx.ewm(alpha=1 / 14, adjust=False).mean()

            delta = df_out['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df_out['RSI_14'] = 100 - (100 / (1 + rs))

            ema_fast = df_out['close'].ewm(span=12, adjust=False).mean()
            ema_slow = df_out['close'].ewm(span=26, adjust=False).mean()
            df_out['MACD_12_26_9'] = ema_fast - ema_slow
            df_out['MACDs_12_26_9'] = df_out['MACD_12_26_9'].ewm(span=9, adjust=False).mean()
            df_out['MACDh_12_26_9'] = df_out['MACD_12_26_9'] - df_out['MACDs_12_26_9']

            df_out['BBM_20_2.0'] = df_out['close'].rolling(window=20).mean()
            std_dev = df_out['close'].rolling(window=20).std()
            df_out['BBU_20_2.0'] = df_out['BBM_20_2.0'] + (std_dev * 2.0)
            df_out['BBL_20_2.0'] = df_out['BBM_20_2.0'] - (std_dev * 2.0)
            df_out['BB_WIDTH'] = (df_out['BBU_20_2.0'] - df_out['BBL_20_2.0']) / df_out['BBM_20_2.0']

            low_k = df_out['low'].rolling(window=14).min()
            high_k = df_out['high'].rolling(window=14).max()
            stoch_k_raw = 100 * ((df_out['close'] - low_k) / (high_k - low_k))
            df_out['STOCHk_14_3_3'] = stoch_k_raw.rolling(window=3).mean()
            df_out['STOCHd_14_3_3'] = df_out['STOCHk_14_3_3'].rolling(window=3).mean()

            df_out['EMA_50'] = df_out['close'].ewm(span=50, adjust=False).mean()
            df_out['EMA_200'] = df_out['close'].ewm(span=200, adjust=False).mean()

            # --- БЛОК 2: Продвинутые признаки (из FeatureEngineer) ---
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

            df_out.replace([np.inf, -np.inf], np.nan, inplace=True)

            essential_cols_for_plotting = ['open', 'high', 'low', 'close', 'EMA_50', 'ATR_14', 'ADX_14']
            cols_to_check = [c for c in essential_cols_for_plotting if c in df_out.columns]
            df_out.dropna(subset=essential_cols_for_plotting, inplace=True)

            # --- ОПТИМИЗАЦИЯ RAM: Принудительное понижение точности до float32 ---

            float64_cols = df_out.select_dtypes(include=['float64']).columns
            if len(float64_cols) > 0:
                df_out[float64_cols] = df_out[float64_cols].astype(np.float32)
            # --------------------------------------------------------------------

            # Добавляем KG признаки как нулевые значения (будут заполнены позже FeatureEngineer)
            if 'KG_CB_SENTIMENT' not in df_out.columns:
                df_out['KG_CB_SENTIMENT'] = 0.0
            if 'KG_INFLATION_SURPRISE' not in df_out.columns:
                df_out['KG_INFLATION_SURPRISE'] = 0.0

            return df_out
        except Exception as e:
            logger.error(f"Не удалось рассчитать все индикаторы: {e}", exc_info=True)
            return pd.DataFrame()

    def _fetch_mt5_data_with_retry(self, symbol: str, timeframe: int, num_bars: int) -> Optional[pd.DataFrame]:
        for attempt in range(self.max_retries):
            rates = None
            with self.mt5_lock:
                if not mt5.initialize(path=self.config.MT5_PATH):
                    continue
                try:
                    # --- ДОБАВЛЕНО: Принудительный выбор символа ---
                    if not mt5.symbol_select(symbol, True):
                        logger.warning(f"[{symbol}] Не удалось выбрать символ в Market Watch.")

                    # Небольшая пауза для подгрузки
                    if attempt == 0:
                        time.sleep(0.1)
                    # -----------------------------------------------

                    symbol_info = mt5.symbol_info(symbol)
                    if symbol_info is None:
                        logger.warning(f"[{symbol}] symbol_info is None.")
                    else:
                        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_bars + 200)
                finally:
                    mt5.shutdown()

            # Обработка данных (вне блокировки MT5)
            if rates is not None and len(rates) >= 50:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('time', inplace=True)
                if 'tick_volume' not in df.columns:
                    df['tick_volume'] = 0

                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC')
                return df

            # Если данных нет
            if rates is None:
                err = mt5.last_error()
                logger.debug(f"[{symbol}] Попытка {attempt + 1}: нет данных ({err}). Ожидание...")
                # Небольшая пауза, чтобы не перегружать терминал
                time.sleep(0.5)

            time.sleep(self.retry_delay_seconds * (attempt + 1))

        logger.error(f"[{symbol}] Не удалось получить данные после {self.max_retries} попыток.")
        return None

    async def get_all_symbols_data_async(self, symbols: List[str], timeframes: List[int],
                                         num_bars_override: Optional[int] = None) -> Dict[str, pd.DataFrame]:
        data_dict = {}
        num_bars = num_bars_override if num_bars_override is not None else self.config.PREDICTION_DATA_POINTS

        # Получаем текущий цикл событий
        loop = asyncio.get_running_loop()

        # Ограничиваем количество параллельных задач (максимум 12 одновременно)
        semaphore = asyncio.Semaphore(12)
        
        async def fetch_with_limit(symbol: str, tf: int):
            async with semaphore:
                # ИСПОЛЬЗУЕМ СТАНДАРТНЫЙ ПУЛ ПОТОКОВ (передаем None)
                # Это более стабильно для MetaTrader5, чем кастомный ThreadPoolExecutor
                result = await loop.run_in_executor(
                    None,  # <-- ИСПОЛЬЗУЕМ СТАНДАРТНЫЙ ПУЛ (более стабильно для MT5)
                    self._fetch_and_process_symbol_sync,
                    symbol,
                    tf,
                    num_bars
                )
                return result

        # Создаем задачи с ограничением
        tasks = []
        for symbol in symbols:
            for tf in timeframes:
                tasks.append(fetch_with_limit(symbol, tf))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # -----------------------------------------------------------------------

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Ошибка в задаче сбора данных: {result}")
            elif result:
                key, df_with_features = result
                data_dict[key] = df_with_features

        return data_dict

    def _fetch_and_process_symbol_sync(self, symbol: str, tf: int, num_bars: int) -> Optional[Tuple[str, pd.DataFrame]]:
        """Синхронный метод, который будет выполняться в пуле потоков."""
        if symbol in self.excluded_symbols:
            return None

        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error(f"[{symbol}] Не удалось инициализировать MT5 для проверки символа.")
                return None
            try:
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None or not symbol_info.visible:
                    logger.warning(f"[{symbol}] Символ не найден или не виден в MT5. Пропуск.")
                    return None
            finally:
                mt5.shutdown()

        df = self._fetch_mt5_data_with_retry(symbol, tf, num_bars)
        source = "MT5"

        if df is None:
            logger.error(f"[{symbol}] Не удалось получить данные ни из одного источника.")
            logger.error(f"[{symbol}_{tf}] Не удалось получить данные. Возврат None.")
            return None

        logger.debug(f"[{symbol}] Данные ({len(df)} баров) успешно получены из источника: {source}.")

        df_with_features = self._add_features(df)

        if not df_with_features.empty:
            return f"{symbol}_{tf}", df_with_features
        return None


    def get_historical_data(self, symbol: str, timeframe: int, start_date: datetime, end_date: datetime) -> Optional[
        pd.DataFrame]:
        logger.debug(f"Запрос исторических данных для {symbol} с {start_date} по {end_date}.")
        try:
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error(f"get_historical_data: initialize() failed, error code = {mt5.last_error()}")
                mt5.shutdown()
                return None
            rates = mt5.copy_rates_range(symbol, timeframe, start_date, end_date)
            mt5.shutdown()
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            if 'tick_volume' not in df.columns:
                df['tick_volume'] = 0
            return self._add_features(df)
        except Exception as e:
            logger.error(f"Критическая ошибка при загрузке исторических данных для {symbol}: {e}", exc_info=True)
            if mt5.terminal_info():
                mt5.shutdown()
            return None

    def _get_timeframe_str(self, tf_code: Optional[int]) -> str:
        if tf_code is None: return "N/A"
        tf_map = {v: k for k, v in mt5.__dict__.items() if k.startswith('TIMEFRAME_')}
        full_name = tf_map.get(tf_code, str(tf_code))
        return full_name.replace('TIMEFRAME_', '')

    def get_mt5_news(self) -> List[NewsItem]:
        """
        Запрашивает последние новости из терминала MetaTrader 5, используя
        правильный метод news_get_page.
        """
        news_items = []
        max_timestamp_in_batch = self.last_news_timestamp

        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error("DataProvider (get_mt5_news): Не удалось подключиться к MT5.")
                return []

            try:
                # Запрашиваем страницу из 50 последних новостей
                terminal_news = mt5.news_get_page(index=0, count=50)
                if not terminal_news:
                    return []

                new_news_to_process = []
                for news in terminal_news:
                    news_time = datetime.fromtimestamp(news.datetime, tz=timezone.utc)

                    if news_time > self.last_news_timestamp:
                        new_news_to_process.append(news)
                        if news_time > max_timestamp_in_batch:
                            max_timestamp_in_batch = news_time
                    else:
                        break

                if not new_news_to_process:
                    return []

                logger.info(f"Из терминала MT5 обнаружено {len(new_news_to_process)} новых новостей для анализа.")

                for news in reversed(new_news_to_process):
                    news_time = datetime.fromtimestamp(news.datetime, tz=timezone.utc)
                    full_text = f"{news.title}. {news.content}"

                    news_items.append(NewsItem(
                        source="MetaTrader 5",
                        text=full_text,
                        timestamp=news_time
                    ))

            except Exception as e:
                logger.error(f"Ошибка при получении новостей из MT5: {e}")
            finally:
                mt5.shutdown()

        if max_timestamp_in_batch > self.last_news_timestamp:
            self.last_news_timestamp = max_timestamp_in_batch

        return news_items