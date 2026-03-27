# -*- coding: utf-8 -*-
# main_pyside.py
from src.analysis.event_driven_backtester import EventDrivenBacktester
from src.analysis.system_backtester import SystemBacktester
from src.data.knowledge_graph_querier import KnowledgeGraphQuerier
from PySide6.QtWebChannel import QWebChannel
from src.utils.scheduler_manager import SchedulerManager
from src.core.config_models import Settings
from src.data.data_provider import DataProvider
from src.strategies.strategy_loader import StrategyLoader
from src._version import __version__
from src.gui.control_center_widget import ControlCenterWidget
from src.gui.sound_manager import SoundManager
from src.gui.styles import LIGHT_STYLE, DARK_STYLE
from src.gui.settings_window import SettingsWindow
from src.gui.log_utils import ColorFormatter, QtLogHandler, setup_qt_logging
from src.core.config_loader import load_config
from src.core.trading_system import TradingSystem
from pyqtgraph import BarGraphItem
from PySide6.QtGui import QColor, QTextCharFormat, QPainterPath, QAction, QIcon
from src.utils.worker import Worker
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal, QObject, QAbstractTableModel, QRectF, QUrl, QDate, QEvent, QPointF, Slot, QRunnable
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
                               QSplitter, QTextEdit, QTabWidget, QLabel, QCheckBox, QTableView, QHeaderView,
                               QMessageBox, QComboBox, QDateEdit, QMenu, QDialog, QLineEdit, QSpinBox, QDialogButtonBox,
                               QGridLayout, QDoubleSpinBox, QGroupBox, QTableWidgetItem, QTableWidget)
from datetime import datetime
from PySide6.QtCore import QTimer, Slot, QThreadPool, QRunnable
import MetaTrader5 as mt5
import queue
import multiprocessing
import pyqtgraph as pg
import subprocess
import numpy as np
import pandas as pd
import warnings
import tempfile
from typing import Optional, Dict, Any, List
import time
import threading
import matplotlib.pyplot as plt
import matplotlib
import json
from urllib3.exceptions import InsecureRequestWarning
from requests.exceptions import SSLError
import requests
import urllib3
import asyncio
import sys
import os
import logging
from pathlib import Path

# ===================================================================
# === НАСТРОЙКА ЛОГИРОВАНИЯ (должно быть самым первым) ===
# ===================================================================
from src.utils.logger import setup_logger, get_logger

# Создаём главный логгер приложения
logger = setup_logger(
    name='genesis',
    level=logging.INFO,
    log_to_file=True,
    log_to_console=True,
    rotation='daily',
    backup_count=7
)

logger.info("=" * 60)
logger.info("  Genesis Trading System - Запуск")
logger.info("=" * 60)
logger.info(f"Версия Python: {sys.version}")
logger.info(f"Путь к скрипту: {Path(__file__).resolve()}")
# ===================================================================


# ===================================================================
# === ПРОВЕРКА КОНФИГУРАЦИИ ПЕРЕД ЗАПУСКОМ ===
# ===================================================================

def check_and_run_setup():
    """Проверка конфигурации и запуск мастера настройки при необходимости"""
    # Определяем путь к конфигу
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent

    config_path = base_path / 'configs' / 'settings.json'

    needs_setup = False
    reason = ""

    # Проверка существования конфига
    if not config_path.exists():
        needs_setup = True
        reason = "Файл конфигурации не найден"
    else:
        # Проверка критических параметров
        try:
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                content = "".join(
                    line for line in f if not line.strip().startswith("//"))
                config = json.loads(content)

            # Проверка обязательных полей
            required_fields = ['MT5_LOGIN',
                               'MT5_PASSWORD', 'MT5_SERVER', 'MT5_PATH']
            missing_fields = []
            for field in required_fields:
                if field not in config or not config[field]:
                    missing_fields.append(field)

            if missing_fields:
                needs_setup = True
                reason = f"Отсутствуют обязательные параметры: {', '.join(missing_fields)}"

            # Проверка путей
            if 'MT5_PATH' in config and config['MT5_PATH']:
                mt5_path = Path(config['MT5_PATH'])
                if not mt5_path.exists():
                    needs_setup = True
                    reason = f"MT5 терминал не найден по пути: {config['MT5_PATH']}"

        except Exception as e:
            needs_setup = True
            reason = f"Ошибка чтения конфигурации: {e}"

    if needs_setup:
        print("\n" + "=" * 60)
        print("  [!] ТРЕБУЕТСЯ НАСТРОЙКА СИСТЕМЫ")
        print("=" * 60)
        print(f"\nПричина: {reason}")
        print("\nЗапуск мастера настройки...\n")

        # Запуск мастера настройки
        setup_script = base_path / 'setup_launcher.py'
        if setup_script.exists():
            if getattr(sys, 'frozen', False):
                # В замороженном виде запускаем через exec
                os.execv(sys.executable, [sys.executable, str(setup_script)])
            else:
                os.execv(sys.executable, [sys.executable, str(setup_script)])
        else:
            print(f"[ERROR] Файл мастера настройки не найден: {setup_script}")
            print("Запустите setup_launcher.py вручную")
            sys.exit(1)


# Запускаем проверку перед всем остальным
check_and_run_setup()
# ===================================================================

os.environ['CURL_CA_BUNDLE'] = ''
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
matplotlib.use('Agg')

# ===================================================================
# === УНИВЕРСАЛЬНОЕ ОГРАНИЧЕНИЕ ЯДЕР CPU (для разгрузки) ===
# ===================================================================
# Устанавливаем 4 ядра для всех многопоточных библиотек.
# Это должно быть сделано ДО импорта NumPy, PyTorch, LightGBM и т.д.
# Если переменная уже установлена (например, в .bat), мы ее не перезаписываем.

if 'OMP_NUM_THREADS' not in os.environ:
    os.environ['OMP_NUM_THREADS'] = '1'
if 'MKL_NUM_THREADS' not in os.environ:
    os.environ['MKL_NUM_THREADS'] = '1'
if 'NUMBA_NUM_THREADS' not in os.environ:
    os.environ['NUMBA_NUM_THREADS'] = '1'
if 'TORCH_NUM_THREADS' not in os.environ:
    os.environ['TORCH_NUM_THREADS'] = '1'

# 1. Отключение JIT-компиляции Numba (если она вызывает сбой)
os.environ['NUMBA_DISABLE_JIT'] = '1'

# 2. Патч для MKL/OpenMP (помогает при конфликтах с пулами потоков)
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

# 3. Принудительное отключение CUDA (для устранения конфликтов VRAM/драйверов)
os.environ['CUDA_VISIBLE_DEVICES'] = ''

# Оставляем ТОЛЬКО один, самый надежный способ установить переменную окружения ДО импортов
try:
    project_root = Path(__file__).resolve().parent
    settings_path = project_root / 'configs' / 'settings.json'

    if settings_path.exists():
        with open(settings_path, 'r', encoding='utf-8') as f:
            # Простой парсинг JSON без полных зависимостей Pydantic
            settings_data = json.load(f)

        hf_cache_dir_str = settings_data.get("HF_MODELS_CACHE_DIR")

        if hf_cache_dir_str:
            # Проверяем, что путь не пустой
            try:
                cache_path = Path(hf_cache_dir_str)
                root_disk = cache_path.anchor
                if not Path(root_disk).exists():
                    logger.warning(
                        f"[WARN] Корневой диск '{root_disk}' для кэша HF не найден. Используется стандартный путь.")
                else:
                    cache_path.mkdir(parents=True, exist_ok=True)
                    os.environ['HF_HOME'] = str(cache_path.resolve())
                    # Сообщение будет выведено позже, через систему логирования
            except Exception as e_mkdir:
                logger.error(
                    f"[ERROR] Не удалось создать/использовать директорию для кэша '{hf_cache_dir_str}'. Причина: {e_mkdir}. Используется стандартный путь.")
    else:
        logger.warning(
            "[WARN] Файл settings.json не найден, используется стандартный путь для кэша HF.")
except Exception as e:
    logger.error(
        f"[ERROR] Не удалось прочитать settings.json для настройки HF_HOME: {e}")


os.environ['QT_WEBENGINE_DISABLE_SANDBOX'] = '1'
# os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = '9223'
# os.environ['NUMBA_DISABLE_INTEL_SVML'] = '1'

# Флаг для выбора интерфейса
USE_MODERN_UI = True  # Установите в False для использования старого интерфейса


warnings.filterwarnings("ignore", category=UserWarning,
                        message="X does not have valid feature names, but LGBMRegressor was fitted with feature names")

warnings.filterwarnings("ignore", category=UserWarning,
                        message="X does not have valid feature names, but MinMaxScaler was fitted with feature names")


SRC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')

if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


app_config_for_path = load_config()


logger = logging.getLogger(__name__)


class GraphBackend(QObject):
    graphDataUpdated = Signal(dict)

    # ---  СЛОТ ДЛЯ ПРИЕМА ЗАПРОСА ИЗ JS ---
    @Slot(str, str)
    def requestFilteredGraph(self, filter_type: str, filter_value: str):
        """Принимает запрос на фильтрацию из JS и перенаправляет его в ядро."""
        self.parent().on_filter_request(filter_type, filter_value)

    @Slot()
    def jsReady(self):
        """Вызывается из JS, когда страница полностью загружена."""
        # Получаем доступ к родительскому окну (MainWindow)
        # Важно: parent() должен быть установлен при создании
        if self.parent():
            self.parent().on_js_ready()


def run_backtest_process(results_queue, config_dict: dict, symbol, strategy_name, timeframe, start_date, end_date,
                         test_type: str, model_id: Optional[int]):
    # Настройка логирования внутри процесса
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s - %(levelname)s - [BACKTEST_PROCESS] - %(message)s')

    try:
        # 1. Инициализация конфигурации и подключение к MT5
        config = Settings(**config_dict)
        if not mt5.initialize(path=config.MT5_PATH):
            raise ConnectionError("Не удалось подключиться к MetaTrader 5.")

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        # Инициализация провайдера данных
        dp = DataProvider(config, threading.Lock())

        # 2. Загрузка данных в зависимости от типа теста
        historical_data = {}  # Для Event-Driven
        df = pd.DataFrame()  # Для векторных тестов

        if test_type == "Event-Driven Backtest":
            logging.info("Загрузка данных для Event-Driven симуляции...")
            # Загружаем основной символ
            main_df = dp.get_historical_data(
                symbol, timeframe, start_dt, end_dt)
            if main_df is not None and not main_df.empty:
                historical_data[symbol] = main_df

            # Загружаем дополнительные символы (например, DXY для корреляций)
            if "DXY" in config.INTER_MARKET_SYMBOLS:
                dxy_df = dp.get_historical_data(
                    "DXY", timeframe, start_dt, end_dt)
                if dxy_df is not None and not dxy_df.empty:
                    historical_data["DXY"] = dxy_df

            if symbol not in historical_data:
                raise ValueError(f"Не удалось загрузить данные для {symbol}")

        else:
            # Для остальных типов тестов загружаем только один DataFrame
            logging.info(f"Загрузка данных для {symbol}...")
            df = dp.get_historical_data(symbol, timeframe, start_dt, end_dt)
            if df is None or df.empty:
                raise ValueError(
                    f"Не удалось загрузить исторические данные для {symbol} на ТФ {timeframe}.")

        # Отключаемся от MT5, так как данные уже в памяти
        mt5.shutdown()

        # 3. Инициализация вспомогательных компонентов (DB, KG)
        # Создаем очередь-заглушку, так как в процессе бэктеста запись в БД не требуется
        dummy_queue = queue.Queue()
        from src.db.database_manager import DatabaseManager
        db_manager = DatabaseManager(config, dummy_queue)
        kg_querier = KnowledgeGraphQuerier(db_manager)

        report = {}
        equity = pd.DataFrame()

        # 4. Запуск соответствующего бэктестера
        if test_type == "Event-Driven Backtest":
            logging.info(f"Запуск Event-Driven симуляции для {symbol}...")
            # Импорт здесь, чтобы избежать циклических зависимостей на уровне модуля
            from src.analysis.event_driven_backtester import EventDrivenBacktester

            ed_backtester = EventDrivenBacktester(config, historical_data)
            # Запускаем асинхронный метод синхронно
            report, equity = asyncio.run(ed_backtester.run())

        elif test_type == "Системный бэктест (Экосистема)":
            logging.info(f"Запуск СИСТЕМНОГО бэктеста для '{symbol}'.")
            system_backtester = SystemBacktester(
                historical_data=df, config=config)
            report = system_backtester.run()

        elif test_type == "Классическая стратегия":
            logging.info(
                f"Запуск бэктеста классической стратегии '{strategy_name}' на {symbol}.")
            from src.analysis.backtester import StrategyBacktester
            strategy_loader = StrategyLoader(config)

            strategies = {
                s.__class__.__name__: s for s in strategy_loader.load_strategies()}
            strategy_instance = strategies.get(strategy_name)
            if not strategy_instance:
                raise ValueError(
                    f"Не удалось найти класс стратегии {strategy_name}")

            backtester = StrategyBacktester(
                strategy=strategy_instance, data=df, timeframe=timeframe, config=config)
            report = backtester.run()

        elif test_type == "AI Модель":
            logging.info(f"Запуск бэктеста AI-модели с ID {model_id}.")
            from src.ml.ai_backtester import AIBacktester

            model_components = db_manager.load_model_components_by_id(model_id)
            if not model_components:
                raise ValueError(
                    f"Не удалось загрузить AI-модель с ID {model_id}")

            from src.ml.feature_engineer import FeatureEngineer

            # Передаем kg_querier для генерации графовых признаков
            feature_engineer = FeatureEngineer(config, kg_querier)
            df_featured = feature_engineer.generate_features(df, symbol=symbol)

            risk_config_dict = config.model_dump()

            backtester = AIBacktester(
                data=df_featured,
                model=model_components['model'],
                model_features=model_components['features'],
                x_scaler=model_components['x_scaler'],
                y_scaler=model_components['y_scaler'],
                risk_config=risk_config_dict
            )
            report = backtester.run()

        # 5. Пост-обработка результатов
        # Если бэктестер не вернул кривую эквити (старые векторные тесты), генерируем синтетическую для GUI
        if equity.empty and report.get('total_trades', 0) > 0 and 'net_pnl' in report:
            initial_balance = config.backtester_initial_balance
            total_trades = report['total_trades']
            net_pnl = report['net_pnl']

            # Простая генерация: равномерное распределение PnL + шум
            avg_pnl = net_pnl / total_trades
            std_dev = abs(avg_pnl) * 5 if avg_pnl != 0 else 10

            pnl_series = np.random.normal(
                loc=avg_pnl, scale=std_dev, size=total_trades)
            # Корректируем сумму, чтобы она точно совпадала с net_pnl
            diff = net_pnl - np.sum(pnl_series)
            pnl_series += diff / total_trades

            equity_values = initial_balance + np.cumsum(pnl_series)
            # Добавляем начальную точку
            equity_values = np.insert(equity_values, 0, initial_balance)
            equity = pd.DataFrame({'equity': equity_values})

        # Отправка результатов в GUI
        results_queue.put(
            {'status': 'success', 'report': report, 'equity': equity})

    except Exception as e:
        logging.error(f"Ошибка в процессе бэктестинга: {e}", exc_info=True)
        results_queue.put({'status': 'error', 'report': {
                          "Ошибка": str(e)}, 'equity': pd.DataFrame()})
    finally:
        # На всякий случай, если shutdown не был вызван ранее
        mt5.shutdown()


class DictTableModel(QAbstractTableModel):
    def __init__(self, data: list[dict], headers: list[str], key_map: list[str]):
        super().__init__()
        self._data = data
        self._headers = headers
        self._key_map = key_map

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self._headers)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None


class CustomCandlestickItem(pg.GraphicsObject):
    def __init__(self):
        pg.GraphicsObject.__init__(self)
        self.data = None

    def setData(self, data):
        self.data = data
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def paint(self, p, *args):
        if self.data is None or len(self.data) < 2:
            return

        # Вычисляем ширину свечи адаптивно (фиксированный процент от шага)
        if len(self.data) > 1:
            step = float(self.data[1][0] - self.data[0][0])
            if step <= 0:
                step = 1
            # Используем только 25% от шага, мин 2 пикселя, макс 8 пикселей
            w = max(min(step * 0.25, 8.0), 2.0)
        else:
            w = 2.0

        for t, o, h, l, c in self.data:
            # Определяем цвет свечи
            if c >= o:  # Зеленая свеча (рост)
                pen = pg.mkPen('g', width=1)
                brush = pg.mkBrush('g')
            else:  # Красная свеча (падение)
                pen = pg.mkPen('r', width=1)
                brush = pg.mkBrush('r')

            p.setPen(pen)
            p.setBrush(brush)

            body_top = max(o, c)
            body_bottom = min(o, c)
            body_height = body_top - body_bottom

            # Рисуем верхнюю тень (от high до верха тела)
            p.drawLine(QPointF(t, h), QPointF(t, body_top))
            # Рисуем нижнюю тень (от low до низа тела)
            p.drawLine(QPointF(t, l), QPointF(t, body_bottom))

            # Рисуем тело с ограниченной шириной
            if body_height > 0:
                p.drawRect(QRectF(t - w, body_bottom, w * 2, body_height))
            else:
                # Если open == close, рисуем горизонтальную линию
                p.drawLine(QPointF(t - w, o), QPointF(t + w, o))

    def boundingRect(self):
        if self.data is None or len(self.data) == 0:
            return QRectF()

        # Находим границы данных
        times = [d[0] for d in self.data]
        highs = [d[2] for d in self.data]
        lows = [d[3] for d in self.data]

        min_time = min(times)
        max_time = max(times)
        min_price = min(lows)
        max_price = max(highs)

        # Добавляем небольшой отступ (согласовано с paint методом)
        step = (self.data[1][0] - self.data[0][0]) if len(self.data) > 1 else 1
        w = max(min(step * 0.25, 8.0), 2.0)

        return QRectF(
            min_time - w,
            min_price,
            max_time - min_time + 2 * w,
            max_price - min_price
        )


