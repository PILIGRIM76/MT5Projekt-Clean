# src/gui/trading_system_adapter.py
"""
Адаптер между GUI и ядром TradingSystem.
Проксирует вызовы, подключает сигналы, обеспечивает безопасное обновление GUI.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5
from PySide6.QtCore import QObject, QThreadPool

from src.core.config_models import Settings
from src.core.event_bus import EventPriority, SystemEvent
from src.core.mt5_connection_manager import mt5_initialize
from src.core.thread_domains import ThreadDomain
from src.core.trading_system import TradingSystem
from src.gui.sound_manager import SoundManager
from src.gui.widgets.bridges import Bridge, GUIBridge
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
        self._event_bridge: Optional[GUIBridge] = None  # Будет установлен через set_event_bridge()

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

    def set_event_bridge(self, event_bridge: GUIBridge):
        """Установка ссылки на GUIEventBridge для публикации событий"""
        self._event_bridge = event_bridge
        logger.info("🔗 PySideTradingSystem connected to GUIEventBridge")

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

    async def start_all_threads(self, threadpool=None):
        """Запуск ядра. Полностью асинхронный, без блокировок."""
        logger.info("🔄 start_all_threads: делегирование в core_system.start()")
        try:
            if hasattr(self, "core_system") and self.core_system:
                await self.core_system.start()  # ← Ждём завершения инициализации
                logger.info("✅ core_system успешно запущен")

                # Запускаем фоновые сервисы (если они отдельные асинхронные задачи)
                if hasattr(self, "start_all_background_services"):
                    await self.start_all_background_services()

                logger.info("🟢 Все компоненты ядра активны и работают в фоне")
        except Exception as e:
            logger.error(f"❌ Failed to start core_system: {e}", exc_info=True)
            raise

    async def start_all_background_services(self, threadpool=None):
        """
        Запуск фоновых сервисов.
        """
        logger.info("start_all_background_services called - services auto-start via EventBus")
        # Компоненты уже запущены через start(), фоновые сервисы работают автоматически

    async def initialize_heavy_components(self):
        """
        Инициализация тяжёлых компонентов.
        """
        logger.info("initialize_heavy_components called - components initialized via core_system.start()")
        # В новой архитектуре это делается при старте компонентов

    async def emergency_close_position(self, ticket: int):
        """Экстренное закрытие одной позиции через EventBus."""
        logger.warning(f"🚨 Emergency close position: {ticket}")
        try:
            from src.core.event_bus import EventPriority, SystemEvent
            from src.core.thread_domains import ThreadDomain

            await self._event_bridge.publish_from_gui(
                "emergency_close_position", {"ticket": ticket}, priority=EventPriority.CRITICAL
            )
            logger.info("✅ Emergency close position request published to EventBus")
        except Exception as e:
            logger.error(f"❌ Failed to publish emergency close: {e}", exc_info=True)

    async def emergency_close_all_positions(self):
        """Экстренное закрытие всех позиций через EventBus."""
        logger.warning("🚨 Emergency close ALL positions")
        try:
            from src.core.event_bus import EventPriority, SystemEvent

            await self._event_bridge.publish_from_gui("emergency_close_all_positions", {}, priority=EventPriority.CRITICAL)
            logger.info("✅ Emergency close all positions request published to EventBus")
        except Exception as e:
            logger.error(f"❌ Failed to publish emergency close all: {e}", exc_info=True)

    async def set_observer_mode(self, enabled: bool):
        """Переключение режима наблюдателя через EventBus."""
        logger.info(f"👁️ Observer mode: {enabled}")
        try:
            await self._event_bridge.publish_from_gui(
                "set_observer_mode",
                {"enabled": enabled},
            )
            logger.info("✅ Observer mode request published")
        except Exception as e:
            logger.error(f"❌ Failed to set observer mode: {e}", exc_info=True)

    async def update_configuration(self, new_config: Settings):
        """Обновление конфигурации через EventBus."""
        logger.info("⚙️ Configuration updated")
        self.config = new_config
        try:
            await self._event_bridge.publish_from_gui(
                "config_updated",
                {"config": new_config.dict() if hasattr(new_config, "dict") else new_config},
            )
            logger.info("✅ Config update published")
        except Exception as e:
            logger.error(f"❌ Failed to publish config update: {e}", exc_info=True)

    async def force_training_cycle(self):
        """Принудительное обучение через EventBus."""
        logger.info("🧠 Force training cycle requested")
        try:
            from src.core.event_bus import EventPriority

            await self._event_bridge.publish_from_gui("force_training", {}, priority=EventPriority.HIGH)
            logger.info("✅ Training request published")
        except Exception as e:
            logger.error(f"❌ Failed to publish training request: {e}", exc_info=True)

    async def force_rd_cycle(self):
        """Принудительный R&D цикл через EventBus."""
        logger.info("🔬 Force R&D cycle requested")
        try:
            await self._event_bridge.publish_from_gui(
                "force_rd_cycle",
                {},
            )
            logger.info("✅ R&D cycle request published")
        except Exception as e:
            logger.error(f"❌ Failed to publish R&D request: {e}", exc_info=True)

    async def add_directive(self, directive_type: str, reason: str, duration_hours: int, value: Any) -> None:
        """Добавление директивы через EventBus."""
        logger.info(f"📝 Add directive: {directive_type}")
        try:
            await self._event_bridge.publish_from_gui(
                "add_directive",
                {
                    "type": directive_type,
                    "reason": reason,
                    "duration_hours": duration_hours,
                    "value": value,
                },
            )
            logger.info("✅ Directive published")
        except Exception as e:
            logger.error(f"❌ Failed to publish directive: {e}", exc_info=True)

    def stop(self):
        """Остановка системы."""
        logger.info("🛑 Stopping trading system")
        try:
            import asyncio

            if hasattr(self, "core_system") and self.core_system:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.core_system.stop())
                loop.close()
                logger.info("✅ Trading system stopped")
        except Exception as e:
            logger.error(f"❌ Failed to stop system: {e}", exc_info=True)

    async def _on_system_restart(self, event: SystemEvent):
        """Обработчик запроса на перезапуск системы"""
        logger.info("🔄 Получен запрос на перезапуск системы")

        try:
            # 1. Полная остановка всех компонентов
            logger.info("🛑 Остановка компонентов...")
            if hasattr(self, "core_system") and self.core_system:
                await self.core_system.stop()  # ← ПРЯМОЙ await, не через self.stop()
                logger.info("✅ Trading system stopped")

            # Пауза для очистки ресурсов
            await asyncio.sleep(1.0)

            # 3. Повторный запуск
            logger.info("🚀 Повторный запуск компонентов...")
            await self.start_all_threads()

            # 4. Уведомление GUI об успехе через EventBus
            event_bus = self._event_bridge.event_bus
            if event_bus:
                await event_bus.publish(
                    SystemEvent(
                        type="system_restart_completed",
                        payload={"success": True, "timestamp": time.time()},
                        priority=EventPriority.HIGH,
                    )
                )
            logger.info("✅ Система успешно перезапущена")

        except Exception as e:
            logger.error(f"❌ Ошибка перезапуска: {e}", exc_info=True)
            # Уведомление об ошибке через EventBus
            event_bus = self._event_bridge.event_bus
            if event_bus:
                await event_bus.publish(
                    SystemEvent(
                        type="system_restart_completed",
                        payload={"success": False, "error": str(e)},
                        priority=EventPriority.CRITICAL,
                    )
                )

    async def set_trading_mode(self, mode_id: str, settings: Optional[Dict[str, Any]] = None):
        """Установка режима торговли через EventBus."""
        logger.info(f"🎯 Set trading mode: {mode_id}")
        try:
            await self._event_bridge.publish_from_gui(
                "set_trading_mode",
                {"mode_id": mode_id, "settings": settings or {}},
            )
            logger.info("✅ Trading mode request published")
        except Exception as e:
            logger.error(f"❌ Failed to publish trading mode: {e}", exc_info=True)

    async def get_trading_mode(self) -> str:
        """Получение текущего режима торговли."""
        # TODO: запрос через EventBus
        return "live"  # Заглушка до реализации запроса статуса

    async def set_paper_trading_mode(self, enabled: bool):
        """Установка режима Paper Trading через EventBus."""
        logger.info(f"📄 Paper trading mode: {enabled}")
        try:
            await self._event_bridge.publish_from_gui(
                "set_paper_trading_mode",
                {"enabled": enabled},
            )
            logger.info("✅ Paper trading mode request published")
        except Exception as e:
            logger.error(f"❌ Failed to publish paper trading mode: {e}", exc_info=True)

    async def get_all_models(self) -> List[Dict]:
        """Получение списка моделей из БД через EventBus."""
        # TODO: запрос через EventBus
        return []  # Заглушка до реализации запроса

    async def get_vector_db_stats(self) -> Dict[str, Any]:
        """Статистика VectorDB через EventBus."""
        # TODO: запрос через EventBus
        return {}  # Заглушка до реализации запроса

    def search_vector_db(self, query_text: str):
        """Поиск в VectorDB через EventBus."""
        logger.info(f"🔍 VectorDB search request: '{query_text}'")
        try:
            import asyncio

            asyncio.create_task(self._event_bridge.publish_from_gui("vector_db_search", {"query": query_text}))
            logger.info("✅ VectorDB search request published")
        except Exception as e:
            logger.error(f"❌ Failed to publish search request: {e}", exc_info=True)

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
