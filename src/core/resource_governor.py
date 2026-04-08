"""
ResourceGovernor — контроль загрузки CPU/RAM/GPU для TradingSystem.

Превращает набор потоков в слаженный организм:
- Жёсткие лимиты для каждого класса задач
- Автоматический backpressure при перегрузке
- Мониторинг загрузки для health dashboard
"""

import logging
import threading
import time
from enum import Enum, auto
from typing import Any, Dict, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None

logger = logging.getLogger(__name__)


class ResourceClass(Enum):
    """Классы ресурсов с разными лимитами."""
    CRITICAL = auto()    # Торговля, исполнение ордеров — всегда приоритет
    HIGH = auto()        # Сигналы, риск-менеджмент
    MEDIUM = auto()      # R&D, переобучение моделей
    LOW = auto()         # Логирование, сбор метрик, GUI


# Жёсткие лимиты для максимальной защиты (настроены под 16 ГБ систему)
DEFAULT_LIMITS = {
    ResourceClass.CRITICAL: {
        "cpu_pct": 85,
        "ram_free_min_gb": 1.0,   # Минимум 1 ГБ должно оставаться свободным
        "ram_max_gb": None,        # Не ограничиваем абсолютно
        "gpu_mem_gb": None,
    },
    ResourceClass.HIGH: {
        "cpu_pct": 65,
        "ram_free_min_gb": 1.5,   # Сигналы требуют запаса
        "ram_max_gb": 3.0,         # Максимум 3 ГБ на задачу
        "gpu_mem_gb": 1.5,
    },
    ResourceClass.MEDIUM: {
        "cpu_pct": 45,
        "ram_free_min_gb": 2.0,   # R&D только если свободно >= 2 ГБ
        "ram_max_gb": 1.5,
        "gpu_mem_gb": 0.5,
    },
    ResourceClass.LOW: {
        "cpu_pct": 25,
        "ram_free_min_gb": 3.0,   # Логи только если есть запас!
        "ram_max_gb": 0.8,
        "gpu_mem_gb": 0.0,
    },
}