class Bridge(QObject):
    status_updated = Signal(str, bool)
    balance_updated = Signal(float, float)
    log_message_added = Signal(str, QColor)
    positions_updated = Signal(list)
    history_updated = Signal(list)
    training_history_updated = Signal(object)
    candle_chart_updated = Signal(pd.DataFrame, str)
    pnl_updated = Signal(list)
    market_scan_updated = Signal(list)
    # Отдельный сигнал для торговых сигналов
    trading_signals_updated = Signal(list)
    uptime_updated = Signal(str)
    rd_progress_updated = Signal(dict)
    xai_data_ready = Signal(object, int)
    all_positions_closed = Signal()
    backtest_finished = Signal(dict, pd.DataFrame)
    market_regime_updated = Signal(str)
    update_status_changed = Signal(str, bool)
    initialization_successful = Signal(list)
    initialization_failed = Signal()
    directives_updated = Signal(list)
    times_updated = Signal(str, str)
    model_list_updated = Signal(list)
    orchestrator_allocation_updated = Signal(dict)
    knowledge_graph_updated = Signal(str)
    observer_pnl_updated = Signal(list)
    vector_db_search_results = Signal(list)

    thread_status_updated = Signal(str, str)
    # task_id, message, is_finished
    long_task_status_updated = Signal(str, str, bool)
    heavy_initialization_finished = Signal()
    drift_data_updated = Signal(float, str, float, bool)
    pnl_kpis_updated = Signal(dict)


class PySideTradingSystem(QObject):
    def __init__(self, config: Settings, bridge: Bridge, sound_manager: SoundManager):
        super().__init__()
        self.config = config
        self.bridge = bridge
        self.core_system = TradingSystem(
            config=config, gui=self, sound_manager=sound_manager, bridge=bridge)
        # --- ПРАВИЛЬНЫЕ ПОДКЛЮЧЕНИЯ (core_system -> bridge) ---
        self.core_system.rd_progress_updated.connect(
            self.bridge.rd_progress_updated)
        self.core_system.market_scan_updated.connect(
            self.bridge.market_scan_updated)
        self.core_system.trading_signals_updated.connect(
            self.bridge.trading_signals_updated)
        self.core_system.uptime_updated.connect(self.bridge.uptime_updated)
        self.core_system.all_positions_closed.connect(
            self.bridge.all_positions_closed)
        self.core_system.directives_updated.connect(
            self.bridge.directives_updated)
        self.core_system.orchestrator_allocation_updated.connect(
            self.bridge.orchestrator_allocation_updated)
        self.core_system.knowledge_graph_updated.connect(
            self.bridge.knowledge_graph_updated)

        # --- ДОБАВЛЕННЫЕ ПОДКЛЮЧЕНИЯ (WEB.3 и другие) ---
        self.core_system.thread_status_updated.connect(
            self.bridge.thread_status_updated)
        self.core_system.long_task_status_updated.connect(
            self.bridge.long_task_status_updated)
        self.core_system.drift_data_updated.connect(
            self.bridge.drift_data_updated)
        # --------------------------------------------------------------------

        # Прокси-методы для вызова из MainWindow
        self.initialize_heavy_components = self.core_system.initialize_heavy_components
        self.start_all_background_services = self.core_system.start_all_background_services
        # Оставляем для обратной совместимости
        self.start_all_threads = self.core_system.start_all_threads

    def emergency_close_position(self, ticket: int):
        """
        Проксирует вызов к TradeExecutor для экстренного закрытия одной позиции.
        """
        # Вызываем метод TradeExecutor, который находится внутри core_system
        self.core_system.execution_service.emergency_close_position(ticket)

    def emergency_close_all_positions(self):
        """
        Проксирует вызов к TradeExecutor для экстренного закрытия всех позиций.
        """
        self.core_system.execution_service.emergency_close_all_positions()

    def set_observer_mode(self, enabled: bool):
        """Проксирует вызов к core_system для переключения режима наблюдателя."""
        self.core_system.set_observer_mode(enabled)

    def update_configuration(self, new_config: Settings):
        """Проксирует вызов к ядру системы для обновления конфигурации."""
        self.core_system.update_configuration(new_config)

    def force_training_cycle(self):
        """Проксирует вызов к ядру системы."""
        self.core_system.force_training_cycle()

    def force_rd_cycle(self):
        """Проксирует вызов к ядру системы."""
        self.core_system.force_rd_cycle()

    def stop(self):
        """Проксирует вызов к ядру системы для остановки торговли."""
        self.core_system.initiate_graceful_shutdown()

    def set_trading_mode(self, mode_id: str, settings: Optional[Dict[str, Any]] = None):
        """
        Проксирует вызов к core_system для установки режима торговли.
        
        Args:
            mode_id: Идентификатор режима ("conservative", "standard", "aggressive", "yolo", "custom", "disabled")
            settings: Пользовательские настройки (для кастомного режима)
        """
        self.core_system.set_trading_mode(mode_id, settings)

    def get_all_models(self) -> List[Dict]:
        """Проксирует вызов к db_manager для получения списка моделей."""
        return self.core_system.db_manager.get_all_models_for_gui()

    def get_vector_db_stats(self) -> Dict[str, Any]:
        """Проксирует вызов к core_system для получения статистики VectorDB."""
        return self.core_system.get_vector_db_stats()

    def search_vector_db(self, query_text: str):
        """Проксирует вызов к core_system для поиска в VectorDB."""
        logger.info(
            f"[VectorDB-Proxy] Получен запрос на поиск: '{query_text}'")

        if not self.core_system:
            logger.error("[VectorDB-Proxy] core_system не инициализирован")
            self.bridge.vector_db_search_results.emit(
                [{"error": "Торговая система не запущена"}])
            return

        if not hasattr(self.core_system, 'search_vector_db'):
            logger.error(
                "[VectorDB-Proxy] Метод search_vector_db не найден в core_system")
            self.bridge.vector_db_search_results.emit(
                [{"error": "Метод поиска не найден"}])
            return

        # --- ИСПРАВЛЕНИЕ: Используем QThreadPool для I/O-bound задачи ---
        # Запускаем синхронный метод в отдельном потоке, чтобы не блокировать GUI
        logger.info(f"[VectorDB-Proxy] Запуск Worker для поиска")
        worker = Worker(self.core_system.search_vector_db, query_text)
        # Результат будет отправлен через сигнал core_system.vector_db_search_results
        QThreadPool.globalInstance().start(worker)
        logger.info(f"[VectorDB-Proxy] Worker запущен")

    def connect_to_terminal_adapter(self) -> tuple[bool, str]:
        with self.core_system.mt5_lock:
            logger.info("Попытка подключения к MetaTrader 5 через адаптер...")
            if not mt5.initialize(
                    path=self.config.MT5_PATH,
                    login=int(self.config.MT5_LOGIN),
                    password=self.config.MT5_PASSWORD,
                    server=self.config.MT5_SERVER,
                    timeout=10000
            ):
                error_message = f"initialize() failed, error code = {mt5.last_error()}"
                logger.error(f"Не удалось подключиться к MT5: {error_message}")
                mt5.shutdown()
                return False, error_message

            account_info = mt5.account_info()
            if account_info is None:
                error_message = f"account_info() failed, error code = {mt5.last_error()}"
                logger.error(
                    f"Не удалось получить информацию о счете: {error_message}")
                mt5.shutdown()
                return False, error_message

            logger.info(
                f"Успешное подключение к счету #{account_info.login} на сервере {account_info.server}.")
            return True, "Success"

    def _safe_gui_update(self, method_name: str, *args, **kwargs):
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
                'update_times': (self.bridge.times_updated, args)
            }
            if method_name in signal_map:
                signal, signal_args = signal_map[method_name]
                signal.emit(*signal_args)
        except Exception as e:
            logger.error(
                f"Ошибка при отправке сигнала GUI '{method_name}': {e}")


class GenericTableModel(QAbstractTableModel):
    def __init__(self, data, headers):
        super().__init__()
        self._data = data
        self._headers = headers

    def data(self, index, role):
        # --- Блок для отображения текста в ячейке (остается без изменений) ---
        if role == Qt.DisplayRole:
            if 0 <= index.row() < len(self._data) and 0 <= index.column() < len(self._data[index.row()]):
                return str(self._data[index.row()][index.column()])
            return None

        if role == Qt.ToolTipRole:
            if 0 <= index.row() < len(self._data):
                row_data = self._data[index.row()]
                headers = self._headers

                # Формируем красивую подсказку с использованием HTML
                tooltip_lines = []
                for header, value in zip(headers, row_data):
                    # Убираем переносы строк из заголовков для красивого отображения
                    clean_header = header.replace('\n', ' ')
                    tooltip_lines.append(f"<b>{clean_header}:</b> {value}")

                # Соединяем все строки в одну с помощью HTML-переноса строки
                return "<br>".join(tooltip_lines)

        return None

    def rowCount(self, index):
        return len(self._data)

    def update_data(self, new_data):
        """
        Обновляет данные модели
        :param new_data: новые данные для таблицы
        """
        # ОТЛАДКА: Логируем каждое обновление
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"[GenericTableModel] update_data вызван с {len(new_data)} строками")

        self.layoutAboutToBeChanged.emit()
        self._data = new_data
        self.layoutChanged.emit()

    def columnCount(self, index):
        return len(self._headers)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None


class RDTableModel(GenericTableModel):
    def __init__(self, headers):
        super().__init__([], headers)

    def update_data(self, new_row_dict: dict):
        self.beginInsertRows(self.index(len(self._data), 0),
                             len(self._data), len(self._data))
        row_data = [
            new_row_dict.get('generation', 'N/A'),
            f"{new_row_dict.get('best_fitness', 0.0):.4f}",
            new_row_dict.get('config', new_row_dict.get(
                'strategy_str', 'N/A'))  # Поддержка обоих ключей
        ]
        self._data.append(row_data)
        self.endInsertRows()


class DirectiveDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создать новую директиву")
        layout = QGridLayout(self)

        layout.addWidget(QLabel("Тип директивы:"), 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "BLOCK_TRADING",
            "RISK_OFF_MODE",
            "SET_MAX_WEEKLY_DRAWDOWN"
        ])
        self.type_combo.currentIndexChanged.connect(self.on_type_changed)
        layout.addWidget(self.type_combo, 0, 1)

        self.value_label = QLabel("Значение (%):")
        self.value_spinbox = QDoubleSpinBox()
        self.value_spinbox.setRange(1.0, 20.0)
        self.value_spinbox.setValue(3.0)
        self.value_spinbox.setSingleStep(0.5)
        layout.addWidget(self.value_label, 1, 0)
        layout.addWidget(self.value_spinbox, 1, 1)

        layout.addWidget(QLabel("Причина:"), 2, 0)
        self.reason_edit = QLineEdit("Manual override from GUI")
        layout.addWidget(self.reason_edit, 2, 1)

        layout.addWidget(QLabel("Срок действия (часы):"), 3, 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 720)
        self.duration_spin.setValue(168)
        layout.addWidget(self.duration_spin, 3, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 4, 0, 1, 2)

        self.on_type_changed(0)

    def on_type_changed(self, index):
        directive_type = self.type_combo.currentText()
        is_value_needed = "DRAWDOWN" in directive_type
        self.value_label.setVisible(is_value_needed)
        self.value_spinbox.setVisible(is_value_needed)

    def get_data(self):
        return {
            "type": self.type_combo.currentText(),
            "reason": self.reason_edit.text(),
            "duration_hours": self.duration_spin.value(),
            "value": self.value_spinbox.value()
        }


class GUIBridge(QObject):
    """
    Мост для передачи сигналов из фоновых потоков (TradingSystem) в GUI.
    Определен здесь, чтобы быть доступным при инициализации.
    """
    log_message = Signal(
        object)              # Сообщение лога (строка или dict)
    # Текст статуса, Важность (True=Красный)
    update_status_changed = Signal(str, bool)
    # Данные для таблицы сканера (list of dicts)
    market_data_updated = Signal(object)
    # Данные о позициях (list of dicts)
    positions_updated = Signal(object)
    graph_data_updated = Signal(object)       # Данные для графа (nodes, edges)


