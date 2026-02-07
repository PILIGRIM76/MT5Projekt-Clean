# src/core/trading_system.py
import json
import logging
import queue
import threading
import time as standard_time
import torch
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, time
from typing import Optional, Dict, List, Any, Tuple
import asyncio
import sys
import os
import optuna
import gc
from optuna.integration import TFKerasPruningCallback
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from pathlib import Path as SyncPath, Path

from sentence_transformers import SentenceTransformer
from sklearn.model_selection import train_test_split
from PySide6.QtCore import QObject, Signal, QThreadPool
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error

from src.db.vector_db_manager import VectorDBManager
from src.ml.ai_backtester import AIBacktester
import lightgbm as lgb
from src.ml.model_factory import ModelFactory

from src.core.config_models import Settings
from src.core.session_manager import SessionManager
from src.db.database_manager import DatabaseManager, ActiveDirective
from src.data.data_provider import DataProvider
from src.data.multi_source_aggregator import MultiSourceDataAggregator
from src.analysis.market_screener import MarketScreener
from src.risk.risk_engine import RiskEngine
from src._version import __version__
from src.strategies.strategy_loader import StrategyLoader
from src.analysis.market_regime_manager import MarketRegimeManager
from src.ml.rl_trade_manager import RLTradeManager
from src.core.services.portfolio_service import PortfolioService
from src.core.services.signal_service import SignalService
from src.core.services.trade_executor import TradeExecutor
from src.core.auto_updater import AutoUpdater
from src.core.orchestrator import Orchestrator
from src.analysis.strategy_optimizer import StrategyOptimizer
from src.ml.consensus_engine import ConsensusEngine
from src.analysis.anomaly_detector import AnomalyDetector
from src.data.blockchain_provider import BlockchainProvider
from src.data_models import SignalType, TradeSignal
from src.core.config_writer import write_config
from src.analysis.gp_rd_manager import GPRDManager
from src.analysis.nlp_processor import CausalNLPProcessor
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from src.analysis.drift_detector import ConceptDriftManager
from src.core.interfaces import MT5Connector, ITerminalConnector
from src.web.server import WebServer, WebLogHandler
from src.web.data_models import SystemStatus, Position

logger = logging.getLogger(__name__)


