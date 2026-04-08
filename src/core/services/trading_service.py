# src/core/services/trading_service.py
"""
Trading Service - Сервис для управления торговым циклом.

Инкапсулирует логику торгового цикла из TradingSystem.
Использует асинхронный подход для неблокирующей торговли.
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.services.base_service import BaseService, HealthStatus, ServiceMetrics

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem

logger = logging.getLogger(__name__)


class TradingService(BaseService):
    """
    Сервис торговли - выполняет торговый цикл.

    Отвечает за:
    - Сканирование рынка
    - Генерацию сигналов
    - Исполнение ордеров
    - Отправку данных в GUI
    """

    def __init__(self, trading_system: "TradingSystem", interval_seconds: float = 60.0):
        super().__init__(name="TradingService")
        self.trading_system = trading_system
        self.interval_seconds = interval_seconds
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None
        self._iteration_count = 0

        # Статистика
        self._last_signal_time: Optional[datetime] = None
        self._signals_generated: int = 0
        self._trades_executed: int = 0

    def _on_start(self) -> None:
        """Запуск торгового сервиса"""
        self._logger.info("Запуск торгового сервиса...")

        # Проверка готовности системы
        if not self.trading_system.is_heavy_init_complete:
            raise RuntimeError("Тяжелая инициализация не завершена")

        # Запуск асинхронного цикла
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._task = self._loop.create_task(self._trading_cycle())

        # Блокирующее ожидание (в отдельном потоке)
        self._loop.run_forever()

    def _on_stop(self) -> None:
        """Остановка торгового сервиса"""
        self._logger.info("Остановка торгового сервиса...")

        if self._loop and not self._loop.is_closed():
            # Отмена задачи
            if self._task:
                self._task.cancel()
                try:
                    self._loop.run_until_complete(self._task)
                except asyncio.CancelledError:
                    pass

            # Отмена всех pending задач
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

            # Закрытие event loop
            self._loop.stop()
            self._loop.close()

        self._logger.info(f"Торговый сервис остановлен. Итераций: {self._iteration_count}")

    async def _trading_cycle(self) -> None:
        """
        Основной торговый цикл.

        Выполняется бесконечно до остановки сервиса.
        """
        self._logger.info("Торговый цикл запущен")

        while self.trading_system.running and not self.trading_system.stop_event.is_set():
            iteration_start = datetime.now()

            try:
                # Выполнение одной итерации
                await self.trading_system.run_cycle()

                self._iteration_count += 1
                self.increment_operations()

                # Логирование производительности
                iteration_time = (datetime.now() - iteration_start).total_seconds()
                self.record_metric("last_iteration_time", iteration_time)

                if iteration_time > self.interval_seconds * 0.9:
                    self._logger.warning(f"Медленная итерация: {iteration_time:.2f}s > {self.interval_seconds}s")

            except asyncio.CancelledError:
                self._logger.info("Торговый цикл отменен")
                break
            except Exception as e:
                error_msg = f"Ошибка в торговом цикле: {e}"
                self._logger.error(error_msg, exc_info=True)
                self.record_error(error_msg)

                # Продолжаем цикл после ошибки
                await asyncio.sleep(1)

            # Пауза до следующей итерации
            elapsed = (datetime.now() - iteration_start).total_seconds()
            sleep_time = max(0, self.interval_seconds - elapsed)

            if sleep_time > 0:
                try:
                    await asyncio.sleep(sleep_time)
                except asyncio.CancelledError:
                    break

        self._logger.info(f"Торговый цикл завершен. Всего итераций: {self._iteration_count}")

    def _health_check(self) -> HealthStatus:
        """Проверка здоровья торгового сервиса"""
        checks = {
            "system_initialized": self.trading_system.is_heavy_init_complete,
            "system_running": self.trading_system.running,
            "mt5_connected": self._check_mt5_connection(),
            "loop_running": self._loop is not None and not self._loop.is_closed(),
        }

        is_healthy = all(checks.values())

        details = {
            "iterations": self._iteration_count,
            "signals_generated": self._signals_generated,
            "trades_executed": self._trades_executed,
            "last_signal_time": str(self._last_signal_time) if self._last_signal_time else None,
        }

        message = "OK" if is_healthy else "Одна или несколько проверок не пройдены"

        return HealthStatus(is_healthy=is_healthy, checks=checks, details=details, message=message)

    def _check_mt5_connection(self) -> bool:
        """Проверить подключение к MT5"""
        try:
            from src.core.mt5_connection_manager import mt5_initialize

            with self.trading_system.mt5_lock:
                return mt5_initialize(path=self.trading_system.config.MT5_PATH)
        except Exception:
            return False

    def get_status(self) -> Dict[str, Any]:
        """Получить расширенный статус сервиса"""
        base_status = super().get_status()
        base_status.update(
            {
                "iteration_count": self._iteration_count,
                "signals_generated": self._signals_generated,
                "trades_executed": self._trades_executed,
                "interval_seconds": self.interval_seconds,
            }
        )
        return base_status

    def record_signal(self) -> None:
        """Записать факт генерации сигнала"""
        self._signals_generated += 1
        self._last_signal_time = datetime.now()

    def record_trade(self) -> None:
        """Записать факт исполнения ордера"""
        self._trades_executed += 1
