# src/core/trading_system.py
"""
Ядро торговой системы: событийный пайплайн принятия решений.

Архитектура:
  [market_tick]
       ↓
  [MLPredictor] → model_prediction
       ↓
  [StrategyEngine] → trade_signal
       ↓
  [RiskEngine] → risk_approved | risk_rejected
       ↓
  [ExecutionEngine] → order_executed | order_failed
       ↓
  [EventBus] → GUI / DB / Analytics

Все этапы изолированы по ThreadDomain, защищены локами и CircuitBreaker.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from src.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from src.core.event_bus import EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager, requires_locks
from src.core.thread_domains import ThreadDomain, run_in_domain

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Типы торговых сигналов"""

    BUY = auto()
    SELL = auto()
    HOLD = auto()
    CLOSE = auto()


class RiskStatus(Enum):
    """Статусы риск-проверки"""

    APPROVED = "approved"
    REJECTED_LIMIT = "rejected:position_limit"
    REJECTED_DRAWDOWN = "rejected:drawdown"
    REJECTED_VOLATILITY = "rejected:volatility"
    REJECTED_CORRELATION = "rejected:correlation"


@dataclass
class TradeSignal:
    """Структура торгового сигнала"""

    symbol: str
    action: SignalType
    volume: float
    confidence: float
    model_version: int
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "action": self.action.name,
            "volume": self.volume,
            "confidence": self.confidence,
            "model_version": self.model_version,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionResult:
    """Результат исполнения ордера"""

    success: bool
    order_id: Optional[str] = None
    retcode: Optional[int] = None
    message: str = ""
    slippage: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "retcode": self.retcode,
            "message": self.message,
            "slippage": self.slippage,
        }


