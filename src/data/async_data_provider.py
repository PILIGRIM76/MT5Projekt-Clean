# src/data/async_data_provider.py
"""
Асинхронный провайдер данных для Genesis Trading System.

Реализует:
- Асинхронное получение исторических данных
- Параллельная загрузка для нескольких символов
- Асинхронная загрузка новостей
- Кэширование результатов

Пример использования:
    async with AsyncDataProvider(config) as provider:
        # Параллельное получение данных для всех символов
        data_dict = await provider.get_multiple_symbols_data(symbols)
        
        # Асинхронная загрузка новостей
        news = await provider.fetch_news_batch(symbols)
"""

import asyncio
import aiohttp
import asyncpg
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
import pandas as pd
import MetaTrader5 as mt5

from src.core.config_models import Settings
from src.utils.cache_manager import quotes_cache, news_cache, cache_result

logger = logging.getLogger(__name__)


# ===========================================
# Async Data Provider
# ===========================================

class AsyncDataProvider:
    """
    Асинхронный провайдер рыночных данных.

    Особенности:
    - Неблокирующий I/O
    - Параллельные запросы
    - Встроенное кэширование
    - Connection pooling
    """

    def __init__(self, config: Settings):
        """
        Инициализация асинхронного провайдера.

        Args:
            config: Конфигурация системы
        """
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self._initialized = False

        logger.info("AsyncDataProvider инициализирован")

    async def initialize(self) -> None:
        """
        Инициализация сессий и пулов соединений.
        """
        if self._initialized:
            return

        # HTTP сессия - ИСПРАВЛЕНИЕ: отключаем прокси
        connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(
            connector=connector,
            trust_env=False  # Игнорировать переменные окружения прокси
        )

        # DB pool (если используется PostgreSQL)
        try:
            self.db_pool = await asyncpg.create_pool(
                self.config.DATABASE_URL.replace(
                    'sqlite:///', 'postgresql://'),
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            logger.info("DB pool создан")
        except Exception:
            logger.warning("PostgreSQL недоступен, используем SQLite")
            self.db_pool = None

        self._initialized = True
        logger.info("AsyncDataProvider полностью инициализирован")

    async def close(self) -> None:
        """
        Закрытие сессий и пулов.
        """
        if self.session:
            await self.session.close()

        if self.db_pool:
            await self.db_pool.close()

        self._initialized = False
        logger.info("AsyncDataProvider закрыт")

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ===========================================
    # Historical Data
    # ===========================================

    async def fetch_historical_data(
        self,
        symbol: str,
        timeframe: str = "H1",
        bars: int = 1000
    ) -> Optional[pd.DataFrame]:
        """
        Асинхронное получение исторических данных из MT5.

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм
            bars: Количество баров

        Returns:
            DataFrame с OHLCV данными
        """
        try:
            # Проверка кэша
            cache_key = f"hist:{symbol}:{timeframe}:{bars}"
            cached = quotes_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Кэш хит: {symbol}")
                return cached

            # Синхронный вызов MT5 в executor
            loop = asyncio.get_event_loop()
            rates = await loop.run_in_executor(
                None,
                lambda: self._get_rates_from_mt5(symbol, timeframe, bars)
            )

            if rates is None or len(rates) == 0:
                return None

            # Преобразование в DataFrame
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)

            # Добавляем символ для корректной работы стратегий
            df['symbol'] = symbol

            # Сохранение в кэш
            quotes_cache.put(cache_key, df, ttl=30)  # 30 секунд

            logger.debug(f"Загружено {len(df)} баров для {symbol}")
            return df

        except Exception as e:
            logger.error(f"Ошибка получения данных для {symbol}: {e}")
            return None

    def _get_rates_from_mt5(self, symbol: str, timeframe: str, bars: int) -> Optional[List]:
        """
        Получение данных из MT5 (синхронно).

        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм
            bars: Количество баров

        Returns:
            Список баров
        """
        # Маппинг таймфреймов
        timeframe_map = {
            'M1': mt5.TIMEFRAME_M1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'H1': mt5.TIMEFRAME_H1,
            'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1
        }

        tf = timeframe_map.get(timeframe, mt5.TIMEFRAME_H1)

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)

        if rates is None or len(rates) == 0:
            return None

        return rates

    # ===========================================
    # Multiple Symbols (Parallel)
    # ===========================================

    async def get_multiple_symbols_data(
        self,
        symbols: List[str],
        timeframe: str = "H1",
        bars: int = 1000,
        max_concurrent: int = 10
    ) -> Dict[str, pd.DataFrame]:
        """
        Параллельное получение данных для нескольких символов.

        Args:
            symbols: Список инструментов
            timeframe: Таймфрейм
            bars: Количество баров
            max_concurrent: Максимум одновременных запросов

        Returns:
            Словарь {symbol: DataFrame}
        """
        logger.info(f"Загрузка данных для {len(symbols)} символов...")

        # Ограничение параллелизма
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(symbol: str) -> Tuple[str, Optional[pd.DataFrame]]:
            async with semaphore:
                df = await self.fetch_historical_data(symbol, timeframe, bars)
                return symbol, df

        # Создание задач
        tasks = [fetch_with_semaphore(symbol) for symbol in symbols]

        # Параллельное выполнение
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Обработка результатов
        data_dict = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Ошибка в задаче: {result}")
                continue

            symbol, df = result
            if df is not None:
                data_dict[symbol] = df
            else:
                logger.warning(f"Нет данных для {symbol}")

        logger.info(
            f"Загружено данных для {len(data_dict)}/{len(symbols)} символов")
        return data_dict

    # ===========================================
    # Real-time Quotes
    # ===========================================

    async def get_realtime_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, float]]:
        """
        Получение котировок реального времени.

        Args:
            symbols: Список инструментов

        Returns:
            Словарь {symbol: {bid, ask, last, volume}}
        """
        try:
            # Проверка кэша
            cache_key = f"quotes:{','.join(sorted(symbols))}"
            cached = quotes_cache.get(cache_key)
            if cached is not None:
                return cached

            # Синхронный вызов в executor
            loop = asyncio.get_event_loop()
            quotes = await loop.run_in_executor(
                None,
                lambda: self._get_quotes_from_mt5(symbols)
            )

            # Сохранение в кэш
            quotes_cache.put(cache_key, quotes, ttl=5)  # 5 секунд

            return quotes

        except Exception as e:
            logger.error(f"Ошибка получения котировок: {e}")
            return {}

    def _get_quotes_from_mt5(self, symbols: List[str]) -> Dict[str, Dict[str, float]]:
        """
        Получение котировок из MT5 (синхронно).

        Args:
            symbols: Список инструментов

        Returns:
            Словарь котировок
        """
        quotes = {}

        for symbol in symbols:
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                quotes[symbol] = {
                    'bid': float(tick.bid),
                    'ask': float(tick.ask),
                    'last': float(tick.last),
                    'volume': int(tick.volume),
                    'time': datetime.fromtimestamp(tick.time)
                }

        return quotes

    # ===========================================
    # News (Async HTTP)
    # ===========================================

    async def fetch_news_batch(
        self,
        symbols: List[str],
        sources: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Асинхронная загрузка новостей для нескольких символов.

        Args:
            symbols: Список инструментов
            sources: Источники новостей

        Returns:
            Список новостей
        """
        # Проверка кэша
        cache_key = f"news:{','.join(sorted(symbols))}"
        cached = news_cache.get(cache_key)
        if cached is not None:
            logger.debug("Новости из кэша")
            return cached

        if not self.session:
            await self.initialize()

        # Создание задач для каждого источника
        tasks = []

        # NewsAPI
        if self.config.NEWS_API_KEY:
            tasks.append(self._fetch_newsapi(symbols))

        # FCS API
        if self.config.FCS_API_KEY:
            tasks.append(self._fetch_fcs_news(symbols))

        # RSS feeds
        if self.config.rss_feeds:
            tasks.append(self._fetch_rss_feeds())

        # Параллельное выполнение
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Объединение результатов
        all_news = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Ошибка загрузки новостей: {result}")
                continue
            if isinstance(result, list):
                all_news.extend(result)

        # Сохранение в кэш
        news_cache.put(cache_key, all_news, ttl=300)  # 5 минут

        logger.info(f"Загружено {len(all_news)} новостей")
        return all_news

    async def _fetch_newsapi(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Загрузка из NewsAPI."""
        url = "https://newsapi.org/v2/everything"

        # Формирование запроса
        symbols_query = " OR ".join(symbols[:5])  # Максимум 5 символов
        params = {
            'q': f"forex OR ({symbols_query})",
            'language': 'en',
            'sortBy': 'publishedAt',
            'pageSize': 20
        }
        headers = {'X-Api-Key': self.config.NEWS_API_KEY}

        try:
            async with self.session.get(url, params=params, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self._parse_newsapi_response(data)
                else:
                    logger.warning(f"NewsAPI error: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"NewsAPI exception: {e}")
            return []

    async def _fetch_fcs_news(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Загрузка из FCS API."""
        url = "https://api.fcseurope.com/2.0/news/"

        params = {
            'token': self.config.FCS_API_KEY,
            'limit': 20
        }

        try:
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self._parse_fcs_response(data)
                else:
                    return []
        except Exception as e:
            logger.error(f"FCS exception: {e}")
            return []

    async def _fetch_rss_feeds(self) -> List[Dict[str, Any]]:
        """Загрузка из RSS лент."""
        all_news = []

        for feed_url in self.config.rss_feeds[:5]:  # Максимум 5 лент
            try:
                async with self.session.get(feed_url, timeout=10) as resp:
                    if resp.status == 200:
                        rss_content = await resp.text()
                        news = self._parse_rss(rss_content)
                        all_news.extend(news)
            except Exception as e:
                logger.error(f"RSS feed error ({feed_url}): {e}")

        return all_news

    def _parse_newsapi_response(self, data: Dict) -> List[Dict[str, Any]]:
        """Парсинг ответа NewsAPI."""
        news = []
        for article in data.get('articles', []):
            news.append({
                'source': article.get('source', {}).get('name', 'NewsAPI'),
                'title': article.get('title', ''),
                'text': article.get('description', '') + ' ' + article.get('content', ''),
                'timestamp': datetime.fromisoformat(article.get('publishedAt', '').replace('Z', '+00:00')),
                'url': article.get('url')
            })
        return news

    def _parse_fcs_response(self, data: Dict) -> List[Dict[str, Any]]:
        """Парсинг ответа FCS API."""
        news = []
        for item in data.get('response', []):
            news.append({
                'source': 'FCS',
                'title': item.get('title', ''),
                'text': item.get('content', ''),
                'timestamp': datetime.fromtimestamp(item.get('timestamp', 0)),
                'url': item.get('url')
            })
        return news

    def _parse_rss(self, rss_content: str) -> List[Dict[str, Any]]:
        """Парсинг RSS ленты."""
        import xml.etree.ElementTree as ET

        news = []
        try:
            root = ET.fromstring(rss_content)
            channel = root.find('channel')

            if channel is None:
                return news

            for item in channel.findall('item')[:10]:  # Максимум 10 элементов
                title = item.find('title')
                description = item.find('description')
                pub_date = item.find('pubDate')
                link = item.find('link')

                news.append({
                    'source': 'RSS',
                    'title': title.text if title is not None else '',
                    'text': description.text if description is not None else '',
                    'timestamp': datetime.strptime(pub_date.text, '%a, %d %b %Y %H:%M:%S %z') if pub_date is not None else datetime.now(),
                    'url': link.text if link is not None else ''
                })
        except Exception as e:
            logger.error(f"RSS parsing error: {e}")

        return news

    # ===========================================
    # Economic Calendar
    # ===========================================

    async def fetch_economic_calendar(
        self,
        from_date: str,
        to_date: str,
        countries: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Получение экономического календаря.

        Args:
            from_date: Дата начала (YYYY-MM-DD)
            to_date: Дата конца (YYYY-MM-DD)
            countries: Список стран

        Returns:
            Список событий
        """
        if not self.session:
            await self.initialize()

        url = "https://api.forexfactory.com/calendar"

        params = {
            'from': from_date,
            'to': to_date,
            'token': self.config.FCS_API_KEY
        }

        if countries:
            params['countries'] = ','.join(countries)

        try:
            async with self.session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('response', [])
                else:
                    return []
        except Exception as e:
            logger.error(f"Economic calendar error: {e}")
            return []


# ===========================================
# Convenience Functions
# ===========================================

async def get_async_provider(config: Settings) -> AsyncDataProvider:
    """
    Получение асинхронного провайдера.

    Args:
        config: Конфигурация

    Returns:
        AsyncDataProvider
    """
    provider = AsyncDataProvider(config)
    await provider.initialize()
    return provider


@cache_result(quotes_cache, ttl=30)
async def get_cached_quotes(symbol: str) -> Optional[Dict[str, float]]:
    """
    Получение котировок с кэшированием.

    Args:
        symbol: Торговый инструмент

    Returns:
        Котировки
    """
    # Реализация будет в TradingSystem
    return None
