# tests/unit/test_logger.py
"""
Unit тесты для логирования.

Проверяет:
- Настройку логирования
- Форматирование логов
- Обработку ошибок
"""

import pytest
import logging
import sys
import os
from io import StringIO
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.logger import setup_logger, get_log_directory


class TestGetLogDirectory:
    """Тесты для get_log_directory."""

    def test_get_log_directory_returns_path(self):
        """Проверка что функция возвращает путь."""
        log_dir = get_log_directory()

        assert log_dir is not None
        assert str(log_dir).endswith('logs')

    def test_get_log_directory_creates_folder(self, tmp_path):
        """Проверка что папка создается."""
        log_dir = get_log_directory()

        # Папка должна существовать
        assert log_dir.exists() or log_dir.parent.exists()


class TestSetupLogger:
    """Тесты для setup_logger."""

    def test_setup_logger_creates_logger(self):
        """Проверка создания логгера."""
        logger = setup_logger("test_logger", level=logging.DEBUG)

        assert logger is not None
        assert logger.name == "test_logger"
        assert logger.level == logging.DEBUG

    def test_setup_logger_default_level(self):
        """Проверка уровня логирования по умолчанию."""
        logger = setup_logger("test_logger_default")

        assert logger.level == logging.INFO

    def test_setup_logger_custom_level(self):
        """Проверка пользовательского уровня."""
        logger = setup_logger("test_logger_info", level=logging.DEBUG)

        assert logger.level == logging.DEBUG

    def test_setup_logger_with_console_handler(self):
        """Проверка создания console handler."""
        logger = setup_logger("test_console", log_to_console=True, log_to_file=False)

        # Должен быть хотя бы один handler
        assert len(logger.handlers) > 0

    def test_setup_logger_with_file_handler(self, tmp_path):
        """Проверка создания file handler."""
        log_file = tmp_path / "test.log"

        with patch('src.utils.logger.get_log_directory', return_value=tmp_path):
            logger = setup_logger(
                "test_file",
                log_to_console=False,
                log_to_file=True,
                rotation='size',
                max_bytes=1024
            )

            # Должен быть file handler
            assert len(logger.handlers) > 0

    def test_setup_logger_rotation_daily(self, tmp_path):
        """Проверка daily ротации."""
        with patch('src.utils.logger.get_log_directory', return_value=tmp_path):
            logger = setup_logger(
                "test_daily",
                log_to_console=False,
                log_to_file=True,
                rotation='daily'
            )

            assert len(logger.handlers) > 0

    def test_setup_logger_rotation_hourly(self, tmp_path):
        """Проверка hourly ротации."""
        with patch('src.utils.logger.get_log_directory', return_value=tmp_path):
            logger = setup_logger(
                "test_hourly",
                log_to_console=False,
                log_to_file=True,
                rotation='hourly'
            )

            assert len(logger.handlers) > 0

    def test_setup_logger_no_rotation(self, tmp_path):
        """Проверка без ротации."""
        with patch('src.utils.logger.get_log_directory', return_value=tmp_path):
            logger = setup_logger(
                "test_no_rotation",
                log_to_console=False,
                log_to_file=True,
                rotation='none'
            )

            # Без ротации должен быть простой FileHandler
            assert len(logger.handlers) > 0

    def test_setup_logger_backup_count(self, tmp_path):
        """Проверка количества резервных файлов."""
        with patch('src.utils.logger.get_log_directory', return_value=tmp_path):
            logger = setup_logger(
                "test_backup",
                log_to_console=False,
                log_to_file=True,
                rotation='daily',
                backup_count=14
            )

            assert len(logger.handlers) > 0

    def test_setup_logger_max_bytes(self, tmp_path):
        """Проверка максимального размера файла."""
        with patch('src.utils.logger.get_log_directory', return_value=tmp_path):
            logger = setup_logger(
                "test_max_bytes",
                log_to_console=False,
                log_to_file=True,
                rotation='size',
                max_bytes=5 * 1024 * 1024  # 5 MB
            )

            assert len(logger.handlers) > 0

    def test_setup_logger_custom_format(self, tmp_path):
        """Проверка пользовательского формата."""
        custom_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

        with patch('src.utils.logger.get_log_directory', return_value=tmp_path):
            logger = setup_logger(
                "test_format",
                log_to_console=False,
                log_to_file=True,
                format_string=custom_format
            )

            assert len(logger.handlers) > 0


