#!/usr/bin/env python3
"""
Hot Reload Manager для Genesis Trading System.
Позволяет обновлять систему без перезапуска приложения.

Возможности:
- Мониторинг Git репозитория на новые коммиты
- Динамическая перезагрузка Python модулей
- Обновление GUI компонентов без закрытия окна
- Безопасное обновление с откатом при ошибках
- Горячая подмена конфигов и моделей (watchdog)
- DRY_RUN режим для тестирования
- Атомарные операции с откатом
"""

import copy
import importlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

logger = logging.getLogger(__name__)

# Отдельный логгер для hot-reload событий
hotreload_logger = logging.getLogger("hotreload")


def setup_hotreload_log_file(log_path: str = "logs/hotreload.log"):
    """Настраивает логирование hot-reload событий в отдельный файл."""
    try:
        log_dir = Path(log_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        hotreload_logger.addHandler(fh)
        hotreload_logger.setLevel(logging.DEBUG)
        hotreload_logger.info("=" * 60)
        hotreload_logger.info("HotReload логгер инициализирован")
        hotreload_logger.info("=" * 60)
    except Exception as e:
        logger.warning(f"Не удалось настроить лог hot-reload: {e}")


# Вызываем настройку при импорте
setup_hotreload_log_file()


class FileChange:
    """Структура для хранения информации об изменении файла."""

    def __init__(self, file_path: Path, change_type: str, timestamp: float):
        self.file_path = file_path
        self.change_type = change_type  # created, modified, deleted
        self.timestamp = timestamp
        self.backup_data: Optional[bytes] = None
        self.backup_config: Optional[Dict] = None

    def __repr__(self):
        return f"FileChange({self.file_path.name}, {self.change_type})"


class HotReloadConfig:
    """Конфигурация HotReloadManager."""

    def __init__(
        self,
        dry_run: bool = False,
        watch_configs: bool = True,
        watch_models: bool = True,
        watch_modules: bool = True,
        auto_apply: bool = False,
        debounce_seconds: float = 2.0,
        validation_timeout: int = 30,
    ):
        self.dry_run = dry_run
        self.watch_configs = watch_configs
        self.watch_models = watch_models
        self.watch_modules = watch_modules
        self.auto_apply = auto_apply
        self.debounce_seconds = debounce_seconds
        self.validation_timeout = validation_timeout

    def to_dict(self) -> Dict:
        return {
            "dry_run": self.dry_run,
            "watch_configs": self.watch_configs,
            "watch_models": self.watch_models,
            "watch_modules": self.watch_modules,
            "auto_apply": self.auto_apply,
            "debounce_seconds": self.debounce_seconds,
        }


class StrategyReloadHandler:
    """Обработчик событий файловой системы для горячей перезагрузки."""

    def __init__(self, hot_reload_manager: "HotReloadManager"):
        self.manager = hot_reload_manager
        self.lock = threading.Lock()
        self._pending_changes: Dict[str, FileChange] = {}
        self._debounce_timer: Optional[threading.Timer] = None

    def on_modified(self, event):
        """Обработка изменения файла."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        self._handle_file_change(path, "modified")

    def on_created(self, event):
        """Обработка создания файла."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        self._handle_file_change(path, "created")

    def on_deleted(self, event):
        """Обработка удаления файла."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        self._handle_file_change(path, "deleted")

    def _handle_file_change(self, path: Path, change_type: str):
        """Централизованная обработка изменений файлов."""
        # Фильтруем по расширениям
        allowed_extensions = {".json", ".py", ".h5", ".keras", ".pt", ".onnx"}
        if path.suffix.lower() not in allowed_extensions:
            return

        with self.lock:
            # Debounce — группировка быстрых изменений
            self._pending_changes[str(path)] = FileChange(
                file_path=path,
                change_type=change_type,
                timestamp=time.time(),
            )

            # Сбрасываем предыдущий таймер
            if self._debounce_timer and self._debounce_timer.is_alive():
                self._debounce_timer.cancel()

            # Запускаем таймер — применяем изменения через debounce_seconds
            self._debounce_timer = threading.Timer(
                self.manager.config.debounce_seconds,
                self._apply_pending_changes,
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

            hotreload_logger.debug(
                f"📝 Зафиксировано изменение: {path.name} ({change_type})"
            )

    def _apply_pending_changes(self):
        """Применяет накопленные изменения после debounce."""
        with self.lock:
            if not self._pending_changes:
                return

            changes = list(self._pending_changes.values())
            self._pending_changes.clear()

            for change in changes:
                try:
                    hotreload_logger.info(
                        f"🔥 Hot reload: обработка {change.file_path.name} ({change.change_type})"
                    )

                    if self.manager.config.dry_run:
                        hotreload_logger.warning(
                            f"🧪 DRY_RUN: Изменение {change.file_path.name} проигнорировано"
                        )
                        continue

                    self.manager.validate_and_apply(change)
                    hotreload_logger.info(
                        f"✅ Hot reload: {change.file_path.name} успешно применён"
                    )

                except Exception as e:
                    hotreload_logger.error(
                        f"❌ Hot reload отклонён ({change.file_path.name}): {e}"
                    )
                    self.manager._rollback_change(change)


class HotReloadManager:
    """
    Менеджер горячего обновления системы.

    Использование:
        manager = HotReloadManager(
            repo_path="F:/MT5Qoder/MT5Projekt-Clean",
            trading_system=trading_system,
            config=HotReloadConfig(dry_run=False, auto_apply=True)
        )
        manager.start_monitoring(interval=60)
    """

    def __init__(
        self,
        repo_path: str,
        branch: str = "main",
        trading_system=None,
        on_update_available: Optional[Callable] = None,
        on_update_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        config: Optional[HotReloadConfig] = None,
        watch_dirs: Optional[List[str]] = None,
    ):
        self.repo_path = Path(repo_path)
        self.branch = branch
        self.trading_system = trading_system
        self.on_update_available = on_update_available
        self.on_update_complete = on_update_complete
        self.on_error = on_error
        self.config = config or HotReloadConfig()

        self._monitoring = False
        self._stop_event = threading.Event()
        self._last_commit = None
        self._monitor_thread = None
        self._last_check_time = 0

        # Watchdog observer
        self.observer: Optional[Observer] = None
        self._watch_dirs = watch_dirs or []
        self._file_handler = StrategyReloadHandler(self)

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

        # Бэкапы для отката
        self._config_backups: Dict[str, Dict] = {}
        self._model_backups: Dict[str, Any] = {}

        logger.info(f"HotReloadManager инициализирован: {repo_path}")
        logger.info(f"Конфигурация: {self.config.to_dict()}")
        if not WATCHDOG_AVAILABLE:
            logger.warning("⚠️ watchdog не установлен — мониторинг файлов отключён")
            logger.info("   Установите: pip install watchdog")

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

        # Запускаем watchdog для файловых изменений
        if WATCHDOG_AVAILABLE and self._watch_dirs:
            self._start_file_watcher()

        # Запускаем поток мониторинга git
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True,
            name="HotReloadMonitor",
        )
        self._monitor_thread.start()
        logger.info(f"✅ Мониторинг обновлений запущен (интервал: {interval}с)")

    def _start_file_watcher(self):
        """Запускает watchdog observer для мониторинга файлов."""
        try:
            self.observer = Observer()

            for dir_path in self._watch_dirs:
                path = Path(dir_path)
                if path.exists():
                    self.observer.schedule(
                        self._file_handler,
                        str(path),
                        recursive=False,
                    )
                    logger.info(f"👁️ Watchdog наблюдает за: {dir_path}")

            self.observer.start()
            logger.info("✅ Watchdog observer запущен")

        except Exception as e:
            logger.error(f"Ошибка запуска watchdog: {e}")

    def stop_monitoring(self):
        """Остановка мониторинга."""
        self._monitoring = False
        self._stop_event.set()

        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)

        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

        logger.info("⏹️ Мониторинг обновлений остановлен")

    def validate_and_apply(self, change: FileChange):
        """
        Валидирует и применяет изменение файла.

        Raises:
            Exception при ошибке валидации
        """
        file_path = change.file_path
        suffix = file_path.suffix.lower()

        # Создаём бэкап перед применением
        self._create_backup(change)

        if suffix == ".json":
            # Конфиг — валидация JSON и схемы
            self._validate_and_apply_config(change)

        elif suffix in (".h5", ".keras", ".pt", ".onnx"):
            # Модель — проверка формата
            self._validate_and_apply_model(change)

        elif suffix == ".py":
            # Модуль — проверка синтаксиса
            self._validate_and_apply_module(change)

        else:
            raise ValueError(f"Неподдерживаемый тип файла: {suffix}")

    def _create_backup(self, change: FileChange):
        """Создаёт бэкап файла/конфига для отката."""
        file_path = change.file_path

        if change.change_type == "deleted":
            return  # Нечего бэкапить

        try:
            if file_path.suffix.lower() == ".json":
                # Для JSON — сохраняем содержимое
                with open(file_path, "r", encoding="utf-8") as f:
                    change.backup_config = json.load(f)
                self._config_backups[str(file_path)] = copy.deepcopy(
                    change.backup_config
                )
            else:
                # Для бинарных файлов — читаем байты
                change.backup_data = file_path.read_bytes()
                self._model_backups[str(file_path)] = change.backup_data

            hotreload_logger.debug(f"💾 Бэкап создан: {file_path.name}")

        except Exception as e:
            hotreload_logger.warning(f"⚠️ Не удалось создать бэкап {file_path.name}: {e}")

    def _validate_and_apply_config(self, change: FileChange):
        """Валидация и применение конфига."""
        file_path = change.file_path

        # 1. Читаем новый конфиг
        with open(file_path, "r", encoding="utf-8") as f:
            new_config = json.load(f)

        # 2. Валидация схемы
        self._validate_config_schema(new_config)

        # 3. Применяем к trading system
        if self.trading_system and hasattr(self.trading_system, "config"):
            ts_config = self.trading_system.config

            # Обновляем поля конфига
            for key, value in new_config.items():
                if hasattr(ts_config, key):
                    old_value = getattr(ts_config, key)
                    setattr(ts_config, key, value)
                    hotreload_logger.info(f"⚙️ Конфиг обновлён: {key} = {value}")

                    # Специальная обработка ACTIVE_MODEL
                    if key == "ACTIVE_MODEL" and hasattr(self.trading_system, "model_loader"):
                        hotreload_logger.info(
                            f"🔄 Перезагрузка активной модели: {value}"
                        )
                        self.trading_system.model_loader.clear_cache()
                        # Перезагружаем модель
                        if hasattr(self.trading_system.model_loader, "reload_active_model"):
                            self.trading_system.model_loader.reload_active_model()

            hotreload_logger.info("✅ Конфиг успешно применён")
        else:
            hotreload_logger.info("✅ Конфиг валиден (TradingSystem недоступен)")

    def _validate_and_apply_model(self, change: FileChange):
        """Валидация и применение модели."""
        file_path = change.file_path

        if change.change_type == "deleted":
            hotreload_logger.warning(f"⚠️ Модель удалена: {file_path.name}")
            return

        # 1. Проверка что файл существует и не пуст
        if not file_path.exists():
            raise FileNotFoundError(f"Файл модели не найден: {file_path}")

        if file_path.stat().st_size == 0:
            raise ValueError(f"Файл модели пуст: {file_path}")

        # 2. Проверка формата
        suffix = file_path.suffix.lower()
        if suffix in (".h5", ".keras"):
            self._validate_keras_model(file_path)
        elif suffix == ".pt":
            self._validate_pytorch_model(file_path)
        elif suffix == ".onnx":
            self._validate_onnx_model(file_path)

        # 3. Обновляем кэш model_loader
        if self.trading_system and hasattr(self.trading_system, "model_loader"):
            self.trading_system.model_loader.clear_cache()
            hotreload_logger.info(f"🧹 Кэш моделей очищен после изменения {file_path.name}")

        hotreload_logger.info(f"✅ Модель валидна: {file_path.name}")

    def _validate_and_apply_module(self, change: FileChange):
        """Валидация и применение Python модуля."""
        file_path = change.file_path

        if change.change_type == "deleted":
            hotreload_logger.warning(f"⚠️ Модуль удалён: {file_path.name}")
            return

        # 1. Проверка синтаксиса
        try:
            source = file_path.read_text(encoding="utf-8")
            compile(source, str(file_path), "exec")
        except SyntaxError as e:
            raise SyntaxError(f"Синтаксическая ошибка в {file_path.name}: {e}")

        # 2. Hot-reload модуля
        module_name = self._file_to_module(str(file_path))
        if module_name and module_name in sys.modules:
            try:
                module = sys.modules[module_name]
                importlib.reload(module)
                hotreload_logger.info(f"🔄 Модуль перезагружен: {module_name}")
            except Exception as e:
                raise RuntimeError(f"Ошибка перезагрузки {module_name}: {e}")
        else:
            hotreload_logger.debug(f"📝 Модуль {module_name} не загружен — пропуск")

    def _validate_config_schema(self, config: Dict):
        """Валидация схемы конфига."""
        required_types = {
            "MODEL_DIR": str,
            "ACTIVE_MODEL": str,
            "BACKUP_MODEL": str,
            "MODEL_FORMAT": str,
        }

        for key, expected_type in required_types.items():
            if key in config:
                if not isinstance(config[key], expected_type):
                    raise ValueError(
                        f"Неверный тип для {key}: ожидался {expected_type.__name__}, "
                        f"получен {type(config[key]).__name__}"
                    )

    def _validate_keras_model(self, file_path: Path):
        """Валидация Keras модели."""
        try:
            import tensorflow as tf

            # Пробуем загрузить модель
            model = tf.keras.models.load_model(str(file_path))
            if model is None:
                raise ValueError("Модель не загрузилась")
            hotreload_logger.debug(f"✅ Keras модель валидна: {file_path.name}")
        except ImportError:
            hotreload_logger.warning("⚠️ TensorFlow не установлен — пропуск валидации")
        except Exception as e:
            raise ValueError(f"Невалидная Keras модель {file_path.name}: {e}")

    def _validate_pytorch_model(self, file_path: Path):
        """Валидация PyTorch модели."""
        try:
            import torch

            state_dict = torch.load(str(file_path), map_location="cpu", weights_only=False)
            if state_dict is None:
                raise ValueError("Модель не загрузилась")
            hotreload_logger.debug(f"✅ PyTorch модель валидна: {file_path.name}")
        except ImportError:
            hotreload_logger.warning("⚠️ PyTorch не установлен — пропуск валидации")
        except Exception as e:
            raise ValueError(f"Невалидная PyTorch модель {file_path.name}: {e}")

    def _validate_onnx_model(self, file_path: Path):
        """Валидация ONNX модели."""
        try:
            import onnx

            onnx.checker.check_model(str(file_path))
            hotreload_logger.debug(f"✅ ONNX модель валидна: {file_path.name}")
        except ImportError:
            hotreload_logger.warning("⚠️ ONNX не установлен — пропуск валидации")
        except Exception as e:
            raise ValueError(f"Невалидная ONNX модель {file_path.name}: {e}")

    def _rollback_change(self, change: FileChange):
        """Откат изменения при ошибке."""
        file_path = change.file_path

        hotreload_logger.warning(f"🔄 Откат изменения: {file_path.name}")

        try:
            if change.change_type == "deleted" and change.backup_data:
                # Восстанавливаем удалённый файл
                file_path.write_bytes(change.backup_data)
                hotreload_logger.info(f"✅ Файл восстановлен: {file_path.name}")

            elif change.backup_data:
                # Восстанавливаем бинарный файл из бэкапа
                file_path.write_bytes(change.backup_data)
                hotreload_logger.info(f"✅ Файл откачен: {file_path.name}")

            elif change.backup_config:
                # Для JSON — восстанавливаем содержимое
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(change.backup_config, f, ensure_ascii=False, indent=2)
                hotreload_logger.info(f"✅ Конфиг откачен: {file_path.name}")

        except Exception as e:
            hotreload_logger.error(f"❌ Ошибка отката {file_path.name}: {e}")

        # Уведомляем об ошибке
        if self.on_error:
            self.on_error(f"Hot rollback: {file_path.name}")

    # ─────────────────── GIT MONITORING ───────────────────

    def check_for_updates(self) -> bool:
        """Проверка наличия обновлений."""
        self._last_check_time = time.time()
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

                    # Автоматически применяем если включено
                    if self.config.auto_apply:
                        self.apply_update()

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
            "has_updates": local_commit != remote_commit
            if (local_commit and remote_commit)
            else False,
            "monitoring": self._monitoring,
            "last_check": self._last_check_time if self._last_check_time > 0 else None,
            "dry_run": self.config.dry_run,
        }

    def set_dry_run(self, enabled: bool):
        """Включить/выключить режим DRY_RUN."""
        self.config.dry_run = enabled
        hotreload_logger.info(f"🧪 DRY_RUN режим: {'включён' if enabled else 'выключен'}")

    def add_watch_dir(self, dir_path: str):
        """Добавить директорию для наблюдения."""
        if not WATCHDOG_AVAILABLE:
            logger.warning("⚠️ watchdog не установлен — невозможно добавить директорию")
            return

        if dir_path not in self._watch_dirs:
            self._watch_dirs.append(dir_path)

            # Если observer уже запущен — добавляем новую директорию
            if self.observer and self.observer.is_alive():
                self.observer.schedule(self._file_handler, dir_path, recursive=False)
                hotreload_logger.info(f"👁️ Добавлена директория: {dir_path}")

    def remove_watch_dir(self, dir_path: str):
        """Убрать директорию из наблюдения."""
        if dir_path in self._watch_dirs:
            self._watch_dirs.remove(dir_path)
            hotreload_logger.info(f"👁️ Убрана директория: {dir_path}")
