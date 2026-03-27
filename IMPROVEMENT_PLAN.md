# 🚀 GENESIS TRADING SYSTEM: ПЛАН УЛУЧШЕНИЙ

**Версия документа:** 1.0  
**Дата составления:** 27 марта 2026  
**Оценка текущего состояния:** 7.5/10  
**Целевая оценка:** 9.0/10  
**Расчетное время реализации:** 4-6 месяцев

---

## 📋 СОДЕРЖАНИЕ

1. [Обзор и приоритеты](#1-обзор-и-приоритеты)
2. [Фаза 1: Критические улучшения (Недели 1-4)](#2-фаза-1-критические-улучшения-недели-1-4)
3. [Фаза 2: Архитектурный рефакторинг (Недели 5-10)](#3-фаза-2-архитектурный-рефакторинг-недели-5-10)
4. [Фаза 3: Тестирование и надежность (Недели 11-14)](#4-фаза-3-тестирование-и-надежность-недели-11-14)
5. [Фаза 4: Производительность (Недели 15-18)](#5-фаза-4-производительность-недели-15-18)
6. [Фаза 5: Production-ready (Недели 19-24)](#6-фаза-5-production-ready-недели-19-24)
7. [Дорожная карта](#7-дорожная-карта)
8. [Метрики успеха](#8-метрики-успеха)

---

## 1. ОБЗОР И ПРИОРИТЕТЫ

### 1.1 Матрица приоритетов

```
                    ┌─────────────────────────────────────┐
                    │           ВАЖНОСТЬ                  │
                    │  Высокая  │  Средняя  │  Низкая     │
    ┌───────────────┼───────────┼───────────┼─────────────┤
    │  Высокий      │  Фаза 1   │  Фаза 3   │  Фаза 5     │
    │               │  (Безопас-│  (Тесты)  │  (Докумен-  │
    │               │   ность)  │           │  тация)     │
    ├───────────────┼───────────┼───────────┼─────────────┤
    │  Средний      │  Фаза 2   │  Фаза 4   │  Будущие    │
    │               │  (Архитек-│  (Произ-  │  улучшения  │
    │               │   тура)   │  водитель-│            │
    │               │           │   ность)  │            │
    └───────────────┴───────────┴───────────┴─────────────┘
```

### 1.2 Распределение ресурсов

| Фаза | Длительность | Приоритет | Команда |
|------|--------------|-----------|---------|
| Фаза 1 | 4 недели | 🔴 Критично | 1 разработчик |
| Фаза 2 | 6 недель | 🔴 Критично | 2 разработчика |
| Фаза 3 | 4 недели | 🟡 Важно | 1 разработчик + QA |
| Фаза 4 | 4 недели | 🟡 Важно | 1 разработчик |
| Фаза 5 | 6 недель | 🟢 Желательно | 1 разработчик |

---

## 2. ФАЗА 1: КРИТИЧЕСКИЕ УЛУЧШЕНИЯ (Недели 1-4)

### 2.1 Безопасность (Неделя 1-2)

#### 🔴 Задача 1.1.1: Вынос секретов в переменные окружения

**Файлы:** `configs/settings.json`, `configs/.env`, `src/core/config_loader.py`

**Текущее состояние:**
```json
// configs/settings.json
{
    "MT5_LOGIN": "52565344",
    "MT5_PASSWORD": "mypassword123",  // ❌ В открытом виде!
    "MT5_SERVER": "Alpari-MT5-Demo"
}
```

**Целевое состояние:**
```bash
# configs/.env
MT5_LOGIN=52565344
MT5_PASSWORD=${ENC:AES256:mypassword123}  # ✅ Шифрование
MT5_SERVER=Alpari-MT5-Demo
DATABASE_URL=sqlite:///F:/Enjen/database/trading_system.db
```

**Изменения:**
```python
# src/core/config_loader.py
import os
from cryptography.fernet import Fernet

class SecureConfigLoader:
    def __init__(self):
        self.encryption_key = os.environ.get('ENCRYPTION_KEY')
        self.cipher = Fernet(self.encryption_key)
    
    def load_mt5_credentials(self) -> dict:
        return {
            'login': int(os.environ.get('MT5_LOGIN')),
            'password': self.decrypt(os.environ.get('MT5_PASSWORD')),
            'server': os.environ.get('MT5_SERVER'),
            'path': os.environ.get('MT5_PATH')
        }
    
    def decrypt(self, encrypted_value: str) -> str:
        if encrypted_value.startswith('${ENC:AES256:'):
            # Извлечение и дешифровка
            encrypted = encrypted_value.split(':')[2].rstrip('}')
            return self.cipher.decrypt(encrypted.encode()).decode()
        return encrypted_value
```

**Критерии приемки:**
- [ ] Пароли не хранятся в открытом виде
- [ ] Шифрование AES-256
- [ ] Ключ шифрования в переменной окружения
- [ ] Документация по настройке шифрования

**Оценка:** 8 часов

---

#### 🔴 Задача 1.1.2: Валидация входных данных

**Файлы:** `src/core/data_models.py`, `src/web/server.py`, `src/db/database_manager.py`

**Текущее состояние:**
```python
# Нет валидации
def execute_trade(symbol, lot, type):
    # symbol может быть любым
    # lot может быть отрицательным
    ...
```

**Целевое состояние:**
```python
# src/core/data_models.py
from pydantic import BaseModel, Field, validator
import re

class TradeSignal(BaseModel):
    type: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    symbol: str
    lot: float = Field(gt=0.0)
    stop_loss: float = Field(gt=0.0)
    take_profit: float = Field(gt=0.0)
    
    @validator('symbol')
    def validate_symbol_format(cls, v):
        if not re.match(r'^[A-Z]{6}$', v) and not v in ['BITCOIN', 'GOLD', 'SILVER']:
            raise ValueError(f'Invalid symbol format: {v}')
        return v
    
    @validator('confidence')
    def validate_confidence(cls, v):
        if v < 0.3:  # Минимальный порог уверенности
            raise ValueError(f'Confidence too low: {v}')
        return v
    
    @validator('lot')
    def validate_lot(cls, v, values):
        if v > 100.0:  # Максимальный лот
            raise ValueError(f'Lot too large: {v}')
        return v

class TradeRequest(BaseModel):
    symbol: str
    lot: float
    order_type: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    @validator('order_type')
    def validate_order_type(cls, v):
        if v not in ['BUY', 'SELL']:
            raise ValueError(f'Invalid order type: {v}')
        return v
```

**Критерии приемки:**
- [ ] Все входные данные валидируются
- [ ] Pydantic модели для API запросов
- [ ] Кастомные валидаторы для бизнес-логики
- [ ] Информативные сообщения об ошибках

**Оценка:** 12 часов

---

#### 🔴 Задача 1.1.3: Rate Limiting для Web API

**Файлы:** `src/web/server.py`

**Текущее состояние:**
```python
@app.post("/api/trade")
async def execute_trade(request: TradeRequest):
    # Нет ограничения частоты запросов
    ...
```

**Целевое состояние:**
```python
# src/web/server.py
from fastapi import FastAPI, Request, HTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Инициализация limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Эндпоинты с rate limiting
@app.post("/api/trade")
@limiter.limit("10/minute")  # Макс 10 торговых запросов в минуту
async def execute_trade(request: Request, trade_req: TradeRequest):
    ...

@app.get("/api/data/{symbol}")
@limiter.limit("60/minute")  # Макс 60 запросов данных в минуту
async def get_data(request: Request, symbol: str):
    ...

@app.post("/api/model/train")
@limiter.limit("5/hour")  # Макс 5 обучений в час
async def train_model(request: Request):
    ...
```

**Критерии приемки:**
- [ ] Rate limiting на всех эндпоинтах
- [ ] Разные лимиты для разных операций
- [ ] Возврат 429 при превышении
- [ ] Логирование превышений

**Оценка:** 6 часов

---

#### 🔴 Задача 1.1.4: Audit Log для сделок

**Файлы:** `src/db/database_manager.py`, `src/core/services/trade_executor.py`

**Новая таблица БД:**
```python
# src/db/database_manager.py
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

class TradeAudit(Base):
    """Таблица аудита торговых решений"""
    __tablename__ = 'trade_audit'
    
    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade_history.id'))
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Кто принял решение
    decision_maker = Column(String)  # 'AI_Model', 'RLTradeManager', 'Human'
    strategy_name = Column(String)
    
    # Обоснование решения
    market_regime = Column(String)
    capital_allocation = Column(Float)
    consensus_score = Column(Float)
    kg_sentiment = Column(Float)
    
    # Проверки риска
    risk_checks = Column(JSON)  # {
                                #   "pre_mortem_passed": true,
                                #   "var_check_passed": true,
                                #   "correlation_check_passed": true,
                                #   "daily_drawdown_ok": true
                                # }
    
    # Контекст
    account_balance = Column(Float)
    account_equity = Column(Float)
    open_positions_count = Column(Integer)
    portfolio_var = Column(Float)
    
    # Результат
    execution_status = Column(String)  # 'EXECUTED', 'REJECTED', 'FAILED'
    rejection_reason = Column(String)
    execution_time_ms = Column(Float)
    
    trade = relationship("TradeHistory", back_populates="audits")
```

**Изменения в TradeExecutor:**
```python
# src/core/services/trade_executor.py
import time

class TradeExecutor:
    def execute_trade(self, signal: TradeSignal) -> bool:
        start_time = time.time()
        
        # Сбор контекста для аудита
        audit_data = {
            'decision_maker': signal.source,
            'strategy_name': signal.strategy_name,
            'market_regime': self.trading_system._get_current_market_regime_name(),
            'capital_allocation': self._get_current_allocation(),
            'consensus_score': signal.confidence,
            'kg_sentiment': self.trading_system.news_cache.aggregated_sentiment,
            'risk_checks': {
                'pre_mortem_passed': self._check_pre_mortem(signal),
                'var_check_passed': self._check_portfolio_var(),
                'correlation_check_passed': self._check_correlation(signal),
                'daily_drawdown_ok': self._check_daily_drawdown()
            },
            'account_balance': self.account_info.balance,
            'account_equity': self.account_info.equity,
            'open_positions_count': len(self.open_positions),
            'portfolio_var': self.risk_engine.calculate_portfolio_var(...)
        }
        
        try:
            # Исполнение сделки
            result = self._send_order_to_mt5(signal)
            
            audit_data['execution_status'] = 'EXECUTED' if result else 'FAILED'
            audit_data['rejection_reason'] = None
            
        except Exception as e:
            audit_data['execution_status'] = 'FAILED'
            audit_data['rejection_reason'] = str(e)
        
        finally:
            audit_data['execution_time_ms'] = (time.time() - start_time) * 1000
            
            # Сохранение в audit log
            self.db_manager.create_trade_audit(audit_data)
        
        return result
```

**Критерии приемки:**
- [ ] Каждая сделка логируется в audit таблицу
- [ ] Сохранение полного контекста решения
- [ ] Фиксация всех проверок риска
- [ ] Время исполнения
- [ ] API для запроса audit логов

**Оценка:** 16 часов

---

### 2.2 Модуляризация (Неделя 3-4)

#### 🔴 Задача 1.2.1: Разделение trading_system.py

**Текущее состояние:**
```
src/core/trading_system.py (3300 строк)
├── __init__ (500 строк)
├── GUI методы (800 строк)
├── Торговая логика (700 строк)
├── ML методы (600 строк)
├── Risk методы (400 строк)
└── Утилиты (300 строк)
```

**Целевая структура:**
```
src/core/
├── trading_system_core.py (600 строк)
│   └── class TradingSystemCore
│       - Инициализация компонентов
│       - Координация сервисов
│       - Управление жизненным циклом
│
├── trading_system_gui.py (900 строк)
│   └── class TradingSystemGUI
│       - Обновление UI элементов
│       - Обработка пользовательских действий
│       - Визуализация данных
│
├── trading_system_trading.py (700 строк)
│   └── class TradingSystemTrading
│       - Исполнение сделок
│       - Управление позициями
│       - Синхронизация с MT5
│
├── trading_system_ml.py (700 строк)
│   └── class TradingSystemML
│       - Управление ML моделями
│       - Обучение и переобучение
│       - Inference сигналов
│
└── trading_system_risk.py (500 строк)
    └── class TradingSystemRisk
        - Проверки риска
        - Расчет VaR
        - Хеджирование
```

**Пример рефакторинга:**
```python
# trading_system_core.py
from .trading_system_gui import TradingSystemGUI
from .trading_system_trading import TradingSystemTrading
from .trading_system_ml import TradingSystemML
from .trading_system_risk import TradingSystemRisk

class TradingSystemCore(QObject):
    """Основной контроллер системы"""
    
    def __init__(self, config):
        super().__init__()
        
        # Инициализация компонентов
        self.db_manager = DatabaseManager()
        self.risk_engine = RiskEngine(config, self)
        
        # Композиция модулей
        self.gui = TradingSystemGUI(self)
        self.trading = TradingSystemTrading(self)
        self.ml = TradingSystemML(self)
        self.risk = TradingSystemRisk(self)
        
    def start(self):
        self.gui.initialize()
        self.trading.connect_mt5()
        self.ml.load_models()
        self.risk.initialize_checks()
```

**Критерии приемки:**
- [ ] trading_system.py разделен на 5 модулей
- [ ] Каждый модуль < 1000 строк
- [ ] Четкие интерфейсы между модулями
- [ ] Все тесты проходят после рефакторинга

**Оценка:** 40 часов

---

## 3. ФАЗА 2: АРХИТЕКТУРНЫЙ РЕФАКТОРИНГ (Недели 5-10)

### 3.1 Dependency Injection (Неделя 5-6)

#### 🟡 Задача 2.1.1: Внедрение DI контейнера

**Файлы:** `src/core/container.py` (новый), `src/core/trading_system_core.py`

**Текущее состояние:**
```python
class TradingSystem:
    def __init__(self):
        self.db_manager = DatabaseManager()  # ❌ Жесткая зависимость
        self.risk_engine = RiskEngine(self.config, self)
        self.orchestrator = Orchestrator(self, ...)
```

**Целевое состояние:**
```python
# src/core/container.py
from dependency_injector import containers, providers

class Container(containers.DeclarativeContainer):
    """DI контейнер для Trading System"""
    
    config = providers.Singleton(load_config)
    
    # Базы данных
    db_manager = providers.Singleton(DatabaseManager)
    vector_db_manager = providers.Singleton(VectorDBManager)
    
    # Данные
    data_provider = providers.Factory(
        DataProvider,
        config=config,
        db_manager=db_manager
    )
    
    # Риск
    risk_engine = providers.Factory(
        RiskEngine,
        config=config,
        trading_system=providers.Self(),
        querier=providers.LazyCallable(
            lambda: KnowledgeGraphQuerier()
        )
    )
    
    # Сервисы
    trading_service = providers.Factory(
        TradingService,
        db_manager=db_manager,
        risk_engine=risk_engine,
        data_provider=data_provider
    )
    
    # ML
    model_factory = providers.Factory(
        ModelFactory,
        config=config
    )
    
    orchestrator = providers.Factory(
        Orchestrator,
        trading_system=providers.Self(),
        strategy_optimizer=providers.LazyCallable(
            lambda: StrategyOptimizer()
        ),
        db_manager=db_manager,
        data_provider=data_provider
    )

# main_pyside.py
container = Container()
container.config()  # Инициализация конфигурации

trading_system = TradingSystemCore(
    db_manager=container.db_manager(),
    risk_engine=container.risk_engine(),
    data_provider=container.data_provider(),
    orchestrator=container.orchestrator()
)
```

**Критерии приемки:**
- [ ] DI контейнер настроен
- [ ] Все зависимости внедряются
- [ ] Легко мокировать для тестов
- [ ] Singleton для тяжелых объектов

**Оценка:** 24 часа

---

#### 🟡 Задача 2.1.2: Интерфейсы для основных компонентов

**Файлы:** `src/core/interfaces.py`

```python
# src/core/interfaces.py
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import pandas as pd

class IDatabaseManager(ABC):
    """Интерфейс для работы с БД"""
    
    @abstractmethod
    def save_trade(self, trade_data: dict) -> int:
        pass
    
    @abstractmethod
    def get_recent_trades(self, symbol: str, limit: int) -> List[dict]:
        pass
    
    @abstractmethod
    def get_strategy_performance(self, strategy_name: str) -> dict:
        pass

class IRiskEngine(ABC):
    """Интерфейс для управления рисками"""
    
    @abstractmethod
    def calculate_position_size(
        self,
        symbol: str,
        df: pd.DataFrame,
        account_info: Any,
        trade_type: SignalType,
        confidence: str,
        strategy_name: str
    ) -> tuple:
        pass
    
    @abstractmethod
    def is_trade_safe(self, symbol: str, signal: TradeSignal) -> bool:
        pass
    
    @abstractmethod
    def calculate_portfolio_var(
        self,
        open_positions: List,
        data_dict: Dict[str, pd.DataFrame]
    ) -> Optional[float]:
        pass

class IDataProvider(ABC):
    """Интерфейс для получения данных"""
    
    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        timeframe: int,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        pass
    
    @abstractmethod
    def get_realtime_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        pass
    
    @abstractmethod
    def get_news(self, limit: int = 50) -> List[dict]:
        pass
```

**Критерии приемки:**
- [ ] Интерфейсы для всех основных компонентов
- [ ] Типизация через ABC
- [ ] Документация методов

**Оценка:** 16 часов

---

### 3.2 Событийная архитектура (Неделя 7-8)

#### 🟡 Задача 2.2.1: Event Bus для межкомпонентного общения

**Файлы:** `src/core/events.py` (новый), `src/core/event_bus.py` (новый)

```python
# src/core/events.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

class EventType(Enum):
    # Торговые события
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    TRADE_REJECTED = "trade_rejected"
    
    # События риска
    RISK_CHECK_PASSED = "risk_check_passed"
    RISK_CHECK_FAILED = "risk_check_failed"
    DRAWDOWN_LIMIT_APPROACHED = "drawdown_limit_approached"
    VAR_LIMIT_EXCEEDED = "var_limit_exceeded"
    
    # ML события
    MODEL_LOADED = "model_loaded"
    MODEL_RETRAINED = "model_retrained"
    CONCEPT_DRIFT_DETECTED = "concept_drift_detected"
    
    # События рынка
    MARKET_REGIME_CHANGED = "market_regime_changed"
    NEWS_PUBLISHED = "news_published"
    ECONOMIC_EVENT = "economic_event"
    
    # События системы
    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPED = "system_stopped"
    ERROR_OCCURRED = "error_occurred"

@dataclass
class Event:
    """Базовый класс события"""
    type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None

@dataclass
class TradeEvent(Event):
    """Событие торговли"""
    symbol: str = ""
    lot: float = 0.0
    order_type: str = ""
    price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_name: str = ""
    pnl: Optional[float] = None

@dataclass
class RiskEvent(Event):
    """Событие риска"""
    risk_type: str = ""
    current_value: float = 0.0
    threshold: float = 0.0
    action_taken: str = ""

@dataclass
class MarketRegimeEvent(Event):
    """Событие смены режима рынка"""
    old_regime: str = ""
    new_regime: str = ""
    confidence: float = 0.0
```

```python
# src/core/event_bus.py
import asyncio
from typing import Callable, Dict, List, Set
from collections import defaultdict
import logging
from .events import Event, EventType

logger = logging.getLogger(__name__)

class EventBus:
    """Центральная шина событий"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._async_subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_history: List[Event] = []
        self._max_history = 1000
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """Подписка на событие (синхронная)"""
        self._subscribers[event_type].append(callback)
        logger.debug(f"Подписчик добавлен на {event_type.value}")
    
    def subscribe_async(self, event_type: EventType, callback: Callable):
        """Подписка на событие (асинхронная)"""
        self._async_subscribers[event_type].append(callback)
    
    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Отписка от события"""
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
    
    def publish(self, event: Event):
        """Публикация события"""
        # Сохранение в историю
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        # Синхронные подписчики
        for callback in self._subscribers[event.type]:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Ошибка в подписчике {callback}: {e}")
        
        # Асинхронные подписчики
        async def call_async_subscribers():
            for callback in self._async_subscribers[event.type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"Ошибка в async подписчике {callback}: {e}")
        
        if self._async_subscribers[event.type]:
            asyncio.create_task(call_async_subscribers())
    
    def get_history(self, event_type: Optional[EventType] = None, limit: int = 100) -> List[Event]:
        """Получение истории событий"""
        if event_type:
            filtered = [e for e in self._event_history if e.type == event_type]
            return filtered[-limit:]
        return self._event_history[-limit:]

# Глобальный экземпляр
event_bus = EventBus()
```

**Использование:**
```python
# src/core/services/trade_executor.py
from ..event_bus import event_bus
from ..events import TradeEvent, EventType

class TradeExecutor:
    def execute_trade(self, signal: TradeSignal) -> bool:
        try:
            result = self._send_order(signal)
            
            if result:
                # Публикация события об открытии сделки
                event = TradeEvent(
                    type=EventType.TRADE_OPENED,
                    source="TradeExecutor",
                    symbol=signal.symbol,
                    lot=signal.lot,
                    order_type=signal.type.name,
                    price=self._get_current_price(signal.symbol),
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    strategy_name=signal.strategy_name
                )
                event_bus.publish(event)
            
            return result
            
        except Exception as e:
            # Публикация события об ошибке
            event = Event(
                type=EventType.ERROR_OCCURRED,
                source="TradeExecutor",
                data={"error": str(e), "signal": signal.dict()}
            )
            event_bus.publish(event)
            raise

# src/core/orchestrator.py
from .event_bus import event_bus
from .events import EventType, MarketRegimeEvent

class Orchestrator:
    def __init__(self, ...):
        # Подписка на события
        event_bus.subscribe(
            EventType.MARKET_REGIME_CHANGED,
            self._on_regime_changed
        )
        event_bus.subscribe(
            EventType.CONCEPT_DRIFT_DETECTED,
            self._on_drift_detected
        )
    
    def _on_regime_changed(self, event: MarketRegimeEvent):
        logger.info(f"Режим рынка изменился: {event.old_regime} → {event.new_regime}")
        # Запуск перераспределения капитала
        self.run_cycle()
    
    def _on_drift_detected(self, event: Event):
        logger.warning("Обнаружен дрейф концепции!")
        # Запуск R&D цикла
        self.trading_system.force_rd_cycle()
```

**Критерии приемки:**
- [ ] Event Bus реализован
- [ ] Поддержка синхронных и асинхронных подписчиков
- [ ] История событий
- [ ] Все компоненты используют Event Bus

**Оценка:** 32 часа

---

### 3.3 CQRS для чтения/записи (Неделя 9-10)

#### 🟡 Задача 2.3.1: Разделение операций чтения и записи

**Файлы:** `src/db/query_manager.py` (новый), `src/db/command_manager.py` (новый)

```python
# src/db/query_manager.py
"""CQRS: Query side - только чтение"""

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime

class QueryManager:
    """Менеджер запросов (только чтение)"""
    
    def __init__(self, session_factory):
        self.session_factory = session_factory
    
    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """Получение истории сделок"""
        with self.session_factory() as session:
            query = select(TradeHistory)
            
            if symbol:
                query = query.where(TradeHistory.symbol == symbol)
            if start_date:
                query = query.where(TradeHistory.open_time >= start_date)
            if end_date:
                query = query.where(TradeHistory.open_time <= end_date)
            
            query = query.order_by(TradeHistory.open_time.desc()).limit(limit)
            
            results = session.execute(query).scalars().all()
            
            return pd.DataFrame([{
                'id': r.id,
                'symbol': r.symbol,
                'open_time': r.open_time,
                'close_time': r.close_time,
                'type': r.type,
                'lot': r.lot,
                'entry_price': r.entry_price,
                'exit_price': r.exit_price,
                'profit': r.profit,
                'strategy_name': r.strategy_name
            } for r in results])
    
    def get_strategy_statistics(self, strategy_name: str) -> Dict:
        """Статистика стратегии"""
        with self.session_factory() as session:
            query = select(
                func.count(TradeHistory.id).label('total_trades'),
                func.sum(TradeHistory.profit).label('total_profit'),
                func.avg(TradeHistory.profit).label('avg_profit'),
                func.max(TradeHistory.profit).label('max_profit'),
                func.min(TradeHistory.profit).label('max_loss'),
                func.sum(case((TradeHistory.profit > 0, 1), else_=0)).label('wins'),
                func.sum(case((TradeHistory.profit <= 0, 1), else_=0)).label('losses')
            ).where(TradeHistory.strategy_name == strategy_name)
            
            result = session.execute(query).one()
            
            total_trades = result.total_trades
            win_rate = result.wins / total_trades if total_trades > 0 else 0
            
            return {
                'total_trades': total_trades,
                'total_profit': result.total_profit or 0,
                'avg_profit': result.avg_profit or 0,
                'max_profit': result.max_profit or 0,
                'max_loss': result.max_loss or 0,
                'win_rate': win_rate,
                'profit_factor': abs(result.wins / result.losses) if result.losses > 0 else float('inf')
            }
    
    def get_portfolio_metrics(self) -> Dict:
        """Метрики портфеля"""
        with self.session_factory() as session:
            # Общая прибыль
            total_profit_query = select(func.sum(TradeHistory.profit))
            total_profit = session.execute(total_profit_query).scalar() or 0
            
            # Прибыль по стратегиям
            strategy_profit_query = select(
                TradeHistory.strategy_name,
                func.sum(TradeHistory.profit).label('profit')
            ).group_by(TradeHistory.strategy_name)
            strategy_profit = {r.strategy_name: r.profit for r in session.execute(strategy_profit_query)}
            
            # Прибыль по символам
            symbol_profit_query = select(
                TradeHistory.symbol,
                func.sum(TradeHistory.profit).label('profit')
            ).group_by(TradeHistory.symbol)
            symbol_profit = {r.symbol: r.profit for r in session.execute(symbol_profit_query)}
            
            return {
                'total_profit': total_profit,
                'strategy_profit': strategy_profit,
                'symbol_profit': symbol_profit
            }

# src/db/command_manager.py
"""CQRS: Command side - только запись"""

from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime

class CommandManager:
    """Менеджер команд (только запись)"""
    
    def __init__(self, session_factory):
        self.session_factory = session_factory
    
    def create_trade(self, trade_data: Dict[str, Any]) -> int:
        """Создание записи о сделке"""
        with self.session_factory() as session:
            trade = TradeHistory(
                symbol=trade_data['symbol'],
                open_time=trade_data.get('open_time', datetime.utcnow()),
                type=trade_data['type'],
                lot=trade_data['lot'],
                entry_price=trade_data['entry_price'],
                stop_loss=trade_data.get('stop_loss'),
                take_profit=trade_data.get('take_profit'),
                strategy_name=trade_data.get('strategy_name'),
                comment=trade_data.get('comment')
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade.id
    
    def update_trade_close(
        self,
        trade_id: int,
        exit_price: float,
        close_time: datetime,
        profit: float,
        close_reason: str
    ):
        """Обновление сделки при закрытии"""
        with self.session_factory() as session:
            trade = session.get(TradeHistory, trade_id)
            if trade:
                trade.exit_price = exit_price
                trade.close_time = close_time
                trade.profit = profit
                trade.close_reason = close_reason
                session.commit()
    
    def create_audit_log(self, audit_data: Dict[str, Any]) -> int:
        """Создание записи audit лога"""
        with self.session_factory() as session:
            audit = TradeAudit(**audit_data)
            session.add(audit)
            session.commit()
            return audit.id
```

**Критерии приемки:**
- [ ] QueryManager только для чтения
- [ ] CommandManager только для записи
- [ ] Оптимизированные запросы
- [ ] Возврат pandas DataFrame для аналитики

**Оценка:** 24 часа

---

## 4. ФАЗА 3: ТЕСТИРОВАНИЕ И НАДЕЖНОСТЬ (Недели 11-14)

### 4.1 Unit тесты (Неделя 11-12)

#### 🟡 Задача 3.1.1: Покрытие unit тестами

**Структура тестов:**
```
tests/
├── __init__.py
├── conftest.py              # Фикстуры pytest
├── unit/
│   ├── test_risk_engine.py
│   ├── test_consensus_engine.py
│   ├── test_market_regime.py
│   ├── test_feature_engineer.py
│   ├── test_orchestrator_env.py
│   └── test_drift_detector.py
├── integration/
│   ├── test_trading_system.py
│   ├── test_orchestrator.py
│   └── test_event_bus.py
└── e2e/
    └── test_full_trading_cycle.py
```

**Пример теста:**
```python
# tests/unit/test_risk_engine.py
import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, MagicMock
from src.risk.risk_engine import RiskEngine
from src.core.config_models import Settings
from src.data_models import SignalType

@pytest.fixture
def mock_config():
    config = Mock(spec=Settings)
    config.RISK_PERCENTAGE = 0.5
    config.STOP_LOSS_ATR_MULTIPLIER = 2.0
    config.MAX_PORTFOLIO_VAR_PERCENT = 5.0
    config.CORRELATION_THRESHOLD = 0.7
    config.risk = Mock()
    config.risk.confidence_risk_map = {"low": 0.5, "medium": 1.0, "high": 1.5}
    return config

@pytest.fixture
def mock_trading_system():
    ts = Mock()
    ts._get_current_market_regime_name.return_value = "Strong Trend"
    ts.strategies = [Mock(__class__.__name__="BreakoutStrategy")]
    return ts

@pytest.fixture
def risk_engine(mock_config, mock_trading_system):
    return RiskEngine(
        config=mock_config,
        trading_system_ref=mock_trading_system,
        is_simulation=True
    )

class TestRiskEngine:
    def test_calculate_position_size_basic(self, risk_engine):
        """Тест базового расчета размера позиции"""
        # Arrange
        symbol = "EURUSD"
        df = pd.DataFrame({
            'close': [1.1000] * 100,
            'ATR_14': [0.0010] * 100
        })
        account_info = Mock()
        account_info.balance = 100000
        
        # Act
        lot_size, stop_loss = risk_engine.calculate_position_size(
            symbol=symbol,
            df=df,
            account_info=account_info,
            trade_type=SignalType.BUY,
            confidence='medium',
            strategy_name="BreakoutStrategy"
        )
        
        # Assert
        assert lot_size is not None
        assert lot_size > 0
        assert stop_loss is not None
        assert stop_loss > 0
    
    def test_position_size_zero_allocation(self, risk_engine):
        """Тест блокировки при нулевой аллокации"""
        # Arrange
        risk_engine.capital_allocation = {
            "Strong Trend": {"BreakoutStrategy": 0.0}  # Нулевая аллокация
        }
        
        # Act
        lot_size, stop_loss = risk_engine.calculate_position_size(
            symbol="EURUSD",
            df=pd.DataFrame({'close': [1.1]*100, 'ATR_14': [0.001]*100}),
            account_info=Mock(balance=100000),
            trade_type=SignalType.BUY,
            strategy_name="BreakoutStrategy"
        )
        
        # Assert
        assert lot_size is None
        assert stop_loss is None
    
    def test_diversity_reward_calculation(self, risk_engine):
        """Тест расчета бонуса за разнообразие"""
        # Arrange
        regime_allocations = {
            "Strong Trend": {
                "AI_Model": 0.4,
                "BreakoutStrategy": 0.3,
                "MeanReversionStrategy": 0.3
            }
        }
        
        # Act
        reward = risk_engine.calculate_diversity_reward(regime_allocations)
        
        # Assert
        assert 0.0 <= reward <= 1.0
```

**Фикстуры:**
```python
# tests/conftest.py
import pytest
from unittest.mock import Mock
from src.core.event_bus import EventBus
from src.db.database_manager import DatabaseManager

@pytest.fixture
def event_bus():
    """Фикстура для Event Bus"""
    bus = EventBus()
    yield bus
    # Очистка после теста
    bus._subscribers.clear()
    bus._async_subscribers.clear()

@pytest.fixture
def mock_db_session():
    """Фикстура для мок сессии БД"""
    session = Mock()
    session.execute = Mock(return_value=Mock())
    session.commit = Mock()
    session.rollback = Mock()
    return session

@pytest.fixture
def sample_market_data():
    """Фикстура с примером рыночных данных"""
    import pandas as pd
    import numpy as np
    
    dates = pd.date_range('2024-01-01', periods=500, freq='H')
    np.random.seed(42)
    
    return pd.DataFrame({
        'open': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001),
        'high': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001) + 0.0005,
        'low': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001) - 0.0005,
        'close': 1.1000 + np.cumsum(np.random.randn(500) * 0.0001),
        'volume': np.random.randint(100, 1000, 500)
    }, index=dates)
```

**Критерии приемки:**
- [ ] Покрытие unit тестами > 70%
- [ ] Все критические компоненты покрыты
- [ ] Тесты изолированы (моки внешних зависимостей)
- [ ] Время выполнения всех unit тестов < 2 минут

**Оценка:** 40 часов

---

### 4.2 Integration тесты (Неделя 13-14)

#### 🟡 Задача 3.2.1: Интеграционные тесты

```python
# tests/integration/test_trading_system.py
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.core.trading_system_core import TradingSystemCore
from src.core.config_models import Settings
from src.data_models import SignalType, TradeSignal

@pytest.fixture
def test_config():
    config = Settings()
    config.MT5_LOGIN = 12345678
    config.MT5_PASSWORD = "test_password"
    config.MT5_SERVER = "Test-Demo"
    config.RISK_PERCENTAGE = 0.5
    return config

@pytest.fixture
def trading_system(test_config):
    """Создание торговойвой системы для тестов"""
    with patch('src.core.trading_system_core.DatabaseManager'):
        with patch('src.core.trading_system_core.MetaTrader5'):
            ts = TradingSystemCore(config=test_config)
            yield ts
            ts.stop()

class TestTradingSystemIntegration:
    @pytest.mark.asyncio
    async def test_full_trade_cycle(self, trading_system):
        """Тест полного цикла торговли"""
        # Arrange
        test_signal = TradeSignal(
            type=SignalType.BUY,
            symbol="EURUSD",
            lot=0.1,
            confidence=0.75,
            strategy_name="BreakoutStrategy"
        )
        
        # Act
        # 1. Запуск системы
        trading_system.start()
        await asyncio.sleep(2)  # Даем системе запуститься
        
        # 2. Проверка инициализации
        assert trading_system.running is True
        assert trading_system.db_manager is not None
        assert trading_system.risk_engine is not None
        
        # 3. Исполнение сделки
        result = trading_system.trading.execute_trade(test_signal)
        
        # 4. Проверка результата
        assert result is True
        
        # 5. Проверка audit лога
        audit_logs = trading_system.db_manager.get_audit_logs(limit=1)
        assert len(audit_logs) == 1
        assert audit_logs[0].execution_status == 'EXECUTED'
        
        # Act: Закрытие сделки
        trading_system.trading.close_position(position_id=1, profit=50.0)
        
        # Assert: Проверка закрытия
        closed_trades = trading_system.db_manager.get_closed_trades(limit=1)
        assert len(closed_trades) == 1
        assert closed_trades[0].profit == 50.0
        
        # Cleanup
        trading_system.stop()
    
    @pytest.mark.asyncio
    async def test_risk_checks_block_trade(self, trading_system):
        """Тест блокировки сделки проверками риска"""
        # Arrange
        # Устанавливаем лимиты так, чтобы сделка была заблокирована
        trading_system.risk_engine.max_daily_drawdown_percent = 0.001  # Очень низкий лимит
        
        # Имитируем превышение дневного лимита
        with patch.object(trading_system.risk_engine, 'check_daily_drawdown', return_value=False):
            test_signal = TradeSignal(
                type=SignalType.BUY,
                symbol="EURUSD",
                lot=0.1,
                confidence=0.75
            )
            
            # Act
            result = trading_system.trading.execute_trade(test_signal)
            
            # Assert: Сделка должна быть заблокирована
            assert result is False
            
            # Проверка audit лога
            audit_logs = trading_system.db_manager.get_audit_logs(limit=1)
            assert audit_logs[0].execution_status == 'REJECTED'
            assert 'drawdown' in audit_logs[0].rejection_reason.lower()
    
    @pytest.mark.asyncio
    async def test_orchestrator_regime_change(self, trading_system):
        """Тест реакции оркестратора на смену режима"""
        # Arrange
        trading_system.start()
        await asyncio.sleep(2)
        
        initial_allocation = trading_system.risk_engine.capital_allocation.copy()
        
        # Act: Имитация смены режима
        with patch.object(trading_system, '_get_current_market_regime_name', return_value="High Volatility Range"):
            # Запуск цикла оркестратора
            trading_system.orchestrator.run_cycle()
            await asyncio.sleep(1)
        
        # Assert: Аллокация должна измениться
        new_allocation = trading_system.risk_engine.capital_allocation
        assert new_allocation != initial_allocation
```

**Критерии приемки:**
- [ ] Integration тесты для основных сценариев
- [ ] Тесты с реальной БД (SQLite test)
- [ ] Тесты с моками MT5
- [ ] Время выполнения < 10 минут

**Оценка:** 32 часа

---

## 5. ФАЗА 4: ПРОИЗВОДИТЕЛЬНОСТЬ (Недели 15-18)

### 5.1 Кэширование (Неделя 15-16)

#### 🟡 Задача 4.1.1: Многоуровневое кэширование

**Файлы:** `src/utils/cache_manager.py` (новый)

```python
# src/utils/cache_manager.py
import asyncio
import time
from functools import wraps
from typing import Any, Callable, Optional, Dict
from collections import OrderedDict
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

class CacheEntry:
    """Элемент кэша"""
    def __init__(self, value: Any, ttl: Optional[float] = None):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl  # Time to live в секундах
    
    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl

class LRUCache:
    """LRU кэш с TTL поддержкой"""
    def __init__(self, max_size: int = 1000):
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            self.misses += 1
            return None
        
        entry = self.cache[key]
        if entry.is_expired():
            del self.cache[key]
            self.misses += 1
            return None
        
        # Перемещение в конец (использовалось недавно)
        self.cache.move_to_end(key)
        self.hits += 1
        return entry.value
    
    def put(self, key: str, value: Any, ttl: Optional[float] = None):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = CacheEntry(value, ttl)
        
        if len(self.cache) > self.max_size:
            # Удаление наименее используемого
            self.cache.popitem(last=False)
    
    def clear(self):
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    def stats(self) -> Dict:
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            'size': len(self.cache),
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': f"{hit_rate:.2f}%"
        }

# Глобальные кэши
market_regime_cache = LRUCache(max_size=50)  # Кэш режимов рынка
pre_mortem_cache = LRUCache(max_size=100)    # Кэш Pre-Mortem анализа
vector_search_cache = LRUCache(max_size=200) # Кэш векторного поиска

def cache_result(cache: LRUCache, ttl: Optional[float] = None):
    """Декоратор для кэширования результатов функций"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Генерация ключа кэша
            key_data = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True, default=str)
            cache_key = hashlib.md5(key_data.encode()).hexdigest()
            
            # Проверка кэша
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Кэш хит для {func.__name__}")
                return cached_value
            
            # Вызов функции
            logger.debug(f"Кэш мисс для {func.__name__}")
            result = await func(*args, **kwargs)
            
            # Сохранение в кэш
            cache.put(cache_key, result, ttl)
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Генерация ключа кэша
            key_data = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True, default=str)
            cache_key = hashlib.md5(key_data.encode()).hexdigest()
            
            # Проверка кэша
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Кэш хит для {func.__name__}")
                return cached_value
            
            # Вызов функции
            logger.debug(f"Кэш мисс для {func.__name__}")
            result = func(*args, **kwargs)
            
            # Сохранение в кэш
            cache.put(cache_key, result, ttl)
            return result
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

# Пример использования
class MarketRegimeManager:
    @cache_result(market_regime_cache, ttl=60)  # Кэш на 1 минуту
    def get_regime(self, df: pd.DataFrame, symbol: str) -> str:
        """Определение режима рынка с кэшированием"""
        # Тяжелые вычисления...
        return regime

class RiskEngine:
    @cache_result(pre_mortem_cache, ttl=300)  # Кэш на 5 минут
    def run_pre_mortem_analysis(self, symbol: str, timeframe: str, params: dict) -> bool:
        """Pre-Mortem анализ с кэшированием"""
        # GARCH Monte Carlo симуляции...
        return result

class VectorDBManager:
    @cache_result(vector_search_cache, ttl=600)  # Кэш на 10 минут
    def query_similar(self, query_embedding: list, n_results: int = 5) -> dict:
        """Векторный поиск с кэшированием"""
        # FAISS поиск...
        return results
```

**Критерии приемки:**
- [ ] LRU кэш реализован
- [ ] Поддержка TTL
- [ ] Декоратор для кэширования
- [ ] Статистика хитов/миссов
- [ ] Кэширование горячих путей

**Оценка:** 20 часов

---

### 5.2 Асинхронность (Неделя 17-18)

#### 🟡 Задача 4.2.1: Асинхронные операции I/O

```python
# src/data/data_provider_async.py
import asyncio
import aiohttp
import asyncpg
from typing import List, Dict, Optional
import pandas as pd

class AsyncDataProvider:
    """Асинхронный провайдер данных"""
    
    def __init__(self, config):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.db_pool: Optional[asyncpg.Pool] = None
    
    async def initialize(self):
        """Инициализация сессий"""
        self.session = aiohttp.ClientSession()
        self.db_pool = await asyncpg.create_pool(
            self.config.DATABASE_URL,
            min_size=5,
            max_size=20
        )
    
    async def close(self):
        """Закрытие сессий"""
        if self.session:
            await self.session.close()
        if self.db_pool:
            await self.db_pool.close()
    
    async def fetch_historical_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """Асинхронное получение исторических данных"""
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT timestamp, open, high, low, close, volume
                FROM market_data
                WHERE symbol = $1 AND timeframe = $2
                AND timestamp BETWEEN $3 AND $4
                ORDER BY timestamp ASC
            """
            rows = await conn.fetch(query, symbol, timeframe, start_date, end_date)
            
            return pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    async def fetch_news_batch(self, symbols: List[str]) -> List[Dict]:
        """Асинхронная загрузка новостей для нескольких символов"""
        async def fetch_symbol_news(symbol: str):
            url = f"https://api.news.com/symbol/{symbol}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                return []
        
        # Параллельная загрузка для всех символов
        tasks = [fetch_symbol_news(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Объединение результатов
        all_news = []
        for result in results:
            if isinstance(result, list):
                all_news.extend(result)
        
        return all_news
    
    async def get_multiple_symbols_data(
        self,
        symbols: List[str],
        timeframe: str = "H1"
    ) -> Dict[str, pd.DataFrame]:
        """Параллельное получение данных для нескольких символов"""
        async def fetch_symbol(symbol: str):
            return symbol, await self.fetch_historical_data(
                symbol, timeframe,
                start_date="2024-01-01",
                end_date="2024-12-31"
            )
        
        tasks = [fetch_symbol(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        data_dict = {}
        for result in results:
            if isinstance(result, tuple):
                symbol, df = result
                data_dict[symbol] = df
        
        return data_dict

# Использование в TradingSystem
class TradingSystemCore:
    async def update_market_data(self):
        """Асинхронное обновление рыночных данных"""
        symbols = self.config.SYMBOLS_WHITELIST
        
        # Параллельное получение данных
        data_dict = await self.data_provider.get_multiple_symbols_data(symbols)
        
        # Обновление матриц корреляции
        self.risk_engine.update_correlation_matrix(data_dict)
    
    async def fetch_and_process_news(self):
        """Асинхронная загрузка и обработка новостей"""
        symbols = self.config.SYMBOLS_WHITELIST
        
        # Параллельная загрузка
        news_list = await self.data_provider.fetch_news_batch(symbols)
        
        # Обработка в фоне
        for news in news_list:
            asyncio.create_task(self.process_news_item(news))
```

**Критерии приемки:**
- [ ] aiohttp для HTTP запросов
- [ ] asyncpg для БД
- [ ] asyncio.gather для параллелизма
- [ ] Неблокирующий I/O

**Оценка:** 28 часов

---

## 6. ФАЗА 5: PRODUCTION-READY (Недели 19-24)

### 6.1 Контейнеризация (Неделя 19-20)

#### 🟢 Задача 5.1.1: Docker контейнер

**Файлы:** `Dockerfile`, `docker-compose.yml`

```dockerfile
# Dockerfile
FROM python:3.10-slim

# Рабочая директория
WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    cmake \
    libatlas-base-dev \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Порты
EXPOSE 8000  # FastAPI
EXPOSE 8080  # Мониторинг

# Команда запуска
CMD ["python", "main_pyside.py"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  trading-system:
    build: .
    container_name: genesis-trading
    environment:
      - MT5_LOGIN=${MT5_LOGIN}
      - MT5_PASSWORD=${MT5_PASSWORD}
      - MT5_SERVER=${MT5_SERVER}
      - DATABASE_URL=postgresql://user:password@db:5432/trading
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
    volumes:
      - ./logs:/app/logs
      - ./database:/app/database
      - ./configs:/app/configs
    ports:
      - "8000:8000"
      - "8080:8080"
    depends_on:
      - db
      - redis
    restart: unless-stopped
    networks:
      - trading-network
  
  db:
    image: postgres:14
    container_name: genesis-db
    environment:
      - POSTGRES_DB=trading
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    networks:
      - trading-network
  
  redis:
    image: redis:7-alpine
    container_name: genesis-redis
    ports:
      - "6379:6379"
    networks:
      - trading-network
  
  prometheus:
    image: prom/prometheus:latest
    container_name: genesis-prometheus
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    networks:
      - trading-network
  
  grafana:
    image: grafana/grafana:latest
    container_name: genesis-grafana
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
    networks:
      - trading-network

volumes:
  postgres_data:
  prometheus_data:
  grafana_data:

networks:
  trading-network:
    driver: bridge
```

**Критерии приемки:**
- [ ] Dockerfile собран
- [ ] docker-compose поднимает все сервисы
- [ ] Persist volume для БД
- [ ] Сеть изолирована

**Оценка:** 16 часов

---

### 6.2 Мониторинг (Неделя 21-22)

#### 🟢 Задача 5.2.1: Prometheus метрики

**Файлы:** `src/monitoring/metrics.py` (новый)

```python
# src/monitoring/metrics.py
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import time
from functools import wraps

# Метрики
TRADES_TOTAL = Counter(
    'trades_total',
    'Total number of trades executed',
    ['symbol', 'strategy', 'type']
)

TRADES_PNL = Histogram(
    'trades_pnl',
    'Trade PnL distribution',
    ['symbol', 'strategy'],
    buckets=[-100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100, 200, 500, 1000]
)

ACCOUNT_BALANCE = Gauge(
    'account_balance',
    'Current account balance'
)

ACCOUNT_EQUITY = Gauge(
    'account_equity',
    'Current account equity'
)

PORTFOLIO_VAR = Gauge(
    'portfolio_var',
    'Portfolio Value at Risk (99%)'
)

OPEN_POSITIONS = Gauge(
    'open_positions',
    'Number of open positions',
    ['symbol']
)

MARKET_REGIME = Gauge(
    'market_regime',
    'Current market regime',
    ['regime']
)

MODEL_INFERENCE_TIME = Histogram(
    'model_inference_seconds',
    'Model inference time',
    ['model_name']
)

RISK_CHECK_DURATION = Histogram(
    'risk_check_seconds',
    'Risk check duration',
    ['check_type']
)

SYSTEM_HEALTH = Gauge(
    'system_health',
    'System health status (1=healthy, 0=unhealthy)',
    ['component']
)

def track_trade(symbol: str, strategy: str, trade_type: str, pnl: float):
    """Декоратор для трекинга сделок"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            
            TRADES_TOTAL.labels(
                symbol=symbol,
                strategy=strategy,
                type=trade_type
            ).inc()
            
            TRADES_PNL.labels(
                symbol=symbol,
                strategy=strategy
            ).observe(pnl)
            
            return result
        return wrapper
    return decorator

def start_metrics_server(port: int = 8080):
    """Запуск сервера метрик"""
    start_http_server(port)
```

**Использование:**
```python
# src/core/trading_system_core.py
from ..monitoring.metrics import (
    ACCOUNT_BALANCE, ACCOUNT_EQUITY, PORTFOLIO_VAR,
    OPEN_POSITIONS, MARKET_REGIME, SYSTEM_HEALTH,
    track_trade
)

class TradingSystemCore:
    def __init__(self):
        # Инициализация метрик
        SYSTEM_HEALTH.labels(component='TradingSystem').set(1)
        SYSTEM_HEALTH.labels(component='RiskEngine').set(1)
        SYSTEM_HEALTH.labels(component='Orchestrator').set(1)
    
    @track_trade(symbol="EURUSD", strategy="AI_Model", trade_type="BUY", pnl=50.0)
    def execute_trade(self, signal):
        ...
    
    def update_metrics(self):
        """Обновление метрик"""
        account_info = self.get_account_info()
        if account_info:
            ACCOUNT_BALANCE.set(account_info.balance)
            ACCOUNT_EQUITY.set(account_info.equity)
        
        var = self.risk_engine.calculate_portfolio_var(...)
        if var:
            PORTFOLIO_VAR.set(var * 100)  # В процентах
        
        regime = self._get_current_market_regime_name()
        MARKET_REGIME.labels(regime=regime).set(1)
        
        for symbol, count in self.get_positions_by_symbol().items():
            OPEN_POSITIONS.labels(symbol=symbol).set(count)
```

**Grafana дашборд:**
```json
{
  "dashboard": {
    "title": "Genesis Trading System",
    "panels": [
      {
        "title": "Account Balance & Equity",
        "targets": [
          {"expr": "account_balance"},
          {"expr": "account_equity"}
        ]
      },
      {
        "title": "Portfolio VaR",
        "targets": [
          {"expr": "portfolio_var"}
        ],
        "alert": {
          "condition": "gt",
          "threshold": 5.0
        }
      },
      {
        "title": "Trades PnL",
        "targets": [
          {"expr": "sum(trades_pnl_sum)"}
        ]
      },
      {
        "title": "System Health",
        "targets": [
          {"expr": "system_health"}
        ]
      }
    ]
  }
}
```

**Критерии приемки:**
- [ ] Prometheus метрики экспортируются
- [ ] Grafana дашборд настроен
- [ ] Алёрты на критичные метрики
- [ ] Health checks

**Оценка:** 24 часа

---

### 6.3 Документация (Неделя 23-24)

#### 🟢 Задача 5.3.1: API документация (OpenAPI)

```python
# src/web/server.py
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html

app = FastAPI(
    title="Genesis Trading System API",
    description="API для управления торговой системой Genesis",
    version="13.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.get("/", tags=["Health"])
async def root():
    """
    Проверка здоровья системы
    """
    return {"status": "healthy", "version": "13.0.0"}

@app.post("/api/trade", tags=["Trading"])
async def execute_trade(request: TradeRequest):
    """
    Исполнение торговой сделки
    
    - **symbol**: Торговый инструмент (6 букв)
    - **lot**: Объем сделки
    - **order_type**: BUY или SELL
    - **stop_loss**: Стоп-лосс (опционально)
    - **take_profit**: Тейк-профит (опционально)
    """
    ...

@app.get("/api/positions", tags=["Trading"])
async def get_positions():
    """
    Получение списка открытых позиций
    """
    ...

@app.get("/api/metrics", tags=["Monitoring"])
async def get_metrics():
    """
    Получение метрик системы
    """
    ...
```

**Критерии приемки:**
- [ ] OpenAPI спецификация
- [ ] Swagger UI доступен
- [ ] Документация всех эндпоинтов
- [ ] Примеры запросов

**Оценка:** 16 часов

---

## 7. ДОРОЖНАЯ КАРТА

```
┌─────────────────────────────────────────────────────────────────┐
│                        2026 ГОД                                 │
├────────────┬────────────┬────────────┬────────────┬────────────┤
│   Апрель   │    Май     │   Июнь     │   Июль     │   Август   │
├────────────┼────────────┼────────────┼────────────┼────────────┤
│ Фаза 1     │ Фаза 2     │ Фаза 3     │ Фаза 4     │ Фаза 5     │
│ Критические│ Архитектура│ Тесты      │ Произв-сть │ Production │
│ улучшения  │            │            │            │            │
│            │            │            │            │            │
│ ─────────  │ ─────────  │ ─────────  │ ─────────  │ ─────────  │
│ • Безопас- │ • DI       │ • Unit     │ • Кэширо-  │ • Docker   │
│   ность    │ • События  │ • Integr.  │   вание    │ • Монито-  │
│ • Модули   │ • CQRS     │ • E2E      │ • Async    │   ринг     │
│            │            │            │            │ • Docs     │
└────────────┴────────────┴────────────┴────────────┴────────────┘

Вехи:
✓ 30 апреля: Безопасность завершена
✓ 15 июня: Архитектура завершена
✓ 15 июля: Тесты > 70%
✓ 15 августа: Production готов
```

---

## 8. МЕТРИКИ УСПЕХА

### 8.1 Технические метрики

| Метрика | Текущее | Целевое | Приоритет |
|---------|---------|---------|-----------|
| Покрытие тестами | 30% | > 70% | Высокий |
| Строк в largest файле | 3300 | < 1000 | Высокий |
| Время отклика API | 500ms | < 100ms | Средний |
| Hit rate кэша | 0% | > 80% | Средний |
| Время запуска системы | 60s | < 30s | Низкий |

### 8.2 Бизнес-метрики

| Метрика | Текущее | Целевое |
|---------|---------|---------|
| Sharpe Ratio | 1.8 | > 2.0 |
| Max Drawdown | 15% | < 10% |
| Win Rate | 58% | > 60% |
| Profit Factor | 1.5 | > 2.0 |

### 8.3 Метрики качества кода

```
✓ Cyclomatic complexity < 10
✓ Maintainability index > 65
✓ Code duplication < 5%
✓ Technical debt ratio < 5%
```

---

## 📊 ИТОГОВАЯ СВОДКА

| Фаза | Длительность | Часов | Критичность |
|------|--------------|-------|-------------|
| Фаза 1 | 4 недели | 82 | 🔴 |
| Фаза 2 | 6 недель | 120 | 🔴 |
| Фаза 3 | 4 недели | 72 | 🟡 |
| Фаза 4 | 4 недели | 48 | 🟡 |
| Фаза 5 | 6 недель | 56 | 🟢 |
| **ВСЕГО** | **24 недели** | **378 часов** | |

**Ресурсы:**
- 1 разработчик: ~6 месяцев
- 2 разработчика: ~3 месяца
- 3 разработчика: ~2 месяца

**ROI:**
- Текущая оценка: 7.5/10
- Целевая оценка: 9.0/10
- Увеличение надежности: +40%
- Снижение рисков: +60%

---

*Документ составлен: 27 марта 2026*  
*Следующий пересмотр: 1 апреля 2026*