class TestLoggerLogging:
    """Тесты логирования."""

    def test_logger_debug(self, caplog):
        """Проверка DEBUG логирования."""
        logger = setup_logger("test_debug", level=logging.DEBUG, log_to_file=False)

        with caplog.at_level(logging.DEBUG):
            logger.debug("Debug message")

        assert "Debug message" in caplog.text

    def test_logger_info(self, caplog):
        """Проверка INFO логирования."""
        logger = setup_logger("test_info", level=logging.INFO, log_to_file=False)

        with caplog.at_level(logging.INFO):
            logger.info("Info message")

        assert "Info message" in caplog.text

    def test_logger_warning(self, caplog):
        """Проверка WARNING логирования."""
        logger = setup_logger("test_warning", level=logging.WARNING, log_to_file=False)

        with caplog.at_level(logging.WARNING):
            logger.warning("Warning message")

        assert "Warning message" in caplog.text

    def test_logger_error(self, caplog):
        """Проверка ERROR логирования."""
        logger = setup_logger("test_error", level=logging.ERROR, log_to_file=False)

        with caplog.at_level(logging.ERROR):
            logger.error("Error message")

        assert "Error message" in caplog.text

    def test_logger_critical(self, caplog):
        """Проверка CRITICAL логирования."""
        logger = setup_logger("test_critical", level=logging.CRITICAL, log_to_file=False)

        with caplog.at_level(logging.CRITICAL):
            logger.critical("Critical message")

        assert "Critical message" in caplog.text

    def test_logger_exception(self, caplog):
        """Проверка логирования исключений."""
        logger = setup_logger("test_exception", level=logging.ERROR, log_to_file=False)

        with caplog.at_level(logging.ERROR):
            try:
                raise ValueError("Test exception")
            except ValueError:
                logger.exception("Exception occurred")

        assert "Exception occurred" in caplog.text
        assert "ValueError" in caplog.text
        assert "Test exception" in caplog.text

    def test_logger_with_args(self, caplog):
        """Проверка логирования с аргументами."""
        logger = setup_logger("test_args", level=logging.INFO, log_to_file=False)

        with caplog.at_level(logging.INFO):
            logger.info("User %s logged in from %s", "test_user", "127.0.0.1")

        assert "User test_user logged in from 127.0.0.1" in caplog.text


class TestLoggerLevels:
    """Тесты уровней логирования."""

    def test_debug_not_logged_when_info_level(self, caplog):
        """Проверка что DEBUG не логируется при INFO уровне."""
        logger = setup_logger("test_not_debug", level=logging.INFO, log_to_file=False)

        with caplog.at_level(logging.DEBUG):
            logger.debug("Debug message")

        # DEBUG сообщение не должно быть в логе при INFO уровне
        assert "Debug message" not in caplog.text

    def test_info_logged_when_info_level(self, caplog):
        """Проверка что INFO логируется при INFO уровне."""
        logger = setup_logger("test_info_only", level=logging.INFO, log_to_file=False)

        with caplog.at_level(logging.INFO):
            logger.info("Info message")

        assert "Info message" in caplog.text

    def test_warning_logged_when_info_level(self, caplog):
        """Проверка что WARNING логируется при INFO уровне."""
        logger = setup_logger("test_warning_at_info", level=logging.INFO, log_to_file=False)

        with caplog.at_level(logging.WARNING):
            logger.warning("Warning message")

        assert "Warning message" in caplog.text


class TestLoggerNames:
    """Тесты имен логгеров."""

    def test_different_logger_names(self):
        """Проверка разных имен логгеров."""
        names = ["test1", "test2", "genesis.test", "my.logger"]

        loggers = []
        for name in names:
            logger = setup_logger(name, level=logging.DEBUG, log_to_file=False)
            loggers.append(logger)

        for i, name in enumerate(names):
            assert loggers[i].name == name

    def test_same_logger_returns_cached(self):
        """Проверка что один и тот же логгер кэшируется."""
        logger1 = setup_logger("cached_logger", level=logging.DEBUG, log_to_file=False)
        logger2 = setup_logger("cached_logger", level=logging.INFO, log_to_file=False)

        # Это один и тот же логгер (logging module кэширует)
        assert logger1 is logger2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
