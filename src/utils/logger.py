# -*- coding: utf-8 -*-
"""
Модуль логирования для системы Genesis Trading
Обеспечивает централизованное логирование с ротацией файлов

Поддержка:
- Текстовое логирование (стандартное)
- JSON логирование (для ELK/Loki)
- Ротация по времени и размеру
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict


def get_log_directory():
    """Получить директорию для логов"""
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent.parent.parent

    log_dir = base_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


class JSONFormatter(logging.Formatter):
    """
    JSON форматтер для логирования.

    Используется для отправки логов в ELK/Loki.

    Example:
        {
            "timestamp": "2026-03-31T12:00:00.000Z",
            "level": "INFO",
            "logger": "genesis",
            "message": "System started",
            "module": "trading_system",
            "function": "start",
            "line": 123,
            "thread": "MainThread",
            "extra_data": {...}
        }
    """

    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record: logging.LogRecord) -> str:
        """Форматирование записи в JSON."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.threadName,
            "process": record.process,
        }

        # Добавляем exception если есть
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Добавляем extra данные если есть
        if self.include_extra:
            extra_data = {
                key: value
                for key, value in record.__dict__.items()
                if key
                not in [
                    "name",
                    "msg",
                    "args",
                    "created",
                    "filename",
                    "funcName",
                    "levelname",
                    "levelno",
                    "lineno",
                    "module",
                    "msecs",
                    "pathname",
                    "process",
                    "processName",
                    "relativeCreated",
                    "stack_info",
                    "exc_info",
                    "exc_text",
                    "thread",
                    "threadName",
                    "message",
                    "asctime",
                    "asctime_ms",
                ]
                and not key.startswith("_")
            }
            if extra_data:
                log_data["extra"] = extra_data

        return json.dumps(log_data, ensure_ascii=False, default=str)


def setup_logger(
    name: str = "genesis",
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_to_console: bool = True,
    rotation: str = "daily",
    backup_count: int = 7,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB для размерной ротации
    format_string: str = None,
    json_format: bool = False,  # Новый параметр для JSON логирования
) -> logging.Logger:
    """
    Настроить и вернуть логгер с ротацией файлов

    Args:
        name: Имя логгера
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Писать логи в файл
        log_to_console: Выводить логи в консоль
        rotation: Тип ротации ('daily', 'hourly', 'size', 'none')
        backup_count: Количество резервных файлов
        max_bytes: Максимальный размер файла (для размерной ротации)
        format_string: Формат сообщений логов
        json_format: Использовать JSON формат (для ELK/Loki)

    Returns:
        Настроенный логгер
    """
    if format_string is None:
        format_string = "%(asctime)s | %(levelname)-8s | " "%(name)s | %(funcName)s:%(lineno)d | " "%(message)s"

    # Выбираем форматтер
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Очистить существующие обработчики
    if logger.handlers:
        logger.handlers.clear()

    # Консольный обработчик
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # Файловый обработчик с ротацией
    if log_to_file:
        log_dir = get_log_directory()

        if rotation == "daily":
            log_file = log_dir / f"{name}.log"
            file_handler = TimedRotatingFileHandler(log_file, when="D", interval=1, backupCount=backup_count, encoding="utf-8")
            file_handler.suffix = ".%Y-%m-%d"
        elif rotation == "hourly":
            log_file = log_dir / f"{name}.log"
            file_handler = TimedRotatingFileHandler(log_file, when="H", interval=1, backupCount=backup_count, encoding="utf-8")
            file_handler.suffix = ".%Y-%m-%d_%H-%M"
        elif rotation == "size":
            log_file = log_dir / f"{name}.log"
            file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        else:  # rotation == 'none'
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = log_dir / f"{name}_{timestamp}.log"
            file_handler = logging.FileHandler(log_file, encoding="utf-8")

        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Обработчик критических ошибок (всегда пишет в отдельный файл)
    error_log_dir = get_log_directory()
    error_file = error_log_dir / f"{name}_errors.log"
    error_handler = RotatingFileHandler(error_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    Получить существующий логгер или создать новый с настройками по умолчанию

    Args:
        name: Имя логгера (если None, вернётся корневой логгер)

    Returns:
        Логгер
    """
    if name is None:
        return logging.getLogger()

    logger = logging.getLogger(name)

    # Если логгер ещё не настроен, настроить его
    if not logger.handlers:
        return setup_logger(name)

    return logger


def set_log_level(level: int, name: str = "genesis") -> None:
    """
    Установить уровень логирования

    Args:
        level: Уровень логирования
        name: Имя логгера
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    for handler in logger.handlers:
        handler.setLevel(level)


# Уровни логирования для удобства
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


# Создать логгер по умолчанию
default_logger = setup_logger(
    name="genesis", level=logging.INFO, log_to_file=True, log_to_console=True, rotation="daily", backup_count=7
)
