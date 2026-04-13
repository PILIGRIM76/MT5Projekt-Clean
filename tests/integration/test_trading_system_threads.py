"""
Интеграционные тесты для TradingSystem с многопоточной архитектурой.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.circuit_breaker import CircuitBreaker, create_circuit_breaker
from src.core.event_bus import AsyncEventBus, EventPriority, SystemEvent, get_event_bus
from src.core.lock_manager import LockLevel, lock_manager
from src.core.thread_domains import ThreadDomain, run_in_domain


class TestTradingSystemThreading:
    """Тесты интеграции TradingSystem с threading архитектурой."""

    @pytest.mark.asyncio
    async def test_event_bus_with_trading_signals(self, async_event_bus_new):
        """Проверка: EventBus доставляет торговые сигналы."""
        received_signals = []

        async def signal_handler(event: SystemEvent):
            received_signals.append(event.payload)

        await async_event_bus_new.subscribe(
            "trade_signal",
            signal_handler,
            domain=ThreadDomain.STRATEGY_ENGINE,
            priority=EventPriority.HIGH,
        )

        # Публикуем сигнал
        await async_event_bus_new.publish(
            SystemEvent(
                type="trade_signal",
                payload={
                    "symbol": "EURUSD",
                    "action": "BUY",
                    "volume": 0.1,
                    "price": 1.0850,
                },
                priority=EventPriority.CRITICAL,
            )
        )

        await asyncio.sleep(0.1)

        assert len(received_signals) == 1
        assert received_signals[0]["symbol"] == "EURUSD"
        assert received_signals[0]["action"] == "BUY"

    @pytest.mark.asyncio
    async def test_ml_prediction_pipeline(self, async_event_bus_new):
        """Проверка: ML prediction pipeline через EventBus."""
        predictions = []

        async def prediction_handler(event: SystemEvent):
            # Имитация ML inference
            symbol = event.payload["symbol"]
            prediction = {"symbol": symbol, "value": 0.75, "confidence": 0.9}
            predictions.append(prediction)

            # Публикуем результат
            await async_event_bus_new.publish(
                SystemEvent(
                    type="prediction_ready",
                    payload=prediction,
                    priority=EventPriority.HIGH,
                )
            )

        # Подписка на market tick
        await async_event_bus_new.subscribe(
            "market_tick",
            prediction_handler,
            domain=ThreadDomain.ML_INFERENCE,
        )

        received_predictions = []

        async def result_handler(event: SystemEvent):
            received_predictions.append(event.payload)

        await async_event_bus_new.subscribe(
            "prediction_ready",
            result_handler,
            domain=ThreadDomain.RISK_ENGINE,
        )

        # Отправляем market tick
        await async_event_bus_new.publish(
            SystemEvent(
                type="market_tick",
                payload={"symbol": "GBPUSD"},
            )
        )

        await asyncio.sleep(0.2)

        assert len(predictions) == 1
        assert len(received_predictions) == 1
        assert received_predictions[0]["symbol"] == "GBPUSD"

    @pytest.mark.asyncio
    async def test_risk_check_before_trade(self, async_event_bus_new):
        """Проверка: risk-check перед исполнением ордера."""
        risk_checks_passed = []
        trades_executed = []

        async def risk_check_handler(event: SystemEvent):
            # Имитация risk check
            risk_ok = event.payload["volume"] <= 1.0
            risk_checks_passed.append(
                {
                    "symbol": event.payload["symbol"],
                    "passed": risk_ok,
                }
            )

            if risk_ok:
                await async_event_bus_new.publish(
                    SystemEvent(
                        type="risk_approved",
                        payload=event.payload,
                        priority=EventPriority.HIGH,
                    )
                )

        async def trade_executor_handler(event: SystemEvent):
            trades_executed.append(event.payload)

        await async_event_bus_new.subscribe(
            "trade_request",
            risk_check_handler,
            domain=ThreadDomain.RISK_ENGINE,
        )

        await async_event_bus_new.subscribe(
            "risk_approved",
            trade_executor_handler,
            domain=ThreadDomain.MT5_IO,
        )

        # Отправляем запрос на торговлю
        await async_event_bus_new.publish(
            SystemEvent(
                type="trade_request",
                payload={"symbol": "EURUSD", "volume": 0.5, "action": "BUY"},
                priority=EventPriority.CRITICAL,
            )
        )

        await asyncio.sleep(0.2)

        assert len(risk_checks_passed) == 1
        assert risk_checks_passed[0]["passed"] is True
        assert len(trades_executed) == 1
        assert trades_executed[0]["symbol"] == "EURUSD"

    def test_lock_protection_for_mt5_and_db(self, lock_manager):
        """Проверка: блокировки защищают MT5 и DB доступ."""
        results = []
        errors = []

        def worker(worker_id):
            try:
                with lock_manager.acquire(
                    LockLevel.MT5_ACCESS,
                    LockLevel.DB_WRITE,
                    timeout=5.0,
                ):
                    # Имитация работы с MT5 и DB
                    time.sleep(0.05)
                    results.append(f"worker_{worker_id}")
            except Exception as e:
                errors.append(str(e))

        # Запускаем 5 параллельных workers
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
        assert len(results) == 5

        # Проверяем contention report
        report = lock_manager.get_contention_report()
        assert "MT5_ACCESS" in report
        assert "DB_WRITE" in report
        assert report["MT5_ACCESS"]["total_acquires"] == 5
        assert report["DB_WRITE"]["total_acquires"] == 5


class TestCircuitBreakerIntegration:
    """Тесты интеграции CircuitBreaker."""

    @pytest.mark.asyncio
    async def test_mt5_service_with_circuit_breaker(self, async_event_bus_new):
        """Проверка: MT5 сервис с circuit breaker."""
        breaker = create_circuit_breaker(
            name="mt5_service_test",
            failure_threshold=3,
            recovery_timeout=1.0,
        )

        call_count = 0

        @breaker.protect
        def mt5_call():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"price": 1.0850}
            else:
                raise ConnectionError("MT5 connection lost")

        # Успешные вызовы
        result1 = mt5_call()
        result2 = mt5_call()

        assert result1["price"] == 1.0850
        assert result2["price"] == 1.0850

        # Вызовы после достижения threshold
        with pytest.raises(Exception):
            mt5_call()

        # Circuit breaker должен быть OPEN
        assert breaker.is_open()

    def test_graceful_degradation_with_circuit_breaker(self):
        """Проверка: graceful degradation при сбое."""
        breaker = CircuitBreaker(
            name="data_service",
            failure_threshold=2,
            recovery_timeout=0.5,
        )

        # Кэш для fallback
        cached_data = {"price": 1.0800}

        def fetch_live_data():
            raise TimeoutError("Data service timeout")

        def get_data():
            if not breaker.can_execute():
                return cached_data  # Fallback

            try:
                data = fetch_live_data()
                breaker.record_success()
                return data
            except Exception:
                breaker.record_failure()
                return cached_data  # Fallback

        # Получаем данные — должен вернуться cached
        data = get_data()
        assert data["price"] == 1.0800

        # Circuit breaker должен зафиксировать ошибку
        assert breaker.metrics.failed_calls == 1


class TestResourceGovernorIntegration:
    """Тесты интеграции ResourceGovernor."""

    @pytest.mark.asyncio
    async def test_ml_training_with_resource_limits(self, async_event_bus_new):
        """Проверка: ML training с лимитами ресурсов."""
        from src.core.resource_governor import AdaptiveResourceGovernor, ResourceBudget

        governor = AdaptiveResourceGovernor(
            total_cpu_cores=8,
            total_memory_gb=16.0,
        )

        # Запрос ресурсов для обучения
        budget = ResourceBudget(
            cpu_percent_max=70.0,
            memory_mb_max=4096,
            timeout_seconds=300.0,
        )

        acquired = await governor.acquire_resources("ml_training_test", budget)
        assert acquired is True

        # Имитация обучения
        await asyncio.sleep(0.1)

        # Освобождение ресурсов
        released = governor.release_resources("ml_training_test")
        assert released is True

        # Проверка отчёта
        report = governor.get_usage_report()
        assert report["active_components"] == 0

    def test_concurrent_tasks_resource_management(self):
        """Проверка: управление ресурсами при параллельных задачах."""
        from src.core.resource_governor import ResourceClass, ResourceGovernor

        # Сбрасываем singleton
        ResourceGovernor._instance = None
        ResourceGovernor._singleton_lock = threading.Lock()

        gov = ResourceGovernor()

        # Запускаем несколько задач
        tasks_started = []
        tasks_finished = []

        for i in range(3):
            task_id = f"prediction_task_{i}"
            if gov.can_start(task_id, ResourceClass.HIGH):
                tasks_started.append(task_id)

        # Проверяем активные задачи
        summary = gov.get_load_summary()
        assert summary["active_tasks"] == len(tasks_started)

        # Завершаем задачи
        for task_id in tasks_started:
            gov.task_finished(task_id)
            tasks_finished.append(task_id)

        summary = gov.get_load_summary()
        assert summary["active_tasks"] == 0


class TestDomainRouting:
    """Тесты маршрутизации по доменам."""

    @pytest.mark.asyncio
    async def test_multi_domain_event_flow(self, async_event_bus_new):
        """Проверка: поток событий через несколько доменов."""
        flow_log = []

        async def market_data_handler(event: SystemEvent):
            flow_log.append(("market_data", event.payload["symbol"]))

            # Генерируем feature engineering
            await async_event_bus_new.publish(
                SystemEvent(
                    type="features_computed",
                    payload={"symbol": event.payload["symbol"], "features": [0.1, 0.2]},
                )
            )

        async def features_handler(event: SystemEvent):
            flow_log.append(("features", event.payload["symbol"]))

            # Генерируем сигнал
            await async_event_bus_new.publish(
                SystemEvent(
                    type="trade_signal",
                    payload={"symbol": event.payload["symbol"], "action": "BUY"},
                )
            )

        async def signal_handler(event: SystemEvent):
            flow_log.append(("signal", event.payload["symbol"], event.payload["action"]))

        # Подписки в разных доменах
        await async_event_bus_new.subscribe(
            "market_tick",
            market_data_handler,
            domain=ThreadDomain.DATA_INGEST,
        )

        await async_event_bus_new.subscribe(
            "features_computed",
            features_handler,
            domain=ThreadDomain.FEATURE_ENGINEERING,
        )

        await async_event_bus_new.subscribe(
            "trade_signal",
            signal_handler,
            domain=ThreadDomain.STRATEGY_ENGINE,
        )

        # Отправляем market tick
        await async_event_bus_new.publish(
            SystemEvent(
                type="market_tick",
                payload={"symbol": "EURUSD"},
            )
        )

        await asyncio.sleep(0.3)

        # Проверяем поток
        assert len(flow_log) == 3
        assert flow_log[0] == ("market_data", "EURUSD")
        assert flow_log[1] == ("features", "EURUSD")
        assert flow_log[2] == ("signal", "EURUSD", "BUY")


class TestThreadSafety:
    """Тесты потокобезопасности."""

    def test_concurrent_lock_acquire_release(self, lock_manager):
        """Проверка: параллельный захват/освобождение блокировок."""
        errors = []
        iterations = 50

        def worker():
            for _ in range(iterations):
                try:
                    with lock_manager.acquire(
                        LockLevel.CACHE,
                        LockLevel.DB_WRITE,
                        timeout=2.0,
                    ):
                        time.sleep(0.001)
                except Exception as e:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Errors: {errors}"

    @pytest.mark.asyncio
    async def test_concurrent_event_publish(self, async_event_bus_new):
        """Проверка: параллельная публикация событий."""
        received_count = [0]

        async def handler(event: SystemEvent):
            received_count[0] += 1

        await async_event_bus_new.subscribe("concurrent_test", handler)

        # Параллельная публикация
        async def publish_batch():
            tasks = []
            for i in range(20):
                task = async_event_bus_new.publish(
                    SystemEvent(
                        type="concurrent_test",
                        payload={"id": i},
                    )
                )
                tasks.append(task)
            await asyncio.gather(*tasks)

        await publish_batch()
        await asyncio.sleep(0.5)

        assert received_count[0] == 20, f"Received {received_count[0]} events"