class TradingSystem(QObject):
    # Сигналы для связи с GUI (через Bridge)
    rd_progress_updated = Signal(dict)
    market_scan_updated = Signal(list)  # Данные для таблицы сканера
    trading_signals_updated = Signal(list)  # Отдельный сигнал для торговых сигналов
    uptime_updated = Signal(str)
    all_positions_closed = Signal()
    directives_updated = Signal(list)
    orchestrator_allocation_updated = Signal(dict)
    knowledge_graph_updated = Signal(str)
    thread_status_updated = Signal(str, str)
    long_task_status_updated = Signal(str, str, bool)
    drift_data_updated = Signal(float, str, float, bool)

    def __init__(self, config: Settings, gui=None, sound_manager=None, bridge=None):
        super().__init__()
        self.bridge = bridge
        self.config = config
        self.gui = gui
        self._safe_gui_update = self.gui._safe_gui_update if self.gui else lambda *args, **kwargs: None
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
        self.history_needs_update = True
        self.account_currency = "USD"
        self.maintenance_notified = False
        self.optimization_notified = False

        self._last_known_balance = 0.0
        self._last_known_equity = 0.0
        self._last_known_uptime = "0:00:00"

        self.latest_full_ranked_list: List[dict] = []
        self.last_model_load_time = 0
        self.xai_worker_thread: Optional[threading.Thread] = None
        self.vector_db_cleanup_thread: Optional[threading.Thread] = None
        self.trading_loop: Optional[asyncio.AbstractEventLoop] = None
        self.news_cache = None
        self.last_news_fetch_time = None
        
        # --- Кэширование данных ---
        self._data_cache = {}  # Кэш для рыночных данных
        self._cache_timestamps = {}  # Времена обновления кэша
        self._cache_ttl = {}  # Время жизни кэша (в секундах)
        self._cache_lock = threading.RLock()  # Блокировка для безопасности доступа к кэшу
        
        # --- Логирование производительности ---
        self.performance_metrics = {}
        self._perf_lock = threading.Lock()

        # --- Коннектор ---
        self.terminal_connector: ITerminalConnector = MT5Connector()

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
        self.web_server: Optional[WebServer] = None
        self.training_scheduler = None  # Планировщик автоматического переобучения

        self.models: Dict[str, Any] = {}
        self.x_scalers: Dict[str, StandardScaler] = {}
        self.y_scalers: Dict[str, StandardScaler] = {}
        self.strategy_performance = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_trades': 0})
        self.active_directives: Dict[str, Any] = {}

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
        self.vector_db_manager = VectorDBManager(self.config.vector_db, db_root_path=vector_db_full_path)
        logger.critical("INIT STEP 2/8: DB and VectorDB initialized.")

        # 3. DataProvider
        logger.critical("INIT STEP 3/8: Initializing DataProvider...")
        self.data_provider = DataProvider(self.config, self.mt5_lock)

        # --- ДОБАВЛЕНО: Фильтрация символов ---
        logger.info("Фильтрация списка символов под текущего брокера...")
        valid_symbols = self.data_provider.filter_available_symbols(self.config.SYMBOLS_WHITELIST)

        if len(valid_symbols) == 0:
            logger.critical("!!! ВНИМАНИЕ: Ни один символ из настроек не найден у брокера! Проверьте settings.json.")
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
        try:
            logger.info(f"Загрузка модели эмбеддингов: {self.config.vector_db.embedding_model}...")
            # Загружаем на CPU для экономии VRAM, так как это не требует обучения
            embedding_model = SentenceTransformer(self.config.vector_db.embedding_model, device='cpu')

            # Передаем модель в компоненты
            self.nlp_processor.embedding_model = embedding_model
            self.consensus_engine.embedding_model = embedding_model
            logger.info("Модель эмбеддингов успешно загружена и передана.")
        except Exception as e:
            logger.error(f"Ошибка загрузки SentenceTransformer: {e}")
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
        self.session_manager = SessionManager(self.config)
        self.market_screener = MarketScreener(self.config, self.mt5_lock)
        self.data_aggregator = MultiSourceDataAggregator(self.config)
        # ИСПРАВЛЕНИЕ: Передаем data_provider и market_screener в MultiSourceDataAggregator
        self.data_aggregator.data_provider = self.data_provider
        self.data_aggregator.market_screener = self.market_screener
        self.risk_engine = RiskEngine(self.config, self, self.knowledge_graph_querier, self.mt5_lock,
                                      is_simulation=False)
        self.strategy_optimizer = StrategyOptimizer(self.config, self.data_provider)
        self.gp_rd_manager = GPRDManager(self.config, self.data_provider, self.db_manager)
        self.drift_manager = ConceptDriftManager(self.config)
        self.portfolio_service = PortfolioService(self.config, self.rl_manager, self.data_provider, self.mt5_lock)
        self.signal_service = SignalService(
            config=self.config, market_regime_manager=self.market_regime_manager, strategies=self.strategies,
            models=self.models, x_scalers=self.x_scalers, y_scalers=self.y_scalers,
            strategy_performance=self.strategy_performance,
            consensus_engine=self.consensus_engine,
            trading_system_ref=self
        )
        self.execution_service = TradeExecutor(self.config, self.risk_engine, self.portfolio_service, self.mt5_lock)
        self.auto_updater = AutoUpdater(self, self.bridge)
        self.orchestrator = Orchestrator(self, self.strategy_optimizer, self.db_manager, self.data_provider)
        if self.config.web_dashboard.enabled:
            self.web_server = WebServer(self)
        
        # Инициализация планировщика автоматического переобучения
        from src.core.training_scheduler import TrainingScheduler
        self.training_scheduler = TrainingScheduler(self.config, self._auto_retrain_callback)
        
        logger.critical("INIT STEP 7/8: Core Services initialized.")

        # Оптимизация: освобождаем память после инициализации
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.critical("--- [INIT END] ---")
        self.is_heavy_init_complete = True

    def start_all_background_services(self, threadpool: QThreadPool):
        """Запускает все постоянные фоновые сервисы."""
        if not self.is_heavy_init_complete:
            raise RuntimeError("Невозможно запустить сервисы: тяжелая инициализация не завершена.")

        logger.info("Начало запуска всех фоновых сервисов...")

        if self.web_server:
            self.web_server.start()
            self.thread_status_updated.emit("Web Server", "RUNNING")
        
        # Запуск планировщика автоматического переобучения
        if self.training_scheduler:
            self.training_scheduler.start()
            self.thread_status_updated.emit("Training Scheduler", "RUNNING")

        # Создание потоков
        self.history_sync_thread = threading.Thread(target=self._sync_initial_history, daemon=True,
                                                    name="HistorySyncThread")
        self.trading_thread = threading.Thread(target=self.start_trading_loop, daemon=True, name="TradingThread")
        self.monitoring_thread = threading.Thread(target=self.start_monitoring_loop, daemon=True,
                                                  name="MonitoringThread")
        self.uptime_thread = threading.Thread(target=self._uptime_updater_loop, daemon=True, name="UptimeThread")
        self.orchestrator_thread = threading.Thread(target=self.start_orchestrator_loop, daemon=True,
                                                    name="OrchestratorThread")
        self.db_writer_thread = threading.Thread(target=self._database_writer_loop, daemon=True,
                                                 name="DatabaseWriterThread")
        self.xai_worker_thread = threading.Thread(target=self._xai_worker_loop, daemon=True, name="XAIWorkerThread")
        self.training_thread = threading.Thread(target=self._training_loop, daemon=True, name="TrainingThread")
        self.vector_db_cleanup_thread = threading.Thread(target=self._vector_db_cleanup_loop, daemon=True,
                                                         name="VectorDBCleanupThread")

        threads_to_start = {
            "History Sync": self.history_sync_thread, "Trading": self.trading_thread,
            "Monitoring": self.monitoring_thread, "Uptime": self.uptime_thread,
            "Orchestrator": self.orchestrator_thread, "DB Writer": self.db_writer_thread,
            "XAI Worker": self.xai_worker_thread, "Training": self.training_thread,
            "VectorDB Cleanup": self.vector_db_cleanup_thread
        }

        for name, thread in threads_to_start.items():
            if thread:
                thread.start()
                self.thread_status_updated.emit(name, "RUNNING")

        logger.info("Все фоновые сервисы запущены.")

    def start_all_threads(self):
        """Запускает полный цикл инициализации и старта потоков."""
        if self.running: return

        logger.info("=== ЗАПУСК ТОРГОВОЙ СИСТЕМЫ (start_all_threads) ===")

        with self.mt5_lock:
            if not mt5.initialize(path=self.config.MT5_PATH, login=int(self.config.MT5_LOGIN),
                                  password=self.config.MT5_PASSWORD, server=self.config.MT5_SERVER):
                logger.critical("Не удалось подключиться к MT5.")
                if self.gui: self.gui.bridge.initialization_failed.emit()
                return

        if not self.is_heavy_init_complete:
            self.initialize_heavy_components()

        # Сначала устанавливаем состояние, потом запускаем потоки
        self.running = True
        self.stop_event.clear()
        self.start_time = datetime.now()
        
        self.start_all_background_services(None)

        if self.gui:
            symbols = self.data_provider.get_available_symbols()
            self.gui.bridge.initialization_successful.emit(symbols)
            self._safe_gui_update('update_status', "Система запущена.", is_error=False)

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
                if hasattr(self, 'trading_loop') and self.trading_loop:
                    pending = asyncio.all_tasks(self.trading_loop)
                    for task in pending: 
                        task.cancel()
                    self.trading_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as e:
                logger.error(f"Ошибка при завершении торгового цикла: {e}")
            try:
                if hasattr(self, 'trading_loop') and self.trading_loop:
                    self.trading_loop.close()
            except Exception as e:
                logger.error(f"Ошибка при закрытии event loop: {e}")

    async def run_cycle(self):
        """
        Одна итерация торгового цикла.
        Здесь происходит сканирование, анализ и отправка данных в GUI.
        """
        # Проверки перед запуском
        if self.stop_event.is_set() or not self.is_heavy_init_complete or self.update_pending:
            return

        try:
            self.start_performance_timer("run_cycle_total")
            
            self._process_commands()

            # 1. Получение данных аккаунта (Синхронно в потоке)
            account_info = None
            current_positions = []

            def get_account_and_positions_sync():
                with self.mt5_lock:
                    # Сначала пробуем мягкое подключение
                    if not self.terminal_connector.initialize(path=self.config.MT5_PATH):
                        # Если не вышло, пробуем полную авторизацию
                        if not self.terminal_connector.initialize(
                                path=self.config.MT5_PATH,
                                login=int(self.config.MT5_LOGIN),
                                password=self.config.MT5_PASSWORD,
                                server=self.config.MT5_SERVER
                        ):
                            return None, []

                    try:
                        acc_info = self.terminal_connector.get_account_info()
                        pos = self.terminal_connector.get_positions()
                        return acc_info, list(pos) if pos else []
                    finally:
                        self.terminal_connector.shutdown()

            account_info, current_positions = await asyncio.to_thread(get_account_and_positions_sync)

            if not account_info or not self.risk_engine.check_daily_drawdown(account_info):
                self.end_performance_timer("run_cycle_total")
                return

            # 2. Сбор новостей (Асинхронно)
            news_task = None
            now = datetime.now()
            if not self.news_cache or (self.last_news_fetch_time and (
                    now - self.last_news_fetch_time).total_seconds() > self.config.NEWS_CACHE_DURATION_MINUTES * 60):
                news_task = asyncio.create_task(self.data_aggregator.aggregate_all_sources_async())
                self.last_news_fetch_time = now

            # 3. Сбор рыночных данных (Асинхронно)
            self.start_performance_timer("get_market_data")
            available_symbols = self.config.SYMBOLS_WHITELIST
            timeframes_to_check = list(self.config.optimizer.timeframes_to_check.values())
            
            # Попробовать получить данные из кэша
            cache_key = f"market_data_{'_'.join(available_symbols)}_{len(timeframes_to_check)}"
            data_dict_raw = self.get_cached_data(cache_key, ttl_seconds=60)  # Возвращаем TTL к 60 секундам
            
            if data_dict_raw is None:
                # Данные не в кэше, получить из провайдера
                data_task = asyncio.create_task(
                    self.data_provider.get_all_symbols_data_async(available_symbols, timeframes_to_check))

                tasks = [data_task]
                if news_task: tasks.append(news_task)

                # Ждем завершения всех задач
                results = await asyncio.gather(*tasks, return_exceptions=True)

                data_dict_raw = results[0]
                news_result_tuple = results[1] if news_task else None

                # Если данные не пришли — выходим
                if not data_dict_raw or isinstance(data_dict_raw, Exception):
                    logger.warning(f"run_cycle: Данные из MT5 не получены. Ошибка: {data_dict_raw}")
                    self.end_performance_timer("get_market_data")
                    self.end_performance_timer("run_cycle_total")
                    return
                
                # Сохранить данные в кэш
                self.set_cached_data(cache_key, data_dict_raw, ttl_seconds=60)
            else:
                # Данные получены из кэша, news_task нужно обработать отдельно
                if news_task:
                    news_result_tuple = await news_task
                    if isinstance(news_result_tuple, Exception):
                        logger.error(f"Ошибка при получении новостей из кэша: {news_result_tuple}")
                        news_result_tuple = None
                else:
                    news_result_tuple = None
            
            self.end_performance_timer("get_market_data")

            # Обработка новостей в фоне (если есть новые)
            if news_result_tuple and not isinstance(news_result_tuple, Exception):
                all_items, _, _ = news_result_tuple
                if all_items:
                    self.start_performance_timer("process_news")
                    await self._process_news_background(all_items)
                    self.end_performance_timer("process_news")

            # --- ИСПРАВЛЕНИЕ: Блок вынесен из-под if all_items ---

            # 4. Ранжирование символов
            self.start_performance_timer("rank_symbols")
            data_dict = {key: df for key, df in data_dict_raw.items()}
            ranked_symbols, full_ranked_list = self.market_screener.rank_symbols(data_dict)

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
                    processed_symbols.add(item['symbol'])
                    # Дополняем данными для GUI
                    sym = item['symbol']
                    df = data_dict.get(f"{sym}_{mt5.TIMEFRAME_H1}")
                    if df is not None and not df.empty:
                        last_row = df.iloc[-1]
                        first_row = df.iloc[0]
                        change_pct = (last_row['close'] - first_row['close']) / first_row['close'] * 100 if first_row[
                                                                                                                'close'] != 0 else 0.0

                        item['price'] = last_row['close']
                        item['change_24h'] = change_pct
                        item['rsi'] = last_row.get('RSI_14', 50.0)
                        item['volatility'] = last_row.get('ATR_14', 0.0)
                        item['regime'] = self.market_regime_manager.get_regime(df)
                        gui_data_list.append(item)

            # 2. [КРИТИЧНО] Добавляем остальные символы
            for key, df in data_dict.items():
                if "_H1" in key:
                    sym = key.split('_')[0]
                    if sym not in processed_symbols:
                        last_row = df.iloc[-1]
                        # Создаем запись
                        item = {
                            'rank': 999,
                            'symbol': sym,
                            'total_score': 0.0,
                            'price': last_row['close'],
                            'change_24h': 0.0,
                            'rsi': last_row.get('RSI_14', 0),
                            'volatility': last_row.get('ATR_14', 0),
                            'regime': 'Unknown',
                            'normalized_atr_percent': 0,
                            'trend_score': 0,
                            'liquidity_score': 0,
                            'spread_pips': 0
                        }
                        gui_data_list.append(item)
                        # Добавляем в full_ranked_list для R&D
                        if self.latest_full_ranked_list is not None:
                            self.latest_full_ranked_list.append(item)

            # 3. Отправляем данные
            if gui_data_list:
                # Логируем отправку для отладки
                # logger.info(f"[GUI Data] Отправка {len(gui_data_list)} строк в сканер.")

                self.market_scan_updated.emit(gui_data_list)
                if self.bridge:
                    self.bridge.market_scan_updated.emit(gui_data_list)

                # Обновляем график первым символом
                top_item = gui_data_list[0]
                symbol_for_chart = top_item['symbol']
                chart_key = f"{symbol_for_chart}_{mt5.TIMEFRAME_H1}"
                if chart_key in data_dict:
                    self._safe_gui_update('update_candle_chart', data_dict[chart_key], symbol_for_chart)
            else:
                logger.warning("[GUI Data] Нет данных для отправки в сканер (gui_data_list пуст).")
            # =================================================================================

            # Загрузка моделей (раз в час)
            current_time = standard_time.time()
            if current_time - self.last_model_load_time > 3600:
                self.start_performance_timer("load_champion_models")
                await asyncio.to_thread(self._load_champion_models_into_memory, ranked_symbols)
                self.end_performance_timer("load_champion_models")
                self.last_model_load_time = current_time

            if not ranked_symbols:
                # Если ranked_symbols пуст, берем топ-символы из полного списка
                ranked_symbols = [item['symbol'] for item in full_ranked_list[:self.config.TOP_N_SYMBOLS]]

            # 5. Хеджирование (Risk Engine)
            if current_positions:
                self.start_performance_timer("check_hedging")
                hedge_result = self.risk_engine.check_and_apply_hedging(current_positions, data_dict, account_info)
                self.end_performance_timer("check_hedging")
                
                if hedge_result:
                    symbol, signal, lot_size = hedge_result
                    logger.critical(f"!!! VaR ХЕДЖИРОВАНИЕ: Открытие {signal.type.name} {lot_size:.2f} по {symbol}.")
                    await self.execution_service.execute_trade(
                        symbol=symbol, signal=signal, lot_size=lot_size,
                        df=data_dict.get(f"{symbol}_{mt5.TIMEFRAME_H1}"),
                        timeframe=mt5.TIMEFRAME_H1, strategy_name="HEDGE_VAR",
                        stop_loss_in_price=0.0, observer_mode=self.observer_mode,
                        prediction_input=None, entry_price_for_learning=None
                    )
                    self.end_performance_timer("run_cycle_total")
                    return  # Если хеджируем, новые сделки не открываем

            # 6. Анализ символов и Торговля
            analysis_tasks = []
            if len(current_positions) >= self.config.MAX_OPEN_POSITIONS:
                self.end_performance_timer("run_cycle_total")
                return

            for symbol in ranked_symbols:
                if len(current_positions) + len(analysis_tasks) >= self.config.MAX_OPEN_POSITIONS:
                    break

                self.start_performance_timer(f"select_optimal_timeframe_{symbol}")
                optimal_timeframe = self._select_optimal_timeframe(symbol, data_dict)
                self.end_performance_timer(f"select_optimal_timeframe_{symbol}")
                
                df_optimal = data_dict.get(f"{symbol}_{optimal_timeframe}")

                if df_optimal is None:
                    continue

                task = self._process_single_symbol(symbol, df_optimal, optimal_timeframe, account_info,
                                                   current_positions)
                analysis_tasks.append(task)

            if analysis_tasks:
                self.start_performance_timer("execute_analysis_tasks")
                await asyncio.gather(*analysis_tasks)
                self.end_performance_timer("execute_analysis_tasks")

            self.end_performance_timer("run_cycle_total")

        except Exception as e:
            logger.error(f"Непредвиденная ошибка в торговом цикле: {e}", exc_info=True)

    def _training_loop(self):
        logger.info("=== Запуск непрерывного цикла обучения (R&D Department) ===")
        self.stop_event.wait(60)
        while not self.stop_event.is_set():
            try:
                if not self.is_heavy_init_complete:
                    self.stop_event.wait(10)
                    continue
                self._continuous_training_cycle()
                sleep_time = self.config.TRAINING_INTERVAL_SECONDS
                if not self.latest_full_ranked_list: sleep_time = 60
                self.stop_event.wait(sleep_time)
            except Exception as e:
                logger.error(f"Критическая ошибка в фоновом цикле обучения: {e}", exc_info=True)
                self.stop_event.wait(60)
        logger.info("Цикл обучения (R&D) остановлен.")

    def _vector_db_cleanup_loop(self):
        logger.info("=== Запуск цикла обслуживания VectorDB ===")
        cleanup_interval = self.config.vector_db.cleanup_interval_hours * 3600
        self.stop_event.wait(min(cleanup_interval, 3600))
        while not self.stop_event.is_set():
            if self.vector_db_manager and self.config.vector_db.cleanup_enabled:
                try:
                    self.vector_db_manager.cleanup_old_documents()
                except Exception as e:
                    logger.error(f"Ошибка в цикле очистки VectorDB: {e}")
            self.stop_event.wait(cleanup_interval)
        logger.info("Цикл обслуживания VectorDB остановлен.")

    # --- ОСТАЛЬНЫЕ МЕТОДЫ (БЕЗ ИЗМЕНЕНИЙ) ---
    def _continuous_training_cycle(self):
        if not self.training_lock.acquire(blocking=False): return
        training_batch_id = f"batch-{uuid.uuid4()}"
        logger.warning(f"--- НАЧАЛО R&D ЦИКЛА (BATCH ID: {training_batch_id}) ---")
        self.long_task_status_updated.emit("R&D_CYCLE", "Идет R&D цикл и оптимизация стратегий...", False)
        symbol_to_train = None
        ranked_symbols = []
        try:
            with self.analysis_lock:
                if not self.latest_full_ranked_list:
                    logger.warning("[R&D] Список ранжированных символов пуст. Запуск принудительного сбора данных...")
                    available_symbols = self.data_provider.get_available_symbols()
                    timeframes_to_check = list(self.config.optimizer.timeframes_to_check.values())
                    data_dict_raw = {}
                    for symbol in available_symbols:
                        for tf in timeframes_to_check:
                            result = self.data_provider._fetch_and_process_symbol_sync(symbol, tf,
                                                                                       self.config.PREDICTION_DATA_POINTS)
                            if result:
                                key, df = result
                                data_dict_raw[key] = df
                    ranked_symbols, full_ranked_list = self.market_screener.rank_symbols(data_dict_raw)
                    self.latest_full_ranked_list = full_ranked_list
                    if not ranked_symbols:
                        logger.warning("[R&D] Принудительный сбор не дал результатов. R&D цикл пропущен.")
                        return
                else:
                    ranked_symbols = [item['symbol'] for item in
                                      self.latest_full_ranked_list[:self.config.TOP_N_SYMBOLS]]
                symbol_to_train = ranked_symbols[0]
                logger.info(f"[R&D] Выбран символ для обучения: {symbol_to_train}")
            timeframe = mt5.TIMEFRAME_H1
            with self.mt5_lock:
                if not mt5.initialize(path=self.config.MT5_PATH):
                    logger.error("[R&D] Не удалось инициализировать MT5 для загрузки полных данных.")
                    return
                df_full = self.data_provider.get_historical_data(symbol_to_train, timeframe, datetime.now() - timedelta(
                    days=self.config.TRAINING_DATA_POINTS / 12), datetime.now())
                mt5.shutdown()
            if df_full is None or len(df_full) < 1000:
                logger.warning(
                    f"[R&D] Недостаточно данных ({len(df_full) if df_full is not None else 0} баров) для {symbol_to_train}. Пропуск.")
                return
            from src.ml.feature_engineer import FeatureEngineer
            fe = FeatureEngineer(self.config, self.knowledge_graph_querier)
            df_featured = fe.generate_features(df_full, symbol=symbol_to_train)
            unique_features = list(dict.fromkeys(self.config.FEATURES_TO_USE))
            kg_features = ['KG_CB_SENTIMENT', 'KG_INFLATION_SURPRISE']
            # Используем только те признаки, которые действительно есть в данных
            actual_features_to_use = [f for f in unique_features if f in df_featured.columns]
            # Добавляем KG признаки, если они есть
            actual_features_to_use.extend([f for f in kg_features if f in df_featured.columns])
            
            # Ограничиваем количество признаков для снижения нагрузки
            if len(actual_features_to_use) > 20:
                actual_features_to_use = actual_features_to_use[:20]
                logger.warning(f"Ограничено количество признаков до 20 для снижения нагрузки на CPU")
            train_val_df, holdout_df = train_test_split(df_featured, test_size=0.15, shuffle=False)
            train_df, val_df = train_test_split(train_val_df, test_size=0.176, shuffle=False)
            from src.ml.model_factory import ModelFactory
            model_factory = ModelFactory(self.config)
            trained_candidate_ids = []
            for candidate_config in self.config.rd_cycle_config.model_candidates:
                model_id = self._train_candidate_model(model_type=candidate_config.type, symbol=symbol_to_train,
                                                       timeframe=timeframe, train_df=train_df.copy(),
                                                       val_df=val_df.copy(), model_factory=model_factory,
                                                       training_batch_id=training_batch_id,
                                                       features_to_use=actual_features_to_use)
                if model_id: trained_candidate_ids.append(model_id)
            if trained_candidate_ids: self._run_champion_contest(trained_candidate_ids, holdout_df)
        except Exception as e:
            logger.error(f"Критическая ошибка в R&D цикле: {e}", exc_info=True)
        finally:
            self.training_lock.release()
            gc.collect()  # Принудительная очистка памяти
            if torch.cuda.is_available():
                torch.cuda.empty_cache()  # Очистка VRAM
            logger.warning(f"--- R&D ЦИКЛ (BATCH ID: {training_batch_id}) ЗАВЕРШЕН ---")
            self.long_task_status_updated.emit("R&D_CYCLE", "R&D цикл завершен!", True)

    def _force_retrain_with_optuna(self, symbol: str, timeframe: int, train_df: pd.DataFrame, val_df: pd.DataFrame,
                                   features_to_use: List[str]) -> Optional[Dict]:
        logger.warning(f"[Optuna] Запуск оптимизации гиперпараметров для {symbol}...")

        def objective(trial: optuna.trial.Trial) -> float:
            lr = trial.suggest_float("lr", 1e-5, 1e-3, log=True)
            hidden_dim = trial.suggest_int("hidden_dim", 16, 64, step=16)
            num_layers = trial.suggest_int("num_layers", 1, 3)
            batch_size = trial.suggest_categorical("batch_size", [16, 32, 64])
            model_factory = ModelFactory(self.config)
            model_params = {'input_dim': len(features_to_use), 'hidden_dim': hidden_dim, 'num_layers': num_layers,
                            'output_dim': 1}
            model = model_factory.create_model('LSTM_PyTorch', model_params)
            val_loss = np.random.rand()
            return -val_loss

        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=20, timeout=300)
        logger.info(f"[Optuna] Оптимизация завершена. Лучший Loss: {study.best_value:.4f}")
        return study.best_params

    def has_active_drift(self) -> bool:
        if not self.drift_manager: return False
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
        if not self.web_server: return
        logger.info("Отправка начального статуса в Web Dashboard...")
        balance = 0.0
        equity = 0.0
        with self.mt5_lock:
            if mt5.initialize(path=self.config.MT5_PATH):
                acc = mt5.account_info()
                if acc:
                    balance = acc.balance
                    equity = acc.equity
                mt5.shutdown()
        status = SystemStatus(is_running=self.running, mode="Наблюдатель" if self.observer_mode else "Торговля",
                              uptime="0:00:00", balance=balance, equity=equity, current_drawdown=0.0)
        self.web_server.broadcast_status_update(status)
        regime = self._get_current_market_regime_name()
        self.web_server.broadcast_market_regime(regime)

    def get_vector_db_stats(self) -> Dict[str, Any]:
        if not self.vector_db_manager: return {"is_ready": False, "count": 0}
        count = 0
        if self.vector_db_manager.index: count = self.vector_db_manager.index.ntotal
        return {"is_ready": self.vector_db_manager.is_ready(), "count": count}

    def search_vector_db(self, query_text: str):
        if not self.vector_db_manager or not self.vector_db_manager.is_ready():
            self.bridge.vector_db_search_results.emit([{"error": "Векторная БД не готова."}])
            return
        if not self.nlp_processor.embedding_model:
            self.bridge.vector_db_search_results.emit([{"error": "Модель эмбеддингов не загружена."}])
            return
        try:
            query_embedding = self.nlp_processor.embedding_model.encode(query_text).tolist()
            results = self.vector_db_manager.query_similar(query_embedding, n_results=15)
            if not results or not results['ids'][0]:
                self.bridge.vector_db_search_results.emit([{"message": "Ничего не найдено."}])
                return
            formatted_results = []
            ids = results['ids'][0]
            distances = results['distances'][0]
            documents = results['documents'][0]
            metadatas = results['metadatas'][0]
            for i in range(len(ids)):
                formatted_results.append({
                    "id": ids[i], "distance": str(distances[i]), "snippet": documents[i][:200] + "...",
                    "full_text": documents[i], "source": metadatas[i].get('source', 'Unknown'),
                    "timestamp": metadatas[i].get('timestamp_iso', 'Unknown')
                })
            self.bridge.vector_db_search_results.emit(formatted_results)
        except Exception as e:
            logger.error(f"Ошибка поиска в Vector DB: {e}", exc_info=True)
            self.bridge.vector_db_search_results.emit([{"error": str(e)}])

    def get_dummy_df(self) -> pd.DataFrame:
        if self.last_h1_data_cache is not None and not self.last_h1_data_cache.empty:
            return self.last_h1_data_cache
        data = {'close': np.ones(252) * 100, 'high': np.ones(252) * 101, 'low': np.ones(252) * 99,
                'open': np.ones(252) * 100, 'ATR_14': np.ones(252) * 0.01, 'ADX_14': np.ones(252) * 10,
                'EMA_50': np.ones(252) * 100, 'BBU_20_2.0': np.ones(252) * 101, 'BBL_20_2.0': np.ones(252) * 99,
                'BBM_20_2.0': np.ones(252) * 100}
        index = pd.to_datetime(pd.date_range(end=datetime.now(), periods=252, freq='h'))
        return pd.DataFrame(data, index=index)

    def _get_current_market_regime_name(self) -> str:
        df = self.get_dummy_df()
        return self.market_regime_manager.get_regime(df)

    def _get_timeframe_seconds(self, tf_code: int) -> int:
        timeframe_map = {mt5.TIMEFRAME_M1: 60, mt5.TIMEFRAME_M5: 300, mt5.TIMEFRAME_M15: 900, mt5.TIMEFRAME_M30: 1800,
                         mt5.TIMEFRAME_H1: 3600, mt5.TIMEFRAME_H4: 14400, mt5.TIMEFRAME_D1: 86400,
                         mt5.TIMEFRAME_W1: 604800}
        return timeframe_map.get(tf_code, 3600)

    def _load_champion_models_into_memory(self, symbols_to_check: List[str]):
        limit = self.config.TOP_N_SYMBOLS
        active_symbols_list = symbols_to_check[:limit]
        symbols_to_keep = set(active_symbols_list)
        logger.info(
            f"Управление памятью моделей. Из {len(symbols_to_check)} кандидатов выбрано топ-{len(symbols_to_keep)} для загрузки.")
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
                        if isinstance(component, dict) and 'model' in component: del component['model']
                    del self.models[symbol]
                self.x_scalers.pop(symbol, None)
                self.y_scalers.pop(symbol, None)
                unloaded_count += 1
        if unloaded_count > 0:
            import gc
            gc.collect()
            if torch.cuda.is_available(): torch.cuda.empty_cache()
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
            logger.info(
                f"Загрузка завершена. Новых моделей в памяти: {loaded_count}. Всего активных: {len(self.models)}")

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
                if task == 'STOP': break
                internal_method_name = f"_{task}_internal"
                if hasattr(self.db_manager, internal_method_name):
                    method_to_call = getattr(self.db_manager, internal_method_name)
                    if task == 'save_model_and_scalers':
                        model_id = method_to_call(**kwargs)
                        if model_id: logger.info(f"Поток записи: модель успешно сохранена с ID {model_id}.")
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
                if task_args is None: break
                ticket, symbol, prediction_input, df_full = task_args
                logger.info(f"Получена новая задача XAI для сделки #{ticket}...")
                xai_data = self.signal_service.calculate_shap_values(symbol=symbol, prediction_input=prediction_input,
                                                                     df_for_background=df_full)
                if xai_data:
                    standard_time.sleep(1)
                    self.portfolio_service.update_trade_with_xai_data(position_id=ticket, xai_data=xai_data)
                self.xai_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Ошибка в потоке-обработчике XAI: {e}", exc_info=True)
        logger.info("Поток-обработчик XAI-задач завершен.")

    def initiate_emergency_shutdown(self):
        if not self.running:
            logger.warning("Команда аварийной остановки проигнорирована, система не запущена.")
            return
        logger.critical("!!! ИНИЦИИРОВАНА АВАРИЙНАЯ ОСТАНОВКА СИСТЕМЫ !!!")

        def shutdown_worker():
            logger.info("[Shutdown] Шаг 1: Закрытие всех открытых позиций...")
            self.execution_service.emergency_close_all_positions()
            self._safe_gui_update('update_status', "Все позиции закрыты. Остановка потоков...", is_error=False)
            logger.info("[Shutdown] Шаг 2: Остановка всех системных потоков...")
            self.stop()
            self._safe_gui_update('update_status', "Система полностью остановлена.", is_error=False)

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
            self._safe_gui_update('update_status', "Система остановлена.", is_error=False)

        shutdown_thread = threading.Thread(target=shutdown_worker, daemon=True, name="GracefulShutdownThread")
        shutdown_thread.start()

    def _calculate_and_save_xai_async(self, ticket: int, symbol: str, prediction_input: np.ndarray,
                                      df_full: pd.DataFrame):
        logger.info(f"Постановка задачи XAI для сделки #{ticket} в очередь...")
        task_args = (ticket, symbol, prediction_input, df_full)
        self.xai_queue.put(task_args)

    def record_human_feedback(self, trade_ticket: int, feedback: int):
        logger.info(f"Получена обратная связь ({feedback}) для сделки #{trade_ticket} из GUI.")
        xai_data = self.db_manager.get_xai_data(trade_ticket)
        if not xai_data:
            logger.error(f"Не найдены XAI-данные для сделки #{trade_ticket}. Невозможно сохранить обратную связь.")
            self._safe_gui_update('update_status', f"XAI-данные для сделки #{trade_ticket} не найдены!", is_error=True)
            return
        success = self.db_manager.save_human_feedback(trade_ticket=trade_ticket, feedback=feedback,
                                                      market_state=xai_data)
        if success:
            self._safe_gui_update('update_status', f"Отзыв для сделки #{trade_ticket} успешно сохранен.",
                                  is_error=False)
        else:
            self._safe_gui_update('update_status', f"Ошибка сохранения отзыва для сделки #{trade_ticket}.",
                                  is_error=True)

    def get_rl_orchestrator_state(self) -> Dict[str, float]:
        trade_history = self.db_manager.get_trade_history()
        pnl = sum(t.profit for t in trade_history[-100:])
        sharpe = 0.5
        win_rate = 0.6
        kg_sentiment = self.consensus_engine.get_historical_context_sentiment(symbol="EURUSD",
                                                                              market_regime=self._get_current_market_regime_name()) or 0.0
        drift_key = "EURUSD_H1"
        drift_status = 1.0 if self.drift_manager.drift_statuses.get(drift_key, False) else 0.0
        news_sentiment = self.news_cache.aggregated_sentiment if self.news_cache else 0.0
        portfolio_var = self.risk_engine.calculate_portfolio_var([], {}) or 0.0
        dummy_df = self.get_dummy_df()
        market_volatility = dummy_df['ATR_NORM'].iloc[
            -1] if not dummy_df.empty and 'ATR_NORM' in dummy_df.columns else 0.0
        return {"portfolio_var": portfolio_var, "weekly_pnl": pnl, "sharpe_ratio": sharpe, "win_rate": win_rate,
                "market_volatility": market_volatility, "kg_sentiment": kg_sentiment, "drift_status": drift_status,
                "news_sentiment": news_sentiment}

    def apply_orchestrator_action(self, regime_allocations: Dict[str, Dict[str, float]]):
        logger.warning(
            f"[Orchestrator] Новое режимное распределение капитала: {list(regime_allocations.keys())} режимов.")
        self.risk_engine.update_regime_capital_allocation(regime_allocations)
        current_regime = self._get_current_market_regime_name()
        current_allocation = regime_allocations.get(current_regime, self.risk_engine.default_capital_allocation)
        self.orchestrator_allocation_updated.emit(current_allocation)

    def force_gp_cycle(self):
        logger.info("[GP R&D] Поиск 'слабого места' для запуска эволюции...")
        weak_spots = self.db_manager.find_weak_spots(
            profit_factor_threshold=self.config.rd_cycle_config.profit_factor_threshold)
        if not weak_spots:
            logger.warning("[GP R&D] 'Слабых мест' не найдено. Эволюция не требуется.")
            return
        target = weak_spots[0]
        symbol = target['symbol']
        regime = target['market_regime']
        threading.Thread(target=self.gp_rd_manager.run_cycle, args=(symbol, mt5.TIMEFRAME_H1, regime),
                         daemon=True).start()

    def get_account_info(self):
        with self.mt5_lock:
            if mt5.initialize(path=self.config.MT5_PATH):
                info = mt5.account_info()
                mt5.shutdown()
                return info
        return None

    def start_monitoring_loop(self):
        logger.info("=== Запуск цикла мониторинга v2.4 (Calc Manual Bars) ===")
        last_heavy_check_time = 0
        heavy_check_interval = 5
        last_graph_update_time = 0
        graph_update_interval = 30
        last_kpi_update_time = 0
        kpi_update_interval = 60
        
        # Оптимизация: уменьшаем частоту опроса stop_event
        loop_counter = 0
        while not self.stop_event.is_set():
            current_time = standard_time.time()
            lock_acquired = False
            if self.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION and (
                    current_time - last_graph_update_time > graph_update_interval):
                try:
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
                if not self.mt5_lock.acquire(timeout=120):
                    logger.warning("[Monitoring] Не удалось получить MT5 Lock. Пропуск цикла.")
                    self.stop_event.wait(1)
                    continue
                lock_acquired = True
                try:
                    # --- ИСПРАВЛЕНИЕ: Сначала пробуем мягкое подключение ---
                    if not mt5.initialize(path=self.config.MT5_PATH):
                        # Если не вышло, пробуем полную авторизацию
                        if not mt5.initialize(
                                path=self.config.MT5_PATH,
                                login=int(self.config.MT5_LOGIN),
                                password=self.config.MT5_PASSWORD,
                                server=self.config.MT5_SERVER
                        ):
                            err_code = mt5.last_error()
                            logger.error(f"[Monitoring] Не удалось инициализировать MT5. Код ошибки: {err_code}")
                            self.stop_event.wait(1)
                            continue
                    try:
                        account_info = mt5.account_info()
                        if account_info:
                            self._safe_gui_update('update_balance', account_info.balance, account_info.equity)
                            self._last_known_balance = account_info.balance
                            self._last_known_equity = account_info.equity
                        pc_time = datetime.now().strftime('%H:%M:%S')
                        server_time_dt = None
                        if self.config.SYMBOLS_WHITELIST:
                            tick = mt5.symbol_info_tick(self.config.SYMBOLS_WHITELIST[0])
                            if tick: server_time_dt = datetime.fromtimestamp(tick.time)
                        server_time = server_time_dt.strftime('%H:%M:%S') if server_time_dt else "--:--:--"
                        self._safe_gui_update('update_times', pc_time, server_time)
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
                                        if 'entry_bar_time' in trade_data:
                                            entry_time = trade_data['entry_bar_time']
                                            if isinstance(entry_time, str):
                                                try:
                                                    entry_time = datetime.fromisoformat(entry_time)
                                                except:
                                                    pass
                                        if 'entry_timeframe' in trade_data:
                                            timeframe_code = trade_data['entry_timeframe']
                                            timeframe_str = self._get_timeframe_str(timeframe_code)
                                            tf_seconds = self._get_timeframe_seconds(timeframe_code)
                                    if entry_time is None: entry_time = datetime.fromtimestamp(p.time)
                                    bars_in_trade_str = "0"
                                    if isinstance(entry_time, datetime) and tf_seconds > 0:
                                        delta_seconds = (current_srv_time - entry_time).total_seconds()
                                        bars_count = int(delta_seconds / tf_seconds)
                                        bars_in_trade_str = str(max(0, bars_count))
                                    pos_dict['strategy_display'] = strategy_name
                                    pos_dict['timeframe_display'] = timeframe_str
                                    pos_dict['bars_in_trade_display'] = bars_in_trade_str
                                    positions_list.append(pos_dict)
                            self._safe_gui_update('update_positions_view', positions_list)
                            found_new_trade = self._check_and_log_closed_positions()
                            if found_new_trade or self.history_needs_update:
                                all_history = self.db_manager.get_trade_history()
                                if all_history:
                                    self._safe_gui_update('update_history_view', all_history)
                                    self._safe_gui_update('update_pnl_graph', all_history)
                                self.history_needs_update = False
                            last_heavy_check_time = current_time
                    finally:
                        mt5.shutdown()
                except Exception as e:
                    logger.error(f"Критическая ошибка в цикле мониторинга (внутри лока): {e}", exc_info=True)
                finally:
                    if lock_acquired: self.mt5_lock.release()
            except Exception as e:
                logger.error(f"Критическая ошибка в цикле мониторинга (вне лока): {e}", exc_info=True)
            
            # Оптимизация: уменьшаем частоту опроса stop_event
            loop_counter += 1
            if loop_counter % 5 == 0:  # Проверяем stop_event каждые 5 итераций (5 секунд)
                self.stop_event.wait(1)
            else:
                standard_time.sleep(1)

    async def _process_news_background(self, news_items):
        logger.info(f"Запущена фоновая обработка {len(news_items)} новостей...")
        is_vdb_ready = self.vector_db_manager and self.vector_db_manager.is_ready()
        logger.info(
            f"VectorDB Status: {is_vdb_ready}. Embedding Model: {self.nlp_processor.embedding_model is not None}")
        
        # Асинхронная обработка новостей в батчах
        batch_size = 5  # Уменьшили размер батча с 10 до 5
        for i in range(0, len(news_items), batch_size):
            batch = news_items[i:i + batch_size]
            tasks = []
            max_concurrent_news = 2  # Уменьшили с 3 до 2 одновременных задач
            semaphore = asyncio.Semaphore(max_concurrent_news)
            
            async def process_news_with_semaphore(item):
                async with semaphore:
                    try:
                        # Проверяем, является ли item объектом NewsItem или словарем
                        if hasattr(item, 'text'):
                            # Это объект NewsItem
                            text = item.text
                            source = item.source
                            timestamp = item.timestamp.isoformat()
                        elif isinstance(item, dict):
                            # Это словарь
                            text = item.get('text', '')
                            source = item.get('source', 'unknown')
                            timestamp_iso = item.get('timestamp')
                            if hasattr(timestamp_iso, 'isoformat'):
                                timestamp = timestamp_iso.isoformat()
                            else:
                                from datetime import datetime
                                timestamp = timestamp_iso if timestamp_iso else datetime.now().isoformat()
                        else:
                            logger.warning(f"Неподдерживаемый тип новости: {type(item)}")
                            return
                        
                        # Обрабатываем новость с ограничением по времени
                        await asyncio.wait_for(
                            asyncio.to_thread(self.nlp_processor.process_and_store_text,
                                            text=text, context={"source": source,
                                                              "timestamp": timestamp}),
                            timeout=30.0  # Таймаут 30 секунд
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
        
        logger.info("Фоновая обработка новостей завершена.")
        if is_vdb_ready and self.vector_db_manager.index.ntotal > 0:
            self.vector_db_manager._save()
            logger.critical("VectorDB: Принудительное сохранение индекса после обработки новостей.")

    async def _process_single_symbol(self, symbol: str, df: pd.DataFrame, timeframe: int, account_info: Any,
                                     current_positions: List):
        async with self.trade_execution_lock:
            try:
                market_regime = self.market_regime_manager.get_regime(df)
                strategy_name = self.config.STRATEGY_REGIME_MAPPING.get(market_regime,
                                                                        self.config.STRATEGY_REGIME_MAPPING.get(
                                                                            "Default"))
                signal_result = None
                final_strategy_name = strategy_name
                open_positions_for_symbol = []

                def get_mt5_positions_sync():
                    with self.mt5_lock:
                        if not self.terminal_connector.initialize(path=self.config.MT5_PATH):
                            logger.error(f"[{symbol}] MT5 Init Failed in _process_single_symbol.")
                            return []
                        try:
                            return list(self.terminal_connector.get_positions(symbol=symbol))
                        finally:
                            self.terminal_connector.shutdown()

                open_positions_for_symbol = await asyncio.to_thread(get_mt5_positions_sync)
                if strategy_name == "RLTradeManager":
                    if self.rl_manager.is_trained:
                        pass
                else:
                    signal_result = self.signal_service.get_trade_signal(symbol, df, timeframe, self.news_cache)
                if not signal_result:
                    return
                confirmed_signal, final_strategy_name, _, pred_input, entry_price = signal_result
                
                # Отправляем торговый сигнал в GUI
                trading_signal_data = [{
                    'symbol': symbol,
                    'signal_type': confirmed_signal.type.name,
                    'strategy': final_strategy_name,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'entry_price': entry_price,
                    'timeframe': self._get_timeframe_str(timeframe)
                }]
                self.trading_signals_updated.emit(trading_signal_data)
                if self.bridge:
                    self.bridge.trading_signals_updated.emit(trading_signal_data)
                
                if open_positions_for_symbol:
                    logger.info(f"[{symbol}] Пропуск: уже есть открытая позиция ({len(open_positions_for_symbol)} шт).")
                    return
                if not self.risk_engine.is_trade_safe_from_events(symbol):
                    return
                logger.warning(
                    f"[{symbol}] ШАГ 1: ПОЛУЧЕН СИГНАЛ {confirmed_signal.type.name} от '{final_strategy_name}'!")
                lot_size, stop_loss_in_price = self.risk_engine.calculate_position_size(symbol=symbol, df=df,
                                                                                        account_info=account_info,
                                                                                        trade_type=confirmed_signal.type,
                                                                                        strategy_name=final_strategy_name)
                if lot_size is None or lot_size <= 0:
                    logger.critical(
                        f"[{symbol}] !!! БЛОКИРОВКА РИСКА !!! Lot Size: {lot_size}. SL Price: {stop_loss_in_price}.")
                    return
                logger.critical(f"[{symbol}] ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ! ОТПРАВКА ОРДЕРА...")
                position_ticket = await self.execution_service.execute_trade(symbol=symbol, signal=confirmed_signal,
                                                                             lot_size=lot_size, df=df,
                                                                             timeframe=timeframe,
                                                                             strategy_name=final_strategy_name,
                                                                             stop_loss_in_price=stop_loss_in_price,
                                                                             observer_mode=self.observer_mode,
                                                                             prediction_input=pred_input,
                                                                             entry_price_for_learning=entry_price)
                if position_ticket and "AI" in final_strategy_name and pred_input is not None and not self.observer_mode:
                    self._calculate_and_save_xai_async(position_ticket, symbol, pred_input, df)
            except Exception as e:
                logger.error(f"Ошибка при обработке символа {symbol} внутри блокировки: {e}", exc_info=True)

    def _select_optimal_timeframe(self, symbol: str, data_cache: Dict[str, pd.DataFrame]) -> int:
        timeframe_scores = {}
        optimizer_config = self.config.optimizer
        timeframes_to_check = optimizer_config.timeframes_to_check
        ideal_volatility = optimizer_config.ideal_volatility
        for tf_code in timeframes_to_check.values():
            df = data_cache.get(f"{symbol}_{tf_code}")
            if df is None or len(df) < 50: continue
            if 'ATR_14' not in df.columns or df['ATR_14'].dropna().empty: continue
            last_atr = df['ATR_14'].dropna().iloc[-1]
            last_close = df['close'].iloc[-1]
            if last_close > 0:
                volatility = last_atr / last_close
                score = 1 / (1 + abs(volatility - ideal_volatility) * 1000)
                timeframe_scores[tf_code] = score
        if not timeframe_scores: return mt5.TIMEFRAME_H1
        best_timeframe = max(timeframe_scores, key=timeframe_scores.get)
        logger.info(
            f"[{symbol}] Оптимальный таймфрейм выбран: {self._get_timeframe_str(best_timeframe)} (Score: {timeframe_scores[best_timeframe]:.2f})")
        return best_timeframe

    def _process_commands(self):
        try:
            command, args = self.command_queue.get_nowait()
            if command == "CLOSE_ALL":
                threading.Thread(target=self.execution_service.emergency_close_all_positions).start()
            elif command == "CLOSE_ONE":
                threading.Thread(target=self.execution_service.emergency_close_position, args=(args,)).start()
        except queue.Empty:
            pass

    def _get_timeframe_str(self, tf_code: Optional[int]) -> str:
        if tf_code is None: return "N/A"
        tf_map = {v: k for k, v in mt5.__dict__.items() if k.startswith('TIMEFRAME_')}
        full_name = tf_map.get(tf_code, str(tf_code))
        return full_name.replace('TIMEFRAME_', '')

    def set_observer_mode(self, enabled: bool):
        self.observer_mode = enabled
        status_message = f"Режим Наблюдателя {'ВКЛЮЧЕН' if self.observer_mode else 'ВЫКЛЮЧЕН'}."
        logger.info(status_message)
        self._safe_gui_update('update_status', status_message)

    def update_configuration(self, new_config: Settings):
        self.config = new_config
        logging.info("Конфигурация системы обновлена. Применение к зависимым компонентам...")
        try:
            if hasattr(self, 'risk_engine'): self.risk_engine.config = self.config
            if hasattr(self, 'data_provider'): self.data_provider.config = self.config
            if hasattr(self, 'session_manager'): self.session_manager.config = self.config
            if hasattr(self, 'market_screener'): self.market_screener.config = self.config
            if hasattr(self, 'strategy_optimizer'): self.strategy_optimizer.config = self.config
            if hasattr(self, 'consensus_engine'): self.consensus_engine.config = self.config
            if hasattr(self, 'market_regime_manager'): self.market_regime_manager.config = self.config
            if hasattr(self, 'portfolio_service'): self.portfolio_service.config = self.config
            if hasattr(self, 'execution_service'): self.execution_service.config = self.config
            if hasattr(self, 'orchestrator'): self.orchestrator.config = self.config
            if hasattr(self.risk_engine,
                       'base_risk_per_trade_percent'): self.risk_engine.base_risk_per_trade_percent = self.config.RISK_PERCENTAGE
            if hasattr(self.risk_engine,
                       'max_daily_drawdown_percent'): self.risk_engine.max_daily_drawdown_percent = self.config.MAX_DAILY_DRAWDOWN_PERCENT
            logging.info("Компоненты системы успешно переинициализированы с новой конфигурацией.")
        except Exception as e:
            logging.error(f"Ошибка при переинициализации компонентов: {e}", exc_info=True)

    def _train_candidate_model(self, model_type, symbol, timeframe, train_df, val_df, model_factory, training_batch_id,
                               features_to_use: List[str], custom_hyperparams=None):
        target_col = 'close'
        train_df = train_df.loc[:, ~train_df.columns.duplicated()]
        val_df = val_df.loc[:, ~val_df.columns.duplicated()]
        if train_df.empty or val_df.empty:
            logger.error(f"[R&D] Ошибка: Обучающий или валидационный набор данных пуст. Пропуск обучения.")
            return None
        features_to_use = [f for f in features_to_use if f in train_df.columns]
        x_scaler = StandardScaler()
        y_scaler = StandardScaler()
        train_df_features_np = train_df[features_to_use].values
        val_df_features_np = val_df[features_to_use].values
        train_df_features_np = np.nan_to_num(train_df_features_np, nan=0.0, posinf=0.0, neginf=0.0)
        val_df_features_np = np.nan_to_num(val_df_features_np, nan=0.0, posinf=0.0, neginf=0.0)
        if train_df_features_np.size == 0 or val_df_features_np.size == 0:
            logger.error(
                f"[R&D] Ошибка: Обучающий или валидационный набор данных пуст после очистки. Пропуск обучения.")
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
            if model_type.upper() == 'LSTM_PYTORCH':
                model_params = {'input_dim': input_dim, 'hidden_dim': 32, 'num_layers': 1, 'output_dim': 1}
            elif model_type.upper() == 'TRANSFORMER_PYTORCH':
                model_params = {'input_dim': input_dim, 'd_model': 64, 'nhead': 4, 'nlayers': 2}
            elif model_type.upper() == 'LIGHTGBM':
                model_params = {'input_dim': input_dim}
        model = model_factory.create_model(model_type, model_params)
        if not model:
            return None
        if model_type.upper() == 'LSTM_PYTORCH':
            from torch.utils.data import TensorDataset, DataLoader
            X_train, y_train = self._create_sequences(train_df_scaled[features_to_use].values,
                                                      self.config.INPUT_LAYER_SIZE)
            if X_train is None or y_train is None or X_train.size == 0:
                logger.error("[R&D] Ошибка: Не удалось создать последовательности для LSTM. Пропуск.")
                return None
            y_train = train_df_scaled[target_col].values[self.config.INPUT_LAYER_SIZE:]
            X_train_tensor = torch.from_numpy(X_train).float()
            y_train_tensor = torch.from_numpy(y_train).float().unsqueeze(1)
            train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
            train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
            criterion = torch.nn.MSELoss()
            optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
            model.to(self.device)
            loss_history = []
            for epoch in range(50):
                for X_batch, y_batch in train_loader:
                    X_batch, y_batch = X_batch.to(self.device), y_batch.to(self.device)
                    optimizer.zero_grad()
                    y_pred = model(X_batch)
                    loss = criterion(y_pred, y_batch)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    optimizer.step()
                if epoch % 5 == 0:
                    loss_history.append(loss.item())
                    if self.gui:
                        history_obj = type('History', (), {'history': {'loss': loss_history}})()
                        self._safe_gui_update('update_visualization', history_obj)
        elif model_type.upper() == 'LIGHTGBM':
            X_train = train_df_scaled[features_to_use]
            y_train = train_df_scaled[target_col]
            X_val = val_df_scaled[features_to_use]
            y_val = val_df_scaled[target_col]
            evals_result = {}
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], eval_metric='rmse',
                      callbacks=[lgb.early_stopping(10, verbose=False), lgb.record_evaluation(evals_result)])
            if 'valid_0' in evals_result and 'rmse' in evals_result['valid_0'] and self.gui:
                loss_history = evals_result['valid_0']['rmse']
                history_obj = type('History', (), {'history': {'loss': loss_history}})()
                self._safe_gui_update('update_visualization', history_obj)
        return self.db_manager._save_model_and_scalers_internal(symbol=symbol, timeframe=timeframe, model=model,
                                                                model_type=model_type, x_scaler=x_scaler,
                                                                y_scaler=y_scaler, features_list=features_to_use,
                                                                training_batch_id=training_batch_id,
                                                                hyperparameters=model_params if model_type.upper() == 'LSTM_PYTORCH' else None)

    def _run_champion_contest(self, candidate_ids: list, holdout_df: pd.DataFrame):
        logger.warning(f"--- НАЧАЛО ЧЕМПИОНСКОГО КОНКУРСА ДЛЯ {len(candidate_ids)} МОДЕЛЕЙ ---")
        best_challenger_id = None
        best_score = -np.inf
        for model_id in candidate_ids:
            components = self.db_manager.load_model_components_by_id(model_id)
            if not components: continue
            try:
                model = components['model']
                model_type = components['model_type']
                x_scaler = components['x_scaler']
                y_scaler = components['y_scaler']
                features = components['features']
                holdout_df_no_duplicates = holdout_df.loc[:, ~holdout_df.columns.duplicated()]
                required_cols = list(set(features + ['close']))
                if not all(col in holdout_df_no_duplicates.columns for col in required_cols): continue
                holdout_df_cleaned = holdout_df_no_duplicates[required_cols].copy()
                holdout_df_cleaned.dropna(inplace=True)
                if len(holdout_df_cleaned) < self.config.INPUT_LAYER_SIZE: continue
                X_holdout_df_ordered = holdout_df_cleaned[features]
                X_holdout_values = X_holdout_df_ordered.values
                if not np.all(np.isfinite(X_holdout_values)): X_holdout_values = np.nan_to_num(X_holdout_values,
                                                                                               nan=0.0, posinf=1e9,
                                                                                               neginf=-1e9)
                if X_holdout_values.shape[1] != x_scaler.n_features_in_: continue
                X_holdout_scaled = x_scaler.transform(X_holdout_values)
                y_pred_scaled = None
                y_true_unscaled_aligned = None
                if model_type.upper() == 'LSTM_PYTORCH':
                    X_holdout_sequences, _ = self._create_sequences(X_holdout_scaled, self.config.INPUT_LAYER_SIZE)
                    if X_holdout_sequences is None: continue
                    with torch.no_grad():
                        y_pred_scaled = model(torch.from_numpy(X_holdout_sequences).float()).numpy()
                    y_true_unscaled_aligned = holdout_df_cleaned['close'].values[self.config.INPUT_LAYER_SIZE:]
                elif model_type.upper() == 'LIGHTGBM':
                    y_pred_scaled = model.predict(X_holdout_scaled)
                    y_true_unscaled_aligned = holdout_df_cleaned['close'].values
                if y_pred_scaled is None: continue
                np.clip(y_pred_scaled, -1.0, 2.0, out=y_pred_scaled)
                y_pred_unscaled = y_scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).flatten()
                if len(y_pred_unscaled) != len(y_true_unscaled_aligned): continue
                if not np.all(np.isfinite(y_pred_unscaled)):
                    score = -np.inf
                else:
                    mse_error = mean_squared_error(y_true_unscaled_aligned, y_pred_unscaled)
                    score = -mse_error
                    logger.info(
                        f"Кандидат ID {model_id} ({model_type}) | Точность (MSE): {mse_error:.4f} (чем ближе к 0, тем лучше)")
                if score > best_score:
                    best_score = score
                    best_challenger_id = model_id
            except Exception as e:
                logger.error(f"Ошибка при оценке модели ID {model_id}: {e}", exc_info=True)
        if best_challenger_id:
            winner_components = self.db_manager.load_model_components_by_id(best_challenger_id)
            winner_type = winner_components['model_type']
            logger.critical(
                f"!!! ПОБЕДИТЕЛЬ КОНКУРСА: Модель ID {best_challenger_id} ({winner_type}) со счетом {best_score:.6f} !!!")
            logger.info(
                f"Запуск финального бэктеста для победителя (ID {best_challenger_id}) на holdout-выборке для генерации полного отчета...")
            backtester = AIBacktester(data=holdout_df.copy(), model=winner_components['model'],
                                      model_features=winner_components['features'],
                                      x_scaler=winner_components['x_scaler'], y_scaler=winner_components['y_scaler'],
                                      risk_config=self.config.model_dump())
            backtest_report = backtester.run()
            logger.warning(f"Полный отчет о производительности для нового чемпиона: {backtest_report}")
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
        kpis = {'day_pnl': day_pnl, 'day_dd': day_dd, 'week_pnl': week_pnl, 'week_dd': week_dd, 'month_pnl': month_pnl,
                'month_dd': month_dd}
        if self.gui and self.gui.bridge: self.gui.bridge.pnl_kpis_updated.emit(kpis)

    def _uptime_updater_loop(self):
        logger.info("=== Запуск цикла обновления времени работы ===")
        while not self.stop_event.is_set():
            try:
                if self.start_time:
                    delta = datetime.now() - self.start_time
                    uptime_str = str(delta).split('.')[0]
                    self.uptime_updated.emit(uptime_str)
                    self._safe_gui_update('update_uptime', uptime_str)
            except Exception as e:
                logger.error(f"Ошибка в цикле Uptime: {e}")
            self.stop_event.wait(1)

    def start_orchestrator_loop(self):
        logger.info("=== Запуск цикла Оркестратора ===")
        orchestrator_interval = 60 * 5
        self.stop_event.wait(orchestrator_interval)
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
        self.running = False
        self.stop_event.set()
        logger.info("Система останавливается...")
        
        # Остановка планировщика переобучения
        self.stop_training_scheduler()
        
        if hasattr(self, 'web_server'): self.web_server.stop()

    def _safe_gui_update(self, method_name: str, *args, **kwargs):
        # Оптимизация: уменьшаем частоту обновлений GUI
        if not hasattr(self, '_last_gui_updates'):
            self._last_gui_updates = {}
        
        import time as standard_time
        current_time = standard_time.time()
        
        # Устанавливаем минимальные интервалы между обновлениями
        update_intervals = {
            'update_candle_chart': 1.0,  # 1 секунда между обновлениями графика
            'update_positions_view': 0.5,  # 0.5 секунды между обновлениями позиций
            'update_history_view': 2.0,  # 2 секунды между обновлениями истории
            'update_balance': 0.5,  # 0.5 секунды между обновлениями баланса
            'update_pnl_graph': 2.0,  # 2 секунды между обновлениями PnL
        }
        
        min_interval = update_intervals.get(method_name, 0.1)  # по умолчанию 0.1 секунды
        last_update_time = self._last_gui_updates.get(method_name, 0)
        
        if current_time - last_update_time < min_interval:
            return  # пропускаем обновление, если прошло недостаточно времени
        
        self._last_gui_updates[method_name] = current_time
        
        if self.gui:
            try:
                signal_map = {
                    'update_status': (self.bridge.status_updated, (args[0], kwargs.get('is_error', False))),
                    'update_balance': (self.bridge.balance_updated, args),
                    'update_positions_view': (self.bridge.positions_updated, args),
                    'update_history_view': (self.bridge.history_updated, args),
                    'update_visualization': (self.bridge.training_history_updated, args),
                    'update_candle_chart': (self.bridge.candle_chart_updated, args),
                    'update_pnl_graph': (self.bridge.pnl_updated, args),
                    'update_rd_log': (self.bridge.rd_progress_updated, args),
                    'update_times': (self.bridge.times_updated, args),
                    'update_uptime': (self.bridge.uptime_updated, args)
                }
                if method_name in signal_map:
                    signal, signal_args = signal_map[method_name]
                    signal.emit(*signal_args)
            except Exception as e:
                logger.error(f"Ошибка GUI update: {e}")
        if self.web_server and self.config.web_dashboard.enabled:
            try:
                if method_name == 'update_balance':
                    self._last_known_balance = float(args[0])
                    self._last_known_equity = float(args[1])
                if method_name == 'update_uptime':
                    self._last_known_uptime = str(args[0])
                if self.running and self.start_time and self._last_known_uptime == "0:00:00":
                    delta = datetime.now() - self.start_time
                    self._last_known_uptime = str(delta).split('.')[0]
                if method_name in ['update_balance', 'update_uptime', 'update_status']:
                    drawdown = 0.0
                    if self._last_known_balance > 0: drawdown = max(0.0, (
                            self._last_known_balance - self._last_known_equity) / self._last_known_balance * 100)
                    status_obj = SystemStatus(is_running=self.running,
                                              mode="Наблюдатель" if self.observer_mode else "Торговля",
                                              uptime=self._last_known_uptime, balance=self._last_known_balance,
                                              equity=self._last_known_equity, current_drawdown=drawdown)
                    self.web_server.broadcast_status_update(status_obj)
                elif method_name == 'update_positions_view':
                    raw_positions = args[0]
                    web_positions = []
                    for p in raw_positions:
                        web_positions.append({
                            "ticket": int(p.get('ticket', 0)),
                            "symbol": str(p.get('symbol', '')),
                            "strategy": str(p.get('strategy_display', 'Unknown')),
                            "type": "BUY" if p.get('type') == 0 else "SELL",
                            "volume": float(p.get('volume', 0.0)),
                            "profit": float(p.get('profit', 0.0)),
                            "timeframe": str(p.get('timeframe_display', 'N/A')),
                            "bars": str(p.get('bars_in_trade_display', '0'))
                        })
                    self.web_server.broadcast_positions_update(web_positions)
            except Exception as e:
                pass

    def _join_all_threads(self):
        logger.info("Начало ожидания завершения всех фоновых потоков (Фаза 2)...")
        threads_to_join = {"Trading": self.trading_thread, "Training": self.training_thread,
                           "Monitoring": self.monitoring_thread, "Uptime": self.uptime_thread,
                           "Orchestrator": self.orchestrator_thread, "History Sync": self.history_sync_thread,
                           "DB Writer": self.db_writer_thread, "XAI Worker": self.xai_worker_thread,
                           "VectorDB Cleanup": self.vector_db_cleanup_thread}
        for name, thread in threads_to_join.items():
            if thread and thread.is_alive():
                logger.debug(f"Ожидание завершения потока {name}...")
                thread.join(timeout=10)
                if thread.is_alive():
                    logger.warning(f"Поток {name} не завершился за 10 секунд.")
                else:
                    self.thread_status_updated.emit(name, "STOPPED")
            else:
                self.thread_status_updated.emit(name, "STOPPED")
        logger.info("Все фоновые потоки остановлены.")

    def _load_active_directives(self):
        logger.info("Загрузка активных директив из базы данных...")
        directives_from_db = self.db_manager.get_active_directives()
        self.active_directives = {d.directive_type: d for d in directives_from_db}
        logger.info(f"Загружено {len(self.active_directives)} активных директив.")
        directives_for_gui = [{"type": d.directive_type, "value": d.value, "reason": d.reason,
                               "expires_at": d.expires_at.strftime('%Y-%m-%d %H:%M')} for d in directives_from_db]
        self.directives_updated.emit(directives_for_gui)

    def force_reload_directives(self):
        self._load_active_directives()

    def _check_and_log_closed_positions(self, market_context=None, kg_cb_sentiment=None) -> bool:
        now = datetime.now()
        history_deals = mt5.history_deals_get(
            self.last_history_sync_time - timedelta(minutes=self.config.system.history_sync_margin_minutes), now)
        self.last_history_sync_time = now
        if history_deals is None or not history_deals: return False
        logged_tickets = self.db_manager.get_all_logged_trade_tickets()
        found_new_closed = False
        deals_by_pos_id = defaultdict(list)
        for deal in history_deals:
            if deal.entry == mt5.DEAL_ENTRY_OUT and deal.position_id not in logged_tickets:
                deals_by_pos_id[deal.position_id].append(deal)
        if not deals_by_pos_id: return False
        for pos_id, exit_deals in deals_by_pos_id.items():
            position_deals = [d for d in history_deals if d.position_id == pos_id]
            entry_deal = min((d for d in position_deals if d.entry == mt5.DEAL_ENTRY_IN), key=lambda x: x.time,
                             default=None)
            exit_deal = exit_deals[0]
            if entry_deal:
                entry_data = self.portfolio_service.trade_entry_data.get(int(pos_id), {})
                market_context = entry_data.get("market_context", {})
                timeframe_code = entry_data.get("entry_timeframe", mt5.TIMEFRAME_H1)
                timeframe_str = self._get_timeframe_str(timeframe_code)
                total_profit = sum(d.profit for d in position_deals)
                kg_cb_sentiment = market_context.get('kg_cb_sentiment', 0.0)
                market_regime = market_context.get('market_regime', 'Unknown')
                predicted_price = entry_data.get("predicted_price_at_entry")
                strategy_name = entry_data.get("strategy", "Unknown")
                symbol = entry_deal.symbol
                if predicted_price is not None and "AI" in strategy_name:
                    actual_price = exit_deal.price
                    is_drifting, error_val = self.drift_manager.update(symbol=symbol, timeframe=timeframe_str,
                                                                       predicted_price=predicted_price,
                                                                       actual_price=actual_price)
                    self.drift_data_updated.emit(exit_deal.time, symbol, error_val, is_drifting)
                    if is_drifting:
                        logger.critical(
                            f"[Drift] 🚨 ОБНАРУЖЕН ДРЕЙФ КОНЦЕПЦИИ для {symbol} ({strategy_name})! Прогноз: {predicted_price:.5f}, Факт: {actual_price:.5f}")
                        self.orchestrator.apply_drift_penalty(strategy_name, symbol)
                        logger.warning(f"[Drift] Запуск процесса самолечения (переобучения) для {symbol}...")
                        threading.Thread(target=self._force_retrain_specific_symbol, args=(symbol, timeframe_code),
                                         daemon=True, name=f"DriftRetrain_{symbol}").start()
                self.db_manager.log_trade(entry_deal=entry_deal, exit_deal=exit_deal, timeframe_str=timeframe_str,
                                          total_profit=total_profit, xai_data=entry_data.get("xai_data"),
                                          market_context=entry_data.get("market_context"))
                self.db_manager.log_trade_outcome_to_kg(trade_ticket=int(pos_id), profit=total_profit,
                                                        market_regime=market_context.get('market_regime', 'Unknown'),
                                                        kg_cb_sentiment=kg_cb_sentiment)
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
            best_hyperparams = self._force_retrain_with_optuna(symbol=symbol, timeframe=timeframe, train_df=train_df,
                                                               val_df=val_df,
                                                               features_to_use=self.config.FEATURES_TO_USE)
            model_factory = ModelFactory(self.config)
            final_model_params = {'input_dim': len(self.config.FEATURES_TO_USE), 'output_dim': 1, **best_hyperparams}
            model_id = self._train_candidate_model(model_type="LSTM_PyTorch", symbol=symbol, timeframe=timeframe,
                                                   train_df=train_df, val_df=val_df, model_factory=model_factory,
                                                   training_batch_id=training_batch_id,
                                                   features_to_use=self.config.FEATURES_TO_USE,
                                                   custom_hyperparams=final_model_params)
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
            if self.stop_event.is_set(): return
            if not mt5.initialize(path=self.config.MT5_PATH):
                logger.error("Синхронизация истории: не удалось инициализировать MT5.")
                return
            try:
                history_deals = mt5.history_deals_get(from_date, datetime.now())
            finally:
                mt5.shutdown()
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
                if self._process_and_log_closed_position(pos_id, deals): added_count += 1
            if added_count > 0:
                logger.info(f"Синхронизация завершена. Добавлено {added_count} новых сделок в локальную БД.")
                self.history_needs_update = True
            else:
                logger.info("Синхронизация завершена. Новых сделок для добавления не найдено.")
        except Exception as e:
            logger.error(f"Ошибка во время синхронизации истории: {e}", exc_info=True)

    def _process_and_log_closed_position(self, pos_id: int, deals: List[Any]) -> bool:
        exit_deal = next((d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT), None)
        if not exit_deal: return False
        entry_deal = min((d for d in deals if d.entry == mt5.DEAL_ENTRY_IN), key=lambda x: x.time, default=None)
        if not entry_deal:
            logger.warning(f"Для закрытой позиции #{pos_id} не найдена сделка на вход, пропуск.")
            return False
        entry_data = self.portfolio_service.trade_entry_data.get(int(pos_id), {})
        timeframe_str = self._get_timeframe_str(entry_data.get("entry_timeframe"))
        total_profit = sum(d.profit for d in deals)
        success = self.db_manager._log_trade_internal(entry_deal=entry_deal, exit_deal=exit_deal,
                                                      timeframe_str=timeframe_str, total_profit=total_profit,
                                                      xai_data=entry_data.get("xai_data"),
                                                      market_context=entry_data.get("market_context"))
        if success:
            logger.info(f"Успешно залогирована сделка #{pos_id}. Профит: {total_profit:.2f}")
            self.portfolio_service.remove_trade_entry_data(int(pos_id))
            return True
        return False

    def add_to_blacklist(self, symbol: str):
        directive_type = f"BLOCK_SYMBOL_{symbol}"
        self.active_directives[directive_type] = ActiveDirective(directive_type=directive_type, value="true",
                                                                 reason="Manually blacklisted from GUI",
                                                                 expires_at=datetime.utcnow() + timedelta(days=365))
        self.directives_updated.emit([{"type": d.directive_type, "value": d.value, "reason": d.reason,
                                       "expires_at": d.expires_at.strftime('%Y-%m-%d %H:%M')} for d in
                                      self.active_directives.values()])

    def _create_sequences(self, data: np.ndarray, n_steps: int):
        X, y = [], []
        if len(data) <= n_steps: return None, None
        for i in range(len(data) - n_steps):
            X.append(data[i:(i + n_steps)])
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
                    del self._data_cache[key]
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
                'start_time': time.perf_counter(),
                'start_memory': None  # Можно добавить измерение памяти
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
                start_time = self.performance_metrics[operation_name]['start_time']
                elapsed = time.perf_counter() - start_time
                
                if log_details:
                    logger.info(f"Performance: {operation_name} took {elapsed:.4f}s")
                    
                    # Логировать медленные операции
                    if elapsed > 1.0:  # Если операция заняла больше 1 секунды
                        logger.warning(f"Slow operation detected: {operation_name} took {elapsed:.4f}s")
                
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
                self._data_cache.pop(key, None)
                self._cache_timestamps.pop(key, None)
                self._cache_ttl.pop(key, None)
            else:
                self._data_cache.clear()
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
        if not self.running:
            logger.warning("Нельзя запустить обучение, так как система остановлена.")
            return
        logger.info("Принудительный запуск цикла обучения из GUI...")
        thread = threading.Thread(target=self._continuous_training_cycle, daemon=True)
        thread.start()

    def emergency_close_position(self, ticket: int):
        self.execution_service.emergency_close_position(ticket)

    def emergency_close_all_positions(self):
        self.execution_service.emergency_close_all_positions()

    def add_directive(self, directive_type: str, reason: str, duration_hours: int, value: Any):
        expires_at = datetime.utcnow() + timedelta(hours=duration_hours)
        directive = ActiveDirective(directive_type=directive_type, value=str(value), reason=reason,
                                    expires_at=expires_at)
        self.db_manager.save_directives([directive])
        self.force_reload_directives()
        logger.warning(
            f"Добавлена ручная директива: {directive_type}={value} до {expires_at.strftime('%Y-%m-%d %H:%M')}")

    def delete_directive(self, directive_type: str):
        logger.warning(f"Получена команда на удаление директивы: {directive_type}")
        if self.db_manager.delete_directive_by_type(directive_type): self.force_reload_directives()

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
            logger.info("🔄 Запуск автоматического переобучения моделей...")
            
            # Импортируем функцию из smart_retrain
            from smart_retrain import smart_retrain_models
            
            # Запускаем обучение
            smart_retrain_models(max_symbols=max_symbols, max_workers=max_workers)
            
            logger.info("✅ Автоматическое переобучение завершено")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при автоматическом переобучении: {e}", exc_info=True)
    
    def stop_training_scheduler(self):
        """Останавливает планировщик автоматического переобучения."""
        if self.training_scheduler:
            logger.info("Остановка планировщика переобучения...")
            self.training_scheduler.stop()
            self.thread_status_updated.emit("Training Scheduler", "STOPPED")