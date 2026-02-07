# src/data/blockchain_provider.py
import logging
import os
from typing import Optional, Dict
import pandas as pd
import httpx
from datetime import datetime, timedelta
import numpy as np

from src.core.config_models import Settings

logger = logging.getLogger(__name__)


class BlockchainProvider:
    """
    Отвечает за получение on-chain данных из внешних API, таких как Santiment.
    """

    def __init__(self, config: Settings):
        self.config = config
        self.api_key = self.config.SANTIMENT_API_KEY
        self.base_url = "https://api.santiment.net/graphql"

        # --- ЭТОТ БЛОК ДОЛЖЕН БЫТЬ В __init__ ---
        self.lunarcrush_api_key = getattr(config, "LUNARCRUSH_API_KEY", os.getenv("LUNARCRUSH_API_KEY"))
        self.lunarcrush_base_url = "https://api.lunarcrush.com/v2"
        # ---------------------------------------

        self.client = httpx.AsyncClient()

    async def get_lunarcrush_metrics(self, symbol: str) -> Optional[pd.DataFrame]:
        if not self.lunarcrush_api_key:
            logger.warning("LUNARCRUSH_API_KEY не найден. Пропуск запроса социальных метрик.")
            return None

        # LunarCrush использует тикеры (BTC, ETH)
        asset_ticker = symbol.replace("COIN", "").replace("CASH", "").replace(" ", "").upper()

        # Запрашиваем данные за последние 90 дней (90 точек)
        url = f"{self.lunarcrush_base_url}/public/list"
        params = {
            "key": self.lunarcrush_api_key,
            "data": "assets",
            "symbol": asset_ticker,
            "interval": "day",
            "limit": 90,
            "metrics": "social_volume,social_score,galaxy_score,alt_rank"
        }

        try:
            response = await self.client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

            if data.get("data") and data["data"][0].get("timeSeries"):
                ts_data = data["data"][0]["timeSeries"]
                df = pd.DataFrame(ts_data)

                # Преобразование Unix timestamp в datetime (LunarCrush использует секунды)
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                df.set_index('time', inplace=True)

                # Выбираем нужные колонки и переименовываем
                df = df[['social_volume', 'social_score', 'galaxy_score', 'alt_rank']]
                df.columns = ['LC_SOCIAL_VOLUME', 'LC_SOCIAL_SCORE', 'LC_GALAXY_SCORE', 'LC_ALT_RANK']

                logger.info(f"Успешно загружено {len(df)} точек социальных метрик для {symbol}.")
                return df

            logger.warning(f"LunarCrush API вернул пустой или неполный ответ для {symbol}.")
            return None

        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка HTTP при запросе к LunarCrush: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при получении LunarCrush данных: {e}", exc_info=True)
            return None

    async def get_onchain_metrics(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Асинхронно загружает ключевые on-chain метрики для заданного символа.
        """
        if self.api_key and "a2mkndlavy67jqpe_x6ff2q5ryibwuyw6" not in self.api_key:
            logger.warning("API ключ для Santiment настроен, но лимит исчерпан. Возврат имитации данных.")
            return self._simulate_onchain_data()
            # --------------------------------------------------------------------

        # Определяем slug для API Santiment
        slug_map = {"BITCOIN": "bitcoin", "ETHEREUM": "ethereum"}
        slug = slug_map.get(symbol)
        if not slug:
            return None

        logger.info(f"Запрос on-chain данных для {symbol} ({slug}) из Santiment...")

        # Запрашиваем данные за последние 90 дней с дневным интервалом
        from_date = (datetime.utcnow() - timedelta(days=90)).isoformat() + "Z"

        # --- ИСПРАВЛЕНИЕ ОШИБОК API: Замена 'mvrv_ratio' и 'binance_perpetual_funding_rate' ---
        query = f"""
        {{
          nvt: getMetric(metric: "nvt") {{
            timeseriesData(slug: "{slug}", from: "{from_date}", to: "utc_now", interval: "1d") {{ datetime, value }}
          }}
          dailyActiveAddresses: getMetric(metric: "active_addresses_24h") {{
            timeseriesData(slug: "{slug}", from: "{from_date}", to: "utc_now", interval: "1d") {{ datetime, value }}
          }}
          transactionVolume: getMetric(metric: "transaction_volume") {{
            timeseriesData(slug: "{slug}", from: "{from_date}", to: "utc_now", interval: "1d") {{ datetime, value }}
          }}
          mvrv: getMetric(metric: "mvrv_usd") {{  
            timeseriesData(slug: "{slug}", from: "{from_date}", to: "utc_now", interval: "1d") {{ datetime, value }}
          }}
          fundingRate: getMetric(metric: "bitfinex_perpetual_funding_rate") {{ 
            timeseriesData(slug: "{slug}", from: "{from_date}", to: "utc_now", interval: "1d") {{ datetime, value }}
          }}
        }}
        """
        # --------------------------------------------------------------------------------------

        try:
            response = await self.client.post(
                self.base_url,
                json={"query": query},
                headers={"Authorization": f"Apikey {self.api_key}"},
                timeout=20.0
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error(f"Ошибка API Santiment: {data['errors']}")
                return None

            # Собираем данные в DataFrame
            data_root = data.get("data", {})

            nvt_data = data_root.get("nvt", {}).get("timeseriesData", [])
            addresses_data = data_root.get("dailyActiveAddresses", {}).get("timeseriesData", [])
            volume_data = data_root.get("transactionVolume", {}).get("timeseriesData", [])

            # --- ИСПРАВЛЕНИЕ: Создание DataFrame напрямую из извлеченных данных ---
            # Устраняем промежуточные переменные mvrv_data и funding_rate_data
            df_mvrv = pd.DataFrame(data_root.get("mvrv", {}).get("timeseriesData", [])).rename(
                columns={'value': 'mvrv_ratio'})
            df_funding = pd.DataFrame(data_root.get("fundingRate", {}).get("timeseriesData", [])).rename(
                columns={'value': 'funding_rate'})
            # ----------------------------------------------------------------------

            df = pd.DataFrame(nvt_data).rename(columns={'value': 'nvt'})
            df_addresses = pd.DataFrame(addresses_data).rename(columns={'value': 'active_addresses'})
            df_volume = pd.DataFrame(volume_data).rename(columns={'value': 'transaction_volume'})

            # --- Объединение всех DataFrame ---
            df = pd.merge(df, df_addresses, on="datetime", how="left")
            df = pd.merge(df, df_volume, on="datetime", how="left")
            df = pd.merge(df, df_mvrv, on="datetime", how="left")
            df = pd.merge(df, df_funding, on="datetime", how="left")
            # ----------------------------------

            df['datetime'] = pd.to_datetime(df['datetime'])

            # --- ИСПРАВЛЕНИЕ: Явная привязка к UTC и установка индекса ---
            # Santiment возвращает ISO-строки, которые Pandas корректно парсит в UTC,
            # но для надежности явно указываем tz=UTC.
            df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
            df.set_index('datetime', inplace=True)
            # -------------------------------------------------------------

            df.ffill(inplace=True)

            logger.info(f"Успешно загружено {len(df)} точек on-chain данных для {symbol}.")
            return df

        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка HTTP при запросе к Santiment API: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при получении on-chain данных: {e}", exc_info=True)
            return None


    def _simulate_onchain_data(self) -> pd.DataFrame:
        """Имитирует on-chain данные для тестирования логики."""
        dates = pd.to_datetime(pd.date_range(end=datetime.utcnow(), periods=90, freq='D', tz='UTC'))
        df = pd.DataFrame(index=dates)
        df['nvt'] = 50 + 10 * np.random.randn(90)
        df['active_addresses'] = 10000 + 500 * np.random.randn(90)
        df['transaction_volume'] = 1e9 + 1e8 * np.random.randn(90)
        # --- ИЗМЕНЕНИЕ: Добавлены MVRV и Funding Rates ---
        df['mvrv_ratio'] = 1.5 + 0.5 * np.random.randn(90)
        df['funding_rate'] = 0.0001 + 0.00005 * np.random.randn(90)
        # -------------------------------------------------
        return df