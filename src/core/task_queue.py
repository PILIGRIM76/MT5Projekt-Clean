"""
PriorityTaskQueue — приоритетная очередь задач для TradingSystem.

Заменяет threading.Thread на управляемую очередь с:
- 4 уровнями приоритетов (URGENT → LOW)
- Worker pool с ограничением параллелизма
- Таймаутами на выполнение задач
- Результатами выполнения
"""

import heapq
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Приоритеты задач (меньше = важнее)."""
    URGENT = 0    # Стоп-лосс, аварийное закрытие позиций
    HIGH = 1      # Торговые сигналы, риск-чеки
    MEDIUM = 2    # Обновление GUI, сбор данных
    LOW = 3       # Обучение моделей, логирование, R&D


@dataclass(order=True)
class Task:
    """Задача для очереди."""
    priority: Priority
    sort_key: float = field(compare=True)  # Для стабильной сортировки (timestamp)
    task_id: str = field(compare=False)
    func: Callable = field(compare=False)
    args: tuple = field(default_factory=tuple, compare=False)
    kwargs: dict = field(default_factory=dict, compare=False)
    timeout: float = field(default=30.0, compare=False)  # Таймаут выполнения


class PriorityTaskQueue:
    """
    Приоритетная очередь задач с worker pool.
    
    Использование:
        queue = PriorityTaskQueue(max_workers=4)
        queue.start()
        
        # Отправка задачи
        task_id = queue.submit(
            func=trainer.retrain,
            args=(symbol, timeframe),
            priority=Priority.LOW,
            timeout=300.0
        )
        
        # Получение результата
        result = queue.get_result(task_id, timeout=300)
        
        queue.stop()
    """
    
    def __init__(self, max_workers: int = 4):
        """
        Args:
            max_workers: Количество воркеров (параллельных задач)
        """
        self._queue: list = []
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._max_workers = max_workers
        self._workers: list = []
        self._running = False
        
        # Результаты задач
        self._results: Dict[str, Dict[str, Any]] = {}
        self._results_lock = threading.Lock()
        
        # Статистика
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "timed_out": 0,
        }
        self._stats_lock = threading.Lock()
    
    def submit(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        priority: Priority = Priority.MEDIUM,
        timeout: float = 30.0,
        task_id: Optional[str] = None,
    ) -> str:
        """
        Добавляет задачу в очередь.
        
        Args:
            func: Функция для выполнения
            args: Позиционные аргументы
            kwargs: Именованные аргументы
            priority: Приоритет задачи
            timeout: Таймаут выполнения в секундах
            task_id: Уникальный ID (автогенерация если None)
            
        Returns:
            task_id для получения результата
        """
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        task = Task(
            priority=priority,
            sort_key=time.time(),
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs or {},
            timeout=timeout,
        )
        
        with self._not_empty:
            heapq.heappush(self._queue, task)
            self._not_empty.notify()
        
        with self._stats_lock:
            self._stats["submitted"] += 1
        
        logger.debug(f"📥 Задача {task_id} добавлена (приоритет {priority.name})")
        return task_id
    
    def start(self):
        """Запускает воркеров."""
        if self._running:
            logger.warning("TaskQueue уже запущен")
            return
        
        self._running = True
        for i in range(self._max_workers):
            t = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name=f"TaskWorker-{i}"
            )
            t.start()
            self._workers.append(t)
        
        logger.info(f"🚀 TaskQueue запущен с {self._max_workers} воркерами")
    
    def stop(self, timeout: float = 10.0):
        """
        Останавливает очередь, ожидая завершения текущих задач.
        
        Args:
            timeout: Максимальное время ожидания каждого воркера
        """
        self._running = False
        with self._not_empty:
            self._not_empty.notify_all()
        
        for i, w in enumerate(self._workers):
            w.join(timeout=timeout)
            if w.is_alive():
                logger.warning(f"⚠️ Воркер TaskWorker-{i} не завершился за {timeout}с")
        
        self._workers.clear()
        logger.info("🛑 TaskQueue остановлен")
    
    def get_result(self, task_id: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """
        Получает результат задачи (блокирующий вызов).
        
        Args:
            task_id: ID задачи
            timeout: Максимальное время ожидания
            
        Returns:
            Dict с результатом или None при таймауте:
            {"success": bool, "result/error": Any, "time": float}
        """
        start = time.time()
        while time.time() - start < timeout:
            with self._results_lock:
                if task_id in self._results:
                    return self._results.pop(task_id)
            time.sleep(0.1)
        
        logger.warning(f"⏳ Таймаут ожидания результата {task_id}")
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику очереди."""
        with self._stats_lock:
            stats = dict(self._stats)
        
        with self._lock:
            stats["queue_size"] = len(self._queue)
            stats["pending_by_priority"] = {
                p.name: sum(1 for t in self._queue if t.priority == p)
                for p in Priority
            }
        
        stats["running_workers"] = sum(1 for w in self._workers if w.is_alive())
        return stats
    
    def clear(self):
        """Очищает очередь (но не текущие задачи)."""
        with self._lock:
            cleared = len(self._queue)
            self._queue.clear()
            logger.info(f"🧹 Очищено {cleared} задач из очереди")
    
    def _worker_loop(self):
        """Цикл воркера: берёт задачи и выполняет."""
        while self._running:
            task = None
            with self._not_empty:
                while self._running and not self._queue:
                    self._not_empty.wait(timeout=1.0)
                if not self._running:
                    break
                if self._queue:
                    task = heapq.heappop(self._queue)
            
            if task:
                self._execute_task(task)
    
    def _execute_task(self, task: Task):
        """Выполняет задачу с таймаутом и обработкой ошибок."""
        start = time.time()
        task_name = task.task_id
        
        try:
            logger.debug(f"▶️ Выполнение {task_name} (приоритет {task.priority.name})...")
            
            # Запуск в отдельном потоке для контроля таймаута
            result_container = {"done": False, "result": None, "error": None}
            
            def run():
                try:
                    result_container["result"] = task.func(*task.args, **task.kwargs)
                    result_container["done"] = True
                except Exception as e:
                    result_container["error"] = e
            
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            worker.join(timeout=task.timeout)
            
            elapsed = time.time() - start
            
            if not result_container["done"]:
                # Таймаут
                with self._stats_lock:
                    self._stats["timed_out"] += 1
                
                if worker.is_alive():
                    logger.warning(
                        f"⚠️ Задача {task_name} превысила таймаут {task.timeout}с "
                        f"(выполнялась {elapsed:.1f}с)"
                    )
                
                with self._results_lock:
                    self._results[task.task_id] = {
                        "success": False,
                        "error": f"Timeout after {task.timeout}s",
                        "time": elapsed,
                    }
            elif result_container["error"] is not None:
                # Ошибка выполнения
                with self._stats_lock:
                    self._stats["failed"] += 1
                
                logger.error(f"❌ Ошибка в задаче {task_name}: {result_container['error']}", exc_info=True)
                
                with self._results_lock:
                    self._results[task.task_id] = {
                        "success": False,
                        "error": str(result_container["error"]),
                        "time": elapsed,
                    }
            else:
                # Успех
                with self._stats_lock:
                    self._stats["completed"] += 1
                
                if elapsed > task.timeout * 0.8:
                    logger.warning(
                        f"⚠️ Задача {task_name} близка к таймауту: "
                        f"{elapsed:.1f}s / {task.timeout}s"
                    )
                
                with self._results_lock:
                    self._results[task.task_id] = {
                        "success": True,
                        "result": result_container["result"],
                        "time": elapsed,
                    }
                
                logger.debug(f"✅ Задача {task_name} завершена за {elapsed:.1f}с")
        
        except Exception as e:
            logger.error(f"❌ Критическая ошибка воркера в задаче {task_name}: {e}", exc_info=True)
            with self._results_lock:
                self._results[task.task_id] = {
                    "success": False,
                    "error": str(e),
                    "time": time.time() - start,
                }


# Глобальный экземпляр (ленивая инициализация)
_global_queue: Optional[PriorityTaskQueue] = None
_queue_lock = threading.Lock()


def get_task_queue(max_workers: int = 4) -> PriorityTaskQueue:
    """Получает глобальный экземпляр TaskQueue."""
    global _global_queue
    with _queue_lock:
        if _global_queue is None:
            _global_queue = PriorityTaskQueue(max_workers)
            _global_queue.start()
        return _global_queue


def stop_task_queue(timeout: float = 10.0):
    """Останавливает глобальную очередь."""
    global _global_queue
    with _queue_lock:
        if _global_queue is not None:
            _global_queue.stop(timeout)
            _global_queue = None
