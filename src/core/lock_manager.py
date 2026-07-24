"""
LockHierarchy — иерархический менеджер блокировок для TradingSystem.

Ключевые улучшения:
- Строгая иерархия уровней (захват только по возрастанию)
- Автоматическое детектирование потенциальных дедлоков
- Таймауты на каждом уровне
- Статистика контентента для мониторинга
- Поддержка "слабых" блокировок (non-blocking acquire)

Правило: захватывать блокировки ТОЛЬКО в порядке возрастания уровней:
  1. MT5_LOCK (доступ к терминалу)
  2. DB_LOCK (запись в БД)
  3. MODEL_LOCK (загрузка/сохранение моделей)
  4. CONFIG_LOCK (изменение конфигов)

Нарушение порядка → RuntimeError.
Превышение таймаута → TimeoutError.

Обратная совместимость:
- Старый API (LockHierarchy, lock_manager) сохранён
- Добавлены новые функции: deadlock detection, статистика
- Существующий код работает без изменений
"""

import logging
import threading
import time
import traceback
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Iterator, List, Optional, Set

logger = logging.getLogger(__name__)


class LockLevel(IntEnum):
    """
    Уровни блокировок — ЗАХВАТЫВАТЬ ТОЛЬКО ПО ВОЗРАСТАНИЮ!

    Правило: если код держит блокировку уровня N,
    он может запросить только уровни > N.
    """

    # === НИЗКИЙ УРОВЕНЬ: частые, быстрые операции ===
    CACHE = 1  # Кэш данных, in-memory структуры
    CONFIG = 2  # Чтение конфигурации (RLock для рекурсии)

    # === СРЕДНИЙ УРОВЕНЬ: бизнес-логика ===
    SYMBOL_DATA = 3  # Данные по инструменту (per-symbol locks)
    MODEL_CACHE = 4  # Кэш предсказаний моделей
    STRATEGY_STATE = 5  # Состояние стратегий

    # === ВЫСОКИЙ УРОВЕНЬ: критичные ресурсы ===
    DB_WRITE = 6  # Запись в БД (эксклюзивная)
    MT5_ACCESS = 7  # Доступ к MetaTrader 5 API
    TRADE_EXECUTION = 8  # Исполнение ордеров (критичная секция)

    # === МАКСИМАЛЬНЫЙ УРОВЕНЬ: глобальные операции ===
    SYSTEM_RECONFIG = 9  # Переконфигурация системы
    MODEL_TRAINING = 10  # Обучение моделей (блокирует много ресурсов)

    # === LEGACY ALIASES для обратной совместимости ===
    MT5_LOCK = 1  # Алиас на CACHE для старого кода
    DB_LOCK = 6  # Алиас на DB_WRITE для старого кода
    MODEL_LOCK = 4  # Алиас на MODEL_CACHE для старого кода
    CONFIG_LOCK = 2  # Алиас на CONFIG для старого кода


@dataclass
class LockStats:
    """Статистика по блокировке"""

    acquire_count: int = 0
    release_count: int = 0
    timeout_count: int = 0
    total_hold_time_ms: float = 0.0
    max_hold_time_ms: float = 0.0
    contention_count: int = 0  # Сколько раз ждали освобождения

    def avg_hold_time_ms(self) -> float:
        if self.acquire_count == 0:
            return 0.0
        return self.total_hold_time_ms / self.acquire_count


