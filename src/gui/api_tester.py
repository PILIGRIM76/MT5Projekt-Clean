# src/gui/api_tester.py
from typing import Tuple

import httpx


class ApiTester:
    """Содержит СИНХРОННЫЕ методы для проверки валидности различных API ключей."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        # ИСПРАВЛЕНИЕ: отключаем прокси
        self.client = httpx.Client(timeout=10, proxy=None)

    def test_finnhub(self) -> Tuple[bool, str]:
        """Тестирует ключ Finnhub, запрашивая профиль Apple."""
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token={self.api_key}"
        try:
            response = self.client.get(url)
            if response.status_code == 200 and response.json():
                return True, "Ключ валиден"
            elif response.status_code in [401, 403]:
                return False, f"Ошибка {response.status_code}: Неверный ключ"
            else:
                return False, f"Ошибка {response.status_code}"
        except Exception as e:
            return False, f"Ошибка сети: {str(e)[:50]}"

    def test_newsapi(self) -> Tuple[bool, str]:
        """Тестирует NewsAPI, запрашивая источники."""
        url = f"https://newsapi.org/v2/top-headlines/sources?apiKey={self.api_key}"
        try:
            response = self.client.get(url)
            data = response.json()
            if response.status_code == 200 and data.get("status") == "ok":
                return True, "Ключ валиден"
            else:
                return False, data.get("message", f"Ошибка {response.status_code}")
        except Exception as e:
            return False, f"Ошибка сети: {str(e)[:50]}"

    def test_santiment(self) -> Tuple[bool, str]:
        """Тестирует Santiment API простым GraphQL запросом."""
        url = "https://api.santiment.net/graphql"
        query = """
        {
          getMetric(metric: "price_usd") {
            timeseriesData(slug: "santiment", from: "utc_now-1d", to: "utc_now", interval: "1d") { value }
          }
        }
        """
        try:
            response = self.client.post(url, json={"query": query}, headers={"Authorization": f"Apikey {self.api_key}"})
            data = response.json()
            if "errors" not in data:
                return True, "Ключ валиден"
            else:
                return False, data["errors"][0]["message"]
        except Exception as e:
            return False, f"Ошибка сети: {str(e)[:50]}"

    def test_key(self, service_name: str) -> Tuple[bool, str]:
        """Диспетчер, вызывающий нужный тест на основе имени сервиса."""
        service_name_lower = service_name.lower()
        if "finnhub" in service_name_lower:
            return self.test_finnhub()
        elif "news_api" in service_name_lower:
            return self.test_newsapi()
        elif "santiment" in service_name_lower:
            return self.test_santiment()
        # Добавьте сюда другие тесты по аналогии
        else:
            return False, "Тест не реализован"
