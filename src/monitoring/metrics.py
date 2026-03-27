# src/monitoring/metrics.py
"""
Prometheus метрики для Genesis Trading System.

Метрики:
- Торговые операции (trades)
- Производительность (performance)
- Риск (risk)
- Система (system)
"""

from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from functools import wraps
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ===========================================
# Trade Metrics
# ===========================================

TRADES_TOTAL = Counter(
    'trades_total',
    'Total number of trades executed',
    ['symbol', 'strategy', 'type']
)

TRADES_PNL = Histogram(
    'trades_pnl',
    'Trade PnL distribution',
    ['symbol', 'strategy'],
    buckets=[-100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100, 200, 500, 1000, float('inf')]
)

TRADES_DURATION = Summary(
    'trade_duration_seconds',
    'Trade duration in seconds',
    ['symbol', 'strategy']
)


# ===========================================
# Account Metrics
# ===========================================

ACCOUNT_BALANCE = Gauge(
    'account_balance',
    'Current account balance'
)

ACCOUNT_EQUITY = Gauge(
    'account_equity',
    'Current account equity'
)

ACCOUNT_MARGIN_USED = Gauge(
    'account_margin_used',
    'Current margin used'
)

ACCOUNT_MARGIN_FREE = Gauge(
    'account_margin_free',
    'Current free margin'
)

ACCOUNT_MARGIN_LEVEL = Gauge(
    'account_margin_level',
    'Current margin level percentage'
)


# ===========================================
# Risk Metrics
# ===========================================

PORTFOLIO_VAR = Gauge(
    'portfolio_var',
    'Portfolio Value at Risk (99%)'
)

DAILY_DRAWDOWN = Gauge(
    'daily_drawdown',
    'Current daily drawdown percentage'
)

OPEN_POSITIONS = Gauge(
    'open_positions',
    'Number of open positions',
    ['symbol']
)

RISK_EXPOSURE = Gauge(
    'risk_exposure',
    'Current risk exposure',
    ['symbol', 'type']
)


# ===========================================
# Market Metrics
# ===========================================

MARKET_REGIME = Gauge(
    'market_regime',
    'Current market regime',
    ['regime']
)

VOLATILITY_INDEX = Gauge(
    'volatility_index',
    'Current volatility index',
    ['symbol']
)


# ===========================================
# ML Metrics
# ===========================================

MODEL_INFERENCE_TIME = Histogram(
    'model_inference_seconds',
    'Model inference time',
    ['model_name']
)

MODEL_ACCURACY = Gauge(
    'model_accuracy',
    'Model accuracy',
    ['model_name', 'symbol']
)

PREDICTION_CONFIDENCE = Gauge(
    'prediction_confidence',
    'Prediction confidence score',
    ['model_name', 'symbol']
)

CONCEPT_DRIFT_SCORE = Gauge(
    'concept_drift_score',
    'Concept drift detection score',
    ['model_name', 'symbol']
)


# ===========================================
# System Metrics
# ===========================================

SYSTEM_HEALTH = Gauge(
    'system_health',
    'System health status (1=healthy, 0=unhealthy)',
    ['component']
)

MEMORY_USAGE = Gauge(
    'memory_usage_bytes',
    'Memory usage in bytes'
)

CPU_USAGE = Gauge(
    'cpu_usage_percent',
    'CPU usage percentage'
)

EVENT_BUS_EVENTS = Counter(
    'event_bus_events_total',
    'Total events published',
    ['event_type']
)

CACHE_HITS = Counter(
    'cache_hits_total',
    'Total cache hits',
    ['cache_name']
)

CACHE_MISSES = Counter(
    'cache_misses_total',
    'Total cache misses',
    ['cache_name']
)


# ===========================================
# Strategy Metrics
# ===========================================

STRATEGY_PERFORMANCE = Gauge(
    'strategy_performance',
    'Strategy performance metrics',
    ['strategy', 'metric']
)