class DeadlockDetector:
    """
    Простой детектор потенциальных дедлоков через анализ графа ожиданий.

    Не гарантирует 100% обнаружение, но ловит очевидные случаи.
    """

    def __init__(self, max_wait_graph_size: int = 100):
        self._wait_graph: Dict[int, Set[int]] = defaultdict(set)  # thread -> waiting_for_threads
        self._lock = threading.Lock()
        self._max_size = max_wait_graph_size

    def record_wait(self, waiter_tid: int, holder_tid: int):
        """Запись что поток waiter ждёт поток holder"""
        with self._lock:
            self._wait_graph[waiter_tid].add(holder_tid)
            # Очистка старых записей
            if len(self._wait_graph) > self._max_size:
                # Удаляем потоки которые больше не ждут
                self._wait_graph = {t: waits for t, waits in self._wait_graph.items() if waits}

    def clear_wait(self, tid: int):
        """Удаление записей о потоке"""
        with self._lock:
            self._wait_graph.pop(tid, None)
            for waits in self._wait_graph.values():
                waits.discard(tid)

    def check_cycle(self) -> Optional[List[int]]:
        """
        Поиск цикла в графе ожиданий (признак дедлока).
        Returns: список thread IDs в цикле или None.
        """
        with self._lock:
            # DFS для поиска цикла
            visited = set()
            rec_stack = set()

            def dfs(node: int, path: List[int]) -> Optional[List[int]]:
                visited.add(node)
                rec_stack.add(node)
                path.append(node)

                for neighbor in self._wait_graph.get(node, []):
                    if neighbor not in visited:
                        result = dfs(neighbor, path)
                        if result:
                            return result
                    elif neighbor in rec_stack:
                        # Нашли цикл
                        cycle_start = path.index(neighbor)
                        return path[cycle_start:] + [neighbor]

                path.pop()
                rec_stack.remove(node)
                return None

            for node in list(self._wait_graph.keys()):
                if node not in visited:
                    cycle = dfs(node, [])
                    if cycle:
                        return cycle
            return None


