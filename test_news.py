"""
test_news.py — Минимальный тест сбора новостей

Запуск:
    python test_news.py

Проверяет:
1. Подключение к Finnhub API
2. Подключение к NewsAPI.org
3. RSS ленты
4. Анализ сентимента
"""

import asyncio
import logging
import sys
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def test_news_collector():
    """Тест сбора новостей."""
    try:
        from unittest.mock import Mock

        from src.core.services_container import get_config

        logger.info("=" * 60)
        logger.info("📰 ТЕСТ СБОРА НОВОСТЕЙ")
        logger.info("=" * 60)

        # 1. Загружаем конфиг
        logger.info("1. Загрузка конфигурации...")
        config = get_config()
        logger.info(f"   ✓ Config загружен")
        logger.info(f"   - FINNHUB_API_KEY: {'✅' if config.FINNHUB_API_KEY else '❌'}")
        logger.info(f"   - NEWS_API_KEY: {'✅' if config.NEWS_API_KEY else '❌'}")

        # 2. Создаём мок для db_manager
        logger.info("2. Создание mock DatabaseManager...")
        db_manager = Mock()
        db_manager.Session = Mock()
        db_manager.engine = Mock()
        logger.info(f"   ✓ Mock DatabaseManager создан")

        # 3. Создаем NewsCollector
        logger.info("3. Создание NewsCollector...")
        from src.data.news_collector import NewsCollector

        news_collector = NewsCollector(config=config, db_manager=db_manager)
        logger.info(f"   ✓ NewsCollector создан")

        # 4. Тест Finnhub
        logger.info("4. Тест Finnhub API...")
        finnhub_news = await news_collector.fetch_finnhub_news("forex")
        logger.info(f"   {'✅' if finnhub_news else '⚠️'} Finnhub: {len(finnhub_news)} новостей")
        if finnhub_news:
            logger.info(f"   Пример: {finnhub_news[0]['headline'][:80]}...")
            logger.info(f"   Сентимент: {finnhub_news[0]['sentiment']}")

        # 5. Тест NewsAPI
        logger.info("5. Тест NewsAPI.org...")
        newsapi_news = await news_collector.fetch_newsapi_news("forex OR Fed", days=1)
        logger.info(f"   {'✅' if newsapi_news else '⚠️'} NewsAPI: {len(newsapi_news)} новостей")
        if newsapi_news:
            logger.info(f"   Пример: {newsapi_news[0]['headline'][:80]}...")
            logger.info(f"   Сентимент: {newsapi_news[0]['sentiment']}")

        # 6. Тест RSS
        logger.info("6. Тест RSS лент...")
        rss_urls = [
            "https://www.forexfactory.com/rss.php",
            "https://www.investing.com/rss/news.rss",
        ]
        rss_news = await news_collector.fetch_rss_news(rss_urls)
        logger.info(f"   {'✅' if rss_news else '⚠️'} RSS: {len(rss_news)} новостей")
        if rss_news:
            logger.info(f"   Пример: {rss_news[0]['headline'][:80]}...")

        # 7. Тест полного сбора
        logger.info("7. Полный сбор всех источников...")
        all_news = await news_collector.fetch_all_news()
        logger.info(f"   ✅ Всего: {len(all_news)} уникальных новостей")

        # 8. Анализ сентимента
        if all_news:
            sentiments = [n["sentiment"] for n in all_news]
            avg_sentiment = sum(sentiments) / len(sentiments)
            logger.info(f"   Средний сентимент: {avg_sentiment:.2f}")
            logger.info(f"   - Позитив: {sum(1 for s in sentiments if s > 0)}")
            logger.info(f"   - Нейтрально: {sum(1 for s in sentiments if s == 0)}")
            logger.info(f"   - Негатив: {sum(1 for s in sentiments if s < 0)}")

        # 9. Сохранение в БД (мок)
        logger.info("9. Сохранение в базу данных (mock)...")
        news_collector.save_to_database(all_news)
        logger.info(f"   ✅ Сохранено {len(all_news)} новостей")

        logger.info("=" * 60)
        logger.info("✅ ТЕСТ ЗАВЕРШЕН УСПЕШНО")
        logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"❌ Ошибка теста: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    result = asyncio.run(test_news_collector())
    sys.exit(0 if result else 1)