STRATEGY_SIGNALS = Counter(
    'strategy_signals_total',
    'Total signals generated',
    ['strategy', 'signal_type']
)


# ===========================================
# Decorators
# ===========================================

def track_trade(symbol: str, strategy: str, trade_type: str):
    """
    Декоратор для трекинга сделок.
    
    Example:
        @track_trade(symbol="EURUSD", strategy="BreakoutStrategy", trade_type="BUY")
        def execute_trade(signal):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                
                # Increment trade counter
                TRADES_TOTAL.labels(
                    symbol=symbol,
                    strategy=strategy,
                    type=trade_type
                ).inc()
                
                return result
                
            except Exception as e:
                logger.error(f"Trade failed: {e}")
                raise
                
            finally:
                duration = time.time() - start_time
                TRADES_DURATION.labels(
                    symbol=symbol,
                    strategy=strategy
                ).observe(duration)
        
        return wrapper
    return decorator


def track_inference(model_name: str):
    """
    Декоратор для трекинга ML inference.
    
    Example:
        @track_inference(model_name="LSTM_PyTorch")
        def predict(model, data):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                MODEL_INFERENCE_TIME.labels(
                    model_name=model_name
                ).observe(duration)
        
        return wrapper
    return decorator


# ===========================================
# Utility Functions
# ===========================================

def start_metrics_server(port: int = 8080) -> None:
    """
    Запуск сервера метрик Prometheus.
    
    Args:
        port: Порт для сервера метрик
    """
    start_http_server(port)
    logger.info(f"Metrics server started on port {port}")


def update_account_metrics(
    balance: float,
    equity: float,
    margin_used: float,
    margin_free: float,
    margin_level: float
) -> None:
    """
    Обновление метрик аккаунта.
    
    Args:
        balance: Баланс
        equity: Эквити
        margin_used: Использованная маржа
        margin_free: Свободная маржа
        margin_level: Уровень маржи
    """
    ACCOUNT_BALANCE.set(balance)
    ACCOUNT_EQUITY.set(equity)
    ACCOUNT_MARGIN_USED.set(margin_used)
    ACCOUNT_MARGIN_FREE.set(margin_free)
    ACCOUNT_MARGIN_LEVEL.set(margin_level)


def update_system_health(component: str, healthy: bool) -> None:
    """
    Обновление статуса здоровья компонента.
    
    Args:
        component: Название компонента
        healthy: Статус (True = healthy)
    """
    SYSTEM_HEALTH.labels(component=component).set(1 if healthy else 0)


def track_cache_operation(cache_name: str, hit: bool) -> None:
    """
    Трекинг операций кэша.
    
    Args:
        cache_name: Название кэша
        hit: True если hit, False если miss
    """
    if hit:
        CACHE_HITS.labels(cache_name=cache_name).inc()
    else:
        CACHE_MISSES.labels(cache_name=cache_name).inc()


def record_trade_pnl(symbol: str, strategy: str, pnl: float) -> None:
    """
    Запись PnL сделки.
    
    Args:
        symbol: Инструмент
        strategy: Стратегия
        pnl: Прибыль/убыток
    """
    TRADES_PNL.labels(symbol=symbol, strategy=strategy).observe(pnl)


def update_strategy_metrics(
    strategy: str,
    win_rate: float,
    profit_factor: float,
    total_trades: int,
    total_pnl: float
) -> None:
    """
    Обновление метрик стратегии.
    
    Args:
        strategy: Название стратегии
        win_rate: Win rate
        profit_factor: Profit factor
        total_trades: Количество сделок
        total_pnl: Общий PnL
    """
    STRATEGY_PERFORMANCE.labels(strategy=strategy, metric='win_rate').set(win_rate)
    STRATEGY_PERFORMANCE.labels(strategy=strategy, metric='profit_factor').set(profit_factor)
    STRATEGY_PERFORMANCE.labels(strategy=strategy, metric='total_trades').set(total_trades)
    STRATEGY_PERFORMANCE.labels(strategy=strategy, metric='total_pnl').set(total_pnl)
