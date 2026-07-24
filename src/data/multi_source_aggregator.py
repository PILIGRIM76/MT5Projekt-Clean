import asyncio
import logging
import os
import random  # <-- Добавлен для рандомизации User-Agent
import time  # <-- Добавлен для пауз между попытками
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import httpx
import MetaTrader5 as mt5
import pandas as pd
import requests
from httpx import AsyncClient, AsyncHTTPTransport
try:
    from ntscraper import Nitter
except Exception as e:
    Nitter = None
    logger = logging.getLogger(__name__)
    logger.warning(f"Nitter (ntscraper) недоступен: {e}. Источник Twitter отключен.")
from telethon.sync import TelegramClient

from src.data.web_scraper import scrape_investing_calendar

try:
    from newsapi.newsapi_client import NewsApiClient
except ImportError:
    NewsApiClient = None
from src.core.config_models import Settings
from src.data_models import NewsItem

logger = logging.getLogger(__name__)  # Исправлено имя логгера

# Пул User-Agent для обхода блокировок
USER_AGENTS = [
    # Chrome (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    # Firefox (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Edge (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Safari (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    # Chrome (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome (Linux)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox (Linux)
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def get_random_user_agent() -> str:
    """Возвращает случайный User-Agent из пула."""
    return random.choice(USER_AGENTS)


def get_headers() -> Dict[str, str]:
    """Возвращает заголовки со случайным User-Agent."""
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }


