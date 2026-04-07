# src/gui/trading_system_adapter.py
"""
Адаптер между GUI и ядром TradingSystem.
Проксирует вызовы, подключает сигналы, обеспечивает безопасное обновление GUI.
"""

import logging
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5
from PySide6.QtCore import QObject, QThreadPool

from src.core.config_models import Settings
from src.core.mt5_connection_manager import mt5_initialize
from src.core.trading_system import TradingSystem
from src.gui.sound_manager import SoundManager
from src.gui.widgets.bridges import Bridge
from src.utils.worker import Worker

logger = logging.getLogger(__name__)


class PySideTradingSystem(QObject):
    """
    Адаптер-прослойка между MainWindow и TradingSystem.
    Проксирует вызовы к ядру и управляет сигналами.
    """

    def __init__(self, config: Settings, bridge: Bridge, sound_manager: SoundManager):
        super().__init__()
        self.config = config
        self.bridge = bridge
        self.core_system: TradingSystem = TradingSystem(config=config, gui=self, sound_manager=sound_manager, bridge=bridge)

        self._connect_core_signals()
        self._proxy_core_methods()

    def _connect_core_signals(self):
        """Подключает сигналы core_system -> bridge."""
        self.core_system.rd_progress_updated.connect(self.bridge.rd_progress_updated)
        self.core_system.market_scan_updated.connect(self.bridge.market_scan_updated)
        self.core_system.trading_signals_updated.connect(self.bridge.trading_signals_updated)
        self.core_system.uptime_updated.connect(self.bridge.uptime_updated)
        self.core_system.all_positions_closed.connect(self.bridge.all_positions_closed)
        self.core_system.directives_updated.connect(self.bridge.directives_updated)
        self.core_system.orchestrator_allocation_updated.connect(self.bridge.orchestrator_allocation_updated)
        self.core_system.knowledge_graph_updated.connect(self.bridge.knowledge_graph_updated)
        self.core_system.thread_status_updated.connect(self.bridge.thread_status_updated)
        self.core_system.long_task_status_updated.connect(self.bridge.long_task_status_updated)
        self.core_system.drift_data_updated.connect(self.bridge.drift_data_updated)

    def _proxy_core_methods(self):
        """Создаёт прокси-методы для вызова из MainWindow."""
        self.initialize_heavy_components = self.core_system.initialize_heavy_components
        self.start_all_background_services = self.core_system.start_all_background_services
        self.start_all_threads = self.core_system.start_all_threads

    def emergency_close_position(self, ticket: int):
        """Экстренное закрытие одной позиции."""
        self.core_system.execution_service.emergency_close_position(ticket)

    def emergency_close_all_positions(self):
        """Экстренное закрытие всех позиций."""
        self.core_system.execution_service.emergency_close_all_positions()

    def set_observer_mode(self, enabled: bool):
        """Переключение режима наблюдателя."""
        self.core_system.set_observer_mode(enabled)

    def update_configuration(self, new_config: Settings):
        """Обновление конфигурации."""
        self.core_system.update_configuration(new_config)

    def force_training_cycle(self):
        """Принудительное обучение."""
        self.core_system.force_training_cycle()

    def force_rd_cycle(self):
        """Принудительный R&D цикл."""
        self.core_system.force_rd_cycle()

    def add_directive(self, directive_type: str, reason: str, duration_hours: int, value: Any) -> None:
        """Добавление директивы через прокси."""
        self.core_system.add_directive(directive_type, reason, duration_hours, value)

    def stop(self):
        """Остановка системы."""
        self.core_system.initiate_graceful_shutdown()

    def set_trading_mode(self, mode_id: str, settings: Optional[Dict[str, Any]] = None):
        """Установка режима торговли."""
        self.core_system.set_trading_mode(mode_id, settings)

    def get_trading_mode(self) -> str:
        """Получение текущего режима торговли."""
        return self.core_system.get_trading_mode()

    def set_paper_trading_mode(self, enabled: bool):
        """Установка режима Paper Trading."""
        self.core_system.set_paper_trading_mode(enabled)

    def get_all_models(self) -> List[Dict]:
        """Получение списка моделей из БД."""
        return self.core_system.db_manager.get_all_models_for_gui()

    def get_vector_db_stats(self) -> Dict[str, Any]:
        """Статистика VectorDB."""
        return self.core_system.get_vector_db_stats()

    def search_vector_db(self, query_text: str):
        """Поиск в VectorDB через QThreadPool."""
        logger.info(f"[VectorDB-Proxy] Получен запрос на поиск: '{query_text}'")

        if not self.core_system:
            logger.error("[VectorDB-Proxy] core_system не инициализирован")
            self.bridge.vector_db_search_results.emit([{"error": "Торговая система не запущена"}])
            return

        if not hasattr(self.core_system, "search_vector_db"):
            logger.error("[VectorDB-Proxy] Метод search_vector_db не найден в core_system")
            self.bridge.vector_db_search_results.emit([{"error": "Метод поиска не найден"}])
            return

        logger.info(f"[VectorDB-Proxy] Запуск Worker для поиска")
        worker = Worker(self.core_system.search_vector_db, query_text)
        QThreadPool.globalInstance().start(worker)
        logger.info(f"[VectorDB-Proxy] Worker запущен")

    def connect_to_terminal_adapter(self) -> tuple[bool, str]:
        """Подключение к MetaTrader 5."""
        with self.core_system.mt5_lock:
            logger.info("Попытка подключения к MetaTrader 5 через адаптер...")
            if not mt5_initialize(
                path=self.config.MT5_PATH,
                login=int(self.config.MT5_LOGIN) if self.config.MT5_LOGIN else None,
                password=self.config.MT5_PASSWORD,
                server=self.config.MT5_SERVER,
                timeout=10000,
            ):
                error_message = f"initialize() failed, error code = {mt5.last_error()}"
                logger.error(f"Не удалось подключиться к MT5: {error_message}")
                return False, error_message

            account_info = mt5.account_info()
            if account_info is None:
                error_message = f"account_info() failed, error code = {mt5.last_error()}"
                logger.error(f"Не удалось получить информацию о счете: {error_message}")
                return False, error_message

            logger.info(f"Успешное подключение к счету #{account_info.login} на сервере {account_info.server}.")
            return True, "Success"

    def _safe_gui_update(self, method_name: str, *args, **kwargs):
        """Безопасная отправка сигналов GUI."""
        try:
            signal_map = {
                "update_status": (self.bridge.status_updated, (args[0], kwargs.get("is_error", False))),
                "update_balance": (self.bridge.balance_updated, args),
                "update_positions_view": (self.bridge.positions_updated, args),
                "update_history_view": (self.bridge.history_updated, args),
                "update_visualization": (self.bridge.training_history_updated, args),
                "update_candle_chart": (self.bridge.candle_chart_updated, args),
                "update_pnl_graph": (self.bridge.pnl_updated, args),
                "update_rd_log": (self.bridge.rd_progress_updated, args),
                "update_times": (self.bridge.times_updated, args),
            }
            if method_name in signal_map:
                signal, signal_args = signal_map[method_name]
                signal.emit(*signal_args)
        except Exception as e:
            logger.error(f"Ошибка при отправке сигнала GUI '{method_name}': {e}")
