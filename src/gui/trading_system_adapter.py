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
        self.sound_manager = sound_manager

        # Новая архитектура: TradingSystem принимает только core компоненты
        # mt5_api, db_manager, predictor инициализируются отдельно
        self.core_system: TradingSystem = TradingSystem(
            config=config.dict() if hasattr(config, "dict") else config,
            mt5_api=None,  # Будет установлен позже
            db_manager=None,  # Будет установлен позже
            predictor=None,  # Будет установлен позже
        )

        self._connect_core_signals()
        self._proxy_core_methods()

    def _connect_core_signals(self):
        """Подключает сигналы core_system -> bridge."""
        # В новой архитектуре сигналы идут через EventBus
        # Здесь оставляем placeholder для будущей интегра
        logger.debug("Core signals connected (via EventBus in new architecture)")

    def _proxy_core_methods(self):
        """Создаёт прокси-методы для вызова из MainWindow."""
        # Новая архитектура: методы вызываются через EventBus
        self.get_stats = self.core_system.get_stats
        self.start = self.core_system.start
        self.stop = self.core_system.stop

    def start_all_threads(self, threadpool=None):
        """
        Запуск всех потоков (совместимость со старым GUI).
        В новой архитектуре это делается через EventBus.
        """
        logger.info("start_all_threads called (compatibility mode)")
        # В новой архитектуре компоненты запускаются через start()
        # Этот метод оставлен для совместимости

    def start_all_background_services(self, threadpool=None):
        """
        Запуск фоновых сервисов (совместимость со старым GUI).
        """
        logger.info("start_all_background_services called (compatibility mode)")
        # Компоненты уже запущены через start()

    def initialize_heavy_components(self):
        """
        Инициализация тяжёлых компонентов (совместимость).
        """
        logger.info("initialize_heavy_components called (compatibility mode)")
        # В новой архитектуре это делается при старте компонентов

    def emergency_close_position(self, ticket: int):
        """Экстренное закрытие одной позиции."""
        # В новой архитектуре это делается через ExecutionEngine
        logger.warning(f"Emergency close position: {ticket}")
        # TODO: реализовать через EventBus

    def emergency_close_all_positions(self):
        """Экстренное закрытие всех позиций."""
        logger.warning("Emergency close all positions")
        # TODO: реализовать через EventBus

    def set_observer_mode(self, enabled: bool):
        """Переключение режима наблюдателя."""
        logger.info(f"Observer mode: {enabled}")
        # TODO: реализовать через EventBus

    def update_configuration(self, new_config: Settings):
        """Обновление конфигурации."""
        logger.info("Configuration updated")
        self.config = new_config
        # TODO: реализовать через EventBus

    def force_training_cycle(self):
        """Принудительное обучение."""
        logger.info("Force training cycle requested")
        # TODO: реализовать через EventBus

    def force_rd_cycle(self):
        """Принудительный R&D цикл."""
        logger.info("Force R&D cycle requested")
        # TODO: реализовать через EventBus

    def add_directive(self, directive_type: str, reason: str, duration_hours: int, value: Any) -> None:
        """Добавление директивы через прокси."""
        logger.info(f"Add directive: {directive_type}")
        # TODO: реализовать через EventBus

    def stop(self):
        """Остановка системы."""
        logger.info("Stopping trading system")
        # TODO: вызвать self.core_system.stop() через asyncio

    def set_trading_mode(self, mode_id: str, settings: Optional[Dict[str, Any]] = None):
        """Установка режима торговли."""
        logger.info(f"Set trading mode: {mode_id}")
        # TODO: реализовать через EventBus

    def get_trading_mode(self) -> str:
        """Получение текущего режима торговли."""
        return "live"  # TODO: реализовать через EventBus

    def set_paper_trading_mode(self, enabled: bool):
        """Установка режима Paper Trading."""
        logger.info(f"Paper trading mode: {enabled}")
        # TODO: реализовать через EventBus

    def get_all_models(self) -> List[Dict]:
        """Получение списка моделей из БД."""
        return []  # TODO: реализовать через EventBus

    def get_vector_db_stats(self) -> Dict[str, Any]:
        """Статистика VectorDB."""
        return {}  # TODO: реализовать через EventBus

    def search_vector_db(self, query_text: str):
        """Поиск в VectorDB через QThreadPool."""
        logger.info(f"[VectorDB-Proxy] Получен запрос на поиск: '{query_text}'")
        # TODO: реализовать через EventBus
        self.bridge.vector_db_search_results.emit([{"info": "VectorDB search pending EventBus integration"}])

    def connect_to_terminal_adapter(self) -> tuple[bool, str]:
        """Подключение к MetaTrader 5."""
        logger.info("Попытка подключения к MetaTrader 5 через адаптер...")
        try:
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
        except Exception as e:
            logger.error(f"MT5 connection error: {e}")
            return False, str(e)

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