class MainWindow(QMainWindow):
    def __init__(self, trading_system_adapter: PySideTradingSystem, config: Settings):
        super().__init__()
        self.setWindowTitle("Genesis v24.0: Reflexive Core")

        logger.info("=== НАЧАЛО ИНИЦИАЛИЗАЦИИ MainWindow ===")

        # 1. Инициализация QThreadPool для управления фоновыми задачами
        self.threadpool = QThreadPool()
        # Ограничиваем количество потоков для I/O-bound задач
        self.threadpool.setMaxThreadCount(10)
        logger.info(
            f"QThreadPool инициализирован с макс. {self.threadpool.maxThreadCount()} потоками.")

        # Инициализация основных объектов
        self.config = config
        self.trading_system = trading_system_adapter
        self.bridge = self.trading_system.bridge
        self.sound_manager = self.trading_system.core_system.sound_manager
        self.chart_trade_history = []
        self.temp_html_file = None

        self.drift_data_points = []
        self.drift_alert_points = []

        # Инициализируем словари
        self.thread_status_labels: Dict[str, QLabel] = {}
        self.scheduler_status_labels: Dict[str, QLabel] = {}

        # Настройка иконки
        project_root = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(project_root, 'assets', 'icon.ico.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logger.warning(f"Файл иконки не найден по пути: {icon_path}")

        # Настройка панели уведомлений
        self.notification_bar = QFrame()
        self.notification_bar.setObjectName("NotificationBar")
        self.notification_bar.setLayout(QHBoxLayout())
        self.notification_label = QLabel("")
        self.notification_bar.layout().addWidget(self.notification_label)
        self.notification_bar.setVisible(False)

        self.notification_timer = QTimer(self)
        self.notification_timer.setSingleShot(True)
        self.notification_timer.timeout.connect(
            lambda: self.notification_bar.setVisible(False))

        # Настройка GUI и сигналов
        self.is_graph_ready = False
        self.graph_data_queue = []
        self.scheduler_manager = SchedulerManager()
        self.settings_window = SettingsWindow(
            self.scheduler_manager, self.config, self)
        self.settings_window.scheduler_status_updated.connect(
            self.update_thread_status_widget)

        self.setGeometry(100, 100, 1600, 900)

        # --- ВРЕМЕННЫЙ ВИДЖЕТ ЗАГРУЗКИ ---
        self.loading_label = QLabel(
            "Загрузка ядра Genesis v24.0... Пожалуйста, подождите (AI, DB, NLP).")
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.addWidget(self.loading_label)
        self.setCentralWidget(self.loading_widget)

        # --- Инициализация GUI (легкая часть) ---
        self._init_widgets()  # Создание всех виджетов, но без данных
        self.connect_signals()
        self.apply_style("Темная")

        # Настройка таймера статуса
        self.status_update_timer = QTimer(self)
        self.status_update_timer.timeout.connect(
            self.update_scheduler_status_display)
        self.status_update_timer.start(60 * 1000)

        self.update_scheduler_status_display()
        # Предполагаем, что kg_enabled_checkbox существует после _init_widgets
        self.kg_enabled_checkbox.setChecked(
            self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION)
        self.on_kg_toggle()

        # --- КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: Запуск тяжелой инициализации в QThreadPool ---
        # Запускаем сразу, не ждем 100мс, но в фоновом потоке
        self.start_heavy_initialization()

        # Показываем уведомление о загрузке
        # self.show_notification("Запуск фоновых сервисов\n(Оркестратор, R&D,\n Data Provider)...", 0)

    def _initialize_and_start_blocking(self):
        """
        Блокирующая функция, которая будет выполняться в Worker.
        Объединяет обе тяжелые фазы.
        """
        # Фаза 1: Тяжелая инициализация компонентов (DB, AI, NLP)
        logger.info("Начало тяжелой инициализации компонентов (DB, AI, NLP)...")

        # !!! КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: УДАЛЯЕМ НИЖНЕЕ ПОДЧЕРКИВАНИЕ !!!
        self.trading_system.core_system.initialize_heavy_components()

        logger.info("Тяжелая инициализация завершена.")

        # Фаза 2: Запуск постоянных фоновых сервисов (Data Provider, Orchestrator, R&D)
        logger.info("Начало запуска всех фоновых сервисов...")
        # Передаем QThreadPool для управления потоками, если это необходимо
        self.trading_system.start_all_background_services(self.threadpool)
        logger.info("Все фоновые сервисы запущены.")
        return True

    @Slot(object)
    def on_heavy_initialization_finished(self, result):
        """
        Слот, вызываемый после успешного запуска всех фоновых сервисов.
        Безопасно выполняется в главном потоке GUI.
        """
        logger.info(
            "Система Genesis v24.0 полностью активна. Переключение на основной GUI.")

        # 1. Инициализация основного GUI (теперь это безопасно)
        self._init_widgets()
        self.connect_signals()
        self.apply_style("Темная")

        # 2. Замена временного виджета на основной GUI
        self.setCentralWidget(self.main_central_widget)

        # 3. Запуск таймеров и начальных обновлений
        self.status_update_timer = QTimer(self)
        self.status_update_timer.timeout.connect(
            self.update_scheduler_status_display)
        self.status_update_timer.start(60 * 1000)
        self.update_scheduler_status_display()
        self.kg_enabled_checkbox.setChecked(
            self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION)
        self.on_kg_toggle()

        if hasattr(self, 'control_center_tab'):
            self.control_center_tab.load_initial_settings()

        self.show_notification(
            "Система Genesis v24.0 полностью активна.", 5000)

    @Slot(tuple)
    def on_heavy_initialization_error(self, error_info):
        """
        Слот для обработки ошибок инициализации.
        """
        exctype, value, traceback_str = error_info
        logger.critical(
            f"Критическая ошибка при запуске сервисов: {value}\n{traceback_str}")
        # Показать бессрочно
        self.show_notification(f"КРИТИЧЕСКАЯ ОШИБКА: {value}", 0)
        self.loading_label.setText(f"КРИТИЧЕСКАЯ ОШИБКА: {value}. См. логи.")
        self.loading_label.setStyleSheet("color: red;")

    def show_notification(self, message: str, duration_ms: int = 3000):
        """
        Отображает уведомление в нижней панели.
        duration_ms = 0 означает бессрочно.
        """
        self.notification_label.setText(message)
        self.notification_bar.setVisible(True)
        if duration_ms > 0:
            self.notification_timer.start(duration_ms)
        else:
            self.notification_timer.stop()

    def _create_vector_db_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # --- Верхняя панель: Статистика и Управление ---
        top_frame = QFrame()
        top_frame.setFrameShape(QFrame.StyledPanel)
        top_layout = QHBoxLayout(top_frame)

        # Статистика
        stats_layout = QVBoxLayout()
        self.vdb_count_label = QLabel("Документов в индексе: --")
        self.vdb_count_label.setStyleSheet(
            "font-size: 12pt; font-weight: bold; color: #50fa7b;")
        self.vdb_status_label = QLabel("Статус: Инициализация...")
        stats_layout.addWidget(self.vdb_count_label)
        stats_layout.addWidget(self.vdb_status_label)

        # Кнопки
        btn_layout = QVBoxLayout()
        self.vdb_refresh_btn = QPushButton("Обновить статистику")
        self.vdb_refresh_btn.clicked.connect(self._refresh_vector_db_stats)
        btn_layout.addWidget(self.vdb_refresh_btn)

        top_layout.addLayout(stats_layout)
        top_layout.addStretch()
        top_layout.addLayout(btn_layout)
        layout.addWidget(top_frame)

        # --- Панель Поиска ---
        search_group = QGroupBox("Семантический Поиск (RAG)")
        search_layout = QVBoxLayout(search_group)

        input_layout = QHBoxLayout()
        self.vdb_query_edit = QLineEdit()
        self.vdb_query_edit.setPlaceholderText(
            "Введите запрос (напр. 'Inflation impact on Gold' или 'Rate hike')...")
        self.vdb_query_edit.returnPressed.connect(self._run_vector_db_search)

        self.vdb_search_button = QPushButton("Найти похожие новости")
        self.vdb_search_button.clicked.connect(self._run_vector_db_search)
        self.vdb_search_button.setStyleSheet(
            "background-color: #bd93f9; color: #282a36; font-weight: bold;")

        input_layout.addWidget(self.vdb_query_edit)
        input_layout.addWidget(self.vdb_search_button)
        search_layout.addLayout(input_layout)
        layout.addWidget(search_group)

        # --- Таблица Результатов ---
        self.vdb_results_table = QTableWidget()
        self.vdb_results_table.setColumnCount(4)
        self.vdb_results_table.setHorizontalHeaderLabels(
            ["Сходство", "Источник", "Дата", "Фрагмент текста"])
        self.vdb_results_table.horizontalHeader().setSectionResizeMode(3,
                                                                       QHeaderView.Stretch)
        self.vdb_results_table.horizontalHeader().setSectionResizeMode(0,
                                                                       QHeaderView.ResizeToContents)
        self.vdb_results_table.setAlternatingRowColors(True)
        self.vdb_results_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.vdb_results_table)

        # Подключение сигналов
        self.bridge.vector_db_search_results.connect(
            self._display_vector_db_results)

        # Авто-обновление статистики через 2 секунды после старта
        QTimer.singleShot(2000, self._refresh_vector_db_stats)

        return widget

    def _refresh_vector_db_stats(self):
        """Запрашивает статистику у ядра."""
        logger.info("[VectorDB-GUI] Запрос статистики VectorDB")
        if hasattr(self.trading_system, 'get_vector_db_stats'):
            stats = self.trading_system.get_vector_db_stats()
            count = stats.get('count', 0)
            ready = stats.get('is_ready', False)

            logger.info(
                f"[VectorDB-GUI] Статистика получена: готов={ready}, документов={count}")

            self.vdb_count_label.setText(f"Документов в индексе: {count}")

            status_text = "АКТИВНА" if ready else "НЕ ГОТОВА"
            color = "#50fa7b" if ready else "#ff5555"
            self.vdb_status_label.setText(f"Статус: {status_text}")
            self.vdb_status_label.setStyleSheet(
                f"color: {color}; font-weight: bold;")

    def _on_vector_db_search(self):
        query = self.vdb_search_input.text().strip()
        if not query:
            return

        self.vdb_search_btn.setEnabled(False)
        self.vdb_search_btn.setText("Поиск...")
        self.vdb_table.setRowCount(0)

        # Запускаем поиск в отдельном потоке через TradingSystem
        threading.Thread(target=self.trading_system.core_system.search_vector_db, args=(
            query,), daemon=True).start()

    # --- СЛОТ ДЛЯ ОБНОВЛЕНИЯ ТАБЛИЦЫ РЕЗУЛЬТАТОВ ---
    @Slot(list)
    def update_vector_db_table(self, results: list):
        self.vdb_search_btn.setEnabled(True)
        self.vdb_search_btn.setText("Найти в Базе Знаний")

        if not results:
            QMessageBox.information(self, "Поиск", "Ничего не найдено.")
            return

        if "error" in results[0]:
            QMessageBox.warning(self, "Ошибка", results[0]["error"])
            return

        self.vdb_table.setRowCount(len(results))
        for i, item in enumerate(results):
            # Сходство (Distance)
            dist_item = QTableWidgetItem(
                f"{float(item.get('distance', 0)):.4f}")
            dist_item.setTextAlignment(Qt.AlignCenter)

            # Источник
            source_item = QTableWidgetItem(str(item.get('source', 'N/A')))

            # Дата
            date_str = item.get('timestamp', 'N/A')
            if 'T' in date_str:
                date_str = date_str.split('T')[0]
            date_item = QTableWidgetItem(date_str)

            # Текст
            text_item = QTableWidgetItem(str(item.get('snippet', '')))
            # Полный текст в подсказке
            text_item.setToolTip(str(item.get('full_text', '')))

            self.vdb_table.setItem(i, 0, dist_item)
            self.vdb_table.setItem(i, 1, source_item)
            self.vdb_table.setItem(i, 2, date_item)
            self.vdb_table.setItem(i, 3, text_item)

    def _run_vector_db_search(self):
        query = self.vdb_query_edit.text().strip()
        if not query:
            QMessageBox.warning(self, "Внимание", "Введите поисковый запрос.")
            # Убедимся, что кнопка в нормальном состоянии
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")
            return

        logger.info(f"[VectorDB-GUI] Запуск поиска: '{query}'")

        # Проверяем, что система инициализирована
        if not hasattr(self.trading_system, 'search_vector_db'):
            logger.error(
                "[VectorDB-GUI] Метод search_vector_db не найден в trading_system")
            QMessageBox.critical(
                self, "Ошибка", "Система VectorDB не инициализирована")
            return

        if not hasattr(self.trading_system, 'core_system'):
            logger.error(
                "[VectorDB-GUI] core_system не найден в trading_system")
            QMessageBox.critical(
                self, "Ошибка", "Торговая система не запущена. Нажмите 'Запустить торговлю'")
            return

        self.vdb_search_button.setEnabled(False)
        self.vdb_search_button.setText("Поиск...")
        self.vdb_results_table.setRowCount(0)

        # --- ИСПРАВЛЕНИЕ: Вызываем прокси-метод, который использует QThreadPool ---
        try:
            logger.info(
                f"[VectorDB-GUI] Вызов trading_system.search_vector_db('{query}')")
            self.trading_system.search_vector_db(query)
            logger.info(
                f"[VectorDB-GUI] Метод search_vector_db вызван успешно")
        except Exception as e:
            logger.error(
                f"[VectorDB-GUI] Ошибка при вызове search_vector_db: {e}", exc_info=True)
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")
            QMessageBox.critical(
                self, "Ошибка", f"Ошибка при запуске поиска: {e}")
            return

        # Таймаут на случай, если результаты не придут (защита от зависания кнопки)
        # 10 секунд таймаут
        QTimer.singleShot(10000, self._restore_search_button)

    def _restore_search_button(self):
        """Восстанавливает кнопку поиска (защита от зависания)"""
        if not self.vdb_search_button.isEnabled():
            logger.warning(
                "[VectorDB-GUI] Таймаут поиска - восстановление кнопки")
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")

    @Slot(list)
    def _display_vector_db_results(self, results: list):
        """Отображает результаты поиска в VectorDB"""
        try:
            logger.info(
                f"[VectorDB-GUI] ===== _display_vector_db_results ВЫЗВАН с {len(results) if results else 0} результатами =====")

            # Всегда восстанавливаем кнопку в начале
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")
            logger.info(f"[VectorDB-GUI] Кнопка восстановлена")

            if not results:
                logger.warning("[VectorDB-GUI] Результаты пустые")
                QMessageBox.information(
                    self, "Результат", "Результаты не получены.")
                return

            if "error" in results[0]:
                logger.error(
                    f"[VectorDB-GUI] Получена ошибка: {results[0]['error']}")
                QMessageBox.critical(
                    self, "Ошибка поиска", results[0]["error"])
                return

            if "message" in results[0]:
                logger.info(
                    f"[VectorDB-GUI] Получено сообщение: {results[0]['message']}")
                QMessageBox.information(
                    self, "Результат", results[0]["message"])
                return

            logger.info(
                f"[VectorDB-GUI] Заполнение таблицы {len(results)} результатами")
            self.vdb_results_table.setRowCount(len(results))
            for i, res in enumerate(results):
                # Логируем первый результат для отладки
                if i == 0:
                    logger.info(f"[VectorDB-GUI] Пример результата: {res}")

                # Сходство (чем меньше дистанция, тем лучше, для L2)
                # Для отображения можно инвертировать или просто показать дистанцию
                dist_val = float(res.get('distance', 0))
                similarity_str = f"{dist_val:.4f}"

                self.vdb_results_table.setItem(
                    i, 0, QTableWidgetItem(similarity_str))
                self.vdb_results_table.setItem(
                    i, 1, QTableWidgetItem(res.get('source', 'N/A')))

                ts = res.get('timestamp', 'N/A')
                if 'T' in ts:
                    ts = ts.split('T')[0]
                self.vdb_results_table.setItem(i, 2, QTableWidgetItem(ts))

                snippet = res.get('snippet', 'Нет текста')
                item_text = QTableWidgetItem(snippet)
                # Полный текст в подсказке
                item_text.setToolTip(res.get('full_text', snippet))
                self.vdb_results_table.setItem(i, 3, item_text)

            logger.info(f"[VectorDB-GUI] Таблица успешно заполнена")

        except Exception as e:
            logger.error(
                f"[VectorDB-GUI] Ошибка при отображении результатов: {e}", exc_info=True)
            # Убедимся, что кнопка восстановлена даже при ошибке
            self.vdb_search_button.setEnabled(True)
            self.vdb_search_button.setText("Найти похожие новости")
            QMessageBox.critical(
                self, "Ошибка", f"Ошибка при отображении результатов: {e}")

    def update_scheduler_status_display(self):
        """Обновляет информацию о запланированных и выполненных задачах в GUI."""
        try:
            project_root = Path(os.path.dirname(os.path.abspath(__file__)))

            # --- Обработка для Обслуживания ---
            maint_label = self.scheduler_status_labels.get('Maintenance')
            if maint_label:
                maint_time_str = self.scheduler_manager.get_task_trigger_time(
                    "GenesisMaintenance")
                maint_status_file = project_root / "database" / "maintenance_status.json"

                last_run_str = ""
                if maint_status_file.exists():
                    try:
                        with open(maint_status_file, 'r') as f:
                            data = json.load(f)
                            last_run_utc = datetime.fromisoformat(
                                data["last_run_utc"])
                            last_run_local = last_run_utc.astimezone()
                            last_run_str = f" (Выполнено: {last_run_local.strftime('%d.%m %H:%M')})"
                    except Exception as e:
                        logger.error(
                            f"Ошибка чтения файла статуса обслуживания: {e}")

                display_text = f"Ежедневно в {maint_time_str}" if maint_time_str else "Не настроено"
                maint_label.setText(display_text + last_run_str)
                maint_label.setStyleSheet(
                    "color: #8be9fd;" if maint_time_str else "color: #f1fa8c;")

            # --- Обработка для Оптимизации ---
            opt_label = self.scheduler_status_labels.get('Optimization')
            if opt_label:
                opt_time_str = self.scheduler_manager.get_task_trigger_time(
                    "GenesisWeeklyOptimization")
                opt_status_file = project_root / "database" / "optimization_status.json"

                last_run_str = ""
                if opt_status_file.exists():
                    try:
                        with open(opt_status_file, 'r') as f:
                            data = json.load(f)
                            last_run_utc = datetime.fromisoformat(
                                data["last_run_utc"])
                            last_run_local = last_run_utc.astimezone()
                            last_run_str = f" (Выполнено: {last_run_local.strftime('%d.%m %H:%M')})"
                    except Exception as e:
                        logger.error(
                            f"Ошибка чтения файла статуса оптимизации: {e}")

                display_text = f"Еженедельно (Сб) в {opt_time_str}" if opt_time_str else "Не настроено"
                opt_label.setText(display_text + last_run_str)
                opt_label.setStyleSheet(
                    "color: #8be9fd;" if opt_time_str else "color: #f1fa8c;")

        except Exception as e:
            logger.error(
                f"Критическая ошибка в update_scheduler_status_display: {e}", exc_info=True)

    def update_thread_status_widget(self, scheduler_summary: dict):
        """
        Слот для приема и отображения статуса планировщика.
        """
        # Пример: Обновление QLabel или QTableWidget рядом со статусом потоков

        status_text = "Планировщик:\n"
        for task_name, status in scheduler_summary.items():
            # Убираем префикс "Genesis" для краткости
            display_name = task_name.replace("Genesis", "")
            status_text += f"  {display_name}: {status}\n"

    def _handle_long_task_status(self, task_id: str, message: str, is_finished: bool):
        """Показывает или обновляет панель уведомлений."""
        self.notification_timer.stop()  # Останавливаем таймер, если он был запущен
        self.notification_label.setText(message)

        if is_finished:
            # Задача завершена - зеленый цвет и запуск таймера на скрытие
            self.notification_bar.setStyleSheet(
                "background-color: #50fa7b; color: #282a36; border-radius: 4px;")
            self.notification_timer.start(7000)  # Скрыть через 7 секунд
        else:
            # Задача в процессе - желтый цвет
            self.notification_bar.setStyleSheet(
                "background-color: #f1fa8c; color: #282a36; border-radius: 4px;")

        self.notification_bar.setVisible(True)

    def _hide_notification_bar(self):
        """Скрывает панель уведомлений."""
        self.notification_bar.setVisible(False)

    def start_heavy_initialization(self):
        """Запускает загрузку тяжелых AI-компонентов в фоновом потоке."""
        self.update_status(
            "Загрузка AI-моделей (может занять несколько минут)...", is_error=False)
        # Блокируем кнопку запуска на время загрузки
        self.start_button.setEnabled(False)

        def worker():
            self.trading_system.core_system.initialize_heavy_components()
            # После завершения отправляем сигнал обратно в GUI
            self.bridge.status_updated.emit(
                "AI-модели загружены. Система готова к запуску.", False)
            # Разблокируем кнопку (нужно делать через сигнал, чтобы быть потокобезопасным)
            self.bridge.heavy_initialization_finished.emit()
            # Разблокируем кнопку после загрузки AI
            self.start_button.setEnabled(True)

        # Запускаем воркера в отдельном потоке, чтобы не блокировать GUI
        init_thread = threading.Thread(target=worker, daemon=True)
        init_thread.start()

    def on_settings_saved(self):
        """
        Слот, который вызывается после сохранения настроек в дочернем окне.
        Перезагружает конфигурацию и передает ее в ядро системы.
        """
        logger.info(
            "Обнаружено сохранение настроек. Применение изменений на лету...")
        try:
            new_config = load_config()
            self.trading_system.update_configuration(new_config)
            self.update_status("Настройки успешно применены.", is_error=False)
            self.update_scheduler_status_display()
        except Exception as e:
            logger.error(f"Ошибка при применении новых настроек: {e}")
            self.update_status(
                "Ошибка при применении настроек. См. логи.", is_error=True)

    def update_thread_status(self, thread_name: str, status: str):
        """Обновляет текст и цвет метки статуса потока."""
        if thread_name in self.thread_status_labels:
            label = self.thread_status_labels[thread_name]
            status_colors = {
                "RUNNING": ("#50fa7b", "РАБОТАЕТ"),
                "STOPPING": ("#f1fa8c", "ОСТАНОВКА..."),
                "STOPPED": ("#ff5555", "ОСТАНОВЛЕН")
            }
            color, text = status_colors.get(
                status.upper(), ("#f8f8f2", status))
            label.setText(text)
            label.setStyleSheet(f"font-weight: bold; color: {color};")
            QApplication.processEvents()  # Принудительное обновление GUI

    def _create_thread_status_panel(self) -> QGroupBox:
        """Создает панель для отображения статуса фоновых потоков и задач."""
        group_box = QGroupBox("Статус Системы")
        layout = QGridLayout(group_box)
        layout.setColumnStretch(1, 1)

        # Словарь для живых потоков
        thread_names = {
            "Trading": "Торговый:", "Monitoring": "Мониторинг:",
            "Training": "R&D:", "Orchestrator": "Оркестратор:",
            "VectorDB Cleanup": "VectorDB Cleanup:"  # <-- ИСПРАВЛЕНИЕ F2
        }

        row = 0
        for key, name in thread_names.items():
            layout.addWidget(QLabel(name), row, 0, Qt.AlignRight)
            status_label = QLabel("STOPPED")
            status_label.setStyleSheet("font-weight: bold; color: #ff5555;")
            # Объединяем 2 и 3 колонки
            layout.addWidget(status_label, row, 1, 1, 2)
            self.thread_status_labels[key] = status_label
            row += 1

        # Разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator, row, 0, 1, 3)
        row += 1

        # --- НАЧАЛО ИЗМЕНЕНИЙ ---
        # Метка для обслуживания
        layout.addWidget(QLabel("Обслуживание:"), row, 0, Qt.AlignRight)
        maint_label = QLabel("...")  # Временный текст
        maint_label.setStyleSheet("color: #f1fa8c;")
        layout.addWidget(maint_label, row, 1, 1, 2)
        self.scheduler_status_labels['Maintenance'] = maint_label
        row += 1

        # Метка для оптимизации
        layout.addWidget(QLabel("Оптимизация:"), row, 0, Qt.AlignRight)
        opt_label = QLabel("...")  # Временный текст
        opt_label.setStyleSheet("color: #f1fa8c;")
        layout.addWidget(opt_label, row, 1, 1, 2)
        self.scheduler_status_labels['Optimization'] = opt_label

        return group_box

    def apply_style(self, style_name: str):
        if style_name == "Светлая":
            self.setStyleSheet(LIGHT_STYLE)
            pg.setConfigOption('background', 'w')
            pg.setConfigOption('foreground', 'k')
        elif style_name == "Темная":
            self.setStyleSheet(DARK_STYLE)
            pg.setConfigOption('background', '#282a36')
            pg.setConfigOption('foreground', '#f8f8f2')
        logger.info(f"Применен стиль: {style_name}")

    def _init_widgets(self):
        central_widget = QWidget()
        self.main_central_widget = central_widget
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 1. Создаем текстовую метку (QLabel)
        title_label = QLabel()

        # 2. Устанавливаем текст с HTML-тегом для золотого цвета
        title_label.setText(
            '<font color="#FFD700">Genesis--Piligrim Evolution v10.0: The Reflexive Core</font>')

        # 3. Настраиваем внешний вид: выравнивание по центру, крупный жирный шрифт
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "font-size: 14pt; font-weight: bold; padding: 5px;")

        # 4. Добавляем метку в самый верх нашего окна
        main_layout.addWidget(title_label)

        top_panel = self._create_top_panel()
        main_layout.addWidget(top_panel)
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)
        left_panel = self._create_left_panel()
        right_panel = self._create_right_panel()
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([650, 950])
        self.status_label = QLabel("Система не запущена.")
        self.statusBar().addWidget(self.status_label)

    def _create_top_panel(self):
        top_widget = QFrame()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # --- НОВЫЙ KPI BAR ---
        kpi_bar = self._create_kpi_bar()

        control_box = QFrame()
        control_layout = QHBoxLayout(control_box)
        self.start_button = QPushButton("Запуск Системы")
        self.stop_button = QPushButton("Остановка")
        self.stop_button.setEnabled(False)

        self.settings_button = QPushButton("Настройки")

        self.restart_system_button = QPushButton("Перезапустить Систему")
        self.restart_system_button.setStyleSheet(
            "background-color: #ffb86c; color: #000;")

        self.observer_checkbox = QCheckBox("Режим Наблюдателя")
        self.observer_checkbox.setChecked(True)

        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)

        control_layout.addWidget(self.settings_button)
        control_layout.addWidget(self.restart_system_button)
        control_layout.addWidget(self.observer_checkbox)

        update_box = QFrame()
        update_layout = QVBoxLayout(update_box)
        self.update_button = QPushButton("Обновить и Перезапустить")
        self.update_button.setEnabled(False)
        self.update_status_label = QLabel("Статус обновления: N/A")
        update_layout.addWidget(self.update_button)
        update_layout.addWidget(self.update_status_label)

        thread_status_box = self._create_thread_status_panel()
        # Для стилизации, если понадобится
        thread_status_box.setObjectName("ThreadStatusBox")

        account_box = QFrame()

        account_layout = QVBoxLayout(account_box)
        self.balance_label = QLabel("Баланс: N/A")
        self.equity_label = QLabel("Эквити: N/A")
        self.uptime_label = QLabel("Время работы: -")
        self.uptime_label.setStyleSheet("font-weight: bold; color: #50fa7b;")
        self.pc_time_label = QLabel("PC Время: --:--:--")
        self.server_time_label = QLabel("Время сервера: --:--:--")

        account_layout.addWidget(self.balance_label)
        account_layout.addWidget(self.equity_label)
        account_layout.addWidget(self.uptime_label)
        account_layout.addWidget(self.pc_time_label)
        account_layout.addWidget(self.server_time_label)

        top_layout.addWidget(control_box)
        top_layout.addWidget(update_box)
        top_layout.addWidget(thread_status_box)
        top_layout.addWidget(self.notification_bar)
        top_layout.addWidget(kpi_bar)

        top_layout.addStretch()
        top_layout.addWidget(account_box)

        return top_widget

    def _create_kpi_bar(self) -> QGroupBox:
        """Создает виджет для отображения ключевых метрик PnL за период."""
        group_box = QGroupBox("PnL по Периодам")
        layout = QGridLayout(group_box)

        # Метки для PnL
        self.pnl_day_label = QLabel("День: N/A")
        self.pnl_week_label = QLabel("Неделя: N/A")
        self.pnl_month_label = QLabel("Месяц: N/A")

        # Метки для Drawdown (Убыток)
        self.dd_day_label = QLabel("DD День: N/A")
        self.dd_week_label = QLabel("DD Неделя: N/A")
        self.dd_month_label = QLabel("DD Месяц: N/A")

        # --- ДОБАВЛЕНИЕ ВСПЛЫВАЮЩИХ ПОДСКАЗОК (TOOLTIPS) ---

        # Подсказки для Прибыли
        self.pnl_day_label.setToolTip(
            "Чистая прибыль/убыток (PnL) по закрытым сделкам с начала текущего дня (00:00 UTC).")
        self.pnl_week_label.setToolTip(
            "Чистая прибыль/убыток (PnL) по закрытым сделкам с начала текущей недели (Понедельник 00:00 UTC).")
        self.pnl_month_label.setToolTip(
            "Чистая прибыль/убыток (PnL) по закрытым сделкам с начала текущего месяца (1-е число 00:00 UTC).")

        # Подсказки для Максимальной Просадки (Drawdown)
        self.dd_day_label.setToolTip(
            "Максимальная просадка (Max Drawdown) по закрытым сделкам с начала текущего дня.")
        self.dd_week_label.setToolTip(
            "Максимальная просадка (Max Drawdown) по закрытым сделкам с начала текущей недели.")
        self.dd_month_label.setToolTip(
            "Максимальная просадка (Max Drawdown) по закрытым сделкам с начала текущего месяца.")

        # ----------------------------------------------------

        # Стилизация (для наглядности)
        self.pnl_day_label.setStyleSheet("font-weight: bold; color: #50fa7b;")
        self.dd_day_label.setStyleSheet("font-weight: bold; color: #ff5555;")

        # Размещение в сетке
        layout.addWidget(QLabel("Прибыль:"), 0, 0)
        layout.addWidget(self.pnl_day_label, 0, 1)
        layout.addWidget(self.pnl_week_label, 0, 2)
        layout.addWidget(self.pnl_month_label, 0, 3)

        # Изменим метку для ясности
        layout.addWidget(QLabel("Max DD (%):"), 1, 0)
        layout.addWidget(self.dd_day_label, 1, 1)
        layout.addWidget(self.dd_week_label, 1, 2)
        layout.addWidget(self.dd_month_label, 1, 3)

        return group_box

    @Slot(dict)
    def update_pnl_kpis(self, kpis: dict):
        """Обновляет метки PnL и Drawdown."""

        def format_pnl(value):
            # Зеленый для прибыли, красный для убытка
            color = "#50fa7b" if value >= 0 else "#ff5555"
            return f"<span style='font-weight: bold; color:{color}'>{value:+.2f}</span>"

        def format_dd(value):
            # Красный для просадки
            color = "#ff5555"
            return f"<span style='font-weight: bold; color:{color}'>{value:.2f}%</span>"

        self.pnl_day_label.setText(format_pnl(kpis.get('day_pnl', 0)))
        self.pnl_week_label.setText(format_pnl(kpis.get('week_pnl', 0)))
        self.pnl_month_label.setText(format_pnl(kpis.get('month_pnl', 0)))

        self.dd_day_label.setText(format_dd(kpis.get('day_dd', 0)))
        self.dd_week_label.setText(format_dd(kpis.get('week_dd', 0)))
        self.dd_month_label.setText(format_dd(kpis.get('month_dd', 0)))

    def _create_left_panel(self):
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        tab_widget = QTabWidget()

        # Добавляем обработчик переключения вкладок левой панели
        tab_widget.currentChanged.connect(
            lambda idx: self.on_left_tab_changed(idx, tab_widget))
        logger.info("[GUI-Init] Инициализация левой панели")

        # --- ВКЛАДКА "ОТКРЫТЫЕ ПОЗИЦИИ" (без изменений) ---
        positions_tab_widget = QWidget()
        positions_tab_layout = QVBoxLayout(positions_tab_widget)
        positions_control_layout = QHBoxLayout()
        positions_control_layout.addWidget(QLabel("<b>Открытые Позиции</b>"))
        positions_control_layout.addStretch()
        self.close_all_pos_button = QPushButton("Закрыть все")
        self.close_all_pos_button.setStyleSheet("background-color: #8B0000;")
        positions_control_layout.addWidget(self.close_all_pos_button)
        self.close_pos_button = QPushButton("Закрыть выбранную")
        positions_control_layout.addWidget(self.close_pos_button)

        self.positions_table = QTableView()
        self.positions_headers = ["Тикет", "Сим\nвол", "Стра\nтегия", "Тип", "Объем", "Цена\nоткр.", "При\nбыль",
                                  "Баров\nв сделке", "ТФ"]
        self.positions_model = GenericTableModel([], self.positions_headers)
        self.positions_table.setModel(self.positions_model)
        header_pos = self.positions_table.horizontalHeader()
        header_pos.setSectionResizeMode(QHeaderView.ResizeToContents)
        header_pos.setSectionResizeMode(1, QHeaderView.Stretch)
        header_pos.setSectionResizeMode(2, QHeaderView.Stretch)
        positions_tab_layout.addLayout(positions_control_layout)
        positions_tab_layout.addWidget(self.positions_table)
        tab_widget.addTab(positions_tab_widget, "Открытые Позиции")

        # --- ВКЛАДКА "ИСТОРИЯ СДЕЛОК" (с исправлениями) ---
        self.history_table = QTableView()

        # +++ НАЧАЛО ИЗМЕНЕНИЙ: Устанавливаем ПРАВИЛЬНЫЙ порядок заголовков +++
        self.history_headers = ["Тикет", "Сим\nвол", "Стра\nтегия", "Тип", "Объем", "Цена\nзакр.", "Время\nзакр.", "При\nбыль",
                                "ТФ"]
        # +++ КОНЕЦ ИЗМЕНЕНИЙ +++

        self.history_model = GenericTableModel([], self.history_headers)
        self.history_table.setModel(self.history_model)

        header_hist = self.history_table.horizontalHeader()
        header_hist.setSectionResizeMode(QHeaderView.ResizeToContents)
        header_hist.setSectionResizeMode(6, QHeaderView.Stretch)  # Время закр.
        header_hist.setSectionResizeMode(7, QHeaderView.Stretch)  # Стратегия

        tab_widget.addTab(self.history_table, "История Сделок")

        # --- ОБЩИЙ ЛЕЙАУТ ---
        left_layout.addWidget(tab_widget)
        log_box = QFrame()
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(QLabel("Логи Системы"))
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        log_layout.addWidget(self.log_text_edit)
        left_layout.addWidget(log_box)

        return left_widget

    def _on_backtest_type_changed(self):
        test_type = self.bt_test_type_combo.currentText()
        self.bt_strategy_combo.clear()  # Очистка списка
        self.bt_strategy_combo.setEnabled(True)

        if test_type == "Event-Driven Backtest":
            self.bt_strategy_combo.addItem("N/A (Вся система)")
            self.bt_strategy_combo.setEnabled(False)

        elif test_type == "Системный бэктест (Экосистема)":
            self.bt_strategy_combo.addItem("N/A (система решает сама)")
            self.bt_strategy_combo.setEnabled(False)

        elif test_type == "Классическая стратегия":
            # Загружаем стратегии заново
            strategy_loader = StrategyLoader(self.trading_system.config)
            strategies = strategy_loader.load_strategies()

            if not strategies:
                self.bt_strategy_combo.addItem("Стратегии не найдены")
            else:
                for s in strategies:
                    # Добавляем имя класса стратегии
                    self.bt_strategy_combo.addItem(s.__class__.__name__)

        elif test_type == "AI Модель":
            all_models = self.trading_system.get_all_models()
            pytorch_models = [
                m for m in all_models if "PyTorch" in m.get('type', '')]
            if not pytorch_models:
                self.bt_strategy_combo.addItem(
                    "Нет совместимых PyTorch моделей")
                self.bt_strategy_combo.setEnabled(False)
            else:
                for model in pytorch_models:
                    status = model.get('status', 'N/A')
                    item_text = f"ID: {model.get('id')} - {model.get('symbol')} - {model.get('type')} ({status})"
                    self.bt_strategy_combo.addItem(item_text)

    def on_kg_toggle(self):
        is_checked = self.kg_enabled_checkbox.isChecked()

        # Обновляем конфиг в ядре
        if hasattr(self, 'trading_system'):
            self.trading_system.core_system.toggle_knowledge_graph(is_checked)

        # Безопасное переключение видимости
        # Проверяем, созданы ли уже виджеты
        if hasattr(self, 'knowledge_graph_view') and hasattr(self, 'kg_disabled_label'):
            self.knowledge_graph_view.setVisible(is_checked)
            self.kg_disabled_label.setVisible(not is_checked)
        else:
            # Если метод вызван до полной инициализации UI
            pass

    def _create_right_panel(self, vector_db_tab=None):
        right_widget = QTabWidget()

        # --- ВКЛАДКА "ОСНОВНОЙ ГРАФИК" ---
        self.chart_layout_widget = pg.GraphicsLayoutWidget()
        right_widget.addTab(self.chart_layout_widget, "Основной График")
        self.price_plot = self.chart_layout_widget.addPlot(row=0, col=0)

        # Используем форматирование дат на нижней оси
        self.price_plot.setAxisItems({'bottom': pg.DateAxisItem()})

        grid_pen = pg.mkPen(color='#888', style=Qt.DotLine)
        self.price_plot.showGrid(x=True, y=True, alpha=0.3)
        self.price_plot.getAxis('bottom').setPen(grid_pen)
        self.price_plot.getAxis('left').setPen(grid_pen)
        self.price_plot.getAxis('left').setWidth(60)
        self.price_plot.disableAutoRange()

        self.regime_region = pg.LinearRegionItem(values=[0, 1], orientation='vertical', movable=False,
                                                 brush=QColor(0, 0, 0, 0))
        self.regime_region.setZValue(-100)
        self.price_plot.addItem(self.regime_region)
        self.regime_colors = {
            "Strong Trend": QColor(0, 255, 0, 30), "Weak Trend": QColor(0, 255, 0, 15),
            "High Volatility Range": QColor(255, 255, 0, 30), "Low Volatility Range": QColor(0, 0, 255, 20),
        }

        self.chart_layout_widget.nextRow()
        self.volume_plot = self.chart_layout_widget.addPlot(row=1, col=0)
        self.volume_plot.setMaximumHeight(150)
        self.volume_plot.showGrid(x=True, y=True, alpha=0.3)
        self.volume_plot.getAxis('bottom').setPen(grid_pen)
        self.volume_plot.getAxis('left').setPen(grid_pen)
        self.volume_plot.getAxis('left').setWidth(60)
        self.volume_plot.setXLink(self.price_plot)

        self.candlestick_item = CustomCandlestickItem()
        self.price_plot.addItem(self.candlestick_item)
        self.volume_item = BarGraphItem(
            x=[], height=[], width=0.8, brush='#50fa7b')
        self.ema50_item = pg.PlotDataItem(pen=pg.mkPen('c', width=2))
        self.ema200_item = pg.PlotDataItem(pen=pg.mkPen('y', width=2))
        self.trade_arrows_item = pg.ScatterPlotItem()
        self.price_plot.addItem(self.ema50_item)
        self.price_plot.addItem(self.ema200_item)
        self.price_plot.addItem(self.trade_arrows_item)
        self.volume_plot.addItem(self.volume_item)

        vLine = pg.InfiniteLine(angle=90, movable=False,
                                pen=pg.mkPen('gray', style=Qt.DashLine))
        hLine = pg.InfiniteLine(angle=0, movable=False,
                                pen=pg.mkPen('gray', style=Qt.DashLine))
        self.price_plot.addItem(vLine, ignoreBounds=True)
        self.price_plot.addItem(hLine, ignoreBounds=True)
        self.crosshair_label = pg.TextItem(anchor=(0, 1))
        self.price_plot.addItem(self.crosshair_label)

        def mouse_moved(evt):
            pos = evt[0]
            if self.price_plot.sceneBoundingRect().contains(pos):
                mouse_point = self.price_plot.vb.mapSceneToView(pos)
                if np.isnan(mouse_point.x()):
                    return
                timestamp = int(mouse_point.x())
                price = mouse_point.y()
                if timestamp < 0 or timestamp > 32503680000:
                    return
                vLine.setPos(timestamp)
                hLine.setPos(price)
                try:
                    time_str = datetime.fromtimestamp(
                        timestamp).strftime('%Y-%m-%d %H:%M')
                    self.crosshair_label.setText(f"{time_str}, {price:.5f}")
                    view_range = self.price_plot.vb.viewRange()
                    self.crosshair_label.setPos(
                        view_range[0][0], view_range[1][1])
                except (OSError, ValueError) as e:
                    logger.debug(
                        f"Ошибка при обновлении позиции crosshair: {e}")
        self.proxy = pg.SignalProxy(self.price_plot.scene(
        ).sigMouseMoved, rateLimit=60, slot=mouse_moved)

        # --- ВКЛАДКА "ЦЕНТР УПРАВЛЕНИЯ" ---
        self.control_center_tab = ControlCenterWidget(
            bridge=self.bridge,
            config=self.config,
            trading_system_adapter=self.trading_system
        )
        right_widget.addTab(self.control_center_tab, "Центр Управления")

        # --- ВКЛАДКА "АНАЛИТИКА" ---
        analytics_tab_widget = QWidget()
        analytics_layout = QVBoxLayout(analytics_tab_widget)
        analytics_controls_layout = QHBoxLayout()
        analytics_controls_layout.addStretch()
        analytics_graph_widget = pg.GraphicsLayoutWidget()
        self.loss_plot = analytics_graph_widget.addPlot(
            row=0, col=0, title="Прогресс обучения (Loss)")
        # График P&L для реальных сделок (существующий)
        self.pnl_plot = analytics_graph_widget.addPlot(
            row=1, col=0, title="Кривая доходности (P&L)")

        self.loss_plot.showGrid(x=True, y=True, alpha=0.3)
        self.loss_plot.getAxis('bottom').setLabel('Эпоха обучения')
        self.loss_plot.getAxis('left').setLabel('Значение ошибки (Loss)')
        self.loss_curve = self.loss_plot.plot(
            pen='y', symbol='o', symbolBrush='y', symbolSize=5)
        self.pnl_plot = analytics_graph_widget.addPlot(
            row=1, col=0, title="Кривая доходности (P&L)")
        self.pnl_plot.showGrid(x=True, y=True, alpha=0.3)
        self.pnl_plot.getAxis('left').setLabel('Баланс', units='USD')
        self.pnl_plot.setAxisItems({'bottom': pg.DateAxisItem()})
        self.pnl_curve = self.pnl_plot.plot(pen='g')

        # +++  Новый график для режима наблюдателя +++
        analytics_graph_widget.nextRow()  # Переходим на новую строку в layout
        self.observer_pnl_plot = analytics_graph_widget.addPlot(
            row=2, col=0, title="Доходность (Режим Наблюдателя)")
        self.observer_pnl_plot.showGrid(x=True, y=True, alpha=0.3)
        self.observer_pnl_plot.getAxis('left').setLabel(
            'Баланс (симуляция)', units='USD')
        self.observer_pnl_plot.getAxis('bottom').setLabel(
            'Количество виртуальных сделок')
        self.observer_pnl_curve = self.observer_pnl_plot.plot(
            pen=pg.mkPen('c', width=2))  # Голубой цвет для графика
        analytics_layout.addLayout(analytics_controls_layout)
        # --- ВКЛАДКА "АНАЛИТИКА" ---
        analytics_tab_widget = QWidget()
        # Используем QVBoxLayout для всей вкладки
        analytics_layout = QVBoxLayout(analytics_tab_widget)

        analytics_controls_layout = QHBoxLayout()
        self.force_train_button = QPushButton("Запустить цикл обучения сейчас")

        analytics_controls_layout.addWidget(self.force_train_button)
        analytics_controls_layout.addStretch()
        analytics_layout.addLayout(analytics_controls_layout)

        # +++ НАЧАЛО ГЛАВНОГО ИСПРАВЛЕНИЯ +++

        # 1. Создаем ОТДЕЛЬНЫЙ виджет для графика обучения
        self.loss_plot_widget = pg.PlotWidget(title="Прогресс обучения (Loss)")
        self.loss_plot = self.loss_plot_widget.getPlotItem()  # Получаем сам объект графика
        self.loss_plot.showGrid(x=True, y=True, alpha=0.3)
        self.loss_plot.getAxis('bottom').setLabel('Эпоха обучения')
        self.loss_plot.getAxis('left').setLabel('Значение ошибки (Loss)')
        self.loss_curve = self.loss_plot.plot(
            pen='y', symbol='o', symbolBrush='y', symbolSize=5)

        # 2. Создаем ОТДЕЛЬНЫЙ виджет для графика P&L
        self.pnl_plot_widget = pg.PlotWidget(title="Кривая доходности (P&L)")
        self.pnl_plot = self.pnl_plot_widget.getPlotItem()
        self.pnl_plot.showGrid(x=True, y=True, alpha=0.3)
        self.pnl_plot.getAxis('left').setLabel('Баланс', units='USD')
        self.pnl_plot.setAxisItems({'bottom': pg.DateAxisItem()})
        self.pnl_curve = self.pnl_plot.plot(pen='g')

        # 3. Создаем ОТДЕЛЬНЫЙ виджет для графика режима наблюдателя
        self.observer_pnl_plot_widget = pg.PlotWidget(
            title="Доходность (Режим Наблюдателя)")
        self.observer_pnl_plot = self.observer_pnl_plot_widget.getPlotItem()
        self.observer_pnl_plot.showGrid(x=True, y=True, alpha=0.3)
        self.observer_pnl_plot.getAxis('left').setLabel(
            'Баланс (симуляция)', units='USD')
        self.observer_pnl_plot.getAxis('bottom').setLabel(
            'Количество виртуальных сделок')
        self.observer_pnl_curve = self.observer_pnl_plot.plot(
            pen=pg.mkPen('c', width=2))

        #  Ошибка предсказаний (Drift) +++
        self.drift_plot_widget = pg.PlotWidget(
            title="Ошибка предсказаний AI (Concept Drift)")
        self.drift_plot = self.drift_plot_widget.getPlotItem()
        self.drift_plot.showGrid(x=True, y=True, alpha=0.3)
        self.drift_plot.getAxis('bottom').setLabel('Время')
        self.drift_plot.getAxis('left').setLabel('Ошибка (APE)')
        self.drift_plot.setAxisItems({'bottom': pg.DateAxisItem()})

        # Scatter plot для нормальных точек (зеленые круги)
        self.drift_scatter = pg.ScatterPlotItem(size=8, pen=pg.mkPen(
            None), brush=pg.mkBrush('#50fa7b'), symbol='o')
        self.drift_plot.addItem(self.drift_scatter)

        # Отдельный Scatter для точек, где обнаружен дрейф (красные крестики)
        self.drift_alert_scatter = pg.ScatterPlotItem(size=12, pen=pg.mkPen('w', width=2), brush=pg.mkBrush('#ff5555'),
                                                      symbol='x')
        self.drift_plot.addItem(self.drift_alert_scatter)

        # Хранилище данных для графика
        self.drift_data_points = []
        self.drift_alert_points = []

        # 4. Добавляем все три виджета в вертикальный компоновщик
        analytics_layout.addWidget(self.loss_plot_widget)
        analytics_layout.addWidget(self.pnl_plot_widget)
        analytics_layout.addWidget(self.observer_pnl_plot_widget)
        analytics_layout.addWidget(self.drift_plot_widget)
        right_widget.addTab(analytics_tab_widget, "Аналитика")

        # --- ВКЛАДКА "СКАНЕР РЫНКА" ---
        scanner_widget = QWidget()
        scanner_layout = QVBoxLayout(scanner_widget)
        self.scanner_table = QTableView()
        self.scanner_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scanner_table.customContextMenuRequested.connect(
            self.show_scanner_context_menu)

        # Улучшенная настройка таблицы
        self.scanner_table.setAlternatingRowColors(True)
        self.scanner_table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows)
        self.scanner_table.setSelectionMode(
            QTableView.SelectionMode.SingleSelection)
        self.scanner_table.verticalHeader().setVisible(False)

        scanner_layout.addWidget(self.scanner_table)

        self.scanner_headers = ["Ранг", "Символ", "Итоговая Оценка",
                                "Оценка Вол.", "Норм. ATR (%)", "Тренд", "Ликвидность", "Спред (пипсы)"]

        self.scanner_model = GenericTableModel([], self.scanner_headers)
        self.scanner_table.setModel(self.scanner_model)

        # ИСПРАВЛЕНИЕ: Используем ResizeToContents вместо Stretch для лучшей читаемости
        header = self.scanner_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        right_widget.addTab(scanner_widget, "Сканер Рынка")

        # --- ВКЛАДКА "ПАНЕЛЬ ОРКЕСТРАТОРА" ---
        orchestrator_tab = QWidget()
        orchestrator_layout = QVBoxLayout(orchestrator_tab)
        orchestrator_layout.addWidget(
            QLabel("<b>Распределение капитала Оркестратором (в реальном времени)</b>"))
        self.orchestrator_chart_widget = pg.PlotWidget()
        self.orchestrator_chart_widget.showGrid(x=True, y=True, alpha=0.3)
        self.orchestrator_bar_item = pg.BarGraphItem(
            x=[], height=[], width=0.6, brush='g')
        self.orchestrator_chart_widget.addItem(self.orchestrator_bar_item)
        self.orchestrator_chart_widget.getAxis(
            'left').setLabel('Доля капитала', units='%')
        self.orchestrator_chart_widget.getAxis('bottom').setTicks([[]])
        orchestrator_layout.addWidget(self.orchestrator_chart_widget)
        right_widget.addTab(orchestrator_tab, "Панель Оркестратора")

        # --- ВКЛАДКА "R&D ЦЕНТР" ---
        rd_tab_widget = QWidget()
        rd_layout = QVBoxLayout(rd_tab_widget)
        rd_controls_layout = QHBoxLayout()
        self.force_rd_button = QPushButton("Запустить R&D цикл сейчас")
        rd_controls_layout.addWidget(self.force_rd_button)
        rd_controls_layout.addStretch()
        self.rd_table = QTableView()
        self.rd_headers = ["Поколение",
                           "Лучший Fitness", "Конфигурация стратегии"]
        self.rd_model = RDTableModel(self.rd_headers)
        self.rd_table.setModel(self.rd_model)
        self.rd_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rd_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        rd_layout.addLayout(rd_controls_layout)
        rd_layout.addWidget(self.rd_table)
        right_widget.addTab(rd_tab_widget, "R&D Центр")

        # --- ВКЛАДКА "ЦЕНТР РЕФЛЕКСИИ" ---
        reflexion_tab_widget = QWidget()
        reflexion_layout = QVBoxLayout(reflexion_tab_widget)
        reflexion_controls_layout = QHBoxLayout()
        self.create_directive_button = QPushButton("Создать Директиву")
        self.delete_directive_button = QPushButton("Удалить Директиву")
        self.delete_directive_button.setStyleSheet(
            "background-color: #ff5555;")
        reflexion_controls_layout.addWidget(self.create_directive_button)
        reflexion_controls_layout.addStretch()
        reflexion_controls_layout.addWidget(self.delete_directive_button)
        self.directives_table = QTableView()
        self.directives_headers = ["Директива",
                                   "Значение", "Причина", "Действует до"]
        self.directives_model = GenericTableModel([], self.directives_headers)
        self.directives_table.setModel(self.directives_model)
        self.directives_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.directives_table.horizontalHeader().setSectionResizeMode(2,
                                                                      QHeaderView.ResizeToContents)
        reflexion_layout.addWidget(QLabel("<b>Активные Директивы Системы</b>"))
        reflexion_layout.addLayout(reflexion_controls_layout)
        reflexion_layout.addWidget(self.directives_table)
        right_widget.addTab(reflexion_tab_widget, "Центр Рефлексии")

        # --- ВКЛАДКА "МЕНЕДЖЕР МОДЕЛЕЙ" ---
        model_manager_tab = QWidget()
        model_manager_layout = QVBoxLayout(model_manager_tab)
        mm_controls_layout = QHBoxLayout()
        self.refresh_models_button = QPushButton("Обновить список")
        self.demote_model_button = QPushButton("Разжаловать чемпиона")
        self.demote_model_button.setStyleSheet("background-color: #8B0000;")
        mm_controls_layout.addWidget(self.refresh_models_button)
        mm_controls_layout.addStretch()
        mm_controls_layout.addWidget(self.demote_model_button)
        self.models_table = QTableView()
        self.models_headers = ["ID", "Символ", "Тип", "Версия",
                               "Статус", "Sharpe", "Profit Factor", "Дата обучения"]
        self.models_model = GenericTableModel([], self.models_headers)
        self.models_table.setModel(self.models_model)
        self.models_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.models_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        model_manager_layout.addLayout(mm_controls_layout)
        model_manager_layout.addWidget(self.models_table)
        right_widget.addTab(model_manager_tab, "Менеджер Моделей")

        # --- ВКЛАДКА "ГРАФ ЗНАНИЙ" ---
        knowledge_graph_tab = QWidget()
        kg_layout = QVBoxLayout(knowledge_graph_tab)

        # 1. Панель управления (Чекбокс)
        kg_controls_layout = QHBoxLayout()
        self.kg_enabled_checkbox = QCheckBox(
            "Включить/Отключить визуализацию графа")
        self.kg_enabled_checkbox.setToolTip(
            "Включает/отключает ресурсоемкую отрисовку графа знаний в реальном времени.")
        # Устанавливаем значение из конфига
        self.kg_enabled_checkbox.setChecked(
            self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION)

        kg_controls_layout.addWidget(self.kg_enabled_checkbox)
        kg_controls_layout.addStretch()
        kg_layout.addLayout(kg_controls_layout)

        kg_layout.addWidget(
            QLabel("<b>Интерактивная карта причинно-следственных связей</b>"))

        # 2. Создаем WebEngineView (Сам граф)
        self.knowledge_graph_view = QWebEngineView()
        # Делаем фон прозрачным для красоты
        self.knowledge_graph_view.page().setBackgroundColor(Qt.transparent)

        # 3. Создаем метку-заглушку
        self.kg_disabled_label = QLabel(
            "Визуализация графа знаний отключена.\nАнализ связей в фоне продолжается.")
        self.kg_disabled_label.setAlignment(Qt.AlignCenter)
        self.kg_disabled_label.setStyleSheet(
            "font-size: 14px; color: gray; padding: 20px; border: 2px dashed #444;")

        # 4. Добавляем виджеты в layout
        kg_layout.addWidget(self.knowledge_graph_view)
        kg_layout.addWidget(self.kg_disabled_label)

        # 5. НАСТРОЙКА МОСТА С JS (КРИТИЧЕСКИ ВАЖНАЯ ЧАСТЬ)

        # Создаем объект бэкенда
        self.graph_backend = GraphBackend(self)

        # !!! ВАЖНО: Создаем канал с родителем (self), чтобы сборщик мусора не удалил его !!!
        self.channel = QWebChannel(self)

        # Регистрируем объект под именем "backend" (как в HTML)
        self.channel.registerObject("backend", self.graph_backend)

        # Устанавливаем канал на страницу
        self.knowledge_graph_view.page().setWebChannel(self.channel)

        # 6. Загрузка HTML файла
        project_root = os.path.dirname(os.path.abspath(__file__))
        graph_html_path = os.path.join(
            project_root, 'assets', 'graph_view.html')

        if os.path.exists(graph_html_path):
            # Используем QTimer для небольшой задержки, чтобы движок успел инициализироваться
            QTimer.singleShot(100, lambda: self.knowledge_graph_view.setUrl(
                QUrl.fromLocalFile(graph_html_path)))
        else:
            logger.error(
                f"Не найден файл для визуализации графа: {graph_html_path}")
            self.knowledge_graph_view.setHtml(
                f"<h3 style='color:red'>Файл не найден: {graph_html_path}</h3>")

        right_widget.addTab(knowledge_graph_tab, "Граф Знаний")

        # --- ВКЛАДКА "ВЕКТОРНАЯ БД (RAG)" ---
        vector_db_tab = self._create_vector_db_tab()
        right_widget.addTab(vector_db_tab, "Векторная БД (RAG)")

        # --- ВКЛАДКА "АНАЛИЗ СДЕЛКИ (XAI)" ---
        xai_tab_widget = QWidget()
        xai_layout = QVBoxLayout(xai_tab_widget)
        self.xai_label = QLabel(
            "Кликните на сделку в 'Истории Сделок' для анализа")
        self.xai_label.setAlignment(Qt.AlignCenter)
        self.xai_web_view = QWebEngineView()
        self.xai_web_view.setHtml(
            "<html><body style='background-color:#282a36;'><h3 style='color:#f8f8f2; text-align:center;'>Ожидание данных...</h3></body></html>")
        feedback_panel = QFrame()
        feedback_layout = QHBoxLayout(feedback_panel)
        feedback_panel.setLayout(feedback_layout)
        self.good_trade_button = QPushButton("👍 Хорошее решение")
        self.good_trade_button.setStyleSheet(
            "background-color: #50fa7b; color: #000;")
        self.good_trade_button.setEnabled(False)
        self.bad_trade_button = QPushButton("👎 Плохое решение")
        self.bad_trade_button.setStyleSheet("background-color: #ff5555;")
        self.bad_trade_button.setEnabled(False)
        feedback_layout.addStretch()
        feedback_layout.addWidget(self.good_trade_button)
        feedback_layout.addWidget(self.bad_trade_button)
        feedback_layout.addStretch()
        xai_layout.addWidget(self.xai_label)
        xai_layout.addWidget(self.xai_web_view)
        xai_layout.addWidget(feedback_panel)
        right_widget.addTab(xai_tab_widget, "Анализ Сделки (XAI)")

        # --- ВКЛАДКА "БЭКТЕСТЕР" ---
        backtester_tab = QWidget()
        backtester_layout = QVBoxLayout(backtester_tab)
        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)
        self.bt_symbol_combo = QComboBox()
        self.bt_test_type_combo = QComboBox()

        self.bt_test_type_combo.addItems(
            ["Event-Driven Backtest", "Системный бэктест (Экосистема)", "Классическая стратегия", "AI Модель"])

        self.bt_strategy_combo = QComboBox()
        self.bt_timeframe_combo = QComboBox()
        self.timeframe_map = {
            "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1
        }
        self.bt_timeframe_combo.addItems(self.timeframe_map.keys())
        self.bt_timeframe_combo.setCurrentText("H1")
        strategy_loader = StrategyLoader(self.trading_system.config)
        strategies = strategy_loader.load_strategies()
        for s in strategies:
            if "Strategy" in s.__class__.__name__:
                self.bt_strategy_combo.addItem(s.__class__.__name__)
        self.bt_start_date = QDateEdit(QDate.currentDate().addMonths(-3))
        self.bt_start_date.setCalendarPopup(True)
        self.bt_end_date = QDateEdit(QDate.currentDate())
        self.bt_end_date.setCalendarPopup(True)
        self.bt_run_button = QPushButton("Запустить Бэктест")
        controls_layout.addWidget(QLabel("Символ:"))
        controls_layout.addWidget(self.bt_symbol_combo)
        controls_layout.addWidget(QLabel("Тип теста:"))
        controls_layout.addWidget(self.bt_test_type_combo)
        controls_layout.addWidget(QLabel("Стратегия/Модель:"))
        controls_layout.addWidget(self.bt_strategy_combo)
        controls_layout.addWidget(QLabel("ТФ:"))
        controls_layout.addWidget(self.bt_timeframe_combo)
        controls_layout.addWidget(QLabel("С:"))
        controls_layout.addWidget(self.bt_start_date)
        controls_layout.addWidget(QLabel("По:"))
        controls_layout.addWidget(self.bt_end_date)
        controls_layout.addStretch()
        controls_layout.addWidget(self.bt_run_button)
        results_splitter = QSplitter(Qt.Vertical)
        self.bt_report_text = QTextEdit(
            "Здесь будет отчет по результатам бэктеста...")
        self.bt_report_text.setReadOnly(True)
        self.bt_equity_chart_widget = pg.GraphicsLayoutWidget()
        self.bt_equity_plot = self.bt_equity_chart_widget.addPlot(
            title="Кривая доходности (Equity)")
        self.bt_equity_curve = self.bt_equity_plot.plot(pen='g')
        results_splitter.addWidget(self.bt_report_text)
        results_splitter.addWidget(self.bt_equity_chart_widget)
        results_splitter.setSizes([200, 400])
        backtester_layout.addWidget(controls_frame)
        backtester_layout.addWidget(results_splitter)
        right_widget.addTab(backtester_tab, "Бэктестер")

        # Добавляем обработчик переключения вкладок для логирования
        right_widget.currentChanged.connect(self.on_tab_changed)
        logger.info("[GUI-Init] Все вкладки правой панели инициализированы")

        return right_widget

    def on_tab_changed(self, index):
        """Обработчик переключения вкладок правой панели (минимальное логирование)"""
        tab_widget = self.sender()
        tab_name = tab_widget.tabText(index)
        logger.debug(
            f"[GUI-Tab-Right] Переключение на вкладку: '{tab_name}' (индекс {index})")

        # Проверяем, что вкладка корректно отображается
        try:
            current_widget = tab_widget.widget(index)
            if current_widget:
                logger.debug(
                    f"[GUI-Tab-Right] Виджет вкладки '{tab_name}' загружен: {type(current_widget).__name__}")
            # убрали warning для часто меняющихся вкладок
        except Exception as e:
            logger.error(
                f"[GUI-Tab-Right] Ошибка при переключении на вкладку '{tab_name}': {e}", exc_info=True)

    def on_left_tab_changed(self, index, tab_widget):
        """Обработчик переключения вкладок левой панели (минимальное логирование)"""
        tab_name = tab_widget.tabText(index)
        logger.debug(
            f"[GUI-Tab-Left] Переключение на вкладку: '{tab_name}' (индекс {index})")

        try:
            current_widget = tab_widget.widget(index)
            if current_widget:
                logger.debug(
                    f"[GUI-Tab-Left] Виджет вкладки '{tab_name}' загружен: {type(current_widget).__name__}")
                # убрали информирование row_count, слишком шумно при частых переключениях
        except Exception as e:
            logger.error(
                f"[GUI-Tab-Left] Ошибка при переключении на вкладку '{tab_name}': {e}", exc_info=True)

    def connect_signals(self):
        self.start_button.clicked.connect(self.start_trading)
        self.stop_button.clicked.connect(self.stop_trading)
        self.settings_button.clicked.connect(self.open_settings_window)
        self.bridge.drift_data_updated.connect(self.update_drift_chart)

        # Подключаем правильный обработчик для чекбокса
        self.observer_checkbox.clicked.connect(
            self.on_observer_checkbox_clicked)

        self.update_button.clicked.connect(self.apply_update)
        self.bridge.update_status_changed.connect(self.update_update_status)
        self.bridge.status_updated.connect(self.update_status)
        self.bridge.balance_updated.connect(self.update_balance)
        self.bridge.log_message_added.connect(
            self.add_log_message, Qt.QueuedConnection)
        self.bridge.positions_updated.connect(self.update_positions_table)
        self.bridge.history_updated.connect(self.update_history_table)
        self.bridge.training_history_updated.connect(
            self.update_training_chart)
        self.bridge.candle_chart_updated.connect(self.update_candle_chart)
        self.bridge.pnl_updated.connect(self.update_pnl_chart)
        self.bridge.market_scan_updated.connect(
            self.update_market_scanner_view)
        logger.info(
            "[GUI] Сигнал market_scan_updated подключен к update_market_scanner_view")
        self.bridge.uptime_updated.connect(self.update_uptime)
        self.bridge.rd_progress_updated.connect(self.update_rd_view)
        self.history_table.clicked.connect(self.on_history_trade_clicked)
        self.bridge.xai_data_ready.connect(self.display_xai_chart)
        self.close_pos_button.clicked.connect(self.close_selected_position)
        self.close_all_pos_button.clicked.connect(self.close_all_positions)
        self.bridge.all_positions_closed.connect(self.on_all_positions_closed)
        self.force_train_button.clicked.connect(self.force_training)
        self.force_rd_button.clicked.connect(self.force_rd)
        self.bridge.market_regime_updated.connect(
            self.update_market_regime_viz)
        self.bt_run_button.clicked.connect(self.run_backtest)
        self.bt_test_type_combo.currentIndexChanged.connect(
            self._on_backtest_type_changed)
        self.bridge.backtest_finished.connect(self.display_backtest_results)

        #  Указываем правильный метод on_initialization_successful +++
        self.bridge.initialization_failed.connect(
            self.on_initialization_failed)
        self.bridge.initialization_successful.connect(
            self.on_initialization_successful)

        self.bridge.directives_updated.connect(self.update_directives_table)
        self.bridge.times_updated.connect(self.update_times)
        self.create_directive_button.clicked.connect(
            self.open_create_directive_dialog)
        self.delete_directive_button.clicked.connect(
            self._delete_selected_directive)
        self.restart_system_button.clicked.connect(self._prompt_and_restart)
        self.refresh_models_button.clicked.connect(self.refresh_model_list)
        self.demote_model_button.clicked.connect(self.demote_selected_model)
        self.bridge.model_list_updated.connect(self.update_models_table)
        self.good_trade_button.clicked.connect(lambda: self.record_feedback(1))
        self.bad_trade_button.clicked.connect(lambda: self.record_feedback(-1))
        self.bridge.orchestrator_allocation_updated.connect(
            self.update_orchestrator_panel)
        self.bridge.knowledge_graph_updated.connect(
            self.update_knowledge_graph)
        self.bridge.observer_pnl_updated.connect(
            self.update_observer_pnl_chart)
        self.bridge.thread_status_updated.connect(self.update_thread_status)
        self.control_center_tab.settings_changed.connect(
            self.on_runtime_settings_changed)
        self.kg_enabled_checkbox.stateChanged.connect(self.on_kg_toggle)
        self.bridge.orchestrator_allocation_updated.connect(
            self.update_orchestrator_panel)
        self.bridge.heavy_initialization_finished.connect(
            self.on_heavy_initialization_finished)

        self.bridge.pnl_kpis_updated.connect(self.update_pnl_kpis)

        # ИСПРАВЛЕНИЕ: Удалена дублирующая связь market_scan_updated -> control_center_tab.update_market_table
        # Эта связь уже установлена в control_center_widget.py:47 через _connect_signals()
        # Дублирование вызывало конфликты и исчезновение данных из таблицы сканера

        # Подключаем торговые сигналы к отдельному методу в ControlCenterWidget
        if hasattr(self.bridge, 'trading_signals_updated'):
            self.bridge.trading_signals_updated.connect(
                self.control_center_tab.update_trading_signals_table)

    @Slot()
    def on_observer_checkbox_clicked(self):
        """
        Обрабатывает клик по чекбоксу "Режим Наблюдателя" с явной установкой состояния.
        """
        # Получаем желаемое состояние (галочка стоит = True, нет = False)
        desired_state = self.observer_checkbox.isChecked()

        # Если пользователь пытается ВЫКЛЮЧИТЬ режим (снять галочку)
        if not desired_state:
            reply = QMessageBox.question(self, 'Подтверждение',
                                         "Вы уверены, что хотите отключить Режим Наблюдателя и перейти в рабочий режим?\n"
                                         "Система сможет открывать реальные сделки.",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply == QMessageBox.Yes:
                # Пользователь подтвердил -> Выключаем
                self.trading_system.set_observer_mode(False)
            else:
                # Пользователь отменил -> Возвращаем галочку обратно (Включено)
                self.observer_checkbox.setChecked(True)
        else:
            # Пользователь ставит галочку -> Включаем без вопросов
            self.trading_system.set_observer_mode(True)

    def _delete_selected_directive(self):
        selected_indexes = self.directives_table.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.warning(
                self, "Внимание", "Не выбрана ни одна директива для удаления.")
            return

        directive_type_item = self.directives_model.index(
            selected_indexes[0].row(), 0)
        directive_type = self.directives_model.data(
            directive_type_item, Qt.DisplayRole)

        reply = QMessageBox.question(self, 'Подтверждение',
                                     f"Вы уверены, что хотите удалить директиву '{directive_type}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            logger.info(
                f"GUI: Отправка команды на удаление директивы '{directive_type}'.")
            self.trading_system.core_system.delete_directive(directive_type)

    def _prompt_and_restart(self):
        reply = QMessageBox.question(self, 'Подтверждение перезапуска',
                                     "Вы уверены, что хотите перезапустить систему? Все текущие операции будут остановлены.",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.update_status("Перезапуск системы...", is_error=False)

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setText("Перезапуск системы...")
            msg.setInformativeText(
                "Пожалуйста, подождите. Приложение будет перезапущено.")
            msg.setStandardButtons(QMessageBox.NoButton)
            msg.show()

            QApplication.processEvents()

            self.trading_system.core_system.restart_system()

    def update_times(self, pc_time_str: str, server_time_str: str):
        # Убрано избыточное логирование (каждые несколько секунд)
        self.pc_time_label.setText(f"PC Время: {pc_time_str}")
        self.server_time_label.setText(f"Время сервера: {server_time_str}")

    def update_directives_table(self, directives: list):
        logger.info(
            f"[GUI-Directives] Обновление таблицы директив: {len(directives)} директив")
        try:
            table_data = []
            for d in directives:
                table_data.append([
                    d.get('type', 'N/A'),
                    d.get('value', 'N/A'),
                    d.get('reason', 'N/A'),
                    d.get('expires_at', 'N/A')
                ])
            self.directives_model = GenericTableModel(
                table_data, self.directives_headers)
            self.directives_table.setModel(self.directives_model)
            logger.debug(
                f"[GUI-Directives] Таблица директив успешно обновлена")
        except Exception as e:
            logger.error(
                f"[GUI-Directives] Ошибка при обновлении таблицы директив: {e}", exc_info=True)

    def open_create_directive_dialog(self):
        logger.info("[GUI-Dialog] Открытие диалога создания директивы")
        dialog = DirectiveDialog(self)
        try:
            if dialog.exec():
                data = dialog.get_data()
                logger.info(
                    f"[GUI-Dialog] Создание директивы: тип={data['type']}, значение={data.get('value', 'N/A')}")
                self.trading_system.add_directive(
                    directive_type=data['type'],
                    reason=data['reason'],
                    duration_hours=data['duration_hours'],
                    value=data['value']
                )
            else:
                logger.info(
                    "[GUI-Dialog] Диалог создания директивы закрыт без сохранения")
        except Exception as e:
            logger.error(
                f"[GUI-Dialog] Ошибка при создании директивы: {e}", exc_info=True)

    def show_scanner_context_menu(self, position):
        index = self.scanner_table.indexAt(position)
        if not index.isValid():
            return
        symbol = self.scanner_model.data(
            index.siblingAtColumn(1), Qt.DisplayRole)
        if not symbol:
            return
        menu = QMenu()
        blacklist_action = QAction(
            f"Добавить '{symbol}' в черный список (временно)", self)
        blacklist_action.triggered.connect(
            lambda: self.add_symbol_to_blacklist(symbol))
        menu.addAction(blacklist_action)
        menu.exec(self.scanner_table.viewport().mapToGlobal(position))

    def add_symbol_to_blacklist(self, symbol: str):
        reply = QMessageBox.question(self, 'Подтверждение',
                                     f"Вы уверены, что хотите временно исключить '{symbol}' из торговли до следующего перезапуска?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            logger.warning(f"GUI: Символ '{symbol}' добавлен в черный список.")
            self.trading_system.add_to_blacklist(symbol)
            self.update_status(
                f"Символ {symbol} временно исключен из торговли.", False)

    def refresh_model_list(self):
        logger.info("Запрос на обновление списка моделей из GUI...")
        threading.Thread(target=self._fetch_and_update_models,
                         daemon=True).start()

    def _fetch_and_update_models(self):
        models = self.trading_system.get_all_models()
        self.bridge.model_list_updated.emit(models)

    def update_models_table(self, models: list):
        logger.info(
            f"[GUI-Models] Обновление таблицы моделей: {len(models)} моделей")
        try:
            table_data = []
            for model in models:
                table_data.append([
                    model.get('id'), model.get('symbol'), model.get('type'),
                    model.get('version'), model.get(
                        'status'), model.get('sharpe'),
                    model.get('profit_factor'), model.get('date')
                ])
            self.models_model = GenericTableModel(
                table_data, self.models_headers)
            self.models_table.setModel(self.models_model)
            logger.debug(
                f"[GUI-Models] Таблица моделей успешно обновлена, загружено {len(models)} моделей")
        except Exception as e:
            logger.error(
                f"[GUI-Models] Ошибка при обновлении таблицы моделей: {e}", exc_info=True)

    def demote_selected_model(self):
        selected_indexes = self.models_table.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.warning(
                self, "Внимание", "Не выбрана ни одна модель для разжалования.")
            return
        model_id_item = self.models_model.index(selected_indexes[0].row(), 0)
        model_id = int(self.models_model.data(model_id_item, Qt.DisplayRole))
        status_item = self.models_model.index(selected_indexes[0].row(), 4)
        status = self.models_model.data(status_item, Qt.DisplayRole)
        if status != "Чемпион":
            QMessageBox.information(
                self, "Информация", "Выбранная модель не является чемпионом.")
            return
        reply = QMessageBox.question(self, 'Подтверждение', f"Вы уверены, что хотите разжаловать модель #{model_id}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            success = self.trading_system.demote_champion(model_id)
            if success:
                QMessageBox.information(self, "Успех",
                                        f"Модель #{model_id} успешно разжалована. Система выберет нового чемпиона в следующем R&D цикле.")
                self.refresh_model_list()
            else:
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось разжаловать модель #{model_id}.")

    def run_backtest(self):
        test_type = self.bt_test_type_combo.currentText()
        symbol = self.bt_symbol_combo.currentText()
        timeframe_text = self.bt_timeframe_combo.currentText()
        timeframe = self.timeframe_map.get(timeframe_text)
        start_date = self.bt_start_date.date().toPython()
        end_date = self.bt_end_date.date().toPython()
        model_id = None
        strategy_name = None
        if test_type == "Классическая стратегия":
            strategy_name = self.bt_strategy_combo.currentText()
            if not all([symbol, strategy_name, timeframe is not None]):
                QMessageBox.warning(
                    self, "Ошибка", "Пожалуйста, выберите символ, стратегию и таймфрейм.")
                return
            self.bt_report_text.setText(
                f"Запуск бэктеста для {strategy_name} на {symbol} ({timeframe_text})...")
        elif test_type == "AI Модель":
            selected_model_text = self.bt_strategy_combo.currentText()
            if "Нет обученных моделей" in selected_model_text or not selected_model_text:
                QMessageBox.warning(
                    self, "Ошибка", "Пожалуйста, выберите AI модель.")
                return
            try:
                model_id = int(selected_model_text.split(' ')[1])
            except (ValueError, IndexError):
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось извлечь ID из строки: {selected_model_text}")
                return
            self.bt_report_text.setText(
                f"Запуск бэктеста для AI Модели ID:{model_id}...")
        self.bt_run_button.setEnabled(False)
        self.results_queue = multiprocessing.Queue()
        config_dict = self.trading_system.config.model_dump()
        self.backtest_process = multiprocessing.Process(
            target=run_backtest_process,
            args=(self.results_queue, config_dict, symbol, strategy_name, timeframe, start_date, end_date, test_type,
                  model_id)
        )
        self.backtest_process.start()
        self.backtest_check_timer = QTimer(self)
        self.backtest_check_timer.timeout.connect(self.check_backtest_results)
        self.backtest_check_timer.start(100)

    def check_backtest_results(self):
        try:
            result = self.results_queue.get_nowait()
            self.backtest_check_timer.stop()
            report = result['report']
            equity_df = result['equity']
            self.display_backtest_results(report, equity_df)

            def cleanup_process():
                self.backtest_process.join(timeout=5)
                if self.backtest_process.is_alive():
                    logger.warning(
                        "Процесс бэктеста не завершился штатно, принудительное завершение.")
                    self.backtest_process.terminate()
                    self.backtest_process.join()
                self.backtest_process.close()
                logger.info("Процесс бэктеста успешно завершен и очищен.")

            cleanup_thread = threading.Thread(
                target=cleanup_process, daemon=True)
            cleanup_thread.start()
        except queue.Empty:
            pass

    def display_backtest_results(self, report: dict, equity_df: pd.DataFrame):
        report_text = "--- Отчет по Бэктесту ---\n\n"
        for key, value in report.items():
            report_text += f"{key}: {value}\n"
        self.bt_report_text.setText(report_text)
        if not equity_df.empty:
            self.bt_equity_curve.setData(x=np.arange(
                len(equity_df)), y=equity_df['equity'].values)
        else:
            self.bt_equity_curve.clear()
        self.bt_run_button.setEnabled(True)

    def apply_update(self):
        reply = QMessageBox.question(self, 'Подтверждение',
                                     "Вы уверены, что хотите применить обновление и перезапустить систему?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.update_status_label.setText("Применение обновления...")
            self.update_button.setEnabled(False)
            QApplication.processEvents()
            self.trading_system.core_system.auto_updater.apply_update_and_restart()

    def update_update_status(self, message: str, is_available: bool):
        self.update_status_label.setText(message)
        self.update_button.setEnabled(is_available)

    def on_initialization_failed(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        QMessageBox.critical(self, "Ошибка Запуска",
                             "Не удалось подключиться к терминалу MetaTrader 5. Проверьте, что терминал запущен, и проверьте логи для деталей.")

    def on_history_trade_clicked(self, index):
        if not index.isValid():
            return
        ticket_item = self.history_model.index(index.row(), 0)
        try:
            ticket = int(self.history_model.data(ticket_item, Qt.DisplayRole))
        except (ValueError, TypeError):
            return
        self.good_trade_button.setEnabled(False)
        self.bad_trade_button.setEnabled(False)
        self.current_xai_ticket = None
        self.xai_label.setText(f"Загрузка данных для сделки #{ticket}...")
        self.xai_web_view.setHtml(
            "<html><body style='background-color:#282a36;'><h3 style='color:#f8f8f2; text-align:center;'>Загрузка...</h3></body></html>")
        threading.Thread(target=self.fetch_and_display_xai,
                         args=(ticket,), daemon=True).start()

    def fetch_and_display_xai(self, ticket: int):
        xai_data = self.trading_system.core_system.get_xai_data_for_trade(
            ticket)
        self.bridge.xai_data_ready.emit(xai_data, ticket)

    def display_xai_chart(self, xai_data: dict, ticket: int):
        if not xai_data or 'shap_values' not in xai_data or 'base_value' not in xai_data:
            self.xai_label.setText(
                f"Данные анализа для сделки #{ticket} отсутствуют или неполны.")
            self.xai_web_view.setHtml(
                "<html><body style='background-color:#282a36;'><h3 style='color:#f8f8f2; text-align:center;'>Данные отсутствуют.</h3></body></html>")
            return
        self.xai_label.setText(
            f"Интерактивный анализ влияния факторов на сделку #{ticket}")
        try:
            shap_values_dict = xai_data.get('shap_values', {})
            base_value = xai_data.get('base_value', 0.5)
            shap_values_array = np.array(list(shap_values_dict.values()))
            feature_names = list(shap_values_dict.keys())
            force_plot = shap.force_plot(
                base_value, shap_values_array, feature_names=feature_names, matplotlib=False)
            self.good_trade_button.setEnabled(True)
            self.bad_trade_button.setEnabled(True)
            self.current_xai_ticket = ticket
            if self.temp_html_file and os.path.exists(self.temp_html_file):
                os.remove(self.temp_html_file)
            fd, self.temp_html_file = tempfile.mkstemp(suffix=".html")
            os.close(fd)
            shap.save_html(self.temp_html_file, force_plot)
            plt.close('all')
            self.xai_web_view.setUrl(QUrl.fromLocalFile(self.temp_html_file))
        except Exception as e:
            logger.error(
                f"Ошибка при создании SHAP force plot: {e}", exc_info=True)
            self.xai_web_view.setHtml(
                f"<html><body><h3>Ошибка: {e}</h3></body></html>")

    def record_feedback(self, feedback_value: int):
        if self.current_xai_ticket is None:
            return
        logger.info(
            f"Отправка отзыва ({feedback_value}) для сделки #{self.current_xai_ticket} в ядро системы.")
        self.trading_system.core_system.record_human_feedback(
            trade_ticket=self.current_xai_ticket,
            feedback=feedback_value
        )
        self.good_trade_button.setEnabled(False)
        self.bad_trade_button.setEnabled(False)

    def start_trading(self):
        """Запускает процесс инициализации торговой системы."""
        logger.info(
            "[GUI-Action] Пользователь нажал кнопку 'Запустить торговлю'")
        try:
            if self.trading_system.core_system.running:
                logger.warning(
                    "[GUI-Action] Система уже запущена, игнорируем повторный запуск")
                return

            # Здесь больше нет диалогового окна
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.status_label.setText(
                "Подключение к торговому терминалу и запуск системы...")
            QApplication.processEvents()

            # Запускаем start_all_threads в фоновом потоке, чтобы не блокировать GUI
            threading.Thread(
                target=self.trading_system.start_all_threads, daemon=True).start()
            logger.info(
                "[GUI-Action] Торговая система запускается в фоновом потоке")
        except Exception as e:
            logger.error(
                f"[GUI-Action] Ошибка при запуске торговли: {e}", exc_info=True)

    def on_initialization_successful(self, symbols: list):
        logger.info(
            f"Инициализация успешна. Получено {len(symbols)} символов для бэктестера.")

        # Обновляем элементы GUI, которые зависят от данных
        self.bt_symbol_combo.clear()
        self.bt_symbol_combo.addItems(symbols)
        self._on_backtest_type_changed()
        self.refresh_model_list()

        # --- FIX: Refresh strategies in Control Center ---
        if hasattr(self, 'control_center_tab'):
            self.control_center_tab.refresh_strategies()
        # -------------------------------------------------

        # Включаем кнопку "Остановка", так как система успешно запущена
        self.stop_button.setEnabled(True)

        success, message = self.trading_system.connect_to_terminal_adapter()

        if success:
            self.bridge.status_updated.emit(
                "Соединение установлено. Запуск торговых циклов...", False)
            self.sound_manager.play("system_start")
            self.stop_button.setEnabled(True)

            self.trading_system.start_all_threads()
        else:
            error_msg = f"Ошибка подключения к MT5: {message}"
            self.bridge.status_updated.emit(error_msg, True)
            self.sound_manager.play("error")
            self.bridge.initialization_failed.emit()

    def stop_trading(self):
        logger.info(
            "[GUI-Action] Пользователь нажал кнопку 'Остановить торговлю'")
        try:
            if self.trading_system.core_system.running:
                self.sound_manager.play("system_stop")
                self.trading_system.stop()
                self.update_status(
                    "Команда на остановку отправлена...", is_error=False)
                logger.info(
                    "[GUI-Action] Команда на остановку торговой системы отправлена")
            else:
                logger.warning("[GUI-Action] Система уже остановлена")

            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

            self.uptime_label.setText("Время работы: остановлено")
        except Exception as e:
            logger.error(
                f"[GUI-Action] Ошибка при остановке торговли: {e}", exc_info=True)

    def close_all_positions(self):
        logger.info(
            "[GUI-Action] Пользователь нажал кнопку 'Закрыть все позиции'")
        try:
            reply = QMessageBox.question(self, 'Подтверждение',
                                         f"Вы уверены, что хотите закрыть ВСЕ открытые позиции по рынку?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                logger.warning(
                    "[GUI-Action] Подтверждено закрытие ВСЕХ позиций")
                self.sound_manager.play("error")
                self.trading_system.emergency_close_all_positions()
                self.close_pos_button.setEnabled(False)
                self.close_all_pos_button.setEnabled(False)
                self.bridge.status_updated.emit(
                    "Команда на закрытие всех позиций отправлена...", False)
            else:
                logger.info(
                    "[GUI-Action] Закрытие всех позиций отменено пользователем")
        except Exception as e:
            logger.error(
                f"[GUI-Action] Ошибка при закрытии всех позиций: {e}", exc_info=True)

    def on_all_positions_closed(self):
        self.close_pos_button.setEnabled(True)
        self.close_all_pos_button.setEnabled(True)
        self.bridge.status_updated.emit("Все позиции закрыты.", False)

    def update_rd_view(self, progress_data: dict):
        logger.info(f"[GUI-RD] Обновление R&D: {progress_data}")
        self.rd_model.update_data(progress_data)
        self.rd_table.scrollToBottom()

    def close_selected_position(self):
        logger.info(
            "[GUI-Action] Пользователь нажал кнопку 'Закрыть выбранную позицию'")
        try:
            selected_indexes = self.positions_table.selectionModel().selectedRows()
            if not selected_indexes:
                logger.warning(
                    "[GUI-Action] Не выбрана ни одна позиция для закрытия")
                QMessageBox.warning(
                    self, "Внимание", "Не выбрана ни одна позиция.")
                return
            ticket_item = self.positions_model.index(
                selected_indexes[0].row(), 0)
            ticket = int(self.positions_model.data(
                ticket_item, Qt.DisplayRole))
            reply = QMessageBox.question(self, 'Подтверждение', f"Закрыть позицию #{ticket} по рынку?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                logger.info(
                    f"[GUI-Action] Подтверждено закрытие позиции #{ticket}")
                self.trading_system.emergency_close_position(ticket)
            else:
                logger.info(
                    f"[GUI-Action] Закрытие позиции #{ticket} отменено пользователем")
        except Exception as e:
            logger.error(
                f"[GUI-Action] Ошибка при закрытии выбранной позиции: {e}", exc_info=True)

    def toggle_observer_mode(self):
        self.trading_system.toggle_observer_mode()

    def update_status(self, message, is_error):
        logger.info(
            f"[GUI-Status] Обновление статуса: '{message}', ошибка={is_error}")
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: red;" if is_error else "")

    def update_balance(self, balance, equity):
        # Убрано избыточное логирование (каждые 3 секунды)
        self.balance_label.setText(f"Баланс: {balance:.2f}")
        self.equity_label.setText(f"Эквити: {equity:.2f}")

    def add_log_message(self, text: str, color: QColor):
        char_format = QTextCharFormat()
        char_format.setForeground(color)
        cursor = self.log_text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.setCharFormat(char_format)
        cursor.insertText(text + '\n')
        cursor.setCharFormat(QTextCharFormat())
        self.log_text_edit.ensureCursorVisible()

    def update_positions_table(self, positions: list):
        """
        Обновляет таблицу открытых позиций данными, полученными от Core.
        """
        try:
            table_data = []

            for pos_dict in positions:
                ticket = pos_dict.get('ticket')
                # 0 - это ORDER_TYPE_BUY в MT5
                pos_type = "BUY" if pos_dict.get('type') == 0 else "SELL"

                # Получаем уже готовые строки, которые мы подготовили в trading_system.py
                # Метод .get(ключ, 'значение_по_умолчанию') защищает от ошибок, если данных нет
                strategy_name = pos_dict.get('strategy_display', 'Загрузка...')
                timeframe_str = pos_dict.get('timeframe_display', 'N/A')
                bars_in_trade = pos_dict.get('bars_in_trade_display', '-')

                profit = float(pos_dict.get('profit', 0.0))

                # Собираем строку для таблицы. ПОРЯДОК ДОЛЖЕН СОВПАДАТЬ С ЗАГОЛОВКАМИ из Шага 3
                row_data = [
                    ticket,  # Тикет
                    pos_dict.get('symbol'),  # Символ
                    strategy_name,  # Стратегия
                    pos_type,  # Тип
                    pos_dict.get('volume'),  # Объем
                    f"{pos_dict.get('price_open', 0):.5f}",  # Цена откр.
                    f"{profit:.2f}",  # Прибыль
                    bars_in_trade,  # Баров
                    timeframe_str  # ТФ
                ]

                table_data.append(row_data)

            # Обновляем модель таблицы
            self.positions_model = GenericTableModel(
                table_data, self.positions_headers)
            self.positions_table.setModel(self.positions_model)
            # Убрано избыточное логирование
        except Exception as e:
            logger.error(
                f"[GUI-Positions] Ошибка при обновлении таблицы позиций: {e}", exc_info=True)

    def update_history_table(self, deals: list):
        logger.info(
            f"[GUI-History] Обновление истории сделок: {len(deals)} сделок")
        try:
            table_data = []
            for deal in deals:
                time_str = deal.time_close.strftime('%Y-%m-%d %H:%M')
                timeframe_display = deal.timeframe.replace(
                    'TIMEFRAME_', '') if deal.timeframe else "N/A"

                # +++ НАЧАЛО ИЗМЕНЕНИЙ: Приводим порядок данных в соответствие с заголовками +++
                table_data.append([
                    deal.ticket,
                    deal.symbol,
                    deal.strategy,  # Сначала Стратегия
                    deal.trade_type,  # Потом Тип
                    deal.volume,
                    f"{deal.price_close:.5f}",
                    time_str,
                    f"{deal.profit:.2f}",
                    timeframe_display
                ])
                # +++ КОНЕЦ ИЗМЕНЕНИЙ +++

            self.history_model = GenericTableModel(
                table_data, self.history_headers)
            self.history_table.setModel(self.history_model)
            self.chart_trade_history = deals
            current_symbol = self.price_plot.titleLabel.text.replace(
                "График ", "")
            if current_symbol:
                self.update_trade_arrows(current_symbol)
            logger.debug(
                f"[GUI-History] Таблица истории успешно обновлена, строк: {len(table_data)}")
        except Exception as e:
            logger.error(
                f"[GUI-History] Ошибка при обновлении таблицы истории: {e}", exc_info=True)

    def update_market_scanner_view(self, ranked_list: list):
        # ОТЛАДКА: Логируем (используем logger вместо print для Windows GUI)
        logger.debug(
            f"[DEBUG] update_market_scanner_view ВЫЗВАН с {len(ranked_list) if ranked_list else 0} элементами")

        # КРИТИЧНО: Не обновляем таблицу пустыми данными
        if not ranked_list or len(ranked_list) == 0:
            return

        logger.info(
            f"[GUI-Scanner] Обновление сканера: {len(ranked_list)} символов")

        try:
            # Оптимизация: ограничиваем количество отображаемых элементов
            if len(ranked_list) > 100:
                ranked_list = ranked_list[:100]

            table_data = []
            for item in ranked_list:
                # ИСПРАВЛЕНИЕ: Конвертируем numpy типы в Python типы для корректного отображения
                row = [
                    int(item.get('rank', 0)) if item.get('rank') else '-',
                    str(item.get('symbol', 'N/A')),
                    f"{float(item.get('total_score', 0)):.3f}",
                    f"{float(item.get('volatility_score', 0)):.3f}",
                    f"{float(item.get('normalized_atr_percent', 0)):.3f}%",
                    f"{float(item.get('trend_score', 0)):.3f}",
                    f"{float(item.get('liquidity_score', 0)):.3f}",
                    f"{float(item.get('spread_pips', -1.0)):.1f}"
                ]
                table_data.append(row)

            # Убрано избыточное логирование

            # Оптимизация: обновляем только данные модели, не создавая новую
            if not hasattr(self, 'scanner_model') or self.scanner_model is None:
                self.scanner_model = GenericTableModel(
                    table_data, self.scanner_headers)
                self.scanner_table.setModel(self.scanner_model)
            else:
                self.scanner_model.update_data(table_data)

            # Оптимизация: устанавливаем размер столбцов только при первой инициализации
            if not hasattr(self, '_scanner_columns_resized'):
                header = self.scanner_table.horizontalHeader()
                for i in range(len(self.scanner_headers)):
                    header.setSectionResizeMode(
                        i, QHeaderView.ResizeMode.ResizeToContents)
                self._scanner_columns_resized = True
        except Exception as e:
            logger.error(
                f"[GUI-Scanner] Ошибка при обновлении сканера: {e}", exc_info=True)

    def update_uptime(self, uptime_str: str):
        # Убрано избыточное логирование
        self.uptime_label.setText(f"Время работы: {uptime_str}")

    def open_settings_window(self):
        logger.info("[GUI-Dialog] Открытие окна настроек")
        dialog = self.settings_window
        dialog.settings_saved.connect(self.on_settings_saved)
        try:
            if dialog.exec():
                logger.info(
                    "[GUI-Dialog] Окно настроек закрыто с сохранением, применяем изменения...")
                new_config = load_config()
                self.trading_system.update_configuration(new_config)
            else:
                logger.info(
                    "[GUI-Dialog] Окно настроек закрыто без сохранения")
        except Exception as e:
            logger.error(
                f"[GUI-Dialog] Ошибка при работе с окном настроек: {e}", exc_info=True)

    def update_observer_pnl_chart(self, pnl_history: list):
        if not pnl_history:
            self.observer_pnl_curve.setData([], [])
            return
        try:
            initial_balance = 10000  # Стартовый баланс для симуляции
            cumulative_pnl = np.cumsum(pnl_history)
            equity_curve = initial_balance + cumulative_pnl

            self.observer_pnl_curve.setData(
                x=np.arange(len(equity_curve)), y=equity_curve)
            self.observer_pnl_plot.setTitle(
                f"Доходность (Наблюдатель: {cumulative_pnl[-1]:.2f})")
        except Exception as e:
            logger.error(f"Ошибка при построении графика P&L наблюдателя: {e}")

    def update_pnl_chart(self, trade_history: list):
        logger.info(
            f"[GUI-PnL] Обновление графика P&L: {len(trade_history)} сделок")
        if not trade_history:
            self.pnl_curve.setData([], [])
            logger.debug("[GUI-PnL] История сделок пуста, график очищен")
            return
        try:
            # Оптимизация: используем только необходимые поля и ограничиваем количество точек
            if len(trade_history) > 1000:  # Ограничение количества точек для производительности
                step = len(trade_history) // 1000
                trade_history = trade_history[::step]
                logger.debug(
                    f"[GUI-PnL] История обрезана для производительности, шаг={step}")

            # Создаем DataFrame более эффективно
            data = []
            for deal in trade_history:
                data.append(
                    {'profit': deal.profit, 'time_close': deal.time_close.timestamp()})

            df = pd.DataFrame(data)
            if df.empty or 'profit' not in df.columns or 'time_close' not in df.columns:
                logger.warning(
                    "[GUI-PnL] DataFrame пуст или не содержит необходимых колонок")
                return

            df = df.sort_values(by='time_close')
            df['cumulative_profit'] = df['profit'].cumsum()

            timestamps = df['time_close'].values
            cumulative_profit = df['cumulative_profit'].values

            self.pnl_curve.setData(x=timestamps, y=cumulative_profit)
            self.pnl_plot.setTitle(
                f"Кривая доходности (P&L: {cumulative_profit[-1]:.2f})")
            logger.debug(
                f"[GUI-PnL] График успешно обновлен, итоговый P&L: {cumulative_profit[-1]:.2f}")
        except Exception as e:
            logger.error(
                f"[GUI-PnL] Ошибка при построении графика P&L: {e}", exc_info=True)

    def update_training_chart(self, history_object):
        logger.info(f"[GUI-Training] Обновление графика обучения")
        try:
            history_dict = history_object.history
            if 'loss' in history_dict and history_dict['loss']:
                loss_values = history_dict['loss']
                self.loss_curve.setData(
                    y=loss_values, x=list(range(len(loss_values))))
                self.loss_plot.setTitle(
                    f"Прогресс обучения (Loss: {loss_values[-1]:.4f})")
                logger.debug(
                    f"[GUI-Training] График обновлен, эпох: {len(loss_values)}, финальный loss: {loss_values[-1]:.4f}")
            else:
                logger.warning(
                    "[GUI-Training] История обучения не содержит данных о loss")
        except Exception as e:
            logger.error(
                f"[GUI-Training] Ошибка при обновлении графика обучения: {e}", exc_info=True)

    def update_candle_chart(self, df: pd.DataFrame, symbol: str):
        logger.info(
            f"[GUI-Chart] update_candle_chart вызван: symbol={symbol}, df is None={df is None}, df.empty={df.empty if df is not None else 'N/A'}, len={len(df) if df is not None else 0}")
        if df is None or df.empty or len(df) < 2:
            logger.warning(
                f"[GUI-Chart] Данные недостаточны для отображения графика {symbol}")
            return
        try:
            df = df.sort_index()  # Гарантируем хронологию
            logger.info(
                f"[GUI-Chart] Обновление графика для {symbol}, баров: {len(df)}")
            self.price_plot.setTitle(f"График {symbol}")
            # Оптимизация: используем последние 200 баров без копирования лишних данных
            if len(df) > 200:
                df_chart = df.tail(200)
                logger.debug(
                    f"[GUI-Chart] График обрезан до 200 баров из {len(df)}")
            else:
                df_chart = df

            # Оптимизация: преобразование данных в numpy массивы для ускорения
            timestamps = (pd.to_datetime(df_chart.index).astype(
                np.int64) / 1e9).astype(np.float64)
            open_vals = df_chart['open'].values.astype(np.float64)
            high_vals = df_chart['high'].values.astype(np.float64)
            low_vals = df_chart['low'].values.astype(np.float64)
            close_vals = df_chart['close'].values.astype(np.float64)

            candlestick_data = np.column_stack(
                (timestamps, open_vals, high_vals, low_vals, close_vals))
            self.candlestick_item.setData(candlestick_data)
            logger.debug(
                f"[GUI-Chart] Данные свечей установлены: {len(candlestick_data)} баров")

            # Обновление объема
            volume_vals = df_chart['tick_volume'].values
            self.volume_item.setOpts(x=timestamps, height=volume_vals)

            # === ИСПРАВЛЕНИЕ: Устанавливаем диапазон вручную с правильным масштабом ===
            if len(timestamps) > 1:
                # Вычисляем диапазон по X (время)
                time_span = timestamps[-1] - timestamps[0]
                x_padding = max(time_span * 0.1, 3600)  # Минимум 1 час отступ
                x_min = timestamps[0] - x_padding
                x_max = timestamps[-1] + x_padding

                # Вычисляем диапазон по Y (цена) с учетом волатильности
                price_range = max(high_vals) - min(low_vals)
                # Минимум 1 единица отступ
                y_padding = max(price_range * 0.1, 1.0)
                y_min = min(low_vals) - y_padding
                y_max = max(high_vals) + y_padding

                # Применяем диапазон с небольшим отступом
                self.price_plot.setXRange(x_min, x_max, padding=0.02)
                self.price_plot.setYRange(y_min, y_max, padding=0.02)
                logger.debug(
                    f"[GUI-Chart] Диапазон установлен: X=[{x_min:.0f}, {x_max:.0f}] ({time_span/3600:.1f}ч), Y=[{y_min:.2f}, {y_max:.2f}] ({price_range:.2f})")

            logger.info(
                f"[GUI-Chart] График {symbol} успешно обновлен, {len(candlestick_data)} баров отображено")
        except Exception as e:
            logger.error(
                f"[GUI-Chart] Ошибка при обновлении графика {symbol}: {e}", exc_info=True)

    def update_trade_arrows(self, symbol: str):
        trade_points = []
        for deal in self.chart_trade_history:
            if deal.symbol == symbol:
                timestamp = deal.time_open.timestamp()
                price = deal.price_open
                arrow_symbol, color = (
                    't1', 'g') if deal.trade_type == "BUY" else ('t', 'r')
                trade_points.append(
                    {'pos': (timestamp, price), 'symbol': arrow_symbol, 'brush': pg.mkBrush(color), 'size': 15})
        self.trade_arrows_item.setData(trade_points)

    def update_market_regime_viz(self, regime: str):
        color = self.regime_colors.get(regime, QColor(0, 0, 0, 0))
        self.regime_region.setBrush(color)
        view_range = self.price_plot.vb.viewRange()
        self.regime_region.setRegion([view_range[0][0], view_range[0][1]])

    @Slot(float, str, float, bool)
    def update_drift_chart(self, timestamp: float, symbol: str, error: float, is_drift: bool):
        """
        Обновляет график ошибок предсказания.
        Принимает timestamp (секунды), символ, ошибку (0.0 - 1.0) и флаг дрейфа.
        """
        import logging
        # Логируем входящие данные, чтобы видеть, приходят ли они вообще
        logging.info(
            f"[GUI Drift] Получены данные: Time={timestamp}, Sym={symbol}, Err={error:.4f}, Drift={is_drift}")

        try:
            # Формируем точку как словарь с x, y и метаданными
            point = {
                'x': float(timestamp),
                'y': float(error),
                'data': symbol,  # Метаданные для тултипа
            }

            # --- ИСПРАВЛЕНИЕ: Разделение точек на два списка ---
            if is_drift:
                # Для дрейфа используем отдельный список
                self.drift_alert_points.append(point)
            else:
                # Для нормальных точек используем основной список
                self.drift_data_points.append(point)

            # Ограничиваем количество точек на графике (последние 200 сделок)
            if len(self.drift_data_points) > 200:
                self.drift_data_points.pop(0)
            # Ограничиваем количество алертов (например, 50)
            if len(self.drift_alert_points) > 50:
                self.drift_alert_points.pop(0)

            # --- ИСПРАВЛЕНИЕ: Обновление двух ScatterPlotItem ---

            # 1. Обновляем нормальные точки (зеленые круги)
            self.drift_scatter.setData(
                x=[p['x'] for p in self.drift_data_points],
                y=[p['y'] for p in self.drift_data_points],
                # brush, size, symbol уже заданы при создании
            )

            # 2. Обновляем точки дрейфа (красные крестики)
            self.drift_alert_scatter.setData(
                x=[p['x'] for p in self.drift_alert_points],
                y=[p['y'] for p in self.drift_alert_points],
                # brush, pen, size, symbol уже заданы при создании
            )

            # Принудительно обновляем виджет
            self.drift_plot_widget.update()

        except Exception as e:
            logging.error(f"[GUI Error] Ошибка отрисовки Drift Chart: {e}")

    def closeEvent(self, event):
        logger.info("Получена команда на закрытие окна GUI.")

        # --- ЗАЩИТА ОТ СЛУЧАЙНОГО ЗАКРЫТИЯ ---
        reply = QMessageBox.question(
            self,
            'Подтверждение закрытия',
            'Вы действительно хотите закрыть торговую систему?\n\nВсе активные сделки будут сохранены, но мониторинг остановится.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.No:
            logger.info("Закрытие окна отменено пользователем.")
            event.ignore()
            return

        # --- 1. Проверка, запущена ли система ---
        if self.trading_system.core_system.running:
            # Инициируем штатную остановку (отправляет сигнал stop_event)
            self.trading_system.core_system.initiate_graceful_shutdown()

            # --- 2. Виджет ожидания ---
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setText("Завершение работы...")
            msg.setInformativeText(
                "Пожалуйста, подождите, пока все фоновые потоки будут остановлены.")
            msg.setStandardButtons(QMessageBox.NoButton)
            msg.show()
            QApplication.processEvents()

            # --- 3. Рабочий класс для ожидания завершения потоков ---
            # (Использует QRunnable, чтобы не блокировать главный цикл PySide)
            class JoinWorker(QRunnable):
                def __init__(self, core_system):
                    super().__init__()
                    self.core_system = core_system

                def run(self):
                    # Отправляем сигнал остановки (если не было) и ждем завершения
                    self.core_system.stop_event.set()
                    # _join_all_threads - это блокирующая операция, которая ждет завершения всех потоков
                    self.core_system._join_all_threads()

            join_worker = JoinWorker(self.trading_system.core_system)
            self.threadpool.start(join_worker)

            # --- 4. Блокирующий цикл ожидания в главном потоке (с таймаутом) ---
            # Используем импортированный 'time'
            import time as standard_time
            start_time = standard_time.time()

            # Ждем, пока система не остановится или не истечет 15 секунд
            while self.trading_system.core_system.running and (standard_time.time() - start_time < 15):
                QApplication.processEvents()
                standard_time.sleep(0.05)

            # --- 5. Финальная очистка ---
            msg.hide()
            if self.trading_system.core_system.running:
                logger.critical(
                    "!!! ПРИНУДИТЕЛЬНОЕ ЗАВЕРШЕНИЕ: Не все потоки остановились за 15 секунд. !!!")
            else:
                logger.info(
                    "Все фоновые потоки остановлены. Закрываем приложение.")

        logger.info("=== ЗАКРЫТИЕ GUI ПОДТВЕРЖДЕНО ===")
        event.accept()

    def event(self, e):
        """Перехватываем все события для отладки"""
        # Логируем только критичные события
        if e.type() == QEvent.Close:
            logger.warning(f"=== QEvent.Close ПОЛУЧЕН ===")
        elif e.type() == QEvent.Quit:
            logger.warning(f"=== QEvent.Quit ПОЛУЧЕН ===")
        elif e.type() == QEvent.Hide:
            logger.warning(f"=== QEvent.Hide ПОЛУЧЕН ===")

        return super().event(e)

    def force_training(self):
        logger.info(
            "[GUI-Action] Пользователь нажал кнопку 'Запустить цикл обучения'")
        try:
            # Теперь вызываем прокси-метод
            self.trading_system.force_training_cycle()
            QMessageBox.information(self, "Запрос отправлен",
                                    "Команда на запуск цикла обучения отправлена в фоновый поток.")
            logger.info(
                "[GUI-Action] Команда на запуск цикла обучения отправлена")
        except Exception as e:
            logger.error(
                f"[GUI-Action] Ошибка при запуске цикла обучения: {e}", exc_info=True)

    def force_rd(self):
        logger.info(
            "[GUI-Action] Пользователь нажал кнопку 'Запустить R&D цикл'")
        try:
            # Теперь вызываем прокси-метод
            self.trading_system.force_rd_cycle()
            QMessageBox.information(
                self, "Запрос отправлен", "Команда на запуск R&D цикла отправлена в фоновый поток.")
            logger.info("[GUI-Action] Команда на запуск R&D цикла отправлена")
        except Exception as e:
            logger.error(
                f"[GUI-Action] Ошибка при запуске R&D цикла: {e}", exc_info=True)

    def update_orchestrator_panel(self, allocation_data: dict):
        logger.info(
            f"[GUI-Orchestrator] Обновление панели оркестратора: {len(allocation_data)} режимов")
        try:
            labels = list(allocation_data.keys())
            values = [v * 100 for v in allocation_data.values()]
            x = np.arange(len(labels))
            self.orchestrator_bar_item.setOpts(x=x, height=values)
            ticks = [(i, label) for i, label in enumerate(labels)]
            self.orchestrator_chart_widget.getAxis('bottom').setTicks([ticks])
            logger.debug(
                f"[GUI-Orchestrator] Панель обновлена: {dict(zip(labels, values))}")
        except Exception as e:
            logger.error(
                f"[GUI-Orchestrator] Ошибка при обновлении панели Оркестратора: {e}", exc_info=True)

    @Slot(str)
    def update_knowledge_graph(self, graph_json: str):
        """Слот, принимающий JSON-строку от ядра системы."""
        if not self.kg_enabled_checkbox.isChecked():
            return

        try:
            graph_data = json.loads(graph_json)

            if self.is_graph_ready:
                # Если JS готов, отправляем сразу
                self.graph_backend.graphDataUpdated.emit(graph_data)
            else:
                # Если нет, кладем в очередь
                # Сохраняем только последнее состояние
                self.graph_data_queue = [graph_data]

        except Exception as e:
            logger.error(f"Ошибка в update_knowledge_graph: {e}")

    @Slot()
    def on_js_ready(self):
        logger.info("JS Граф готов! Инициализация данных...")
        self.is_graph_ready = True

        # Проверяем, есть ли данные в очереди (данные, пришедшие до готовности JS)
        if hasattr(self, 'graph_data_queue') and self.graph_data_queue:

            # Отправляем только последний элемент, так как он самый актуальный
            # (или все, если нужно, но для графа обычно достаточно последнего состояния)
            latest_data = self.graph_data_queue[-1]

            logger.info(
                f"Отправка {len(self.graph_data_queue)} пакетов данных из очереди в Граф (отправляется только последний).")

            # Отправляем данные
            self.graph_backend.graphDataUpdated.emit(latest_data)

            # Очищаем очередь после отправки
            self.graph_data_queue.clear()

        else:
            # Если очередь пуста, это первый запуск или данные еще не пришли.
            # Запускаем принудительный запрос в фоновом потоке.
            logger.info("Очередь пуста. Запрос свежих данных из БД...")
            threading.Thread(target=self._force_graph_update,
                             daemon=True).start()

    # Метод _force_graph_update остается без изменений, так как он корректен:
    def _force_graph_update(self):
        # Вспомогательный метод для принудительного обновления
        try:
            # 1. Вызываем метод, который должен вернуть данные
            graph_data = self.trading_system.core_system.db_manager.get_graph_data(
                limit=50)

            if graph_data:
                # 2. Если данные есть, отправляем их
                self.bridge.knowledge_graph_updated.emit(
                    json.dumps(graph_data))
                logger.info(
                    f"KG: Отправлено {len(graph_data['nodes'])} узлов и {len(graph_data['edges'])} связей в GUI.")
            else:
                # 3. Если данных нет, отправляем пустой набор (или заглушку)
                self.bridge.knowledge_graph_updated.emit(
                    json.dumps({"nodes": [], "edges": []}))
                logger.warning(
                    "KG: В базе данных пока нет связей для отображения.")

        except Exception as e:
            logger.error(f"Ошибка принудительного обновления графа: {e}")

    def on_runtime_settings_changed(self, new_settings: dict):
        self.trading_system.core_system.update_runtime_settings(new_settings)

    @Slot()
    def on_heavy_initialization_finished(self):
        """Слот, который безопасно включает кнопку запуска после загрузки моделей."""
        self.start_button.setEnabled(True)

    def on_filter_request(self, filter_type: str, filter_value: str):
        """
        Обрабатывает запрос на фильтрацию графа.
        В текущей версии просто запрашивает все данные и отправляет их обратно.
        (Фактическая фильтрация будет реализована на стороне JS для простоты).
        """
        logger.info(
            f"KG Filter Request: Type={filter_type}, Value={filter_value}")

        # Запускаем в отдельном потоке, чтобы не блокировать GUI
        threading.Thread(target=self._fetch_and_send_filtered_graph,
                         args=(filter_type, filter_value),
                         daemon=True).start()

    def _fetch_and_send_filtered_graph(self, filter_type: str, filter_value: str):
        """
        Синхронный метод для получения данных из БД и отправки в JS.
        """
        try:
            # В реальной системе здесь была бы сложная логика запроса к Neo4j/SQLite.
            # Для демонстрации: просто запрашиваем последние 50 связей
            graph_data = self.trading_system.core_system.db_manager.get_graph_data(
                limit=50)

            if graph_data:
                # Отправляем данные обратно в JS
                # В JS будет реализована логика фильтрации по полученному набору
                self.graph_backend.graphDataUpdated.emit(graph_data)

        except Exception as e:
            logger.error(f"Ошибка при фильтрации графа: {e}")


_logger_configured = False


def run_core_process(config_dict):
    """
    Эта функция выполняется в отдельном процессе и содержит ВСЮ тяжелую логику.
    """
    # 1. Переинициализация логирования для нового процесса
    from src.core.config_loader import load_config
    from src.core.trading_system import TradingSystem
    from src.gui.sound_manager import SoundManager
    from src.gui.log_utils import setup_qt_logging  # Используем для настройки

    # Загружаем конфиг из словаря
    app_config = Settings(**config_dict)

    # Настраиваем логирование для этого процесса
    # Логируем только в файл/консоль
    setup_qt_logging(lambda *a, **k: None, app_config)

    logger.critical("--- CORE PROCESS STARTED ---")

    # 2. Инициализация и запуск Core
    bridge = type('Bridge', (object,), {
                  '__getattr__': lambda self, name: lambda *a, **k: None})()
    sound_manager = SoundManager(
        project_root=os.path.dirname(os.path.abspath(__file__)))

    core_system = TradingSystem(
        config=app_config, gui=None, sound_manager=sound_manager, bridge=bridge)

    try:
        core_system.initialize_heavy_components()
        core_system.start_all_background_services(
            None)  # Запускаем без QThreadPool

        logger.critical(
            "CORE PROCESS: Heavy initialization and services started.")

        # 3. Блокировка процесса
        while core_system.running:
            standard_time.sleep(1)

    except Exception as e:
        logger.critical(f"CORE PROCESS CRITICAL FAILURE: {e}", exc_info=True)
    finally:
        logger.critical("--- CORE PROCESS SHUTDOWN ---")


def qt_exception_hook(exctype, value, traceback_obj):
    """Глобальный обработчик необработанных исключений Qt"""
    import traceback
    tb_lines = traceback.format_exception(exctype, value, traceback_obj)
    tb_text = ''.join(tb_lines)
    logger.critical(f"=== НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ В QT ===\n{tb_text}")
    logger.critical(f"Exception type: {exctype}")
    logger.critical(f"Exception value: {value}")
    # Не вызываем sys.exit, чтобы дать возможность Qt обработать


def main():
    """Основная функция для запуска приложения."""
    # Установка глобального обработчика исключений
    sys.excepthook = qt_exception_hook

    os.environ['QT_WEBENGINE_DISABLE_SANDBOX'] = '1'
    app = QApplication(sys.argv)

    try:
        # --- НОВАЯ, НАДЕЖНАЯ НАСТРОЙКА ЛОГИРОВАНИЯ ---
        app_config = load_config()

        bridge = Bridge()

        # 1. Создание SoundManager
        PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
        sound_manager = SoundManager(project_root=PROJECT_ROOT)

        # 2. Вызываем нашу новую функцию ОДИН РАЗ, передав ей нужный сигнал и конфиг
        setup_qt_logging(bridge.log_message_added, app_config)

        # 3. ЕДИНСТВЕННАЯ ИНИЦИАЛИЗАЦИЯ
        # TradingSystem.__init__ теперь не требует db_manager/vector_db_manager
        trading_system_adapter = PySideTradingSystem(
            config=app_config, bridge=bridge, sound_manager=sound_manager)

        window = MainWindow(trading_system_adapter, app_config)

        # Добавляем обработчик aboutToQuit
        app.aboutToQuit.connect(lambda: logger.info(
            "=== QApplication.aboutToQuit СИГНАЛ ПОЛУЧЕН ==="))

        window.show()
        logger.info("=== ОКНО ПОКАЗАНО, РАЗМЕР: {}x{} ===".format(
            window.width(), window.height()))

        logger.info("=== GUI ЗАПУЩЕН УСПЕШНО, ВХОД В EVENT LOOP ===")
        exit_code = app.exec()
        logger.info(f"=== GUI EVENT LOOP ЗАВЕРШЕН, КОД: {exit_code} ===")
        sys.exit(exit_code)

    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА В MAIN GUI: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
