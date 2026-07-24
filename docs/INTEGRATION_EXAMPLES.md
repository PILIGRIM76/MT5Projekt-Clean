# Примеры интеграции многопоточной архитектуры

## 📚 Содержание
1. [TradingSystem Integration](#1-tradingsystem-integration)
2. [MLCoordinator Integration](#2-mlcoordinator-integration)
3. [GUI Bridge Integration](#3-gui-bridge-integration)
4. [Best Practices](#best-practices)

---

## 1. TradingSystem Integration

### Базовая интеграция с EventBus

```python
# src/core/trading_system.py

from src.core.event_bus import get_event_bus, SystemEvent, EventPriority
from src.core.thread_domains import ThreadDomain, run_in_domain
from src.core.lock_manager import lock_manager, LockLevel, requires_locks
from src.core.circuit_breaker import create_circuit_breaker
import asyncio
import logging

logger = logging.getLogger(__name__)


class TradingSystem:
    """
    Trading System с многопоточной архитектурой.

    Особенности:
    - Все события через AsyncEventBus
    - Блокировки через LockHierarchy
    - Circuit breakers для внешних сервисов
    """

    def __init__(self, config):
        self.config = config
        self.event_bus = get_event_bus()

        # Circuit breaker для MT5
        self.mt5_breaker = create_circuit_breaker(
            name="mt5_api",
            failure_threshold=5,
            recovery_timeout=30.0,
        )

        # Circuit breaker для DB
        self.db_breaker = create_circuit_breaker(
            name="database",
            failure_threshold=3,
            recovery_timeout=10.0,
        )

        logger.info("TradingSystem initialized with threading architecture")

    async def start(self):
        """Запуск системы"""
        # Подписка на события
        await self._subscribe_to_events()

        logger.info("TradingSystem started")

    async def stop(self):
        """Остановка системы"""
        await self.event_bus.stop(timeout=10.0)
        logger.info("TradingSystem stopped")

    async def _subscribe_to_events(self):
        """Регистрация обработчиков событий"""
        # Market ticks
        await self.event_bus.subscribe(
            "market_tick",
            self._on_market_tick,
            domain=ThreadDomain.STRATEGY_ENGINE,
            priority=EventPriority.HIGH,
        )

        # Model predictions
        await self.event_bus.subscribe(
            "model_prediction",
            self._on_prediction,
            domain=ThreadDomain.RISK_ENGINE,
            priority=EventPriority.HIGH,
        )

        # Trade signals
        await self.event_bus.subscribe(
            "trade_signal",
            self._on_trade_signal,
            domain=ThreadDomain.MT5_IO,
            priority=EventPriority.CRITICAL,
        )

    @requires_locks(LockLevel.MT5_ACCESS, LockLevel.DB_WRITE)
    def execute_trade(self, symbol: str, volume: float, order_type: str) -> dict:
        """
        Исполнение ордера с автоматической защитой блокировками.

        Decorator требует_locks гарантирует:
        1. Захват MT5_ACCESS и DB_WRITE в правильном порядке
        2. Автоматическое освобождение при выходе
        3. Deadlock detection
        """
        # Проверяем circuit breaker
        if not self.mt5_breaker.can_execute():
            logger.warning("MT5 circuit breaker is OPEN, trade deferred")
            return {"error": "MT5 unavailable"}

        try:
            # MT5 API call (защищено MT5_ACCESS lock)
            result = self._mt5_order_send(symbol, volume, order_type)

            if result.get('retcode') == 10009:
                # Log to DB (защищено DB_WRITE lock)
                self._db_log_trade(result)
                self.mt5_breaker.record_success()

            return result

        except Exception as e:
            self.mt5_breaker.record_failure()
            raise

    @run_in_domain(ThreadDomain.ML_INFERENCE)
    async def _on_market_tick(self, event: SystemEvent):
        """
        Обработчик тика — выполняется в домене ML_INFERENCE.

        Автоматически:
        - Запускается в THREAD_POOL executor
        - Имеет timeout из конфигурации домена (5 сек)
        - Приоритет HIGH
        """
        symbol = event.payload['symbol']

        try:
            # Получение предсказания
            prediction = await self._ml_predict(symbol)

            # Публикация результата
            await self.event_bus.publish(SystemEvent(
                type="model_prediction",
                payload={
                    "symbol": symbol,
                    "prediction": prediction,
                    "timestamp": event.timestamp,
                },
                priority=EventPriority.HIGH,
            ))

        except Exception as e:
            logger.error(f"Prediction failed for {symbol}: {e}")

    async def _on_prediction(self, event: SystemEvent):
        """
        Обработка предсказания с риск-менеджментом.
        Выполняется в домене RISK_ENGINE.
        """
        symbol = event.payload['symbol']
        prediction = event.payload['prediction']

        # Risk check
        risk_ok = await self._check_risk(symbol, prediction)

        if risk_ok:
            # Генерация торгового сигнала
            await self.event_bus.publish(SystemEvent(
                type="trade_signal",
                payload={
                    "symbol": symbol,
                    "action": "BUY" if prediction > 0.6 else "SELL",
                    "confidence": prediction,
                },
                priority=EventPriority.CRITICAL,  # Высокий приоритет для исполнения
            ))

    async def _on_trade_signal(self, event: SystemEvent):
        """
        Исполнение торгового сигнала.
        Выполняется в домене MT5_IO.
        """
        try:
            result = self.execute_trade(
                symbol=event.payload['symbol'],
                volume=0.1,
                order_type=event.payload['action'],
            )

            # Публикуем результат
            await self.event_bus.publish(SystemEvent(
                type="trade_executed",
                payload={
                    "symbol": event.payload['symbol'],
                    "result": result,
                },
                priority=EventPriority.HIGH,
            ))

        except Exception as e:
            logger.error(f"Trade execution failed: {e}")

    async def _ml_predict(self, symbol: str) -> float:
        """ML prediction (выполняется в ML_INFERENCE domain)"""
        # Здесь ваша логика ML
        return 0.75

    async def _check_risk(self, symbol: str, prediction: float) -> bool:
        """Risk check (выполняется в RISK_ENGINE domain)"""
        # Здесь ваша логика риск-менеджмента
        return True

    def _mt5_order_send(self, symbol, volume, order_type):
        """MT5 order send (защищено circuit breaker)"""
        # Здесь вызов MT5 API
        return {"retcode": 10009, "deal": 12345}

    def _db_log_trade(self, result):
        """Log trade to DB"""
        # Здесь запись в БД
        pass
```

---

## 2. MLCoordinator Integration

### Асинхронное обучение моделей

```python
# src/ml/ml_coordinator.py

from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import asyncio
from src.core.event_bus import get_event_bus, SystemEvent, EventPriority
from src.core.thread_domains import ThreadDomain, run_in_domain
from src.core.lock_manager import lock_manager, LockLevel
from src.core.resource_governor import AdaptiveResourceGovernor, ResourceBudget
import logging

logger = logging.getLogger(__name__)


class MLCoordinator:
    """
    Координатор ML моделей с асинхронным обучением.

    Особенности:
    - ProcessPool для обучения (обход GIL)
    - ThreadPool для inference (NumPy освобождает GIL)
    - Hot-swap моделей без блокировки трейдинга
    """

    def __init__(self, config):
        self.config = config
        self.event_bus = get_event_bus()

        # ProcessPool для обучения (только 1 задача!)
        self._train_pool = ProcessPoolExecutor(
            max_workers=1,
            mp_context=mp.get_context('spawn')  # Важно для Windows
        )

        # Resource governor
        self.resource_governor = AdaptiveResourceGovernor()

        # Registry моделей
        self._models = {}
        self._models_lock = asyncio.Lock()

        logger.info("MLCoordinator initialized")

    @run_in_domain(ThreadDomain.ML_TRAINING)
    async def retrain_symbol(self, symbol: str, force: bool = False) -> bool:
        """
        Переобучение модели в фоне с hot-swap заменой.

        НЕ блокирует основной поток трейдинга!
        """
        # 1. Проверка ресурсов
        budget = ResourceBudget(
            cpu_percent_max=70.0,
            memory_mb_max=4096,
            timeout_seconds=300.0,
        )

        if not await self.resource_governor.acquire_resources(
            f"train_{symbol}",
            budget,
        ):
            logger.warning(f"Training deferred for {symbol}: resources busy")
            return False

        try:
            # 2. Подготовка данных (в thread pool)
            data = await asyncio.to_thread(
                self._prepare_training_data,
                symbol
            )

            # 3. Обучение в процессе (обход GIL)
            loop = asyncio.get_event_loop()
            new_model = await loop.run_in_executor(
                self._train_pool,
                self._train_sync,
                symbol,
                data,
                self.config,
            )

            # 4. Валидация перед заменой
            if not self._validate_model(new_model, symbol):
                logger.warning(f"Model validation failed for {symbol}")
                return False

            # 5. Атомарная замена модели (с блокировкой)
            async with self._models_lock:
                self._models[symbol] = new_model

            # 6. Уведомление системы
            await self.event_bus.publish(SystemEvent(
                type="model_updated",
                payload={
                    "symbol": symbol,
                    "timestamp": asyncio.get_event_loop().time(),
                },
                priority=EventPriority.MEDIUM,
            ))

            logger.info(f"✅ Model for {symbol} updated successfully")
            return True

        except Exception as e:
            logger.error(f"Training failed for {symbol}: {e}", exc_info=True)
            return False

        finally:
            self.resource_governor.release_resources(f"train_{symbol}")

    async def predict(self, symbol: str) -> float:
        """
        Предсказание модели (быстрый inference).

        Выполняется в THREAD_POOL (не блокирует GUI)
        """
        async with self._models_lock:
            model = self._models.get(symbol)

        if model is None:
            logger.warning(f"No model for {symbol}")
            return 0.5  # Default

        # Inference (освобождает GIL для NumPy/ONNX)
        prediction = await asyncio.to_thread(
            self._predict_sync,
            model,
            symbol,
        )

        return prediction

    def _train_sync(self, symbol: str, data, config):
        """
        Синхронная функция обучения — выполняется в отдельном процессе.

        Здесь можно грузить CPU на 100% без блокировки!
        """
        # Тяжёлые вычисления
        model = self._build_model(config)
        model.fit(data)
        return model

    def _predict_sync(self, model, symbol: str) -> float:
        """Синхронное предсказание"""
        features = self._extract_features(symbol)
        return model.predict(features)

    def _prepare_training_data(self, symbol: str):
        """Подготовка данных для обучения"""
        # Загрузка и предобработка данных
        return {"features": [], "labels": []}

    def _validate_model(self, model, symbol: str) -> bool:
        """Валидация модели перед заменой"""
        # Проверка качества
        return True

    def _build_model(self, config):
        """Создание модели"""
        # Здесь ваша логика
        pass

    def _extract_features(self, symbol: str):
        """Извлечение фич"""
        # Здесь ваша логика
        pass
```

---

## 3. GUI Bridge Integration

### Безопасная интеграция с Qt GUI

```python
# main_pyside.py (фрагмент)

import asyncio
from PySide6.QtCore import QThread, Signal, QObject, Slot
from PySide6.QtWidgets import QMainWindow, QLabel, QVBoxLayout, QWidget
from src.core.event_bus import get_event_bus, SystemEvent
from src.core.thread_domains import ThreadDomain


class GUIEventBridge(QObject):
    """
    Мост между Qt сигналами и EventBus.

    Гарантирует:
    - Все обновления GUI в главном потоке Qt
    - Блокирующие операции в background потоках
    """

    # Signals для отправки в GUI
    prediction_updated = Signal(dict)
    trade_executed = Signal(dict)
    system_status = Signal(str)

    def __init__(self):
        super().__init__()
        self.event_bus = get_event_bus()

    async def start_listening(self):
        """Подписка на события для GUI"""
        # Predictions
        await self.event_bus.subscribe(
            "prediction_ready",
            self._on_prediction,
            domain=ThreadDomain.GUI,
        )

        # Trade executions
        await self.event_bus.subscribe(
            "trade_executed",
            self._on_trade,
            domain=ThreadDomain.GUI,
        )

        # System status
        await self.event_bus.subscribe(
            "system_status",
            self._on_status,
            domain=ThreadDomain.GUI,
        )

    def _on_prediction(self, event: SystemEvent):
        """Обработка предсказания — вызывается в EventLoop, отправляем в GUI"""
        self.prediction_updated.emit(event.payload)

    def _on_trade(self, event: SystemEvent):
        """Обработка исполнения ордера"""
        self.trade_executed.emit(event.payload)

    def _on_status(self, event: SystemEvent):
        """Обработка статуса системы"""
        self.system_status.emit(event.payload.get('message', ''))


class AsyncWorker(QObject):
    """Worker для запуска asyncio loop в QThread"""
    finished = Signal()

    @Slot()
    def run(self):
        """Запуск event loop в этом потоке"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def main():
            await get_event_bus().start()

            # GUI bridge
            bridge = GUIEventBridge()
            await bridge.start_listening()

            # Loop работает пока не будет остановлен
            while True:
                await asyncio.sleep(0.1)

        try:
            loop.run_until_complete(main())
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()
            self.finished.emit()


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self):
        super().__init__()

        # UI
        self.prediction_label = QLabel("Prediction: --")
        self.status_label = QLabel("Status: Initializing...")

        layout = QVBoxLayout()
        layout.addWidget(self.prediction_label)
        layout.addWidget(self.status_label)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # GUI Bridge
        self.gui_bridge = GUIEventBridge()
        self.gui_bridge.prediction_updated.connect(self._update_prediction)
        self.gui_bridge.trade_executed.connect(self._update_trade)
        self.gui_bridge.system_status.connect(self._update_status)

        # Запуск asyncio loop в отдельном потоке
        self.async_thread = QThread()
        self.async_worker = AsyncWorker()
        self.async_worker.moveToThread(self.async_thread)

        self.async_thread.started.connect(self.async_worker.run)
        self.async_thread.start()

        self.status_label.setText("Status: Running")

    def _update_prediction(self, data: dict):
        """Обновление предсказания в GUI (главный поток Qt)"""
        symbol = data.get('symbol', '--')
        value = data.get('prediction', 0)
        self.prediction_label.setText(
            f"Prediction: {symbol} = {value:.4f}"
        )

    def _update_trade(self, data: dict):
        """Обновление информации о сделке"""
        symbol = data.get('symbol', '--')
        result = data.get('result', {})
        self.status_label.setText(
            f"Trade: {symbol} - {result.get('retcode', 'unknown')}"
        )

    def _update_status(self, message: str):
        """Обновление статуса системы"""
        self.status_label.setText(f"Status: {message}")

    def closeEvent(self, event):
        """Корректное завершение при закрытии"""
        # Остановка EventBus
        loop = asyncio.new_event_loop()
        loop.run_until_complete(get_event_bus().stop(timeout=5.0))
        loop.close()

        # Остановка async потока
        self.async_thread.quit()
        self.async_thread.wait(3000)  # 3 секунды таймаут

        super().closeEvent(event)
```

---

## Best Practices

### ✅ DO:

```python
# 1. Используйте EventBus для межкомпонентного общения
await event_bus.publish(SystemEvent(
    type="trade_signal",
    payload={"symbol": "EURUSD", "action": "BUY"},
    priority=EventPriority.CRITICAL,
))

# 2. Используйте блокировки с правильным порядком
with lock_manager.acquire(LockLevel.MT5_ACCESS, LockLevel.DB_WRITE):
    # Код защищён
    pass

# 3. Используйте circuit breakers для внешних сервисов
@breaker.protect
def call_external_api():
    return requests.get(url)

# 4. Используйте домены для тяжелых операций
@run_in_domain(ThreadDomain.ML_INFERENCE)
def heavy_computation():
    return model.predict(data)
```

### ❌ DON'T:

```python
# 1. НЕ блокируйте GUI поток
def bad_example():
    time.sleep(10)  # Блокирует GUI!
    self.label.setText("Done")

# 2. НЕ захватывайте блокировки в неправильном порядке
with lock_manager.acquire(LockLevel.DB_WRITE, LockLevel.MT5_ACCESS):
    # DEADLOCK RISK!
    pass

# 3. НЕ игнорируйте circuit breaker errors
def call_api():
    result = external_api.call()  # Может упасть!
    return result

# 4. НЕ используйте прямые вызовы между компонентами
trading_system.generate_signal(data)  # Tight coupling!
```

### 📊 Мониторинг:

```python
# Проверка contention блокировок
report = lock_manager.get_contention_report()
if report['MT5_ACCESS']['contention_ratio'] > 0.1:
    logger.warning("High MT5 lock contention!")

# Проверка EventBus
stats = event_bus.get_stats()
if stats['queue_size'] > 100:
    logger.warning("EventBus queue growing!")

# Проверка circuit breakers
health = circuit_breaker_registry.get_health_report()
if health['open_circuits'] > 0:
    logger.critical(f"Open circuits: {health['open_circuits']}")
```

---

> 📝 **Дата**: 14 апреля 2026
> 👥 **Team**: MT5 Projekt
> 🚀 **Статус**: Production Ready