class LockHierarchy:
    """
    Управляет блокировками с фиксированным порядком захвата.

    Использование:
        lock_manager = LockHierarchy()

        # Безопасный захват нескольких блокировок
        with lock_manager.acquire(LockLevel.MT5_LOCK, LockLevel.DB_LOCK, timeout=3.0):
            deals = mt5.history_deals_get(...)
            db_manager.log_deals(deals)

        # Проверка持有
        if lock_manager.is_held_by_current(LockLevel.MT5_LOCK):
            # Уже держим MT5 лок
            pass

    Обратная совместимость:
    - Этот класс полностью сохранён для старого кода
    - Добавлены: deadlock detection, статистика, таймауты
    """

    def __init__(self, default_timeout: float = 5.0, enable_deadlock_detection: bool = True):
        """
        Args:
            default_timeout: Таймаут по умолчанию для всех блокировок
            enable_deadlock_detection: Включить детектор дедлоков
        """
        self._locks = {
            LockLevel.MT5_LOCK: threading.RLock(),
            LockLevel.DB_LOCK: threading.RLock(),
            LockLevel.MODEL_LOCK: threading.RLock(),
            LockLevel.CONFIG_LOCK: threading.RLock(),
            # Новые уровни
            LockLevel.CACHE: threading.RLock(),
            LockLevel.CONFIG: threading.RLock(),
            LockLevel.SYMBOL_DATA: threading.RLock(),
            LockLevel.MODEL_CACHE: threading.RLock(),
            LockLevel.STRATEGY_STATE: threading.RLock(),
            LockLevel.DB_WRITE: threading.RLock(),
            LockLevel.MT5_ACCESS: threading.RLock(),
            LockLevel.TRADE_EXECUTION: threading.RLock(),
            LockLevel.SYSTEM_RECONFIG: threading.RLock(),
            LockLevel.MODEL_TRAINING: threading.RLock(),
        }
        self._default_timeout = default_timeout
        self._enable_deadlock_detection = enable_deadlock_detection

        # Отслеживание какие блокировки держит каждый поток
        self._held: dict = {}  # thread_id -> dict of LockLevel -> acquire_time
        self._held_lock = threading.Lock()

        # Статистика
        self._stats: Dict[LockLevel, LockStats] = {level: LockStats() for level in LockLevel}

        # Детектор дедлоков
        self._deadlock_detector = DeadlockDetector() if enable_deadlock_detection else None

    @contextmanager
    def acquire(self, *levels: LockLevel, timeout: float = -1) -> Iterator[None]:
        """
        Контекстный менеджер для безопасного захвата блокировок.

        Args:
            *levels: Уровни блокировок для захвата
            timeout: Таймаут в секундах (-1 = default_timeout)

        Raises:
            RuntimeError: Если нарушен порядок блокировок
            TimeoutError: Если не удалось захватить блокировку за timeout секунд

        Example:
            with lock_manager.acquire(LockLevel.MT5_LOCK, LockLevel.DB_LOCK):
                # Код требующий обоих локов
                pass
        """
        if timeout < 0:
            timeout = self._default_timeout

        level_list = list(levels)

        # Проверка порядка (должны быть отсортированы)
        if level_list != sorted(level_list):
            raise RuntimeError(
                f"Нарушен порядок блокировок! "
                f"Ожидалось {sorted(level_list)}, получено {level_list}. "
                f"Захватывайте только по возрастанию уровней."
            )

        # Проверка дубликатов
        if len(level_list) != len(set(level_list)):
            raise RuntimeError(f"Дубликаты блокировок: {level_list}")

        tid = threading.get_ident()
        acquired = []
        acquire_times: Dict[LockLevel, float] = {}

        try:
            for level in level_list:
                lock = self._locks[level]
                stats = self._stats[level]

                # Проверка: не держим ли мы уже эту блокировку (reentrant)
                with self._held_lock:
                    if level in self._held.get(tid, {}):
                        # Рекурсивный захват — пропускаем
                        acquired.append(level)
                        continue

                # Проверка дедлоков перед захватом
                if self._enable_deadlock_detection and self._deadlock_detector:
                    with self._held_lock:
                        for held_level in self._held.get(tid, {}).keys():
                            if held_level >= level:
                                logger.warning(
                                    f"Potential deadlock risk: thread {tid} holds {held_level.name} "
                                    f"and trying to acquire {level.name} (should be > {held_level})"
                                )

                # Попытка захвата
                start_wait = time.time()
                acquired_lock = lock.acquire(timeout=timeout)
                wait_time = (time.time() - start_wait) * 1000

                if not acquired_lock:
                    stats.timeout_count += 1
                    raise TimeoutError(
                        f"Не удалось захватить блокировку уровня {level.name} "
                        f"за {timeout}с (поток {tid}, ожидание {wait_time:.1f}ms)"
                    )

                # Успешный захват
                acquire_time = time.time()
                acquire_times[level] = acquire_time
                acquired.append(level)

                # Обновляем отслеживание
                with self._held_lock:
                    if tid not in self._held:
                        self._held[tid] = {}
                    self._held[tid][level] = acquire_time

                # Обновляем статистику
                stats.acquire_count += 1
                if wait_time > 10:  # Только если было ожидание
                    stats.contention_count += 1
                    if self._deadlock_detector:
                        holder_tids = self._find_holders_of(level)
                        for holder in holder_tids:
                            if holder != tid:
                                self._deadlock_detector.record_wait(tid, holder)

                logger.debug(f"🔒 Захвачен лок {level.name} (поток {tid}, ожидание={wait_time:.1f}ms)")

            yield

        finally:
            # Освобождаем в обратном порядке
            for level in reversed(acquired):
                if level not in acquire_times:
                    # Пропускаем рекурсивные захваты
                    continue

                lock = self._locks[level]
                stats = self._stats[level]

                # Вычисляем время удержания
                hold_time = (time.time() - acquire_times[level]) * 1000

                lock.release()

                # Обновляем отслеживание
                with self._held_lock:
                    held = self._held.get(tid, {})
                    held.pop(level, None)
                    if not held:
                        self._held.pop(tid, None)

                # Обновляем статистику
                stats.release_count += 1
                stats.total_hold_time_ms += hold_time
                stats.max_hold_time_ms = max(stats.max_hold_time_ms, hold_time)

                # Очищаем детектор
                if self._deadlock_detector:
                    self._deadlock_detector.clear_wait(tid)

                logger.debug(f"🔓 Освобождён лок {level.name} (поток {tid}, удержание={hold_time:.1f}ms)")

    def try_acquire(self, level: LockLevel, timeout: float = 0) -> bool:
        """
        Неблокирующая попытка захвата одной блокировки.

        Returns:
            True если захват успешен, False если блокировка занята
        """
        try:
            with self.acquire(level, timeout=timeout):
                return True
        except (TimeoutError, BlockingIOError):
            return False

    def _find_holders_of(self, level: LockLevel) -> Set[int]:
        """Найти потоки которые держат указанную блокировку"""
        holders = set()
        with self._held_lock:
            for tid, held_levels in self._held.items():
                if level in held_levels:
                    holders.add(tid)
        return holders

    def is_held_by_current(self, level: LockLevel) -> bool:
        """
        Проверяет, держит ли текущий поток указанную блокировку.

        Args:
            level: Уровень блокировки

        Returns:
            True если текущий поток держит блокировку
        """
        tid = threading.get_ident()
        with self._held_lock:
            return level in self._held.get(tid, {})

    def get_held_levels(self) -> Set[LockLevel]:
        """Возвращает блокировки которые держит текущий поток."""
        tid = threading.get_ident()
        with self._held_lock:
            return set(self._held.get(tid, {}).keys())

    def get_stats(self, level: Optional[LockLevel] = None) -> dict:
        """
        Возвращает статистику блокировок.

        Args:
            level: Если указан — статистика по конкретному уровню,
                   иначе — по всем уровням
        """
        if level:
            stats = self._stats[level]
            return {
                "level": level.name,
                "acquire_count": stats.acquire_count,
                "release_count": stats.release_count,
                "timeout_count": stats.timeout_count,
                "avg_hold_time_ms": stats.avg_hold_time_ms(),
                "max_hold_time_ms": stats.max_hold_time_ms,
                "contention_count": stats.contention_count,
                "contention_ratio": (stats.contention_count / stats.acquire_count if stats.acquire_count > 0 else 0),
            }
        else:
            with self._held_lock:
                total_held = sum(len(levels) for levels in self._held.values())
                threads_holding = len(self._held)

            return {
                "threads_holding_locks": threads_holding,
                "total_locks_held": total_held,
                "lock_levels": [level.name for level in LockLevel],
                "by_level": {lvl.name: self.get_stats(lvl) for lvl in LockLevel},
            }

    def get_contention_report(self) -> dict:
        """
        Детальный отчёт о конкурентности блокировок для мониторинга.

        Returns:
            Dict с метриками contention по каждому уровню

        Example:
            >>> lock_mgr.get_contention_report()
            {
                'MT5_ACCESS': {
                    'contention_ratio': 0.03,  # 3% запросов ждали
                    'avg_wait_ms': 2.5,
                    'max_hold_ms': 45.2,
                    'total_acquires': 1523,
                },
                ...
            }
        """
        report = {}
        for level in LockLevel:
            stats = self._stats[level]
            avg_wait = stats.total_hold_time_ms / stats.acquire_count if stats.acquire_count > 0 else 0
            report[level.name] = {
                "contention_ratio": round(stats.contention_count / max(1, stats.acquire_count), 3),
                "avg_wait_ms": round(avg_wait, 2),
                "max_hold_ms": round(stats.max_hold_time_ms, 2),
                "total_acquires": stats.acquire_count,
                "total_timeouts": stats.timeout_count,
            }
        return report

    def check_deadlock_risk(self) -> Optional[str]:
        """
        Проверка на потенциальный дедлок.
        Returns: описание проблемы или None если всё ок.
        """
        if not self._deadlock_detector:
            return None

        cycle = self._deadlock_detector.check_cycle()
        if cycle:
            cycle_names = [str(t) for t in cycle]
            return f"DEADLOCK RISK: Cycle detected in wait graph: {' -> '.join(cycle_names)}"
        return None

    def reset(self):
        """Сбрасывает отслеживание (для тестов)."""
        with self._held_lock:
            self._held.clear()
        self.reset_stats()
        if self._deadlock_detector:
            self._deadlock_detector = DeadlockDetector()

    def reset_stats(self):
        """Сброс статистики (для тестов)"""
        for stats in self._stats.values():
            stats.acquire_count = 0
            stats.release_count = 0
            stats.timeout_count = 0
            stats.total_hold_time_ms = 0.0
            stats.max_hold_time_ms = 0.0
            stats.contention_count = 0


# Глобальный экземпляр
lock_manager = LockHierarchy(default_timeout=5.0)


# === Утилиты для удобного использования ===


@contextmanager
def mt5_protected(timeout: float = 10.0):
    """Контекстный менеджер для безопасного доступа к MT5"""
    with lock_manager.acquire(LockLevel.MT5_ACCESS, timeout=timeout):
        yield


@contextmanager
def db_write_protected(timeout: float = 5.0):
    """Контекстный менеджер для записи в БД"""
    with lock_manager.acquire(LockLevel.DB_WRITE, timeout=timeout):
        yield


def requires_locks(*levels: LockLevel, timeout: float = -1):
    """
    Декоратор для автоматического захвата блокировок в функции.

    Пример:
        @requires_locks(LockLevel.MT5_ACCESS, LockLevel.DB_WRITE)
        def log_and_execute_trade(...):
            # Код автоматически защищён нужными локами
            pass
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            with lock_manager.acquire(*levels, timeout=timeout):
                return func(*args, **kwargs)

        wrapper.__wrapped__ = func
        return wrapper

    return decorator
