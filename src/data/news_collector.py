# src/data/news_collector.py
"""
News Collector — Сбор исторических и текущих новостей.

Источники (бесплатные):
1. Finnhub News API — финансовые новости
2. NewsAPI.org — общие новости
3. RSS Feeds — прямые ленты
4. Web Scraping — парсинг сайтов

Функции:
- Загрузка исторических новостей
- Непрерывный мониторинг
- Сохранение в базу данных
- Анализ сентимента
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
import threading
import time
import json
import hashlib

import httpx
import feedparser
from bs4 import BeautifulSoup

from src.core.config_models import Settings
from src.db.database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class NewsCollector:
    """
    Сборщик новостей для Genesis Trading System.
    
    Атрибуты:
        config: Конфигурация системы
        db_manager: Менеджер базы данных
    """
    
    def __init__(self, config: Settings, db_manager: DatabaseManager):
        """
        Инициализация сборщика новостей.
        
        Args:
            config: Конфигурация системы
            db_manager: Менеджер базы данных
        """
        self.config = config
        self.db_manager = db_manager
        
        # API ключи
        self.finnhub_api_key = config.FINNHUB_API_KEY
        self.newsapi_key = config.NEWS_API_KEY
        self.fcs_api_key = config.FCS_API_KEY
        
        # Настройки
        self.symbols = config.SYMBOLS_WHITELIST
        self.important_entities = getattr(config, 'IMPORTANT_NEWS_ENTITIES', [
            'USD', 'EUR', 'GBP', 'JPY', 'Fed', 'ECB', 'NFP', 'CPI'
        ])
        
        # Кэш
        self._news_cache: List[Dict[str, Any]] = []
        self._last_fetch_time: Optional[datetime] = None
        
        # Блокировка
        self._lock = threading.Lock()
        
        # Статистика
        self.stats = {
            'news_collected': 0,
            'last_collection_time': None,
            'sources_used': 0,
            'errors': 0
        }
        
        logger.info("News Collector инициализирован")
        logger.info(f"  - Символы: {len(self.symbols)}")
        logger.info(f"  - Важные сущности: {len(self.important_entities)}")
    
    async def fetch_finnhub_news(
        self,
        symbol: str = 'forex',
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Загружает новости из Finnhub API.
        
        Args:
            symbol: Категория (forex, stock, crypto)
            start_date: Дата начала
            end_date: Дата конца
            
        Returns:
            Список новостей
        """
        if not self.finnhub_api_key:
            logger.warning("Finnhub API ключ не настроен")
            return []
        
        try:
            if start_date is None:
                start_date = datetime.now() - timedelta(days=7)
            if end_date is None:
                end_date = datetime.now()
            
            url = 'https://finnhub.io/api/v1/news'
            params = {
                'category': symbol,
                'token': self.finnhub_api_key
            }

            # ИСПРАВЛЕНИЕ: отключаем прокси
            async with httpx.AsyncClient(timeout=10.0, proxy=None) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            
            news_list = []
            for item in data[:50]:  # Ограничиваем 50 новостями
                news = {
                    'id': hashlib.md5(item['headline'].encode()).hexdigest(),
                    'source': 'Finnhub',
                    'headline': item.get('headline', ''),
                    'summary': item.get('summary', ''),
                    'url': item.get('url', ''),
                    'published_at': datetime.fromtimestamp(item.get('datetime', 0)),
                    'sentiment': self._analyze_sentiment_simple(item.get('headline', '')),
                    'symbols': self._extract_symbols(item.get('headline', '') + ' ' + item.get('summary', '')),
                    'category': 'forex'
                }
                news_list.append(news)
            
            logger.info(f"Загружено {len(news_list)} новостей из Finnhub")
            return news_list
            
        except Exception as e:
            logger.error(f"Ошибка загрузки Finnhub новостей: {e}")
            self.stats['errors'] += 1
            return []
    
    async def fetch_newsapi_news(
        self,
        query: str = 'forex OR currency OR Fed OR ECB',
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Загружает новости из NewsAPI.org.
        
        Args:
            query: Поисковый запрос
            days: Количество дней
            
        Returns:
            Список новостей
        """
        if not self.newsapi_key:
            logger.warning("NewsAPI ключ не настроен")
            return []
        
        try:
            from_date = datetime.now() - timedelta(days=days)

            url = 'https://newsapi.org/v2/everything'
            params = {
                'q': query,
                'from': from_date.strftime('%Y-%m-%d'),
                'sortBy': 'publishedAt',
                'apiKey': self.newsapi_key,
                'language': 'en'
            }

            # ИСПРАВЛЕНИЕ: отключаем прокси
            async with httpx.AsyncClient(timeout=10.0, proxy=None) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            
            news_list = []
            for item in data.get('articles', [])[:50]:
                news = {
                    'id': hashlib.md5(item['title'].encode()).hexdigest(),
                    'source': 'NewsAPI',
                    'headline': item.get('title', ''),
                    'summary': item.get('description', ''),
                    'url': item.get('url', ''),
                    'published_at': datetime.fromisoformat(item['publishedAt'].replace('Z', '+00:00')),
                    'sentiment': self._analyze_sentiment_simple(item.get('title', '')),
                    'symbols': self._extract_symbols(item.get('title', '') + ' ' + item.get('description', '')),
                    'category': 'general'
                }
                news_list.append(news)
            
            logger.info(f"Загружено {len(news_list)} новостей из NewsAPI")
            return news_list
            
        except Exception as e:
            logger.error(f"Ошибка загрузки NewsAPI новостей: {e}")
            self.stats['errors'] += 1
            return []
    
    async def fetch_rss_news(self, rss_urls: List[str]) -> List[Dict[str, Any]]:
        """
        Загружает новости из RSS лент.
        
        Args:
            rss_urls: Список URL RSS лент
            
        Returns:
            Список новостей
        """
        news_list = []
        
        for url in rss_urls:
            try:
                # ИСПРАВЛЕНИЕ: отключаем прокси
                async with httpx.AsyncClient(timeout=10.0, proxy=None) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    
                feed = feedparser.parse(response.text)
                
                for entry in feed.entries[:20]:
                    news = {
                        'id': hashlib.md5(entry.title.encode()).hexdigest(),
                        'source': feed.feed.get('title', 'RSS'),
                        'headline': entry.title,
                        'summary': entry.get('summary', ''),
                        'url': entry.get('link', ''),
                        'published_at': datetime.fromtimestamp(time.mktime(entry.published_parsed)) if hasattr(entry, 'published_parsed') else datetime.now(),
                        'sentiment': self._analyze_sentiment_simple(entry.title),
                        'symbols': self._extract_symbols(entry.title),
                        'category': 'rss'
                    }
                    news_list.append(news)
                
            except Exception as e:
                logger.error(f"Ошибка загрузки RSS {url}: {e}")
                self.stats['errors'] += 1
        
        logger.info(f"Загружено {len(news_list)} новостей из RSS")
        return news_list
    
    async def fetch_all_news(self) -> List[Dict[str, Any]]:
        """
        Загружает новости из всех источников.
        
        Returns:
            Объединённый список новостей
        """
        logger.info("Запуск сбора новостей из всех источников...")
        start_time = time.time()
        
        # RSS ленты (бесплатно)
        rss_urls = [
            'https://www.forexfactory.com/rss.php',
            'https://www.investing.com/rss/news.rss',
            'https://www.reutersagency.com/feed/'
        ]
        
        # Запускаем все источники параллельно
        tasks = [
            self.fetch_finnhub_news('forex'),
            self.fetch_newsapi_news('forex OR currency OR Fed'),
            self.fetch_rss_news(rss_urls)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Объединяем результаты
        all_news = []
        for result in results:
            if isinstance(result, list):
                all_news.extend(result)
        
        # Удаляем дубликаты
        unique_news = {news['id']: news for news in all_news}
        all_news = list(unique_news.values())
        
        # Сортируем по времени
        all_news.sort(key=lambda x: x['published_at'], reverse=True)
        
        elapsed = time.time() - start_time
        self.stats['news_collected'] += len(all_news)
        self.stats['last_collection_time'] = datetime.now()
        self.stats['sources_used'] = 3
        
        logger.info(
            f"Сбор новостей завершён за {elapsed:.1f} сек. "
            f"Найдено {len(all_news)} уникальных новостей"
        )
        
        return all_news
    
    def _analyze_sentiment_simple(self, text: str) -> float:
        """
        Простой анализ сентимента по ключевым словам.
        
        Args:
            text: Текст для анализа
            
        Returns:
            Число от -1.0 (негатив) до 1.0 (позитив)
        """
        text = text.lower()
        
        positive_words = [
            'rise', 'gain', 'increase', 'grow', 'positive', 'bullish',
            'up', 'higher', 'strong', 'beat', 'exceed', 'optimistic'
        ]
        
        negative_words = [
            'fall', 'drop', 'decrease', 'decline', 'negative', 'bearish',
            'down', 'lower', 'weak', 'miss', 'fail', 'pessimistic', 'crash'
        ]
        
        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0  # Нейтрально
        
        sentiment = (positive_count - negative_count) / total
        return round(sentiment, 2)
    
    def _extract_symbols(self, text: str) -> List[str]:
        """
        Извлекает упомянутые символы/валюты из текста.
        
        Args:
            text: Текст новости
            
        Returns:
            Список символов
        """
        symbols = []
        text_upper = text.upper()
        
        # Извлекаем валюты
        currency_map = {
            'USD': ['USD', 'US DOLLAR', 'DOLLAR'],
            'EUR': ['EUR', 'EURO'],
            'GBP': ['GBP', 'BRITISH POUND', 'POUND'],
            'JPY': ['JPY', 'JAPANESE YEN', 'YEN'],
            'CHF': ['CHF', 'SWISS FRANC'],
            'AUD': ['AUD', 'AUSTRALIAN DOLLAR'],
            'CAD': ['CAD', 'CANADIAN DOLLAR'],
            'NZD': ['NZD', 'NEW ZEALAND DOLLAR']
        }
        
        for symbol, variants in currency_map.items():
            if any(variant in text_upper for variant in variants):
                symbols.append(symbol)
        
        # Извлекаем важные сущности
        for entity in self.important_entities:
            if entity.upper() in text_upper and entity not in symbols:
                symbols.append(entity)
        
        return symbols
    
    def save_to_database(self, news_list: List[Dict[str, Any]]):
        """
        Сохраняет новости в базу данных.
        
        Args:
            news_list: Список новостей
        """
        try:
            # Создаём таблицу
            self.db_manager.Session.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id TEXT PRIMARY KEY,
                    source TEXT,
                    headline TEXT,
                    summary TEXT,
                    url TEXT,
                    published_at DATETIME,
                    sentiment REAL,
                    symbols TEXT,
                    category TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Сохраняем новости
            for news in news_list:
                self.db_manager.Session.execute("""
                    INSERT OR REPLACE INTO news 
                    (id, source, headline, summary, url, published_at, sentiment, symbols, category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    news['id'],
                    news['source'],
                    news['headline'],
                    news['summary'],
                    news['url'],
                    news['published_at'],
                    news['sentiment'],
                    json.dumps(news['symbols']),
                    news['category']
                ))
            
            self.db_manager.Session.commit()
            logger.info(f"Сохранено {len(news_list)} новостей в БД")
            
        except Exception as e:
            logger.error(f"Ошибка сохранения новостей в БД: {e}")
            self.db_manager.Session.rollback()
    
    def get_recent_news(
        self,
        symbol: Optional[str] = None,
        hours: int = 24,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Получает последние новости из базы.
        
        Args:
            symbol: Фильтр по символу (опционально)
            hours: За сколько часов
            limit: Максимальное количество
            
        Returns:
            Список новостей
        """
        try:
            from_time = datetime.now() - timedelta(hours=hours)
            
            query = """
                SELECT * FROM news
                WHERE published_at >= ?
            """
            params = [from_time]
            
            if symbol:
                query += " AND symbols LIKE ?"
                params.append(f'%{symbol}%')
            
            query += " ORDER BY published_at DESC LIMIT ?"
            params.append(limit)
            
            df = pd.read_sql_query(query, self.db_manager.engine, params=params)
            
            news_list = []
            for _, row in df.iterrows():
                news = {
                    'id': row['id'],
                    'source': row['source'],
                    'headline': row['headline'],
                    'summary': row['summary'],
                    'url': row['url'],
                    'published_at': row['published_at'],
                    'sentiment': row['sentiment'],
                    'symbols': json.loads(row['symbols']) if row['symbols'] else [],
                    'category': row['category']
                }
                news_list.append(news)
            
            return news_list
            
        except Exception as e:
            logger.error(f"Ошибка получения новостей из БД: {e}")
            return []
    
    def get_news_sentiment(
        self,
        symbol: str,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Получает агрегированный сентимент новостей для символа.
        
        Args:
            symbol: Торговый инструмент
            hours: За сколько часов
            
        Returns:
            Словарь со статистикой сентимента
        """
        news_list = self.get_recent_news(symbol, hours)
        
        if not news_list:
            return {
                'symbol': symbol,
                'sentiment_avg': 0.0,
                'sentiment_sum': 0.0,
                'news_count': 0,
                'positive': 0,
                'negative': 0,
                'neutral': 0
            }
        
        sentiments = [news['sentiment'] for news in news_list]
        
        return {
            'symbol': symbol,
            'sentiment_avg': sum(sentiments) / len(sentiments),
            'sentiment_sum': sum(sentiments),
            'news_count': len(news_list),
            'positive': sum(1 for s in sentiments if s > 0),
            'negative': sum(1 for s in sentiments if s < 0),
            'neutral': sum(1 for s in sentiments if s == 0)
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику сборщика."""
        return {
            **self.stats,
            'symbols_monitored': len(self.symbols)
        }


class NewsCollectorScheduler:
    """
    Планировщик для автоматического сбора новостей.
    """
    
    def __init__(self, news_collector: NewsCollector, config: Settings):
        """
        Инициализация планировщика.
        
        Args:
            news_collector: Сборщик новостей
            config: Конфигурация системы
        """
        self.news_collector = news_collector
        self.config = config
        
        # Интервал сбора (в минутах)
        self.collection_interval = getattr(config, 'NEWS_COLLECTION_INTERVAL_MINUTES', 30)
        
        # Флаг работы
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        logger.info(f"News Collector Scheduler инициализирован (интервал: {self.collection_interval} мин)")
    
    def start(self):
        """Запускает планировщик."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        logger.info("News Collector Scheduler запущен")
    
    def stop(self):
        """Останавливает планировщик."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("News Collector Scheduler остановлен")
    
    def _run_loop(self):
        """Основной цикл планировщика."""
        logger.info("Запуск цикла сбора новостей...")
        
        while self._running:
            try:
                # Сбор новостей
                logger.info("Запуск сбора новостей...")
                
                # Запускаем асинхронный сбор
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    news_list = loop.run_until_complete(self.news_collector.fetch_all_news())
                    self.news_collector.save_to_database(news_list)
                finally:
                    loop.close()
                
                # Пауза до следующего сбора
                logger.info(f"Следующий сбор через {self.collection_interval} мин")
                
                for _ in range(self.collection_interval * 60):
                    if not self._running:
                        break
                    time.sleep(1)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле сбора новостей: {e}")
                time.sleep(60)
    
    def collect_now(self):
        """Запускает сбор новостей немедленно."""
        logger.info("Запуск немедленного сбора новостей...")
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            news_list = loop.run_until_complete(self.news_collector.fetch_all_news())
            self.news_collector.save_to_database(news_list)
            logger.info(f"Собрано {len(news_list)} новостей")
        finally:
            loop.close()
        
        return len(news_list)
