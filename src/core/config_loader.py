# src/core/config_loader.py
"""
Модуль загрузки конфигурации с поддержкой шифрования чувствительных данных.

Приоритет загрузки (от высшего к низшему):
1. Переменные окружения (.env)
2. settings.json
3. Значения по умолчанию
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from src.core.config_models import Settings
from src.core.secure_config import SecureConfigLoader

logger = logging.getLogger(__name__)


def _normalize_path(path_value: str, project_root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        return (project_root / path).resolve()
    return path


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".write_test"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            test_file.unlink()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _select_writable_dir(primary: Path, fallback: Path, label: str) -> Path:
    if _is_writable_dir(primary):
        return primary
    logger.warning(f"{label} недоступен для записи: {primary}. Переключаюсь на {fallback}")
    if _is_writable_dir(fallback):
        return fallback
    logger.error(f"{label} также недоступен для записи: {fallback}. Оставляю исходный путь: {primary}")
    return primary


def _get_default_settings_dict() -> dict:
    """Возвращает словарь с настройками по умолчанию."""
    return {
        "SYMBOLS_WHITELIST": [
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "USDCAD",
            "AUDUSD",
            "USDCHF",
            "NZDUSD",
            "EURJPY",
            "GBPJPY",
            "EURGBP",
            "AUDJPY",
            "XAUUSD",
            "XAGUSD",
            "EURCHF",
            "CADJPY",
            "AUDNZD",
            "GBPAUD",
            "BITCOIN",
        ],
        "FEATURES_TO_USE": [
            "close",
            "tick_volume",
            "ATR_14",
            "RSI_14",
            "BB_WIDTH",
            "STOCHk_14_3_3",
            "MACD_12_26_9",
            "EMA_50",
            "EMA_200",
            "ADX_14",
            "ATR_NORM",
            "DIST_EMA_50",
            "DIST_EMA_200",
            "SKEW_60",
            "KURT_60",
            "VOLA_60",
            "hour_sin",
            "hour_cos",
            "day_of_week_sin",
            "day_of_week_cos",
            "KG_CB_SENTIMENT",
            "KG_INFLATION_SURPRISE",
        ],
        "TRADE_INTERVAL_SECONDS": 60,
        "MAX_OPEN_POSITIONS": 5,
        "RISK_PER_TRADE": 1.0,
        "CONSENSUS_THRESHOLD": 0.05,
        "MT5_LOGIN": 0,
        "MT5_PASSWORD": "",
        "MT5_SERVER": "",
        "MT5_PATH": "",
        "DATABASE_FOLDER": "database",
        "vector_db": {"enabled": True, "path": "database/vector_db", "embedding_model": "all-MiniLM-L6-v2"},
        "CONSENSUS_WEIGHTS": {"ai_forecast": 0.5, "classic_strategies": 0.3, "sentiment_kg": 0.1, "on_chain_data": 0.1},
        "strategies": {
            "breakout": {"window": 15},
            "mean_reversion": {"window": 50, "std_dev_multiplier": 1.9, "confirmation_buffer_std_dev_fraction": 0.05},
            "ma_crossover": {
                "timeframe_params": {
                    "default": {"short_window": 15, "long_window": 35},
                    "low": {"short_window": 10, "long_window": 25},
                    "high": {"short_window": 50, "long_window": 200},
                }
            },
        },
    }


def load_config() -> Settings:
    """
    Загружает конфигурацию из .env и settings.json,
    валидирует и возвращает строго типизированный объект Settings.
    При первом запуске создает settings.json с настройками по умолчанию.

    Returns:
        Settings: Валидированная конфигурация

    Raises:
        ValueError: Если отсутствуют обязательные переменные окружения
        ValidationError: Если конфигурация не прошла валидацию Pydantic
    """
    config_dict = {}
    project_root = Path(__file__).parent.parent.parent

    # 1. Загрузка из settings.json (только нечувствительные данные)
    settings_path = project_root / "configs" / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                # Удаляем комментарии перед парсингом
                content = "".join(line for line in f if not line.strip().startswith("//"))
                config_dict.update(json.loads(content))
            logger.info(f"Конфигурация загружена из {settings_path}")
        except Exception as e:
            logger.error(f"Критическая ошибка чтения {settings_path}: {e}")
            raise  # Прерываем выполнение, если основной конфиг не читается
    else:
        # Создаем settings.json с настройками по умолчанию
        logger.warning(f"Файл конфигурации {settings_path} не найден. Создаю с настройками по умолчанию...")
        try:
            default_settings = _get_default_settings_dict()
            # Создаем директорию если не существует
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(default_settings, f, indent=4, ensure_ascii=False)
            logger.info(f"Создан файл настроек: {settings_path}")
            logger.warning("ВНИМАНИЕ: Отредактируйте settings.json и укажите ваш MT5 путь, логин и пароль!")
            config_dict.update(default_settings)
        except Exception as e:
            logger.error(f"Не удалось создать файл настроек: {e}")
            raise

    # 2. Загрузка и переопределение из .env
    env_path = project_root / "configs" / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
        logger.info(f"Переменные окружения загружены из {env_path}")
        # Добавляем переменные из os.environ в наш словарь
        for key, value in os.environ.items():
            # Pydantic сам обработает приведение типов, так что просто добавляем
            config_dict[key] = value
    else:
        logger.warning(f"Файл {env_path} не найден. Рекомендуется создать .env файл для безопасного хранения учётных данных.")

    # 3. Инициализация безопасного загрузчика
    secure_loader = SecureConfigLoader()

    # 4. Проверка наличия обязательных учётных данных MT5
    try:
        mt5_creds = secure_loader.load_mt5_credentials()
        logger.info("Учётные данные MT5 загружены и расшифрованы")

        # Обновляем конфигурацию расшифрованными данными
        config_dict["MT5_LOGIN"] = str(mt5_creds["login"])
        config_dict["MT5_PASSWORD"] = mt5_creds["password"]
        config_dict["MT5_SERVER"] = mt5_creds["server"]
        config_dict["MT5_PATH"] = mt5_creds["path"]

    except ValueError as e:
        logger.warning(f"Учётные данные MT5 не загружены: {e}")
        # Не прерываем выполнение, позволяя системе работать в режиме без MT5

    # 4.5. Уточнение путей хранения (с проверкой записи)
    default_db = project_root / "database"
    raw_db = config_dict.get("DATABASE_FOLDER", "database")
    db_path = _normalize_path(str(raw_db), project_root)
    db_path = _select_writable_dir(db_path, default_db, "DATABASE_FOLDER")
    config_dict["DATABASE_FOLDER"] = str(db_path)

    raw_logs = config_dict.get("LOGS_FOLDER")
    if raw_logs:
        logs_path = _normalize_path(str(raw_logs), project_root)
    else:
        logs_path = db_path / "logs"
    logs_fallback = db_path / "logs"
    logs_path = _select_writable_dir(logs_path, logs_fallback, "LOGS_FOLDER")
    config_dict["LOGS_FOLDER"] = str(logs_path)

    # 5. Валидация и создание объекта Settings
    try:
        settings = Settings(**config_dict)
        logger.info("Конфигурация успешно прошла валидацию Pydantic.")
        return settings
    except ValidationError as e:
        logger.critical(f"ОШИБКА ВАЛИДАЦИИ КОНФИГУРАЦИИ:\n{e}")
        # Выводим детальную информацию по каждой ошибке
        for error in e.errors():
            logger.error(f"  - Поле: {'.'.join(map(str, error['loc']))}, Ошибка: {error['msg']}")
        raise  # Прерываем выполнение при невалидном конфиге