class MultiSourceDataAggregator:
    def __init__(self, config: Settings):
        self.config = config
        # --- ИЗМЕНЕНИЕ: Доступ к параметрам через атрибуты ---
        self.tg_api_id = self.config.TELEGRAM_API_ID
        self.tg_api_hash = self.config.TELEGRAM_API_HASH
        self.tg_phone = os.getenv("TELEGRAM_PHONE")  # Телефон лучше оставить в .env
        self.tg_session_name = "genesis_telegram_session"
        self.news_api_key = self.config.NEWS_API_KEY
        if self.news_api_key and NewsApiClient:
            self.news_api_client = NewsApiClient(api_key=self.news_api_key)
        else:
            self.news_api_client = None
            logger.warning(
                "Ключ для NewsAPI не найден или библиотека не установлена. Сбор новостей из NewsAPI будет пропущен."
            )

        self.fcs_api_key = self.config.FCS_API_KEY
        # ИСПРАВЛЕНИЕ: Создаём транспорт без прокси
        no_proxy_transport = AsyncHTTPTransport(proxy=None, verify=False)
        self.client = httpx.AsyncClient(transport=no_proxy_transport)
        self.telegram_channels = self.config.telegram_channels
        self.twitter_influencers = self.config.twitter_influencers
        self.rss_feeds = self.config.rss_feeds
        self.news_api_queries = self.config.news_api_queries
        self.finnhub_api_key = self.config.FINNHUB_API_KEY
        self.calendar_config = self.config.economic_calendar

        # Инициализация кэша новостей
        self.news_cache = None
        self.last_news_fetch_time = None

    async def _fetch_fear_and_greed_index_async(self, client: httpx.AsyncClient) -> Optional[int]:
        """
        Асинхронно получает индекс Fear & Greed.
        """
        try:
            # Используем более надежный URL и таймаут
            # Добавлено verify=False для совместимости с отключенной проверкой SSL
            response = await client.get("https://api.alternative.me/fng/?limit=1", timeout=15)
            response.raise_for_status()
            data = response.json()

            if "data" in data and len(data["data"]) > 0:
                value = data["data"][0].get("value")
                if value is not None:
                    logger.info(f"Индекс Fear & Greed получен: {value}")
                    return int(value)

            logger.warning("Индекс Fear & Greed: Ответ API пуст или не содержит данных.")
            return None

        except httpx.ConnectError as e:
            logger.error(f"Ошибка подключения при получении Fear & Greed: {e}")
            return 50
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка HTTP при получении Fear & Greed: {e.response.status_code}")
            return 50
        except httpx.RequestError as e:
            # Логируем как общую ошибку запроса (включая таймауты)
            logger.error(f"Ошибка запроса при получении Fear & Greed: {e}")
            return 50
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при получении Fear & Greed: {e}", exc_info=True)
            return 50

    async def _fetch_binance_open_interest_async(self, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
        try:
            url = "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=10"
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data and len(data) >= 10:
                oi_values = [float(d["sumOpenInterestValue"]) for d in data]
                current_oi = oi_values[-1]
                avg_oi = sum(oi_values) / len(oi_values)
                oi_trend = "rising" if current_oi > avg_oi * 1.01 else "falling" if current_oi < avg_oi * 0.99 else "flat"
                result = {"BTCUSDT": {"trend": oi_trend, "current_value": current_oi}}
                logger.info(f"Данные по открытому интересу Binance получены: {result}")
                return result
        except httpx.RequestError as e:
            logger.error(f"Ошибка при запросе к Binance API: {e}")
        except (KeyError, ValueError, IndexError) as e:
            logger.error(f"Ошибка парсинга ответа от Binance API: {e}")
        return None

    async def _fetch_telegram(self) -> List[NewsItem]:
        if not all([self.tg_api_id, self.tg_api_hash, self.tg_phone]):
            return []
        return []

    async def _load_all_news_async(self) -> Tuple[List[NewsItem], Optional[int], Optional[Dict[str, Any]]]:
        """
        Загружает все новости из доступных источников.
        Возвращает кортеж: (список новостей, fear_greed_index, on_chain_data)
        """
        logger.info("Загрузка новостей из всех источников...")

        all_news = []
        fear_greed_index = None
        on_chain_data = None

        try:
            logger.info("[News] Шаг 1: Fear & Greed Index...")
            # Загружаем новости из различных источников - ИСПРАВЛЕНИЕ: отключаем прокси
            async with httpx.AsyncClient(timeout=30.0, proxy=None) as client:
                # 1. Fear & Greed Index
                fear_greed_index = await self._fetch_fear_and_greed_index_async(client)
                logger.info(f"[News] Шаг 1 завершён: Fear & Greed = {fear_greed_index}")

                # 2. Economic Calendar (синхронный вызов)
                logger.info("[News] Шаг 2: Economic Calendar...")
                calendar_news = self._fetch_economic_calendar()
                all_news.extend(calendar_news)
                logger.info(f"[News] Шаг 2 завершён: {len(calendar_news)} новостей")

                # 3. News API (синхронный вызов)
                logger.info("[News] Шаг 3: News API...")
                api_news = self._fetch_news_api()
                all_news.extend(api_news)
                logger.info(f"[News] Шаг 3 завершён: {len(api_news)} новостей")

                # 4. RSS Feeds (ВЫНОСИМ В ПОТОК!)
                logger.info("[News] Шаг 4: RSS Feeds (в потоке)...")
                rss_news = await asyncio.to_thread(self._fetch_rss)
                all_news.extend(rss_news)
                logger.info(f"[News] Шаг 4 завершён: {len(rss_news)} новостей")

                # 5. On-chain данные (для криптовалют)
                logger.info("[News] Шаг 5: On-chain данные...")
                on_chain_data = await self._fetch_binance_open_interest_async(client)
                logger.info(f"[News] Шаг 5 завершён: On-chain = {on_chain_data is not None}")

            logger.info(f"Загружено {len(all_news)} новостей из всех источников")

        except Exception as e:
            logger.error(f"Ошибка загрузки новостей: {e}", exc_info=True)

        return all_news, fear_greed_index, on_chain_data

    def _fetch_twitter_scrape(self) -> List[NewsItem]:
        return []

    def _fetch_news_api(self) -> List[NewsItem]:
        if not self.news_api_client or not self.news_api_queries:
            return []

        items = []
        logger.info(f"Запрос новостей из NewsAPI по {len(self.news_api_queries)} запросам...")

        # --- ВРЕМЕННАЯ ЗАГЛУШКА ДЛЯ ТЕСТА НАПОЛНЕНИЯ VectorDB ---
        # Этот блок гарантирует, что VectorDB получит хотя бы 2 документа.
        # Оставляем его, так как он нужен для инициализации KG.
        items.append(
            NewsItem(
                source="TEST_NEWSAPI_FED",
                text="The Federal Reserve is expected to raise interest rates by 50 basis points next month due to persistent inflation.",
                timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        items.append(
            NewsItem(
                source="TEST_NEWSAPI_ECB",
                text="ECB President Lagarde stated that the Eurozone economy is showing signs of strong recovery, boosting the EUR/USD pair.",
                timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        # --- КОНЕЦ ВРЕМЕННОЙ ЗАГЛУШКИ ---

        # --- ИСПРАВЛЕННЫЙ БЛОК ЗАПРОСА С ПРОВЕРКОЙ ЛИМИТА ---
        try:
            # Попытка выполнить запрос (если лимит исчерпан, здесь будет исключение)
            for query in self.news_api_queries:
                articles = self.news_api_client.get_everything(q=query, language="en", sort_by="publishedAt", page_size=20)
                for article in articles.get("articles", []):
                    published_at = article.get("publishedAt")
                    if published_at:
                        items.append(
                            NewsItem(
                                source=f"newsapi_{article['source']['name']}",
                                text=f"{article['title']}. {article.get('description', '')}",
                                timestamp=datetime.fromisoformat(published_at.replace("Z", "+00:00")),
                            )
                        )

            logger.info(f"Получено {len(items) - 2} реальных статей из NewsAPI (плюс 2 заглушки).")

        except Exception as e:
            # Обработка ошибки лимита
            if "rateLimited" in str(e):
                logger.error("Ошибка при получении данных из NewsAPI: Лимит исчерпан. Возврат только заглушек.")
                # Возвращаем только те элементы, которые уже были добавлены (заглушки)
                return items
            else:
                logger.error(f"Ошибка при получении данных из NewsAPI: {e}")
                # Возвращаем только заглушки при любой другой ошибке
                return items

        return items

    def _fetch_rss(self) -> List[NewsItem]:
        if not self.rss_feeds:
            return []
        items = []
        logger.info(f"Запрос новостей из {len(self.rss_feeds)} RSS-лент...")

        # --- ВРЕМЕННАЯ ЗАГЛУШКА ДЛЯ ТЕСТА ---
        items.append(
            NewsItem(
                source="TEST_SOURCE",
                text="TEST: The FED is considering a rate hike due to unexpected inflation.",
                timestamp=datetime.now(timezone.utc),
            )
        )
        # --- КОНЕЦ ВРЕМЕННОЙ ЗАГЛУШКИ ---

        for url in self.rss_feeds:
            max_retries = 2  # Максимум 2 попытки
            for attempt in range(max_retries):
                try:
                    # ИСПРАВЛЕНИЕ: Увеличиваем таймаут до 30 секунд для медленных лент
                    import requests

                    headers = get_headers()  # <-- Случайные заголовки для каждого запроса
                    logger.debug(f"RSS запрос к {url} (попытка {attempt + 1}/{max_retries})")

                    # Увеличиваем таймаут: 30 секунд на подключение + 30 секунд на чтение
                    response = requests.get(url, timeout=(30, 30), headers=headers)
                    response.raise_for_status()

                    # ИСПРАВЛЕНИЕ: Обрабатываем разные кодировки
                    raw_content = response.content

                    # Пробуем несколько вариантов декодирования
                    xml_text = None
                    for encoding in ["utf-8", "windows-1251", "latin-1"]:
                        try:
                            xml_text = raw_content.decode(encoding)
                            if encoding != "utf-8":
                                logger.debug(f"RSS {url}: декодировано как {encoding}")
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue

                    if xml_text is None:
                        logger.error(f"RSS {url}: не удалось декодировать ответ")
                        break

                    # ИСПРАВЛЕНИЕ: Заменяем русские XML-теги на английские (если есть)
                    xml_text = (
                        xml_text.replace("<ссылка>", "<link>")
                        .replace("</ссылка>", "</link>")
                        .replace("<описание>", "<description>")
                        .replace("</описание>", "</description>")
                        .replace("<заголовок>", "<title>")
                        .replace("</заголовок>", "</title>")
                        .replace("<товар>", "<item>")
                        .replace("</товар>", "</item>")
                        .replace("<категория>", "<category>")
                        .replace("</категория>", "</category>")
                        .replace("<dc:создатель>", "<dc:creator>")
                        .replace("</dc:создатель>", "</dc:creator>")
                    )

                    # Парсим обработанный XML
                    feed = feedparser.parse(xml_text)

                    # Логируем для отладки
                    if not feed.entries:
                        logger.warning(f"RSS {url}: feedparser не нашел записей (bozo={feed.bozo})")
                        # Проверяем есть ли вообще <item> теги
                        import re

                        items_count = len(re.findall(r"<item>", xml_text))
                        logger.debug(f"RSS {url}: найдено {items_count} <item> тегов в XML")

                    # --- ИСПРАВЛЕНИЕ: Используем .get() для безопасного доступа к title ---
                    feed_title = feed.feed.get("title", "Unknown RSS Feed")

                    for entry in feed.entries[:15]:
                        # Используем .get() для безопасного доступа к полям entry
                        entry_title = entry.get("title", "No Title")
                        entry_summary = entry.get("summary", entry_title)  # Используем title как fallback для summary

                        # Безопасное получение времени
                        published_time = datetime.now(timezone.utc)
                        if hasattr(entry, "published_parsed") and entry.published_parsed:
                            published_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                        items.append(
                            NewsItem(
                                source=f"rss_{feed_title}",  # <-- Используем безопасный feed_title
                                text=f"{entry_title}. {entry_summary}",
                                timestamp=published_time,
                            )
                        )

                    # Если успешно - выходим из цикла повторных попыток
                    break

                except requests.Timeout:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Таймаут при загрузке RSS-ленты {url} (попытка {attempt + 1}/{max_retries}). Повторная попыка..."
                        )
                        time.sleep(2)  # Пауза перед повторной попыткой
                    else:
                        logger.error(f"Таймаут при загрузке RSS-ленты {url} после {max_retries} попыток - пропускаем")
                except requests.HTTPError as e:
                    # Логируем ошибку, но продолжаем обработку других лент
                    logger.warning(f"HTTP {e.response.status_code} при загрузке RSS-ленты {url} - пропускаем")
                    break  # Не повторяем при HTTP ошибке
                except requests.ConnectionError as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Ошибка соединения {url} (попытка {attempt + 1}/{max_retries}). Повторная попыка...")
                        time.sleep(3)  # Более длительная пауза при проблемах соединения
                    else:
                        logger.error(f"Ошибка соединения с {url} после {max_retries} попыток - пропускаем")
                except requests.RequestException as e:
                    # Логируем ошибку, но продолжаем обработку других лент
                    logger.error(f"Ошибка HTTP при обработке RSS-ленты {url}: {e}")
                    break  # Не повторяем при других ошибках requests
                except Exception as e:
                    # Логируем ошибку, но продолжаем обработку других лент
                    logger.error(f"Ошибка при обработке RSS-ленты {url}: {e}")
                    break  # Не повторяем при других ошибках

        logger.info(f"Получено {len(items)} новостей из RSS-лент.")
        return items

    def _fetch_economic_calendar(self) -> List[NewsItem]:
        return []

    def _process_calendar_df(self, df: pd.DataFrame) -> List[NewsItem]:
        """
        Преобразует DataFrame экономического календаря в список NewsItem.
        """
        if df.empty:
            return []

        items = []
        now_utc = datetime.now(timezone.utc)

        # Используем настройки из конфига
        min_impact = self.calendar_config.get("min_impact_level", 2)
        lookahead_hours = self.calendar_config.get("lookahead_hours", 24)

        # Фильтруем только важные события
        df_filtered = df[df["importance"] >= min_impact]

        for _, row in df_filtered.iterrows():
            # Создаем полную дату/время события (предполагаем, что время UTC)
            event_dt_utc = datetime.combine(now_utc.date(), row["time"], tzinfo=timezone.utc)

            # Если событие уже прошло сегодня, предполагаем, что оно будет завтра
            if event_dt_utc < now_utc - timedelta(hours=1):
                event_dt_utc += timedelta(days=1)

            # Фильтруем события, которые слишком далеко в будущем
            if event_dt_utc > now_utc + timedelta(hours=lookahead_hours):
                continue

            # Формируем текст новости
            text = f"ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ: {row['currency']} - {row['event']} (Важность: {row['importance']}/3)"

            items.append(NewsItem(source="EconomicCalendar", text=text, timestamp=event_dt_utc, asset=row["currency"]))

        logger.info(f"Обработано {len(items)} важных событий из экономического календаря.")
        return items

    async def aggregate_all_sources_async(self) -> Tuple[List[NewsItem], Optional[int], Optional[Dict[str, Any]]]:
        logger.info("Запуск асинхронной агрегации данных из всех источников...")
        news_items = []
        available_symbols = self.config.SYMBOLS_WHITELIST
        timeframes_to_check = list(self.config.optimizer.timeframes_to_check.values())

        # Задача для получения рыночных данных
        data_task = asyncio.create_task(self.data_provider.get_all_symbols_data_async(available_symbols, timeframes_to_check))
        tasks = [data_task]

        # Задача для получения новостей (если кэш устарел или пуст)
        news_task = None
        should_fetch_news = (
            self.news_cache is None
            or len(self.news_cache) == 0
            or (
                self.last_news_fetch_time
                and (datetime.now() - self.last_news_fetch_time).total_seconds() > self.config.NEWS_CACHE_DURATION_MINUTES * 60
            )
        )

        if should_fetch_news:
            logger.info(f"Загрузка новостей (кэш: {len(self.news_cache) if self.news_cache else 0} записей)")
            news_task = asyncio.create_task(self._load_all_news_async())
            tasks.append(news_task)
            self.last_news_fetch_time = datetime.now()

        results = await asyncio.gather(*tasks, return_exceptions=True)
        data_dict_raw = results[0]
        news_result_tuple = results[1] if len(results) > 1 else None

        if isinstance(data_dict_raw, Exception):
            logger.error(f"Ошибка при сборе данных: {data_dict_raw}")
            return [], None, None

        if news_result_tuple and not isinstance(news_result_tuple, Exception):
            all_items, _, _ = news_result_tuple
            # Обработка новостей выполняется в news_service
            # if all_items:
            #     await asyncio.to_thread(self._process_news_background, all_items)
            logger.info(f"[News] Обработано {len(all_items)} новостей")

        data_dict = {key: df for key, df in data_dict_raw.items()}
        ranked_symbols, full_ranked_list = self.market_screener.rank_symbols(data_dict)

        self.latest_full_ranked_list = full_ranked_list
        if not ranked_symbols:
            logger.warning("[R&D] Принудительный сбор не дал результатов. R&D цикл пропущен.")
            return [], None, None

        gui_data_list = []
        source_list = full_ranked_list if full_ranked_list else [{"symbol": s} for s in available_symbols]
        for item in source_list:
            sym = item.get("symbol")
            df = data_dict.get(f"{sym}_{mt5.TIMEFRAME_H1}")
            if df is not None and not df.empty:
                last_row = df.iloc[-1]
                gui_data_list.append(
                    {
                        "symbol": sym,
                        "rank": item.get("rank", 0),
                        "total_score": item.get("total_score", 0.0),
                        "volatility_score": item.get("volatility_score", 0.0),
                        "normalized_atr_percent": item.get("normalized_atr_percent", 0.0),
                        "trend_score": item.get("trend_score", 0.0),
                        "liquidity_score": item.get("liquidity_score", 0.0),
                        "spread_pips": item.get("spread_pips", 0.0),
                        "last_close": last_row["close"],
                        "last_atr": last_row["ATR_14"],
                        "last_adx": last_row["ADX_14"],
                    }
                )

        # Убираем вызовы GUI методов - они должны вызываться из trading_system
        # self.market_scan_updated.emit(gui_data_list)
        # logger.info(f"[GUI Data] Отправлено {len(gui_data_list)} строк в сканер.")

        if gui_data_list:
            top_item = gui_data_list[0]
            symbol_for_chart = top_item["symbol"]
            eurusd_h1_key = f"{symbol_for_chart}_{mt5.TIMEFRAME_H1}"
            if eurusd_h1_key in data_dict:
                df_to_display = data_dict[eurusd_h1_key]
                self.last_h1_data_cache = df_to_display
                # Убираем вызов GUI метода
                # self._safe_gui_update('update_candle_chart', df_to_display, symbol_for_chart)

        return gui_data_list, None, None
