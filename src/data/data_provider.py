# src/data/data_provider.py
import asyncio
import logging
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx
import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from src.core.config_models import Settings
from src.core.mt5_connection_manager import mt5_ensure_connected, mt5_initialize
from src.core.mt5_symbol_helper import SymbolHelper
from src.data_models import NewsItem

logger = logging.getLogger(__name__)


class LRUCache:
    """
    LRU-кэш для хранения исторических данных.
    Потокобезопасная реализация с ограничением по размеру.
    """

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[pd.DataFrame]:
        """Получить данные из кэша."""
        with self._lock:
            if key in self.cache:
                # Переместить в конец (свежий)
                self.cache.move_to_end(key)
                logger.debug(f"Cache HIT: {key}")
                return self.cache[key]
            logger.debug(f"Cache MISS: {key}")
            return None

    def put(self, key: str, value: pd.DataFrame) -> None:
        """Сохранить данные в кэш."""
        with self._lock:
            if key in self.cache:
                # Обновить существующий
                self.cache.move_to_end(key)
                self.cache[key] = value
            else:
                # Добавить новый
                if len(self.cache) >= self.max_size:
                    # Удалить самый старый
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
                    logger.debug(f"Cache EVICT: {oldest_key}")
                self.cache[key] = value
                logger.debug(f"Cache PUT: {key}")

    def clear(self) -> None:
        """Очистить кэш."""
        with self._lock:
            self.cache.clear()
            logger.info("Cache cleared")

    def size(self) -> int:
        """Вернуть текущий размер кэша."""
        with self._lock:
            return len(self.cache)


