"""
LockHierarchy — иерархия блокировок для TradingSystem.

Правило: захватывать блокировки ТОЛЬКО в порядке возрастания уровней:
  1. MT5_LOCK (доступ к терминалу)
  2. DB_LOCK (запись в БД)
  3. MODEL_LOCK (загрузка/сохранение моделей)
  4. CONFIG_LOCK (изменение конфигов)

Нарушение порядка → RuntimeError.
Превышение таймаута → TimeoutError.
"""

import logging
import threading
from contextlib import contextmanager
from enum import IntEnum
from typing import Iterator, Set

logger = logging.getLogger(__name__)


class LockLevel(IntEnum):
    """Уровни блокировок (захватывать только по возрастанию!)."""
    MT5_LOCK = 1       # Доступ к терминалу MetaTrader 5
    DB_LOCK = 2        # Запись в базу данных
    MODEL_LOCK = 3     # Загрузка/сохранение моделей
    CONFIG_LOCK = 4    # Изменение конфигурации


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
    """
    
    def __init__(self, default_timeout: float = 5.0):
        """
        Args:
            default_timeout: Таймаут по умолчанию для всех блокировок
        """
        self._locks = {
            LockLevel.MT5_LOCK: threading.RLock(),
            LockLevel.DB_LOCK: threading.RLock(),
            LockLevel.MODEL_LOCK: threading.RLock(),
            LockLevel.CONFIG_LOCK: threading.RLock(),
        }
        self._default_timeout = default_timeout
        
        # Отслеживание какие блокировки держит каждый поток
        self._held: dict = {}  # thread_id -> set of LockLevel
        self._held_lock = threading.Lock()
    
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
        
        # Проверка порядка (должны быть отсортированы)
        level_list = list(levels)
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
        
        try:
            for level in level_list:
                lock = self._locks[level]
                if not lock.acquire(timeout=timeout):
                    raise TimeoutError(
                        f"Не удалось захватить блокировку уровня {level.name} "
                        f"за {timeout}с (поток {tid})"
                    )
                acquired.append(level)
                
                with self._held_lock:
                    self._held.setdefault(tid, set()).add(level)
                
                logger.debug(f"🔒 Захвачен лок {level.name} (поток {tid})")
            
            yield
        
        finally:
            # Освобождаем в обратном порядке
            for level in reversed(acquired):
                self._locks[level].release()
                
                with self._held_lock:
                    held_set = self._held.get(tid, set())
                    held_set.discard(level)
                    if not held_set:
                        self._held.pop(tid, None)
                
                logger.debug(f"🔓 Освобождён лок {level.name} (поток {tid})")
    
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
            return level in self._held.get(tid, set())
    
    def get_held_levels(self) -> Set[LockLevel]:
        """Возвращает блокировки которые держит текущий поток."""
        tid = threading.get_ident()
        with self._held_lock:
            return set(self._held.get(tid, set()))
    
    def get_stats(self) -> dict:
        """Возвращает статистику блокировок."""
        with self._held_lock:
            total_held = sum(len(levels) for levels in self._held.values())
            threads_holding = len(self._held)
        
        return {
            "threads_holding_locks": threads_holding,
            "total_locks_held": total_held,
            "lock_levels": [level.name for level in LockLevel],
        }
    
    def reset(self):
        """Сбрасывает отслеживание (для тестов)."""
        with self._held_lock:
            self._held.clear()


# Глобальный экземпляр
lock_manager = LockHierarchy(default_timeout=5.0)
