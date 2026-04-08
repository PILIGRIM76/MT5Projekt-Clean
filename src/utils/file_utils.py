"""
Утилиты для атомарной записи файлов.

Предотвращает повреждение конфигов при сбое процесса/диска:
1. Пишем во временный файл
2. Атомарно заменяем оригинал через os.replace()
3. При ошибке — временный файл удаляется, оригинал intact
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)


def save_text_atomic(filepath: Union[str, Path], content: str, encoding: str = "utf-8") -> None:
    """
    Атомарная запись текстового файла: tmp → rename.
    
    Args:
        filepath: Путь к файлу
        content: Содержимое для записи
        encoding: Кодировка (по умолчанию utf-8)
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Создаём временный файл в той же директории (для атомарного rename)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, suffix=".tmp", prefix=f".{path.name}."
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        # Атомарная замена (работает на POSIX и Windows)
        os.replace(tmp_path, str(path))
        logger.debug(f"💾 Atomic write: {path}")
    except Exception:
        # Очистка временного файла при ошибке
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        logger.error(f"❌ Atomic write failed: {path}", exc_info=True)
        raise


def save_json_atomic(filepath: Union[str, Path], data: Any, indent: int = 2, **json_kwargs) -> None:
    """
    Атомарная запись JSON-конфига.
    
    Args:
        filepath: Путь к JSON файлу
        data: Данные для сериализации
        indent: Отступ для форматирования
        **json_kwargs: Дополнительные аргументы для json.dumps
    """
    content = json.dumps(data, indent=indent, ensure_ascii=False, **json_kwargs)
    save_text_atomic(filepath, content + "\n")


def save_env_atomic(filepath: Union[str, Path], env_dict: Dict[str, str]) -> None:
    """
    Атомарная запись .env файла.
    
    Args:
        filepath: Путь к .env файлу
        env_dict: Словарь {KEY: VALUE} для записи
    """
    lines = []
    for k, v in env_dict.items():
        if v is not None:
            # Экранируем значения с пробелами
            if " " in str(v) or not str(v):
                lines.append(f'{k}="{v}"')
            else:
                lines.append(f"{k}={v}")
    
    content = "\n".join(lines) + "\n"
    save_text_atomic(filepath, content)


def read_json_safe(filepath: Union[str, Path], default: Any = None) -> Any:
    """
    Безопасное чтение JSON с fallback на default при ошибке.
    
    Args:
        filepath: Путь к JSON файлу
        default: Значение по умолчанию при ошибке чтения
        
    Returns:
        Распарсенные данные или default
    """
    path = Path(filepath)
    if not path.exists():
        return default
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"⚠️ Failed to read JSON {filepath}: {e}")
        return default
