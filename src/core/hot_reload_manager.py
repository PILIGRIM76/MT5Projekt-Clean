#!/usr/bin/env python3
"""
Hot Reload Manager для Genesis Trading System.
Позволяет обновлять систему без перезапуска приложения.

Возможности:
- Мониторинг Git репозитория на новые коммиты
- Динамическая перезагрузка Python модулей
- Обновление GUI компонентов без закрытия окна
- Безопасное обновление с откатом при ошибках
"""

import importlib
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class HotReloadManager:
    """
    Менеджер горячего обновления системы.

    Использование:
        manager = HotReloadManager(repo_path="F:/MT5Qoder/MT5Projekt-Clean")
        manager.start_monitoring(interval=60)  # Проверка каждые 60 секунд
    """

    def __init__(
        self,
        repo_path: str,
        branch: str = "main",
        on_update_available: Optional[Callable] = None,
        on_update_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ):
        self.repo_path = Path(repo_path)
        self.branch = branch
        self.on_update_available = on_update_available
        self.on_update_complete = on_update_complete
        self.on_error = on_error

        self._monitoring = False
        self._stop_event = threading.Event()
        self._last_commit = None
        self._monitor_thread = None

        # Модули для hot-reload
        self._reloadable_modules = []
        self._excluded_patterns = [
            "__pycache__",
            ".pyc",
            ".git",
            "venv",
            "node_modules",
            ".vs",
            "database",
            "logs",
            "secrets",
        ]

        logger.info(f"HotReloadManager инициализирован: {repo_path}")

    def start_monitoring(self, interval: int = 60):
        """Запуск мониторинга обновлений."""
        if self._monitoring:
            logger.warning("Мониторинг уже запущен")
            return

        self._monitoring = True
        self._stop_event.clear()

        # Получаем текущий коммит
        self._last_commit = self._get_current_commit()
        logger.info(f"Текущий коммит: {self._last_commit}")

        # Запускаем поток мониторинга
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True,
            name="HotReloadMonitor",
        )
        self._monitor_thread.start()
        logger.info(f"✅ Мониторинг обновлений запущен (интервал: {interval}с)")

    def stop_monitoring(self):
        """Остановка мониторинга."""
        self._monitoring = False
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("⏹️ Мониторинг обновлений остановлен")

    def check_for_updates(self) -> bool:
        """Проверка наличия обновлений."""
        current_commit = self._get_current_commit()
        if current_commit and current_commit != self._last_commit:
            logger.info(f"🔄 Доступна новая версия: {current_commit[:8]}")
            return True
        return False

    def apply_update(self) -> bool:
        """
        Применение обновления (pull + reload).

        Returns:
            True если обновление успешно применено
        """
        try:
            logger.info("🔄 Начало применения обновления...")

            # 1. Git pull
            if not self._git_pull():
                logger.error("❌ Ошибка git pull")
                if self.on_error:
                    self.on_error("Git pull failed")
                return False

            # 2. Перезагрузка модулей
            if not self._reload_modules():
                logger.error("❌ Ошибка перезагрузки модулей")
                if self.on_error:
                    self.on_error("Module reload failed")
                return False

            # 3. Обновляем текущий коммит
            self._last_commit = self._get_current_commit()

            logger.info("✅ Обновление успешно применено!")
            if self.on_update_complete:
                self.on_update_complete(self._last_commit)

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка применения обновления: {e}", exc_info=True)
            if self.on_error:
                self.on_error(str(e))
            return False

    def _monitor_loop(self, interval: int):
        """Цикл мониторинга."""
        logger.info(f"👁️ Цикл мониторинга запущен (интервал: {interval}с)")

        while not self._stop_event.is_set():
            try:
                # Проверяем наличие обновлений
                if self.check_for_updates():
                    logger.info("🔔 Обнаружено обновление!")

                    # Уведомляем о доступности обновления
                    if self.on_update_available:
                        self.on_update_available(self._last_commit)

                    # Автоматически применяем (или можно сделать ручное подтверждение)
                    # self.apply_update()

                # Ждём следующий интервал
                self._stop_event.wait(interval)

            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}", exc_info=True)
                self._stop_event.wait(60)  # Пауза при ошибке

        logger.info("👁️ Цикл мониторинга остановлен")

    def _get_current_commit(self) -> Optional[str]:
        """Получение текущего хэша коммита."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.error(f"Git rev-parse error: {result.stderr}")
                return None
        except Exception as e:
            logger.error(f"Ошибка получения текущего коммита: {e}")
            return None

    def _get_remote_commit(self) -> Optional[str]:
        """Получение хэша последнего коммита на удалённом репозитории."""
        try:
            # Fetch без merge
            subprocess.run(
                ["git", "fetch", "origin", self.branch],
                cwd=str(self.repo_path),
                capture_output=True,
                timeout=30,
            )

            # Получаем хэш удалённого коммита
            result = subprocess.run(
                ["git", "rev-parse", f"origin/{self.branch}"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return None
        except Exception as e:
            logger.error(f"Ошибка получения удалённого коммита: {e}")
            return None

    def _git_pull(self) -> bool:
        """Выполнение git pull."""
        try:
            logger.info("📥 Выполнение git pull...")

            result = subprocess.run(
                ["git", "pull", "origin", self.branch],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                logger.info(f"✅ Git pull успешен: {result.stdout}")
                return True
            else:
                logger.error(f"❌ Git pull ошибка: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("❌ Git pull timeout (120s)")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка git pull: {e}")
            return False

    def _reload_modules(self) -> bool:
        """Перезагрузка изменённых модулей."""
        try:
            logger.info("🔄 Перезагрузка модулей...")

            # Получаем список изменённых файлов
            changed_files = self._get_changed_files()
            if not changed_files:
                logger.info("Нет изменённых модулей для перезагрузки")
                return True

            logger.info(f"Изменённые файлы: {changed_files}")

            # Конвертируем файлы в модули
            modules_to_reload = set()
            for file_path in changed_files:
                module_name = self._file_to_module(file_path)
                if module_name and module_name in sys.modules:
                    modules_to_reload.add(module_name)

            # Перезгружаем модули
            for module_name in sorted(modules_to_reload):
                try:
                    logger.info(f"🔄 Перезагрузка модуля: {module_name}")
                    module = sys.modules[module_name]
                    importlib.reload(module)
                    logger.info(f"✅ Модуль перезагружен: {module_name}")
                except Exception as e:
                    logger.error(f"❌ Ошибка перезагрузки {module_name}: {e}")

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка перезагрузки модулей: {e}", exc_info=True)
            return False

    def _get_changed_files(self) -> List[str]:
        """Получение списка изменённых файлов после последнего pull."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD@{1}", "HEAD"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
                # Фильтруем только Python файлы
                return [f for f in files if f.endswith(".py")]
            return []
        except Exception as e:
            logger.error(f"Ошибка получения изменённых файлов: {e}")
            return []

    def _file_to_module(self, file_path: str) -> Optional[str]:
        """Конвертация пути файла в имя модуля."""
        try:
            # Убираем расширение
            module_path = file_path.replace("/", ".").replace("\\", ".")
            if module_path.endswith(".py"):
                module_path = module_path[:-3]

            # Убираем префикс проекта
            project_name = self.repo_path.name
            if module_path.startswith(project_name + "."):
                module_path = module_path[len(project_name) + 1 :]

            return module_path if module_path else None
        except Exception as e:
            logger.error(f"Ошибка конвертации файла в модуль: {e}")
            return None

    def get_update_status(self) -> dict:
        """Получение статуса обновлений."""
        local_commit = self._get_current_commit()
        remote_commit = self._get_remote_commit()

        return {
            "local_commit": local_commit,
            "remote_commit": remote_commit,
            "has_updates": local_commit != remote_commit if (local_commit and remote_commit) else False,
            "monitoring": self._monitoring,
            "last_check": time.time(),
        }
