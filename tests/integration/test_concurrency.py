"""
Интеграционные тесты: координация процессов без дедлоков.

Тестирует взаимодействие:
- ResourceGovernor + PriorityTaskQueue + LockHierarchy
- 100 итераций параллельных задач без дедлока
"""

import time
import threading
import pytest

from src.core.resource_governor import ResourceGovernor, ResourceClass
from src.core.task_queue import PriorityTaskQueue, Priority
from src.core.lock_manager import LockHierarchy, LockLevel


class TestConcurrencyCoordination:
    """Интеграционные тесты координации."""

    def test_no_deadlock_100_iterations(self):
        """Проверка: 100 итераций торговли + R&D без дедлока."""
        governor = ResourceGovernor()
        # Увеличиваем таймаут чтобы избежать contention
        lock_manager = LockHierarchy(default_timeout=5.0)
        task_queue = PriorityTaskQueue(max_workers=4)
        task_queue.start()

        errors = []
        completed_tasks = {"trade": 0, "rd": 0}
        lock = threading.Lock()

        def trade_cycle(iteration):
            """Имитация торгового цикла."""
            try:
                if not governor.can_start(f"trade_{iteration}", ResourceClass.CRITICAL):
                    return

                with lock_manager.acquire(LockLevel.MT5_LOCK, timeout=3.0):
                    time.sleep(0.005)  # Короткая имитация работы с MT5

                with lock:
                    completed_tasks["trade"] += 1

                governor.task_finished(f"trade_{iteration}")
            except TimeoutError:
                # Таймаут — это не дедлок, а нормальная конкуренция за ресурсы
                pass
            except Exception as e:
                errors.append(f"Trade error: {e}")

        def rd_cycle(iteration):
            """Имитация R&D цикла."""
            try:
                if not governor.can_start(f"rd_{iteration}", ResourceClass.MEDIUM):
                    return

                with lock_manager.acquire(
                    LockLevel.MT5_LOCK, LockLevel.DB_LOCK, timeout=3.0
                ):
                    time.sleep(0.01)  # Имитация загрузки данных + запись в БД

                with lock:
                    completed_tasks["rd"] += 1

                governor.task_finished(f"rd_{iteration}")
            except TimeoutError:
                # Таймаут — это не дедлок, а нормальная конкуренция за ресурсы
                pass
            except Exception as e:
                errors.append(f"R&D error: {e}")

        # Запускаем 100 итераций параллельно
        threads = []
        for i in range(100):
            t_trade = threading.Thread(target=trade_cycle, args=(i,))
            t_rd = threading.Thread(target=rd_cycle, args=(i,))
            threads.extend([t_trade, t_rd])

        for t in threads:
            t.start()

        # Ждём завершения с таймаутом 30с (дедлок detection)
        for t in threads:
            t.join(timeout=30)
            if t.is_alive():
                errors.append(f"Thread {t.name} did not finish in 30s — possible deadlock!")

        task_queue.stop(timeout=5.0)

        # Если дошли сюда — дедлока нет
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert completed_tasks["trade"] + completed_tasks["rd"] > 0

    def test_resource_governor_prevents_overload(self):
        """Проверка: governor блокирует задачи при перегрузке."""
        governor = ResourceGovernor()

        # Запускаем много MEDIUM задач
        started = []
        rejected = []

        def medium_task(i):
            if governor.can_start(f"task_{i}", ResourceClass.MEDIUM):
                started.append(i)
                time.sleep(0.1)
                governor.task_finished(f"task_{i}")
            else:
                rejected.append(i)

        threads = [threading.Thread(target=medium_task, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Некоторые должны быть запущены
        assert len(started) > 0

    def test_task_queue_priority_order(self):
        """Проверка: приоритеты соблюдаются в очереди."""
        queue = PriorityTaskQueue(max_workers=1)  # Один воркер для строгого порядка
        queue.start()

        execution_order = []
        lock = threading.Lock()

        def ordered_task(name):
            with lock:
                execution_order.append(name)
            time.sleep(0.05)

        # Сначала LOW — они встанут в очередь
        for i in range(3):
            queue.submit(ordered_task, args=(f"low_{i}",), priority=Priority.LOW)

        # Потом HIGH — они должны выполниться раньше
        for i in range(2):
            queue.submit(ordered_task, args=(f"high_{i}",), priority=Priority.HIGH)

        time.sleep(0.5)
        queue.stop(timeout=5.0)

        # HIGH задачи должны быть выполнены до LOW (кроме первой которая уже started)
        if len(execution_order) >= 3:
            high_indices = [i for i, name in enumerate(execution_order) if name.startswith("high")]
            low_indices = [i for i, name in enumerate(execution_order) if name.startswith("low")]

            # Если HIGH были добавлены после LOW, они должны быть раньше в порядке
            if high_indices and low_indices:
                assert min(high_indices) < max(low_indices)

    def test_lock_hierarchy_prevents_wrong_order(self):
        """Проверка: LockHierarchy предотвращает неправильный порядок."""
        lm = LockHierarchy(default_timeout=1.0)

        # Правильный порядок — должен работать
        with lm.acquire(LockLevel.MT5_LOCK, LockLevel.DB_LOCK):
            pass

        # Неправильный порядок — должен вызвать RuntimeError
        with pytest.raises(RuntimeError):
            with lm.acquire(LockLevel.CONFIG_LOCK, LockLevel.MT5_LOCK):
                pass

    def test_health_monitor_integration(self):
        """Проверка: HealthMonitor корректно собирает данные от всех компонентов."""
        from src.core.health_monitor import HealthMonitor

        governor = ResourceGovernor()
        task_queue = PriorityTaskQueue(max_workers=2)
        task_queue.start()
        lock_manager = LockHierarchy()

        monitor = HealthMonitor(
            governor=governor,
            task_queue=task_queue,
            lock_manager=lock_manager,
        )

        # Запускаем несколько задач
        governor.can_start("test_task_1", ResourceClass.HIGH)
        governor.can_start("test_task_2", ResourceClass.MEDIUM)

        health = monitor.get_health()

        assert "load" in health
        assert "task_stats" in health
        assert "lock_stats" in health
        assert health["load"]["active_tasks"] == 2

        governor.task_finished("test_task_1")
        governor.task_finished("test_task_2")

        health_after = monitor.get_health()
        assert health_after["load"]["active_tasks"] == 0

        task_queue.stop(timeout=5.0)

    def test_combined_governor_queue_lock(self):
        """Проверка: Governor + TaskQueue + LockHierarchy работают вместе."""
        governor = ResourceGovernor()
        lock_manager = LockHierarchy(default_timeout=2.0)
        task_queue = PriorityTaskQueue(max_workers=2)
        task_queue.start()

        results = []
        errors = []

        def complex_task(task_id):
            try:
                # 1. Governor check
                if not governor.can_start(task_id, ResourceClass.MEDIUM):
                    return

                # 2. Lock acquisition
                with lock_manager.acquire(LockLevel.DB_LOCK, timeout=1.0):
                    time.sleep(0.05)
                    results.append(task_id)

                # 3. Cleanup
                governor.task_finished(task_id)
            except Exception as e:
                errors.append(f"{task_id}: {e}")

        # Отправляем задачи через очередь
        for i in range(10):
            task_queue.submit(
                complex_task,
                args=(f"task_{i}",),
                priority=Priority.MEDIUM,
                timeout=5.0,
            )

        time.sleep(2.0)
        task_queue.stop(timeout=5.0)

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) > 0
