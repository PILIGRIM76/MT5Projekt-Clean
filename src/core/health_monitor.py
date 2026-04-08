"""
Health Dashboard — мониторинг состояния TradingSystem.

Предоставляет:
- Текущую загрузку CPU/RAM/GPU
- Статистику задач (active/completed/failed)
- Состояние блокировок
- Статус системы (healthy/degraded/overloaded)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Монитор здоровья системы.
    
    Использование:
        monitor = HealthMonitor(governor, task_queue, lock_manager)
        
        # Проверка статуса
        status = monitor.get_health()
        if status["status"] != "healthy":
            logger.warning(f"Система в состоянии {status['status']}")
        
        # Алёрты при перегрузке
        monitor.check_and_alert()
    """
    
    def __init__(
        self,
        governor: Any = None,
        task_queue: Any = None,
        lock_manager: Any = None,
        trading_system: Any = None,
    ):
        """
        Args:
            governor: ResourceGovernor экземпляр
            task_queue: PriorityTaskQueue экземпляр
            lock_manager: LockHierarchy экземпляр
            trading_system: TradingSystem экземпляр (опционально)
        """
        self.governor = governor
        self.task_queue = task_queue
        self.lock_manager = lock_manager
        self.trading_system = trading_system
        
        self._last_overload_alert = 0
        self._overload_cooldown = 30  # Не спамить алёртами чаще 30с
        self._alert_count = 0
    
    def get_health(self) -> Dict[str, Any]:
        """
        Возвращает полное состояние системы.
        
        Returns:
            Dict с информацией о здоровье системы
        """
        health: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "13.0.0",
        }
        
        # 1. Загрузка ресурсов
        if self.governor:
            load = self.governor.get_load_summary()
            health["load"] = load
            
            # Определяем статус по загрузке
            cpu_pct = load.get("cpu_pct", 0)
            ram_pct = load.get("ram_pct", 0)
            
            if cpu_pct > 95 or ram_pct > 95:
                health["status"] = "overloaded"
            elif cpu_pct > 85 or ram_pct > 85 or self.governor.is_overloaded():
                health["status"] = "degraded"
            else:
                health["status"] = "healthy"
        
        # 2. Статистика задач
        if self.task_queue:
            health["task_stats"] = self.task_queue.get_stats()
        
        # 3. Состояние блокировок
        if self.lock_manager:
            health["lock_stats"] = self.lock_manager.get_stats()
        
        # 4. Состояние торговой системы
        if self.trading_system:
            health["trading"] = {
                "running": getattr(self.trading_system, "is_heavy_init_complete", False),
                "mt5_connected": not getattr(self.trading_system, "mt5_connection_failed", True),
                "active_positions": len(getattr(self.trading_system, "_last_positions_cache", [])),
                "last_balance": getattr(self.trading_system, "_last_known_balance", None),
                "last_equity": getattr(self.trading_system, "_last_known_equity", None),
            }
        
        return health
    
    def check_and_alert(self) -> Optional[str]:
        """
        Проверяет перегрузку и генерирует алёрт.
        
        Returns:
            Текст алёрта или None
        """
        now = time.time()
        if now - self._last_overload_alert < self._overload_cooldown:
            return None  # Кулдаун
        
        if not self.governor:
            return None
        
        # Проверяем общий статус перегрузки
        is_overloaded = self.governor.is_overloaded()
        
        # Проверяем уровень алерта по памяти
        memory_alert = self.governor.get_memory_alert_level()
        
        if not is_overloaded and memory_alert == "ok":
            return None
        
        self._last_overload_alert = now
        self._alert_count += 1
        
        load = self.governor.get_load_summary()
        
        # Формируем сообщение
        parts = []
        if is_overloaded:
            parts.append("🚨 ПЕРЕГРУЗКА СИСТЕМЫ")
        if memory_alert in ("critical", "warning"):
            emoji = "🔴" if memory_alert == "critical" else "🟡"
            parts.append(f"{emoji} ПАМЯТЬ: {memory_alert.upper()}")
        
        parts.append(f"(алёрт #{self._alert_count})")
        
        details = [
            f"CPU: {load.get('cpu_pct', 0):.1f}%",
            f"RAM доступно: {load.get('ram_available_gb', 0):.1f}GB / {load.get('ram_total_gb', 0):.1f}GB",
            f"RAM кэш: {load.get('ram_cached_gb', 0):.1f}GB",
        ]
        
        if load.get('swap_pct', 0) > 0:
            details.append(f"Swap: {load.get('swap_pct', 0):.0f}% (свободно {load.get('swap_free_gb', 0):.1f}GB)")
        
        if load.get('gpu_mem_gb', 0) > 0:
            details.append(f"GPU: {load.get('gpu_mem_gb', 0):.1f}GB / {load.get('gpu_total_gb', 0):.1f}GB")
        
        details.append(f"Активных задач: {load.get('active_tasks', 0)}")
        
        alert = "\n".join([" ".join(parts)] + details)
        
        if memory_alert == "critical":
            logger.critical(alert)
        elif memory_alert == "warning" or is_overloaded:
            logger.warning(alert)
        else:
            logger.info(alert)
        
        # Принудительное завершение низкоприоритетных задач при критической нехватке памяти
        if memory_alert == "critical" or (is_overloaded and memory_alert == "warning"):
            from src.core.resource_governor import ResourceClass
            killed = self.governor.kill_low_priority_tasks(ResourceClass.LOW)
            if killed:
                logger.warning(f"🗑️ Завершены низкоприоритетные задачи: {killed}")
        
        return alert
    
    def get_summary(self) -> str:
        """Возвращает читаемую сводку состояния системы."""
        health = self.get_health()
        status = health.get("status", "unknown")
        
        lines = [
            f"{'=' * 50}",
            f"  Health Dashboard v{health.get('version', '?')}",
            f"{'=' * 50}",
            f"  Status: {status.upper()}",
            f"  Time: {health.get('timestamp', '?')}",
        ]
        
        if "load" in health:
            load = health["load"]
            lines.extend([
                f"",
                f"  Resources:",
                f"    CPU: {load.get('cpu_pct', 0):.1f}%",
                f"    RAM: {load.get('ram_used_gb', 0):.1f}GB / {load.get('ram_total_gb', 0):.1f}GB ({load.get('ram_pct', 0):.0f}%)",
                f"    GPU: {load.get('gpu_mem_gb', 0):.1f}GB",
                f"    Active tasks: {load.get('active_tasks', 0)}",
            ])
        
        if "task_stats" in health:
            ts = health["task_stats"]
            lines.extend([
                f"",
                f"  Tasks:",
                f"    Submitted: {ts.get('submitted', 0)}",
                f"    Completed: {ts.get('completed', 0)}",
                f"    Failed: {ts.get('failed', 0)}",
                f"    Timed out: {ts.get('timed_out', 0)}",
                f"    Queue size: {ts.get('queue_size', 0)}",
            ])
        
        if "trading" in health:
            tr = health["trading"]
            lines.extend([
                f"",
                f"  Trading:",
                f"    Running: {'✅' if tr.get('running') else '❌'}",
                f"    MT5: {'✅' if tr.get('mt5_connected') else '❌'}",
                f"    Positions: {tr.get('active_positions', 0)}",
            ])
            if tr.get("last_balance"):
                lines.append(f"    Balance: ${tr['last_balance']:,.2f}")
            if tr.get("last_equity"):
                lines.append(f"    Equity: ${tr['last_equity']:,.2f}")
        
        lines.append(f"{'=' * 50}")
        return "\n".join(lines)


# Глобальный монитор
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor(**kwargs) -> HealthMonitor:
    """Получает глобальный HealthMonitor."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor(**kwargs)
    return _health_monitor
