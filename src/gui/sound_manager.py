# src/gui/sound_manager.py
import logging
import os
import sys
import winsound
from typing import Dict, Optional

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect

logger = logging.getLogger(__name__)


class SoundManager:
    """
    Менеджер звуков с fallback на winsound если QSoundEffect не работает.

    На Windows 10/11 QSoundEffect часто не может декодировать MP3.
    В этом случае автоматически используется winsound.PlaySound.
    """

    def __init__(self, project_root: str):
        self.sounds: Dict[str, QSoundEffect] = {}
        self.sound_paths: Dict[str, str] = {}  # Для winsound fallback
        self.project_root = project_root
        self.use_winsound = False  # Будет установлено после проверки
        self.sound_files = {
            "trade_open": "trade_open.mp3",
            "error": "error.mp3",
            "system_start": "system_start.mp3",
            "system_stop": "system_stop.mp3",
            "alert": "alert.mp3",
        }
        self._load_sounds()

    def _load_sounds(self):
        """Загружает все звуковые файлы в память."""
        sounds_dir = os.path.join(self.project_root, "assets", "sounds")

        if not os.path.isdir(sounds_dir):
            logger.warning(f"Папка со звуками не найдена: {sounds_dir}. Звуки отключены.")
            return

        sounds_loaded_count = 0
        sounds_failed_count = 0

        for key, filename in self.sound_files.items():
            path = os.path.join(sounds_dir, filename)
            if not os.path.exists(path):
                logger.warning(f"Звуковой файл {filename} не найден для '{key}'.")
                continue

            # Пробуем QSoundEffect
            sound_effect = QSoundEffect()
            sound_effect.setSource(QUrl.fromLocalFile(path))
            sound_effect.setVolume(0.7)

            # Проверяем статус загрузки
            if sound_effect.status() == QSoundEffect.Status.Ready:
                self.sounds[key] = sound_effect
                self.sound_paths[key] = path
                sounds_loaded_count += 1
                logger.debug(f"Звук '{key}' загружен через QSoundEffect")
            else:
                # Fallback на winsound
                logger.warning(f"QSoundEffect не смог загрузить '{key}' ({filename}). " f"Будет использован winsound.")
                self.sound_paths[key] = path
                self.use_winsound = True

        # Итоговое логирование
        if sounds_failed_count == 0 and sounds_loaded_count > 0:
            logger.info(f"✅ Все {sounds_loaded_count} звуков загружены через QSoundEffect")
        elif self.use_winsound:
            logger.info(f"⚠ {sounds_loaded_count} звуков через QSoundEffect, " f"остальные через winsound")

    def play(self, sound_key: str):
        """Воспроизводит звук по его ключу."""
        if sound_key not in self.sound_paths:
            logger.debug(f"Звук '{sound_key}' не найден.")
            return

        # Если хотя бы один звук не загрузился — используем winsound для всех
        if self.use_winsound:
            self._play_winsound(sound_key)
        else:
            self._play_qt(sound_key)

    def _play_qt(self, sound_key: str):
        """Воспроизведение через QSoundEffect."""
        if sound_key in self.sounds:
            self.sounds[sound_key].play()

    def _play_winsound(self, sound_key: str):
        """Воспроизведение через winsound (Windows API)."""
        path = self.sound_paths.get(sound_key)
        if not path:
            return

        try:
            # SND_FILENAME — играть файл, SND_ASYNC — асинхронно
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            logger.debug(f"[winsound] Ошибка воспроизведения '{sound_key}': {e}")

    def set_volume(self, volume: float):
        """Устанавливает громкость для всех звуков (от 0.0 до 1.0)."""
        for sound in self.sounds.values():
            sound.setVolume(volume)
