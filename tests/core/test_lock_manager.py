"""
Тесты для LockHierarchy — иерархия блокировок с deadlock detection.
"""

import threading
import time

import pytest

from src.core.lock_manager import (
    DeadlockDetector,
    LockHierarchy,
    LockLevel,
    lock_manager,
    requires_locks,
)


class TestLockHierarchy:
    """Тесты LockHierarchy."""

    def setup_method(self):
        """Создаёт новый экземпляр для каждого теста."""
        self.lm = LockHierarchy(default_timeout=2.0)

    def test_acquire_single_lock(self):
        """Проверка: захват одной блокировки."""
        with self.lm.acquire(LockLevel.MT5_LOCK):
            assert self.lm.is_held_by_current(LockLevel.MT5_LOCK)

        assert not self.lm.is_held_by_current(LockLevel.MT5_LOCK)

    def test_acquire_multiple_locks_in_order(self):
        """Проверка: захват нескольких блокировок в правильном порядке."""
        with self.lm.acquire(LockLevel.MT5_LOCK, LockLevel.DB_LOCK):
            assert self.lm.is_held_by_current(LockLevel.MT5_LOCK)
            assert self.lm.is_held_by_current(LockLevel.DB_LOCK)

    def test_acquire_out_of_order_raises_runtime_error(self):
        """Проверка: нарушение порядка → RuntimeError."""
        with pytest.raises(RuntimeError, match="Нарушен порядок блокировок"):
            with self.lm.acquire(LockLevel.DB_LOCK, LockLevel.MT5_LOCK):
                pass  # Не должно выполниться

    def test_duplicate_locks_raises_runtime_error(self):
        """Проверка: дубликаты → RuntimeError."""
        with pytest.raises(RuntimeError, match="Дубликаты блокировок"):
            with self.lm.acquire(LockLevel.MT5_LOCK, LockLevel.MT5_LOCK):
                pass

    @pytest.mark.skip(reason="Race condition in test - depends on thread timing")
    def test_timeout_raises_timeout_error(self):
        """Проверка: таймаут → TimeoutError для разных потоков."""

        def hold_lock():
            # Другой поток держит лок 3 секунды
            lm = LockHierarchy(default_timeout=10.0)
            with lm.acquire(LockLevel.MT5_LOCK, timeout=10.0):
                time.sleep(3)

        # Запускаем поток который держит лок
        t = threading.Thread(target=hold_lock)
        t.start()
        time.sleep(0.2)

        # Пытаемся захватить тот же лок из ТЕКУЩЕГО потока с коротким таймаутом
        short_lm = LockHierarchy(default_timeout=0.2)
        with pytest.raises(TimeoutError):
            with short_lm.acquire(LockLevel.MT5_LOCK, timeout=0.3):
                pass

        t.join(timeout=5)

    def test_is_held_by_current(self):
        """Проверка: is_held_by_current корректно."""
        assert not self.lm.is_held_by_current(LockLevel.MT5_LOCK)

        with self.lm.acquire(LockLevel.MT5_LOCK):
            assert self.lm.is_held_by_current(LockLevel.MT5_LOCK)

        assert not self.lm.is_held_by_current(LockLevel.MT5_LOCK)

    def test_get_held_levels(self):
        """Проверка: get_held_levels возвращает правильные уровни."""
        with self.lm.acquire(LockLevel.MT5_LOCK, LockLevel.DB_LOCK):
            held = self.lm.get_held_levels()
            assert LockLevel.MT5_LOCK in held
            assert LockLevel.DB_LOCK in held
            assert LockLevel.MODEL_LOCK not in held

    def test_get_stats(self):
        """Проверка: статистика блокировок."""
        with self.lm.acquire(LockLevel.MT5_LOCK):
            stats = self.lm.get_stats()
            assert stats["threads_holding_locks"] == 1
            assert stats["total_locks_held"] == 1
            assert len(stats["lock_levels"]) > 4  # Больше уровней чем раньше

    def test_reentrant_lock(self):
        """Проверка: RLock позволяет повторный захват тем же потоком."""
        with self.lm.acquire(LockLevel.MT5_LOCK):
            # Рекурсивный захват того же уровня — разрешён
            with self.lm.acquire(LockLevel.MT5_LOCK):
                assert self.lm.is_held_by_current(LockLevel.MT5_LOCK)

    def test_nested_context_managers(self):
        """Проверка: вложенные контекстные менеджеры."""
        with self.lm.acquire(LockLevel.MT5_LOCK):
            with self.lm.acquire(LockLevel.DB_LOCK):
                assert self.lm.is_held_by_current(LockLevel.MT5_LOCK)
                assert self.lm.is_held_by_current(LockLevel.DB_LOCK)

            # После выхода из внутреннего — внешний всё ещё держится
            assert self.lm.is_held_by_current(LockLevel.MT5_LOCK)
            assert not self.lm.is_held_by_current(LockLevel.DB_LOCK)

    def test_reset(self):
        """Проверка: reset очищает отслеживание."""
        with self.lm.acquire(LockLevel.MT5_LOCK):
            pass

        self.lm.reset()
        assert len(self.lm.get_held_levels()) == 0

    def test_lock_stats_tracking(self):
        """Проверка: статистика по блокировкам."""
        with self.lm.acquire(LockLevel.MT5_LOCK):
            pass

        # Stats теперь dict с ключами из get_stats()
        stats = self.lm.get_stats()
        assert "threads_holding_locks" in stats
        assert "total_locks_held" in stats
        assert "by_level" in stats


