# src/core/auto_updater.py

import logging
import subprocess
import time
import sys
import os
from threading import Thread
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class AutoUpdater:
    def __init__(self, trading_system, bridge: QObject, check_interval_hours: int = 1):
        self.trading_system = trading_system
        self.check_interval_sec = check_interval_hours * 3600
        self.update_pending = False
        self.bridge = bridge
        logger.info(f"Авто-обновление (AutoUpdater) инициализировано. Проверка каждые {check_interval_hours} час(а).")

    def _run_command(self, command: list) -> str:
        """Безопасно выполняет системную команду с правильной обработкой кодировки."""
        try:
            is_windows = sys.platform.startswith('win')
            startupinfo = None
            if is_windows:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # Git всегда выводит коммиты и другие данные в UTF-8.
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                shell=False,
                startupinfo=startupinfo,
                encoding='utf-8',
                errors='replace'
            )

            if result.returncode != 0:
                logger.error(f"Ошибка выполнения команды '{' '.join(command)}':\n{result.stderr}")
                return ""

            return result.stdout.strip()
        except FileNotFoundError:
            logger.error(
                f"Команда '{command[0]}' не найдена. Убедитесь, что Git установлен и находится в системном PATH.")
            return ""
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при выполнении команды '{' '.join(command)}': {e}")
            return ""

    def check_for_updates(self):
        logger.info("Проверка наличия обновлений...")
        self._run_command(['git', 'fetch'])
        local_hash = self._run_command(['git', 'rev-parse', 'HEAD'])
        remote_hash = self._run_command(['git', 'rev-parse', 'origin/main'])

        if local_hash and remote_hash and local_hash != remote_hash:
            status_text = f"Доступно обновление! (-> {remote_hash[:7]})"
            logger.warning(f"!!! НАЙДЕНО ОБНОВЛЕНИЕ !!! Локальный: {local_hash[:7]}, Удаленный: {remote_hash[:7]}")
            self.update_pending = True
            self.trading_system.update_pending = True

            # --- ИСПРАВЛЕНИЕ: Проверка на существование bridge ---
            if self.bridge is not None:
                try:
                    if hasattr(self.bridge, 'update_status_changed'):
                        self.bridge.update_status_changed.emit(status_text, True)
                except Exception as e:
                    logger.error(f"Ошибка отправки сигнала в GUI: {e}")
            else:
                logger.info(f"GUI Bridge не подключен. Статус обновления: {status_text}")
        else:
            status_text = "Обновлений нет"
            logger.info("Обновлений не найдено.")

    def apply_update_and_restart(self):
        logger.critical("НАЧИНАЕТСЯ ПРОЦЕСС АВТОМАТИЧЕСКОГО ОБНОВЛЕНИЯ!")

        # Корректная остановка системы ПЕРЕД обновлением
        logger.info("Остановка всех системных потоков перед перезапуском...")
        if self.trading_system.running:
            self.trading_system.stop()
            time.sleep(3)  # Даем время на завершение всех операций

        logger.info("Шаг 1: Получение последних изменений с сервера (fetch)...")
        self._run_command(['git', 'fetch', 'origin', 'main'])

        logger.info("Шаг 2: Принудительное обновление до последней версии (reset --hard)...")
        reset_result = self._run_command(['git', 'reset', '--hard', 'origin/main'])
        logger.info(f"Результат git reset:\n{reset_result}")

        logger.info("Шаг 3: Установка/обновление зависимостей из requirements.txt...")
        python_executable = sys.executable
        req_path = os.path.join(os.path.dirname(sys.argv[0]), 'requirements.txt')
        if os.path.exists(req_path):
            self._run_command([python_executable, '-m', 'pip', 'install', '-r', req_path])
        else:
            logger.warning("Файл requirements.txt не найден, пропуск установки зависимостей.")

        logger.critical("Шаг 4: Перезапуск приложения для применения обновлений...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def start(self):
        def loop():
            # Даем системе 5 секунд на полный запуск перед первой проверкой
            time.sleep(5)
            while self.trading_system.running:
                try:
                    self.check_for_updates()
                except Exception as e:
                    logger.error(f"Ошибка в цикле обновлений: {e}")
                time.sleep(self.check_interval_sec)

        thread = Thread(target=loop, daemon=True)
        thread.start()