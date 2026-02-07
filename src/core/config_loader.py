# src/core/config_loader.py
import os
import json
import logging
from dotenv import load_dotenv
from pathlib import Path
from pydantic import ValidationError

from src.core.config_models import Settings

logger = logging.getLogger(__name__)

def load_config() -> Settings:
    """
    Загружает конфигурацию из .env и settings.json,
    валидирует и возвращает строго типизированный объект Settings.
    """
    config_dict = {}
    project_root = Path(__file__).parent.parent.parent

    # 1. Загрузка из settings.json
    settings_path = project_root / 'configs' / 'settings.json'
    if settings_path.exists():
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                # Удаляем комментарии перед парсингом
                content = "".join(line for line in f if not line.strip().startswith("//"))
                config_dict.update(json.loads(content))
            logger.info(f"Конфигурация загружена из {settings_path}")
        except Exception as e:
            logger.error(f"Критическая ошибка чтения {settings_path}: {e}")
            raise  # Прерываем выполнение, если основной конфиг не читается
    else:
        logger.critical(f"Файл конфигурации {settings_path} не найден. Работа невозможна.")
        raise FileNotFoundError(f"Файл конфигурации {settings_path} не найден.")

    # 2. Загрузка и переопределение из .env
    env_path = project_root / 'configs' / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
        logger.info(f"Переменные окружения загружены из {env_path}")
        # Добавляем переменные из os.environ в наш словарь
        for key, value in os.environ.items():
            # Pydantic сам обработает приведение типов, так что просто добавляем
            config_dict[key] = value
    else:
        logger.warning(f"Файл {env_path} не найден.")

    # 3. Валидация и создание объекта Settings
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
