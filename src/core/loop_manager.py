# src/core/loop_manager.py
"""
Loop Manager - Централизованное управление фоновыми циклами.

Заменяет прямое создание threading.Thread в TradingSystem.
Предоставляет единый интерфейс для запуска, остановки и мониторинга циклов.
"""

import asyncio
import logging
import threading
import time as standard_time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Dict, Any, List
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class LoopState(Enum):
    """Состояние цикла"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class LoopStats:
    """Статистика выполнения цикла"""
    name: str
    state: LoopState
    iterations: int = 0
    last_run: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    avg_iteration_time: float = 0.0
    total_run_time: float = 0.0


class BaseLoop(ABC):
    """Базовый класс для всех циклов"""
    
    def __init__(self, name: str, interval_seconds: float = 1.0):
        self.name = name
        self.interval_seconds = interval_seconds
        self.state = LoopState.STOPPED
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.stats = LoopStats(name=name, state=LoopState.STOPPED)
        self._iteration_times: List[float] = []
        self._max_iteration_times = 100  # Скользящее окно для среднего

    @abstractmethod
    def run_iteration(self) -> None:
        """Выполнить одну итерацию цикла"""
        pass

    def start(self) -> None:
        """Запустить цикл в отдельном потоке"""
        if self.state == LoopState.RUNNING:
            logger.warning(f"[{self.name}] Цикл уже запущен")
            return

        logger.info(f"[{self.name}] Запуск цикла...")
        self.stop_event.clear()
        self.state = LoopState.RUNNING
        self.stats.state = LoopState.RUNNING
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name=f"Loop-{self.name}")
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Остановить цикл"""
        if self.state != LoopState.RUNNING:
            return

        logger.info(f"[{self.name}] Остановка цикла...")
        self.stop_event.set()
        self.state = LoopState.STOPPED
        self.stats.state = LoopState.STOPPED
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)
            if self.thread.is_alive():
                logger.warning(f"[{self.name}] Поток не завершился за {timeout}с")

    def _run_loop(self) -> None:
        """Основной цикл выполнения"""
        logger.info(f"[{self.name}] Цикл запущен")
        
        while not self.stop_event.is_set():
            iteration_start = standard_time.perf_counter()
            
            try:
                self.run_iteration()
                self.stats.iterations += 1
                self.stats.last_run = datetime.now()
                self.stats.last_error = None
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"[{self.name}] Ошибка в итерации: {error_msg}", exc_info=True)
                self.stats.last_error = error_msg
                self.stats.last_error_time = datetime.now()
                self.state = LoopState.ERROR
                self.stats.state = LoopState.ERROR
            
            # Вычисление времени итерации
            iteration_time = standard_time.perf_counter() - iteration_start
            self._update_avg_iteration_time(iteration_time)
            self.stats.total_run_time += iteration_time
            
            # Ожидание следующего интервала
            sleep_time = max(0, self.interval_seconds - iteration_time)
            if sleep_time > 0:
                self.stop_event.wait(sleep_time)
        
        logger.info(f"[{self.name}] Цикл остановлен")

    def _update_avg_iteration_time(self, iteration_time: float) -> None:
        """Обновить скользящее среднее времени итерации"""
        self._iteration_times.append(iteration_time)
        if len(self._iteration_times) > self._max_iteration_times:
            self._iteration_times.pop(0)
        self.stats.avg_iteration_time = sum(self._iteration_times) / len(self._iteration_times)

    def get_stats(self) -> LoopStats:
        """Получить статистику цикла"""
        return self.stats


