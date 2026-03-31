# src/core/config_writer.py
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_config(new_settings: dict):
    """
    Безопасно обновляет файл settings.json.
    Читает существующий файл, обновляет значения из new_settings
    и записывает всю структуру обратно.
    """
    project_root = Path(__file__).parent.parent.parent
    settings_path = project_root / "configs" / "settings.json"

    try:
        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as f:
                content = "".join(line for line in f if not line.strip().startswith("//"))
                current_config = json.loads(content)
        else:
            current_config = {}

        current_config.update(new_settings)

        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(current_config, f, indent=2, ensure_ascii=False)

        logger.warning(f"Файл конфигурации '{settings_path}' был программно обновлен.")
        return True

    except Exception as e:
        logger.error(f"Не удалось записать в settings.json: {e}")
        return False
