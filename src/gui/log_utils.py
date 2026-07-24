# src/gui/log_utils.py

import logging
import os
from typing import Optional
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
    def __init__(self, log_signal_emitter, light_mode: bool = False):
        super().__init__()
        self.log_signal_emitter = log_signal_emitter
        self.light_mode = light_mode

        # Цвета для тёмной темы (Dracula)
        self.dark_colors = {
            logging.DEBUG: QColor("#6272a4"),
            logging.INFO: QColor("#f8f8f2"),
            logging.WARNING: QColor("#f1fa8c"),
            logging.ERROR: QColor("#ff5555"),
            logging.CRITICAL: QColor("#ffb86c"),
        }

        # Цвета для светлой темы (читаемые на белом фоне)
        self.light_colors = {
            logging.DEBUG: QColor("#4B5563"),  # Тёмно-серый
            logging.INFO: QColor("#1E293B"),  # Почти чёрный
            logging.WARNING: QColor("#B45309"),  # Тёмно-оранжевый
            logging.ERROR: QColor("#DC2626"),  # Красный
            logging.CRITICAL: QColor("#991B1B"),  # Тёмно-красный
        }

        self.level_colors = self.light_colors if light_mode else self.dark_colors

    def set_light_mode(self, enabled: bool) -> None:
        """Переключает режим цветов для светлой/тёмной темы."""
        self.light_mode = enabled
        self.level_colors = self.light_colors if enabled else self.dark_colors

    def emit(self, record):
        try:
            msg = self.format(record)
            color = self.level_colors.get(record.levelno, QColor("#1E293B"))
            # --- ИСПРАВЛЕНИЕ: Проверка существования эмиттера ---
            if self.log_signal_emitter:
                self.log_signal_emitter.emit(msg, color)
        except RuntimeError:
            # Объект C++ уже удален (при закрытии)
            pass
        except Exception:
            pass


def setup_qt_logging(bridge_log_signal, config: Settings, light_mode: bool = False):
    """
    Централизованно настраивает корневой логгер для вывода в консоль, в GUI и в файл.
    Гарантирует, что настройка произойдет только один раз.

    Args:
        bridge_log_signal: Сигнал для отправки логов в GUI
        config: Конфигурация приложения
        light_mode: Если True, использует читаемые цвета для светлой темы
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
    qt_log_handler = QtLogHandler(bridge_log_signal, light_mode=light_mode)
    qt_log_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(qt_log_handler)

    # +++ НАЧАЛО ИЗМЕНЕНИЙ +++
    # 3. Настраиваем обработчик для записи в файл с ротацией
    def _resolve_logs_path() -> Optional[Path]:
        candidates = []
        # Явно заданный путь
        if hasattr(config, "LOGS_FOLDER") and config.LOGS_FOLDER:
            candidates.append(Path(config.LOGS_FOLDER))
        # По умолчанию: DATABASE_FOLDER/logs
        if hasattr(config, "DATABASE_FOLDER") and config.DATABASE_FOLDER:
            candidates.append(Path(config.DATABASE_FOLDER) / "logs")
        # Fallback: локальные логи в репозитории/рабочей директории
        candidates.append(Path.cwd() / "logs")
        candidates.append(Path(__file__).resolve().parents[2] / "logs")

        for path in candidates:
            try:
                path.mkdir(parents=True, exist_ok=True)
                test_file = path / ".write_test"
                with open(test_file, "a", encoding="utf-8") as f:
                    f.write("")
                try:
                    test_file.unlink()
                except Exception:
                    pass
                return path
            except Exception:
                continue
        return None

    try:
        logs_path = _resolve_logs_path()
        if not logs_path:
            logging.warning("Не удалось выбрать доступную директорию для логов. Файловое логирование отключено.")
        else:
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
