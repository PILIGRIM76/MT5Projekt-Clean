# src/gui/log_utils.py

import logging
import os
from logging.handlers import RotatingFileHandler  # +++ ИЗМЕНЕНИЕ: Импортируем нужный обработчик
from pathlib import Path  # +++ ИЗМЕНЕНИЕ: Импортируем Path

from PySide6.QtGui import QColor

# +++ ИЗМЕНЕНИЕ: Импортируем модель конфига для проверки типов +++
from src.core.config_models import Settings

# Глобальный флаг, чтобы гарантировать, что настройка произойдет только один раз
_logger_configured = False


class ColorFormatter(logging.Formatter):
    """
    Пользовательский Formatter для добавления цвета в консольные логи.
    """

    # Определяем цвета
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    # Формат для каждого уровня лога
    FORMATS = {
        logging.DEBUG: GREY + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + RESET,
        logging.INFO: GREY + "%(asctime)s - %(levelname)s - %(message)s" + RESET,
        logging.WARNING: YELLOW + "%(asctime)s - %(levelname)s - %(message)s" + RESET,
        logging.ERROR: RED + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + RESET,
        logging.CRITICAL: BOLD_RED + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


class QtLogHandler(logging.Handler):
    def __init__(self, log_signal_emitter):
        super().__init__()
        self.log_signal_emitter = log_signal_emitter
        self.level_colors = {
            logging.DEBUG: QColor("#6272a4"),
            logging.INFO: QColor("#f8f8f2"),
            logging.WARNING: QColor("#f1fa8c"),
            logging.ERROR: QColor("#ff5555"),
            logging.CRITICAL: QColor("#ffb86c"),
        }

    def emit(self, record):
        try:
            msg = self.format(record)
            color = self.level_colors.get(record.levelno, QColor("#f8f8f2"))
            # --- ИСПРАВЛЕНИЕ: Проверка существования эмиттера ---
            if self.log_signal_emitter:
                self.log_signal_emitter.emit(msg, color)
        except RuntimeError:
            # Объект C++ уже удален (при закрытии)
            pass
        except Exception:
            pass


def setup_qt_logging(bridge_log_signal, config: Settings):
    """
    Централизованно настраивает корневой логгер для вывода в консоль, в GUI и в файл.
    Гарантирует, что настройка произойдет только один раз.
    """

    global _logger_configured
    if _logger_configured:
        return

    # Устанавливаем кодировку UTF-8 для логов на Windows
    import locale
    import sys

    try:
        locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
    except locale.Error:
        pass  # Windows может не поддерживать эту локаль

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 1. Настраиваем цветной обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColorFormatter())
    # Устанавливаем utf-8 для корректного отображения кириллицы в Windows
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    root_logger.addHandler(console_handler)

    # 2. Настраиваем обработчик для GUI
    qt_log_handler = QtLogHandler(bridge_log_signal)
    qt_log_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(qt_log_handler)

    # +++ НАЧАЛО ИЗМЕНЕНИЙ +++
    # 3. Настраиваем обработчик для записи в файл с ротацией
    try:
        # Создаем папку для логов, если ее нет
        logs_path = Path(config.DATABASE_FOLDER) / "logs"
        logs_path.mkdir(parents=True, exist_ok=True)
        log_file_path = logs_path / "genesis_system.log"

        # Создаем обработчик, который будет создавать до 5 файлов логов по 5 МБ каждый
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            delay=True,  # Откладываем открытие файла до первой записи
        )
        # Устанавливаем более детальный формат для файла
        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

        logging.info(f"Логирование в файл настроено. Файлы будут сохраняться в: {log_file_path}")

    except Exception as e:
        logging.error(f"Не удалось настроить логирование в файл: {e}")
    # +++ КОНЕЦ ИЗМЕНЕНИЙ +++

    # 4. Устанавливаем уровни для "шумных" библиотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("shap").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _logger_configured = True
    logging.info("Система логирования успешно инициализирована.")