class StrategyEngine:
    """
    Генерация сигналов на основе предсказаний.
    Работает в ThreadDomain.STRATEGY_ENGINE.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.threshold_buy = config.get("threshold_buy", 0.65)
        self.threshold_sell = config.get("threshold_sell", 0.35)
        self.min_confidence = config.get("min_confidence", 0.5)
        self._signal_count = 0

    @run_in_domain(ThreadDomain.STRATEGY_ENGINE)
    async def on_prediction(self, event: SystemEvent) -> Optional[TradeSignal]:
        """Обработка предсказания → генерация сигнала"""
        payload = event.payload
        symbol = payload.get("symbol")
        prediction = payload.get("prediction")
        confidence = payload.get("confidence", 0.0)

        if prediction is None or confidence < self.min_confidence:
            return None

        # Логика генерации сигнала
        if prediction >= self.threshold_buy:
            action = SignalType.BUY
        elif prediction <= self.threshold_sell:
            action = SignalType.SELL
        else:
            return None

        volume = self._calculate_volume(symbol or "", confidence)

        signal = TradeSignal(
            symbol=symbol or "",
            action=action,
            volume=volume,
            confidence=confidence,
            model_version=payload.get("model_version", 0),
            correlation_id=event.correlation_id or "",
        )

        self._signal_count += 1
        logger.debug(f"Signal generated: {signal.action.name} {symbol} " f"(conf={confidence:.2f})")
        return signal

    def _calculate_volume(self, symbol: str, confidence: float) -> float:
        """Расчёт объёма на основе уверенности."""
        base_volume = self.config.get("base_volume", 0.1)
        multiplier = 0.5 + confidence
        return round(base_volume * multiplier, 2)


class RiskEngine:
    """
    Проверка сигналов на соответствие риск-параметрам.
    Работает в ThreadDomain.RISK_ENGINE.
    """

    def __init__(self, config: Dict, mt5_api, db_manager):
        self.config = config
        self.mt5 = mt5_api
        self.db = db_manager

        self.max_position_per_symbol = config.get("max_position_per_symbol", 1)
        self.max_total_exposure = config.get("max_total_exposure", 10.0)
        self.max_drawdown_percent = config.get("max_drawdown_percent", 5.0)
        self.min_volatility = config.get("min_volatility", 0.0001)

        self._positions_cache: Dict[str, Dict] = {}
        self._cache_timestamp: float = 0

    @run_in_domain(ThreadDomain.RISK_ENGINE)
    async def check(self, signal: TradeSignal) -> Tuple[RiskStatus, str]:
        """Комплексная риск-проверка сигнала."""
        symbol = signal.symbol

        # 1. Лимит позиций на символ
        current_positions = await self._get_symbol_positions(symbol)
        if len(current_positions) >= self.max_position_per_symbol:
            return RiskStatus.REJECTED_LIMIT, f"Max positions for {symbol}"

        # 2. Общая экспозиция
        total_exposure = await self._calculate_total_exposure()
        if total_exposure + signal.volume > self.max_total_exposure:
            return (
                RiskStatus.REJECTED_LIMIT,
                f"Total exposure limit: {total_exposure:.2f}/{self.max_total_exposure}",
            )

        # 3. Просадка
        drawdown = await self._calculate_current_drawdown()
        if drawdown > self.max_drawdown_percent:
            return (
                RiskStatus.REJECTED_DRAWDOWN,
                f"Drawdown {drawdown:.2f}% > {self.max_drawdown_percent}%",
            )

        # 4. Волатильность
        volatility = await self._get_volatility(symbol)
        if volatility < self.min_volatility:
            return (
                RiskStatus.REJECTED_VOLATILITY,
                f"Low volatility: {volatility:.6f}",
            )

        return RiskStatus.APPROVED, "Risk check passed"

    async def _get_symbol_positions(self, symbol: str) -> List[Dict]:
        """Получение открытых позиций по символу (с кэшированием)."""
        if time.time() - self._cache_timestamp < 5:
            return self._positions_cache.get(symbol, [])  # type: ignore

        # Запрос к MT5 (в реальном коде)
        positions: List[Dict] = []
        self._positions_cache[symbol] = positions
        self._cache_timestamp = time.time()
        return positions

    async def _calculate_total_exposure(self) -> float:
        """Расчёт общей экспозиции."""
        return 2.5

    async def _calculate_current_drawdown(self) -> float:
        """Расчёт текущей просадки в %."""
        return 1.2

    async def _get_volatility(self, symbol: str) -> float:
        """Расчёт волатильности."""
        return 0.0025


class ExecutionEngine:
    """
    Исполнение ордеров через MT5 с защитой от сбоев.
    Работает в ThreadDomain.MT5_IO.
    """

    def __init__(self, mt5_api, config: Dict):
        self.mt5 = mt5_api
        self.config = config
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=120.0,
        )
        self._execution_count = 0

    @run_in_domain(ThreadDomain.MT5_IO)
    @requires_locks(LockLevel.MT5_ACCESS, LockLevel.TRADE_EXECUTION)
    async def execute(self, signal: TradeSignal, price: Optional[float] = None) -> ExecutionResult:
        """Исполнение ордера с Circuit Breaker."""
        try:
            if not self.circuit_breaker.can_execute():
                logger.critical(f"Circuit OPEN for {signal.symbol} — execution blocked")
                return ExecutionResult(
                    success=False,
                    message="Circuit breaker: too many failures",
                )

            result = await asyncio.to_thread(self._send_order_sync, signal, price)

            if result.success:
                self.circuit_breaker.record_success()
            else:
                self.circuit_breaker.record_failure()

            self._execution_count += 1
            logger.info(f"Order executed: {signal.action.name} {signal.symbol} " f"(id={result.order_id})")
            return result

        except Exception as e:
            self.circuit_breaker.record_failure()
            logger.error(f"Execution failed for {signal.symbol}: {e}", exc_info=True)
            return ExecutionResult(success=False, message=str(e))

    def _send_order_sync(self, signal: TradeSignal, price: Optional[float]) -> ExecutionResult:
        """Синхронная отправка ордера."""
        import random

        success = random.random() > 0.05
        return ExecutionResult(
            success=success,
            order_id=f"ORD_{int(time.time())}" if success else None,
            retcode=10009 if success else 4000,
            message="Done" if success else "Requote",
            slippage=random.uniform(0, 0.0002) if success else 0,
        )

    def get_stats(self) -> Dict[str, Any]:
        return {
            "execution_count": self._execution_count,
            "circuit_state": self.circuit_breaker.state.name,
        }


class TradingSystem:
    """
    Координатор всего пайплайна: от тика до исполнения.

    Поток данных:
    1. market_tick → 2. predict → 3. generate_signal →
    4. check_risk → 5. execute → 6. log_result
    """

    def __init__(self, config: Dict, mt5_api, db_manager, predictor):
        self.config = config
        self.mt5 = mt5_api
        self.db = db_manager
        self.db_manager = db_manager  # alias для совместимости с GUI/adapter
        self.predictor = predictor

        self.event_bus = get_event_bus()

        self.strategy = StrategyEngine(config.get("strategy", {}))
        self.risk = RiskEngine(config.get("risk", {}), mt5_api, db_manager)
        self.execution = ExecutionEngine(mt5_api, config.get("execution", {}))

        self._stats = {
            "ticks_received": 0,
            "predictions_made": 0,
            "signals_generated": 0,
            "risks_approved": 0,
            "orders_executed": 0,
            "orders_failed": 0,
        }

        self._running = False

    async def start(self):
        """Запуск системы: подписка на события"""
        self._running = True

        await self.event_bus.subscribe(
            "market_tick",
            self._on_market_tick,
            domain=ThreadDomain.STRATEGY_ENGINE,
            priority=EventPriority.HIGH,
        )
        await self.event_bus.subscribe(
            "model_prediction",
            self._on_prediction,
            domain=ThreadDomain.STRATEGY_ENGINE,
            priority=EventPriority.HIGH,
        )
        await self.event_bus.subscribe(
            "order_executed",
            self._on_order_result,
            domain=ThreadDomain.PERSISTENCE,
            priority=EventPriority.MEDIUM,
        )
        await self.event_bus.subscribe(
            "news_batch_processed",
            self._on_news_batch,
            domain=ThreadDomain.STRATEGY_ENGINE,
            priority=EventPriority.LOW,
        )

        logger.info("TradingSystem started — pipeline active")

        # === ОТПРАВКА ПОДТВЕРЖДЕНИЯ В GUI ===
        await self.event_bus.publish(
            SystemEvent(
                type="trading_started",
                payload={
                    "status": True,
                    "timestamp": datetime.now().isoformat(),
                    "components": ["DataSync", "MLPredictor", "RiskManager", "Executor"],
                },
                priority=EventPriority.HIGH,
            )
        )
        logger.info("📡 GUI notified: trading_started event published")
        # =======================================

        # 🔧 HEARTBEAT: Каждые 30 секунд логируем статус системы
        asyncio.create_task(self._system_heartbeat())
        logger.info("💓 System heartbeat started")

    async def _system_heartbeat(self):
        """Heartbeat для мониторинга жизненного цикла системы."""
        import asyncio as aio

        while getattr(self, "_running", True):
            try:
                task_count = len(aio.all_tasks()) if hasattr(aio, "all_tasks") else 0
                logger.info(f"💓 System Heartbeat: OK | Tasks: {task_count} | Running: {self._running}")
                await aio.sleep(30)
            except Exception as e:
                logger.error(f"💓 Heartbeat error: {e}")
                break

    async def stop(self):
        """Корректная остановка"""
        self._running = False
        logger.info(f"TradingSystem stopped — stats: {self._stats}")

    @run_in_domain(ThreadDomain.STRATEGY_ENGINE)
    async def _on_market_tick(self, event: SystemEvent):
        """Обработчик тика: запуск пайплайна"""
        self._stats["ticks_received"] += 1
        symbol = event.payload.get("symbol")

        if event.type == "market_tick":
            await self.event_bus.publish(
                SystemEvent(
                    type="ml_input",
                    payload={"symbol": symbol, "tick": event.payload},
                    priority=EventPriority.HIGH,
                    correlation_id=event.correlation_id,
                )
            )

    @run_in_domain(ThreadDomain.STRATEGY_ENGINE)
    async def _on_prediction(self, event: SystemEvent):
        """Обработчик предсказания: сигнал → риск → исполнение"""
        self._stats["predictions_made"] += 1

        # 1. Генерация сигнала
        signal = await self.strategy.on_prediction(event)
        if not signal:
            return

        self._stats["signals_generated"] += 1

        # 2. Публикация сигнала
        await self.event_bus.publish(
            SystemEvent(
                type="risk_check_requested",
                payload={"signal": signal.to_dict()},
                priority=EventPriority.CRITICAL,
                correlation_id=signal.correlation_id or event.correlation_id,
            )
        )

        # 3. Риск-проверка
        risk_status, risk_msg = await self.risk.check(signal)

        if risk_status != RiskStatus.APPROVED:
            logger.debug(f"Risk rejected: {signal.symbol} — {risk_status.value}")
            await self._publish_rejection(signal, risk_status, risk_msg)
            return

        self._stats["risks_approved"] += 1

        # 4. Исполнение
        current_price = self._get_tick_price(event.payload)
        result = await self.execution.execute(signal, current_price)

        # 5. Публикация результата
        await self.event_bus.publish(
            SystemEvent(
                type="order_executed" if result.success else "order_failed",
                payload={
                    "signal": signal.to_dict(),
                    "execution": result.to_dict(),
                    "risk_status": risk_status.value,
                },
                priority=EventPriority.HIGH,
                correlation_id=signal.correlation_id,
            )
        )

        if result.success:
            self._stats["orders_executed"] += 1
        else:
            self._stats["orders_failed"] += 1

    async def _publish_rejection(self, signal: TradeSignal, status: RiskStatus, message: str):
        """Публикация события об отклонении сигнала"""
        await self.event_bus.publish(
            SystemEvent(
                type="signal_rejected",
                payload={
                    "symbol": signal.symbol,
                    "action": signal.action.name,
                    "reason": status.value,
                    "message": message,
                },
                priority=EventPriority.MEDIUM,
            )
        )

    async def _on_order_result(self, event: SystemEvent):
        """Логирование результата исполнения в БД"""
        if hasattr(self.db, "log_trade_execution"):
            await self.db.log_trade_execution(event.payload)

    @run_in_domain(ThreadDomain.STRATEGY_ENGINE)
    async def _on_news_batch(self, event: SystemEvent):
        """Обработка батча новостей — обновление сентимента для решений"""
        payload = event.payload
        avg_sentiment = payload.get("avg_sentiment", 0.0)
        count = payload.get("count", 0)

        logger.debug(f"📰 Новости: {count} шт, сентимент: {avg_sentiment:.2f}")

        # Сохраняем сентимент для использования в стратегии
        if not hasattr(self, "_market_sentiment"):
            self._market_sentiment = 0.0
        self._market_sentiment = avg_sentiment

    def get_market_sentiment(self) -> float:
        """Получение текущего рыночного сентимента из новостей."""
        return getattr(self, "_market_sentiment", 0.0)

    def _get_tick_price(self, tick_payload: Dict) -> Optional[float]:
        """Извлечение цены из тика"""
        return tick_payload.get("ask") or tick_payload.get("bid")

    def get_stats(self) -> Dict[str, Any]:
        """Статистика пайплайна"""
        pipeline_efficiency = self._stats["orders_executed"] / max(1, self._stats["signals_generated"])
        return {
            **self._stats,
            "pipeline_efficiency": round(pipeline_efficiency, 3),
            "components": {
                "strategy_signals": self.strategy._signal_count,
                "execution_attempts": self.execution._execution_count,
            },
        }
