# src/core/config_validator.py
"""
Валидатор конфигурации.

Проверяет и нормализует конфигурацию системы.
Предоставляет дефолтные значения и валидацию.
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Ошибка валидации конфигурации"""

    pass


class ConfigValidator:
    """
    Валидатор и нормализатор конфигурации.

    Пример использования:
        validator = ConfigValidator()
        is_valid, errors = validator.validate(config_dict)
        if not is_valid:
            raise ConfigValidationError("; ".join(errors))
    """

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Проверить конфигурацию.

        Args:
            config: Словарь конфигурации

        Returns:
            Tuple[bool, List[str]]: (валидна, список ошибок)
        """
        self.errors = []
        self.warnings = []

        # Проверка обязательных полей
        self._check_required_fields(config)

        # Проверка типов
        self._check_field_types(config)

        # Проверка диапазонов
        self._check_ranges(config)

        # Проверка путей
        self._check_paths(config)

        # Нормализация
        self._normalize_config(config)

        is_valid = len(self.errors) == 0

        if self.warnings:
            for warning in self.warnings:
                logger.warning(f"[Config] {warning}")

        if not is_valid:
            for error in self.errors:
                logger.error(f"[Config] {error}")

        return is_valid, self.errors

    def _check_required_fields(self, config: Dict[str, Any]) -> None:
        """Проверить обязательные поля"""
        required_fields = [
            "MT5_LOGIN",
            "MT5_PASSWORD",
            "MT5_SERVER",
            "MT5_PATH",
            "SYMBOLS_WHITELIST",
            "FEATURES_TO_USE",
        ]

        for field in required_fields:
            if field not in config:
                self.errors.append(f"Отсутствует обязательное поле: {field}")
            elif config[field] is None or config[field] == "":
                self.errors.append(f"Поле '{field}' не должно быть пустым")

    def _check_field_types(self, config: Dict[str, Any]) -> None:
        """Проверить типы полей"""
        type_checks = {
            "MT5_LOGIN": (int, str),  # Может быть строкой или числом
            "MT5_PASSWORD": str,
            "MT5_SERVER": str,
            "MT5_PATH": str,
            "SYMBOLS_WHITELIST": list,
            "FEATURES_TO_USE": list,
            "MAX_OPEN_POSITIONS": int,
            "RISK_PERCENTAGE": (int, float),
            "MAX_DAILY_DRAWDOWN_PERCENT": (int, float),
        }

        for field, expected_type in type_checks.items():
            if field in config:
                value = config[field]
                if not isinstance(value, expected_type):
                    self.errors.append(f"Поле '{field}' должно быть типа {expected_type}, " f"получено {type(value).__name__}")

    def _check_ranges(self, config: Dict[str, Any]) -> None:
        """Проверить диапазоны значений"""
        range_checks = {
            "RISK_PERCENTAGE": (0.1, 5.0, "Риск должен быть от 0.1% до 5.0%"),
            "MAX_DAILY_DRAWDOWN_PERCENT": (1.0, 20.0, "Дневная просадка от 1% до 20%"),
            "MAX_OPEN_POSITIONS": (1, 50, "Количество позиций от 1 до 50"),
            "TRADE_INTERVAL_SECONDS": (10, 300, "Интервал торговли от 10с до 300с"),
        }

        for field, (min_val, max_val, message) in range_checks.items():
            if field in config:
                value = config[field]
                if not (min_val <= value <= max_val):
                    self.warnings.append(
                        f"{message}. Текущее значение: {value}. " f"Используется безопасное значение по умолчанию."
                    )

    def _check_paths(self, config: Dict[str, Any]) -> None:
        """Проверить пути к файлам и директориям"""
        path_fields = ["MT5_PATH", "DATABASE_FOLDER"]

        for field in path_fields:
            if field in config:
                path = Path(config[field])

                # Для MT5_PATH требуем существование файла
                if field == "MT5_PATH":
                    if not path.exists():
                        self.errors.append(f"MT5 терминал не найден по пути: {path}")
                    elif not path.is_file():
                        self.errors.append(f"MT5_PATH должен указывать на файл, а не директорию")

                # Для директорий создаем если не существуют
                elif field == "DATABASE_FOLDER":
                    if not path.exists():
                        self.warnings.append(f"Директория БД не найдена: {path}. Будет создана.")
                        try:
                            path.mkdir(parents=True, exist_ok=True)
                        except Exception as e:
                            self.errors.append(f"Не удалось создать директорию БД: {e}")

    def _normalize_config(self, config: Dict[str, Any]) -> None:
        """Нормализовать конфигурацию (привести к безопасным значениям)"""
        # Нормализация риска
        if "RISK_PERCENTAGE" in config:
            risk = config["RISK_PERCENTAGE"]
            if risk < 0.1:
                config["RISK_PERCENTAGE"] = 0.1
                self.warnings.append("Риск увеличен до минимального: 0.1%")
            elif risk > 5.0:
                config["RISK_PERCENTAGE"] = 5.0
                self.warnings.append("Риск уменьшен до максимального: 5.0%")

        # Нормализация дневной просадки
        if "MAX_DAILY_DRAWDOWN_PERCENT" in config:
            dd = config["MAX_DAILY_DRAWDOWN_PERCENT"]
            if dd < 1.0:
                config["MAX_DAILY_DRAWDOWN_PERCENT"] = 1.0
                self.warnings.append("Дневная просадка увеличена до минимальной: 1.0%")
            elif dd > 20.0:
                config["MAX_DAILY_DRAWDOWN_PERCENT"] = 20.0
                self.warnings.append("Дневная просадка уменьшена до максимальной: 20.0%")

        # Нормализация количества позиций
        if "MAX_OPEN_POSITIONS" in config:
            positions = config["MAX_OPEN_POSITIONS"]
            if positions < 1:
                config["MAX_OPEN_POSITIONS"] = 1
                self.warnings.append("Количество позиций увеличено до минимального: 1")
            elif positions > 50:
                config["MAX_OPEN_POSITIONS"] = 50
                self.warnings.append("Количество позиций уменьшено до максимального: 50")

        # Преобразование MT5_LOGIN в строку (если было числом)
        if "MT5_LOGIN" in config and isinstance(config["MT5_LOGIN"], int):
            config["MT5_LOGIN"] = str(config["MT5_LOGIN"])

    def get_safe_defaults(self) -> Dict[str, Any]:
        """
        Получить безопасные значения по умолчанию.

        Returns:
            Dict[str, Any]: Словарь с безопасными значениями
        """
        return {
            # Торговля
            "RISK_PERCENTAGE": 0.5,
            "MAX_OPEN_POSITIONS": 5,
            "MAX_DAILY_DRAWDOWN_PERCENT": 5.0,
            "TRADE_INTERVAL_SECONDS": 60,
            # Символы
            "SYMBOLS_WHITELIST": ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "USDCHF", "NZDUSD", "EURJPY"],
            # Признаки
            "FEATURES_TO_USE": ["close", "tick_volume", "ATR_14", "RSI_14", "BB_WIDTH", "STOCHk_14_3_3", "MACD_12_26_9"],
            # Таймфреймы
            "TIMEFRAMES": ["H1"],
            # Ограничения
            "MAX_PORTFOLIO_VAR_PERCENT": 3.0,
            "CORRELATION_THRESHOLD": 0.85,
            # Базы данных
            "DATABASE_FOLDER": "database",
        }

    def validate_and_fix(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Проверить и исправить конфигурацию.

        Args:
            config: Исходная конфигурация

        Returns:
            Tuple[Dict[str, Any], List[str]]: (исправленная конфигурация, предупреждения)
        """
        # Получаем дефолтные значения
        defaults = self.get_safe_defaults()

        # Merge с приоритетом пользовательских значений
        fixed_config = {**defaults, **config}

        # Валидируем
        is_valid, errors = self.validate(fixed_config)

        if not is_valid:
            # Если есть критические ошибки, используем дефолты
            logger.error("Критические ошибки в конфигурации. Используются значения по умолчанию.")
            fixed_config = defaults
            self.errors = []  # Очищаем ошибки после сброса

        return fixed_config, self.warnings


def validate_config_file(config_path: Path) -> Tuple[bool, List[str]]:
    """
    Проверить файл конфигурации.

    Args:
        config_path: Путь к файлу конфигурации

    Returns:
        Tuple[bool, List[str]]: (валидна, список ошибок)
    """
    import json

    if not config_path.exists():
        return False, [f"Файл конфигурации не найден: {config_path}"]

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            # Удаляем комментарии перед парсингом
            content = "".join(line for line in f if not line.strip().startswith("//"))
            config = json.loads(content)

        validator = ConfigValidator()
        return validator.validate(config)

    except json.JSONDecodeError as e:
        return False, [f"Ошибка парсинга JSON: {e}"]
    except Exception as e:
        return False, [f"Ошибка чтения файла: {e}"]