class AsyncLoop(BaseLoop):
    """Асинхронный цикл с использованием asyncio"""
    
    def __init__(self, name: str, interval_seconds: float = 1.0):
        super().__init__(name, interval_seconds)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self) -> None:
        """Запустить асинхронный цикл"""
        if self.state == LoopState.RUNNING:
            logger.warning(f"[{self.name}] Цикл уже запущен")
            return

        logger.info(f"[{self.name}] Запуск асинхронного цикла...")
        self.stop_event.clear()
        self.state = LoopState.RUNNING
        self.stats.state = LoopState.RUNNING
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True, name=f"AsyncLoop-{self.name}")
        self.thread.start()

    def _run_async_loop(self) -> None:
        """Запуск asyncio event loop"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            self.loop.run_until_complete(self._async_run_loop())
        except Exception as e:
            logger.error(f"[{self.name}] Критическая ошибка в async цикле: {e}", exc_info=True)
        finally:
            # Отмена всех pending задач
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()
        
        logger.info(f"[{self.name}] Асинхронный цикл остановлен")

    async def _async_run_loop(self) -> None:
        """Асинхронный основной цикл"""
        logger.info(f"[{self.name}] Асинхронный цикл запущен")
        
        while not self.stop_event.is_set():
            iteration_start = standard_time.perf_counter()
            
            try:
                await self.run_async_iteration()
                self.stats.iterations += 1
                self.stats.last_run = datetime.now()
                self.stats.last_error = None
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"[{self.name}] Ошибка в async итерации: {error_msg}", exc_info=True)
                self.stats.last_error = error_msg
                self.stats.last_error_time = datetime.now()
                self.state = LoopState.ERROR
                self.stats.state = LoopState.ERROR
            
            iteration_time = standard_time.perf_counter() - iteration_start
            self._update_avg_iteration_time(iteration_time)
            self.stats.total_run_time += iteration_time
            
            sleep_time = max(0, self.interval_seconds - iteration_time)
            if sleep_time > 0:
                try:
                    await asyncio.sleep(sleep_time)
                except asyncio.CancelledError:
                    break
        
        logger.info(f"[{self.name}] Асинхронный цикл остановлен")

    @abstractmethod
    async def run_async_iteration(self) -> None:
        """Выполнить одну асинхронную итерацию"""
        pass


@dataclass
class LoopConfig:
    """Конфигурация для создания цикла"""
    name: str
    interval: float
    loop_type: str = "sync"  # "sync" или "async"
    enabled: bool = True
    initial_delay: float = 0.0  # Задержка перед первым запуском


class LoopManager(QObject):
    """
    Менеджер циклов - централизованное управление всеми фоновыми циклами.
    
    Сигналы для интеграции с GUI:
    - loop_status_updated: Обновление статуса цикла
    - loop_error: Произошла ошибка в цикле
    """
    loop_status_updated = Signal(str, str)  # name, status
    loop_error = Signal(str, str)  # name, error_message

    def __init__(self):
        super().__init__()
        self.loops: Dict[str, BaseLoop] = {}
        self.configs: Dict[str, LoopConfig] = {}
        self._started = False

    def register_loop(self, loop: BaseLoop, config: Optional[LoopConfig] = None) -> None:
        """Зарегистрировать цикл в менеджере"""
        if loop.name in self.loops:
            logger.warning(f"[LoopManager] Цикл '{loop.name}' уже зарегистрирован, заменяем")
        
        self.loops[loop.name] = loop
        if config:
            self.configs[loop.name] = config
        
        logger.info(f"[LoopManager] Зарегистрирован цикл: {loop.name} (interval={loop.interval_seconds}s)")

    def create_and_register(self, config: LoopConfig, iteration_func: Callable, 
                           is_async: bool = False) -> BaseLoop:
        """Создать и зарегистрировать цикл из функции"""
        if is_async:
            # Для async нужно обернуть функцию
            loop = AsyncLoop(config.name, config.interval)
            # Сохраняем функцию в loop для использования
            loop._iteration_func = iteration_func
            loop.run_async_iteration = lambda: iteration_func()
        else:
            loop = BaseLoop(config.name, config.interval)
            loop.run_iteration = iteration_func
        
        self.register_loop(loop, config)
        return loop

    def start_all(self) -> None:
        """Запустить все зарегистрированные циклы"""
        if self._started:
            logger.warning("[LoopManager] Менеджер уже запущен")
            return

        logger.info("[LoopManager] Запуск всех циклов...")
        self._started = True
        
        for name, loop in self.loops.items():
            config = self.configs.get(name)
            if config and not config.enabled:
                logger.info(f"[LoopManager] Пропуск отключенного цикла: {name}")
                continue
            
            try:
                loop.start()
                self.loop_status_updated.emit(name, "RUNNING")
            except Exception as e:
                error_msg = f"Ошибка запуска цикла {name}: {e}"
                logger.error(error_msg, exc_info=True)
                self.loop_error.emit(name, error_msg)

    def stop_all(self, timeout: float = 5.0) -> None:
        """Остановить все циклы"""
        logger.info("[LoopManager] Остановка всех циклов...")
        self._started = False
        
        for name, loop in self.loops.items():
            try:
                loop.stop(timeout=timeout)
                self.loop_status_updated.emit(name, "STOPPED")
            except Exception as e:
                logger.error(f"Ошибка остановки цикла {name}: {e}", exc_info=True)

    def start_loop(self, name: str) -> bool:
        """Запустить конкретный цикл"""
        if name not in self.loops:
            logger.error(f"[LoopManager] Цикл '{name}' не найден")
            return False
        
        try:
            self.loops[name].start()
            self.loop_status_updated.emit(name, "RUNNING")
            return True
        except Exception as e:
            error_msg = f"Ошибка запуска цикла {name}: {e}"
            logger.error(error_msg, exc_info=True)
            self.loop_error.emit(name, error_msg)
            return False

    def stop_loop(self, name: str, timeout: float = 5.0) -> bool:
        """Остановить конкретный цикл"""
        if name not in self.loops:
            logger.error(f"[LoopManager] Цикл '{name}' не найден")
            return False
        
        try:
            self.loops[name].stop(timeout=timeout)
            self.loop_status_updated.emit(name, "STOPPED")
            return True
        except Exception as e:
            logger.error(f"Ошибка остановки цикла {name}: {e}", exc_info=True)
            return False

    def get_loop_stats(self, name: str) -> Optional[LoopStats]:
        """Получить статистику цикла"""
        if name not in self.loops:
            return None
        return self.loops[name].get_stats()

    def get_all_stats(self) -> Dict[str, LoopStats]:
        """Получить статистику всех циклов"""
        return {name: loop.get_stats() for name, loop in self.loops.items()}

    def pause_loop(self, name: str) -> bool:
        """Приостановить цикл (будущая функциональность)"""
        if name not in self.loops:
            return False
        # TODO: Реализовать pause/resume функциональность
        logger.warning(f"[LoopManager] Pause не реализован для {name}")
        return False

    def resume_loop(self, name: str) -> bool:
        """Возобновить цикл (будущая функциональность)"""
        if name not in self.loops:
            return False
        # TODO: Реализовать pause/resume функциональность
        logger.warning(f"[LoopManager] Resume не реализован для {name}")
        return False