class ResourceGovernor:
    """
    Singleton: контролирует загрузку системы и решает можно ли запустить задачу.
    
    Использование:
        governor = ResourceGovernor()
        if governor.can_start("retrain_EURUSD", ResourceClass.MEDIUM):
            try:
                trainer.retrain()
            finally:
                governor.task_finished("retrain_EURUSD")
    """
    _instance: Optional["ResourceGovernor"] = None
    _singleton_lock = threading.Lock()
    
    def __new__(cls, limits: Optional[Dict[ResourceClass, Dict[str, Any]]] = None):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, limits: Optional[Dict[ResourceClass, Dict[str, Any]]] = None):
        if self._initialized:
            return
        
        self._lock = threading.RLock()
        self._limits = limits or DEFAULT_LIMITS
        self._active_tasks: Dict[str, ResourceClass] = {}
        self._task_start_times: Dict[str, float] = {}
        self._rejected_count = 0
        self._total_tasks = 0
        self._initialized = True
        
        if not HAS_PSUTIL:
            logger.warning("⚠️ psutil не установлен — мониторинг CPU/RAM отключён")
            logger.info("   Установите: pip install psutil")
        
        logger.info(
            f"🎛️ ResourceGovernor инициализирован "
            f"(limits: {len(self._limits)} классов, psutil={'✅' if HAS_PSUTIL else '❌'})"
        )
    
    def can_start(self, task_id: str, rclass: ResourceClass) -> bool:
        """
        Проверяет можно ли запустить задачу без перегрузки системы.
        
        Args:
            task_id: Уникальный идентификатор задачи
            rclass: Класс ресурсов задачи
            
        Returns:
            True если задача может быть запущена
        """
        with self._lock:
            # 1. Проверка CPU
            cpu_limit = self._limits[rclass]["cpu_pct"]
            if cpu_limit is not None and HAS_PSUTIL:
                cpu_pct = psutil.cpu_percent(interval=0.1)
                if cpu_pct > cpu_limit:
                    self._rejected_count += 1
                    logger.warning(
                        f"⏳ CPU перегрузка: {cpu_pct}% > {cpu_limit}% "
                        f"(задача {task_id}, класс {rclass.name})"
                    )
                    return False
            
            # 2. Проверка RAM — используем available (реально свободно), не used!
            ram_free_min = self._limits[rclass].get("ram_free_min_gb")
            if ram_free_min is not None and HAS_PSUTIL:
                free_gb = psutil.virtual_memory().available / (1024 ** 3)
                if free_gb < ram_free_min:
                    self._rejected_count += 1
                    logger.warning(
                        f"⏳ Недостаточно свободной RAM: {free_gb:.1f}GB < {ram_free_min}GB "
                        f"(задача {task_id}, класс {rclass.name})"
                    )
                    return False
            
            # 3. Проверка максимального потребления задачи (если задано)
            ram_max = self._limits[rclass].get("ram_max_gb")
            if ram_max is not None and HAS_PSUTIL:
                estimated = self._estimate_task_ram(task_id, rclass)
                if estimated > ram_max:
                    self._rejected_count += 1
                    logger.warning(
                        f"⏳ Задача {task_id} требует ~{estimated:.1f}GB > лимит {ram_max}GB "
                        f"(класс {rclass.name})"
                    )
                    return False
            
            # 4. Проверка GPU
            gpu_limit = self._limits[rclass].get("gpu_mem_gb")
            if gpu_limit is not None and HAS_TORCH and torch.cuda.is_available():
                gpu_mem_gb = torch.cuda.memory_allocated(0) / (1024 ** 3)
                if gpu_mem_gb > gpu_limit:
                    self._rejected_count += 1
                    logger.warning(
                        f"⏳ GPU перегрузка: {gpu_mem_gb:.1f}GB > {gpu_limit}GB "
                        f"(задача {task_id}, класс {rclass.name})"
                    )
                    return False
            
            # Всё ок — регистрируем задачу
            self._active_tasks[task_id] = rclass
            self._task_start_times[task_id] = time.time()
            self._total_tasks += 1
            
            logger.info(f"✅ Задача {task_id} запущена (класс {rclass.name})")
            return True
    
    def task_finished(self, task_id: str) -> Optional[float]:
        """
        Освобождает ресурсы после завершения задачи.
        
        Returns:
            Время выполнения задачи в секундах или None
        """
        with self._lock:
            start_time = self._task_start_times.pop(task_id, None)
            self._active_tasks.pop(task_id, None)
            
            if start_time is not None:
                elapsed = time.time() - start_time
                logger.debug(f"🔓 Задача {task_id} завершена за {elapsed:.1f}с")
                return elapsed
            
            logger.debug(f"🔓 Задача {task_id} завершена (время неизвестно)")
            return None
    
    def _estimate_task_ram(self, task_id: str, rclass: ResourceClass) -> float:
        """
        Оценивает потребление RAM задачей в ГБ.
        
        Args:
            task_id: ID задачи
            rclass: Класс ресурсов
            
        Returns:
            Оценка в ГБ
        """
        # Упрощённая оценка по типу задачи
        if "retrain" in task_id or "training" in task_id:
            return 1.5  # Обучение моделей — много RAM
        elif "signal" in task_id or "predict" in task_id:
            return 0.5  # Инференс — умеренно
        elif "rd" in task_id or "research" in task_id:
            return 1.0  # R&D — средне
        else:
            return 0.3  # По умолчанию — мало
    
    def get_load_summary(self) -> Dict[str, Any]:
        """
        Возвращает текущую загрузку системы для мониторинга.
        
        Returns:
            Dict с метриками загрузки
        """
        summary: Dict[str, Any] = {
            "active_tasks": len(self._active_tasks),
            "total_tasks": self._total_tasks,
            "rejected_tasks": self._rejected_count,
        }
        
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            summary["cpu_pct"] = psutil.cpu_percent(interval=0.1)
            summary["ram_available_gb"] = mem.available / (1024 ** 3)  # Реально доступно
            summary["ram_used_gb"] = mem.used / (1024 ** 3)
            summary["ram_total_gb"] = mem.total / (1024 ** 3)
            summary["ram_pct"] = mem.percent
            summary["ram_cached_gb"] = (mem.total - mem.available - mem.used) / (1024 ** 3)
            
            # Swap
            swap = psutil.swap_memory()
            summary["swap_pct"] = swap.percent
            summary["swap_free_gb"] = swap.free / (1024 ** 3)
        
        if HAS_TORCH and torch.cuda.is_available():
            summary["gpu_mem_gb"] = torch.cuda.memory_allocated(0) / (1024 ** 3)
            summary["gpu_total_gb"] = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        
        # Список активных задач
        summary["tasks"] = [
            {
                "id": task_id,
                "class": rclass.name,
                "duration_s": time.time() - self._task_start_times.get(task_id, 0),
            }
            for task_id, rclass in self._active_tasks.items()
        ]
        
        return summary
    
    def get_memory_alert_level(self) -> str:
        """
        Определяет уровень алерта по памяти.
        
        Returns:
            "critical", "warning", "info", или "ok"
        """
        if not HAS_PSUTIL:
            return "ok"
        
        mem = psutil.virtual_memory()
        free_gb = mem.available / (1024 ** 3)
        swap = psutil.swap_memory()
        
        if free_gb < 1.0:
            return "critical"  # < 1 ГБ свободно
        elif free_gb < 2.5 or swap.percent > 70:
            return "warning"   # < 2.5 ГБ или swap > 70%
        elif mem.percent > 85:
            return "info"
        
        return "ok"
    
    def is_overloaded(self) -> bool:
        """
        Проверяет перегружена ли система в целом.
        
        Returns:
            True если система перегружена
        """
        if not HAS_PSUTIL:
            return False
        
        cpu_pct = psutil.cpu_percent(interval=0.1)
        ram_pct = psutil.virtual_memory().percent
        
        return cpu_pct > 90 or ram_pct > 95
    
    def kill_low_priority_tasks(self, min_rclass: ResourceClass = ResourceClass.LOW) -> list:
        """
        Принудительно завершает задачи низкого приоритета при перегрузке.
        
        Args:
            min_rclass: Минимальный класс задач для завершения
            
        Returns:
            Список ID завершённых задач
        """
        with self._lock:
            to_kill = [
                task_id for task_id, rclass in self._active_tasks.items()
                if rclass.value >= min_rclass.value
            ]
            
            for task_id in to_kill:
                self._active_tasks.pop(task_id, None)
                self._task_start_times.pop(task_id, None)
                logger.warning(f"🗑️ Задача {task_id} принудительно завершена (перегрузка)")
            
            return to_kill
    
    def reset_stats(self):
        """Сбрасывает статистику (для тестов)."""
        with self._lock:
            self._rejected_count = 0
            self._total_tasks = 0


# Глобальный singleton
_governor_instance: Optional[ResourceGovernor] = None


def get_governor(limits: Optional[Dict[ResourceClass, Dict[str, Any]]] = None) -> ResourceGovernor:
    """Получает глобальный экземпляр ResourceGovernor."""
    global _governor_instance
    if _governor_instance is None:
        _governor_instance = ResourceGovernor(limits)
    return _governor_instance