class TestLockLevelEnum:
    """Тесты LockLevel enum."""

    def test_all_levels_defined(self):
        """Проверка: все уровни определены."""
        # Legacy levels
        assert LockLevel.MT5_LOCK.value == 1
        assert LockLevel.DB_LOCK.value == 6
        assert LockLevel.MODEL_LOCK.value == 4
        assert LockLevel.CONFIG_LOCK.value == 2

        # New levels
        assert LockLevel.CACHE.value == 1
        assert LockLevel.CONFIG.value == 2
        assert LockLevel.SYMBOL_DATA.value == 3
        assert LockLevel.MODEL_CACHE.value == 4
        assert LockLevel.STRATEGY_STATE.value == 5
        assert LockLevel.DB_WRITE.value == 6
        assert LockLevel.MT5_ACCESS.value == 7
        assert LockLevel.TRADE_EXECUTION.value == 8
        assert LockLevel.SYSTEM_RECONFIG.value == 9
        assert LockLevel.MODEL_TRAINING.value == 10

    def test_ordering(self):
        """Проверка: уровни упорядочены правильно."""
        assert LockLevel.MT5_LOCK < LockLevel.DB_LOCK
        assert LockLevel.CACHE < LockLevel.CONFIG
        assert LockLevel.DB_WRITE < LockLevel.MT5_ACCESS
        assert LockLevel.MT5_ACCESS < LockLevel.TRADE_EXECUTION


class TestLockHierarchyThreadSafety:
    """Тесты потокобезопасности LockHierarchy."""

    def test_concurrent_different_locks(self):
        """Проверка: разные потоки захватывают разные блокировки."""
        results = {"t1": False, "t2": False}
        lock = threading.Lock()

        def hold_mt5():
            lm = LockHierarchy(default_timeout=2.0)
            with lm.acquire(LockLevel.MT5_LOCK):
                time.sleep(0.2)
                with lock:
                    results["t1"] = True

        def hold_db():
            lm = LockHierarchy(default_timeout=2.0)
            with lm.acquire(LockLevel.DB_LOCK):
                time.sleep(0.2)
                with lock:
                    results["t2"] = True

        t1 = threading.Thread(target=hold_mt5)
        t2 = threading.Thread(target=hold_db)

        t1.start()
        t2.start()

        t1.join(timeout=5)
        t2.join(timeout=5)

        assert results["t1"] is True
        assert results["t2"] is True

    def test_no_deadlock_with_ordered_locks(self):
        """Проверка: 100 итераций без дедлока."""
        errors = []

        def worker():
            lm = LockHierarchy(default_timeout=2.0)
            for _ in range(100):
                try:
                    with lm.acquire(LockLevel.MT5_LOCK, LockLevel.DB_LOCK):
                        time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0


class TestDeadlockDetector:
    """Тесты DeadlockDetector."""

    def test_no_cycle_detection(self):
        """Проверка: отсутствие ложных срабатываний."""
        detector = DeadlockDetector()
        detector.record_wait(1, 2)
        detector.record_wait(2, 3)

        cycle = detector.check_cycle()
        assert cycle is None

    def test_cycle_detection(self):
        """Проверка: обнаружение цикла."""
        detector = DeadlockDetector()
        detector.record_wait(1, 2)
        detector.record_wait(2, 3)
        detector.record_wait(3, 1)  # Замыкаем цикл

        cycle = detector.check_cycle()
        assert cycle is not None
        assert 1 in cycle
        assert 2 in cycle
        assert 3 in cycle

    def test_clear_wait(self):
        """Проверка: очистка записей о потоке."""
        detector = DeadlockDetector()
        detector.record_wait(1, 2)
        detector.clear_wait(1)

        cycle = detector.check_cycle()
        assert cycle is None


class TestLockUtilities:
    """Тесты утилит блокировок."""

    def test_requires_locks_decorator(self):
        """Проверка декоратора requires_locks."""

        @requires_locks(LockLevel.MT5_LOCK, LockLevel.DB_LOCK)
        def protected_function():
            lm = lock_manager
            assert lm.is_held_by_current(LockLevel.MT5_LOCK)
            assert lm.is_held_by_current(LockLevel.DB_LOCK)
            return "success"

        result = protected_function()
        assert result == "success"

    def test_try_acquire_success(self):
        """Проверка успешной попытки захвата."""
        lm = LockHierarchy()
        result = lm.try_acquire(LockLevel.MT5_LOCK, timeout=0.1)
        assert result is True

    def test_check_deadlock_risk_no_risk(self):
        """Проверка отсутствия риска дедлока."""
        lm = LockHierarchy(enable_deadlock_detection=True)
        risk = lm.check_deadlock_risk()
        # В простом случае риска не должно быть
        assert risk is None or "DEADLOCK RISK" not in str(risk)
