# src/core/trading/health_check.py
"""
Health Check Endpoint — мониторинг состояния системы через API.

Предоставляет endpoint /health для проверки:
- Статуса всех компонентов
- Здоровья ML моделей
- Статуса подключения к MT5
- Статуса баз данных
- Uptime и использования памяти

Используется для:
- Мониторинга (Grafana, Prometheus)
- Автоматических перезапусков (systemd, Docker)
- Оповещений (Telegram, email)
"""

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class HealthCheckEndpoint:
    """
    Endpoint проверки здоровья системы.

    Атрибуты:
        trading_system: Ссылка на TradingSystem
        start_time: Время запуска системы
    """

    def __init__(self, trading_system):
        self.trading_system = trading_system
        self.start_time = time.time()
        self._last_check_time = 0
        self._last_health_report: Dict[str, Any] = {}
        self._check_interval = 5.0  # Мин. 5 сек между проверками

    def get_health_status(self, force: bool = False) -> Dict[str, Any]:
        """
        Получить полный статус здоровья системы.

        Args:
            force: Принудительная проверка (игнорировать кэш)

        Returns:
            Словарь с полным отчётом о здоровье
        """
        now = time.time()

        # Используем кэш если прошло мало времени
        if not force and (now - self._last_check_time) < self._check_interval:
            return self._last_health_report

        report = {
            "status": self._calculate_overall_status(),
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": now - self.start_time,
            "uptime_human": self._format_uptime(now - self.start_time),
            "components": self._check_components(),
            "ml_models": self._check_ml_models(),
            "database": self._check_database(),
            "mt5": self._check_mt5(),
            "memory": self._check_memory(),
            "degradation": self._check_degradation(),
        }

        self._last_check_time = now
        self._last_health_report = report
        return report

    def get_health_summary(self) -> Dict[str, str]:
        """
        Получить краткий статус здоровья (для мониторинга).

        Returns:
            Словарь {status: "healthy/degraded/unhealthy"}
        """
        full_report = self.get_health_status()
        return {
            "status": full_report["status"],
            "uptime": full_report["uptime_human"],
            "components_healthy": str(full_report["components"]["healthy"]),
            "ml_models_healthy": str(full_report["ml_models"]["healthy"]),
            "database_connected": str(full_report["database"]["connected"]),
            "mt5_connected": str(full_report["mt5"]["connected"]),
        }

    def _calculate_overall_status(self) -> str:
        """
        Рассчитать общий статус системы.

        Returns:
            "healthy", "degraded", или "unhealthy"
        """
        ts = self.trading_system

        # Проверяем критичные компоненты
        if not ts.is_heavy_init_complete:
            return "starting"

        if ts.update_pending:
            return "updating"

        # Проверяем Graceful Degradation фазу
        if hasattr(ts, "_ml_coordinator"):
            # Если фаза degradации — observer mode или emergency stop
            pass  # Проверяется в _check_degradation

        # Проверяем MT5
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(path=ts.config.MT5_PATH):
                return "unhealthy"
        except Exception:
            return "unhealthy"

        # Проверяем БД
        if not ts.db_manager:
            return "degraded"

        return "healthy"

    def _check_components(self) -> Dict[str, Any]:
        """Проверить статус компонентов."""
        ts = self.trading_system
        components = {
            "trading_system": ts.is_heavy_init_complete,
            "mt5": False,
            "database": ts.db_manager is not None,
            "data_provider": ts.data_provider is not None,
            "risk_engine": ts.risk_engine is not None,
            "trading_engine": hasattr(ts, "_trading_engine"),
            "ml_coordinator": hasattr(ts, "_ml_coordinator"),
            "gui_coordinator": hasattr(ts, "_gui_coordinator"),
        }

        # Проверяем MT5
        try:
            import MetaTrader5 as mt5
            if mt5.initialize(path=ts.config.MT5_PATH):
                acc_info = mt5.account_info()
                components["mt5"] = acc_info is not None
                mt5.shutdown()
        except Exception:
            components["mt5"] = False

        healthy_count = sum(1 for v in components.values() if v)
        total_count = len(components)

        return {
            "details": components,
            "healthy": healthy_count,
            "total": total_count,
            "percentage": (healthy_count / max(total_count, 1)) * 100,
        }

    def _check_ml_models(self) -> Dict[str, Any]:
        """Проверить статус ML моделей."""
        ts = self.trading_system
        models_status = {}

        if hasattr(ts, "_ml_coordinator"):
            models_status = ts._ml_coordinator.get_all_model_accuracy()

        total = len(models_status)
        healthy = sum(1 for acc in models_status.values() if acc and acc > 0.5)

        return {
            "models": models_status,
            "healthy": healthy,
            "total": total,
            "percentage": (healthy / max(total, 1)) * 100,
        }

    def _check_database(self) -> Dict[str, Any]:
        """Проверить статус базы данных."""
        ts = self.trading_system
        db_status = {
            "connected": False,
            "type": "sqlite",
            "path": "",
            "error": "",
        }

        try:
            if ts.db_manager and ts.db_manager.engine:
                # Пробуем простой запрос
                ts.db_manager.engine.execute("SELECT 1")
                db_status["connected"] = True
                db_status["path"] = str(ts.config.DATABASE_FOLDER)
        except Exception as e:
            db_status["error"] = str(e)

        return db_status

    def _check_mt5(self) -> Dict[str, Any]:
        """Проверить статус подключения к MT5."""
        ts = self.trading_system
        mt5_status = {
            "connected": False,
            "balance": 0.0,
            "equity": 0.0,
            "server": ts.config.MT5_SERVER,
            "error": "",
        }

        try:
            import MetaTrader5 as mt5
            if mt5.initialize(path=ts.config.MT5_PATH):
                acc_info = mt5.account_info()
                if acc_info:
                    mt5_status["connected"] = True
                    mt5_status["balance"] = acc_info.balance
                    mt5_status["equity"] = acc_info.equity
                mt5.shutdown()
        except Exception as e:
            mt5_status["error"] = str(e)

        return mt5_status

    def _check_memory(self) -> Dict[str, Any]:
        """Проверить использование памяти."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()

            return {
                "rss_mb": memory_info.rss / (1024 * 1024),
                "vms_mb": memory_info.vms / (1024 * 1024),
                "percent": process.memory_percent(),
            }
        except ImportError:
            return {"error": "psutil not installed"}
        except Exception as e:
            return {"error": str(e)}

    def _check_degradation(self) -> Dict[str, Any]:
        """Проверить статус Graceful Degradation."""
        ts = self.trading_system

        if hasattr(ts, "_ml_coordinator") and hasattr(ts._ml_coordinator, "degradation_manager"):
            return ts._ml_coordinator.degradation_manager.get_health_report()

        return {"status": "not_configured"}

    def _format_uptime(self, seconds: float) -> str:
        """Форматировать uptime в читаемый вид."""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def to_prometheus_format(self) -> str:
        """
        Экспорт метрик в формате Prometheus.

        Returns:
            Строка метрик в формате Prometheus
        """
        report = self.get_health_status()

        metrics = []
        metrics.append(f'# HELP genesis_system_status Health status (1=healthy, 0=unhealthy)')
        metrics.append(f'# TYPE genesis_system_status gauge')
        metrics.append(f'genesis_system_status{{status="{report["status"]}"}} 1')

        metrics.append(f'# HELP genesis_system_uptime_seconds System uptime in seconds')
        metrics.append(f'# TYPE genesis_system_uptime_seconds counter')
        metrics.append(f'genesis_system_uptime_seconds {report["uptime_seconds"]:.2f}')

        components = report["components"]
        metrics.append(f'# HELP genesis_components_healthy Number of healthy components')
        metrics.append(f'# TYPE genesis_components_healthy gauge')
        metrics.append(f'genesis_components_healthy {components["healthy"]}')

        ml = report["ml_models"]
        metrics.append(f'# HELP genesis_ml_models_healthy Number of healthy ML models')
        metrics.append(f'# TYPE genesis_ml_models_healthy gauge')
        metrics.append(f'genesis_ml_models_healthy {ml["healthy"]}')

        db = report["database"]
        metrics.append(f'# HELP genesis_database_connected Database connection status')
        metrics.append(f'# TYPE genesis_database_connected gauge')
        metrics.append(f'genesis_database_connected {1 if db["connected"] else 0}')

        mt5 = report["mt5"]
        metrics.append(f'# HELP genesis_mt5_connected MT5 connection status')
        metrics.append(f'# TYPE genesis_mt5_connected gauge')
        metrics.append(f'genesis_mt5_connected {1 if mt5["connected"] else 0}')

        mem = report["memory"]
        if "rss_mb" in mem:
            metrics.append(f'# HELP genesis_memory_usage_mb Memory usage in MB')
            metrics.append(f'# TYPE genesis_memory_usage_mb gauge')
            metrics.append(f'genesis_memory_usage_mb {mem["rss_mb"]:.2f}')

        return "\n".join(metrics)
