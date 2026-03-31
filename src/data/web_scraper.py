# src/data/web_scraper.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx
import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def scrape_investing_calendar(client: httpx.AsyncClient) -> pd.DataFrame:
    """
    Асинхронно скрейпит экономический календарь с Investing.com и возвращает DataFrame.
    Внедрен механизм повторных попыток для устойчивости к таймаутам и редиректам.
    """
    logger.info("Запуск асинхронного скрейпинга экономического календаря с Investing.com...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }
    calendar_url = "https://www.investing.com/economic-calendar/"

    MAX_RETRIES = 3
    INITIAL_TIMEOUT = 30  # Увеличиваем базовый таймаут до 30 секунд

    for attempt in range(MAX_RETRIES):
        try:
            # --- ИСПРАВЛЕНИЕ: Добавлен follow_redirects=True ---
            response = await client.get(
                calendar_url,
                headers=headers,
                timeout=INITIAL_TIMEOUT + attempt * 10,
                follow_redirects=True,  # Исправляет ошибку 308 Permanent Redirect
            )
            response.raise_for_status()

            # Парсинг остается синхронным, но выполняется после асинхронного запроса
            soup = BeautifulSoup(response.text, "lxml")
            table = soup.find("table", id="economicCalendarData")

            if not table:
                logger.error("Не удалось найти таблицу экономического календаря на странице.")
                return pd.DataFrame()

            events = []
            rows = table.find_all("tr", class_="js-event-item")

            for row in rows:
                time_str = row.find("td", class_="time").text.strip()
                currency_tag = row.find("td", class_="flagCur")
                currency = currency_tag.text.strip() if currency_tag else "N/A"

                importance_tag = row.find("td", class_="sentiment")
                importance = 0
                if importance_tag:
                    bulls = importance_tag.find_all("i", class_="grayFullBull")
                    importance = len(bulls)

                event_name_tag = row.find("td", class_="event")
                event_name = event_name_tag.text.strip() if event_name_tag else "N/A"

                if time_str and currency != "N/A" and importance > 0:
                    try:
                        event_time = datetime.strptime(time_str, "%H:%M").time()
                        events.append(
                            {"time": event_time, "currency": currency, "importance": importance, "event": event_name}
                        )
                    except ValueError:
                        continue

            df = pd.DataFrame(events)
            logger.info(f"Скрейпинг календаря завершен. Найдено {len(df)} событий.")
            return df

        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            logger.warning(f"Ошибка сети при скрейпинге календаря (Попытка {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2**attempt)
                continue
            else:
                logger.error("Скрейпинг календаря не удался после всех повторных попыток.")
                return pd.DataFrame()

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP ошибка {e.response.status_code} при скрейпинге: {e}")
            return pd.DataFrame()

        except Exception as e:
            logger.error(f"Непредвиденная ошибка при скрейпинге календаря: {e}", exc_info=True)
            return pd.DataFrame()

    return pd.DataFrame()


# --- ЗАГЛУШКИ ДЛЯ БУДУЩИХ СКРЕЙПЕРОВ ---


def scrape_central_bank_news() -> List[Dict[str, Any]]:
    """
    (ЗАГЛУШКА) В будущем будет скрейпить тексты с сайтов ЦБ.
    """
    logger.info("Скрейпинг сайтов ЦБ (заглушка)...")
    return []


def scrape_reddit_sentiment() -> List[Dict[str, Any]]:
    """
    (ЗАГЛУШКА) В будущем будет скрейпить Reddit для анализа сентимента.
    """
    logger.info("Скрейпинг Reddit (заглушка)...")
    return []
