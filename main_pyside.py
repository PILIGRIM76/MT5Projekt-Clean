# -*- coding: utf-8 -*-
# main_pyside.py
# ============================================================================
# ИСПРАВЛЕНИЕ: Отключаем использование системного прокси для всех HTTP-запросов
# ============================================================================
import os

# Удаляем переменные окружения прокси, если они есть
for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(proxy_var, None)
# Устанавливаем переменную для игнорирования прокси в urllib3
os.environ["NO_PROXY"] = "*"
# ============================================================================

import json
import logging
import sys
import time as standard_time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict

import matplotlib
import MetaTrader5 as mt5
import urllib3
from PySide6.QtCore import QEvent, QRunnable, Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from urllib3.exceptions import InsecureRequestWarning

from src.core.config_loader import load_config
from src.core.config_models import Settings
from src.core.trading_system import TradingSystem
from src.gui.log_utils import setup_qt_logging
from src.gui.main_window_parts import PanelsMixin, ChartsMixin, SignalsMixin
from src.gui.settings_window import SettingsWindow
from src.gui.sound_manager import SoundManager
from src.gui.widgets import Bridge
from src.gui.trading_system_adapter import PySideTradingSystem
from src.utils.logger import setup_logger
from src.utils.scheduler_manager import SchedulerManager

# Создаём главный логгер приложения
logger = setup_logger(
    name="genesis", level=logging.INFO, log_to_file=True, log_to_console=True, rotation="daily", backup_count=7
)

logger.info("=" * 60)
logger.info("  Genesis Trading System - Запуск")
logger.info("=" * 60)
logger.info(f"Версия Python: {sys.version}")
logger.info(f"Путь к скрипту: {Path(__file__).resolve()}")


# ===================================================================
# === ПРОВЕРКА КОНФИГУРАЦИИ ПЕРЕД ЗАПУСКОМ ===
# ===================================================================


def check_and_run_setup():
    """Проверка конфигурации и запуск мастера настройки при необходимости"""
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent

    config_path = base_path / "configs" / "settings.json"

    needs_setup = False
    reason = ""

    if not config_path.exists():
        needs_setup = True
        reason = "Файл конфигурации не найден"
    else:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = "".join(line for line in f if not line.strip().startswith("//"))
                config = json.loads(content)

            required_fields = ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_PATH"]
            missing_fields = []
            for field in required_fields:
                if field not in config or not config[field]:
                    missing_fields.append(field)

            if missing_fields:
                needs_setup = True
                reason = f"Отсутствуют обязательные параметры: {', '.join(missing_fields)}"

            if "MT5_PATH" in config and config["MT5_PATH"]:
                mt5_path = Path(config["MT5_PATH"])
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

        setup_script = base_path / "setup_launcher.py"
        if setup_script.exists():
            if getattr(sys, "frozen", False):
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

os.environ["CURL_CA_BUNDLE"] = ""
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
matplotlib.use("Agg")

# ===================================================================
# === НАСТРОЙКА КОЛИЧЕСТВА ЯДЕР CPU ===
# ===================================================================

cpu_count = 4
logger.info(f"Используем {cpu_count} ядер CPU для обучения моделей (из 12 доступных)")

if "OMP_NUM_THREADS" not in os.environ:
    os.environ["OMP_NUM_THREADS"] = str(cpu_count)
if "MKL_NUM_THREADS" not in os.environ:
    os.environ["MKL_NUM_THREADS"] = str(cpu_count)
if "NUMBA_NUM_THREADS" not in os.environ:
    os.environ["NUMBA_NUM_THREADS"] = str(cpu_count)
if "TORCH_NUM_THREADS" not in os.environ:
    os.environ["TORCH_NUM_THREADS"] = str(cpu_count)

os.environ["NUMBA_DISABLE_JIT"] = "0"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CUDA_VISIBLE_DEVICES"] = ""

try:
    project_root = Path(__file__).resolve().parent
    settings_path = project_root / "configs" / "settings.json"

    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            settings_data = json.load(f)

        hf_cache_dir_str = settings_data.get("HF_MODELS_CACHE_DIR")

        if hf_cache_dir_str:
            try:
                cache_path = Path(hf_cache_dir_str)
                root_disk = cache_path.anchor
                if not Path(root_disk).exists():
                    logger.warning(f"[WARN] Корневой диск '{root_disk}' для кэша HF не найден. Используется стандартный путь.")
                else:
                    cache_path.mkdir(parents=True, exist_ok=True)
                    os.environ["HF_HOME"] = str(cache_path.resolve())
            except Exception as e_mkdir:
                logger.error(
                    f"[ERROR] Не удалось создать/использовать директорию для кэша '{hf_cache_dir_str}'. Причина: {e_mkdir}."
                )
    else:
        logger.warning("[WARN] Файл settings.json не найден, используется стандартный путь для кэша HF.")
except Exception as e:
    logger.error(f"[ERROR] Не удалось прочитать settings.json для настройки HF_HOME: {e}")


os.environ["QT_WEBENGINE_DISABLE_SANDBOX"] = "1"

warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="X does not have valid feature names, but LGBMRegressor was fitted with feature names",
)

warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="X does not have valid feature names, but MinMaxScaler was fitted with feature names",
)


SRC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")

if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


logger = logging.getLogger(__name__)


# ===================================================================
# === MainWindow (наследует миксины из main_window_parts/) ===
# ===================================================================


class MainWindow(PanelsMixin, ChartsMixin, SignalsMixin, QMainWindow):
    def __init__(self, trading_system_adapter: PySideTradingSystem, config: Settings):
        super().__init__()
        self.setWindowTitle("Genesis v24.0: Reflexive Core")

        logger.info("=== НАЧАЛО ИНИЦИАЛИЗАЦИИ MainWindow ===")

        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(10)
        logger.info(f"QThreadPool инициализирован с макс. {self.threadpool.maxThreadCount()} потоками.")

        self.config = config
        self.trading_system = trading_system_adapter
        self.bridge = self.trading_system.bridge
        self.sound_manager = self.trading_system.core_system.sound_manager
        self.chart_trade_history = []
        self.temp_html_file = None

        self.drift_data_points = []
        self.drift_alert_points = []

        self.thread_status_labels: Dict[str, QLabel] = {}
        self.scheduler_status_labels: Dict[str, QLabel] = {}

        project_root = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(project_root, "assets", "icon.ico.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logger.warning(f"Файл иконки не найден по пути: {icon_path}")

        self.notification_bar = QFrame()
        self.notification_bar.setObjectName("NotificationBar")
        notification_layout = QHBoxLayout()
        self.notification_bar.setLayout(notification_layout)
        self.notification_label = QLabel("")
        notification_layout.addWidget(self.notification_label)
        self.notification_bar.setVisible(False)

        self.notification_timer = QTimer(self)
        self.notification_timer.setSingleShot(True)
        self.notification_timer.timeout.connect(lambda: self.notification_bar.setVisible(False))

        self.is_graph_ready = False
        self.graph_data_queue = []
        self.scheduler_manager = SchedulerManager()
        self.settings_window = SettingsWindow(self.scheduler_manager, self.config, self)
        self.settings_window.scheduler_status_updated.connect(self.update_thread_status_widget)

        self.setGeometry(100, 100, 1600, 900)

        self.loading_label = QLabel("Загрузка ядра Genesis v24.0... Пожалуйста, подождите (AI, DB, NLP).")
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.addWidget(self.loading_label)
        self.setCentralWidget(self.loading_widget)

        # Методы из миксинов (PanelsMixin, SignalsMixin)
        self._init_widgets()
        self.connect_signals()
        self.apply_style("Темная")

        self.status_update_timer = QTimer(self)
        self.status_update_timer.timeout.connect(self.update_scheduler_status_display)
        self.status_update_timer.start(60 * 1000)

        self.update_scheduler_status_display()

        self.update_info_timer = QTimer(self)
        self.update_info_timer.timeout.connect(self._update_version_and_monitoring_info)
        self.update_info_timer.start(30 * 1000)

        self.kg_enabled_checkbox.setChecked(self.trading_system.config.ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION)
        self.on_kg_toggle()

        self.start_heavy_initialization()

    # ========================================================================
    # Методы, НЕ вошедшие в миксины (остаются здесь)
    # ========================================================================

    @Slot(tuple)
    def on_heavy_initialization_error(self, error_info):
        exctype, value, traceback_str = error_info
        logger.critical(f"Критическая ошибка при запуске сервисов: {value}\n{traceback_str}")
        self.show_notification(f"КРИТИЧЕСКАЯ ОШИБКА: {value}", 0)
        self.loading_label.setText(f"КРИТИЧЕСКАЯ ОШИБКА: {value}. См. логи.")
        self.loading_label.setStyleSheet("color: red;")

    def show_notification(self, message: str, duration_ms: int = 3000):
        self.notification_label.setText(message)
        self.notification_bar.setVisible(True)
        if duration_ms > 0:
            self.notification_timer.start(duration_ms)
        else:
            self.notification_timer.stop()

    def start_heavy_initialization(self):
        self.update_status("Загрузка AI-моделей (может занять несколько минут)...", is_error=False)
        self.start_button.setEnabled(False)

        def worker():
            try:
                self.trading_system.core_system.initialize_heavy_components()
                self.bridge.status_updated.emit("AI-модели загружены. Система готова к запуску.", False)
                self.bridge.heavy_initialization_finished.emit()
                self.start_button.setEnabled(True)
            except Exception as e:
                logger.critical(f"Ошибка при инициализации: {e}", exc_info=True)
                self.bridge.status_updated.emit(f"ОШИБКА: {e}", True)
                self.start_button.setEnabled(True)

        init_thread = __import__("threading").Thread(target=worker, daemon=True)
        init_thread.start()

    def update_thread_status_widget(self, scheduler_summary: dict):
        status_text = "Планировщик:\n"
        for task_name, status in scheduler_summary.items():
            display_name = task_name.replace("Genesis", "")
            status_text += f"  {display_name}: {status}\n"

    def _handle_long_task_status(self, task_id: str, message: str, is_finished: bool):
        self.notification_timer.stop()
        self.notification_label.setText(message)

        if is_finished:
            self.notification_bar.setStyleSheet("background-color: #50fa7b; color: #282a36; border-radius: 4px;")
            self.notification_timer.start(7000)
        else:
            self.notification_bar.setStyleSheet("background-color: #f1fa8c; color: #282a36; border-radius: 4px;")

        self.notification_bar.setVisible(True)

    def _hide_notification_bar(self):
        self.notification_bar.setVisible(False)

    def apply_style(self, style_name: str):
        from src.gui.styles import DARK_STYLE, LIGHT_STYLE
        import pyqtgraph as pg

        if style_name == "Светлая":
            self.setStyleSheet(LIGHT_STYLE)
            pg.setConfigOption("background", "w")
            pg.setConfigOption("foreground", "k")
        elif style_name == "Темная":
            self.setStyleSheet(DARK_STYLE)
            pg.setConfigOption("background", "#282a36")
            pg.setConfigOption("foreground", "#f8f8f2")
        logger.info(f"Применен стиль: {style_name}")

    def closeEvent(self, event):
        logger.info("Получена команда на закрытие окна GUI.")

        reply = QMessageBox.question(
            self,
            "Подтверждение закрытия",
            "Вы действительно хотите закрыть торговую систему?\n\nВсе активные сделки будут сохранены, но мониторинг остановится.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.No:
            logger.info("Закрытие окна отменено пользователем.")
            event.ignore()
            return

        if self.trading_system.core_system.running:
            self.trading_system.core_system.initiate_graceful_shutdown()

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("Завершение работы...")
            msg.setInformativeText("Пожалуйста, подождите, пока все фоновые потоки будут остановлены.")
            msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
            msg.show()
            QApplication.processEvents()

            class JoinWorker(QRunnable):
                def __init__(self, core_system: "TradingSystem"):
                    super().__init__()
                    self.core_system: TradingSystem = core_system

                def run(self):
                    self.core_system.stop_event.set()
                    self.core_system._join_all_threads()

            join_worker = JoinWorker(self.trading_system.core_system)
            self.threadpool.start(join_worker)

            start_time = standard_time.time()

            while self.trading_system.core_system.running and (standard_time.time() - start_time < 15):
                QApplication.processEvents()
                standard_time.sleep(0.05)

            msg.hide()
            if self.trading_system.core_system.running:
                logger.critical("!!! ПРИНУДИТЕЛЬНОЕ ЗАВЕРШЕНИЕ: Не все потоки остановились за 15 секунд. !!!")
            else:
                logger.info("Все фоновые потоки остановлены. Закрываем приложение.")

        logger.info("=== ЗАКРЫТИЕ GUI ПОДТВЕРЖДЕНО ===")
        event.accept()

    def event(self, e):
        if e.type() == QEvent.Close:
            logger.warning(f"=== QEvent.Close ПОЛУЧЕН ===")
        elif e.type() == QEvent.Quit:
            logger.warning(f"=== QEvent.Quit ПОЛУЧЕН ===")
        elif e.type() == QEvent.Hide:
            logger.warning(f"=== QEvent.Hide ПОЛУЧЕН ===")
        return super().event(e)


# ===================================================================
# === Точка входа ===
# ===================================================================

_logger_configured = False


def qt_exception_hook(exctype, value, traceback_obj):
    import traceback
    tb_lines = traceback.format_exception(exctype, value, traceback_obj)
    tb_text = "".join(tb_lines)
    logger.critical(f"=== НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ В QT ===\n{tb_text}")
    logger.critical(f"Exception type: {exctype}")
    logger.critical(f"Exception value: {value}")


def main():
    sys.excepthook = qt_exception_hook
    os.environ["QT_WEBENGINE_DISABLE_SANDBOX"] = "1"
    app = QApplication(sys.argv)

    try:
        app_config = load_config()
        bridge = Bridge()

        PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
        sound_manager = SoundManager(project_root=PROJECT_ROOT)

        setup_qt_logging(bridge.log_message_added, app_config)
        trading_system_adapter = PySideTradingSystem(config=app_config, bridge=bridge, sound_manager=sound_manager)

        window = MainWindow(trading_system_adapter, app_config)

        app.aboutToQuit.connect(lambda: logger.info("=== QApplication.aboutToQuit СИГНАЛ ПОЛУЧЕН ==="))

        window.show()
        logger.info("=== ОКНО ПОКАЗАНО, РАЗМЕР: {}x{} ===".format(window.width(), window.height()))

        logger.info("=== GUI ЗАПУЩЕН УСПЕШНО, ВХОД В EVENT LOOP ===")
        exit_code = app.exec()
        logger.info(f"=== GUI EVENT LOOP ЗАВЕРШЕН, КОД: {exit_code} ===")
        sys.exit(exit_code)

    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА В MAIN GUI: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
