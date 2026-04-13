# -*- coding: utf-8 -*-
"""
src/core/account_monitor.py — Выделенный поток для мониторинга метрик аккаунта

Отвечает за:
- Чтение баланса, эквити, маржи из MT5
- Отправку данных в GUI через Qt-сигналы
- Логирование изменений
- НЕ блокирует торговый цикл

Архитектура:
- Работает в отдельном daemon потоке
- Имеет собственный account_lock для безопасного чтения MT5
- Отправляет данные в GUI без блокировок
- Интервал обновления настраиваемый (по умолчанию 1 сек)
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import MetaTrader5 as mt5
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class AccountMetricsSignals(QObject):
    """Qt сигналы для отправки метрик аккаунта в GUI."""

    # Основной сигнал с полными данными
    metrics_updated = Signal(dict)  # {'balance', 'equity', 'margin', 'profit', ...}

    # Отдельные сигналы для оптимизации (меньше трафика)
    balance_updated = Signal(float, float)  # (balance, equity)
    profit_updated = Signal(float)  # profit в валюте счета
    margin_alert = Signal(str, float)  # (type, value) - предупреждения о марже


class AccountMonitorThread(threading.Thread):
    """
    Выделенный поток для мониторинга аккаунта MT5.

    Преимущества:
    - Полная изоляция от торгового цикла
    - Отсутствие deadlock с order_lock/data_lock
    - Плавный GUI (обновления не ждут торговлю)
    - Масштабируемость (легко добавить отправку в Telegram/DB)

    Attributes:
        interval: Интервал обновления в секундах
        running: Флаг работы потока
        signals: Qt-сигналы для отправки данных в GUI
        account_lock: Локальная блокировка для MT5 запросов
        _last_metrics: Кэш последних метрик (для сравнения)
        _error_count: Счётчик ошибок (для логирования)
    """

    def __init__(
        self,
        interval: float = 1.0,
        emit_on_change_only: bool = True,
    ):
        """
        Инициализация потока мониторинга.

        Args:
            interval: Интервал обновления (секунды). По умолчанию 1.0
            emit_on_change_only: Отправлять сигнал только при изменении данных
        """
        super().__init__(daemon=True, name="AccountMonitorThread")
        self.interval = interval
        self.emit_on_change_only = emit_on_change_only
        self.running = True
        self.signals = AccountMetricsSignals()
        self.account_lock = threading.Lock()

        # Кэш для сравнения
        self._last_metrics: Optional[Dict[str, Any]] = None
        self._error_count = 0
        self._consecutive_errors = 0
        self._last_success_time: Optional[float] = None

        logger.info(f"[AccountMonitor] Инициализирован. Интервал: {interval}s, Emit on change: {emit_on_change_only}")

    def run(self):
        """Основной цикл потока (выполняется в отдельном потоке)."""
        logger.info("[AccountMonitor] ✅ Поток запущен")

        while self.running:
            try:
                # Получаем метрики
                metrics = self._fetch_metrics()

                if metrics:
                    self._consecutive_errors = 0
                    self._last_success_time = time.time()

                    # Проверяем изменения (если включен режим only-on-change)
                    if self.emit_on_change_only:
                        if self._has_significant_change(metrics):
                            self._emit_metrics(metrics)
                            self._last_metrics = metrics.copy()
                    else:
                        # Отправляем каждый раз
                        self._emit_metrics(metrics)
                        self._last_metrics = metrics.copy()
                else:
                    self._consecutive_errors += 1
                    self._error_count += 1

                    # Логируем только каждую 10-ю ошибку для снижения шума
                    if self._consecutive_errors % 10 == 1:
                        logger.warning(
                            f"[AccountMonitor] Не удалось получить метрики. "
                            f"Последовательных ошибок: {self._consecutive_errors}"
                        )

                        # Если много ошибок — возможно MT5 отключился
                        if self._consecutive_errors >= 30:
                            logger.error("[AccountMonitor] ⚠️ MT5 недоступен более 30 секунд! " "Проверьте соединение.")

            except Exception as e:
                self._consecutive_errors += 1
                self._error_count += 1

                if self._consecutive_errors <= 3:
                    logger.error(f"[AccountMonitor] Исключение: {e}", exc_info=True)
                elif self._consecutive_errors % 20 == 0:
                    logger.warning(f"[AccountMonitor] Повторяющиеся ошибки (всего: {self._error_count})")

            # Ждём до следующего обновления
            time.sleep(self.interval)

        logger.info("[AccountMonitor] Поток остановлен")

    def _fetch_metrics(self) -> Optional[Dict[str, Any]]:
        """
        Получает метрики аккаунта из MT5.

        Использует локальный account_lock для безопасного чтения.
        Блокировка удерживается минимальное время (только на время запроса к MT5).

        Returns:
            Dict с метриками или None при ошибке
        """
        try:
            # Короткая блокировка только для запроса к MT5
            with self.account_lock:
                info = mt5.account_info()

            if info is None:
                return None

            # Рассчитываем прибыль
            profit = info.equity - info.balance

            # Уровень маржи (в процентах)
            margin_level = (info.equity / info.margin * 100) if info.margin > 0 else float("inf")

            metrics = {
                "balance": float(info.balance),
                "equity": float(info.equity),
                "margin": float(info.margin),
                "margin_free": float(info.margin_free),
                "margin_level": float(margin_level) if margin_level != float("inf") else 999999.0,
                "profit": float(profit),
                "currency": str(info.currency),
                "leverage": int(info.leverage),
                "timestamp": time.time(),
                "timestamp_iso": datetime.now().isoformat(),
            }

            return metrics

        except Exception as e:
            logger.debug(f"[AccountMonitor] Ошибка запроса к MT5: {e}")
            return None

    def _has_significant_change(self, new_metrics: Dict[str, Any]) -> bool:
        """
        Проверяет есть ли значительные изменения в метриках.

        Избегает спама сигналами когда данные не изменились.
        Порог: 0.01 валюты счета (1 цент для USD).

        Args:
            new_metrics: Новые метрики

        Returns:
            True если есть значительные изменения
        """
        if self._last_metrics is None:
            return True  # Первый вызов — всегда отправляем

        # Проверяем основные метрики
        for key in ["balance", "equity", "margin", "profit"]:
            old_val = self._last_metrics.get(key, 0.0)
            new_val = new_metrics.get(key, 0.0)

            if abs(new_val - old_val) > 0.01:  # Порог 0.01
                return True

        return False

    def _emit_metrics(self, metrics: Dict[str, Any]):
        """
        Отправляет метрики в GUI через Qt-сигналы.

        Отправка происходит безопасно из любого потока (Qt гарантирует).

        Args:
            metrics: Словарь с метриками аккаунта
        """
        try:
            # Основной сигнал с полными данными
            self.signals.metrics_updated.emit(metrics)

            # Отдельные оптимизированные сигналы
            self.signals.balance_updated.emit(metrics["balance"], metrics["equity"])
            self.signals.profit_updated.emit(metrics["profit"])

            # Проверка предупреждений о марже
            if metrics["margin_level"] < 150.0:
                self.signals.margin_alert.emit("LOW_MARGIN_LEVEL", metrics["margin_level"])

            # Логирование только при первом запуске или крупных изменениях
            if self._last_metrics is None:
                logger.info(
                    f"[AccountMonitor] 📊 Первые метрики: "
                    f"Balance={metrics['balance']:.2f} {metrics['currency']}, "
                    f"Equity={metrics['equity']:.2f}, "
                    f"Profit={metrics['profit']:.2f}"
                )
            elif abs(metrics["profit"] - self._last_metrics.get("profit", 0)) > 1.0:
                logger.debug(
                    f"[AccountMonitor] 💰 Profit изменился: "
                    f"{self._last_metrics.get('profit', 0):.2f} → {metrics['profit']:.2f}"
                )

        except Exception as e:
            logger.error(f"[AccountMonitor] Ошибка отправки метрик: {e}")

    def get_last_metrics(self) -> Optional[Dict[str, Any]]:
        """
        Получает последние кэшированные метрики (без запроса к MT5).

        Потокобезопасный getter для чтения из других потоков.

        Returns:
            Dict с метриками или None если еще не получены
        """
        if self._last_metrics:
            return self._last_metrics.copy()
        return None

    def get_error_count(self) -> int:
        """Возвращает общее количество ошибок."""
        return self._error_count

    def get_time_since_last_success(self) -> Optional[float]:
        """Возвращает время (секунды) с последнего успешного получения метрик."""
        if self._last_success_time:
            return time.time() - self._last_success_time
        return None

    def stop(self):
        """Останавливает поток мониторинга."""
        logger.info("[AccountMonitor] Остановка потока...")
        self.running = False
        # Не вызываем join() здесь — поток daemon, завершится сам


# ===========================================
# Фабрика для создания с правильной конфигурацией
# ===========================================


def create_account_monitor(
    interval: float = 1.0,
    emit_on_change_only: bool = True,
) -> AccountMonitorThread:
    """
    Фабрика для создания AccountMonitorThread.

    Args:
        interval: Интервал обновления (секунды)
        emit_on_change_only: Отправлять только при изменениях

    Returns:
        Настроенный экземпляр AccountMonitorThread
    """
    monitor = AccountMonitorThread(
        interval=interval,
        emit_on_change_only=emit_on_change_only,
    )
    return monitor
