# src/core/auto_updater.py

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

import requests
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class AutoUpdater:
    """
    Система автоматического обновления через GitHub Releases.
    Работает как для dev-версии (с Git), так и для установленной версии (через GitHub API).
    """

    GITHUB_REPO = "PILIGRIM76/MT5Projekt-Clean"
    GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    def __init__(self, trading_system, bridge: QObject, check_interval_hours: int = 24):
        self.trading_system = trading_system
        self.check_interval_sec = check_interval_hours * 3600
        self.update_pending = False
        self.bridge = bridge
        self.latest_version = None
        self.download_url = None
        self.is_dev_mode = self._check_if_dev_mode()

        logger.info(
            f"AutoUpdater инициализирован. Режим: {'DEV (Git)' if self.is_dev_mode else 'PRODUCTION (GitHub Releases)'}"
        )
        logger.info(f"Проверка обновлений каждые {check_interval_hours} час(ов)")

    def _check_if_dev_mode(self) -> bool:
        """Проверяет, запущена ли программа в dev-режиме (с Git) или как установленная версия."""
        # Проверяем наличие .git папки
        git_dir = Path(__file__).parent.parent.parent / ".git"
        return git_dir.exists()

    def _get_current_version(self) -> str:
        """Получает текущую версию программы."""
        try:
            from src._version import __version__

            return __version__.strip()
        except:
            return "1.0.0"

    def _run_command(self, command: list) -> str:
        """Безопасно выполняет системную команду."""
        try:
            is_windows = sys.platform.startswith("win")
            startupinfo = None
            if is_windows:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                shell=False,
                startupinfo=startupinfo,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

            if result.returncode != 0:
                logger.error(f"Ошибка выполнения команды '{' '.join(command)}':\n{result.stderr}")
                return ""

            return result.stdout.strip()
        except FileNotFoundError:
            logger.error(f"Команда '{command[0]}' не найдена.")
            return ""
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout при выполнении команды '{' '.join(command)}'")
            return ""
        except Exception as e:
            logger.error(f"Ошибка при выполнении команды '{' '.join(command)}': {e}")
            return ""

    def _check_github_releases(self) -> bool:
        """Проверяет наличие новой версии через GitHub Releases API."""
        try:
            logger.info(f"Проверка обновлений через GitHub API: {self.GITHUB_API_URL}")

            response = requests.get(self.GITHUB_API_URL, timeout=10, headers={"Accept": "application/vnd.github.v3+json"})

            if response.status_code != 200:
                logger.warning(f"GitHub API вернул статус {response.status_code}")
                return False

            data = response.json()
            latest_version = data.get("tag_name", "").lstrip("v")
            current_version = self._get_current_version()

            logger.info(f"Текущая версия: {current_version}, Последняя версия: {latest_version}")

            if self._compare_versions(latest_version, current_version) > 0:
                self.latest_version = latest_version

                # Ищем установщик в assets
                for asset in data.get("assets", []):
                    if asset["name"].endswith(".exe") and "Setup" in asset["name"]:
                        self.download_url = asset["browser_download_url"]
                        logger.info(f"Найден установщик: {asset['name']}")
                        logger.info(f"URL загрузки: {self.download_url}")
                        return True

                logger.warning("Установщик не найден в релизе")
                return False

            return False

        except requests.RequestException as e:
            logger.error(f"Ошибка при обращении к GitHub API: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при проверке обновлений: {e}")
            return False

    def _check_git_updates(self) -> bool:
        """Проверяет наличие обновлений через Git (для dev-режима)."""
        logger.info("Проверка обновлений через Git...")
        self._run_command(["git", "fetch"])
        local_hash = self._run_command(["git", "rev-parse", "HEAD"])
        remote_hash = self._run_command(["git", "rev-parse", "origin/main"])

        if local_hash and remote_hash and local_hash != remote_hash:
            logger.warning(f"Найдено обновление! Локальный: {local_hash[:7]}, Удаленный: {remote_hash[:7]}")
            return True

        return False

    def _compare_versions(self, version1: str, version2: str) -> int:
        """
        Сравнивает две версии.
        Возвращает: 1 если version1 > version2, -1 если version1 < version2, 0 если равны
        """
        try:
            v1_parts = [int(x) for x in version1.split(".")]
            v2_parts = [int(x) for x in version2.split(".")]

            # Дополняем нулями до одинаковой длины
            max_len = max(len(v1_parts), len(v2_parts))
            v1_parts.extend([0] * (max_len - len(v1_parts)))
            v2_parts.extend([0] * (max_len - len(v2_parts)))

            for v1, v2 in zip(v1_parts, v2_parts):
                if v1 > v2:
                    return 1
                elif v1 < v2:
                    return -1

            return 0
        except:
            return 0

    def check_for_updates(self):
        """Проверяет наличие обновлений (универсальный метод)."""
        logger.info("Проверка наличия обновлений...")

        update_available = False

        if self.is_dev_mode:
            # Dev-режим: проверяем через Git
            update_available = self._check_git_updates()
            status_text = "Доступно обновление через Git!" if update_available else "Обновлений нет"
        else:
            # Production-режим: проверяем через GitHub Releases
            update_available = self._check_github_releases()
            if update_available:
                status_text = f"Доступна новая версия {self.latest_version}!"
            else:
                status_text = "Обновлений нет"

        if update_available:
            logger.warning(f"!!! НАЙДЕНО ОБНОВЛЕНИЕ !!! {status_text}")
            self.update_pending = True
            self.trading_system.update_pending = True

            # Отправляем сигнал в GUI
            if self.bridge is not None:
                try:
                    if hasattr(self.bridge, "update_status_changed"):
                        self.bridge.update_status_changed.emit(status_text, True)
                except Exception as e:
                    logger.error(f"Ошибка отправки сигнала в GUI: {e}")
            else:
                logger.info(f"GUI Bridge не подключен. Статус: {status_text}")
        else:
            logger.info(status_text)

    def apply_update_and_restart(self):
        """Применяет обновление (универсальный метод)."""
        if self.is_dev_mode:
            self._apply_git_update()
        else:
            self._apply_release_update()

    def _apply_git_update(self):
        """Применяет обновление через Git (для dev-режима)."""
        logger.critical("НАЧИНАЕТСЯ ПРОЦЕСС ОБНОВЛЕНИЯ ЧЕРЕЗ GIT!")

        # Остановка системы
        logger.info("Остановка всех системных потоков...")
        if self.trading_system.running:
            self.trading_system.stop()
            time.sleep(3)

        logger.info("Шаг 1: Получение последних изменений (fetch)...")
        self._run_command(["git", "fetch", "origin", "main"])

        logger.info("Шаг 2: Обновление до последней версии (reset --hard)...")
        reset_result = self._run_command(["git", "reset", "--hard", "origin/main"])
        logger.info(f"Результат git reset:\n{reset_result}")

        logger.info("Шаг 3: Установка/обновление зависимостей...")
        python_executable = sys.executable
        req_path = Path(__file__).parent.parent.parent / "requirements.txt"
        if req_path.exists():
            self._run_command([python_executable, "-m", "pip", "install", "-r", str(req_path)])
        else:
            logger.warning("Файл requirements.txt не найден")

        logger.critical("Шаг 4: Перезапуск приложения...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _apply_release_update(self):
        """Применяет обновление через загрузку установщика (для production-режима)."""
        logger.critical("НАЧИНАЕТСЯ ПРОЦЕСС ОБНОВЛЕНИЯ ЧЕРЕЗ GITHUB RELEASES!")

        if not self.download_url:
            logger.error("URL загрузки не найден!")
            return

        try:
            # Остановка системы
            logger.info("Остановка всех системных потоков...")
            if self.trading_system.running:
                self.trading_system.stop()
                time.sleep(3)

            # Загрузка установщика
            logger.info(f"Загрузка установщика с {self.download_url}...")

            # Путь для сохранения установщика
            temp_dir = Path(os.environ.get("TEMP", "/tmp"))
            installer_path = temp_dir / f"GenesisTrading_Setup_v{self.latest_version}.exe"

            # Загружаем файл
            response = requests.get(self.download_url, stream=True, timeout=300)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            logger.info(f"Размер файла: {total_size / 1024 / 1024:.2f} MB")

            with open(installer_path, "wb") as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            if downloaded % (1024 * 1024 * 10) == 0:  # Каждые 10 MB
                                logger.info(f"Загружено: {progress:.1f}%")

            logger.info(f"Установщик сохранён: {installer_path}")

            # Запуск установщика
            logger.critical("Запуск установщика...")

            if sys.platform.startswith("win"):
                # Windows: запускаем установщик с silent флагами
                subprocess.Popen([str(installer_path), "/SILENT", "/CLOSEAPPLICATIONS"], shell=False)
            else:
                subprocess.Popen([str(installer_path)], shell=False)

            # Закрываем приложение
            logger.critical("Закрытие приложения для установки обновления...")
            time.sleep(2)
            sys.exit(0)

        except requests.RequestException as e:
            logger.error(f"Ошибка при загрузке установщика: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обновлении: {e}")

    def start(self):
        """Запускает фоновый поток проверки обновлений."""

        def loop():
            # Даем системе 30 секунд на полный запуск перед первой проверкой
            time.sleep(30)
            while self.trading_system.running:
                try:
                    self.check_for_updates()
                except Exception as e:
                    logger.error(f"Ошибка в цикле обновлений: {e}")
                time.sleep(self.check_interval_sec)

        thread = Thread(target=loop, daemon=True, name="AutoUpdater")
        thread.start()
        logger.info("Фоновый поток проверки обновлений запущен")
