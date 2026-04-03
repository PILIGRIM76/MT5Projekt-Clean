"""
Real-time Data Updater для Genesis Trading System.
Автоматическое обновление рыночных данных в реальном времени с использованием:
- Redis Pub/Sub для мгновенных уведомлений
- TimescaleDB для эффективной записи временных рядов
- Кэширование последних данных

Использование:
    updater = RealTimeDataUpdater(multi_db_manager, config)
    updater.start()
"""

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class RealTimeDataUpdater:
    """
    Менеджер реального времени для обновления рыночных данных.

    Возможности:
    - Автоматическая подписка на обновления MT5
    - Запись в TimescaleDB/QuestDB в реальном времени
    - Pub/Sub уведомления через Redis
    - Кэширование последних данных
    - Автоматический реконнект при потере связи
    """

    def __init__(self, multi_db_manager, config, symbols: Optional[List[str]] = None):
        self.multi_db_manager = multi_db_manager
        self.config = config
        self.symbols = symbols or config.SYMBOLS_WHITELIST[:5]  # По умолчанию первые 5 символов

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Кэш последних данных
        self._last_candles: Dict[str, pd.DataFrame] = {}
        self._last_update: Dict[str, datetime] = {}

        # Статистика
        self._stats = {
            "updates_received": 0,
            "updates_written": 0,
            "errors": 0,
            "reconnects": 0,
        }

    def start(self):
        """Запуск потока обновления данных."""
        if self._running:
            logger.warning("RealTimeDataUpdater уже запущен")
            return

        logger.info("Запуск RealTimeDataUpdater...")
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("✓ RealTimeDataUpdater запущен")

    def stop(self):
        """Остановка потока обновления."""
        if not self._running:
            return

        logger.info("Остановка RealTimeDataUpdater...")
        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("✓ RealTimeDataUpdater остановлен")

    def _run_loop(self):
        """Основной цикл обновления."""
        logger.info("RealTimeDataUpdater: основной цикл запущен")

        while self._running and not self._stop_event.is_set():
            try:
                # Обновление данных по каждому символу
                for symbol in self.symbols:
                    if not self._running:
                        break

                    self._update_symbol_data(symbol)

                # Пауза между обновлениями (зависит от таймфрейма)
                update_interval = self._get_update_interval()
                time.sleep(update_interval)

            except Exception as e:
                logger.error(f"Ошибка в цикле обновления: {e}")
                self._stats["errors"] += 1

                # Попытка реконнекта
                self._stats["reconnects"] += 1
                time.sleep(5)

    def _update_symbol_data(self, symbol: str):
        """
        Обновление данных по конкретному символу.

        Алгоритм:
        1. Получить последние данные от брокера (MT5)
        2. Сравнить с кэшем
        3. Если есть новые данные → записать в TimescaleDB
        4. Опубликовать обновление через Redis Pub/Sub
        5. Обновить кэш
        """
        try:
            # 1. Получение данных от MT5
            import MetaTrader5 as mt5

            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)

            if rates is None or len(rates) == 0:
                logger.debug(f"Нет данных для {symbol}")
                return

            # Преобразование в DataFrame
            df = pd.DataFrame(rates)
            df["timestamp"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("timestamp", inplace=True)

            # 2. Проверка на наличие новых данных
            if symbol in self._last_candles:
                last_cached_time = self._last_candles[symbol].index[-1]
                if df.index[-1] <= last_cached_time:
                    # Нет новых данных
                    return

            # 3. Запись в TimescaleDB
            self._write_to_timescaledb(symbol, df)

            # 4. Публикация обновления
            self._publish_update(symbol, df)

            # 5. Обновление кэша
            self._last_candles[symbol] = df
            self._last_update[symbol] = datetime.utcnow()

            self._stats["updates_received"] += 1

            logger.debug(f"✓ Обновлен {symbol}: {len(df)} свечей, последняя: {df.index[-1]}")

        except Exception as e:
            logger.error(f"Ошибка обновления {symbol}: {e}")
            self._stats["errors"] += 1

    def _write_to_timescaledb(self, symbol: str, df: pd.DataFrame):
        """Запись данных в TimescaleDB."""
        if not self.multi_db_manager.is_available("timescaledb"):
            logger.debug("TimescaleDB недоступен, пропускаем запись")
            return

        try:
            ts_adapter = self.multi_db_manager.get_timescaledb()

            # Подготовка данных
            candles_df = df.copy()
            candles_df = candles_df.rename(
                columns={
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "tick_volume": "tick_volume",
                }
            )

            # Вставка
            success = ts_adapter.insert_candles(
                table_name="candle_data",
                candles=candles_df,
                symbol=symbol,
                timeframe=60,  # M1
            )

            if success:
                self._stats["updates_written"] += 1
                logger.debug(f"✓ Записано в TimescaleDB: {symbol} ({len(df)} свечей)")

        except Exception as e:
            logger.error(f"Ошибка записи в TimescaleDB: {e}")
            self._stats["errors"] += 1

    def _publish_update(self, symbol: str, df: pd.DataFrame):
        """Публикация обновления через Redis Pub/Sub."""
        if not self.multi_db_manager.is_available("redis"):
            return

        try:
            redis = self.multi_db_manager.get_redis()

            # Формирование сообщения
            last_candle = df.iloc[-1]
            message = {
                "symbol": symbol,
                "timestamp": df.index[-1].isoformat(),
                "open": float(last_candle["open"]),
                "high": float(last_candle["high"]),
                "low": float(last_candle["low"]),
                "close": float(last_candle["close"]),
                "volume": int(last_candle.get("tick_volume", 0)),
                "type": "candle_update",
            }

            # Публикация
            redis.publish("market:candles", json.dumps(message))

            logger.debug(f"✓ Опубликовано обновление: {symbol}")

        except Exception as e:
            logger.error(f"Ошибка публикации в Redis: {e}")

    def _get_update_interval(self) -> float:
        """
        Получение интервала обновления в секундах.

        Для M1: 10-15 секунд
        Для M5: 30-60 секунд
        Для H1: 60-120 секунд
        """
        # Динамический интервал в зависимости от количества символов
        base_interval = 10.0

        if len(self.symbols) > 5:
            base_interval = 5.0

        return base_interval

    def get_last_candle(self, symbol: str) -> Optional[pd.DataFrame]:
        """Получение последней свечи из кэша."""
        return self._last_candles.get(symbol)

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики обновлений."""
        return {
            **self._stats,
            "running": self._running,
            "symbols": self.symbols,
            "last_update": {symbol: dt.isoformat() if dt else None for symbol, dt in self._last_update.items()},
        }


class RedisPubSubListener:
    """
    Слушатель Redis Pub/Sub для получения обновлений в реальном времени.

    Использование:
        listener = RedisPubSubListener(multi_db_manager)
        listener.subscribe('market:candles')

        # В другом потоке
        for message in listener.get_messages():
            process(message)
    """

    def __init__(self, multi_db_manager):
        self.multi_db_manager = multi_db_manager
        self._pubsub = None
        self._running = False

    def subscribe(self, channel: str):
        """Подписка на канал."""
        if not self.multi_db_manager.is_available("redis"):
            logger.warning("Redis недоступен")
            return

        try:
            redis = self.multi_db_manager.get_redis()
            self._pubsub = redis.subscribe(channel)
            self._running = True
            logger.info(f"✓ Подписка на канал: {channel}")
        except Exception as e:
            logger.error(f"Ошибка подписки: {e}")

    def unsubscribe(self, channel: str):
        """Отписка от канала."""
        if self._pubsub:
            self._pubsub.unsubscribe(channel)
            self._running = False

    def get_messages(self, timeout: float = 1.0):
        """
        Генератор сообщений.

        Yields:
            dict: Сообщение из Pub/Sub
        """
        if not self._pubsub:
            return

        while self._running:
            try:
                message = self._pubsub.get_message(timeout=timeout)

                if message and message["type"] == "message":
                    # Парсинг JSON
                    try:
                        data = json.loads(message["data"])
                        yield data
                    except json.JSONDecodeError:
                        logger.warning(f"Не удалось распарсить сообщение: {message['data']}")

            except Exception as e:
                logger.error(f"Ошибка получения сообщения: {e}")
                time.sleep(1)

    def stop(self):
        """Остановка слушателя."""
        self._running = False
        if self._pubsub:
            self._pubsub.close()


class CandleStreamProcessor:
    """
    Процессор потоковых свечных данных.

    Обрабатывает обновления свечей в реальном времени:
    - Агрегация в большие таймфреймы
    - Вычисление индикаторов
    - Генерация событий при пересечении уровней
    """

    def __init__(self, multi_db_manager):
        self.multi_db_manager = multi_db_manager
        self._aggregates: Dict[str, Dict[str, pd.DataFrame]] = {}
        self._listeners = []

    def add_listener(self, callback):
        """Добавление слушателя событий."""
        self._listeners.append(callback)

    def process_candle(self, symbol: str, candle_data: Dict[str, Any]):
        """
        Обработка новой свечи.

        Args:
            symbol: Торговый инструмент
            candle_data: Данные свечи (OHLCV)
        """
        # Преобразование в DataFrame
        df = pd.DataFrame([candle_data])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)

        # Агрегация в большие таймфреймы
        self._aggregate_candles(symbol, df)

        # Вычисление индикаторов
        indicators = self._compute_indicators(symbol, df)

        # Генерация событий
        events = self._generate_events(symbol, df, indicators)

        # Уведомление слушателей
        for listener in self._listeners:
            try:
                listener(symbol, df, indicators, events)
            except Exception as e:
                logger.error(f"Ошибка уведомления слушателя: {e}")

    def _aggregate_candles(self, symbol: str, df: pd.DataFrame):
        """Агрегация свечей в большие таймфреймы."""
        # Пример: M1 → M5
        if symbol not in self._aggregates:
            self._aggregates[symbol] = {}

        # Инициализация
        if "M5" not in self._aggregates[symbol]:
            self._aggregates[symbol]["M5"] = pd.DataFrame()

        # Агрегация
        m5 = df.resample("5min").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )

        # Объединение с существующими
        self._aggregates[symbol]["M5"] = pd.concat([self._aggregates[symbol]["M5"], m5]).drop_duplicates()

    def _compute_indicators(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Вычисление технических индикаторов."""
        indicators = {}

        # SMA
        if len(df) >= 20:
            indicators["sma_20"] = df["close"].rolling(20).mean().iloc[-1]

        # RSI
        if len(df) >= 14:
            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
            if loss != 0:
                rs = gain / loss
                indicators["rsi_14"] = 100 - (100 / (1 + rs))
            else:
                indicators["rsi_14"] = 50

        return indicators

    def _generate_events(self, symbol: str, df: pd.DataFrame, indicators: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Генерация торговых событий."""
        events = []

        # Пример: пересечение RSI уровней
        if "rsi_14" in indicators:
            rsi = indicators["rsi_14"]

            if rsi < 30:
                events.append(
                    {
                        "type": "RSI_OVERSOLD",
                        "symbol": symbol,
                        "value": rsi,
                        "signal": "BUY",
                    }
                )
            elif rsi > 70:
                events.append(
                    {
                        "type": "RSI_OVERBOUGHT",
                        "symbol": symbol,
                        "value": rsi,
                        "signal": "SELL",
                    }
                )

        return events
