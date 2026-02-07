# src/gui/sound_manager.py
import os
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class SoundManager:
    def __init__(self, project_root: str):
        self.sounds: Dict[str, QSoundEffect] = {}
        self.project_root = project_root
        self.sound_files = {
            "trade_open": "trade_open.mp3",
            "error": "error.mp3",
            "system_start": "system_start.mp3",
            "system_stop": "system_stop.mp3",
            "alert": "alert.mp3"
        }
        self._load_sounds()

    def _load_sounds(self):
        """Загружает все звуковые файлы в память."""
        # --- ИЗМЕНЕНИЕ: Используем переданный project_root для построения пути ---
        # Это делает путь абсолютно надежным, независимо от того, откуда запускается скрипт.
        sounds_dir = os.path.join(self.project_root, 'assets', 'sounds')

        if not os.path.isdir(sounds_dir):
            logger.warning(f"Папка со звуками не найдена по пути: {sounds_dir}. Звуковые эффекты будут отключены.")
            return

        for key, filename in self.sound_files.items():
            path = os.path.join(sounds_dir, filename)
            if os.path.exists(path):
                sound_effect = QSoundEffect()
                sound_effect.setSource(QUrl.fromLocalFile(path))
                sound_effect.setVolume(0.7)
                self.sounds[key] = sound_effect
                logger.info(f"Звук '{key}' успешно загружен из {filename}")
            else:
                logger.warning(f"Звуковой файл {filename} не найден для события '{key}'.")

    def play(self, sound_key: str):
        """Воспроизводит звук по его ключу."""
        if sound_key in self.sounds:
            self.sounds[sound_key].play()
        else:
            logger.debug(f"Попытка воспроизвести несуществующий звук: {sound_key}")

    def set_volume(self, volume: float):
        """Устанавливает громкость для всех звуков (от 0.0 до 1.0)."""
        for sound in self.sounds.values():
            sound.setVolume(volume)