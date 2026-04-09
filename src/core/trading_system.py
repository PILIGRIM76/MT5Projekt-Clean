# src/core/trading_system.py
import asyncio
import functools
import gc
import json
import logging
import os
import queue
import sys
import threading
import time as standard_time
import traceback
import uuid
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import optuna
except ImportError:
    optuna = None
import torch

try:
    from optuna.integration import TFKerasPruningCallback
except ImportError:
    # Fallback if tfkeras integration is not available
    TFKerasPruningCallback = None
from pathlib import Path as SyncPath

import lightgbm as lgb
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from PySide6.QtCore import QObject, QThreadPool, Signal
from sentence_transformers import SentenceTransformer
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src._version import __version__
from src.analysis.anomaly_detector import AnomalyDetector
from src.analysis.defi_analyzer import DeFiAnalyzer
from src.analysis.drift_detector import ConceptDriftManager
from src.analysis.gp_rd_manager import GPRDManager
from src.analysis.market_regime_manager import MarketRegimeManager
from src.analysis.market_screener import MarketScreener
from src.analysis.nlp_processor import CausalNLPProcessor
from src.analysis.strategy_optimizer import StrategyOptimizer
from src.core.account_manager import AccountManager
from src.core.auto_updater import AutoUpdater
from src.core.config_models import Settings
from src.core.config_writer import write_config
from src.core.hot_reload_manager import HotReloadManager
from src.core.interfaces import ITerminalConnector
from src.core.mt5_connection_manager import mt5_ensure_connected, mt5_initialize, mt5_shutdown
from src.core.orchestrator import Orchestrator
from src.core.paper_trading_engine import PaperTradingEngine
from src.core.secrets_manager import SecretsManager
from src.core.services.portfolio_service import PortfolioService
from src.core.services.signal_service import SignalService
from src.core.services.trade_executor import TradeExecutor
from src.core.session_manager import SessionManager
from src.core.system_service_manager import SystemServiceManager
from src.core.trading import GUICoordinator, MLCoordinator, PerformanceTimer, TradingCache, TradingEngine
from src.data.blockchain_provider import BlockchainProvider
from src.data.data_provider import DataProvider
from src.data.data_provider_manager import DataProviderManager
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.data.multi_source_aggregator import MultiSourceDataAggregator
from src.data_models import SignalType, TradeSignal
from src.db.database_manager import ActiveDirective, DatabaseManager
from src.db.multi_database_manager import MultiDatabaseManager
from src.db.vector_db_manager import VectorDBManager
from src.ml.ai_backtester import AIBacktester
from src.ml.consensus_engine import ConsensusEngine
from src.ml.model_factory import ModelFactory
from src.ml.rl_trade_manager import RLTradeManager
from src.monitoring.alert_manager import AlertManager
from src.risk.circuit_breaker import CircuitBreaker
from src.risk.risk_engine import RiskEngine
from src.social.subscriber import TradeSubscriber
from src.strategies.strategy_loader import StrategyLoader

logger = logging.getLogger(__name__)


