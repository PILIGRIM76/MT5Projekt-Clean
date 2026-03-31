# src/core/services/execution_service.py
"""
Сервис исполнения ордеров для Genesis Trading System.

Объединяет:
- TradeExecutor (исполнение ордеров)
- RiskEngine (проверка рисков)
- PortfolioService (управление портфелем)

Жизненный цикл:
- start(): Проверка подключения к MT5
- stop(): Закрытие всех позиций (опционально)
- health_check(): Проверка доступности MT5 и баланса
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5

from src.core.config_models import Settings
from src.core.services.base_service import BaseService
from src.core.services.trade_executor import TradeExecutor
from src.data_models import SignalType, TradeSignal
from src.db.database_manager import DatabaseManager
from src.risk.risk_engine import RiskEngine

logger = logging.getLogger(__name__)


class ExecutionService(BaseService):
    """
    Сервис исполнения торговых операций.

    Атрибуты:
        trade_executor: Исполнитель ордеров
        risk_engine: Риск-движок
        portfolio_service: Управление портфелем
    """

    def __init__(
        self,
        config: Settings,
        db_manager: DatabaseManager,
        mt5_lock: threading.Lock,
    ):
        """
        Инициализация сервиса исполнения.

        Args:
            config: Конфигурация системы
            db_manager: Менеджер базы данных
            mt5_lock: Блокировка для доступа к MT5
        """
        super().__init__(config, name="ExecutionService")

        self.db_manager = db_manager
        self.mt5_lock = mt5_lock

        # Инициализация RiskEngine
        self.risk_engine = RiskEngine(
            config=config,
            trading_system_ref=None,  # Будет установлено позже
        )

        # Инициализация PortfolioService (требуется rl_manager, data_provider)
        # Пока используем упрощённую инициализацию
        self.portfolio_service = None  # Временно None

        # Инициализация TradeExecutor (требуется risk_engine и portfolio_service)
        self.trade_executor = TradeExecutor(
            config=config,
            risk_engine=self.risk_engine,
            portfolio_service=self.portfolio_service,
            mt5_lock=mt5_lock,
        )

        # Статистика
        self._orders_executed = 0
        self._orders_rejected = 0
        self._positions_open = 0
        self._last_balance = 0.0

        self._healthy = True

    def set_trading_system_ref(self, trading_system_ref) -> None:
        """Установка ссылки на торговую систему (для RiskEngine)."""
        self.risk_engine.trading_system = trading_system_ref
        logger.debug(f"{self.name}: Ссылка на TradingSystem установлена")

    async def start(self) -> None:
        """
        Запуск сервиса исполнения.

        Проверяет подключение к MT5 и баланс счёта.
        """
        logger.info(f"{self.name}: Запуск сервиса исполнения...")

        try:
            # Проверка подключения к MT5
            await self._safe_execute(self._check_mt5_connection(), "Проверка подключения к MT5")

            # Получение баланса
            self._last_balance = await self._safe_execute(self._get_balance(), "Получение баланса")

            # Подсчёт открытых позиций
            self._positions_open = await self._safe_execute(self._count_positions(), "Подсчёт позиций")

            self._running = True
            self._healthy = True

            logger.info(f"{self.name}: Сервис запущен успешно. Баланс: ${self._last_balance:.2f}")

        except Exception as e:
            logger.error(f"{self.name}: Ошибка при запуске: {e}", exc_info=True)
            self._healthy = False
            raise

    async def stop(self) -> None:
        """
        Остановка сервиса исполнения.

        Закрывает MT5 соединение.
        """
        logger.info(f"{self.name}: Остановка сервиса исполнения...")

        try:
            # Закрытие MT5
            await self._safe_execute(self._shutdown_mt5(), "Закрытие MT5")

            self._running = False
            self._healthy = False

            logger.info(f"{self.name}: Сервис остановлен")

        except Exception as e:
            logger.error(f"{self.name}: Ошибка при остановке: {e}", exc_info=True)

    def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья сервиса.

        Returns:
            Словарь с информацией о состоянии:
            - status: "healthy" | "unhealthy"
            - mt5_connected: bool
            - balance: float
            - positions_open: int
            - orders_executed: int
            - orders_rejected: int
        """
        # Проверка подключения к MT5
        mt5_connected = False
        try:
            mt5_connected = mt5.terminal_info() is not None
        except Exception:
            pass

        status = "healthy" if self._healthy and mt5_connected else "unhealthy"

        return {
            "status": status,
            "mt5_connected": mt5_connected,
            "balance": self._last_balance,
            "positions_open": self._positions_open,
            "orders_executed": self._orders_executed,
            "orders_rejected": self._orders_rejected,
        }

    async def _check_mt5_connection(self) -> bool:
        """Проверка подключения к MT5."""
        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH, timeout=5000):
                raise ConnectionError(f"Не удалось подключиться к MT5: {mt5.last_error()}")
            mt5.shutdown()
        return True

    async def _shutdown_mt5(self) -> None:
        """Закрытие соединения с MT5."""
        with self.mt5_lock:
            mt5.shutdown()

    async def _get_balance(self) -> float:
        """Получение баланса счёта."""
        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                return 0.0
            try:
                account_info = mt5.account_info()
                if account_info:
                    return account_info.balance
            finally:
                mt5.shutdown()
        return 0.0

    async def _count_positions(self) -> int:
        """Подсчёт открытых позиций."""
        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                return 0
            try:
                positions = mt5.positions_get()
                return len(positions) if positions else 0
            finally:
                mt5.shutdown()

    # ===========================================
    # Публичные методы для торговых операций
    # ===========================================

    async def execute_signal(
        self,
        signal: TradeSignal,
        symbol: str,
        lot: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Исполнение торгового сигнала.

        Args:
            signal: Торговый сигнал
            symbol: Символ
            lot: Объем лота (None = авто-расчёт)

        Returns:
            Результат исполнения:
            - success: bool
            - order_id: int (если успешно)
            - error: str (если ошибка)
        """
        # Проверка риска
        risk_check = await self._safe_execute(
            self._check_risk(signal, symbol),
            "Проверка риска",
        )

        if not risk_check:
            self._orders_rejected += 1
            return {"success": False, "error": "Risk check failed"}

        # Расчёт лота
        if lot is None:
            lot = await self._safe_execute(
                lambda: self.risk_engine.calculate_position_size(symbol, signal.type),
                "Расчёт лота",
            )

        if lot <= 0:
            self._orders_rejected += 1
            return {"success": False, "error": "Invalid lot size"}

        # Исполнение ордера
        if signal.type == SignalType.BUY:
            result = await self._safe_execute(
                lambda: self.trade_executor.open_buy(symbol, lot),
                "Открытие BUY",
            )
        else:
            result = await self._safe_execute(
                lambda: self.trade_executor.open_sell(symbol, lot),
                "Открытие SELL",
            )

        if result and result.get("success"):
            self._orders_executed += 1
            self._positions_open += 1
            logger.info(f"{self.name}: Ордер исполнен: {signal.type} {symbol} {lot} лот")
        else:
            self._orders_rejected += 1
            logger.warning(f"{self.name}: Ордер отклонён: {signal.type} {symbol}")

        return result

    async def close_position(
        self,
        ticket: int,
        reason: str = "manual",
    ) -> Dict[str, Any]:
        """
        Закрытие позиции.

        Args:
            ticket: Тикет позиции
            reason: Причина закрытия

        Returns:
            Результат закрытия
        """
        result = await self._safe_execute(
            lambda: self.trade_executor.close_position(ticket, reason=reason),
            f"Закрытие позиции #{ticket}",
        )

        if result and result.get("success"):
            self._positions_open = max(0, self._positions_open - 1)
            logger.info(f"{self.name}: Позиция #{ticket} закрыта: {reason}")

        return result

    async def close_all_positions(
        self,
        reason: str = "emergency",
    ) -> List[Dict[str, Any]]:
        """
        Закрытие всех позиций.

        Args:
            reason: Причина закрытия

        Returns:
            Список результатов закрытия
        """
        logger.critical(f"{self.name}: Аварийное закрытие всех позиций: {reason}")

        results = []

        # Получение всех позиций
        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH):
                return [{"success": False, "error": "MT5 connection failed"}]

            try:
                positions = mt5.positions_get()
                if not positions:
                    logger.info(f"{self.name}: Нет открытых позиций")
                    return []

                # Закрытие каждой позиции
                for pos in positions:
                    result = await self.close_position(pos.ticket, reason)
                    results.append(result)

            finally:
                mt5.shutdown()

        self._positions_open = 0
        logger.info(f"{self.name}: Все позиции закрыты. Всего: {len(results)}")

        return results

    async def _check_risk(self, signal: TradeSignal, symbol: str) -> bool:
        """
        Проверка рисков перед исполнением.

        Args:
            signal: Торговый сигнал
            symbol: Символ

        Returns:
            True если риски в норме
        """
        # Проверка дневного drawdown
        daily_dd = await self._safe_execute(
            self.risk_engine.check_daily_drawdown,
            "Проверка дневного DD",
        )

        if not daily_dd:
            logger.warning(f"{self.name}: Превышен дневной drawdown")
            return False

        # Проверка максимального количества позиций
        if self._positions_open >= self.config.MAX_OPEN_POSITIONS:
            logger.warning(f"{self.name}: Достигнут лимит позиций: {self._positions_open}")
            return False

        # Проверка волатильности
        vol_check = await self._safe_execute(
            lambda: self.risk_engine.check_volatility(symbol),
            "Проверка волатильности",
        )

        if not vol_check:
            logger.warning(f"{self.name}: Высокая волатильность для {symbol}")
            return False

        return True

    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Получение списка открытых позиций.

        Returns:
            Список позиций
        """

        def _get_positions():
            with self.mt5_lock:
                if not mt5.initialize(path=self.config.MT5_PATH):
                    return []
                try:
                    positions = mt5.positions_get()
                    if not positions:
                        return []

                    return [
                        {
                            "ticket": pos.ticket,
                            "symbol": pos.symbol,
                            "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                            "volume": pos.volume,
                            "price_open": pos.price_open,
                            "price_current": pos.price_current,
                            "sl": pos.sl,
                            "tp": pos.tp,
                            "profit": pos.profit,
                            "time": datetime.fromtimestamp(pos.time),
                        }
                        for pos in positions
                    ]
                finally:
                    mt5.shutdown()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_positions)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"running={self._running}, "
            f"healthy={self._healthy}, "
            f"positions={self._positions_open})"
        )
