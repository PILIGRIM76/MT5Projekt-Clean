# src/core/services/orchestrator_service.py
"""
Orchestrator Service - Сервис для управления RL-оркестратором.

Инкапсулирует логику оркестратора из TradingSystem.
"""

import logging
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict, Any

from src.core.services.base_service import BaseService, HealthStatus

if TYPE_CHECKING:
    from src.core.trading_system import TradingSystem

logger = logging.getLogger(__name__)


class OrchestratorService(BaseService):
    """
    Сервис оркестратора - управляет RL-агентом для распределения капитала.
    
    Отвечает за:
    - Запуск цикла оркестратора каждые 5 минут
    - Проверку адаптивных триггеров (Drift, VaR)
    - Управление пулом стратегий (наём/увольнение)
    - Дообучение RL-агента
    """
    
    def __init__(self, trading_system: 'TradingSystem', interval_seconds: float = 300.0):
        """
        Args:
            trading_system: Ссылка на торговую систему
            interval_seconds: Интервал между циклами (по умолчанию 5 минут)
        """
        super().__init__(name="OrchestratorService")
        self.trading_system = trading_system
        self.interval_seconds = interval_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._iteration_count = 0
        
        # Статистика
        self._last_rd_trigger: Optional[datetime] = None
        self._rd_triggers_count = 0
        self._strategies_hired = 0
        self._strategies_fired = 0

    def _on_start(self) -> None:
        """Запуск сервиса оркестратора"""
        self._logger.info("Запуск сервиса оркестратора...")
        
        # Проверка наличия оркестратора
        if not hasattr(self.trading_system, 'orchestrator'):
            raise RuntimeError("Оркестратор не инициализирован")
        
        if not self.trading_system.orchestrator:
            raise RuntimeError("Оркестратор = None")
        
        self._stop_event.clear()
        
        # Запуск в отдельном потоке
        self._thread = threading.Thread(
            target=self._orchestrator_loop,
            daemon=True,
            name="OrchestratorService-Thread"
        )
        self._thread.start()

    def _on_stop(self) -> None:
        """Остановка сервиса оркестратора"""
        self._logger.info("Остановка сервиса оркестратора...")
        self._stop_event.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                self._logger.warning("Поток оркестратора не завершился за 10с")

    def _orchestrator_loop(self) -> None:
        """Основной цикл оркестратора"""
        self._logger.info(f"Цикл оркестратора запущен (интервал={self.interval_seconds}s)")
        
        # Первая задержка перед запуском (опционально)
        # self._stop_event.wait(60)  # Ждем 1 минуту перед первым запуском
        
        while not self._stop_event.is_set():
            try:
                # Запуск цикла оркестратора
                self.trading_system.orchestrator.run_cycle()
                
                self._iteration_count += 1
                self.increment_operations()
                
                self._logger.debug(f"Цикл оркестратора завершен. Итерация #{self._iteration_count}")
                
            except Exception as e:
                error_msg = f"Ошибка в цикле оркестратора: {e}"
                self._logger.error(error_msg, exc_info=True)
                self.record_error(error_msg)
            
            # Ожидание следующего интервала
            self._stop_event.wait(self.interval_seconds)
        
        self._logger.info(f"Цикл оркестратора завершен. Всего итераций: {self._iteration_count}")

    def _health_check(self) -> HealthStatus:
        """Проверка здоровья сервиса оркестратора"""
        orchestrator_exists = hasattr(self.trading_system, 'orchestrator')
        orchestrator_valid = orchestrator_exists and self.trading_system.orchestrator is not None
        
        checks = {
            "thread_alive": self._thread is not None and self._thread.is_alive(),
            "orchestrator_exists": orchestrator_exists,
            "orchestrator_valid": orchestrator_valid,
            "system_running": self.trading_system.running,
        }
        
        is_healthy = all(checks.values())
        
        details = {
            "iterations": self._iteration_count,
            "rd_triggers": self._rd_triggers_count,
            "strategies_hired": self._strategies_hired,
            "strategies_fired": self._strategies_fired,
            "last_rd_trigger": str(self._last_rd_trigger) if self._last_rd_trigger else None,
        }
        
        message = "OK" if is_healthy else "Оркестратор нездоров"
        
        return HealthStatus(
            is_healthy=is_healthy,
            checks=checks,
            details=details,
            message=message
        )

    def force_cycle(self) -> None:
        """Принудительный запуск цикла оркестратора"""
        self._logger.info("Принудительный запуск цикла оркестратора...")
        
        def run_cycle():
            try:
                self.trading_system.orchestrator.run_cycle()
                self._iteration_count += 1
                self._logger.info("Принудительный цикл завершен")
            except Exception as e:
                self._logger.error(f"Ошибка в принудительном цикле: {e}", exc_info=True)
                self.record_error(str(e))
        
        thread = threading.Thread(target=run_cycle, daemon=True)
        thread.start()

    def trigger_rd_cycle(self) -> None:
        """Запустить R&D цикл через оркестратор"""
        self._logger.warning("Адаптивный триггер: Запуск R&D цикла...")
        
        def run_rd():
            try:
                self.trading_system.force_rd_cycle()
                self._rd_triggers_count += 1
                self._last_rd_trigger = datetime.now()
            except Exception as e:
                self._logger.error(f"Ошибка запуска R&D: {e}", exc_info=True)
        
        thread = threading.Thread(target=run_rd, daemon=True)
        thread.start()

    def check_and_trigger_rd(self) -> bool:
        """
        Проверить условия для запуска R&D и запустить при необходимости.
        
        Returns:
            bool: True если R&D был запущен
        """
        should_trigger = False
        reason = ""
        
        # Проверка дрейфа концепции
        if self.trading_system.has_active_drift():
            should_trigger = True
            reason = "Concept Drift обнаружен"
        
        # Проверка высокого VaR
        state = self.trading_system.get_rl_orchestrator_state()
        current_var = state.get('portfolio_var', 0.0)
        max_var_config = self.trading_system.config.MAX_PORTFOLIO_VAR_PERCENT
        
        if current_var > max_var_config * 1.5:
            should_trigger = True
            reason = f"Высокий VaR: {current_var:.2%} > {max_var_config * 1.5:.2%}"
        
        if should_trigger:
            self._logger.critical(f"АДАПТИВНЫЙ ТРИГГЕР: {reason}. Запуск R&D.")
            self.trigger_rd_cycle()
            return True
        
        return False

    def get_status(self) -> Dict[str, Any]:
        """Получить расширенный статус сервиса"""
        base_status = super().get_status()
        base_status.update({
            "iteration_count": self._iteration_count,
            "interval_seconds": self.interval_seconds,
            "rd_triggers_count": self._rd_triggers_count,
            "last_rd_trigger": str(self._last_rd_trigger) if self._last_rd_trigger else None,
        })
        return base_status