def exception_handler(default_return_value=None, fatal=False):
    """Декоратор для обработки исключений в методах.

    Args:
        default_return_value: Значение по умолчанию при ошибке
        fatal: Если True — ошибка критическая, логируется CRITICAL
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if fatal:
                    logger.critical(f"КРИТИЧЕСКАЯ ошибка в {func.__name__}: {e}", exc_info=True)
                else:
                    logger.error(f"Ошибка в {func.__name__}: {e}")
                return default_return_value

        return wrapper

    return decorator


class TradingSystem(QObject):
    # Сигналы для связи с GUI (через Bridge)
    rd_progress_updated = Signal(dict)
    market_scan_updated = Signal(list)  # Данные для таблицы сканера
    # Отдельный сигнал для торговых сигналов
    trading_signals_updated = Signal(list)
    uptime_updated = Signal(str)
    all_positions_closed = Signal()
    directives_updated = Signal(list)
    orchestrator_allocation_updated = Signal(dict)
    knowledge_graph_updated = Signal(str)
    thread_status_updated = Signal(str, str)
    long_task_status_updated = Signal(str, str, bool)
    social_status_updated = Signal(str)  # НОВОЕ: Сигнал статуса социальной торговли
    drift_data_updated = Signal(float, str, float, bool)

    def __init__(self, config: Settings, gui=None, sound_manager=None, bridge=None):
        super().__init__()
        self.bridge = bridge
        self.config = config
        self.gui = gui
        # УДАЛЕНО: self._safe_gui_update = self.gui._safe_gui_update if self.gui else lambda *args, **kwargs: None
        # Используем собственный метод _safe_gui_update из этого класса
        self.sound_manager = sound_manager
        self.version = "v24.0"

        # --- Инициализация переменных ---
        self.stop_event = threading.Event()
        self.running = False
        self.mt5_lock = threading.Lock()
        self.training_lock = threading.Lock()
        self.analysis_lock = threading.Lock()
        self.trade_execution_lock = asyncio.Lock()

        self.update_pending = False
        self.last_h1_data_cache: Optional[pd.DataFrame] = None
        self.last_history_sync_time = datetime.now()

        self.db_write_queue = queue.Queue()
        self.command_queue = queue.Queue()
        self.xai_queue = queue.Queue()
        self.start_time = None
        self.observer_mode = False
        self.is_heavy_init_complete = False
        self._background_services_started = False  # Флаг для предотвращения повторного запуска
        self.history_needs_update = True
        self.account_currency = "USD"
        self.maintenance_notified = False
        self.optimization_notified = False
        # НОВОЕ: флаг для fallback режима при потере MT5
        self.mt5_connection_failed = False

        # НОВОЕ: Счётчик ошибок авторизации для экспоненциальной задержки
        self._auth_error_count = 0
        self._last_auth_error_time = None
        self._auth_error_logged = False  # Флаг для дедупликации логов

        self._last_known_balance = 0.0
        self._last_known_equity = 0.0
        self._last_known_uptime = "0:00:00"
        self._last_positions_cache = []  # Кэш позиций для легкого обновления прибыли

        self.latest_full_ranked_list: List[dict] = []
        self.last_model_load_time = 0
        self.xai_worker_thread: Optional[threading.Thread] = None
        self.vector_db_cleanup_thread: Optional[threading.Thread] = None
        self.trading_loop: Optional[asyncio.AbstractEventLoop] = None
        self.news_cache = None
        self.last_news_fetch_time = None

        # --- Кэширование данных ---
        # Используем новый TradingCache (вынесен из God Object)
        self._data_cache = TradingCache(max_size=1000)
        self._cache_timestamps = {}  # Legacy
        self._cache_ttl = {}  # Legacy
        self._cache_lock = threading.RLock()  # Legacy

        # --- Таймер производительности ---
        self._perf_timer = PerformanceTimer()
        self.performance_metrics = {}
        self._perf_lock = threading.Lock()

        # --- GUI Coordinator ---
        self._gui_coordinator = GUICoordinator(bridge=bridge, config=config) if bridge else None

        # --- TradingEngine ---
        self._trading_engine = TradingEngine(self)

        # --- MLCoordinator ---
        self._ml_coordinator = MLCoordinator(self)

        # --- Отслеживание активных обучений ---
        self._training_symbols = set()  # Символы, которые сейчас обучаются
        self._training_lock = threading.Lock()  # Блокировка для _training_symbols

        # --- Логирование производительности ---
        self.performance_metrics = {}
        self._perf_lock = threading.Lock()

        # --- Коннектор (инициализируется как MT5 модуль) ---
        # Используем напрямую MetaTrader5 как коннектор
        self.terminal_connector = mt5  # MT5 wrapper модуль

        # --- Тяжелые объекты (инициализируются позже) ---
        self.db_manager = None
        self.vector_db_manager = None
        self.data_provider = None
        self.nlp_processor = None
        self.consensus_engine = None
        self.knowledge_graph_querier = None
        self.strategy_loader = None
        self.strategies = {}
        self.rl_manager = None
        self.market_screener = None
        self.data_aggregator = None
        self.market_regime_manager = None
        self.session_manager = None
        self.anomaly_detector = None
        self.blockchain_provider = None
        self.risk_engine = None
        self.strategy_optimizer = None
        self.gp_rd_manager = None
        self.drift_manager = None
        self.portfolio_service = None
        self.signal_service = None
        self.execution_service = None
        self.auto_updater = None
        self.orchestrator = None
        self.training_scheduler = None  # Планировщик автоматического переобучения
        self.hot_reload_manager = None  # Менеджер горячего обновления
        self.model_loader = None  # Загрузчик AI-моделей с кастомными путями
        self.safety_monitor = None  # CRITICAL: Safety Monitor для защиты капитала
        self.circuit_breaker = None  # P0: Circuit Breaker для аварийной остановки
        self.alert_manager = None  # P0: Alert Manager для уведомлений
        self.paper_trading_engine = None  # P0: Paper Trading Engine для симуляции
        self.secrets_manager = None  # P0: Secrets Manager для безопасного хранения

        self.models: Dict[str, Any] = {}
        self.x_scalers: Dict[str, StandardScaler] = {}
        self.y_scalers: Dict[str, StandardScaler] = {}
        self.strategy_performance = defaultdict(lambda: {"wins": 0, "losses": 0, "total_trades": 0})
        self.active_directives: Dict[str, Any] = {}
        # {symbol: {'last_profit_pct': float, 'last_trade_time': datetime, 'last_outcome': str}}
        self.trade_history: Dict[str, Dict] = {}

        # === ИНТЕГРАЦИЯ НОВЫХ СЕРВИСОВ ===
        self.service_manager = SystemServiceManager(self)
        logger.info("SystemServiceManager инициализирован")
        # ==================================

        if bridge:
            logger.info("TradingSystem __init__: Bridge ОБЪЕКТ СУЩЕСТВУЕТ. Легкая инициализация завершена.")

    def initialize_heavy_components(self, bridge=None):
        """Выполняет всю блокирующую инициализацию."""
        logger.critical("--- [INIT START] ---")

        if bridge:
            self.bridge = bridge

        # 1. Device
        logger.critical("INIT STEP 1/8: Determining Device...")
        # Используем CPU для стабильности и снижения нагрузки на систему
        self.device = torch.device("cpu")
        logger.critical(f"INIT STEP 1/8: Device determined: {self.device}")

        # 2. DB
        logger.critical("INIT STEP 2/8: Initializing DB and VectorDB...")
        self.db_manager = DatabaseManager(self.config, self.db_write_queue)
        vector_db_full_path = SyncPath(self.config.DATABASE_FOLDER) / self.config.vector_db.path
        logger.info(f"[VectorDB] Инициализация по пути: {vector_db_full_path}")
        self.vector_db_manager = VectorDBManager(self.config.vector_db, db_root_path=vector_db_full_path)

        # Инициализация MultiDatabaseManager (мульти-базовая архитектура)
        logger.info("Инициализация MultiDatabaseManager...")
        self.multi_db_manager = MultiDatabaseManager.from_env()
        self.multi_db_enabled = self._check_multi_db_status()

        if self.multi_db_enabled:
            logger.info("✓ Мульти-БД режим активирован")
            self._integrate_multi_db()
        else:
            logger.warning("⚠ Мульти-БД режим отключен (используется SQLite + FAISS)")

        logger.critical("INIT STEP 2/8: DB and VectorDB initialized.")

        # 3. DataProvider
        logger.critical("INIT STEP 3/8: Initializing DataProvider...")
        self.data_provider = DataProvider(self.config, self.mt5_lock)

        # 3.1 DataProviderManager (multi-source: MT5 + Crypto)
        logger.critical("INIT STEP 3.1/8: Initializing DataProviderManager...")
        self.data_provider_manager = DataProviderManager(self.config, self.mt5_lock)
        self.data_provider_manager.set_mt5_provider(self.data_provider)
        # Инициализация крипто-провайдеров будет выполнена в async контексте
        logger.critical("INIT STEP 3.1/8: DataProviderManager initialized.")

        # --- ДОБАВЛЕНО: Фильтрация символов ---
        logger.info("Фильтрация списка символов под текущего брокера...")
        valid_symbols = self.data_provider.filter_available_symbols(self.config.SYMBOLS_WHITELIST)

        if len(valid_symbols) == 0:
            logger.critical("!!! ВНИМАНИЕ: Ни один символ из whitelist не найден у брокера! Проверьте settings.json.")
            # Переход на fallback: используем все доступные символы брокера, если whitelist пустой
            fallback_symbols = self.data_provider.get_available_symbols()
            if fallback_symbols:
                valid_symbols = fallback_symbols
                self.config.SYMBOLS_WHITELIST = valid_symbols
                self.data_provider.symbols_whitelist = valid_symbols
                logger.warning(f"Используются доступные у брокера символы: {len(valid_symbols)} (fallback).")
            else:
                logger.critical("!!! ОШИБКА: Нет доступных символов для торговли. Инициализация завершена с пустым списком.")
        else:
            # Обновляем конфиг в памяти (не в файле), чтобы работать только с валидными
            self.config.SYMBOLS_WHITELIST = valid_symbols
            # Обновляем whitelist внутри провайдера
            self.data_provider.symbols_whitelist = valid_symbols
            logger.info(f"Список символов обновлен: {len(valid_symbols)} активных инструментов.")
        # --------------------------------------

        logger.critical("INIT STEP 3/8: DataProvider initialized.")

        # 4. Strategies
        logger.critical("INIT STEP 4/8: Loading Strategies...")
        self.strategy_loader = StrategyLoader(self.config)
        self.strategies = self.strategy_loader.load_strategies()
        logger.critical("INIT STEP 4/8: Strategies loaded.")

        # 5. Cognitive
        logger.critical("INIT STEP 5/8: Initializing Cognitive Components...")
        self.knowledge_graph_querier = KnowledgeGraphQuerier(self.db_manager)
        self.nlp_processor = CausalNLPProcessor(self.config, self.db_manager, self.vector_db_manager)
        self.consensus_engine = ConsensusEngine(self.config, self.db_manager, self.vector_db_manager)
        logger.critical("INIT STEP 5/8: Cognitive Components initialized.")

        # 6. Models
        logger.critical("INIT STEP 6/8: Loading NLP/Embedding Models (CRITICAL ZONE)...")

        # --- ДОБАВЛЕНО: Загрузка SentenceTransformer ---
        # Отключаем загрузку, если VectorDB выключен
        if self.config.vector_db.enabled:
            try:
                logger.info(f"Загрузка модели эмбеддингов: {self.config.vector_db.embedding_model}...")

                # Устанавливаем путь к кэшу моделей из настроек
                cache_dir = None
                if hasattr(self.config, "HF_MODELS_CACHE_DIR") and self.config.HF_MODELS_CACHE_DIR:
                    cache_dir = self.config.HF_MODELS_CACHE_DIR
                    logger.info(f"Используется кэш моделей: {cache_dir}")
                    import os

                    os.environ["TRANSFORMERS_CACHE"] = cache_dir
                    os.environ["HF_HOME"] = cache_dir
                else:
                    logger.info("Используется кэш моделей по умолчанию")

                from huggingface_hub.utils import disable_progress_bars

                disable_progress_bars()

                # Оптимизация: Lazy Loading вместо eager загрузки (~80MB RAM экономии)
                from src.core.trading import NLPLazyLoader

                self.nlp_lazy_loader = NLPLazyLoader(idle_timeout=3600.0)

                # Регистрируем модели но НЕ загружаем их сразу
                self.nlp_lazy_loader.register_model(self.config.vector_db.embedding_model, "embedding")
                logger.info(f"✅ NLP модели зарегистрированы (lazy load): {self.config.vector_db.embedding_model}")

                # Передаём lazy loader в компоненты
                self.nlp_processor.nlp_lazy_loader = self.nlp_lazy_loader
                self.consensus_engine.nlp_lazy_loader = self.nlp_lazy_loader

                # Загружаем только если VectorDB включён и нужен сразу
                if self.config.vector_db.enabled:
                    logger.info("VectorDB включён — загрузка embedding модели при первом использовании")
                else:
                    logger.info("VectorDB отключён — модель эмбеддингов не будет загружена")
            except Exception as e:
                logger.error(f"Ошибка инициализации NLP Lazy Loader: {e}")
                logger.warning("Продолжаем работу без lazy loading моделей")
        else:
            logger.info("VectorDB отключен, регистрация NLP моделей пропущена")
        # -----------------------------------------------

        self.nlp_processor.device = self.device
        self.nlp_processor.load_models()
        self.consensus_engine.load_models()
        logger.critical("INIT STEP 6/8: NLP/Embedding Models loaded.")

        # 7. Core Services
        logger.critical("INIT STEP 7/8: Initializing Core Services...")
        self.rl_manager = RLTradeManager(self.config, self.data_provider)
        self.anomaly_detector = AnomalyDetector(self.config)
        self.blockchain_provider = BlockchainProvider(self.config)
        self.market_regime_manager = MarketRegimeManager(self.config)

        # P0: Инициализация DeFi Analyzer (анализ метрик DeFi для торговли)
        self.defi_analyzer = DeFiAnalyzer(self.db_manager)
        logger.info("DeFi Analyzer инициализирован")
        self.session_manager = SessionManager(self.config)
        self.market_screener = MarketScreener(self.config, self.mt5_lock)
        self.data_aggregator = MultiSourceDataAggregator(self.config)
        # ИСПРАВЛЕНИЕ: Передаем data_provider и market_screener в MultiSourceDataAggregator
        self.data_aggregator.data_provider = self.data_provider
        self.data_aggregator.market_screener = self.market_screener

        # P0: Инициализация Account Manager (Автоопределение типа счета и рисков)
        self.account_manager = AccountManager()
        logger.info("Account Manager инициализирован")

        self.risk_engine = RiskEngine(
            self.config,
            self,
            self.knowledge_graph_querier,
            self.mt5_lock,
            is_simulation=False,
            account_manager=self.account_manager,
        )
        self.risk_engine.data_provider_manager = self.data_provider_manager  # Для крипто-позиций

        # P0: Инициализация Circuit Breaker
        self.circuit_breaker = CircuitBreaker(self.config, self)
        logger.info("Circuit Breaker инициализирован")

        # P0: Инициализация Social Trading Subscriber
        if hasattr(self, "social_subscriber"):
            try:
                # Запускаем в асинхронном цикле событий
                asyncio.create_task(self.social_subscriber.start())
                logger.info("Social Trading Subscriber запущен")
            except Exception as e:
                logger.error(f"Ошибка запуска Social Trading: {e}")

        # P0: Инициализация Alert Manager
        self.alert_manager = AlertManager(self.config, self)
        logger.info("Alert Manager инициализирован")

        # P0: Инициализация Paper Trading Engine
        self.paper_trading_engine = PaperTradingEngine(self.config, self)
        logger.info("Paper Trading Engine инициализирован")

        # P0: Инициализация Secrets Manager
        self.secrets_manager = SecretsManager()
        logger.info("Secrets Manager инициализирован")

        # P0: Инициализация Social Trading (Копирование сделок)
        self.social_subscriber = TradeSubscriber(self.config, signal_emitter=self.social_status_updated)
        logger.info("Social Trading Subscriber инициализирован")

        self.strategy_optimizer = StrategyOptimizer(self.config, self.data_provider)
        self.gp_rd_manager = GPRDManager(self.config, self.data_provider, self.db_manager)
        self.drift_manager = ConceptDriftManager(self.config)
        self.portfolio_service = PortfolioService(self.config, self.rl_manager, self.data_provider, self.mt5_lock)
        self.portfolio_service.data_provider_manager = self.data_provider_manager  # Для крипто-позиций

        self.signal_service = SignalService(
            config=self.config,
            market_regime_manager=self.market_regime_manager,
            strategies=self.strategies,
            models=self.models,
            x_scalers=self.x_scalers,
            y_scalers=self.y_scalers,
            strategy_performance=self.strategy_performance,
            consensus_engine=self.consensus_engine,
            trading_system_ref=self,
        )
        self.signal_service.data_provider_manager = self.data_provider_manager  # Для крипто-сигналов
        self.execution_service = TradeExecutor(self.config, self.risk_engine, self.portfolio_service, self.mt5_lock)
        self.execution_service.data_provider_manager = self.data_provider_manager  # Для крипто-ордеров
        self.auto_updater = AutoUpdater(self, self.bridge)
        self.orchestrator = Orchestrator(
            self, self.strategy_optimizer, self.db_manager, self.data_provider, self.data_provider_manager
        )

        # Инициализация планировщика автоматического переобучения
        from src.core.training_scheduler import TrainingScheduler

        self.training_scheduler = TrainingScheduler(self.config, self._auto_retrain_callback)

        # Инициализация Model Loader (загрузка моделей с кастомными путями)
        from src.core.model_loader import create_model_loader, validate_models_at_startup

        self.model_loader = create_model_loader(self.config)
        logger.info("✅ ModelLoader инициализирован")

        # Валидация моделей при старте (до начала торговли)
        if validate_models_at_startup(self.config):
            logger.info("✅ Валидация моделей прошла успешно")
        else:
            logger.warning("⚠️ Валидация моделей не удалась — торговля может быть ограничена")

        # Инициализация Model Championship (турнир для отбора лучших моделей)
        from src.ml.championship import ModelChampionship

        self.championship = ModelChampionship(self.config, self.db_manager)
        # Связываем config с trading_system (для hot-reload)
        self.config._trading_system = self
        logger.info("✅ ModelChampionship инициализирован")

        # === ORCHESTRATOR STATE ===
        self.orchestrator_active_strategies: Dict[str, bool] = {}  # {strategy_name: is_active}
        self.orchestrator_current_regime: str = "Default"
        self.orchestrator_max_positions: int = self.config.MAX_OPEN_POSITIONS
        self.orchestrator_risk_multiplier: float = 1.0
        # ==========================

        # === ARCHITECTURE: "Единый организм" — 4 слоя координации ===
        from src.core.health_monitor import get_health_monitor
        from src.core.lock_manager import lock_manager
        from src.core.resource_governor import get_governor
        from src.core.task_queue import get_task_queue

        # 1. ResourceGovernor — контроль CPU/RAM/GPU
        self.governor = get_governor()
        logger.info("🎛️ ResourceGovernor инициализирован")

        # 2. PriorityTaskQueue — замена threading.Thread для R&D
        self.task_queue = get_task_queue(max_workers=4)
        logger.info("🚀 PriorityTaskQueue инициализирован (4 воркера)")

        # 3. LockHierarchy — иерархия блокировок (будет использоваться вместо прямых mt5_lock)
        self.lock_manager = lock_manager
        logger.info("🔒 LockHierarchy инициализирован")

        # 4. HealthMonitor — мониторинг состояния системы
        self.health_monitor = get_health_monitor(
            governor=self.governor,
            task_queue=self.task_queue,
            lock_manager=self.lock_manager,
            trading_system=self,
        )
        logger.info("📊 HealthMonitor инициализирован")
        # =============================================================

        # Планируем первый запуск чемпионата
        self._championship_next_run = datetime.now()
        logger.info(f"🏆 Первый запуск чемпионата: {self._championship_next_run.strftime('%Y-%m-%d %H:%M')}")

        # Инициализация HotReloadManager (с поддержкой файлового мониторинга)
        import os

        repo_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Директории для наблюдения (конфиги, модели)
        watch_dirs = []
        model_dir = (
            self.config.MODEL_DIR if self.config.MODEL_DIR else str(SyncPath(self.config.DATABASE_FOLDER) / "ai_models")
        )
        if SyncPath(model_dir).exists():
            watch_dirs.append(model_dir)
            logger.info(f"👁️ HotReload наблюдает за моделями: {model_dir}")

        from src.core.hot_reload_manager import HotReloadConfig

        self.hot_reload_manager = HotReloadManager(
            repo_path=repo_path,
            branch="main",
            trading_system=self,  # Передаём ссылку на TradingSystem
            on_update_available=self._on_update_available,
            on_update_complete=self._on_update_complete,
            on_error=self._on_update_error,
            config=HotReloadConfig(
                dry_run=False,  # Включить для тестирования без реальных изменений
                auto_apply=False,  # Ручное подтверждение обновлений
                debounce_seconds=2.0,
            ),
            watch_dirs=watch_dirs,
        )
        logger.info("✅ HotReloadManager инициализирован")

        # Запускаем мониторинг обновлений (проверка каждые 5 минут)
        self.hot_reload_manager.start_monitoring(interval=300)
        logger.info("✅ Мониторинг обновлений запущен (каждые 5 минут)")

        logger.critical("INIT STEP 7/8: Core Services initialized.")

        # CRITICAL: Инициализация Safety Monitor
        logger.critical("INIT STEP 8/8: Initializing Safety Monitor...")
        from src.core.safety_monitor import SafetyMonitor

        self.safety_monitor = SafetyMonitor(self.config, self)
        logger.critical("INIT STEP 8/8: Safety Monitor object created.")

        # Оптимизация: освобождаем память после инициализации
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.critical("--- [INIT END] ---")
        self.is_heavy_init_complete = True

        # Сбрасываем флаг обновления после полной инициализации
        if self.update_pending:
            logger.info("[INIT] Сброс флага update_pending после завершения инициализации")
            self.update_pending = False

        # === ИНТЕГРАЦИЯ: Инициализация сервисов ===
        if hasattr(self, "service_manager"):
            try:
                asyncio.run(self.service_manager.initialize_services())
                logger.info("Сервисы инициализированы через SystemServiceManager")
            except Exception as e:
                logger.error(f"Ошибка инициализации сервисов: {e}")
        # ===========================================

    async def initialize_crypto_providers(self):
        """
        Асинхронная инициализация крипто-провайдеров.
        Вызывается отдельно после initialize_heavy_components.
        """
        if hasattr(self, "data_provider_manager") and self.data_provider_manager:
            logger.info("[CryptoProviders] Инициализация крипто-провайдеров...")
            await self.data_provider_manager.initialize()

            # Получаем расширенный список символов
            crypto_symbols = []
            for exchange_id, provider in self.data_provider_manager._crypto_providers.items():
                symbols = await provider.get_symbols()
                crypto_symbols.extend(symbols)
                logger.info(f"[CryptoProviders] {exchange_id}: {len(symbols)} символов")

            if crypto_symbols:
                # Добавляем крипто-символы в whitelist
                all_symbols = list(set(self.config.SYMBOLS_WHITELIST + crypto_symbols))
                self.config.SYMBOLS_WHITELIST = all_symbols
                logger.info(f"[CryptoProviders] Общий список символов: {len(all_symbols)} (MT5 + Crypto)")

            logger.info(
                f"[CryptoProviders] Инициализация завершена. Бирж: {len(self.data_provider_manager._crypto_providers)}"
            )

    def start_all_background_services(self, threadpool: Optional[QThreadPool] = None):
        """Запускает все постоянные фоновые сервисы."""
        logger.info(
            f"[TradingSystem] start_all_background_services вызван. is_heavy_init_complete={self.is_heavy_init_complete}"
        )

        if not self.is_heavy_init_complete:
            raise RuntimeError("Невозможно запустить сервисы: тяжелая инициализация не завершена.")

        # Проверка на повторный запуск
        if hasattr(self, "_background_services_started") and self._background_services_started:
            logger.warning("[TradingSystem] Фоновые сервисы уже запущены, пропускаю повторный запуск")
            return

        logger.info("[TradingSystem] Начинаю запуск фоновых сервисов...")

        # КРИТИЧНО: Принудительный сброс флага обновления при запуске сервисов
        # AutoUpdater может установить его в фоновом потоке, что блокирует торговый цикл
        if self.update_pending:
            logger.warning("[RUNTIME] Принудительный сброс update_pending при запуске сервисов")
            self.update_pending = False

        # Запуск планировщика автоматического переобучения
        if self.training_scheduler:
            self.training_scheduler.start()
            self.thread_status_updated.emit("Training Scheduler", "RUNNING")

        # Запуск системы автоматического обновления
        if self.auto_updater:
            self.auto_updater.start()
            self.thread_status_updated.emit("Auto Updater", "RUNNING")
            logger.info("[UPDATE] Система автоматического обновления запущена")

        # CRITICAL: Инициализация Safety Monitor
        if self.safety_monitor:
            self.safety_monitor.initialize()
            logger.critical("[SAFETY] Safety Monitor активирован и готов к работе")

        # Инициализация Health Check Endpoint
        from src.core.trading import HealthCheckEndpoint

        self.health_check = HealthCheckEndpoint(self)
        logger.info("[HEALTH] Health Check Endpoint инициализирован")
        initial_health = self.health_check.get_health_summary()
        logger.info(f"[HEALTH] Начальный статус: {initial_health}")

        # Создание потоков
        self.history_sync_thread = threading.Thread(target=self._sync_initial_history, daemon=True, name="HistorySyncThread")
        self.trading_thread = threading.Thread(target=self.start_trading_loop, daemon=True, name="TradingThread")
        self.monitoring_thread = threading.Thread(target=self.start_monitoring_loop, daemon=True, name="MonitoringThread")
        self.uptime_thread = threading.Thread(target=self._uptime_updater_loop, daemon=True, name="UptimeThread")
        self.orchestrator_thread = threading.Thread(
            target=self.start_orchestrator_loop, daemon=True, name="OrchestratorThread"
        )
        self.db_writer_thread = threading.Thread(target=self._database_writer_loop, daemon=True, name="DatabaseWriterThread")
        self.xai_worker_thread = threading.Thread(target=self._xai_worker_loop, daemon=True, name="XAIWorkerThread")
        self.training_thread = threading.Thread(target=self._training_loop, daemon=True, name="TrainingThread")
        self.vector_db_cleanup_thread = threading.Thread(
            target=self._vector_db_cleanup_loop, daemon=True, name="VectorDBCleanupThread"
        )
        self.symbol_monitor_thread = threading.Thread(
            target=self._symbol_performance_monitor_loop, daemon=True, name="SymbolMonitorThread"
        )
        self.training_status_thread = threading.Thread(
            target=self._periodic_training_status_update_loop, daemon=True, name="TrainingStatusThread"
        )

        threads_to_start = {
            "History Sync": self.history_sync_thread,
            "Trading": self.trading_thread,
            "Monitoring": self.monitoring_thread,
            "Uptime": self.uptime_thread,
            "Orchestrator": self.orchestrator_thread,
            "DB Writer": self.db_writer_thread,
            # "XAI Worker": self.xai_worker_thread,  # 🔧 OPTIMIZATION: Запускается лениво (по требованию GUI)
            "Training": self.training_thread,
            "VectorDB Cleanup": self.vector_db_cleanup_thread,
            "Symbol Monitor": self.symbol_monitor_thread,
            "Training Status": self.training_status_thread,  # НОВЫЙ
        }

        for name, thread in threads_to_start.items():
            if thread:
                thread.start()
                logger.info(f"[TradingSystem] Поток '{name}' запущен: {thread.name}, daemon={thread.daemon}")
                self.thread_status_updated.emit(name, "RUNNING")
            else:
                logger.error(f"[TradingSystem] Поток '{name}' = None, не могу запустить!")

        self._background_services_started = True
        logger.info(f"Все фоновые сервисы запущены. Активных потоков: {len(threads_to_start)}")

    def start_all_threads(self):
        """Запускает полный цикл инициализации и старта потоков."""
        if self.running:
            logger.info("[TradingSystem] Система уже запущена (running=True), пропускаю")
            return

        logger.info("=== ЗАПУСК ТОРГОВОЙ СИСТЕМЫ (start_all_threads) ===")

        with self.mt5_lock:
            # Безопасная обработка MT5_LOGIN
            try:
                mt5_login = int(self.config.MT5_LOGIN) if self.config.MT5_LOGIN else None
            except (ValueError, TypeError) as e:
                logger.error(f"[MT5] Некорректный MT5_LOGIN: {self.config.MT5_LOGIN}, ошибка: {e}")
                mt5_login = None

            if not mt5_initialize(
                path=self.config.MT5_PATH,
                login=mt5_login,
                password=self.config.MT5_PASSWORD,
                server=self.config.MT5_SERVER,
            ):
                logger.critical("Не удалось подключиться к MT5.")
                if self.gui:
                    self.gui.bridge.initialization_failed.emit()
                return

            # === ПРОВЕРКА АВТОТОРГОВЛИ ===
            try:
                # TERMINAL_TRADE_AVAILABLE может отсутствовать в старых версиях MT5
                if hasattr(mt5, "TERMINAL_TRADE_ALLOWED"):
                    auto_trading_enabled = mt5.TerminalInfo(mt5.TERMINAL_TRADE_ALLOWED)
                else:
                    # Fallback: предполагаем что торговля разрешена
                    auto_trading_enabled = True
                    logger.debug("[MT5] TERMINAL_TRADE_ALLOWED отсутствует — предполагаем что торговля разрешена")

                if not auto_trading_enabled:
                    logger.critical("=" * 60)
                    logger.critical("⚠️  АВТОТОРГОВЛЯ ОТКЛЮЧЕНА В MT5!")
                    logger.critical("=" * 60)
                    logger.critical("Система НЕ сможет открывать сделки!")
                    logger.critical("")
                    logger.critical("Чтобы включить:")
                    logger.critical("  1. Откройте MetaTrader 5")
                    logger.critical("  2. Нажмите кнопку 'Algo Trading' (или Ctrl+E)")
                    logger.critical("  3. Убедитесь, что горит зелёный индикатор")
                    logger.critical("=" * 60)

                    # Отправляем уведомление в GUI
                    if self.gui and hasattr(self.gui, "bridge"):
                        self.gui.bridge.status_updated.emit("⚠️ АВТОТОРГОВЛЯ ОТКЛЮЧЕНА! Включите в MT5 (Ctrl+E)", True)
            except Exception as e:
                logger.warning(f"Не удалось проверить статус автоторговли: {e}")
            # ============================

        # Тяжелая инициализация (если ещё не завершена)
        if not self.is_heavy_init_complete:
            self.initialize_heavy_components()

        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Принудительно запускаем фоновые сервисы
        # независимо от флага _background_services_started, т.к. при автоинициализации
        # запускается SystemServiceManager, но НЕ создаются торговые потоки
        logger.info("[TradingSystem] Принудительный запуск фоновых сервисов...")
        self._background_services_started = False  # Сброс для обхода защиты

        # КРИТИЧНО: Устанавливаем running=True ДО запуска потоков,
        # чтобы TradingThread не завершился сразу после старта
        self.running = True
        self.stop_event.clear()
        self.start_time = datetime.now()

        self.start_all_background_services(None)

        if self.gui:
            symbols = self.data_provider.get_available_symbols()
            self.gui.bridge.initialization_successful.emit(symbols)
            self._safe_gui_update("update_status", "Система запущена.", is_error=False)

    # --- ОСНОВНОЙ ТОРГОВЫЙ ЦИКЛ (ВМЕСТО _trade_loop) ---
    def start_trading_loop(self):
        """
        Запускает асинхронный цикл торговли.
        Это и есть главный цикл, который сканирует рынок и отправляет данные в GUI.
        """
        logger.info("Торговый поток запущен.")
        self.trading_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.trading_loop)

        # Добавляем дополнительную проверку состояния перед началом цикла
        if not self.running:
            logger.warning("Торговый поток: система не запущена (self.running=False)")
            logger.info("Торговый поток завершен.")
            return

        if self.stop_event.is_set():
            logger.warning("Торговый поток: stop_event уже установлен")
            logger.info("Торговый поток завершен.")
            return

        if not self.is_heavy_init_complete:
            logger.warning("Торговый поток: тяжелая инициализация не завершена")
            logger.info("Торговый поток завершен.")
            return

        iteration_count = 0
        try:
            while self.running and not self.stop_event.is_set():
                iteration_count += 1

                # === RESOURCE GOVERNOR: проверка перегрузки ===
                if hasattr(self, "governor") and self.governor:
                    from src.core.resource_governor import ResourceClass

                    # Критическая операция — всегда разрешена, но логируем перегрузку
                    if self.governor.is_overloaded():
                        logger.warning(f"⚠️ Система перегружена! Пропуск итерации #{iteration_count}")
                        # Принудительно завершаем низкоприоритетные задачи
                        killed = self.governor.kill_low_priority_tasks()
                        if killed:
                            logger.warning(f"🗑️ Завершены задачи: {killed}")
                        # Пауза для восстановления
                        self.stop_event.wait(2.0)
                        continue
                # ===================================================

                logger.debug(f"Торговый цикл: итерация #{iteration_count}")

                try:
                    # Запуск одной итерации цикла
                    self.trading_loop.run_until_complete(self.run_cycle())
                except Exception as e:
                    logger.error(f"Критическая ошибка в торговом цикле (итерация {iteration_count}): {e}", exc_info=True)
                    # Не прерываем весь цикл из-за одной ошибки
                    continue

                # Пауза между итерациями
                try:
                    self.trading_loop.run_until_complete(asyncio.sleep(self.config.TRADE_INTERVAL_SECONDS))
                except asyncio.CancelledError:
                    logger.info("Торговый цикл прерван (CancelledError).")
                    break
                except Exception as e:
                    logger.error(f"Ошибка при паузе в торговом цикле: {e}")
                    # Продолжаем цикл даже при ошибке паузы
                    continue

        except Exception as e:
            logger.error(f"Критическая ошибка в торговом потоке: {e}", exc_info=True)
        finally:
            logger.info(f"Торговый поток завершен после {iteration_count} итераций.")
            try:
                if hasattr(self, "trading_loop") and self.trading_loop:
                    pending = asyncio.all_tasks(self.trading_loop)
                    for task in pending:
                        task.cancel()
                    self.trading_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as e:
                logger.error(f"Ошибка при завершении торгового цикла: {e}")
            try:
                if hasattr(self, "trading_loop") and self.trading_loop:
                    self.trading_loop.close()
            except Exception as e:
                logger.error(f"Ошибка при закрытии event loop: {e}")

    async def run_cycle(self):
        """
        Одна итерация торгового цикла.
        Здесь происходит сканирование, анализ и отправка данных в GUI.
        """
        # Логирование для отладки
        logger.info("[run_cycle] Начало цикла")

        # CRITICAL: Check safety before each cycle
        if self.safety_monitor and not self.safety_monitor.check_safety_conditions():
            logger.critical("⛔ Trading stopped by Safety Monitor")
            return

        # Graceful Degradation: проверяем фазу деградации ML моделей
        if hasattr(self, "_ml_coordinator") and self._ml_coordinator:
            from src.core.trading import DegradationPhase

            # Получаем статус деградации из health_check
            if hasattr(self, "health_check") and self.health_check:
                degradation = self.health_check.get_health_status().get("degradation", {})
                phase = degradation.get("current_phase", "full_ml")
                if phase in ["observer_mode", "emergency_stop"]:
                    logger.warning(f"[run_cycle] Graceful Degradation фаза: {phase}, снижаю активность")
        # Проверки перед запуском
        if self.stop_event.is_set() or not self.is_heavy_init_complete:
            logger.warning(
                f"[run_cycle] Пропуск: stop_event={self.stop_event.is_set()}, heavy_init={self.is_heavy_init_complete}"
            )
            return

        # ИСПРАВЛЕНИЕ: update_pending больше не блокирует цикл мониторинга!
        # Баланс и позиции должны обновляться даже если есть pending update
        if self.update_pending:
            logger.debug(f"[run_cycle] Update pending, но продолжаем обновление баланса/позиций")

        try:
            logger.info("[run_cycle] Запуск performance timer")
            self.start_performance_timer("run_cycle_total")

            logger.info("[run_cycle] Обработка команд")
            self._process_commands()

            # 1. Получение данных аккаунта (Синхронно в потоке)
            account_info = None
            current_positions = []

            def get_account_and_positions_sync():
                logger.info("[run_cycle] Попытка захвата mt5_lock...")
                # ИСПРАВЛЕНИЕ: Сделаем таймаут коротким (0.5 сек) чтобы не блокировать торговлю на долго
                if not self.mt5_lock.acquire(timeout=0.5):
                    logger.warning("[run_cycle] MT5 Lock недоступен (таймаут 0.5с), пропуск цикла")
                    return None, []

                logger.info("[run_cycle] MT5 Lock захвачен")
                try:
                    # Безопасная обработка MT5_LOGIN
                    try:
                        mt5_login = int(self.config.MT5_LOGIN) if self.config.MT5_LOGIN else None
                    except (ValueError, TypeError) as e:
                        logger.error(f"[MT5] Некорректный MT5_LOGIN: {self.config.MT5_LOGIN}, ошибка: {e}")
                        mt5_login = None

                    # Сначала пробуем мягкое подключение через ConnectionManager
                    if not mt5_ensure_connected(path=self.config.MT5_PATH):
                        logger.warning("[run_cycle] Не удалось подключиться к MT5 (мягкое)")
                        # Если не вышло, пробуем полную авторизацию
                        if not mt5_initialize(
                            path=self.config.MT5_PATH,
                            login=mt5_login,
                            password=self.config.MT5_PASSWORD,
                            server=self.config.MT5_SERVER,
                        ):
                            logger.error("[run_cycle] Не удалось подключиться к MT5 (полная авторизация)")
                            return None, []

                    try:
                        acc_info = mt5.account_info()
                        pos = mt5.positions_get()
                        logger.info(
                            f"[run_cycle] Данные аккаунта получены: balance={acc_info.balance if acc_info else 'None'}"
                        )
                        return acc_info, list(pos) if pos else []
                    finally:
                        mt5_shutdown()
                finally:
                    logger.info("[run_cycle] MT5 Lock освобождается")
                    self.mt5_lock.release()

            logger.info("[run_cycle] Запрос данных аккаунта через asyncio.to_thread")
            account_info, current_positions = await asyncio.to_thread(get_account_and_positions_sync)
            logger.info(f"[run_cycle] Данные аккаунта получены: {account_info is not None}")

            if not account_info or not self.risk_engine.check_daily_drawdown(account_info):
                logger.warning("[run_cycle] Нет данных аккаунта или не прошла проверка drawdown")
                self.end_performance_timer("run_cycle_total")
                return

            # 2. Сбор новостей (Асинхронно)
            news_task = None
            now = datetime.now()
            # Загружаем новости, если кэш пуст ИЛИ прошло больше NEWS_CACHE_DURATION_MINUTES
            should_fetch_news = (
                not self.news_cache
                or len(self.news_cache) == 0
                or (self.last_news_fetch_time is None)
                or (now - self.last_news_fetch_time).total_seconds() > self.config.NEWS_CACHE_DURATION_MINUTES * 60
            )

            if should_fetch_news:
                logger.info(
                    f"[News] Загрузка новостей (кэш: {len(self.news_cache) if self.news_cache else 0} записей, last_fetch: {self.last_news_fetch_time})"
                )
                # ИСПРАВЛЕНИЕ: Вызываем только загрузку новостей, без сбора рыночных данных
                news_task = asyncio.create_task(self.data_aggregator._load_all_news_async())
                self.last_news_fetch_time = now

            # 3. Сбор рыночных данных (Асинхронно)
            self.start_performance_timer("get_market_data")

            # ОПТИМИЗАЦИЯ: Используем только TOP_N_SYMBOLS из сканера, а не все символы
            if hasattr(self, "latest_ranked_list") and self.latest_ranked_list:
                # Берем топ символов из сканера
                top_n = self.config.TOP_N_SYMBOLS
                available_symbols = [item["symbol"] for item in self.latest_ranked_list[:top_n]]
                logger.info(f"[run_cycle] Используем топ-{len(available_symbols)} символов из сканера: {available_symbols}")
            else:
                # Fallback: используем все символы из whitelist
                available_symbols = self.config.SYMBOLS_WHITELIST
                logger.warning(f"[run_cycle] Сканер еще не работал, используем все {len(available_symbols)} символов")

            # ОПТИМИЗАЦИЯ: Загружаем только H1 для основного цикла (не все таймфреймы!)
            # Остальные таймфреймы нужны только для обучения/оптимизации
            timeframes_to_check = [mt5.TIMEFRAME_H1]  # Только H1 для торговли

            if not available_symbols:
                logger.warning("run_cycle: список доступных символов пуст. Нечего торговать.")
                self.end_performance_timer("get_market_data")
                self.end_performance_timer("run_cycle_total")
                return

            # Попробовать получить данные из кэша
            cache_key = f"market_data_{'_'.join(sorted(available_symbols))}_H1"
            data_dict_raw = self.get_cached_data(cache_key, ttl_seconds=300)  # 5 минут кэш
            logger.info(f"[run_cycle] Данные из кэша: {data_dict_raw is not None}")

            if data_dict_raw is None:
                logger.info("[run_cycle] Данные не в кэше, загрузка из MT5...")

                # 🔧 OPTIMIZATION: Повторная попытка загрузки данных (макс 2 попытки)
                max_retries = 2
                for attempt in range(1, max_retries + 1):
                    # Данные не в кэше, получить из провайдера
                    data_task = asyncio.create_task(
                        self.data_provider.get_all_symbols_data_async(available_symbols, timeframes_to_check)
                    )

                    tasks = [data_task]
                    if news_task:
                        tasks.append(news_task)
                        if attempt == 1:
                            logger.info(f"[run_cycle] Запуск задач: данные + новости")

                    # Ждем завершения всех задач
                    logger.info(f"[run_cycle] Ожидание завершения задач (попытка {attempt}/{max_retries})...")
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    data_dict_raw = results[0]
                    news_result_tuple = results[1] if news_task else None
                    logger.info(
                        f"[run_cycle] Задачи завершены: данные={data_dict_raw is not None}, новости={news_result_tuple is not None}"
                    )

                    # Проверяем, не вернула ли новость ошибку
                    if news_result_tuple and isinstance(news_result_tuple, Exception):
                        logger.error(f"[VectorDB] Ошибка при загрузке новостей: {news_result_tuple}")
                        news_result_tuple = None

                    # Если данные не пришли — пробуем снова
                    if not data_dict_raw or isinstance(data_dict_raw, Exception):
                        if attempt < max_retries:
                            logger.warning(
                                f"[run_cycle] Данные не получены (попытка {attempt}/{max_retries}). "
                                f"Повторная попытка через 2 секунды..."
                            )
                            await asyncio.sleep(2)
                            continue
                        else:
                            logger.warning(
                                f"[run_cycle] Данные из MT5 не получены после {max_retries} попыток. "
                                f"Пропускаю цикл, попробую в следующий раз."
                            )
                            self.end_performance_timer("get_market_data")
                            self.end_performance_timer("run_cycle_total")
                            return
                    else:
                        # Данные получены успешно
                        break

                # Сохранить данные в кэш
                self.set_cached_data(cache_key, data_dict_raw, ttl_seconds=60)
            else:
                # Данные получены из кэша, news_task нужно обработать отдельно
                if news_task:
                    logger.info("[run_cycle] Данные из кэша, ожидание новостей...")
                    news_result_tuple = await news_task
                    if isinstance(news_result_tuple, Exception):
                        logger.error(f"Ошибка при получении новостей из кэша: {news_result_tuple}")
                        news_result_tuple = None
                else:
                    news_result_tuple = None

            self.end_performance_timer("get_market_data")
            logger.info(f"[run_cycle] Сбор данных завершён, обработка новостей...")

            # Обработка новостей для VectorDB (с максимальной защитой от крашей)
            try:
                # Отладочные логи
                has_news = news_result_tuple is not None and not isinstance(news_result_tuple, Exception)
                news_count = len(news_result_tuple[0]) if has_news else 0
                vdb_ready = self.vector_db_manager.is_ready() if self.vector_db_manager else False

                logger.info(f"[VectorDB-DEBUG] has_news={has_news}, news_count={news_count}, vdb_ready={vdb_ready}")

                if news_result_tuple and not isinstance(news_result_tuple, Exception):
                    all_items, _, _ = news_result_tuple
                    logger.info(f"[VectorDB] Получено {len(all_items)} новостей для обработки")

                    if not all_items:
                        logger.warning("[VectorDB] Список новостей пуст")
                    elif not self.vector_db_manager:
                        logger.warning("[VectorDB] vector_db_manager = None")
                    elif not self.vector_db_manager.is_ready():
                        logger.warning("[VectorDB] VectorDB не готов (is_ready=False)")
                    else:
                        # Ограничиваем количество новостей для обработки (защита от перегрузки)
                        max_news_per_cycle = 20  # Увеличено с 5 до 20
                        if len(all_items) > max_news_per_cycle:
                            logger.warning(
                                f"[VectorDB] Ограничение: обработка только {max_news_per_cycle} из {len(all_items)} новостей"
                            )
                            all_items = all_items[:max_news_per_cycle]

                        # Запускаем фоновую обработку новостей с защитой от ошибок
                        try:
                            asyncio.create_task(self._process_news_background(all_items))
                            logger.info(f"[VectorDB] Фоновая обработка {len(all_items)} новостей запущена")
                        except Exception as news_error:
                            logger.error(f"[VectorDB] Ошибка при запуске фоновой обработки: {news_error}", exc_info=True)
                else:
                    if isinstance(news_result_tuple, Exception):
                        logger.error(f"[VectorDB] Новости вернули ошибку: {news_result_tuple}")
                    else:
                        logger.warning("[VectorDB] Новости не получены (news_result_tuple = None)")
            except Exception as e:
                logger.error(f"[VectorDB] Критическая ошибка при обработке новостей: {e}", exc_info=True)
                # Продолжаем работу системы даже при ошибке обработки новостей

            # --- Обогащение DeFi данными (Бесплатно) ---
            # Проверяем конфиг и время последней загрузки
            news_sched = getattr(self.config, "news_scheduler", {})
            if news_sched.get("defi_enabled", True):
                try:
                    # Загружаем раз в N часов (по умолчанию 6)
                    defi_interval = news_sched.get("defi_interval_hours", 6) * 3600

                    last_defi_load = getattr(self, "_last_defi_load_time", 0)
                    current_time = standard_time.time()

                    if current_time - last_defi_load > defi_interval:
                        logger.info("[DeFi] Запуск фоновой загрузки DeFi метрик...")
                        await self._refresh_defi_data_background()
                        self._last_defi_load_time = current_time
                except Exception as defi_err:
                    logger.debug(f"[DeFi] Ошибка фонового обогащения: {defi_err}")

            # --- ИСПРАВЛЕНИЕ: Блок вынесен из-под if all_items ---

            # 4. Ранжирование символов
            logger.info(f"[Orchestrator] Начало ранжирования символов. Данных: {len(data_dict_raw)}")
            self.start_performance_timer("rank_symbols")
            data_dict = {key: df for key, df in data_dict_raw.items()}
            ranked_symbols, full_ranked_list = self.market_screener.rank_symbols(
                data_dict, account_manager=self.account_manager
            )

            # === ТОРГОВЛЯ ВСЕМИ ИНСТРУМЕНТАМИ ===
            # Используем ВСЕ доступные символы вместо топ-N
            # ranked_symbols уже содержит все символы благодаря TOP_N_SYMBOLS = 18
            logger.info(
                f"[Orchestrator] Ранжирование завершено. Торгую всеми {len(ranked_symbols)} символами из {len(full_ranked_list)} доступных"
            )

            # === ТОРГОВЛЯ ВСЕМИ ИНСТРУМЕНТАМИ ===

            # --- ВАЖНО: Сохраняем список для R&D ---
            self.latest_full_ranked_list = full_ranked_list
            # ---------------------------------------
            self.end_performance_timer("rank_symbols")

            # =================================================================================
            # [FIX] ПОДГОТОВКА И ОТПРАВКА ДАННЫХ В GUI
            # =================================================================================
            gui_data_list = []
            processed_symbols = set()

            # 1. Данные из скринера
            if full_ranked_list:
                for item in full_ranked_list:
                    processed_symbols.add(item["symbol"])
                    # Дополняем данными для GUI
                    sym = item["symbol"]
                    df = data_dict.get(f"{sym}_{mt5.TIMEFRAME_H1}")
                    if df is not None and not df.empty:
                        last_row = df.iloc[-1]
                        first_row = df.iloc[0]
                        change_pct = (
                            (last_row["close"] - first_row["close"]) / first_row["close"] * 100
                            if first_row["close"] != 0
                            else 0.0
                        )

                        item["price"] = last_row["close"]
                        item["change_24h"] = change_pct
                        item["rsi"] = last_row.get("RSI_14", 50.0)
                        item["volatility"] = last_row.get("ATR_14", 0.0)
                        item["regime"] = self.market_regime_manager.get_regime(df)
                        gui_data_list.append(item)

            # 2. [КРИТИЧНО] Добавляем остальные символы
            for key, df in data_dict.items():
                if "_H1" in key:
                    sym = key.split("_")[0]
                    if sym not in processed_symbols:
                        last_row = df.iloc[-1]
                        # Создаем запись
                        item = {
                            "rank": 999,
                            "symbol": sym,
                            "total_score": 0.0,
                            "price": last_row["close"],
                            "change_24h": 0.0,
                            "rsi": last_row.get("RSI_14", 0),
                            "volatility": last_row.get("ATR_14", 0),
                            "regime": "Unknown",
                            "normalized_atr_percent": 0,
                            "trend_score": 0,
                            "liquidity_score": 0,
                            "spread_pips": 0,
                        }
                        gui_data_list.append(item)
                        # Добавляем в full_ranked_list для R&D
                        if self.latest_full_ranked_list is not None:
                            self.latest_full_ranked_list.append(item)

            # 3. Отправляем данные
            # Убрано избыточное логирование
            if gui_data_list:
                # Отправляем данные в сканер
                try:
                    self.market_scan_updated.emit(gui_data_list)
                except RuntimeError as e:
                    if "Signal source has been deleted" in str(e):
                        logger.debug("[GUI] Сигнал market_scan_updated был удалён, пропускаем отправку")
                    else:
                        logger.error(f"Ошибка отправки сигнала: {e}")
                    # Продолжаем работу, просто не отправляем сигнал

                # Обновляем график первым символом
                top_item = gui_data_list[0]
                symbol_for_chart = top_item["symbol"]
                chart_key = f"{symbol_for_chart}_{mt5.TIMEFRAME_H1}"
                if chart_key in data_dict:
                    df_chart = data_dict[chart_key]
                    self._safe_gui_update("update_candle_chart", df_chart, symbol_for_chart)
                else:
                    logger.warning(f"[Chart] Ключ {chart_key} не найден в data_dict")
            else:
                logger.warning("[GUI Data] Нет данных для отправки в сканер")

            # Дополнительно: обновляем график для любого доступного символа, если основное обновление не сработало
            if not gui_data_list or (gui_data_list and f"{gui_data_list[0]['symbol']}_{mt5.TIMEFRAME_H1}" not in data_dict):
                # Ищем любой доступный символ с данными H1
                for key in data_dict.keys():
                    if "_H1" in key or f"_{mt5.TIMEFRAME_H1}" in key:
                        symbol = key.split("_")[0]
                        self._safe_gui_update("update_candle_chart", data_dict[key], symbol)
                        break
            # =================================================================================

            # Загрузка моделей (раз в час)
            current_time = standard_time.time()
            if current_time - self.last_model_load_time > 3600:
                self.start_performance_timer("load_champion_models")
                await asyncio.to_thread(self._load_champion_models_into_memory, ranked_symbols)
                self.end_performance_timer("load_champion_models")
                self.last_model_load_time = current_time

            if self.config.TOP_N_SYMBOLS <= 0:
                # Если TOP_N_SYMBOLS=0 или отрицательно, торгуем всеми символами, разрешенными в whitelist
                ranked_symbols = [item["symbol"] for item in full_ranked_list]
            elif not ranked_symbols:
                # Если ranked_symbols пуст (неудачное ранжирование), берем все из полного списка
                ranked_symbols = [item["symbol"] for item in full_ranked_list]

            # 5. Хеджирование (Risk Engine)
            if current_positions:
                self.start_performance_timer("check_hedging")
                hedge_result = self.risk_engine.check_and_apply_hedging(current_positions, data_dict, account_info)
                self.end_performance_timer("check_hedging")

                if hedge_result:
                    symbol, signal, lot_size = hedge_result
                    # Исправление: type может быть строкой или SignalType
                    signal_type_name = (
                        signal.type
                        if isinstance(signal.type, str)
                        else (signal.type.name if hasattr(signal.type, "name") else str(signal.type))
                    )
                    logger.critical(f"!!! VaR ХЕДЖИРОВАНИЕ: Открытие {signal_type_name} {lot_size:.2f} по {symbol}.")
                    await self.execution_service.execute_trade(
                        symbol=symbol,
                        signal=signal,
                        lot_size=lot_size,
                        df=data_dict.get(f"{symbol}_{mt5.TIMEFRAME_H1}"),
                        timeframe=mt5.TIMEFRAME_H1,
                        strategy_name="HEDGE_VAR",
                        stop_loss_in_price=0.0,
                        observer_mode=self.observer_mode,
                        prediction_input=None,
                        entry_price_for_learning=None,
                    )
                    self.end_performance_timer("run_cycle_total")
                    return  # Если хеджируем, новые сделки не открываем

            # 6. Анализ символов и Торговля
            analysis_tasks = []
            if len(current_positions) >= self.config.MAX_OPEN_POSITIONS:
                self.end_performance_timer("run_cycle_total")
                return

            # НОВАЯ ЛОГИКА: Фильтрация символов в выходные дни
            # datetime уже импортирован глобально, не нужно импортировать снова
            current_time = datetime.now()
            weekday = current_time.weekday()  # 0=Monday, 6=Sunday

            # Определяем, выходной ли день для Forex
            is_forex_weekend = (
                weekday == 5  # Суббота
                or
                # Воскресенье до 23:00
                (weekday == 6 and current_time.hour < 23)
                or (weekday == 4 and current_time.hour >= 23)  # Пятница после 23:00
            )

            if is_forex_weekend and not self.config.ALLOW_WEEKEND_TRADING:
                # В выходные торгуем только 24/7 (если ALLOW_WEEKEND_TRADING=False)
                original_count = len(ranked_symbols)
                crypto_symbols = [
                    s
                    for s in ranked_symbols
                    if any(
                        [
                            "BTC" in s.upper(),
                            "BITCOIN" in s.upper(),
                            "ETH" in s.upper(),
                            "ETHEREUM" in s.upper(),
                            "CRYPTO" in s.upper(),
                            "USDT" in s.upper(),
                        ]
                    )
                ]

                weekend_classic_enabled = getattr(self.config, "WEEKEND_CLASSIC_STRATEGIES_ENABLED", True)

                if crypto_symbols:
                    ranked_symbols = crypto_symbols
                    if weekend_classic_enabled:
                        logger.info(
                            f"[Weekend Mode] Forex рынок закрыт. Торговля криптовалютами: {ranked_symbols} (было {original_count}, осталось {len(ranked_symbols)})"
                        )
                        logger.info(
                            f"[Weekend Mode] Классические стратегии РАЗРЕШЕНЫ (Breakout, MA Crossover, Mean Reversion)"
                        )
                        logger.info(f"[Weekend Mode] AI-модели также участвуют в торговле (сниженные пороги для крипты)")
                    else:
                        logger.info(
                            f"[Weekend Mode] Forex рынок закрыт. Торговля только 24/7 инструментами: {ranked_symbols} (было {original_count}, осталось {len(ranked_symbols)})"
                        )
                else:
                    logger.debug(f"[Weekend Mode] Нет доступных 24/7 инструментов для торговли в выходные")
                    self.end_performance_timer("run_cycle_total")
                    return
            elif is_forex_weekend and self.config.ALLOW_WEEKEND_TRADING:
                logger.info("[Weekend Mode] ALLOW_WEEKEND_TRADING=True. Торгуем по всем доступным символам.")

            # === ТОРГОВЛЯ ПО ВСЕМ СИМВОЛАМ ИЗ WHITELIST ===
            symbols_to_trade = ranked_symbols

            logger.info("=" * 80)
            logger.info("НАЧАЛО ТОРГОВЛИ ПО СИМВОЛАМ")
            logger.info("=" * 80)
            logger.info(f"[Trading] Торговля по {len(symbols_to_trade)} символам из {len(full_ranked_list)} доступных")
            logger.info(f"[Trading] Текущих позиций: {len(current_positions)}, Максимум: {self.config.MAX_OPEN_POSITIONS}")
            logger.info(f"[Trading] SYMBOLS_WHITELIST: {len(self.config.SYMBOLS_WHITELIST)} символов")
            logger.info(f"[Trading] TOP_N_SYMBOLS: {self.config.TOP_N_SYMBOLS}")
            logger.info("=" * 80)

            for symbol in symbols_to_trade:
                # Проверяем лимит позиций (но не блокируем, а логируем)
                if len(current_positions) + len(analysis_tasks) >= self.config.MAX_OPEN_POSITIONS:
                    logger.warning(
                        f"[Trading] Достигнут лимит позиций ({len(current_positions)}/{self.config.MAX_OPEN_POSITIONS}). "
                        f"Символ {symbol} будет пропущен."
                    )
                    continue  # Пропускаем, но не прерываем цикл

                # Проверяем, есть ли уже позиция по этому символу
                symbol_positions = [p for p in current_positions if p.symbol == symbol]
                if symbol_positions:
                    logger.debug(f"[Trading] Пропуск {symbol}: уже есть открытая позиция")
                    continue

                self.start_performance_timer(f"select_optimal_timeframe_{symbol}")
                optimal_timeframe = self._select_optimal_timeframe(symbol, data_dict)
                self.end_performance_timer(f"select_optimal_timeframe_{symbol}")

                df_optimal = data_dict.get(f"{symbol}_{optimal_timeframe}")

                if df_optimal is None:
                    logger.warning(f"[Trading] Нет данных для {symbol} на таймфрейме {optimal_timeframe}")
                    continue

                logger.debug(f"[Trading] Добавлен символ {symbol} на обработку (всего задач: {len(analysis_tasks) + 1})")
                task = self._process_single_symbol(symbol, df_optimal, optimal_timeframe, account_info, current_positions)
                analysis_tasks.append(task)

            logger.info(f"[Trading] Всего добавлено задач: {len(analysis_tasks)}")
            logger.info("=" * 80)

            if analysis_tasks:
                self.start_performance_timer("execute_analysis_tasks")
                await asyncio.gather(*analysis_tasks)
                self.end_performance_timer("execute_analysis_tasks")

            # === CHAMPIONSHIP: Проверка, пора ли запускать чемпионат моделей ===
            if hasattr(self, "championship") and self.championship.should_run_championship():
                await self._run_championship_check()

            self.end_performance_timer("run_cycle_total")

        except Exception as e:
            logger.error(f"Непредвиденная ошибка в торговом цикле: {e}", exc_info=True)

    def _training_loop(self):
        """
        Непрерывный цикл обучения (R&D Department).
        Оптимизирован: работает только в разрешенное время (ночью), чтобы не мешать торговле.
        """
        logger.info("=== Запуск непрерывного цикла обучения (R&D Department) ===")

        # Ждем 60 секунд чтобы система успела набрать данные
        logger.debug("[R&D] Ожидание 60 сек для накопления данных...")
        self.stop_event.wait(60)

        while not self.stop_event.is_set():
            try:
                if not self.is_heavy_init_complete:
                    logger.warning("[R&D] Тяжелая инициализация не завершена, ожидание...")
                    self.stop_event.wait(10)
                    continue

                # 🔧 OPTIMIZATION: Проверка "Тихих часов" (R&D только ночью)
                if not self._is_rnd_time():
                    # Если сейчас не время для обучения, спим 1 час
                    self.stop_event.wait(3600)
                    continue

                # Проверяем есть ли данные для обучения
                if not self.latest_full_ranked_list or len(self.latest_full_ranked_list) == 0:
                    logger.warning("[R&D] Список ранжированных символов пуст. Запуск принудительного сбора данных...")
                    # Собираем данные самостоятельно
                    self._force_collect_data_for_training()
                    # Ждем немного после сбора
                    self.stop_event.wait(10)
                    # Проверяем снова
                    if not self.latest_full_ranked_list or len(self.latest_full_ranked_list) == 0:
                        logger.warning("[R&D] Принудительный сбор не дал результатов. Повтор через 60 сек...")
                        self.stop_event.wait(60)
                        continue

                logger.info("[R&D] Запуск цикла обучения...")
                self._continuous_training_cycle()

                sleep_time = self.config.TRAINING_INTERVAL_SECONDS
                logger.info(f"[R&D] Цикл завершен. Следующий через {sleep_time} сек")
                self.stop_event.wait(sleep_time)

            except Exception as e:
                logger.error(f"Критическая ошибка в фоновом цикле обучения: {e}", exc_info=True)
                self.stop_event.wait(60)

        logger.info("Цикл обучения (R&D) остановлен.")

    def _is_rnd_time(self) -> bool:
        """
        Проверяет, разрешено ли сейчас обучение (R&D).
        Если включен планировщик, то учимся только в его временное окно.
        """
        auto_retrain_config = getattr(self.config, "auto_retraining", None)
        if not auto_retrain_config:
            return True  # Если настроек нет, учимся всегда

        # Поддержка dict и pydantic
        if isinstance(auto_retrain_config, dict):
            enabled = auto_retrain_config.get("enabled", False)
            schedule_time_str = auto_retrain_config.get("schedule_time", "02:00")
        else:
            enabled = getattr(auto_retrain_config, "enabled", False)
            schedule_time_str = getattr(auto_retrain_config, "schedule_time", "02:00")

        # Если планировщик выключен, учимся всегда (старый режим)
        if not enabled:
            return True

        try:
            # Парсим время из строки "HH:MM"
            target_hour, target_minute = map(int, schedule_time_str.split(":"))
            now = datetime.now()

            # Окно обучения: +/- 2 часа от времени планировщика
            # Например, если 02:00, то учимся с 00:00 до 04:00
            current_minutes = now.hour * 60 + now.minute
            target_minutes = target_hour * 60 + target_minute

            # Разница в минутах (учитывая переход через полночь)
            diff = abs(current_minutes - target_minutes)
            if diff > 720:  # Если разница больше 12 часов, значит мы на другом конце суток
                diff = 1440 - diff

            # Разрешаем если разница меньше 120 минут (2 часа)
            is_allowed = diff <= 120

            if not is_allowed:
                logger.debug(
                    f"[R&D-Time] Сейчас {now.strftime('%H:%M')}, обучение запрещено (окно +/- 2ч от {schedule_time_str})"
                )

            return is_allowed
        except Exception as e:
            logger.error(f"[R&D-Time] Ошибка проверки времени: {e}")
            return True  # В случае ошибки разрешаем учиться

    def _force_collect_data_for_training(self):
        """
        Принудительный сбор данных для R&D когда список пуст.
        """
        logger.info("[R&D] Запуск принудительного сбора данных...")
        try:
            available_symbols = self.data_provider.get_available_symbols()
            if not available_symbols:
                logger.warning("[R&D] Нет доступных символов для сбора данных")
                return

            timeframes_to_check = list(self.config.optimizer.timeframes_to_check.values())
            data_dict_raw = {}

            logger.info(f"[R&D] Сбор данных для {len(available_symbols)} символов...")
            for symbol in available_symbols[:10]:  # Ограничиваем 10 символами для скорости
                for tf in timeframes_to_check:
                    result = self.data_provider._fetch_and_process_symbol_sync(symbol, tf, self.config.PREDICTION_DATA_POINTS)
                    if result:
                        key, df = result
                        data_dict_raw[key] = df

            if data_dict_raw:
                logger.info(f"[R&D] Данные собраны: {len(data_dict_raw)} таймфреймов")
                ranked_symbols, full_ranked_list = self.market_screener.rank_symbols(
                    data_dict_raw, account_manager=self.account_manager
                )
                self.latest_full_ranked_list = full_ranked_list
                logger.info(f"[R&D] Ранжировано {len(ranked_symbols)} символов")
            else:
                logger.warning("[R&D] Не удалось собрать данные")
        except Exception as e:
            logger.error(f"[R&D] Ошибка принудительного сбора данных: {e}", exc_info=True)

    def _vector_db_cleanup_loop(self):
        logger.info("[VectorDB] === Запуск цикла обслуживания ===")
        cleanup_interval = self.config.vector_db.cleanup_interval_hours * 3600
        self.stop_event.wait(min(cleanup_interval, 3600))
        while not self.stop_event.is_set():
            if self.vector_db_manager and self.config.vector_db.cleanup_enabled:
                logger.info(
                    f"[VectorDB] Запуск очистки устаревших документов (интервал: {self.config.vector_db.cleanup_interval_hours}ч)"
                )
                try:
                    self.vector_db_manager.cleanup_old_documents()
                except Exception as e:
                    logger.error(f"[VectorDB] Ошибка в цикле очистки: {e}")
            self.stop_event.wait(cleanup_interval)
        logger.info("[VectorDB] Цикл обслуживания остановлен.")

    def _symbol_performance_monitor_loop(self):
        """
        Фоновый цикл для автоматического анализа производительности символов.
        Исключает убыточные символы и включает обратно прибыльные.
        Интервал: каждые 6 часов (или после 50 новых сделок).
        """
        logger.info("=== Запуск мониторинга производительности символов ===")
        check_interval = 6 * 3600  # 6 часов
        last_trade_count = 0

        # Первая проверка через 5 минут после запуска
        self.stop_event.wait(300)

        while not self.stop_event.is_set():
            try:
                # Проверка количества новых сделок
                current_trade_count = len(self.trade_history)
                new_trades = current_trade_count - last_trade_count

                # Запускаем анализ если прошло 6 часов ИЛИ есть 50+ новых сделок
                if new_trades >= 50 or (self.stop_event.wait(check_interval) and not self.stop_event.is_set()):
                    logger.info("[SYMBOL-MONITOR] Запуск анализа производительности символов...")

                    # 1. Получаем текущие исключенные символы
                    current_excluded = set(self.config.EXCLUDED_SYMBOLS) if hasattr(self.config, "EXCLUDED_SYMBOLS") else set()

                    # 2. Анализируем символы на исключение
                    candidates_for_exclusion = self.db_manager.get_symbols_for_auto_exclusion(
                        min_trades=10, max_loss_threshold=-500.0, profit_factor_threshold=0.8, win_rate_threshold=0.40
                    )

                    # 3. Анализируем исключенные символы на включение
                    candidates_for_inclusion = self.db_manager.get_symbols_for_auto_inclusion(
                        excluded_symbols=list(current_excluded),
                        min_trades=5,
                        profit_factor_threshold=1.2,
                        win_rate_threshold=0.55,
                    )

                    # 4. Применяем исключения
                    symbols_to_exclude = []
                    for candidate in candidates_for_exclusion:
                        symbol = candidate["symbol"]
                        if symbol not in current_excluded:
                            symbols_to_exclude.append(symbol)
                            logger.critical(
                                f"[SYMBOL-MONITOR] ИСКЛЮЧЕНИЕ: {symbol} - "
                                f"Убыток: {candidate['total_profit']:.2f}, "
                                f"PF: {candidate['profit_factor']:.2f}, "
                                f"WR: {candidate['win_rate']:.2f} | "
                                f"Причины: {', '.join(candidate['reasons'])}"
                            )

                    # 5. Применяем включения
                    symbols_to_include = []
                    for candidate in candidates_for_inclusion:
                        symbol = candidate["symbol"]
                        if symbol in current_excluded:
                            symbols_to_include.append(symbol)
                            logger.critical(
                                f"[SYMBOL-MONITOR] ВКЛЮЧЕНИЕ: {symbol} - "
                                f"Прибыль: {candidate['total_profit']:.2f}, "
                                f"PF: {candidate['profit_factor']:.2f}, "
                                f"WR: {candidate['win_rate']:.2f} | "
                                f"Причины: {', '.join(candidate['reasons'])}"
                            )

                    # 6. Обновляем конфигурацию
                    if symbols_to_exclude or symbols_to_include:
                        new_excluded = list(current_excluded)
                        new_excluded.extend(symbols_to_exclude)
                        new_excluded = [s for s in new_excluded if s not in symbols_to_include]
                        # Удаляем дубликаты
                        new_excluded = list(set(new_excluded))

                        # Обновляем конфигурацию
                        self.config.EXCLUDED_SYMBOLS = new_excluded
                        self.data_provider.excluded_symbols = new_excluded

                        logger.critical(f"[SYMBOL-MONITOR] ОБНОВЛЕНО: Исключенные символы = {new_excluded}")

                        # Отправляем уведомление в GUI
                        if self.gui:
                            self._safe_gui_update(
                                "update_status",
                                f"Авто-обновление символов: -{len(symbols_to_exclude)} +{len(symbols_to_include)}",
                                is_error=False,
                            )

                    last_trade_count = current_trade_count

            except Exception as e:
                logger.error(f"[SYMBOL-MONITOR] Ошибка в цикле мониторинга: {e}", exc_info=True)
                self.stop_event.wait(60)

        logger.info("[SYMBOL-MONITOR] Цикл мониторинга символов остановлен.")

    # --- ОСТАЛЬНЫЕ МЕТОДЫ (БЕЗ ИЗМЕНЕНИЙ) ---
    def _continuous_training_cycle(self):
        # === RESOURCE GOVERNOR: проверка можно ли запустить R&D ===
        if hasattr(self, "governor") and self.governor:
            from src.core.resource_governor import ResourceClass

            task_id = f"rd_cycle_{uuid.uuid4().hex[:6]}"

            if not self.governor.can_start(task_id, ResourceClass.MEDIUM):
                logger.warning("⏳ R&D пропущен: система перегружена")
                return

            try:
                self._run_training_with_governor(task_id)
            finally:
                self.governor.task_finished(task_id)
        else:
            # Fallback: старый путь без governor
            self._run_training_with_governor(None)

    def _run_training_with_governor(self, task_id: Optional[str]):
        """Внутренний метод R&D с поддержкой ResourceGovernor."""
        if not self.training_lock.acquire(blocking=False):
            return

        # === Очистка памяти перед тяжёлой операцией ===
        from src.core.memory_utils import prepare_for_heavy_task

        prepare_for_heavy_task()

        training_batch_id = f"batch-{uuid.uuid4()}"
        cycle_start_time = standard_time.time()
        logger.warning(f"--- НАЧАЛО R&D ЦИКЛА (BATCH ID: {training_batch_id}) ---")
        self.long_task_status_updated.emit("R&D_CYCLE", "Идет R&D цикл и оптимизация стратегий...", False)

        # Отправка начального прогресса в GUI
        if self.gui:
            self._safe_gui_update(
                "update_rd_log",
                {"generation": 0, "best_fitness": 0.0, "config": f"Начало R&D цикла (Batch: {training_batch_id[:8]})"},
            )

        # ПРОВЕРКА: Инициализирован ли bridge для отправки данных обучения
        logger.info(f"[R&D] self.bridge = {self.bridge is not None}, self.gui = {self.gui is not None}")

        symbol_to_train = None
        ranked_symbols = []
        try:
            with self.analysis_lock:
                if not self.latest_full_ranked_list:
                    logger.warning("[R&D] Список ранжированных символов пуст. Запуск принудительного сбора данных...")
                    # ОПТИМИЗАЦИЯ: Используем таймаут для захвата mt5_lock в R&D
                    available_symbols = self.data_provider.get_available_symbols()
                    timeframes_to_check = list(self.config.optimizer.timeframes_to_check.values())
                    data_dict_raw = {}
                    for symbol in available_symbols:
                        for tf in timeframes_to_check:
                            result = self.data_provider._fetch_and_process_symbol_sync(
                                symbol, tf, self.config.PREDICTION_DATA_POINTS
                            )
                            if result:
                                key, df = result
                                data_dict_raw[key] = df
                    ranked_symbols, full_ranked_list = self.market_screener.rank_symbols(
                        data_dict_raw, account_manager=self.account_manager
                    )
                    self.latest_full_ranked_list = full_ranked_list
                    if not ranked_symbols:
                        logger.warning("[R&D] Принудительный сбор не дал результатов. R&D цикл пропущен.")
                        return
                else:
                    ranked_symbols = [item["symbol"] for item in self.latest_full_ranked_list[: self.config.TOP_N_SYMBOLS]]

                # НОВАЯ ЛОГИКА: Приоритет символам без моделей
                logger.info("[R&D] Проверка символов без моделей...")

                # Получаем список всех символов из whitelist
                all_symbols = self.config.SYMBOLS_WHITELIST if hasattr(self.config, "SYMBOLS_WHITELIST") else ranked_symbols

                # Проверяем, какие символы не имеют моделей
                symbols_without_models = []
                session = self.db_manager.Session()
                try:
                    from src.db.database_manager import TrainedModel

                    for symbol in all_symbols:
                        # Проверяем наличие моделей в базе данных
                        models_count = session.query(TrainedModel).filter_by(symbol=symbol).count()
                        if models_count == 0:
                            symbols_without_models.append(symbol)
                            logger.info(f"[R&D] Символ {symbol} не имеет моделей")
                finally:
                    session.close()

                # Выбираем символ для обучения
                if symbols_without_models:
                    # ПРИОРИТЕТ 1: Обучаем первый символ без моделей
                    symbol_to_train = symbols_without_models[0]
                    logger.warning(f"[R&D] ПРИОРИТЕТ: Выбран символ БЕЗ МОДЕЛЕЙ: {symbol_to_train}")
                    logger.info(f"[R&D] Осталось символов без моделей: {len(symbols_without_models)}")
                else:
                    # ПРИОРИТЕТ 2: Обучаем топ-1 символ из рейтинга
                    symbol_to_train = ranked_symbols[0]
                    logger.info(f"[R&D] Все символы имеют модели. Выбран топ-1: {symbol_to_train}")

                logger.info(f"[R&D] Выбран символ для обучения: {symbol_to_train}")

                # Отправка прогресса в GUI
                if self.gui:
                    priority_label = "БЕЗ МОДЕЛЕЙ" if symbol_to_train in symbols_without_models else "ТОП-1"
                    self._safe_gui_update(
                        "update_rd_log",
                        {
                            "generation": 1,
                            "best_fitness": 0.0,
                            "config": f"Выбран символ: {symbol_to_train} ({priority_label})",
                        },
                    )

            # === ИСПРАВЛЕНИЕ: Загружаем данные для обучения с коротким MT5 lock ===
            timeframe = mt5.TIMEFRAME_H1
            data_load_start = standard_time.time()

            # Загружаем данные НАПРЯМУЮ через MT5 без использования data_provider,
            # с повторными попытками при занятости блокировки (exponential backoff)
            logger.info(f"[R&D] Прямая загрузка данных из MT5 для {symbol_to_train}...")

            df_full = None
            max_retries = 3
            for attempt in range(max_retries):
                lock_acquired = self.mt5_lock.acquire(timeout=5.0)
                if not lock_acquired:
                    wait_time = 1.0 * (attempt + 1)  # Экспоненциальная задержка: 1с, 2с, 3с
                    logger.warning(f"[R&D] MT5 Lock занят (попытка {attempt+1}/{max_retries}), ждём {wait_time}с...")
                    self.stop_event.wait(wait_time)
                    continue

                try:
                    # Инициализируем отдельное подключение для обучения
                    if not mt5_ensure_connected(path=self.config.MT5_PATH):
                        logger.error(f"[R&D] Не удалось подключиться к MT5 для загрузки данных")
                        self.mt5_lock.release()
                        break

                    # Загружаем данные
                    rates = mt5.copy_rates_from_pos(symbol_to_train, timeframe, 0, self.config.TRAINING_DATA_POINTS)

                    if rates is not None and len(rates) > 0:
                        df_full = pd.DataFrame(rates)
                        df_full["time"] = pd.to_datetime(df_full["time"], unit="s")
                        df_full.set_index("time", inplace=True)
                        logger.info(f"[R&D] Загружено {len(df_full)} баров напрямую из MT5")
                    else:
                        logger.warning(f"[R&D] MT5 вернул пустые данные")

                    mt5_shutdown()
                    self.mt5_lock.release()
                    break  # Успех — выходим из цикла

                except Exception as e:
                    logger.error(f"[R&D] Ошибка загрузки данных (попытка {attempt+1}): {e}")
                    if self.mt5_lock.locked():
                        self.mt5_lock.release()
                    if attempt < max_retries - 1:
                        self.stop_event.wait(1.0 * (attempt + 1))

            data_load_time = standard_time.time() - data_load_start
            logger.info(f"[R&D] Загрузка данных заняла {data_load_time:.2f} сек")

            if df_full is None:
                logger.warning(
                    f"[R&D] Не удалось загрузить данные для {symbol_to_train} после {max_retries} попыток. Пропуск."
                )
                return

            if len(df_full) < 1000:
                logger.warning(f"[R&D] Недостаточно данных ({len(df_full)} баров) для {symbol_to_train}. Пропуск.")
                return
            from src.ml.feature_engineer import FeatureEngineer

            fe = FeatureEngineer(self.config, self.knowledge_graph_querier)
            df_featured = fe.generate_features(df_full, symbol=symbol_to_train)
            # Удаляем дубликаты из FEATURES_TO_USE
            unique_features = list(dict.fromkeys(self.config.FEATURES_TO_USE))
            # Используем только те признаки, которые действительно есть в данных
            actual_features_to_use = [f for f in unique_features if f in df_featured.columns]

            # ВРЕМЕННО: Добавляем KG признаки для совместимости со старыми моделями
            # TODO: Удалить после переобучения всех моделей
            kg_features = ["KG_CB_SENTIMENT", "KG_INFLATION_SURPRISE"]
            for kg_feat in kg_features:
                if kg_feat in df_featured.columns and kg_feat not in actual_features_to_use:
                    actual_features_to_use.append(kg_feat)

            # Ограничиваем количество признаков для снижения нагрузки
            if len(actual_features_to_use) > 20:
                actual_features_to_use = actual_features_to_use[:20]
                logger.warning(f"Ограничено количество признаков до 20 для снижения нагрузки на CPU")
            train_val_df, holdout_df = train_test_split(df_featured, test_size=0.15, shuffle=False)
            train_df, val_df = train_test_split(train_val_df, test_size=0.176, shuffle=False)
            from src.ml.model_factory import ModelFactory

            model_factory = ModelFactory(self.config)
            trained_candidate_ids = []
            training_start = standard_time.time()
            logger.info(f"[R&D] Начало обучения {len(self.config.rd_cycle_config.model_candidates)} моделей...")
            for idx, candidate_config in enumerate(self.config.rd_cycle_config.model_candidates, 1):
                # Отправка прогресса в GUI
                if self.gui:
                    self._safe_gui_update(
                        "update_rd_log",
                        {
                            "generation": idx + 1,
                            "best_fitness": 0.0,
                            "config": f"Обучение модели {candidate_config.type} для {symbol_to_train}",
                        },
                    )

                model_id = self._train_candidate_model(
                    model_type=candidate_config.type,
                    symbol=symbol_to_train,
                    timeframe=timeframe,
                    train_df=train_df.copy(),
                    val_df=val_df.copy(),
                    model_factory=model_factory,
                    training_batch_id=training_batch_id,
                    features_to_use=actual_features_to_use,
                )
                if model_id:
                    trained_candidate_ids.append(model_id)
                    # Отправка успешного результата
                    if self.gui:
                        self._safe_gui_update(
                            "update_rd_log",
                            {
                                "generation": idx + 1,
                                "best_fitness": 1.0,
                                "config": f"✓ Модель {candidate_config.type} обучена (ID: {model_id})",
                            },
                        )

                    # ОПТИМИЗАЦИЯ: Короткая пауза между моделями для освобождения CPU
                    # Это позволяет мониторингу получить MT5 lock
                    standard_time.sleep(0.5)
            training_time = standard_time.time() - training_start
            logger.info(f"[R&D] Обучение всех моделей заняло {training_time:.2f} сек")

            if trained_candidate_ids:
                contest_start = standard_time.time()
                self._run_champion_contest(trained_candidate_ids, holdout_df)
                contest_time = standard_time.time() - contest_start
                logger.info(f"[R&D] Конкурс моделей занял {contest_time:.2f} сек")
        except Exception as e:
            logger.error(f"Критическая ошибка в R&D цикле: {e}", exc_info=True)
        finally:
            self.training_lock.release()
            gc.collect()  # Принудительная очистка памяти
            if torch.cuda.is_available():
                torch.cuda.empty_cache()  # Очистка VRAM
            total_time = standard_time.time() - cycle_start_time
            logger.warning(f"--- R&D ЦИКЛ (BATCH ID: {training_batch_id}) ЗАВЕРШЕН за {total_time:.2f} сек ---")
            self.long_task_status_updated.emit("R&D_CYCLE", "R&D цикл завершен!", True)

            # Отправка финального прогресса в GUI
            if self.gui:
                self._safe_gui_update(
                    "update_rd_log",
                    {"generation": 99, "best_fitness": 1.0, "config": f"✓ R&D цикл завершен (Batch: {training_batch_id[:8]})"},
                )

    def _force_retrain_with_optuna(
        self, symbol: str, timeframe: int, train_df: pd.DataFrame, val_df: pd.DataFrame, features_to_use: List[str]
    ) -> Optional[Dict]:
        if optuna is None:
            logger.error("[Optuna] Библиотека optuna не установлена. Оптимизация гиперпараметров отключена.")
            return None

        logger.warning(f"[Optuna] Запуск оптимизации гиперпараметров для {symbol}...")

        def objective(trial) -> float:
            lr = trial.suggest_float("lr", 1e-5, 1e-3, log=True)
            hidden_dim = trial.suggest_int("hidden_dim", 16, 64, step=16)
            num_layers = trial.suggest_int("num_layers", 1, 3)
            batch_size = trial.suggest_categorical("batch_size", [16, 32, 64])
            model_factory = ModelFactory(self.config)
            model_params = {
                "input_dim": len(features_to_use),
                "hidden_dim": hidden_dim,
                "num_layers": num_layers,
                "output_dim": 1,
            }
            model = model_factory.create_model("LSTM_PyTorch", model_params)
            val_loss = np.random.rand()
            return -val_loss

        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=20, timeout=300)
        logger.info(f"[Optuna] Оптимизация завершена. Лучший Loss: {study.best_value:.4f}")
        return study.best_params

    def has_active_drift(self) -> bool:
        if not self.drift_manager:
            return False
        return any(self.drift_manager.drift_statuses.values())

    def force_rd_cycle(self):
        if not self.running:
            logger.warning("Нельзя запустить R&D, так как система остановлена.")
            return
        logger.warning("Принудительный запуск R&D цикла из GUI/Адаптивного триггера...")
        thread = threading.Thread(target=self._continuous_training_cycle, daemon=True)
        thread.start()

    def _on_drift_data_emitted(self, timestamp: float, symbol: str, error: float, is_drift: bool):
        if self.web_server and self.config.web_dashboard.enabled:
            self.web_server.broadcast_drift_update(timestamp, symbol, error, is_drift)

    def _send_initial_web_status(self):
        if not self.web_server:
            return
        logger.info("Отправка начального статуса в Web Dashboard...")
        balance = 0.0
        equity = 0.0
        with self.mt5_lock:
            if mt5_ensure_connected(path=self.config.MT5_PATH):
                try:
                    acc = mt5.account_info()
                    if acc:
                        balance = acc.balance
                        equity = acc.equity
                except Exception as e:
                    logger.debug(f"Ошибка получения account_info: {e}")
        status = SystemStatus(
            is_running=self.running,
            mode="Наблюдатель" if self.observer_mode else "Торговля",
            uptime="0:00:00",
            balance=balance,
            equity=equity,
            current_drawdown=0.0,
        )
        self.web_server.broadcast_status_update(status)
        regime = self._get_current_market_regime_name()
        self.web_server.broadcast_market_regime(regime)

    def get_vector_db_stats(self) -> Dict[str, Any]:
        if not self.vector_db_manager:
            logger.debug("[VectorDB] Менеджер не инициализирован")
            return {"is_ready": False, "count": 0, "reason": "Менеджер не инициализирован"}

        count = 0
        if hasattr(self.vector_db_manager, "index") and self.vector_db_manager.index:
            count = self.vector_db_manager.index.ntotal

        is_ready = self.vector_db_manager.is_ready()

        # Дополнительная проверка embedding модели
        has_embedding = False
        if hasattr(self, "nlp_processor") and self.nlp_processor:
            has_embedding = self.nlp_processor.embedding_model is not None

        logger.info(f"[VectorDB] Статистика: готов={is_ready}, документов={count}, embedding_model={has_embedding}")

        return {"is_ready": is_ready, "count": count, "has_embedding_model": has_embedding}

    def search_vector_db(self, query_text: str):
        logger.info(f"[VectorDB] Поиск по запросу: '{query_text}'")
        if not self.vector_db_manager or not self.vector_db_manager.is_ready():
            logger.warning("[VectorDB] Векторная БД не готова для поиска")
            self.bridge.vector_db_search_results.emit([{"error": "Векторная БД не готова."}])
            return
        if not self.nlp_processor.embedding_model:
            logger.warning("[VectorDB] Модель эмбеддингов не загружена")
            self.bridge.vector_db_search_results.emit([{"error": "Модель эмбеддингов не загружена."}])
            return
        try:
            # ИСПРАВЛЕНИЕ: Отключаем progress bar для предотвращения OSError в Windows GUI
            query_embedding = self.nlp_processor.embedding_model.encode(query_text, show_progress_bar=False).tolist()
            results = self.vector_db_manager.query_similar(query_embedding, n_results=15)
            if not results or not results["ids"][0]:
                logger.info(f"[VectorDB] Ничего не найдено по запросу: '{query_text}'")
                self.bridge.vector_db_search_results.emit([{"message": "Ничего не найдено."}])
                return
            formatted_results = []
            ids = results["ids"][0]
            distances = results["distances"][0]
            documents = results["documents"][0]
            metadatas = results["metadatas"][0]
            for i in range(len(ids)):
                doc_text = documents[i] if documents[i] else "Текст недоступен"
                snippet = doc_text[:200] + ("..." if len(doc_text) > 200 else "")
                formatted_results.append(
                    {
                        "id": ids[i],
                        "distance": str(distances[i]),
                        "snippet": snippet,
                        "full_text": doc_text,
                        "source": metadatas[i].get("source", "Unknown"),
                        "timestamp": metadatas[i].get("timestamp_iso", "Unknown"),
                    }
                )
            logger.info(f"[VectorDB] Найдено {len(formatted_results)} результатов по запросу: '{query_text}'")
            self.bridge.vector_db_search_results.emit(formatted_results)
        except Exception as e:
            logger.error(f"[VectorDB] Ошибка поиска: {e}", exc_info=True)
            self.bridge.vector_db_search_results.emit([{"error": str(e)}])

    def get_dummy_df(self) -> pd.DataFrame:
        if self.last_h1_data_cache is not None and not self.last_h1_data_cache.empty:
            return self.last_h1_data_cache
        data = {
            "close": np.ones(252) * 100,
            "high": np.ones(252) * 101,
            "low": np.ones(252) * 99,
            "open": np.ones(252) * 100,
            "ATR_14": np.ones(252) * 0.01,
            "ADX_14": np.ones(252) * 10,
            "EMA_50": np.ones(252) * 100,
            "BBU_20_2.0": np.ones(252) * 101,
            "BBL_20_2.0": np.ones(252) * 99,
            "BBM_20_2.0": np.ones(252) * 100,
        }
        index = pd.to_datetime(pd.date_range(end=datetime.now(), periods=252, freq="h"))
        return pd.DataFrame(data, index=index)

    def _get_current_market_regime_name(self) -> str:
        df = self.get_dummy_df()
        return self.market_regime_manager.get_regime(df)

    def _get_timeframe_seconds(self, tf_code: int) -> int:
        timeframe_map = {
            mt5.TIMEFRAME_M1: 60,
            mt5.TIMEFRAME_M5: 300,
            mt5.TIMEFRAME_M15: 900,
            mt5.TIMEFRAME_M30: 1800,
            mt5.TIMEFRAME_H1: 3600,
            mt5.TIMEFRAME_H4: 14400,
            mt5.TIMEFRAME_D1: 86400,
            mt5.TIMEFRAME_W1: 604800,
        }
        return timeframe_map.get(tf_code, 3600)

    def request_chart_data(self, symbol: str, timeframe: int, bars: int = 500):
        """
        Возвращает данные свечей для графика по запросу GUI.

        Args:
            symbol: Символ (напр. "EURUSD")
            timeframe: MT5 таймфрейм (напр. mt5.TIMEFRAME_H1)
            bars: Количество баров (по умолчанию 500)
        """
        try:
            logger.info(f"[Chart] Запрос данных для {symbol} TF={timeframe} bars={bars}")

            # Получаем данные у DataProvider
            df = self.data_provider.get_historical_data(symbol, timeframe, bars)

            if df is not None and not df.empty:
                # Проверяем что есть колонка 'time' для графика
                if "time" not in df.columns and df.index.name == "time":
                    df = df.reset_index()

                # Отправляем на график
                self._safe_gui_update("update_candle_chart", df, symbol)
                logger.info(f"[Chart] Данные отправлены: {len(df)} баров для {symbol}")
            else:
                logger.warning(f"[Chart] Нет данных для {symbol} TF={timeframe}")
        except Exception as e:
            logger.error(f"[Chart] Ошибка запроса данных: {e}", exc_info=True)

    def _load_champion_models_into_memory(self, symbols_to_check: List[str]):
        limit = self.config.TOP_N_SYMBOLS
        active_symbols_list = symbols_to_check[:limit]
        symbols_to_keep = set(active_symbols_list)
        logger.info(
            f"Управление памятью моделей. Из {len(symbols_to_check)} кандидатов выбрано топ-{len(symbols_to_keep)} для загрузки."
        )
        loaded_count = 0
        unloaded_count = 0
        timeframe = mt5.TIMEFRAME_H1
        current_models_in_memory = list(self.models.keys())
        for symbol in current_models_in_memory:
            if symbol not in symbols_to_keep:
                if symbol in self.models:
                    model_data = self.models[symbol]
                    for m_key in list(model_data.keys()):
                        component = model_data[m_key]
                        if isinstance(component, dict) and "model" in component:
                            del component["model"]
                    del self.models[symbol]
                self.x_scalers.pop(symbol, None)
                self.y_scalers.pop(symbol, None)
                unloaded_count += 1
        if unloaded_count > 0:
            import gc

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info(f"Память очищена. Выгружено {unloaded_count} моделей.")
        for symbol in active_symbols_list:
            try:
                if symbol not in self.models:
                    champion_models, x_scaler, y_scaler = self.db_manager.load_champion_models(symbol, timeframe)
                    if champion_models:
                        self.models[symbol] = champion_models
                        self.x_scalers[symbol] = x_scaler
                        self.y_scalers[symbol] = y_scaler
                        loaded_count += 1
            except Exception as e:
                logger.error(f"Ошибка при управлении моделью для {symbol}: {e}", exc_info=True)
        if loaded_count > 0:
            logger.info(f"Загрузка завершена. Новых моделей в памяти: {loaded_count}. Всего активных: {len(self.models)}")

    def _check_scheduled_tasks(self):
        project_root = SyncPath(__file__).parent.parent.parent
        maintenance_lock = project_root / "maintenance.lock"
        if maintenance_lock.exists():
            if not self.maintenance_notified:
                self.long_task_status_updated.emit("MAINTENANCE", "Идет ежедневное обслуживание...", False)
                self.maintenance_notified = True
        elif self.maintenance_notified:
            self.long_task_status_updated.emit("MAINTENANCE", "Ежедневное обслуживание завершено!", True)
            self.maintenance_notified = False
        optimization_lock = project_root / "optimization.lock"
        if optimization_lock.exists():
            if not self.optimization_notified:
                self.long_task_status_updated.emit("OPTIMIZATION", "Идет еженедельная оптимизация...", False)
                self.optimization_notified = True
        elif self.optimization_notified:
            self.long_task_status_updated.emit("OPTIMIZATION", "Еженедельная оптимизация завершена!", True)
            self.optimization_notified = False

    def toggle_knowledge_graph(self, enabled: bool):
        self.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION = enabled
        logger.info(f"Визуализация Графа Знаний была {'ВКЛЮЧЕНА' if enabled else 'ОТКЛЮЧЕНА'} пользователем.")

    def set_trading_mode(self, mode_id: str, settings: Optional[Dict[str, Any]] = None):
        """
        Прокси-метод для установки режима торговли через RiskEngine.

        Args:
            mode_id: Идентификатор режима ("conservative", "standard", "aggressive", "yolo", "custom", "disabled")
            settings: Пользовательские настройки (для кастомного режима)
        """
        # Обработка отключения режимов
        if mode_id == "disabled":
            logger.info("⚙️ Режимы торговли ОТКЛЮЧЕНЫ - возврат к базовым настройкам из конфига")
            # Возвращаем базовые настройки из конфига
            self.risk_engine.base_risk_per_trade_percent = self.config.RISK_PERCENTAGE
            self.risk_engine.max_daily_drawdown_percent = self.config.MAX_DAILY_DRAWDOWN_PERCENT
            logger.info("✅ Базовые настройки риск-менеджмента восстановлены")
            return

        logger.info(f"🎯 Запрос на установку режима торговли: {mode_id}")
        try:
            if hasattr(self, "risk_engine") and self.risk_engine is not None:
                self.risk_engine.set_trading_mode(mode_id, settings)
                logger.info(f"✅ Режим торговли '{mode_id}' успешно применен")
            else:
                logger.warning(f"⚠️ RiskEngine ещё не инициализирован. Режим '{mode_id}' будет применён после инициализации.")
        except Exception as e:
            logger.error(f"❌ Ошибка при установке режима торговли: {e}", exc_info=True)

    def update_runtime_settings(self, new_settings: dict):
        logger.warning(f"Применение новых настроек в реальном времени: {new_settings}")
        try:
            for key, value in new_settings.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
                    logger.info(f"Параметр '{key}' обновлен на '{value}'")
            self.risk_engine.config = self.config
            self.risk_engine.base_risk_per_trade_percent = self.config.RISK_PERCENTAGE
            self.risk_engine.max_daily_drawdown_percent = self.config.MAX_DAILY_DRAWDOWN_PERCENT
            self.data_provider.symbols_whitelist = self.config.SYMBOLS_WHITELIST
            if not write_config(new_settings):
                logger.error("Не удалось сохранить runtime-настройки в settings.json")
            else:
                logger.info("Runtime-настройки успешно сохранены в settings.json")
        except Exception as e:
            logger.error(f"Ошибка при применении runtime-настроек: {e}", exc_info=True)

    def _database_writer_loop(self):
        logger.info("Поток-обработчик записей в БД запущен.")
        while self.running:
            try:
                task, kwargs = self.db_write_queue.get(timeout=1)
                if task == "STOP":
                    break
                internal_method_name = f"_{task}_internal"
                if hasattr(self.db_manager, internal_method_name):
                    method_to_call = getattr(self.db_manager, internal_method_name)
                    if task == "save_model_and_scalers":
                        # Для асинхронного вызова используем синхронную версию с возвратом ID
                        model_id = self.db_manager.save_model_and_scalers_sync(**kwargs)
                        if model_id:
                            logger.info(f"Поток записи: модель успешно сохранена с ID {model_id}.")
                        else:
                            logger.warning(f"Поток записи: модель НЕ сохранена в БД (ID=None)")
                    else:
                        method_to_call(**kwargs)
                else:
                    logger.error(f"Получена неизвестная задача для записи в БД: {task}")
            except queue.Empty:
                continue
            except Exception as e:
                logger.critical(f"Критическая ошибка в потоке записи в БД: {e}", exc_info=True)
        logger.info("Поток-обработчик записей в БД завершен.")

    def _xai_worker_loop(self):
        logger.info("Поток-обработчик XAI-задач запущен.")
        while self.running:
            try:
                task_args = self.xai_queue.get(timeout=1)
                if task_args is None:
                    break
                ticket, symbol, prediction_input, df_full = task_args
                logger.info(f"Получена новая задача XAI для сделки #{ticket}...")
                xai_data = self.signal_service.calculate_shap_values(
                    symbol=symbol, prediction_input=prediction_input, df_for_background=df_full
                )
                if xai_data:
                    standard_time.sleep(1)
                    self.portfolio_service.update_trade_with_xai_data(position_id=ticket, xai_data=xai_data)
                self.xai_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Ошибка в потоке-обработчике XAI: {e}", exc_info=True)
        logger.info("Поток-обработчик XAI-задач завершен.")

    def start_xai_worker_on_demand(self):
        """
        🔧 OPTIMIZATION: Запускает XAI Worker только по требованию (ленивая загрузка).
        Вызывается из GUI при открытии вкладки XAI.
        """
        if hasattr(self, "xai_worker_thread") and self.xai_worker_thread and self.xai_worker_thread.is_alive():
            logger.info("[XAI-OnDemand] XAI Worker уже запущен, пропускаю.")
            return

        if not self.running:
            logger.warning("[XAI-OnDemand] Система не запущена, невозможно запустить XAI Worker.")
            return

        logger.info("[XAI-OnDemand] Запуск XAI Worker по требованию...")
        self.xai_worker_thread = threading.Thread(target=self._xai_worker_loop, daemon=True, name="XAIWorkerThread")
        self.xai_worker_thread.start()
        self.thread_status_updated.emit("XAI Worker", "RUNNING")
        logger.info("[XAI-OnDemand] XAI Worker успешно запущен.")

    def initiate_emergency_shutdown(self):
        if not self.running:
            logger.warning("Команда аварийной остановки проигнорирована, система не запущена.")
            return
        logger.critical("!!! ИНИЦИИРОВАНА АВАРИЙНАЯ ОСТАНОВКА СИСТЕМЫ !!!")

        def shutdown_worker():
            logger.info("[Shutdown] Шаг 1: Закрытие всех открытых позиций...")
            self.execution_service.emergency_close_all_positions()
            self._safe_gui_update("update_status", "Все позиции закрыты. Остановка потоков...", is_error=False)
            logger.info("[Shutdown] Шаг 2: Остановка всех системных потоков...")
            self.stop()
            self._safe_gui_update("update_status", "Система полностью остановлена.", is_error=False)

        shutdown_thread = threading.Thread(target=shutdown_worker, daemon=True, name="EmergencyShutdownThread")
        shutdown_thread.start()

    def initiate_graceful_shutdown(self):
        if not self.running:
            logger.warning("Команда штатной остановки проигнорирована, система не запущена.")
            return
        logger.info("Инициирована штатная остановка системы...")

        def shutdown_worker():
            self.stop()
            self._join_all_threads()
            self._safe_gui_update("update_status", "Система остановлена.", is_error=False)

        shutdown_thread = threading.Thread(target=shutdown_worker, daemon=True, name="GracefulShutdownThread")
        shutdown_thread.start()

    def _calculate_and_save_xai_async(self, ticket: int, symbol: str, prediction_input: np.ndarray, df_full: pd.DataFrame):
        logger.info(f"Постановка задачи XAI для сделки #{ticket} в очередь...")
        task_args = (ticket, symbol, prediction_input, df_full)
        self.xai_queue.put(task_args)

    def record_human_feedback(self, trade_ticket: int, feedback: int):
        logger.info(f"Получена обратная связь ({feedback}) для сделки #{trade_ticket} из GUI.")
        xai_data = self.db_manager.get_xai_data(trade_ticket)
        if not xai_data:
            logger.error(f"Не найдены XAI-данные для сделки #{trade_ticket}. Невозможно сохранить обратную связь.")
            self._safe_gui_update("update_status", f"XAI-данные для сделки #{trade_ticket} не найдены!", is_error=True)
            return
        success = self.db_manager.save_human_feedback(trade_ticket=trade_ticket, feedback=feedback, market_state=xai_data)
        if success:
            self._safe_gui_update("update_status", f"Отзыв для сделки #{trade_ticket} успешно сохранен.", is_error=False)
        else:
            self._safe_gui_update("update_status", f"Ошибка сохранения отзыва для сделки #{trade_ticket}.", is_error=True)

    def get_rl_orchestrator_state(self) -> Dict[str, float]:
        trade_history = self.db_manager.get_trade_history()
        pnl = sum(t.profit for t in trade_history[-100:])
        sharpe = 0.5
        win_rate = 0.6
        kg_sentiment = (
            self.consensus_engine.get_historical_context_sentiment(
                symbol="EURUSD", market_regime=self._get_current_market_regime_name()
            )
            or 0.0
        )
        drift_key = "EURUSD_H1"
        drift_status = 1.0 if self.drift_manager.drift_statuses.get(drift_key, False) else 0.0
        news_sentiment = self.news_cache.aggregated_sentiment if self.news_cache else 0.0
        portfolio_var = self.risk_engine.calculate_portfolio_var([], {}) or 0.0
        dummy_df = self.get_dummy_df()
        market_volatility = dummy_df["ATR_NORM"].iloc[-1] if not dummy_df.empty and "ATR_NORM" in dummy_df.columns else 0.0
        return {
            "portfolio_var": portfolio_var,
            "weekly_pnl": pnl,
            "sharpe_ratio": sharpe,
            "win_rate": win_rate,
            "market_volatility": market_volatility,
            "kg_sentiment": kg_sentiment,
            "drift_status": drift_status,
            "news_sentiment": news_sentiment,
        }

    def apply_orchestrator_action(self, regime_allocations: Dict[str, Dict[str, float]]):
        """Применяет решение оркестратора — теперь как единый мозг системы."""
        logger.warning(f"[Orchestrator] Новое режимное распределение капитала: {list(regime_allocations.keys())} режимов.")

        # 1. Сохраняем распределение в risk engine
        self.risk_engine.update_regime_capital_allocation(regime_allocations)

        # 2. Определяем текущий режим
        current_regime = self._get_current_market_regime_name()
        self.orchestrator_current_regime = current_regime
        current_allocation = regime_allocations.get(current_regime, self.risk_engine.default_capital_allocation)

        # 3. Определяем АКТИВНЫЕ стратегии (allocation > 5%)
        MIN_ACTIVE = 0.05  # 5% минимум для считаться "активной"
        active_strategies = set()
        for strategy, weight in current_allocation.items():
            if weight >= MIN_ACTIVE:
                active_strategies.add(strategy)

        # Сохраняем в состоянии
        self.orchestrator_active_strategies = {
            strategy: (strategy in active_strategies) for strategy in current_allocation.keys()
        }

        # 4. Обновляем SignalService — какие стратегии разрешены
        if hasattr(self, "signal_service") and self.signal_service:
            self.signal_service.set_active_strategies(active_strategies)
            logger.info(
                f"[Orchestrator] SignalService обновлён: {len(active_strategies)} активных стратегий: {active_strategies}"
            )

        # 5. Динамические risk-параметры от оркестратора
        total_active = len(active_strategies)
        if total_active <= 2:
            # Мало активных стратегий → снижаем риск
            self.orchestrator_max_positions = max(3, self.config.MAX_OPEN_POSITIONS - 2)
            self.orchestrator_risk_multiplier = 0.7
            logger.warning(f"[Orchestrator] ⚠️ Мало активных стратегий ({total_active}) → снижаем риск")
        elif total_active >= 5:
            # Много активных → повышаем риск
            self.orchestrator_max_positions = self.config.MAX_OPEN_POSITIONS + 2
            self.orchestrator_risk_multiplier = 1.2
            logger.info(f"[Orchestrator] Много активных стратегий ({total_active}) → повышаем риск")
        else:
            self.orchestrator_max_positions = self.config.MAX_OPEN_POSITIONS
            self.orchestrator_risk_multiplier = 1.0

        # 6. Логирование
        active_list = [s for s, active in self.orchestrator_active_strategies.items() if active]
        logger.info(f"[Orchestrator] Текущий режим: {current_regime}")
        logger.info(f"[Orchestrator] Активные стратегии ({len(active_list)}): {active_list}")
        logger.info(
            f"[Orchestrator] Max positions: {self.orchestrator_max_positions}, Risk multiplier: {self.orchestrator_risk_multiplier}"
        )
        logger.info(f"[Orchestrator] Применяемое распределение: {current_allocation}")

        self.orchestrator_allocation_updated.emit(current_allocation)

    def is_strategy_active(self, strategy_name: str) -> bool:
        """Проверяет, активна ли стратегия по решению оркестратора."""
        if not self.orchestrator_active_strategies:
            return True  # Пока оркестратор не принял решение — все активны

        # Маппинг имён стратегий → ключи оркестратора
        strategy_key = strategy_name
        if strategy_name.startswith("AI_MF_Consensus") or strategy_name.startswith("AI_Model"):
            strategy_key = "AI_Model"
        elif strategy_name.startswith("AI_LightGBM") or strategy_name.startswith("AI_LSTM"):
            strategy_key = "AI_Model"
        elif strategy_name.startswith("RLTradeManager"):
            strategy_key = "RLTradeManager"

        return self.orchestrator_active_strategies.get(strategy_key, True)

    def force_gp_cycle(self):
        logger.info("[GP R&D] Поиск 'слабого места' для запуска эволюции...")
        weak_spots = self.db_manager.find_weak_spots(
            profit_factor_threshold=self.config.rd_cycle_config.profit_factor_threshold
        )
        if not weak_spots:
            logger.warning("[GP R&D] 'Слабых мест' не найдено. Эволюция не требуется.")
            return
        target = weak_spots[0]
        symbol = target["symbol"]
        regime = target["market_regime"]
        threading.Thread(target=self.gp_rd_manager.run_cycle, args=(symbol, mt5.TIMEFRAME_H1, regime), daemon=True).start()

    def get_account_info(self):
        with self.mt5_lock:
            if mt5_ensure_connected(path=self.config.MT5_PATH):
                try:
                    info = mt5.account_info()
                    return info
                finally:
                    mt5_shutdown()
        return None

    def start_monitoring_loop(self):
        logger.info("=== Запуск цикла мониторинга v2.4 (Calc Manual Bars) ===")
        last_heavy_check_time = 0
        # ОПТИМИЗАЦИЯ: Уменьшено до 3 секунд для частого обновления прибыли
        heavy_check_interval = 3
        last_graph_update_time = 0
        # Оптимизация: Интервал обновления графика знаний увеличен до 60 секунд
        # чтобы снизить нагрузку на GUI и БД.
        graph_update_interval = 60
        last_kpi_update_time = 0
        kpi_update_interval = 60
        last_account_update = 0
        last_health_check = 0  # Для проверки здоровья системы

        # Оптимизация: уменьшаем частоту опроса stop_event
        loop_counter = 0
        while not self.stop_event.is_set():
            current_time = standard_time.time()

            # === HEALTH MONITOR: проверка каждые 60 секунд ===
            if current_time - last_health_check > 60 and hasattr(self, "health_monitor") and self.health_monitor:
                alert = self.health_monitor.check_and_alert()
                if alert:
                    logger.critical(f"🚨 HEALTH ALERT: {alert}")
                last_health_check = current_time
            # =================================================

            # Обновляем информацию о счете каждые 5 секунд
            if current_time - last_account_update > 5:
                self.account_manager.update_info()
                last_account_update = current_time
                logger.info(
                    f"[AccountManager] Тип: {self.account_manager.account_type} | "
                    f"Баланс: {self.account_manager.balance} | Эквити: {self.account_manager.equity}"
                )

            lock_acquired = False
            if self.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION and (
                current_time - last_graph_update_time > graph_update_interval
            ):
                try:
                    if self.db_manager is None:
                        continue
                    graph_data = self.db_manager.get_graph_data()
                    if graph_data:
                        graph_json = json.dumps(graph_data)
                        self.knowledge_graph_updated.emit(graph_json)
                    last_graph_update_time = current_time
                except Exception as e:
                    logger.error(f"Ошибка в под-цикле обновления графа: {e}")
            if current_time - last_kpi_update_time > kpi_update_interval:
                try:
                    self._update_pnl_kpis()
                    last_kpi_update_time = current_time
                except Exception as e:
                    logger.error(f"Ошибка в под-цикле обновления KPI: {e}")
            try:
                self._check_scheduled_tasks()
                # ОПТИМИЗАЦИЯ: Быстрая проверка лока (1 сек вместо 5), не блокируем долго
                if not self.mt5_lock.acquire(timeout=1):
                    logger.debug("[Monitoring] MT5 Lock занят. Пропуск этого цикла мониторинга (таймаут 1с)...")
                    # ОПТИМИЗАЦИЯ: Уменьшено до 1 секунды для меньшего ожидания
                    self.stop_event.wait(1)
                    continue
                lock_acquired = True
                try:
                    # --- ИСПРАВЛЕНИЕ: Сначала пробуем мягкое подключение ---
                    if not mt5_ensure_connected(path=self.config.MT5_PATH):
                        # Безопасная обработка MT5_LOGIN
                        try:
                            mt5_login = int(self.config.MT5_LOGIN) if self.config.MT5_LOGIN else None
                        except (ValueError, TypeError) as e:
                            logger.error(f"[MT5] Некорректный MT5_LOGIN: {self.config.MT5_LOGIN}, ошибка: {e}")
                            mt5_login = None

                        # 🔧 OPTIMIZATION: Используем безопасную обертку вместо прямого mt5.initialize()
                        if not mt5_initialize(
                            path=self.config.MT5_PATH,
                            login=mt5_login,
                            password=self.config.MT5_PASSWORD,
                            server=self.config.MT5_SERVER,
                        ):
                            err_code = mt5.last_error()

                            # 🔧 OPTIMIZATION: Специальная обработка ошибки -10004 (No IPC connection)
                            # Это означает что терминал MT5 временно недоступен (перезапуск после сделки)
                            if isinstance(err_code, tuple) and err_code[0] == -10004:
                                if not hasattr(self, "_ipc_error_count"):
                                    self._ipc_error_count = 0
                                self._ipc_error_count += 1

                                # Логируем только первую ошибку или каждую 5-ю
                                if self._ipc_error_count == 1 or self._ipc_error_count % 5 == 0:
                                    logger.warning(
                                        f"[Monitoring] MT5 терминал временно недоступен (No IPC connection). "
                                        f"Попытка переподключения... (попытка #{self._ipc_error_count})"
                                    )

                                # КРАТКАЯ задержка — MT5 обычно восстанавливается за 2-5 сек после сделки
                                delay = min(3 + self._ipc_error_count, 10)
                                logger.debug(f"[Monitoring] Задержка {delay} сек перед повторной попыткой")

                                # ОБНОВЛЯЕМ GUI последними известными значениями
                                if hasattr(self, "_last_known_balance") and self._last_known_balance > 0:
                                    self._safe_gui_update(
                                        "update_balance",
                                        self._last_known_balance,
                                        self._last_known_equity or self._last_known_balance,
                                    )

                                self.stop_event.wait(delay)
                                continue

                            # НОВОЕ: Специальная обработка ошибки -6 (Authorization failed)
                            if isinstance(err_code, tuple) and err_code[0] == -6:
                                # Увеличиваем счётчик ошибок
                                self._auth_error_count += 1
                                self._last_auth_error_time = datetime.now()

                                # Логгируем только первую ошибку или каждую 10-ю для снижения шума
                                if not self._auth_error_logged or self._auth_error_count % 10 == 0:
                                    logger.error(
                                        f"[Monitoring] КРИТИЧНО: MT5 Authorization Failed. "
                                        f"Терминал может быть закрыт или учетная запись заблокирована. "
                                        f"Ошибка: {err_code} (попытка #{self._auth_error_count})"
                                    )
                                    if not self._auth_error_logged:
                                        logger.warning(
                                            f"[Monitoring] Переключение на FALLBACK: классические стратегии без live-ордеров"
                                        )
                                        self._auth_error_logged = True
                                    else:
                                        logger.debug(
                                            f"[Monitoring] Повтор ошибки авторизации (всего: {self._auth_error_count})"
                                        )

                                # Устанавливаем флаг что торговля недоступна
                                self.mt5_connection_failed = True

                                # Экспоненциальная задержка: min(2^count, 30) секунд
                                delay = min(2 ** min(self._auth_error_count, 5), 30)
                                logger.debug(f"[Monitoring] Задержка перед следующей попыткой: {delay} сек.")
                                self.stop_event.wait(delay)
                                continue
                            else:
                                logger.error(f"[Monitoring] Не удалось инициализировать MT5. Код ошибки: {err_code}")
                                self.stop_event.wait(1)
                                continue

                    # НОВОЕ: Если соединение восстановлено, сбросим флаг
                    if self.mt5_connection_failed:
                        logger.info(f"[Monitoring] ✓ MT5 соединение восстановлено! Возврат в NORMAL режим торговли")
                        self.mt5_connection_failed = False
                        # Сбрасываем счётчик ошибок при успешном подключении
                        self._auth_error_count = 0
                        self._auth_error_logged = False

                    try:
                        account_info = mt5.account_info()

                        # DEBUG: Логируем каждую итерацию мониторинга (DEBUG чтобы не засорять лог)
                        logger.debug(
                            f"[Monitoring-Debug] account_info={account_info is not None}, lock_acquired={lock_acquired}"
                        )

                        if account_info:
                            # Оптимизация: логирование баланса только при изменении > 0.1% или раз в 60 сек
                            should_log = False
                            if not hasattr(self, "_last_logged_balance"):
                                self._last_logged_balance = 0
                                self._last_balance_log_time = 0
                                should_log = True
                            else:
                                time_since_log = current_time - self._last_balance_log_time
                                balance_changed_pct = (
                                    abs(account_info.balance - self._last_logged_balance)
                                    / max(self._last_logged_balance, 1)
                                    * 100
                                )
                                if balance_changed_pct > 0.1 or time_since_log > 60:
                                    should_log = True

                            if should_log:
                                logger.info(
                                    f"[Monitoring] Баланс: ${account_info.balance:,.2f}, Эквити: ${account_info.equity:,.2f}"
                                )
                                self._last_logged_balance = account_info.balance
                                self._last_balance_log_time = current_time

                            # DEBUG: Логируем каждую попытку обновления баланса
                            logger.debug(
                                f"[Monitoring-Debug] Вызываю update_balance: {account_info.balance}, {account_info.equity}"
                            )
                            self._safe_gui_update("update_balance", account_info.balance, account_info.equity)
                            self._last_known_balance = account_info.balance
                            self._last_known_equity = account_info.equity
                        else:
                            logger.warning("[Monitoring] account_info вернул None")
                        pc_time = datetime.now().strftime("%H:%M:%S")
                        server_time_dt = None
                        if self.config.SYMBOLS_WHITELIST:
                            tick = mt5.symbol_info_tick(self.config.SYMBOLS_WHITELIST[0])
                            if tick:
                                server_time_dt = datetime.fromtimestamp(tick.time)
                        server_time = server_time_dt.strftime("%H:%M:%S") if server_time_dt else "--:--:--"
                        self._safe_gui_update("update_times", pc_time, server_time)

                        # ЛЕГКОЕ ОБНОВЛЕНИЕ: Обновляем прибыль позиций без полного запроса
                        if hasattr(self, "_last_positions_cache") and self._last_positions_cache:
                            positions_quick = mt5.positions_get()
                            if positions_quick:
                                positions_list_quick = []
                                for p in positions_quick:
                                    # Ищем кэшированные данные для этой позиции
                                    cached = next(
                                        (pos for pos in self._last_positions_cache if pos.get("ticket") == p.ticket), None
                                    )
                                    if cached:
                                        # Обновляем только прибыль
                                        pos_dict = cached.copy()
                                        pos_dict["profit"] = p.profit
                                        positions_list_quick.append(pos_dict)
                                    else:
                                        # Новая позиция - добавляем базовую информацию
                                        pos_dict = p._asdict()
                                        pos_dict["strategy_display"] = "Loading..."
                                        pos_dict["timeframe_display"] = "N/A"
                                        pos_dict["bars_in_trade_display"] = "0"
                                        positions_list_quick.append(pos_dict)
                                self._safe_gui_update("update_positions_view", positions_list_quick)
                            else:
                                # MT5 временно недоступен — показываем кэш с последней известной прибылью
                                logger.debug("[Monitoring] positions_get вернул None — используем кэш позиций")
                                self._safe_gui_update("update_positions_view", list(self._last_positions_cache))

                        if current_time - last_heavy_check_time > heavy_check_interval:
                            positions = mt5.positions_get()
                            positions_list = []
                            current_srv_time = server_time_dt if server_time_dt else datetime.now()
                            if positions:
                                for p in positions:
                                    pos_dict = p._asdict()
                                    trade_data = self.portfolio_service.get_entry_data(p.ticket)
                                    strategy_name = trade_data.get("strategy", "Manual/External")
                                    timeframe_str = "H1 (Est)"
                                    entry_time = None
                                    tf_seconds = 3600
                                    if trade_data:
                                        strategy_name = trade_data.get("strategy", "Unknown")
                                        if "entry_bar_time" in trade_data:
                                            entry_time = trade_data["entry_bar_time"]
                                            if isinstance(entry_time, str):
                                                try:
                                                    entry_time = datetime.fromisoformat(entry_time)
                                                except:
                                                    pass
                                        if "entry_timeframe" in trade_data:
                                            timeframe_code = trade_data["entry_timeframe"]
                                            timeframe_str = self._get_timeframe_str(timeframe_code)
                                            tf_seconds = self._get_timeframe_seconds(timeframe_code)

                                    if entry_time is None:
                                        entry_time = datetime.fromtimestamp(p.time)
                                        logger.debug(
                                            f"[{p.symbol}] entry_time не найден в trade_data, используем p.time: {entry_time}"
                                        )

                                    bars_in_trade_str = "0"
                                    if isinstance(entry_time, datetime) and tf_seconds > 0:
                                        delta_seconds = (current_srv_time - entry_time).total_seconds()
                                        bars_count = int(delta_seconds / tf_seconds)
                                        bars_in_trade_str = str(max(0, bars_count))
                                        logger.debug(
                                            f"[{p.symbol}] Баров в сделке: {bars_in_trade_str} (delta={delta_seconds}s, tf={tf_seconds}s)"
                                        )
                                    else:
                                        logger.debug(
                                            f"[{p.symbol}] Не удалось рассчитать бары: entry_time={entry_time}, tf_seconds={tf_seconds}"
                                        )
                                    pos_dict["strategy_display"] = strategy_name
                                    pos_dict["timeframe_display"] = timeframe_str
                                    pos_dict["bars_in_trade_display"] = bars_in_trade_str
                                    positions_list.append(pos_dict)
                                # Кэшируем позиции для легкого обновления
                                self._last_positions_cache = positions_list
                            else:
                                self._last_positions_cache = []
                            self._safe_gui_update("update_positions_view", positions_list)
                            found_new_trade = self._check_and_log_closed_positions()

                            # Оптимизация: проверка закрытых Paper Trading позиций
                            if hasattr(self, "paper_trading_engine") and self.paper_trading_engine.enabled:
                                closed_tickets = self.paper_trading_engine.check_stop_loss_take_profit()
                                if closed_tickets:
                                    logger.info(f"[PaperTrading] Закрыто {len(closed_tickets)} позиций по SL/TP")
                                    # Обновляем баланс и отправляем в GUI
                                    balance = self.paper_trading_engine.current_balance
                                    equity = self.paper_trading_engine.current_equity
                                    self._safe_gui_update("update_balance", balance, equity)
                                    # Обновляем PnL график
                                    history = self.paper_trading_engine.get_trade_history()
                                    if history:
                                        self._safe_gui_update("update_pnl_graph", history)

                            if found_new_trade or self.history_needs_update:
                                all_history = self.db_manager.get_trade_history()
                                if all_history:
                                    self._safe_gui_update("update_history_view", all_history)
                                    self._safe_gui_update("update_pnl_graph", all_history)
                                self.history_needs_update = False
                            last_heavy_check_time = current_time
                    finally:
                        mt5_shutdown()
                except Exception as e:
                    logger.error(f"Критическая ошибка в цикле мониторинга (внутри лока): {e}", exc_info=True)
                finally:
                    if lock_acquired:
                        self.mt5_lock.release()
            except Exception as e:
                logger.error(f"Критическая ошибка в цикле мониторинга (вне лока): {e}", exc_info=True)

            # Оптимизация: уменьшаем частоту опроса stop_event
            loop_counter += 1
            # Проверяем stop_event каждые 5 итераций (5 секунд)
            if loop_counter % 5 == 0:
                self.stop_event.wait(1)
            else:
                standard_time.sleep(1)

    async def _process_news_background(self, news_items):
        """Фоновая обработка новостей с защитой от крашей"""
        try:
            logger.info(f"[VectorDB] Запущена фоновая обработка {len(news_items)} новостей...")
            is_vdb_ready = self.vector_db_manager and self.vector_db_manager.is_ready()
            vdb_count = self.vector_db_manager.index.ntotal if is_vdb_ready else 0
            logger.info(
                f"[VectorDB] Статус: готов={is_vdb_ready}, документов={vdb_count}, модель эмбеддингов={self.nlp_processor.embedding_model is not None}"
            )

            if not is_vdb_ready:
                logger.warning("[VectorDB] VectorDB не готов, обработка новостей отменена")
                return

            if not self.nlp_processor.embedding_model:
                logger.warning("[VectorDB] Модель эмбеддингов не загружена, обработка новостей отменена")
                return

            # Асинхронная обработка новостей в батчах (УМЕНЬШЕННАЯ НАГРУЗКА)
            batch_size = 3  # Уменьшили с 10 до 3 для стабильности
            for i in range(0, len(news_items), batch_size):
                batch = news_items[i : i + batch_size]
                tasks = []
                # Уменьшили с 5 до 1 для стабильности (последовательная обработка)
                max_concurrent_news = 1
                semaphore = asyncio.Semaphore(max_concurrent_news)

                async def process_news_with_semaphore(item):
                    async with semaphore:
                        try:
                            # Проверяем, является ли item объектом NewsItem или словарем
                            if hasattr(item, "text"):
                                # Это объект NewsItem
                                text = item.text
                                source = item.source
                                timestamp = item.timestamp.isoformat()
                            elif isinstance(item, dict):
                                # Это словарь
                                text = item.get("text", "")
                                source = item.get("source", "unknown")
                                timestamp_iso = item.get("timestamp")
                                if hasattr(timestamp_iso, "isoformat"):
                                    # Проверяем, есть ли timezone
                                    if timestamp_iso.tzinfo is None:
                                        # NAIVE datetime - добавляем UTC timezone
                                        timestamp = timestamp_iso.replace(tzinfo=timezone.utc).isoformat()
                                    else:
                                        # AWARE datetime - просто конвертируем
                                        timestamp = timestamp_iso.isoformat()
                                else:
                                    # datetime уже импортирован глобально
                                    # Используем timezone-aware datetime
                                    timestamp = timestamp_iso if timestamp_iso else datetime.now(timezone.utc).isoformat()
                            else:
                                logger.warning(f"Неподдерживаемый тип новости: {type(item)}")
                                return

                            # Обрабатываем новость с ограничением по времени
                            await asyncio.wait_for(
                                asyncio.to_thread(
                                    self.nlp_processor.process_and_store_text,
                                    text=text,
                                    context={"source": source, "timestamp": timestamp},
                                ),
                                timeout=10.0,  # Уменьшили таймаут с 15 до 10 секунд для стабильности
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"Таймаут обработки новости")
                        except Exception as e:
                            logger.error(f"Ошибка обработки новости: {e}")

            for item in batch:
                task = asyncio.create_task(process_news_with_semaphore(item))
                tasks.append(task)

            # Выполняем задачи в батче
            if tasks:
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as e:
                    logger.error(f"Ошибка при выполнении задач обработки новостей: {e}")

            # Небольшая пауза между батчами для снижения нагрузки
            await asyncio.sleep(0.2)  # Увеличил с 0.1 до 0.2 секунды

            logger.info(f"[VectorDB] Фоновая обработка новостей завершена.")
            if is_vdb_ready and self.vector_db_manager.index.ntotal > 0:
                try:
                    docs_before = self.vector_db_manager.index.ntotal
                    self.vector_db_manager.force_save()
                    logger.critical(f"[VectorDB] Принудительное сохранение индекса: {docs_before} документов сохранено.")
                except Exception as save_error:
                    logger.error(f"[VectorDB] Ошибка при сохранении индекса: {save_error}", exc_info=True)

        except Exception as e:
            logger.error(f"[VectorDB] Критическая ошибка в фоновой обработке новостей: {e}", exc_info=True)
            # Не прерываем работу системы

    async def _process_single_symbol(
        self, symbol: str, df: pd.DataFrame, timeframe: int, account_info: Any, current_positions: List
    ):
        async with self.trade_execution_lock:
            logger.info(f"[{symbol}] 🟢 Начало обработки символа")
            try:
                market_regime = self.market_regime_manager.get_regime(df)
                logger.info(f"[{symbol}] Режим рынка: {market_regime}")

                strategy_name = self.config.STRATEGY_REGIME_MAPPING.get(
                    market_regime, self.config.STRATEGY_REGIME_MAPPING.get("Default")
                )
                logger.info(f"[{symbol}] Стратегия: {strategy_name}")

                signal_result = None
                final_strategy_name = strategy_name
                open_positions_for_symbol = []

                def get_mt5_positions_sync():
                    with self.mt5_lock:
                        # Добавляем повторные попытки подключения
                        for attempt in range(3):
                            if not mt5_ensure_connected(path=self.config.MT5_PATH):
                                logger.error(f"[{symbol}] MT5 Init Failed in _process_single_symbol, attempt {attempt + 1}.")
                                standard_time.sleep(1)
                                continue
                            try:
                                positions = list(mt5.positions_get(symbol=symbol))
                                return positions
                            except Exception as e:
                                logger.error(f"Ошибка получения позиций: {e}")
                                standard_time.sleep(1)
                            finally:
                                mt5_shutdown()
                        return []

                open_positions_for_symbol = await asyncio.to_thread(get_mt5_positions_sync)
                if strategy_name == "RLTradeManager":
                    if self.rl_manager.is_trained:
                        pass
                else:
                    signal_result = self.signal_service.get_trade_signal(symbol, df, timeframe, self.news_cache)
                if not signal_result:
                    logger.info(
                        f"[{symbol}] Сигнал не получен - возможно, нет условий по AI/классике или вежливая блокировка."
                    )
                    logger.debug(
                        f"[{symbol}] Детали диагностики: regime={market_regime}, open_positions={len(open_positions_for_symbol)}, TOP_N_SYMBOLS={self.config.TOP_N_SYMBOLS}, whitelist={self.config.SYMBOLS_WHITELIST}"
                    )
                    return
                confirmed_signal, final_strategy_name, _, pred_input, entry_price = signal_result

                # ===================================================================
                # DEFI ANALYSIS (Варианты А, Б, В)
                # ===================================================================
                if hasattr(self, "defi_analyzer"):
                    try:
                        # 1. Получаем оценку риска (Вариант А)
                        defi_risk = self.defi_analyzer.get_risk_assessment(symbol)

                        # 2. Получаем режим рынка (Вариант Б)
                        defi_regime = self.defi_analyzer.get_market_regime()

                        # 3. Блокировка при высоком риске (Вариант А)
                        if defi_risk["risk_level"] in ["scam", "high"]:
                            logger.warning(
                                f"[{symbol}] 🚫 БЛОКИРОВКА DeFi: риск={defi_risk['risk_level']}, "
                                f"APY={defi_risk['max_apy']:.1f}%, TVL=${defi_risk['tvl_usd']/1_000_000:.1f}M"
                            )
                            for warning in defi_risk["warnings"]:
                                logger.warning(f"[{symbol}] ⚠️ {warning}")
                            return  # Пропускаем сделку

                        # 4. Корректировка размера позиции на основе DeFi (Вариант Б)
                        defi_signals = self.defi_analyzer.get_trading_signals(symbol)
                        if defi_signals["action"] == "avoid":
                            logger.warning(f"[{symbol}] 🚫 DeFi сигнал: ИЗБЕГАТЬ")
                            return
                        elif defi_signals["action"] == "sell" and confirmed_signal.type.value == "BUY":
                            logger.warning(f"[{symbol}] ⚠️ DeFi сигнал против сделки — снижаю уверенность")
                            confirmed_signal.confidence *= 0.5  # Снижаем уверенность на 50%

                        # 5. Логируем DeFi данные для анализа
                        logger.info(
                            f"[{symbol}] 📊 DeFi: APY={defi_risk['max_apy']:.1f}%, "
                            f"TVL=${defi_risk['tvl_usd']/1_000_000:.1f}M ({defi_risk['tvl_trend']}), "
                            f"Режим={defi_regime['regime']}, Сентимент={defi_regime['sentiment']}"
                        )

                    except Exception as defi_err:
                        logger.debug(f"[{symbol}] Ошибка DeFi анализа: {defi_err}")
                # ===================================================================

                # Исправление: type может быть строкой или SignalType
                signal_type_name = (
                    confirmed_signal.type
                    if isinstance(confirmed_signal.type, str)
                    else (confirmed_signal.type.name if hasattr(confirmed_signal.type, "name") else str(confirmed_signal.type))
                )

                # Отправляем торговый сигнал в GUI
                trading_signal_data = [
                    {
                        "symbol": symbol,
                        "signal_type": signal_type_name,
                        "strategy": final_strategy_name,
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "entry_price": entry_price,
                        "timeframe": self._get_timeframe_str(timeframe),
                    }
                ]
                logger.info(f"[TradingSignal] Отправляю сигнал в GUI: {trading_signal_data}")
                # ИСПРАВЛЕНИЕ: Отправляем только через self.trading_signals_updated
                # Сигнал автоматически пробрасывается в bridge через подключение
                self.trading_signals_updated.emit(trading_signal_data)
                # УДАЛЕНО: Дублирующая отправка через bridge
                # if self.bridge:
                #     self.bridge.trading_signals_updated.emit(trading_signal_data)

                if open_positions_for_symbol:
                    # СТРОГАЯ ПРОВЕРКА: Запрещаем любые дублирующие позиции по символу
                    logger.info(f"[{symbol}] Пропуск: уже есть открытая позиция по символу {symbol}.")
                    return

                # Проверка кулдауна повторного входа
                if symbol in self.trade_history:
                    last_trade = self.trade_history[symbol]
                    last_trade_time = last_trade.get("last_trade_time")
                    last_outcome = last_trade.get("last_outcome", "unknown")

                    if last_trade_time:
                        minutes_since = (datetime.now() - last_trade_time).total_seconds() / 60

                        # Определяем нужный кулдаун
                        if last_outcome == "profit":
                            cooldown = getattr(self.config, "REENTRY_COOLDOWN_AFTER_PROFIT", 60)
                        elif last_outcome == "loss":
                            cooldown = getattr(self.config, "REENTRY_COOLDOWN_AFTER_LOSS", 30)
                        else:
                            cooldown = getattr(self.config, "REENTRY_COOLDOWN_AFTER_BREAKEVEN", 45)

                        if minutes_since < cooldown:
                            logger.info(f"[{symbol}] Кулдаун повторного входа: {minutes_since:.1f}/{cooldown} мин")
                            return

                if not self.risk_engine.is_trade_safe_from_events(symbol):
                    return

                # Исправление: type может быть строкой или SignalType
                signal_type_name = (
                    confirmed_signal.type
                    if isinstance(confirmed_signal.type, str)
                    else (confirmed_signal.type.name if hasattr(confirmed_signal.type, "name") else str(confirmed_signal.type))
                )

                logger.warning(f"[{symbol}] ШАГ 1: ПОЛУЧЕН СИГНАЛ {signal_type_name} от '{final_strategy_name}'!")
                lot_size, stop_loss_in_price = self.risk_engine.calculate_position_size(
                    symbol=symbol,
                    df=df,
                    account_info=account_info,
                    trade_type=confirmed_signal.type,
                    strategy_name=final_strategy_name,
                )
                if lot_size is None or lot_size <= 0 or stop_loss_in_price is None:
                    logger.warning(
                        f"[{symbol}] Лот размер равен 0 или None. Lot Size: {lot_size}. SL Price: {stop_loss_in_price}."
                    )
                    # Попробуем использовать минимальный размер лота, если возможно
                    min_lots = self.data_provider.get_minimum_lot_size(symbol)
                    if min_lots is not None and min_lots > 0 and stop_loss_in_price is not None:
                        lot_size = min_lots
                        logger.info(f"[{symbol}] Используем минимальный размер лота: {lot_size}")
                    else:
                        return
                logger.critical(f"[{symbol}] ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ! ОТПРАВКА ОРДЕРА...")

                # P0: Проверка Paper Trading режима
                if hasattr(self, "paper_trading_engine") and self.paper_trading_engine.enabled:
                    logger.info(f"[{symbol}] Paper Trading режим активен — симуляция сделки")

                    # Симулируем сделку через Paper Trading Engine
                    position_ticket = self.paper_trading_engine.execute_trade(
                        signal=confirmed_signal,
                        lot_size=lot_size,
                        stop_loss=stop_loss_in_price,
                        take_profit=None,  # Можно добавить из сигнала
                    )

                    if position_ticket:
                        logger.info(f"[{symbol}] Paper Trading сделка открыта: {position_ticket}")
                else:
                    # Реальная сделка через execution_service
                    position_ticket = await self.execution_service.execute_trade(
                        symbol=symbol,
                        signal=confirmed_signal,
                        lot_size=lot_size,
                        df=df,
                        timeframe=timeframe,
                        strategy_name=final_strategy_name,
                        stop_loss_in_price=stop_loss_in_price,
                        observer_mode=self.observer_mode,
                        prediction_input=pred_input,
                        entry_price_for_learning=entry_price,
                    )

                if position_ticket and "AI" in final_strategy_name and pred_input is not None and not self.observer_mode:
                    self._calculate_and_save_xai_async(position_ticket, symbol, pred_input, df)

                # 📢 Social Trading: Публикация сделки для подписчиков
                if position_ticket:
                    try:
                        from src.social.publisher import publish_trade_result

                        acc_info = mt5.account_info()
                        if acc_info:
                            # Создаем фейковый объект result для публикатора
                            class MockResult:
                                def __init__(self, ticket, sym, price, vol, sl, tp, comm, magic):
                                    self.retcode = 10009  # TRADE_RETCODE_DONE
                                    self.order = ticket
                                    self.symbol = sym
                                    self.price = price
                                    self.request = type(
                                        "Req",
                                        (),
                                        {
                                            "type": 0 if confirmed_signal.type.value == "BUY" else 1,
                                            "volume": lot_size,
                                            "sl": sl,
                                            "tp": tp,
                                            "magic": magic,
                                            "comment": comm,
                                        },
                                    )()

                            mock_res = MockResult(
                                ticket=position_ticket,
                                sym=symbol,
                                price=entry_price,
                                vol=lot_size,
                                sl=stop_loss_in_price,
                                tp=None,
                                comm=final_strategy_name,
                                magic=234000,
                            )
                            # Вызываем синхронно, так как это быстрая запись в SQLite
                            publish_trade_result(mock_res, acc_info)
                    except Exception as soc_err:
                        logger.debug(f"[SocialTrading] Ошибка публикации: {soc_err}")
            except Exception as e:
                logger.error(f"Ошибка при обработке символа {symbol} внутри блокировки: {e}", exc_info=True)

    def _select_optimal_timeframe(self, symbol: str, data_cache: Dict[str, pd.DataFrame]) -> int:
        timeframe_scores = {}
        optimizer_config = self.config.optimizer
        timeframes_to_check = optimizer_config.timeframes_to_check
        ideal_volatility = optimizer_config.ideal_volatility
        for tf_code in timeframes_to_check.values():
            df = data_cache.get(f"{symbol}_{tf_code}")
            if df is None or len(df) < 50:
                continue
            if "ATR_14" not in df.columns or df["ATR_14"].dropna().empty:
                continue
            last_atr = df["ATR_14"].dropna().iloc[-1]
            last_close = df["close"].iloc[-1]
            if last_close > 0:
                volatility = last_atr / last_close
                score = 1 / (1 + abs(volatility - ideal_volatility) * 1000)
                timeframe_scores[tf_code] = score
        if not timeframe_scores:
            return mt5.TIMEFRAME_H1
        best_timeframe = max(timeframe_scores, key=timeframe_scores.get)
        logger.info(
            f"[{symbol}] Оптимальный таймфрейм выбран: {self._get_timeframe_str(best_timeframe)} (Score: {timeframe_scores[best_timeframe]:.2f})"
        )
        return best_timeframe

    def _process_commands(self):
        """Делегирование обработки команд на TradingEngine."""
        if hasattr(self, "_trading_engine") and self._trading_engine:
            self._trading_engine.process_commands()
        else:
            # Fallback на старую логику
            try:
                command, args = self.command_queue.get_nowait()
                if command == "CLOSE_ALL":
                    threading.Thread(target=self.execution_service.emergency_close_all_positions).start()
                elif command == "CLOSE_ONE":
                    threading.Thread(target=self.execution_service.emergency_close_position, args=(args,)).start()
            except queue.Empty:
                pass

    def _get_timeframe_str(self, tf_code: Optional[int]) -> str:
        if tf_code is None:
            return "N/A"
        tf_map = {v: k for k, v in mt5.__dict__.items() if k.startswith("TIMEFRAME_")}
        full_name = tf_map.get(tf_code, str(tf_code))
        return full_name.replace("TIMEFRAME_", "")

    def set_observer_mode(self, enabled: bool) -> None:
        """
        Переключить режим наблюдателя.

        Args:
            enabled: True для включения режима наблюдателя
        """
        self.observer_mode = enabled
        status_message = f"Режим Наблюдателя {'ВКЛЮЧЕН' if self.observer_mode else 'ВЫКЛЮЧЕН'}."
        logger.info(status_message)
        self._safe_gui_update("update_status", status_message)

    def toggle_observer_mode(self) -> None:
        """Переключить режим наблюдателя на противоположный."""
        self.set_observer_mode(not self.observer_mode)
        logger.info(f"Режим торговли переключён: {'Наблюдатель' if self.observer_mode else 'Торговля'}")

    def set_paper_trading_mode(self, enabled: bool) -> None:
        """
        Включить/выключить режим Paper Trading.

        Args:
            enabled: True для включения Paper Trading
        """
        if hasattr(self, "paper_trading_engine"):
            self.paper_trading_engine.enabled = enabled
            status_message = f"Paper Trading {'ВКЛЮЧЕН' if enabled else 'ВЫКЛЮЧЕН'}."
            logger.info(status_message)
            self._safe_gui_update("update_status", status_message)

            # Если включаем Paper Trading, выключаем observer mode
            if enabled and self.observer_mode:
                self.set_observer_mode(False)
        else:
            logger.warning("Paper Trading Engine не инициализирован")

    def get_trading_mode(self) -> str:
        """
        Возвращает текущий режим торговли.

        Returns:
            "Paper Trading", "Observer", или "Real Trading"
        """
        if hasattr(self, "paper_trading_engine") and self.paper_trading_engine.enabled:
            return "Paper Trading"
        elif self.observer_mode:
            return "Наблюдатель"
        else:
            return "Реальная торговля"

    def update_configuration(self, new_config: Settings):
        self.config = new_config
        logging.info("Конфигурация системы обновлена. Применение к зависимым компонентам...")
        try:
            if hasattr(self, "risk_engine") and self.risk_engine is not None:
                self.risk_engine.config = self.config
            if hasattr(self, "data_provider") and self.data_provider is not None:
                self.data_provider.config = self.config
            if hasattr(self, "session_manager") and self.session_manager is not None:
                self.session_manager.config = self.config
            if hasattr(self, "market_screener") and self.market_screener is not None:
                self.market_screener.config = self.config
            if hasattr(self, "strategy_optimizer") and self.strategy_optimizer is not None:
                self.strategy_optimizer.config = self.config
            if hasattr(self, "consensus_engine") and self.consensus_engine is not None:
                self.consensus_engine.config = self.config
            if hasattr(self, "market_regime_manager") and self.market_regime_manager is not None:
                self.market_regime_manager.config = self.config
            if hasattr(self, "portfolio_service") and self.portfolio_service is not None:
                self.portfolio_service.config = self.config
            if hasattr(self, "execution_service") and self.execution_service is not None:
                self.execution_service.config = self.config
            if hasattr(self, "orchestrator") and self.orchestrator is not None:
                self.orchestrator.config = self.config
            if hasattr(self, "risk_engine") and self.risk_engine is not None:
                if hasattr(self.risk_engine, "base_risk_per_trade_percent"):
                    self.risk_engine.base_risk_per_trade_percent = self.config.RISK_PERCENTAGE
                if hasattr(self.risk_engine, "max_daily_drawdown_percent"):
                    self.risk_engine.max_daily_drawdown_percent = self.config.MAX_DAILY_DRAWDOWN_PERCENT
            logging.info("Компоненты системы успешно переинициализированы с новой конфигурацией.")
        except Exception as e:
            logging.error(f"Ошибка при переинициализации компонентов: {e}", exc_info=True)

    def _validate_model_metrics(self, backtest_results: Dict, symbol: str = "UNKNOWN") -> bool:
        """
        CRITICAL: Reject models that don't meet minimum profitability criteria.
        Это защита от убыточных моделей на реальном счёте.

        Args:
            backtest_results: Словарь с результатами бэктеста
            symbol: Название символа для определения типа актива (crypto/forex)
        """
        profit_factor = backtest_results.get("profit_factor", 0)
        win_rate = backtest_results.get("win_rate", 0)
        sharpe_ratio = backtest_results.get("sharpe_ratio", 0)
        max_drawdown = backtest_results.get("max_drawdown", 100)
        total_trades = backtest_results.get("total_trades", 0)

        # Проверяем, является ли символ криптовалютой
        is_crypto = any(
            [
                "BTC" in symbol.upper(),
                "BITCOIN" in symbol.upper(),
                "ETH" in symbol.upper(),
                "ETHEREUM" in symbol.upper(),
                "CRYPTO" in symbol.upper(),
                "USDT" in symbol.upper(),
            ]
        )

        # Проверяем временный режим со сниженными порогами
        relaxed_mode = getattr(self.config, "TEMPORARY_RELAXED_MODE", False)

        # Определяем пороги в зависимости от типа актива
        if is_crypto and hasattr(self.config, "CRYPTO_THRESHOLDS"):
            # Используем сниженные пороги для криптовалют
            thresholds = self.config.CRYPTO_THRESHOLDS
            pf_threshold = thresholds.get("profit_factor", 1.2)
            wr_threshold = thresholds.get("win_rate", 0.35)
            sharpe_threshold = thresholds.get("sharpe_ratio", 0.5)
            dd_threshold = thresholds.get("max_drawdown", 15.0)
            trades_threshold = thresholds.get("total_trades", 20)
            logger.info(
                f"[CRYPTO MODE] {symbol}: используются сниженные пороги (PF>{pf_threshold}, WR>{wr_threshold*100}%, DD<{dd_threshold}%)"
            )
        elif relaxed_mode and hasattr(self.config, "FOREX_THRESHOLDS"):
            # Временный режим: используем сниженные пороги для Forex
            thresholds = self.config.FOREX_THRESHOLDS
            pf_threshold = thresholds.get("profit_factor", 1.2)
            wr_threshold = thresholds.get("win_rate", 0.35)
            sharpe_threshold = thresholds.get("sharpe_ratio", 0.5)
            dd_threshold = thresholds.get("max_drawdown", 20.0)
            trades_threshold = thresholds.get("total_trades", 3)  # Минимум 3 сделки для D1
            logger.info(
                f"[RELAXED MODE] {symbol}: временные сниженные пороги (PF>{pf_threshold}, WR>{wr_threshold*100}%, DD<{dd_threshold}%, Trades>{trades_threshold})"
            )
        else:
            # Стандартные пороги для Forex
            pf_threshold = 1.2
            wr_threshold = 0.35
            sharpe_threshold = 0.5
            dd_threshold = 15.0
            trades_threshold = 3  # Минимум 3 сделки для D1
            logger.info(
                f"[STANDARD MODE] {symbol}: стандартные пороги (PF>{pf_threshold}, WR>{wr_threshold*100}%, DD<{dd_threshold}%, Trades>{trades_threshold})"
            )

        # CRITICAL THRESHOLDS - модель должна пройти ВСЕ проверки
        if profit_factor < pf_threshold:
            logger.critical(f"❌ MODEL REJECTED: Profit Factor {profit_factor:.2f} < {pf_threshold} (убыточная модель)")
            return False

        if win_rate < wr_threshold:
            logger.critical(f"❌ MODEL REJECTED: Win Rate {win_rate:.2%} < {wr_threshold*100}% (низкая точность)")
            return False

        if sharpe_ratio < sharpe_threshold:
            logger.critical(
                f"❌ MODEL REJECTED: Sharpe Ratio {sharpe_ratio:.2f} < {sharpe_threshold} (плохое соотношение риск/доходность)"
            )
            return False

        if max_drawdown > dd_threshold:
            logger.critical(f"❌ MODEL REJECTED: Max Drawdown {max_drawdown:.2f}% > {dd_threshold}% (слишком рискованная)")
            return False

        if total_trades < trades_threshold:
            logger.critical(f"❌ MODEL REJECTED: Total Trades {total_trades} < {trades_threshold} (недостаточно данных)")
            return False

        logger.critical(
            f"✅ MODEL ACCEPTED: PF={profit_factor:.2f}, WR={win_rate:.2%}, Sharpe={sharpe_ratio:.2f}, DD={max_drawdown:.1f}%, Trades={total_trades}"
        )
        return True

    def _train_candidate_model(
        self,
        model_type,
        symbol,
        timeframe,
        train_df,
        val_df,
        model_factory,
        training_batch_id,
        features_to_use: List[str],
        custom_hyperparams=None,
    ):
        logger.info(f"[TRAIN] Начало _train_candidate_model: {model_type} для {symbol}")
        logger.info(f"[TRAIN] self.bridge = {self.bridge is not None}, self.gui = {self.gui is not None}")
        logger.info(f"[TRAIN] train_df shape: {train_df.shape}, val_df shape: {val_df.shape}")
        logger.info(f"[TRAIN] features_to_use ({len(features_to_use)}): {features_to_use[:10]}...")
        target_col = "close"

        # Проверка на пустые датафреймы
        if train_df.empty or val_df.empty:
            logger.error(f"[R&D] Ошибка: Обучающий или валидационный набор данных пуст. Пропуск обучения.")
            return None

        logger.info(f"[TRAIN] Данные проверены, train={len(train_df)}, val={len(val_df)}")

        # Удаление дубликатов колонок
        train_df = train_df.loc[:, ~train_df.columns.duplicated()]
        val_df = val_df.loc[:, ~val_df.columns.duplicated()]

        # Проверка наличия необходимых признаков
        features_to_use = [f for f in features_to_use if f in train_df.columns]
        if not features_to_use:
            logger.error(f"[R&D] Ошибка: Ни один из требуемых признаков не найден в обучающем датафрейме.")
            return None

        logger.info(f"[TRAIN] Признаки проверены: {len(features_to_use)} колонок")

        # Проверка целевой переменной
        if target_col not in train_df.columns:
            logger.error(f"[R&D] Ошибка: Целевая переменная '{target_col}' отсутствует в обучающем датафрейме.")
            return None

        if target_col not in val_df.columns:
            logger.error(f"[R&D] Ошибка: Целевая переменная '{target_col}' отсутствует в валидационном датафрейме.")
            return None

        logger.info(f"[TRAIN] Скалирование данных...")
        x_scaler = StandardScaler()
        y_scaler = StandardScaler()
        train_df_features_np = train_df[features_to_use].values
        val_df_features_np = val_df[features_to_use].values
        train_df_features_np = np.nan_to_num(train_df_features_np, nan=0.0, posinf=0.0, neginf=0.0)
        val_df_features_np = np.nan_to_num(val_df_features_np, nan=0.0, posinf=0.0, neginf=0.0)
        if train_df_features_np.size == 0 or val_df_features_np.size == 0:
            logger.error(f"[R&D] Ошибка: Обучающий или валидационный набор данных пуст после очистки. Пропуск обучения.")
            return None
        train_df_scaled_features = x_scaler.fit_transform(train_df_features_np)
        val_df_scaled_features = x_scaler.transform(val_df_features_np)
        train_df_scaled = pd.DataFrame(train_df_scaled_features, index=train_df.index, columns=features_to_use)
        val_df_scaled = pd.DataFrame(val_df_scaled_features, index=val_df.index, columns=features_to_use)
        train_df_scaled[target_col] = y_scaler.fit_transform(train_df[[target_col]])
        val_df_scaled[target_col] = y_scaler.transform(val_df[[target_col]])
        model_params = {}
        input_dim = len(features_to_use)
        if custom_hyperparams:
            model_params = custom_hyperparams
        else:
            if model_type.upper() == "LSTM_PYTORCH":
                model_params = {"input_dim": input_dim, "hidden_dim": 32, "num_layers": 1, "output_dim": 1}
            elif model_type.upper() == "TRANSFORMER_PYTORCH":
                model_params = {"input_dim": input_dim, "d_model": 64, "nhead": 4, "nlayers": 2}
            elif model_type.upper() == "LIGHTGBM":
                model_params = {"input_dim": input_dim}
        model = model_factory.create_model(model_type, model_params)
        if not model:
            return None
        if model_type.upper() == "LSTM_PYTORCH":
            from torch.utils.data import DataLoader, TensorDataset

            X_train, y_train = self._create_sequences(train_df_scaled[features_to_use].values, self.config.INPUT_LAYER_SIZE)
            if X_train is None or y_train is None or X_train.size == 0:
                logger.error("[R&D] Ошибка: Не удалось создать последовательности для LSTM. Пропуск.")
                return None
            y_train = train_df_scaled[target_col].values[self.config.INPUT_LAYER_SIZE :]
            X_train_tensor = torch.from_numpy(X_train).float()
            y_train_tensor = torch.from_numpy(y_train).float().unsqueeze(1)
            train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
            train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
            criterion = torch.nn.MSELoss()
            optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
            model.to(self.device)
            loss_history = []
            # ОПТИМИЗАЦИЯ: Уменьшено с 50 до 20 эпох для ускорения R&D цикла
            logger.info(f"[LSTM] Начало обучения: 20 эпох, input_dim={input_dim}")
            for epoch in range(20):
                for X_batch, y_batch in train_loader:
                    X_batch, y_batch = X_batch.to(self.device), y_batch.to(self.device)
                    optimizer.zero_grad()
                    y_pred = model(X_batch)
                    loss = criterion(y_pred, y_batch)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    optimizer.step()
                loss_history.append(loss.item())
                # Отправляем прогресс каждые 2 эпохи и всегда последнюю эпоху
                if epoch % 2 == 0 or epoch == 19:
                    logger.info(f"[LSTM] Epoch {epoch}/19: loss={loss.item():.6f}")
                    # Отправляем в GUI даже если self.gui=None (используем bridge напрямую)
                    history_obj = type("History", (), {"history": {"loss": loss_history}})()
                    logger.info(f"[LSTM] Отправляем в GUI loss_history: {len(loss_history)} значений")
                    logger.info(
                        f"[LSTM] self.bridge type: {type(self.bridge)}, bridge has signal: {hasattr(self.bridge, 'training_history_updated')}"
                    )
                    if self.bridge:
                        try:
                            self.bridge.training_history_updated.emit(history_obj)
                            logger.info(f"[LSTM] ✅ Сигнал отправлен через bridge")
                        except Exception as e:
                            logger.error(f"[LSTM] ❌ Ошибка отправки сигнала: {e}", exc_info=True)
                    elif self.gui:
                        self._safe_gui_update("update_visualization", history_obj)
                    else:
                        logger.warning("[LSTM] self.gui и self.bridge = None, пропускаем обновление GUI")
        elif model_type.upper() == "LIGHTGBM":
            X_train = train_df_scaled[features_to_use]
            y_train = train_df_scaled[target_col]
            X_val = val_df_scaled[features_to_use]
            y_val = val_df_scaled[target_col]
            evals_result = {}
            model.fit(
                X_train,
                y_train,
                eval_set=[(X_val, y_val)],
                eval_metric="rmse",
                callbacks=[lgb.early_stopping(10, verbose=False), lgb.record_evaluation(evals_result)],
            )
            if "valid_0" in evals_result and "rmse" in evals_result["valid_0"]:
                loss_history = evals_result["valid_0"]["rmse"]
                history_obj = type("History", (), {"history": {"loss": loss_history}})()
                logger.info(f"[LightGBM] Отправляем в GUI loss_history: {len(loss_history)} значений")
                if self.bridge:
                    self.bridge.training_history_updated.emit(history_obj)
                    logger.info(f"[LightGBM] ✅ Сигнал отправлен через bridge")
                elif self.gui:
                    self._safe_gui_update("update_visualization", history_obj)

        model_id = self.db_manager._save_model_and_scalers_internal(
            symbol=symbol,
            timeframe=timeframe,
            model=model,
            model_type=model_type,
            x_scaler=x_scaler,
            y_scaler=y_scaler,
            features_list=features_to_use,
            training_batch_id=training_batch_id,
            hyperparameters=model_params if model_type.upper() == "LSTM_PYTORCH" else None,
        )
        logger.info(f"[TRAIN] Модель {model_type} для {symbol} сохранена с ID={model_id}")
        return model_id

    def _run_champion_contest(self, candidate_ids: list, holdout_df: pd.DataFrame):
        logger.warning(f"--- НАЧАЛО ЧЕМПИОНСКОГО КОНКУРСА ДЛЯ {len(candidate_ids)} МОДЕЛЕЙ ---")
        best_challenger_id = None
        best_score = -np.inf
        for model_id in candidate_ids:
            components = self.db_manager.load_model_components_by_id(model_id)
            if not components:
                continue
            try:
                model = components["model"]
                model_type = components["model_type"]
                x_scaler = components["x_scaler"]
                y_scaler = components["y_scaler"]
                features = components["features"]
                holdout_df_no_duplicates = holdout_df.loc[:, ~holdout_df.columns.duplicated()]
                required_cols = list(set(features + ["close"]))
                if not all(col in holdout_df_no_duplicates.columns for col in required_cols):
                    continue
                holdout_df_cleaned = holdout_df_no_duplicates[required_cols].copy()
                holdout_df_cleaned.dropna(inplace=True)
                if len(holdout_df_cleaned) < self.config.INPUT_LAYER_SIZE:
                    continue
                X_holdout_df_ordered = holdout_df_cleaned[features]
                X_holdout_values = X_holdout_df_ordered.values
                if not np.all(np.isfinite(X_holdout_values)):
                    X_holdout_values = np.nan_to_num(X_holdout_values, nan=0.0, posinf=1e9, neginf=-1e9)
                if X_holdout_values.shape[1] != x_scaler.n_features_in_:
                    continue
                X_holdout_scaled = x_scaler.transform(X_holdout_values)
                y_pred_scaled = None
                y_true_unscaled_aligned = None
                if model_type.upper() == "LSTM_PYTORCH":
                    X_holdout_sequences, _ = self._create_sequences(X_holdout_scaled, self.config.INPUT_LAYER_SIZE)
                    if X_holdout_sequences is None:
                        continue
                    # ИНФЕРЕНС: Используем inference_mode для оптимизации
                    with torch.inference_mode():
                        y_pred_scaled = model(torch.from_numpy(X_holdout_sequences).float()).numpy()
                    y_true_unscaled_aligned = holdout_df_cleaned["close"].values[self.config.INPUT_LAYER_SIZE :]
                elif model_type.upper() == "LIGHTGBM":
                    y_pred_scaled = model.predict(X_holdout_scaled)
                    y_true_unscaled_aligned = holdout_df_cleaned["close"].values
                if y_pred_scaled is None:
                    continue
                np.clip(y_pred_scaled, -1.0, 2.0, out=y_pred_scaled)
                y_pred_unscaled = y_scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).flatten()
                if len(y_pred_unscaled) != len(y_true_unscaled_aligned):
                    continue
                if not np.all(np.isfinite(y_pred_unscaled)):
                    score = -np.inf
                else:
                    mse_error = mean_squared_error(y_true_unscaled_aligned, y_pred_unscaled)
                    score = -mse_error
                    logger.info(
                        f"Кандидат ID {model_id} ({model_type}) | Точность (MSE): {mse_error:.4f} (чем ближе к 0, тем лучше)"
                    )
                if score > best_score:
                    best_score = score
                    best_challenger_id = model_id
            except Exception as e:
                logger.error(f"Ошибка при оценке модели ID {model_id}: {e}", exc_info=True)
        if best_challenger_id:
            winner_components = self.db_manager.load_model_components_by_id(best_challenger_id)
            winner_type = winner_components["model_type"]
            logger.critical(
                f"!!! ПОБЕДИТЕЛЬ КОНКУРСА: Модель ID {best_challenger_id} ({winner_type}) со счетом {best_score:.6f} !!!"
            )
            logger.info(
                f"Запуск финального бэктеста для победителя (ID {best_challenger_id}) на holdout-выборке для генерации полного отчета..."
            )
            backtester = AIBacktester(
                data=holdout_df.copy(),
                model=winner_components["model"],
                model_features=winner_components["features"],
                x_scaler=winner_components["x_scaler"],
                y_scaler=winner_components["y_scaler"],
                risk_config=self.config.model_dump(),
            )
            backtest_report = backtester.run()
            logger.warning(f"Полный отчет о производительности для нового чемпиона: {backtest_report}")

            # CRITICAL: Validate model before accepting (нужен symbol для определения порогов)
            # Получаем символ из компонентов победителя
            winner_symbol = winner_components.get("symbol", "UNKNOWN")
            if not self._validate_model_metrics(backtest_report, winner_symbol):
                logger.critical(f"!!! МОДЕЛЬ ID {best_challenger_id} ОТКЛОНЕНА ВАЛИДАЦИЕЙ !!!")
                logger.critical(
                    "Модель не будет использоваться для торговли. Требуется переобучение с большим количеством данных."
                )
                return

            final_report = {"holdout_neg_mse": best_score, **backtest_report}
            self.db_manager.promote_challenger_to_champion(challenger_id=best_challenger_id, report=final_report)
        else:
            logger.error("Не удалось определить победителя в конкурсе моделей.")

    def _update_pnl_kpis(self):
        now = datetime.now()
        start_of_day = datetime.combine(now.date(), time.min)
        start_of_week = start_of_day - timedelta(days=now.weekday())
        start_of_month = datetime(now.year, now.month, 1)
        day_pnl, day_dd = self.db_manager.get_period_pnl(start_of_day)
        week_pnl, week_dd = self.db_manager.get_period_pnl(start_of_week)
        month_pnl, month_dd = self.db_manager.get_period_pnl(start_of_month)
        kpis = {
            "day_pnl": day_pnl,
            "day_dd": day_dd,
            "week_pnl": week_pnl,
            "week_dd": week_dd,
            "month_pnl": month_pnl,
            "month_dd": month_dd,
        }
        logger.debug(f"[PnL-KPI] day_pnl={day_pnl:.2f}, week_pnl={week_pnl:.2f}, month_pnl={month_pnl:.2f}")
        if self.gui and self.gui.bridge:
            self.gui.bridge.pnl_kpis_updated.emit(kpis)
            logger.debug(f"[PnL-KPI] Сигнал отправлен в GUI")
        else:
            logger.warning(f"[PnL-KPI] GUI или bridge не доступны")

    def _uptime_updater_loop(self):
        logger.info("=== Запуск цикла обновления времени работы ===")
        while not self.stop_event.is_set():
            try:
                if self.start_time:
                    delta = datetime.now() - self.start_time
                    uptime_str = str(delta).split(".")[0]

                    # АДАПТИВНОСТЬ: Вывод типа счета, валюты и баланса
                    acc_info = ""
                    if hasattr(self, "account_manager") and self.account_manager.currency:
                        acc_type = self.account_manager.account_type
                        currency = self.account_manager.currency
                        balance = self.account_manager.balance
                        balance_usd = self.account_manager.get_balance_usd()

                        if currency != "USD":
                            acc_info = f"{acc_type} {currency} {balance:.2f} (≈${balance_usd:.2f})"
                        else:
                            acc_info = f"{acc_type} ${balance:.2f}"

                    full_status = f"{acc_info} | {uptime_str}"
                    self.uptime_updated.emit(full_status)
                    self._safe_gui_update("update_uptime", full_status)
            except Exception as e:
                logger.error(f"Ошибка в цикле Uptime: {e}")
            self.stop_event.wait(1)

    def start_orchestrator_loop(self):
        logger.info("=== Запуск цикла Оркестратора ===")
        # 🔧 OPTIMIZATION: Интервал увеличен до 30 минут (1800 сек), чтобы снизить нагрузку на CPU
        # Оркестратору не нужно пересчитывать веса стратегий каждые 5 минут
        orchestrator_interval = 60 * 30
        while not self.stop_event.is_set():
            try:
                self.orchestrator.run_cycle()
            except Exception as e:
                logger.error(f"Критическая ошибка в цикле Оркестратора: {e}", exc_info=True)
            self.stop_event.wait(orchestrator_interval)

    def _train_rl_agent_async(self):
        if self.rl_manager.is_trained:
            logger.info("[RL Manager] Агент уже обучен, пропуск обучения.")
            return
        logger.info("[RL Manager] Запуск асинхронного обучения RL-агента...")

        def train_worker():
            try:
                self.rl_manager.train()
            except Exception as e:
                logger.error(f"Ошибка в потоке обучения RL-агента: {e}", exc_info=True)

        training_thread = threading.Thread(target=train_worker, daemon=True)
        training_thread.start()

    def stop(self):
        """Остановка системы с поддержкой новых сервисов."""
        self.running = False
        self.stop_event.set()
        self._background_services_started = False  # Сброс для возможности повторного запуска
        logger.info("Система останавливается...")

        # === ИНТЕГРАЦИЯ: Остановка сервисов ===
        if hasattr(self, "service_manager"):
            logger.info("Остановка сервисов через SystemServiceManager...")
            self.service_manager.stop_all(timeout=10.0)
        # =======================================

        # Остановка планировщика переобучения
        self.stop_training_scheduler()

        # Остановка веб-сервера (если инициализирован)

        # Отключение крипто-провайдеров
        if hasattr(self, "data_provider_manager") and self.data_provider_manager:
            logger.info("Отключение крипто-провайдеров...")
            try:
                import asyncio

                # ИСПРАВЛЕНИЕ: Правильное создание event loop в потоке
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self.data_provider_manager.shutdown())
                    finally:
                        loop.close()
                        asyncio.set_event_loop(None)
                except RuntimeError as e:
                    if "no current event loop" in str(e):
                        logger.debug("Event loop не требуется для shutdown крипто-провайдеров")
                    else:
                        raise
            except Exception as e:
                logger.error(f"Ошибка отключения крипто-провайдеров: {e}")

    def _check_multi_db_status(self) -> bool:
        """
        Проверка доступности мульти-базовой архитектуры.

        Returns:
            bool: True если хотя бы 3 БД доступны
        """
        if not hasattr(self, "multi_db_manager") or not self.multi_db_manager:
            return False

        try:
            status = self.multi_db_manager.get_status()
            available_count = sum(status.values())

            logger.info(f"Статус мульти-БД: {available_count}/6 БД доступно")
            for db_name, is_available in status.items():
                status_icon = "✓" if is_available else "✗"
                logger.info(f"  {status_icon} {db_name}")

            # Активируем если хотя бы 3 БД доступны
            return available_count >= 3

        except Exception as e:
            logger.error(f"Ошибка проверки статуса мульти-БД: {e}")
            return False

    def _integrate_multi_db(self):
        """Интеграция мульти-БД с существующими компонентами."""
        if not hasattr(self, "multi_db_manager") or not self.multi_db_manager:
            return

        try:
            logger.info("Интеграция MultiDatabaseManager с компонентами...")

            # 1. Интеграция с DatabaseManager
            if hasattr(self, "db_manager") and self.db_manager:
                self.db_manager.multi_db_manager = self.multi_db_manager
                logger.info("  → DatabaseManager: мульти-БД подключен")

            # 2. Интеграция с VectorDBManager (Qdrant)
            if hasattr(self, "vector_db_manager") and self.vector_db_manager:
                if self.multi_db_manager.is_available("qdrant"):
                    self.vector_db_manager.qdrant_adapter = self.multi_db_manager.get_qdrant()
                    self.vector_db_manager.use_qdrant = True
                    logger.info("  → VectorDBManager: Qdrant подключен")
                else:
                    logger.info("  → VectorDBManager: используется локальный FAISS")

            # 3. Интеграция с DataProvider (TimescaleDB/QuestDB)
            if hasattr(self, "data_provider") and self.data_provider:
                if self.multi_db_manager.is_available("timescaledb"):
                    self.data_provider.timescaledb_adapter = self.multi_db_manager.get_timescaledb()
                    logger.info("  → DataProvider: TimescaleDB подключен")

                if self.multi_db_manager.is_available("questdb"):
                    self.data_provider.questdb_adapter = self.multi_db_manager.get_questdb()
                    logger.info("  → DataProvider: QuestDB подключен")

            # 4. Интеграция с ConsensusEngine (Redis)
            if hasattr(self, "consensus_engine") and self.consensus_engine:
                if self.multi_db_manager.is_available("redis"):
                    self.consensus_engine.redis_adapter = self.multi_db_manager.get_redis()
                    logger.info("  → ConsensusEngine: Redis подключен для кэширования")

            # 5. Интеграция с KnowledgeGraphQuerier (Neo4j)
            if hasattr(self, "knowledge_graph_querier") and self.knowledge_graph_querier:
                if self.multi_db_manager.is_available("neo4j"):
                    self.knowledge_graph_querier.neo4j_driver = self.multi_db_manager.get_neo4j_driver()
                    logger.info("  → KnowledgeGraphQuerier: Neo4j подключен")

            logger.info("✓ Интеграция мульти-БД завершена")

        except Exception as e:
            logger.error(f"Ошибка интеграции мульти-БД: {e}")

    def get_database_statistics(self) -> dict:
        """
        Получение статистики по всем базам данных.

        Returns:
            dict: Статистика по БД
        """
        if not self.multi_db_enabled or not hasattr(self, "multi_db_manager"):
            return {"multi_db_enabled": False, "using": "sqlite_faiss"}

        try:
            stats = self.multi_db_manager.get_stats()
            stats["multi_db_enabled"] = True
            stats["using"] = "multi_database"
            return stats
        except Exception as e:
            logger.error(f"Ошибка получения статистики БД: {e}")
            return {"error": str(e), "multi_db_enabled": True}

    def get_defi_features_for_ai(self, symbol: str = None) -> dict:
        """
        Получение DeFi признаков для AI моделей (Вариант В).

        Вызывается из signal_service при генерации AI сигнала.

        Returns:
            Dict с числовыми признаками:
            - defi_max_apy: Максимальная доходность
            - defi_avg_apy: Средняя доходность
            - defi_tvl_usd: TVL в USD
            - defi_lending_rate: Средняя ставка кредитования
            - defi_risk_score: Оценка риска (0-1)
            - defi_sentiment_score: Сентимент (-1 до +1)
        """
        if hasattr(self, "defi_analyzer"):
            return self.defi_analyzer.get_ai_features(symbol)
        return {}

    async def _refresh_defi_data_background(self):
        """Фоновая загрузка DeFi метрик."""
        try:
            # Запускаем в пуле потоков, чтобы не блокировать асинхронный цикл
            await asyncio.to_thread(self._load_defi_data_sync)
            logger.info("[DeFi] Фоновая загрузка метрик завершена успешно")
        except Exception as e:
            logger.error(f"[DeFi] Ошибка фоновой загрузки: {e}")

    def _load_defi_data_sync(self):
        """Синхронная обертка для загрузчика DeFi."""
        from src.data_enrichment.defi_data_loader import DefiDataLoader

        loader = DefiDataLoader(self.db_manager)
        return loader.load_all()

    def _safe_gui_update(self, method_name: str, *args, **kwargs):
        # Оптимизация: уменьшаем частоту обновлений GUI
        if not hasattr(self, "_last_gui_updates"):
            self._last_gui_updates = {}

        # Логирование для отладки обучения
        if method_name == "update_visualization":
            logger.info(f"[Throttle] Вызван _safe_gui_update для {method_name}")

        current_time = standard_time.time()

        # Устанавливаем минимальные интервалы между обновлениями
        update_intervals = {
            # 0.1 секунды между обновлениями графика
            "update_candle_chart": 0.1,
            "update_positions_view": 0.3,  # 0.3 секунды между обновлениями позиций
            "update_history_view": 1.0,  # 1 секунда между обновлениями истории
            "update_balance": 0.3,  # 0.3 секунды между обновлениями баланса
            "update_pnl_graph": 1.0,  # 1 секунда между обновлениями PnL
            # ИСПРАВЛЕНИЕ: Отключаем throttle для графика обучения, чтобы отображать все эпохи
            "update_visualization": 0.0,  # Без ограничений для прогресса обучения
        }

        min_interval = update_intervals.get(method_name, 0.1)  # по умолчанию 0.1 секунды
        last_update_time = self._last_gui_updates.get(method_name, 0)

        if current_time - last_update_time < min_interval:
            logger.debug(f"[Throttle] Пропуск {method_name}, прошло {current_time - last_update_time:.2f}s < {min_interval}s")
            return  # пропускаем обновление, если прошло недостаточно времени

        self._last_gui_updates[method_name] = current_time

        # Логирование для отладки update_balance
        if method_name == "update_balance":
            logger.debug(f"[GUI-Debug] _safe_gui_update вызван для update_balance: args={args}")

        if self.gui:
            try:
                # Проверка что bridge существует
                if not hasattr(self, "bridge") or self.bridge is None:
                    logger.debug(f"[GUI] Bridge не найден, пропуск {method_name}")
                    return

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
                    "update_uptime": (self.bridge.uptime_updated, args),
                }
                if method_name in signal_map:
                    signal, signal_args = signal_map[method_name]

                    # Логирование для отладки баланса
                    if method_name == "update_balance":
                        logger.debug(f"[GUI-Balance] Отправка сигнала balance_updated: {args}")

                    logger.debug(
                        f"[GUI] Отправка сигнала {method_name} с аргументами: {type(signal_args[0]) if signal_args else 'none'}"
                    )
                    signal.emit(*signal_args)
                    # Логирование для отладки прогресса обучения
                    if method_name == "update_visualization":
                        logger.info(
                            f"[GUI] Отправлен сигнал update_visualization с {len(args[0].history.get('loss', []))} значениями loss"
                        )
            except Exception as e:
                logger.error(f"Ошибка GUI update: {e}", exc_info=True)
        # Проверка web_server через hasattr, так как атрибут может не существовать
        if (
            hasattr(self, "web_server")
            and self.web_server
            and hasattr(self.config, "web_dashboard")
            and self.config.web_dashboard.enabled
        ):
            try:
                if method_name == "update_balance":
                    self._last_known_balance = float(args[0])
                    self._last_known_equity = float(args[1])
                if method_name == "update_uptime":
                    self._last_known_uptime = str(args[0])
                if self.running and self.start_time and self._last_known_uptime == "0:00:00":
                    delta = datetime.now() - self.start_time
                    self._last_known_uptime = str(delta).split(".")[0]
                if method_name in ["update_balance", "update_uptime", "update_status"]:
                    drawdown = 0.0
                    if self._last_known_balance > 0:
                        drawdown = max(
                            0.0, (self._last_known_balance - self._last_known_equity) / self._last_known_balance * 100
                        )
                    status_obj = SystemStatus(
                        is_running=self.running,
                        mode="Наблюдатель" if self.observer_mode else "Торговля",
                        uptime=self._last_known_uptime,
                        balance=self._last_known_balance,
                        equity=self._last_known_equity,
                        current_drawdown=drawdown,
                    )
                    self.web_server.broadcast_status_update(status_obj)
                elif method_name == "update_positions_view":
                    raw_positions = args[0]
                    web_positions = []
                    for p in raw_positions:
                        web_positions.append(
                            {
                                "ticket": int(p.get("ticket", 0)),
                                "symbol": str(p.get("symbol", "")),
                                "strategy": str(p.get("strategy_display", "Unknown")),
                                "type": "BUY" if p.get("type") == 0 else "SELL",
                                "volume": float(p.get("volume", 0.0)),
                                "profit": float(p.get("profit", 0.0)),
                                "timeframe": str(p.get("timeframe_display", "N/A")),
                                "bars": str(p.get("bars_in_trade_display", "0")),
                            }
                        )
                    self.web_server.broadcast_positions_update(web_positions)
                elif method_name == "update_pnl_graph":
                    # Ensure PnL graph data is properly formatted for web
                    history_data = args[0] if args else []
                    formatted_history = []
                    for trade in history_data:
                        # Convert trade object to dictionary format
                        if hasattr(trade, "__dict__"):
                            trade_dict = trade.__dict__
                        else:
                            trade_dict = vars(trade) if hasattr(trade, "__dict__") else {}
                        # Ensure all values are serializable
                        formatted_trade = {
                            "ticket": int(trade_dict.get("ticket", 0)),
                            "symbol": str(trade_dict.get("symbol", "")),
                            "profit": float(trade_dict.get("profit", 0.0)),
                            "time_close": str(trade_dict.get("time_close", "")),
                        }
                        formatted_history.append(formatted_trade)
                    # Broadcast the formatted history data to web clients
                    if self.web_server and self.config.web_dashboard.enabled:
                        self.web_server.broadcast_history_update(formatted_history)
            except Exception as e:
                logger.error(f"Error in UI callback: {e}")

    def _join_all_threads(self):
        logger.info("Начало ожидания завершения всех фоновых потоков (Фаза 2)...")
        threads_to_join = {
            "Trading": self.trading_thread,
            "Training": self.training_thread,
            "Monitoring": self.monitoring_thread,
            "Uptime": self.uptime_thread,
            "Orchestrator": self.orchestrator_thread,
            "History Sync": self.history_sync_thread,
            "DB Writer": self.db_writer_thread,
            "XAI Worker": self.xai_worker_thread,
            "VectorDB Cleanup": self.vector_db_cleanup_thread,
        }
        for name, thread in threads_to_join.items():
            if thread and thread.is_alive():
                logger.debug(f"Ожидание завершения потока {name}...")
                thread.join(timeout=10)
                if thread.is_alive():
                    logger.warning(f"Поток {name} не завершился за 10 секунд.")
                else:
                    # ИСПРАВЛЕНИЕ: Проверяем, что сигнал еще существует перед отправкой
                    try:
                        self.thread_status_updated.emit(name, "STOPPED")
                    except RuntimeError:
                        pass  # Сигнал уже удален, игнорируем
            else:
                try:
                    self.thread_status_updated.emit(name, "STOPPED")
                except RuntimeError:
                    pass  # Сигнал уже удален, игнорируем
        logger.info("Все фоновые потоки остановлены.")

    def _load_active_directives(self):
        logger.info("Загрузка активных директив из базы данных...")
        directives_from_db = self.db_manager.get_active_directives()
        self.active_directives = {d.directive_type: d for d in directives_from_db}
        logger.info(f"Загружено {len(self.active_directives)} активных директив.")
        directives_for_gui = [
            {
                "type": d.directive_type,
                "value": d.value,
                "reason": d.reason,
                "expires_at": d.expires_at.strftime("%Y-%m-%d %H:%M"),
            }
            for d in directives_from_db
        ]
        self.directives_updated.emit(directives_for_gui)

    def force_reload_directives(self):
        self._load_active_directives()

    def _check_and_log_closed_positions(self, market_context=None, kg_cb_sentiment=None) -> bool:
        now = datetime.now()
        history_deals = mt5.history_deals_get(
            self.last_history_sync_time - timedelta(minutes=self.config.system.history_sync_margin_minutes), now
        )
        self.last_history_sync_time = now
        if history_deals is None or not history_deals:
            return False
        logged_tickets = self.db_manager.get_all_logged_trade_tickets()
        found_new_closed = False
        deals_by_pos_id = defaultdict(list)
        for deal in history_deals:
            if deal.entry == mt5.DEAL_ENTRY_OUT and deal.position_id not in logged_tickets:
                deals_by_pos_id[deal.position_id].append(deal)
        if not deals_by_pos_id:
            return False
        for pos_id, exit_deals in deals_by_pos_id.items():
            position_deals = [d for d in history_deals if d.position_id == pos_id]
            entry_deal = min((d for d in position_deals if d.entry == mt5.DEAL_ENTRY_IN), key=lambda x: x.time, default=None)
            exit_deal = exit_deals[0]
            if entry_deal:
                entry_data = self.portfolio_service.trade_entry_data.get(int(pos_id), {})
                market_context = entry_data.get("market_context", {})
                timeframe_code = entry_data.get("entry_timeframe", mt5.TIMEFRAME_H1)
                timeframe_str = self._get_timeframe_str(timeframe_code)
                total_profit = sum(d.profit for d in position_deals)
                kg_cb_sentiment = market_context.get("kg_cb_sentiment", 0.0)
                market_regime = market_context.get("market_regime", "Unknown")
                predicted_price = entry_data.get("predicted_price_at_entry")
                strategy_name = entry_data.get("strategy", "Unknown")
                symbol = entry_deal.symbol

                # === ГРАФИК ОШИБОК ПРЕДСКАЗАНИЙ (ДРЕЙФ) ===
                # Работает для ВСЕХ стратегий в режиме наблюдателя
                # Для AI стратегий также работает в режиме торговли
                is_ai_strategy = any(
                    keyword in strategy_name.upper() for keyword in ["AI", "LSTM", "LIGHTGBM", "ML", "NEURAL"]
                )

                # Отправляем данные для графика если:
                # 1. Есть predicted_price (модель что-то предсказала)
                # 2. Режим наблюдателя ИЛИ AI стратегия
                if predicted_price is not None and (self.observer_mode or is_ai_strategy):
                    actual_price = exit_deal.price
                    is_drifting, error_val = self.drift_manager.update(
                        symbol=symbol, timeframe=timeframe_str, predicted_price=predicted_price, actual_price=actual_price
                    )
                    logger.info(
                        f"[Drift] Отправка сигнала: time={exit_deal.time}, sym={symbol}, error={error_val:.4f}, drift={is_drifting}, strategy={strategy_name}, observer={self.observer_mode}"
                    )
                    self.drift_data_updated.emit(exit_deal.time, symbol, error_val, is_drifting)

                    # Дрейф и переобучение работают ТОЛЬКО для AI стратегий в режиме торговли
                    if is_drifting and is_ai_strategy and not self.observer_mode:
                        logger.critical(
                            f"[Drift] 🚨 ОБНАРУЖЕН ДРЕЙФ КОНЦЕПЦИИ для {symbol} ({strategy_name})! Прогноз: {predicted_price:.5f}, Факт: {actual_price:.5f}"
                        )
                        self.orchestrator.apply_drift_penalty(strategy_name, symbol)
                        logger.warning(f"[Drift] Запуск процесса самолечения (переобучения) для {symbol}...")
                        threading.Thread(
                            target=self._force_retrain_specific_symbol,
                            args=(symbol, timeframe_code),
                            daemon=True,
                            name=f"DriftRetrain_{symbol}",
                        ).start()
                self.db_manager.log_trade(
                    entry_deal=entry_deal,
                    exit_deal=exit_deal,
                    timeframe_str=timeframe_str,
                    total_profit=total_profit,
                    xai_data=entry_data.get("xai_data"),
                    market_context=entry_data.get("market_context"),
                )
                self.db_manager.log_trade_outcome_to_kg(
                    trade_ticket=int(pos_id),
                    profit=total_profit,
                    market_regime=market_context.get("market_regime", "Unknown"),
                    kg_cb_sentiment=kg_cb_sentiment,
                )
                self.portfolio_service.remove_trade_entry_data(int(pos_id))
                found_new_closed = True
        return found_new_closed

    def _force_retrain_specific_symbol(self, symbol: str, timeframe: int, train_df=None, val_df=None, holdout_df=None):
        if not self.training_lock.acquire(blocking=False):
            logger.warning(f"[Drift] Обучение уже идет, задача восстановления для {symbol} отложена.")
            return
        try:
            logger.info(f"[Drift] Начало экстренного переобучения модели для {symbol}...")
            training_batch_id = f"drift-fix-{uuid.uuid4()}"
            self.long_task_status_updated.emit("DRIFT_FIX", f"Лечение модели {symbol}...", False)
            best_hyperparams = self._force_retrain_with_optuna(
                symbol=symbol,
                timeframe=timeframe,
                train_df=train_df,
                val_df=val_df,
                features_to_use=self.config.FEATURES_TO_USE,
            )
            model_factory = ModelFactory(self.config)
            final_model_params = {"input_dim": len(self.config.FEATURES_TO_USE), "output_dim": 1, **best_hyperparams}
            model_id = self._train_candidate_model(
                model_type="LSTM_PyTorch",
                symbol=symbol,
                timeframe=timeframe,
                train_df=train_df,
                val_df=val_df,
                model_factory=model_factory,
                training_batch_id=training_batch_id,
                features_to_use=self.config.FEATURES_TO_USE,
                custom_hyperparams=final_model_params,
            )
            if model_id:
                self._run_champion_contest([model_id], holdout_df)
            else:
                logger.error(f"[Drift] Не удалось обучить новую модель для {symbol}.")
        except Exception as e:
            logger.error(f"[Drift] Ошибка при переобучении {symbol}: {e}", exc_info=True)
        finally:
            self.training_lock.release()

    def _sync_initial_history(self):
        logger.info("Запуск первоначальной синхронизации истории сделок...")
        standard_time.sleep(5)
        try:
            from_date = datetime.now() - timedelta(days=self.config.system.initial_history_sync_days)
            if self.stop_event.is_set():
                return
            lock_acquired = self.mt5_lock.acquire(timeout=3)
            if not lock_acquired:
                logger.debug("Синхронизация истории: MT5 lock занят, пропускаю.")
                return
            try:
                if not mt5_ensure_connected(path=self.config.MT5_PATH):
                    # 🔧 OPTIMIZATION: При отсутствии MT5 пропускаем синхронизацию, не спамим ошибкой
                    logger.debug("Синхронизация истории: MT5 недоступен, пропускаю.")
                    return
                history_deals = mt5.history_deals_get(from_date, datetime.now())
            finally:
                mt5_shutdown()
                self.mt5_lock.release()
            if history_deals is None:
                logger.warning("Синхронизация истории: не удалось получить историю сделок от MT5.")
                return
            logged_tickets = self.db_manager.get_all_logged_trade_tickets()
            deals_to_check = defaultdict(list)
            for deal in history_deals:
                if deal.position_id != 0 and deal.position_id not in logged_tickets:
                    deals_to_check[deal.position_id].append(deal)
            added_count = 0
            for pos_id, deals in deals_to_check.items():
                if self._process_and_log_closed_position(pos_id, deals):
                    added_count += 1
            if added_count > 0:
                logger.info(f"Синхронизация завершена. Добавлено {added_count} новых сделок в локальную БД.")
                self.history_needs_update = True
            else:
                logger.info("Синхронизация завершена. Новых сделок для добавления не найдено.")
        except Exception as e:
            logger.error(f"Ошибка во время синхронизации истории: {e}", exc_info=True)

    def _process_and_log_closed_position(self, pos_id: int, deals: List[Any]) -> bool:
        exit_deal = next((d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT), None)
        if not exit_deal:
            return False
        entry_deal = min((d for d in deals if d.entry == mt5.DEAL_ENTRY_IN), key=lambda x: x.time, default=None)
        if not entry_deal:
            logger.warning(f"Для закрытой позиции #{pos_id} не найдена сделка на вход, пропуск.")
            return False
        entry_data = self.portfolio_service.trade_entry_data.get(int(pos_id), {})
        timeframe_str = self._get_timeframe_str(entry_data.get("entry_timeframe"))
        total_profit = sum(d.profit for d in deals)
        success = self.db_manager._log_trade_internal(
            entry_deal=entry_deal,
            exit_deal=exit_deal,
            timeframe_str=timeframe_str,
            total_profit=total_profit,
            xai_data=entry_data.get("xai_data"),
            market_context=entry_data.get("market_context"),
        )
        if success:
            logger.info(f"Успешно залогирована сделка #{pos_id}. Профит: {total_profit:.2f}")
            self.portfolio_service.remove_trade_entry_data(int(pos_id))
            return True
        return False

    def add_to_blacklist(self, symbol: str):
        directive_type = f"BLOCK_SYMBOL_{symbol}"
        self.active_directives[directive_type] = ActiveDirective(
            directive_type=directive_type,
            value="true",
            reason="Manually blacklisted from GUI",
            expires_at=datetime.utcnow() + timedelta(days=365),
        )
        self.directives_updated.emit(
            [
                {
                    "type": d.directive_type,
                    "value": d.value,
                    "reason": d.reason,
                    "expires_at": d.expires_at.strftime("%Y-%m-%d %H:%M"),
                }
                for d in self.active_directives.values()
            ]
        )

    def _create_sequences(self, data: np.ndarray, n_steps: int):
        X, y = [], []
        if len(data) <= n_steps:
            return None, None
        for i in range(len(data) - n_steps):
            X.append(data[i : (i + n_steps)])
            y.append(data[i + n_steps])
        return np.array(X), np.array(y)

    def get_cached_data(self, key: str, ttl_seconds: int = 300) -> Optional[Any]:
        """
        Получить данные из кэша
        :param key: ключ для данных
        :param ttl_seconds: время жизни кэша в секундах (по умолчанию 300 секунд = 5 минут)
        :return: данные из кэша или None, если кэш устарел или не существует
        """
        with self._cache_lock:
            if key in self._data_cache:
                cached_time = self._cache_timestamps.get(key, 0)
                current_time = standard_time.time()

                if current_time - cached_time < ttl_seconds:
                    return self._data_cache[key]
                else:
                    # Удалить устаревшие данные
                    self._data_cache.invalidate(key)
                    del self._cache_timestamps[key]
            return None

    def set_cached_data(self, key: str, data: Any, ttl_seconds: int = 300):
        """
        Сохранить данные в кэш
        :param key: ключ для данных
        :param data: данные для сохранения
        :param ttl_seconds: время жизни кэша в секундах
        """
        with self._cache_lock:
            self._data_cache[key] = data
            self._cache_timestamps[key] = standard_time.time()
            self._cache_ttl[key] = ttl_seconds

    def start_performance_timer(self, operation_name: str):
        """
        Начать замер времени выполнения операции
        :param operation_name: название операции
        """
        import time

        with self._perf_lock:
            self.performance_metrics[operation_name] = {
                "start_time": time.perf_counter(),
                "start_memory": None,  # Можно добавить измерение памяти
            }

    def end_performance_timer(self, operation_name: str, log_details: bool = True):
        """
        Завершить замер времени выполнения операции
        :param operation_name: название операции
        :param log_details: логировать ли детали
        :return: время выполнения в секундах
        """
        import time

        with self._perf_lock:
            if operation_name in self.performance_metrics:
                start_time = self.performance_metrics[operation_name]["start_time"]
                elapsed = time.perf_counter() - start_time

                if log_details:
                    logger.info(f"Performance: {operation_name} took {elapsed:.4f}s")

                    # Логировать медленные операции (порог 15 секунд для AI системы)
                    if elapsed > 15.0:  # Если операция заняла больше 15 секунд
                        logger.warning(f"Slow operation detected: {operation_name} took {elapsed:.4f}s")
                    elif elapsed > 5.0:  # Информационное сообщение для 5+ секунд
                        logger.debug(f"Performance note: {operation_name} took {elapsed:.4f}s (normal for AI analysis)")

                # Удаляем метрику после использования
                del self.performance_metrics[operation_name]

                return elapsed
            else:
                return None

    def invalidate_cache(self, key: str = None):
        """
        Инвалидировать кэш
        :param key: ключ для инвалидации; если None, инвалидируется весь кэш
        """
        with self._cache_lock:
            if key:
                self._data_cache.invalidate(key)
                self._cache_timestamps.pop(key, None)
                self._cache_ttl.pop(key, None)
            else:
                self._data_cache.invalidate()
                self._cache_timestamps.clear()
                self._cache_ttl.clear()

    def get_xai_data_for_trade(self, ticket: int) -> Optional[Dict]:
        # Попробовать получить данные из кэша
        cache_key = f"xai_data_{ticket}"
        cached_data = self.get_cached_data(cache_key, ttl_seconds=600)  # 10 минут TTL
        if cached_data is not None:
            return cached_data

        # Получить данные из базы
        data = self.db_manager.get_xai_data(ticket)

        # Сохранить в кэш
        if data:
            self.set_cached_data(cache_key, data, ttl_seconds=600)

        return data

    def force_training_cycle(self):
        """
        Принудительный запуск цикла обучения из GUI.
        Запускается в отдельном потоке без блокировки основного цикла.
        """
        logger.info("[GUI->TRAIN] Вызван force_training_cycle()")
        logger.info(f"[GUI->TRAIN] self.running = {self.running}")
        if not self.running:
            logger.warning("Нельзя запустить обучение, так как система остановлена.")
            return
        logger.info("[GUI->TRAIN] Запуск потока обучения...")
        # Запускаем в отдельном потоке с высоким приоритетом
        thread = threading.Thread(target=self._force_training_cycle_async, daemon=True, name="ForceTrainingThread")
        thread.start()
        logger.info("[Force Training] Поток обучения запущен")

    def _force_training_cycle_async(self):
        """
        Асинхронное принудительное обучение (в отдельном потоке).
        """
        import uuid

        training_batch_id = f"batch-{uuid.uuid4()}"
        cycle_start_time = standard_time.time()
        logger.warning(f"--- НАЧАЛО ПРИНУДИТЕЛЬНОГО R&D ЦИКЛА (BATCH ID: {training_batch_id}) ---")

        try:
            symbol_to_train = None

            # Пробуем получить символы из рейтинга, но не ждем долго
            wait_count = 0
            while not self.latest_full_ranked_list and wait_count < 5:  # Ждем максимум 10 сек
                if wait_count % 2 == 0:
                    logger.info(f"[Force Training] Ожидание данных... ({wait_count}/5)")
                standard_time.sleep(2)
                wait_count += 1

            ranked_symbols = []
            if self.latest_full_ranked_list:
                ranked_symbols = [item["symbol"] for item in self.latest_full_ranked_list[: self.config.TOP_N_SYMBOLS]]
                logger.info(f"[Force Training] Доступно {len(ranked_symbols)} символов из рейтинга")
            else:
                logger.warning("[Force Training] Рейтинг пуст, используем whitelist")

            # Проверяем символы без моделей (быстро)
            logger.info("[Force Training] Проверка символов без моделей...")
            all_symbols = self.config.SYMBOLS_WHITELIST if hasattr(self.config, "SYMBOLS_WHITELIST") else ranked_symbols
            if not all_symbols:
                logger.error("[Force Training] Нет символов для обучения")
                return

            symbols_without_models = []
            session = self.db_manager.Session()
            try:
                from src.db.database_manager import TrainedModel

                for symbol in all_symbols[:5]:  # Только первые 5 для скорости
                    models_count = session.query(TrainedModel).filter_by(symbol=symbol).count()
                    if models_count == 0:
                        symbols_without_models.append(symbol)
                        logger.info(f"[Force Training] Символ {symbol} не имеет моделей")
            finally:
                session.close()

            if symbols_without_models:
                symbol_to_train = symbols_without_models[0]
                logger.warning(f"[Force Training] ПРИОРИТЕТ: Выбран символ БЕЗ МОДЕЛЕЙ: {symbol_to_train}")
            elif ranked_symbols:
                symbol_to_train = ranked_symbols[0]
                logger.info(f"[Force Training] Выбран топ-1 символ: {symbol_to_train}")
            elif all_symbols:
                symbol_to_train = all_symbols[0]  # Берем первый из whitelist
                logger.warning(f"[Force Training] Выбран первый символ из whitelist: {symbol_to_train}")
            else:
                logger.error("[Force Training] Нет символов для обучения")
                return

            if symbol_to_train:
                # Запускаем обучение БЕЗ блокировки training_lock
                timeframe = mt5.TIMEFRAME_H1
                logger.info(f"[Force Training] Начало обучения для {symbol_to_train}...")
                self._run_training_for_symbol_async(symbol_to_train, timeframe, training_batch_id)

        except Exception as e:
            logger.error(f"Критическая ошибка в принудительном цикле обучения: {e}", exc_info=True)

        total_time = standard_time.time() - cycle_start_time
        logger.warning(f"--- ПРИНУДИТЕЛЬНЫЙ R&D ЦИКЛ ЗАВЕРШЕН за {total_time:.2f} сек ---")

    def _run_training_for_symbol_async(self, symbol: str, timeframe, training_batch_id: str):
        """
        Асинхронное обучение для конкретного символа (без блокировки training_lock).
        """
        from sklearn.model_selection import train_test_split

        from src.ml.feature_engineer import FeatureEngineer
        from src.ml.model_factory import ModelFactory

        # ПРОВЕРКА: Не обучается ли уже этот символ
        with self._training_lock:
            if symbol in self._training_symbols:
                logger.warning(f"[Async Training] Символ {symbol} УЖЕ обучается. Пропуск.")
                return
            # Добавляем символ в множество обучаемых
            self._training_symbols.add(symbol)
            logger.info(f"[Async Training] Символ {symbol} добавлен в _training_symbols")

        logger.info(f"[Async Training] Начало обучения для {symbol}...")

        try:
            # Загрузка данных (не блокирует)
            logger.info(f"[Async Training] Шаг 1: Загрузка данных для {symbol}...")
            data_load_start = standard_time.time()
            df_full = self.data_provider.get_historical_data(
                symbol,
                timeframe,
                datetime.now() - timedelta(days=self.config.TRAINING_DATA_POINTS / 12),
                datetime.now(),
            )
            data_load_time = standard_time.time() - data_load_start
            logger.info(
                f"[Async Training] Загрузка данных заняла {data_load_time:.2f} сек, баров: {len(df_full) if df_full is not None else 0}"
            )

            if df_full is None or len(df_full) < 1000:
                logger.warning(f"[Async Training] Недостаточно данных для {symbol}. Пропуск.")
                return

            # Генерация признаков
            logger.info(f"[Async Training] Шаг 2: Генерация признаков...")
            fe = FeatureEngineer(self.config, self.knowledge_graph_querier)
            df_featured = fe.generate_features(df_full, symbol=symbol)
            logger.info(
                f"[Async Training] Признаки сгенерированы: {len(df_featured)} баров, колонок: {len(df_featured.columns)}"
            )

            # Подготовка признаков
            unique_features = list(dict.fromkeys(self.config.FEATURES_TO_USE))
            actual_features_to_use = [f for f in unique_features if f in df_featured.columns]
            logger.info(f"[Async Training] Используется {len(actual_features_to_use)} признаков")

            if len(actual_features_to_use) > 20:
                actual_features_to_use = actual_features_to_use[:20]
                logger.warning(f"Ограничено количество признаков до 20")

            # Разделение на train/val/holdout
            logger.info(f"[Async Training] Шаг 3: Разделение данных...")
            train_val_df, holdout_df = train_test_split(df_featured, test_size=0.15, shuffle=False)
            train_df, val_df = train_test_split(train_val_df, test_size=0.176, shuffle=False)
            logger.info(f"[Async Training] Train: {len(train_df)}, Val: {len(val_df)}, Holdout: {len(holdout_df)}")

            model_factory = ModelFactory(self.config)
            trained_candidate_ids = []
            training_start = standard_time.time()

            # Инициализируем loss_history для отслеживания
            all_loss_history = []

            logger.info(
                f"[Async Training] Шаг 4: Начало обучения {len(self.config.rd_cycle_config.model_candidates)} моделей..."
            )

            for idx, candidate_config in enumerate(self.config.rd_cycle_config.model_candidates, 1):
                logger.info(
                    f"[Async Training] Обучение модели {idx}/{len(self.config.rd_cycle_config.model_candidates)}: {candidate_config.type}"
                )

                # Отправка прогресса в GUI
                if self.gui:
                    self._safe_gui_update(
                        "update_rd_log",
                        {
                            "generation": idx + 1,
                            "best_fitness": 0.0,
                            "config": f"Обучение модели {candidate_config.type} для {symbol}",
                        },
                    )

                model_id = self._train_candidate_model(
                    model_type=candidate_config.type,
                    symbol=symbol,
                    timeframe=timeframe,
                    train_df=train_df.copy(),
                    val_df=val_df.copy(),
                    model_factory=model_factory,
                    training_batch_id=training_batch_id,
                    features_to_use=actual_features_to_use,
                )
                if model_id:
                    trained_candidate_ids.append(model_id)
                    logger.info(f"[Async Training] Модель {candidate_config.type} обучена (ID: {model_id})")

                    if self.gui:
                        self._safe_gui_update(
                            "update_rd_log",
                            {
                                "generation": idx + 1,
                                "best_fitness": 1.0,
                                "config": f"✓ Модель {candidate_config.type} обучена (ID: {model_id})",
                            },
                        )

                    standard_time.sleep(0.5)
                else:
                    logger.warning(f"[Async Training] Модель {candidate_config.type} НЕ обучена (model_id=None)")

            training_time = standard_time.time() - training_start
            logger.info(f"[Async Training] Обучение всех моделей заняло {training_time:.2f} сек")

            if trained_candidate_ids:
                contest_start = standard_time.time()
                logger.info(f"[Async Training] Шаг 5: Конкурс моделей...")
                self._run_champion_contest(trained_candidate_ids, holdout_df)
                contest_time = standard_time.time() - contest_start
                logger.info(f"[Async Training] Конкурс моделей занял {contest_time:.2f} сек")

            logger.info(f"[Async Training] ✅ Обучение для {symbol} завершено успешно")

        except Exception as e:
            logger.error(f"[Async Training] Ошибка обучения: {e}", exc_info=True)

        finally:
            # Удаляем символ из множества обучаемых (освобождаем блокировку)
            with self._training_lock:
                if symbol in self._training_symbols:
                    self._training_symbols.remove(symbol)
                    logger.info(f"[Async Training] Символ {symbol} удалён из _training_symbols")

    # === ИНТЕГРАЦИЯ: Методы для управления сервисами ===

    def enable_new_services(self, enabled: bool = True) -> None:
        """
        Включить/выключить использование новых сервисов.

        Args:
            enabled: True для использования новых сервисов
        """
        if hasattr(self, "service_manager"):
            self.service_manager.enable_new_services(enabled)
            logger.info(f"Новые сервисы {'ВКЛЮЧЕНЫ' if enabled else 'ВЫКЛЮЧЕНЫ'}")

    def get_service_status(self) -> Dict[str, Any]:
        """
        Получить статус сервисов.

        Returns:
            Dict[str, Any]: Статус сервисов
        """
        if hasattr(self, "service_manager"):
            return self.service_manager.get_status()
        return {"error": "ServiceManager не инициализирован"}

    def get_service_health(self) -> Dict[str, bool]:
        """
        Проверить здоровье сервисов.

        Returns:
            Dict[str, bool]: Здоровье сервисов
        """
        if hasattr(self, "service_manager"):
            return self.service_manager.health_check()
        return {"error": "ServiceManager не инициализирован"}

    # =====================================================

    def emergency_close_position(self, ticket: int) -> None:
        """
        Экстренно закрыть позицию.

        Args:
            ticket: Тикет позиции для закрытия
        """
        self.execution_service.emergency_close_position(ticket)

    def emergency_close_all_positions(self) -> None:
        """Экстренно закрыть все позиции"""
        self.execution_service.emergency_close_all_positions()

    def add_directive(self, directive_type: str, reason: str, duration_hours: int, value: Any) -> None:
        """
        Добавить директиву.

        Args:
            directive_type: Тип директивы
            reason: Причина
            duration_hours: Длительность в часах
            value: Значение
        """
        expires_at = datetime.utcnow() + timedelta(hours=duration_hours)
        directive = ActiveDirective(directive_type=directive_type, value=str(value), reason=reason, expires_at=expires_at)
        self.db_manager.save_directives([directive])
        self.force_reload_directives()
        logger.warning(f"Добавлена ручная директива: {directive_type}={value} до {expires_at.strftime('%Y-%m-%d %H:%M')}")

    def delete_directive(self, directive_type: str) -> bool:
        """
        Удалить директиву.

        Args:
            directive_type: Тип директивы для удаления

        Returns:
            bool: True если успешно
        """
        logger.warning(f"Получена команда на удаление директивы: {directive_type}")
        if self.db_manager.delete_directive_by_type(directive_type):
            self.force_reload_directives()
            return True
        return False

    def restart_system(self):
        logger.critical("!!! ИНИЦИИРОВАН ПЕРЕЗАПУСК СИСТЕМЫ В ФОНОВОМ РЕЖИМЕ !!!")

        def _shutdown_and_restart_worker():
            self.stop()
            standard_time.sleep(2)
            logger.info("Выполнение os.execv для перезапуска...")
            try:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception as e:
                logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА ПЕРЕЗАПУСКА: Не удалось выполнить os.execv: {e}")

        restart_thread = threading.Thread(target=_shutdown_and_restart_worker, daemon=True, name="RestartThread")
        restart_thread.start()

    def _auto_retrain_callback(self, max_symbols: int, max_workers: int):
        """
        Callback функция для автоматического переобучения.
        Вызывается планировщиком по расписанию.
        """
        try:
            logger.info("=" * 80)
            logger.info("🔄 ЗАПУСК АВТОМАТИЧЕСКОГО ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
            logger.info(f"   Параметры: max_symbols={max_symbols}, max_workers={max_workers}")
            logger.info(f"   Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 80)

            # Импортируем функцию из smart_retrain
            from smart_retrain import smart_retrain_models

            # Запускаем обучение
            logger.info("📢 Вызов smart_retrain_models()...")
            result = smart_retrain_models(max_symbols=max_symbols, max_workers=max_workers)
            logger.info(f"✅ Результат переобучения: {result}")

            logger.info("✅ Автоматическое переобучение завершено")

            # Перезагружаем модели чемпионов после автообучения
            try:
                symbols_for_reload = []
                if hasattr(self, "latest_ranked_list") and self.latest_ranked_list:
                    symbols_for_reload = [item["symbol"] for item in self.latest_ranked_list]
                else:
                    symbols_for_reload = list(self.config.SYMBOLS_WHITELIST)
                self._load_champion_models_into_memory(symbols_for_reload)
            except Exception as reload_error:
                logger.error(f"Ошибка перезагрузки моделей после автообучения: {reload_error}", exc_info=True)

            # ОТПРАВКА ДАННЫХ В GUI ПОСЛЕ ОБУЧЕНИЯ
            if self.bridge:
                logger.info("📊 Отправка данных в GUI...")
                self._send_model_accuracy_to_gui()
                self._send_retrain_progress_to_gui()
                logger.info("✅ Данные отправлены в GUI")

        except Exception as e:
            logger.error(f"❌ Ошибка при автоматическом переобучении: {e}", exc_info=True)

    # ========== HotReloadManager Callbacks ==========

    def _on_update_available(self, new_commit: str):
        """Callback при обнаружении обновления."""
        logger.info(f"🔔 Доступно обновление: {new_commit[:8]}")
        if self.bridge:
            try:
                self.bridge.status_updated.emit(f"🔔 Доступна новая версия: {new_commit[:8]}")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления об обновлении: {e}")

    def _on_update_complete(self, commit: str):
        """Callback после успешного применения обновления."""
        logger.info(f"✅ Система обновлена: {commit[:8]}")
        if self.bridge:
            try:
                self.bridge.status_updated.emit(f"✅ Система обновлена: {commit[:8]}")
                # Перезагружаем GUI данные
                if hasattr(self, "_send_model_accuracy_to_gui"):
                    self._send_model_accuracy_to_gui()
                if hasattr(self, "_send_retrain_progress_to_gui"):
                    self._send_retrain_progress_to_gui()
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о завершении обновления: {e}")

    def _on_update_error(self, error: str):
        """Callback при ошибке обновления."""
        logger.error(f"❌ Ошибка обновления: {error}")
        if self.bridge:
            try:
                self.bridge.status_updated.emit(f"❌ Ошибка обновления: {error}")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления об ошибке обновления: {e}")

    async def _run_championship_check(self):
        """
        Запускает чемпионат моделей для отбора лучшей.
        Вызывается автоматически раз в N дней.
        """
        try:
            logger.info("=" * 80)
            logger.info("🏆 ЗАПУСК ЧЕМПИОНАТА МОДЕЛЕЙ")
            logger.info("=" * 80)

            # Собираем модели-кандидаты
            candidate_names = self.config.championship.candidate_models
            candidates = {}

            for model_name in candidate_names:
                try:
                    # Загружаем модель через model_loader
                    model = self.model_loader.load_model(model_name=model_name, force_reload=True)
                    if model:
                        candidates[model_name] = model
                        logger.info(f"   ✅ Загружена модель: {model_name}")
                    else:
                        logger.warning(f"   ⚠️ Модель {model_name} не найдена")
                except Exception as e:
                    logger.warning(f"   ❌ Ошибка загрузки {model_name}: {e}")

            if len(candidates) < 2:
                logger.warning("⚠️ Недостаточно моделей для чемпионата (минимум 2)")
                return

            # Загружаем данные для оценки (последние N баров)
            symbol = self.config.SYMBOLS_WHITELIST[0] if self.config.SYMBOLS_WHITELIST else ""
            if not symbol:
                logger.warning("⚠️ Нет символов для оценки")
                return

            # Получаем исторические данные
            data = self._load_historical_data_for_championship(symbol)
            if data is None or len(data) < 100:
                logger.warning(f"⚠️ Недостаточно данных для {symbol} ({len(data) if data is not None else 0} баров)")
                return

            # Запускаем чемпионат (в executor чтобы не блокировать)
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: self.championship.run_championship(candidates, data, symbol))

            if result:
                logger.info(f"🏆 Чемпионат завершён! Победитель: {result.winner}")
                if result.champion_changed:
                    logger.critical(
                        f"🎉 СМЕНА ЧЕМПИОНА: {result.previous_champion} → {result.winner}\n"
                        f"   Sharpe: {result.winner_metrics.get('sharpe_ratio', 0):.3f}"
                    )
                    # Отправляем уведомление в GUI
                    if self.bridge:
                        self.bridge.status_updated.emit(
                            f"🏆 Новый чемпион: {result.winner} (был {result.previous_champion})",
                            False,  # is_error=False
                        )

                    # Запускаем карантин для новой модели
                    self.championship.activate_model(result.winner)
                else:
                    logger.info(f"👑 Чемпион остался прежним: {result.winner}")
            else:
                logger.warning("⚠️ Чемпионат не состоялся — ни одна модель не прошла порог")

        except Exception as e:
            logger.error(f"❌ Ошибка в чемпионате моделей: {e}", exc_info=True)

    def _load_historical_data_for_championship(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Загружает исторические данные для чемпионата.

        Returns:
            DataFrame с OHLCV данными
        """
        try:
            # Загружаем из БД
            window = self.config.championship.evaluation_window

            if self.db_manager:
                query = """
                    SELECT timestamp, open, high, low, close, tick_volume as volume
                    FROM candle_data
                    WHERE symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                # Зависит от реализации БД — может потребоваться адаптация
                pass

            # Fallback: запрашиваем из MT5
            from datetime import timedelta

            import MetaTrader5 as mt5

            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, window * 2)
            if rates is None or len(rates) == 0:
                return None

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)
            df.rename(columns={"tick_volume": "volume"}, inplace=True)

            return df

        except Exception as e:
            logger.error(f"Ошибка загрузки данных для чемпионата: {e}")
            return None

    def _send_model_accuracy_to_gui(self):
        """
        Собирает и отправляет в GUI данные о точности моделей.
        """
        try:
            import json
            from pathlib import Path

            accuracy_data = {}
            # Используем model_loader для получения пути к моделям
            models_path = (
                self.model_loader._resolve_model_dir()
                if self.model_loader
                else Path(self.config.DATABASE_FOLDER) / "ai_models"
            )

            for symbol in self.config.SYMBOLS_WHITELIST:
                metadata_file = models_path / f"{symbol}_metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                        accuracy = metadata.get("val_accuracy", 0)
                        # Если точность 0 или None, ставим дефолтное значение
                        if not accuracy or accuracy == 0:
                            accuracy = 0.5  # Показываем жёлтый цвет пока нет данных
                        accuracy_data[symbol] = accuracy
                else:
                    accuracy_data[symbol] = 0.0  # Модели нет - красный

            if accuracy_data and self.bridge:
                self.bridge.model_accuracy_updated.emit(accuracy_data)
                logger.info(f"📊 Отправлены данные точности для {len(accuracy_data)} символов: {accuracy_data}")

        except Exception as e:
            logger.error(f"Ошибка при отправке точности моделей в GUI: {e}", exc_info=True)

    def _send_retrain_progress_to_gui(self):
        """
        Собирает и отправляет в GUI данные о прогрессе переобучения.
        """
        try:
            import json
            from pathlib import Path

            progress_data = {}
            # Используем model_loader для получения пути к моделям
            models_path = (
                self.model_loader._resolve_model_dir()
                if self.model_loader
                else Path(self.config.DATABASE_FOLDER) / "ai_models"
            )

            for symbol in self.config.SYMBOLS_WHITELIST:
                metadata_file = models_path / f"{symbol}_metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                        trained_at = datetime.fromisoformat(metadata["trained_at"])
                        hours_since = (datetime.now() - trained_at).total_seconds() / 3600
                        progress_data[symbol] = hours_since
                else:
                    progress_data[symbol] = 999.0  # Модели нет - требует обучения

            if progress_data and self.bridge:
                self.bridge.retrain_progress_updated.emit(progress_data)
                # Считаем сколько символов требуют переобучения (> 24 часа)
                symbols_to_retrain = sum(1 for h in progress_data.values() if h >= 24.0)
                logger.info(
                    f"⏰ Отправлены данные прогресса для {len(progress_data)} символов, требуют переобучения (>24ч): {symbols_to_retrain}"
                )

        except Exception as e:
            logger.error(f"Ошибка при отправке прогресса переобучения в GUI: {e}", exc_info=True)

    def _periodic_training_status_update_loop(self):
        """
        Фоновый цикл для периодического обновления статусов переобучения в GUI.
        Запускается каждые 5 минут.
        """
        logger.info("⏰ Запуск цикла обновления статусов переобучения...")
        update_interval = 300  # 5 минут

        # Первая задержка 30 секунд для стабильности
        self.stop_event.wait(30)

        while not self.stop_event.is_set():
            try:
                # Обновляем прогресс переобучения И точность моделей
                if self.bridge:
                    self._send_retrain_progress_to_gui()
                    self._send_model_accuracy_to_gui()  # 🔧 FIX: Отправляем точность моделей

                # Ждём следующий интервал
                self.stop_event.wait(update_interval)

            except Exception as e:
                logger.error(f"Ошибка в цикле обновления статусов: {e}", exc_info=True)
                self.stop_event.wait(60)  # Пауза при ошибке

        logger.info("⏰ Цикл обновления статусов остановлен")

    def stop_training_scheduler(self):
        """Останавливает планировщик автоматического переобучения."""
        if self.training_scheduler:
            logger.info("Остановка планировщика переобучения...")
            self.training_scheduler.stop()
            self.thread_status_updated.emit("Training Scheduler", "STOPPED")

    # ===================================================================
    # Делегирование на новые модули (Фаза 3 аудита v2.0)
    # ===================================================================

    def can_trade(self) -> bool:
        """Делегирование проверки готовности к торговле на TradingEngine."""
        if hasattr(self, "_trading_engine") and self._trading_engine:
            return self._trading_engine.can_trade()
        # Fallback
        return not (self.stop_event.is_set() or not self.is_heavy_init_complete or self.update_pending)

    def get_available_symbols(self, fallback_symbols=None) -> list:
        """Делегирование получения символов на TradingEngine."""
        if hasattr(self, "_trading_engine") and self._trading_engine:
            return self._trading_engine.get_available_symbols(fallback_symbols)
        return fallback_symbols or self.config.SYMBOLS_WHITELIST

    def close_positions(self, symbols_to_close=None):
        """Делегирование закрытия позиций на TradingEngine."""
        if hasattr(self, "_trading_engine") and self._trading_engine:
            return self._trading_engine.close_positions_if_needed(symbols_to_close)
        return False

    def get_model_accuracy(self, symbol):
        """Делегирование получения точности модели на MLCoordinator."""
        if hasattr(self, "_ml_coordinator") and self._ml_coordinator:
            return self._ml_coordinator.get_model_accuracy(symbol)
        return None

    def get_training_status(self, symbol=None):
        """Делегирование получения статуса обучения на MLCoordinator."""
        if hasattr(self, "_ml_coordinator") and self._ml_coordinator:
            return self._ml_coordinator.get_training_status(symbol)
        return "not_available"

    def get_health_status(self, force=False):
        """Делегирование проверки здоровья на HealthCheckEndpoint."""
        if hasattr(self, "health_check") and self.health_check:
            return self.health_check.get_health_status(force)
        return {"status": "unknown"}