class DataProvider:
    def __init__(self, config: Settings, mt5_lock: threading.Lock):
        self.config = config
        self.mt5_lock = mt5_lock
        self.finnhub_api_key = self.config.FINNHUB_API_KEY
        self.alpha_vantage_api_key = self.config.ALPHA_VANTAGE_API_KEY
        self.polygon_api_key = os.getenv("POLYGON_API_KEY")
        # Инициализация помощника символов
        self.symbol_helper = SymbolHelper
        self.symbol_helper._lock = mt5_lock
        self.max_retries = 3
        self.retry_delay_seconds = 2
        self._finnhub_403_blacklist = set()
        self.training_bars = self.config.TRAINING_DATA_POINTS
        self.prediction_bars = self.config.PREDICTION_DATA_POINTS
        self.excluded_symbols = self.config.EXCLUDED_SYMBOLS
        self.symbols_whitelist = self.config.SYMBOLS_WHITELIST

        # Ограничиваем количество параллельных запросов к MT5
        self.mt5_semaphore = asyncio.Semaphore(5)

        # LRU-кэш для исторических данных (оптимизация: 50 вместо 100)
        self._data_cache = LRUCache(max_size=50)

        # Кэш для курсов конвертации (оптимизация: 30 вместо 50)
        self._conversion_cache = LRUCache(max_size=30)

        # Инициализация last_news_timestamp для get_mt5_news
        self.last_news_timestamp = datetime.now(timezone.utc) - timedelta(days=1)

        # ThreadPoolExecutor для всех асинхронных операций (оптимизация: 4 вместо None)
        self.executor = ThreadPoolExecutor(max_workers=4)

    def __del__(self):
        """Корректное закрытие executor."""
        if hasattr(self, "executor") and self.executor:
            self.executor.shutdown(wait=False)

    def _force_mt5_reconnect(self):
        """Принудительный reconnect к MT5 через shutdown + initialize."""
        import MetaTrader5 as mt5

        try:
            mt5.shutdown()
        except Exception:
            pass
        time.sleep(1.0)
        try:
            # Безопасная обработка MT5_LOGIN
            try:
                mt5_login = int(self.config.MT5_LOGIN) if self.config.MT5_LOGIN else None
            except (ValueError, TypeError) as e:
                logger.error(f"[DATA] Некорректный MT5_LOGIN: {self.config.MT5_LOGIN}, ошибка: {e}")
                mt5_login = None

            # 🔧 OPTIMIZATION: Используем безопасную обертку вместо прямого mt5.initialize()
            mt5_initialize(
                path=self.config.MT5_PATH,
                login=mt5_login,
                password=self.config.MT5_PASSWORD,
                server=self.config.MT5_SERVER,
            )
        except Exception as e:
            logger.error(f"[DATA] Ошибка reconnect: {e}")

    def filter_available_symbols(self, requested_symbols: List[str]) -> List[str]:
        """
        Проверяет список символов на наличие у брокера.
        Возвращает только те, которые реально существуют в терминале.
        """
        logger.info("Проверка доступности символов в терминале...")

        # Строим карту символов (базовое_имя -> реальное_имя_у_брокера)
        self.symbol_helper.build_symbol_map(requested_symbols, self.mt5_lock)
        symbol_map = self.symbol_helper._symbol_map_cache

        valid_symbols = []
        for base_sym in requested_symbols:
            real_sym = symbol_map.get(base_sym, base_sym)
            if base_sym != real_sym:
                logger.info(f"[SymbolMap] {base_sym} → {real_sym}")
            # Проверяем что символ действительно доступен
            if self.symbol_helper.select_and_wait(real_sym, self.mt5_lock, timeout=2.0):
                valid_symbols.append(real_sym)
            else:
                logger.warning(f"[{base_sym}] Не удалось выбрать символ в Market Watch (реальное имя: {real_sym})")

        logger.info(f"Фильтрация завершена. Из {len(requested_symbols)} символов доступно: {len(valid_symbols)}")
        return valid_symbols

    def get_conversion_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Получает курс конвертации с кэшированием.
        Ключ кэша: {from_currency}_{to_currency}
        """
        if from_currency == to_currency:
            return 1.0

        # Проверка кэша
        cache_key = f"{from_currency}_{to_currency}"
        cached_rate = self._conversion_cache.get(cache_key)
        if cached_rate is not None:
            return cached_rate

        # 1. Поиск прямой или обратной пары
        def _get_rate_from_mt5(pair: str) -> Optional[float]:
            with self.mt5_lock:
                if not mt5_ensure_connected(path=self.config.MT5_PATH):
                    return None
                try:
                    tick = mt5.symbol_info_tick(pair)
                    if tick and tick.ask > 0:
                        return tick.ask
                except Exception as e:
                    logger.debug(f"Ошибка получения тика для {pair}: {e}")
            return None

        # Поиск прямой пары (e.g., USDRUB)
        pair_direct = f"{from_currency}{to_currency}"
        rate = _get_rate_from_mt5(pair_direct)
        if rate is not None:
            self._conversion_cache.put(cache_key, rate)
            return rate

        # Поиск обратной пары (e.g., RUBUSD)
        pair_inverse = f"{to_currency}{from_currency}"
        rate = _get_rate_from_mt5(pair_inverse)
        if rate is not None and rate > 0:
            inverse_rate = 1.0 / rate
            self._conversion_cache.put(cache_key, inverse_rate)
            return inverse_rate

        # 2. Поиск через USD (Кросс-курс)
        if from_currency != "USD" and to_currency != "USD":
            logger.info(f"Поиск кросс-курса для {from_currency}/{to_currency} через USD...")

            # Получаем курс из FROM_CURRENCY в USD
            rate_to_usd = self.get_conversion_rate(from_currency, "USD")

            # Получаем курс из USD в TO_CURRENCY
            rate_usd_to_final = self.get_conversion_rate("USD", to_currency)

            if rate_to_usd != 1.0 and rate_usd_to_final != 1.0:
                cross_rate = rate_to_usd * rate_usd_to_final
                self._conversion_cache.put(cache_key, cross_rate)
                return cross_rate

        # 3. Неудача
        logger.warning(f"Не удалось найти курс конвертации для {from_currency} -> {to_currency}. Используется курс 1.0.")
        return 1.0

    def get_available_symbols(self) -> List[str]:
        if self.symbols_whitelist:
            return self.symbols_whitelist
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return []
        return [s.name for s in all_symbols if s.visible and s.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL]

    def _add_features(self, df: pd.DataFrame, symbol: str = None) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        df_out = df.copy()

        # Добавляем колонку symbol для идентификации
        if symbol:
            df_out["symbol"] = symbol

        try:
            # --- БЛОК 1: Базовые индикаторы ---
            high_low = df_out["high"] - df_out["low"]
            high_close = np.abs(df_out["high"] - df_out["close"].shift())
            low_close = np.abs(df_out["low"] - df_out["close"].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df_out["ATR_14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

            plus_dm = df_out["high"].diff()
            minus_dm = df_out["low"].diff() * -1
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            tr_adx = pd.concat(
                [
                    df_out["high"] - df_out["low"],
                    np.abs(df_out["high"] - df_out["close"].shift()),
                    np.abs(df_out["low"] - df_out["close"].shift()),
                ],
                axis=1,
            ).max(axis=1)
            atr_adx = tr_adx.ewm(alpha=1 / 14, adjust=False).mean()
            plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_adx)
            minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_adx)
            dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di))
            df_out["ADX_14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

            delta = df_out["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df_out["RSI_14"] = 100 - (100 / (1 + rs))

            ema_fast = df_out["close"].ewm(span=12, adjust=False).mean()
            ema_slow = df_out["close"].ewm(span=26, adjust=False).mean()
            df_out["MACD_12_26_9"] = ema_fast - ema_slow
            df_out["MACDs_12_26_9"] = df_out["MACD_12_26_9"].ewm(span=9, adjust=False).mean()
            df_out["MACDh_12_26_9"] = df_out["MACD_12_26_9"] - df_out["MACDs_12_26_9"]

            df_out["BBM_20_2.0"] = df_out["close"].rolling(window=20).mean()
            std_dev = df_out["close"].rolling(window=20).std()
            df_out["BBU_20_2.0"] = df_out["BBM_20_2.0"] + (std_dev * 2.0)
            df_out["BBL_20_2.0"] = df_out["BBM_20_2.0"] - (std_dev * 2.0)
            df_out["BB_WIDTH"] = (df_out["BBU_20_2.0"] - df_out["BBL_20_2.0"]) / df_out["BBM_20_2.0"]

            low_k = df_out["low"].rolling(window=14).min()
            high_k = df_out["high"].rolling(window=14).max()
            stoch_k_raw = 100 * ((df_out["close"] - low_k) / (high_k - low_k))
            df_out["STOCHk_14_3_3"] = stoch_k_raw.rolling(window=3).mean()
            df_out["STOCHd_14_3_3"] = df_out["STOCHk_14_3_3"].rolling(window=3).mean()

            df_out["EMA_50"] = df_out["close"].ewm(span=50, adjust=False).mean()
            df_out["EMA_200"] = df_out["close"].ewm(span=200, adjust=False).mean()

            # --- БЛОК 2: Продвинутые признаки (из FeatureEngineer) ---
            df_out["ATR_NORM"] = df_out["ATR_14"] / df_out["close"]
            for length in [50, 200]:
                ema_col = f"EMA_{length}"
                if ema_col in df_out.columns:
                    df_out[f"DIST_{ema_col}"] = (df_out["close"] / df_out[ema_col]) - 1

            for length in [20, 60]:
                if len(df_out) > length:
                    returns = df_out["close"].pct_change()
                    df_out[f"SKEW_{length}"] = returns.rolling(window=length).skew()
                    df_out[f"KURT_{length}"] = returns.rolling(window=length).kurt()
                    df_out[f"VOLA_{length}"] = returns.rolling(window=length).std() * np.sqrt(252)

            df_out["HOUR"] = df_out.index.hour
            df_out["DAY_OF_WEEK"] = df_out.index.dayofweek
            df_out["hour_sin"] = np.sin(2 * np.pi * df_out["HOUR"] / 24)
            df_out["hour_cos"] = np.cos(2 * np.pi * df_out["HOUR"] / 24)
            df_out["day_of_week_sin"] = np.sin(2 * np.pi * df_out["DAY_OF_WEEK"] / 7)
            df_out["day_of_week_cos"] = np.cos(2 * np.pi * df_out["DAY_OF_WEEK"] / 7)

            df_out.replace([np.inf, -np.inf], np.nan, inplace=True)

            essential_cols_for_plotting = ["open", "high", "low", "close", "EMA_50", "ATR_14", "ADX_14"]
            cols_to_check = [c for c in essential_cols_for_plotting if c in df_out.columns]
            df_out.dropna(subset=essential_cols_for_plotting, inplace=True)

            # --- ОПТИМИЗАЦИЯ RAM: Принудительное понижение точности до float32 ---

            float64_cols = df_out.select_dtypes(include=["float64"]).columns
            if len(float64_cols) > 0:
                df_out[float64_cols] = df_out[float64_cols].astype(np.float32)
            # --------------------------------------------------------------------

            # Добавляем KG признаки как нулевые значения (будут заполнены позже FeatureEngineer)
            if "KG_CB_SENTIMENT" not in df_out.columns:
                df_out["KG_CB_SENTIMENT"] = 0.0
            if "KG_INFLATION_SURPRISE" not in df_out.columns:
                df_out["KG_INFLATION_SURPRISE"] = 0.0

            return df_out
        except Exception as e:
            logger.error(f"Не удалось рассчитать все индикаторы: {e}", exc_info=True)
            return pd.DataFrame()

    def _fetch_mt5_data_with_retry(self, symbol: str, timeframe: int, num_bars: int) -> Optional[pd.DataFrame]:
        for attempt in range(self.max_retries):
            rates = None
            with self.mt5_lock:
                if not mt5_ensure_connected(path=self.config.MT5_PATH):
                    continue
                try:
                    # Разрешаем символ через помощник
                    real_symbol = self.symbol_helper.resolve_symbol(symbol)

                    # Выбираем символ в Market Watch
                    mt5.symbol_select(real_symbol, True)
                    time.sleep(0.3)

                    symbol_info = mt5.symbol_info(real_symbol)
                    if symbol_info is None:
                        logger.warning(f"[{symbol}] ({real_symbol}) symbol_info is None.")
                        time.sleep(0.5)
                        continue

                    rates = mt5.copy_rates_from_pos(real_symbol, timeframe, 0, num_bars + 200)
                except Exception as e:
                    logger.debug(f"[{symbol}] Ошибка при получении данных (попытка {attempt + 1}): {e}")

            # Обработка данных (вне блокировки MT5)
            if rates is not None and len(rates) >= 50:
                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df.set_index("time", inplace=True)
                if "tick_volume" not in df.columns:
                    df["tick_volume"] = 0

                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
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

    async def get_all_symbols_data_async(
        self, symbols: List[str], timeframes: List[int], num_bars_override: Optional[int] = None
    ) -> Dict[str, pd.DataFrame]:
        data_dict = {}
        num_bars = num_bars_override if num_bars_override is not None else self.config.PREDICTION_DATA_POINTS

        # Получаем текущий цикл событий
        loop = asyncio.get_running_loop()

        # Ограничиваем количество параллельных задач (максимум 12 одновременно)
        semaphore = asyncio.Semaphore(12)

        async def fetch_with_limit(symbol: str, tf: int):
            async with semaphore:
                # Используем наш executor для стабильности
                result = await loop.run_in_executor(self.executor, self._fetch_and_process_symbol_sync, symbol, tf, num_bars)
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

        # Разрешаем символ через помощник
        real_symbol = self.symbol_helper.resolve_symbol(symbol)

        # Проверяем symbol_info
        symbol_info = None
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                # 🔧 OPTIMIZATION: При ошибке -10004 логируем только один раз, не для каждого символа
                logger.debug(f"[{symbol}] MT5 недоступен, пропускаю проверку символа.")
                return None
            try:
                mt5.symbol_select(real_symbol, True)
                time.sleep(0.3)
                symbol_info = mt5.symbol_info(real_symbol)
            except Exception as e:
                logger.debug(f"Ошибка получения symbol_info для {symbol}: {e}")

        # Проверка вне блокировки
        if symbol_info is None or not symbol_info.visible:
            logger.warning(f"[{symbol}] ({real_symbol}) Символ не найден или не виден в MT5. Пропуск.")
            return None

        df = self._fetch_mt5_data_with_retry(symbol, tf, num_bars)
        source = "MT5"

        if df is None:
            logger.error(f"[{symbol}] Не удалось получить данные ни из одного источника.")
            logger.error(f"[{symbol}_{tf}] Не удалось получить данные. Возврат None.")
            return None

        logger.debug(f"[{symbol}] Данные ({len(df)} баров) успешно получены из источника: {source}.")

        # ОПТИМИЗАЦИЯ: Обработка признаков вне блокировки MT5
        df_with_features = self._add_features(df, symbol)

        if not df_with_features.empty:
            return f"{symbol}_{tf}", df_with_features
        return None

    def get_historical_data(
        self, symbol: str, timeframe: int, start_date: datetime, end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Загружает исторические данные с кэшированием.

        Ключ кэша: {symbol}_{timeframe}_{start}_{end}
        TTL: Данные кэшируются до сброса кэша (автоматически при старте)
        """
        # Формируем ключ кэша
        cache_key = f"{symbol}_{timeframe}_{start_date.timestamp()}_{end_date.timestamp()}"

        # Проверяем кэш
        cached_data = self._data_cache.get(cache_key)
        if cached_data is not None:
            logger.debug(f"Кэш HIT для {symbol} {timeframe}")
            return cached_data.copy()

        logger.info(f"[DATA] Загрузка {symbol} {timeframe}...")

        try:
            # Пытаемся захватить mt5_lock с УВЕЛИЧЕННЫМ таймаутом для обучения (180 сек)
            # Обучение моделей - долгая операция, требует стабильного доступа к MT5
            acquired = self.mt5_lock.acquire(timeout=180)  # 3 минуты для обучения
            if not acquired:
                logger.error(
                    f"[DATA] ТАЙМАУТ захвата mt5_lock для {symbol} (180 сек). "
                    f"Возможно торговый цикл выполняет длительную операцию. Пропуск."
                )
                return None

            try:
                if not mt5_ensure_connected(path=self.config.MT5_PATH):
                    logger.error(f"get_historical_data: инициализация MT5 не удалась")
                    return None

                # Разрешаем символ через помощник
                real_symbol = self.symbol_helper.resolve_symbol(symbol)

                # Выбираем в Market Watch
                mt5.symbol_select(real_symbol, True)
                time.sleep(0.5)  # Пауза для подгрузки

                logger.info(f"[DATA] Загрузка MT5 copy_rates_range для {symbol} ({real_symbol})...")
                rates = mt5.copy_rates_range(real_symbol, timeframe, start_date, end_date)
                logger.info(f"[DATA] Получено {len(rates) if rates is not None else 0} баров")

                # Если 0 баров — пробуем reconnect
                if rates is None or len(rates) == 0:
                    logger.warning(f"[DATA] 0 баров для {symbol}, пробуем reconnect...")
                    self._force_mt5_reconnect()
                    if not mt5_ensure_connected(path=self.config.MT5_PATH):
                        logger.error(f"[DATA] Reconnect не удался для {symbol}")
                        return None
                    mt5.symbol_select(real_symbol, True)
                    time.sleep(1.0)
                    rates = mt5.copy_rates_range(real_symbol, timeframe, start_date, end_date)
                    logger.info(f"[DATA] После reconnect: {len(rates) if rates is not None else 0} баров для {symbol}")
            finally:
                self.mt5_lock.release()

            if rates is None or len(rates) == 0:
                logger.warning(f"[DATA] Пустые данные для {symbol}")
                return None

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)

            # Добавляем символ для корректной работы стратегий
            df["symbol"] = symbol

            if "tick_volume" not in df.columns:
                df["tick_volume"] = 0

            # Добавляем признаки
            df_with_features = self._add_features(df, symbol)

            # Сохраняем в кэш
            self._data_cache.put(cache_key, df_with_features)
            logger.info(f"[DATA] Завершено для {symbol}, баров: {len(df_with_features)}")

            return df_with_features

        except Exception as e:
            logger.error(f"Критическая ошибка при загрузке исторических данных для {symbol}: {e}", exc_info=True)
            return None

    def _get_timeframe_str(self, tf_code: Optional[int]) -> str:
        if tf_code is None:
            return "N/A"
        tf_map = {v: k for k, v in mt5.__dict__.items() if k.startswith("TIMEFRAME_")}
        full_name = tf_map.get(tf_code, str(tf_code))
        return full_name.replace("TIMEFRAME_", "")

    def get_mt5_news(self) -> List[NewsItem]:
        """
        Запрашивает последние новости из терминала MetaTrader 5, используя
        правильный метод news_get_page.
        """
        news_items = []
        max_timestamp_in_batch = self.last_news_timestamp

        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
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

                    news_items.append(NewsItem(source="MetaTrader 5", text=full_text, timestamp=news_time))

            except Exception as e:
                logger.error(f"Ошибка при получении новостей из MT5: {e}")

        if max_timestamp_in_batch > self.last_news_timestamp:
            self.last_news_timestamp = max_timestamp_in_batch

        return news_items

    def get_minimum_lot_size(self, symbol: str) -> Optional[float]:
        """
        Получает минимальный размер лота для символа из MT5.
        """
        with self.mt5_lock:
            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                logger.error(f"[get_minimum_lot_size] Не удалось инициализировать MT5 для {symbol}.")
                return None

            try:
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"[get_minimum_lot_size] Символ {symbol} не найден в терминале.")
                    return None

                # Возвращаем минимальный лот, если он больше 0
                min_lot = symbol_info.volume_min
                if min_lot > 0:
                    return float(min_lot)
                else:
                    # Если минимальный объем 0 или отрицательный, используем стандартный минимальный лот
                    return 0.01

            except Exception as e:
                logger.error(f"[get_minimum_lot_size] Ошибка при получении информации о символе {symbol}: {e}")
                return None
