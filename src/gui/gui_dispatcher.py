# -*- coding: utf-8 -*-
"""
GUI Traffic Dispatcher — разделяет обновления GUI на 3 независимых канала.

Предотвращает:
- Залипание эквити из-за блокировки графики
- Тормоза интерфейса при частой перерисовке
- Потерю сигналов в очереди
"""

import logging
import time
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)


class GUIDispatcher(QObject):
    """
    Разделяет обновления GUI на 3 независимых канала:
    1. Эквити/Прибыль (высокий приоритет, каждые 3 сек)
    2. Сигналы/Ордера (мгновенный, событийный)
    3. Графики (низкий приоритет, каждые 10 сек)
    """

    # 🔹 КАНАЛ 1: Эквити/Прибыль (высокий приоритет, частый)
    equity_data_ready = Signal(dict)  # {'balance': float, 'equity': float, 'profit': float}

    # 🔹 КАНАЛ 2: Сигналы/Ордера (мгновенный, событийный)
    trade_signal_ready = Signal(dict)  # {'symbol': str, 'signal_type': str, 'price': float}

    # 🔹 КАНАЛ 3: Графики (низкий приоритет, редкий)
    chart_data_ready = Signal(dict)  # {'symbol': str, 'df': DataFrame, 'timeframe': str}

    def __init__(
        self,
        equity_interval_ms: int = 3000,
        chart_interval_ms: int = 10000,
    ):
        super().__init__()

        # 🔹 Таймер для эквити (каждые 3 секунды по умолчанию)
        self.equity_timer = QTimer(self)
        self.equity_timer.timeout.connect(self._on_equity_timer)
        self.equity_timer.start(equity_interval_ms)

        # 🔹 Таймер для графика (каждые 10 секунд по умолчанию)
        self.chart_timer = QTimer(self)
        self.chart_timer.timeout.connect(self._on_chart_timer)
        self.chart_timer.start(chart_interval_ms)

        # 🔹 Очередь сигналов (мгновенная отправка)
        self._signal_queue: list[dict] = []

        # 🔹 Отслеживание последнего обновления графика
        self._last_chart_time = 0.0
        self._last_chart_symbol: Optional[str] = None
        self.chart_min_interval_sec = 8  # Минимум 8 сек между обновлениями графика

        # 🔹 Счётчики для диагностики
        self._equity_count = 0
        self._signal_count = 0
        self._chart_count = 0

        logger.info(
            f"🚦 GUIDispatcher инициализирован: " f"3 канала (equity={equity_interval_ms}ms, chart={chart_interval_ms}ms)"
        )

    def push_equity_data(self, data: dict):
        """
        Эквити/Прибыль → Канал 1 (высокий приоритет).
        Вызывается из любого потока — Qt сам перенаправит в GUI.
        """
        try:
            self.equity_data_ready.emit(data)
            self._equity_count += 1
        except Exception as e:
            logger.debug(f"⚠️ Эквити не отправлено: {e}")

    def push_trade_signal(self, data: dict):
        """
        Торговый сигнал → Канал 2 (мгновенно).
        """
        try:
            self.trade_signal_ready.emit(data)
            self._signal_count += 1
            logger.info(f"📡 Сигнал отправлен: {data.get('symbol')} {data.get('signal_type')}")
        except Exception as e:
            logger.debug(f"⚠️ Сигнал не отправлен: {e}")

    def push_chart_data(self, data: dict):
        """
        Данные графика → Канал 3 (сглаживание, не чаще чем раз в 8 сек).
        """
        current_time = time.time()
        symbol = data.get("symbol", "UNKNOWN")

        # Не даём графику обновляться чаще чем раз в 8 сек
        if current_time - self._last_chart_time < self.chart_min_interval_sec:
            # Если тот же символ — пропускаем (слишком часто)
            if symbol == self._last_chart_symbol:
                logger.debug(f"📈 Пропуск графика {symbol}: прошло {current_time - self._last_chart_time:.1f}с")
                return

        self.chart_data_ready.emit(data)
        self._chart_count += 1
        self._last_chart_time = current_time
        self._last_chart_symbol = symbol

    def get_stats(self) -> dict:
        """Возвращает статистику отправок."""
        return {
            "equity_updates": self._equity_count,
            "trade_signals": self._signal_count,
            "chart_updates": self._chart_count,
        }

    def _on_equity_timer(self):
        """Таймер эквити — запрос свежих данных из ядра."""
        # Этот метод может быть переопределён или подключён к сигналу запроса
        pass

    def _on_chart_timer(self):
        """Таймер графика — запрос обновления из ядра."""
        # Этот метод может быть переопределён или подключён к сигналу запроса
        pass
