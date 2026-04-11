# src/core/mt5_connection_manager.py
"""
MT5 Connection Manager — Единая точка подключения к MetaTrader 5.

Решает проблемы:
- Множественные вызовы mt5.initialize() в разных модулях
- Утечки ресурсов при shutdown/init
- Состояние гонки при многопоточном доступе
"""

import logging
import threading
from typing import Optional, Tuple

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MT5ConnectionManager:
    """
    Singleton менеджер подключений к MT5.

    Гарантирует:
    - Только одна инициализация за весь жизненный цикл
    - Безопасное подключение/отключение
    - Автоматическое переподключение при разрыве
    """

    _instance: Optional["MT5ConnectionManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        if MT5ConnectionManager._instance is not None:
            raise RuntimeError("Используйте MT5ConnectionManager.get_instance()")

        self._initialized = False
        self._login: Optional[int] = None
        self._password: Optional[str] = None
        self._server: Optional[str] = None
        self._path: Optional[str] = None
        self._lock = threading.RLock()  # Reentrant lock для вложенных вызовов

        # 🔧 OPTIMIZATION: Защита от частых переподключений
        self._last_reconnect_time = 0.0
        self._reconnect_cooldown = 5.0  # Минимальная задержка между переподключениями (сек)
        self._consecutive_failures = 0  # Счетчик неудачных переподключений

        MT5ConnectionManager._instance = self

    @classmethod
    def get_instance(cls) -> "MT5ConnectionManager":
        """Получить singleton экземпляр (потокобезопасно)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def initialize(
        self,
        path: str = None,
        login: int = None,
        password: str = None,
        server: str = None,
        timeout: int = 60000,
    ) -> bool:
        """
        Инициализировать подключение к MT5.

        Если уже инициализировано — возвращает True без повторного вызова.

        Args:
            path: Путь к terminal64.exe
            login: Номер торгового счета
            password: Пароль
            server: Имя сервера
            timeout: Таймаут подключения (мс)

        Returns:
            True если подключение успешно
        """
        import time

        with self._lock:
            # Если уже подключены — проверяем связь
            if self._initialized:
                if self._is_connected():
                    return True
                else:
                    # 🔧 OPTIMIZATION: Защита от частых переподключений
                    current_time = time.time()
                    time_since_last_reconnect = current_time - self._last_reconnect_time

                    if time_since_last_reconnect < self._reconnect_cooldown:
                        logger.debug(
                            f"[MT5] Пропуск переподключения (cooldown: {self._reconnect_cooldown - time_since_last_reconnect:.1f}с)"
                        )
                        return False

                    logger.warning(f"[MT5] Соединение потеряно. Переподключение...")
                    self._force_shutdown()

                    # Увеличиваем счетчик неудач и задержку
                    self._consecutive_failures += 1
                    self._reconnect_cooldown = min(5.0 * (2 ** min(self._consecutive_failures - 1, 3)), 60.0)

                    # Восстанавливаем сохранённые параметры
                    path = path or self._path
                    login = login or self._login
                    password = password or self._password
                    server = server or self._server

            logger.info(f"[MT5] Инициализация подключения...")

            try:
                # Сохраняем параметры для переподключения
                self._path = path
                self._login = login
                self._password = password
                self._server = server

                # Определяем режим подключения
                has_all_params = path and login and password and server
                has_path_only = path and not (login and password and server)
                has_login_only = login and not path

                if has_all_params:
                    # Полная авторизация
                    logger.info(f"[MT5] Полная авторизация: server={server}, login={login}, path={path}")
                    result = mt5.initialize(
                        path=path,
                        login=login,
                        password=password,
                        server=server,
                        timeout=timeout,
                    )
                elif has_path_only:
                    # Только путь — подключаемся к уже запущенному терминалу
                    logger.info(f"[MT5] Подключение к терминалу по пути: {path}")
                    result = mt5.initialize(path=path, timeout=timeout)
                elif has_login_only:
                    # Только логин — используем сохранённые параметры
                    logger.info(f"[MT5] Авторизация по логину: {login}")
                    result = mt5.initialize(
                        login=login,
                        password=self._password,
                        server=self._server,
                        timeout=timeout,
                    )
                else:
                    # Пробуем подключиться к уже запущенному терминалу без параметров
                    logger.info("[MT5] Попытка подключения к запущенному терминалу...")
                    result = mt5.initialize()

                if result:
                    self._initialized = True

                    # 🔧 OPTIMIZATION: Сброс счетчика неудач при успешном подключении
                    if self._consecutive_failures > 0:
                        logger.info(f"[MT5] Счетчик неудач сброшен (было: {self._consecutive_failures})")
                    self._consecutive_failures = 0
                    self._reconnect_cooldown = 5.0  # Возврат к базовой задержке
                    self._last_reconnect_time = time.time()

                    account_info = mt5.account_info()
                    if account_info:
                        logger.info(
                            f"[MT5] ✅ Подключено: Счет #{account_info.login}, "
                            f"Сервер: {account_info.server}, "
                            f"Баланс: {account_info.balance}"
                        )
                    return True
                else:
                    error = mt5.last_error()
                    error_code, error_msg = error

                    # Детальная диагностика ошибок
                    if error_code == -6:
                        logger.error(
                            f"[MT5] ❌ Ошибка авторизации (код {error_code}): {error_msg}\n"
                            f"  → Терминал MT5 уже запущен с другим логином/паролем.\n"
                            f"  → Решение:\n"
                            f"     1) Закройте MT5 терминал вручную\n"
                            f"     2) Или укажите MT5_PATH в configs/settings.json\n"
                            f"     3) Или проверьте правильность MT5_LOGIN/MT5_PASSWORD/MT5_SERVER"
                        )
                    elif error_code == -1:
                        logger.error(
                            f"[MT5] ❌ Ошибка инициализации (код {error_code}): {error_msg}\n"
                            f"  → Проверьте путь к terminal64.exe"
                        )
                    else:
                        logger.error(f"[MT5] ❌ Ошибка инициализации: {error}")
                    return False

            except Exception as e:
                logger.error(f"[MT5] ❌ Исключение при инициализации: {e}")
                return False

    def shutdown(self) -> None:
        """Безопасное отключение от MT5."""
        with self._lock:
            self._force_shutdown()

    def _force_shutdown(self) -> None:
        """Внутренний метод для принудительного отключения."""
        try:
            mt5.shutdown()
            logger.info("[MT5] Соединение закрыто")
        except Exception as e:
            logger.debug(f"[MT5] Ошибка при shutdown: {e}")
        finally:
            self._initialized = False
            self._login = None
            self._password = None
            self._server = None

    def is_connected(self) -> bool:
        """Проверить, активно ли подключение."""
        with self._lock:
            return self._initialized and self._is_connected()

    def _is_connected(self) -> bool:
        """Внутренняя проверка без блокировки (вызывать внутри with self._lock)."""
        try:
            # Легкая проверка: только version и account_info
            # symbols_get() слишком тяжелый и может возвращать None при нагрузке
            version = mt5.version()
            if version is None:
                return False

            account = mt5.account_info()
            if account is None:
                return False

            return True
        except Exception:
            return False

    def get_connection_info(self) -> dict:
        """Получить информацию о текущем подключении."""
        with self._lock:
            info = {
                "connected": self._initialized,
                "login": self._login,
                "server": self._server,
                "path": self._path,
            }

            if self._initialized:
                try:
                    account = mt5.account_info()
                    if account:
                        info["balance"] = account.balance
                        info["equity"] = account.equity
                        info["currency"] = account.currency
                        info["leverage"] = account.leverage

                    terminal = mt5.terminal_info()
                    if terminal:
                        info["terminal_name"] = terminal.name
                        info["company"] = terminal.company
                except Exception as e:
                    info["error"] = str(e)

            return info

    def __del__(self):
        """Гарантированное отключение при удалении объекта."""
        try:
            self.shutdown()
        except Exception:
            pass


# ===================================================================
# Функции-обёртки для замены прямых вызовов mt5.initialize()
# ===================================================================


def mt5_initialize(**kwargs) -> bool:
    """
    Безопасная замена mt5.initialize().
    Использует ConnectionManager для предотвращения дублирования.
    """
    manager = MT5ConnectionManager.get_instance()
    return manager.initialize(**kwargs)


def mt5_shutdown():
    """
    Безопасная замена mt5.shutdown().
    Реальное отключение происходит только при завершении приложения.
    """
    # Не вызываем shutdown() здесь, т.к. другие модули могут ещё работать
    # Отключение произойдёт при завершении приложения
    pass


def mt5_ensure_connected(max_retries: int = 5, base_delay: float = 0.5, **kwargs) -> bool:
    """
    Гарантировать подключение к MT5 перед выполнением операции.
    Использует экспоненциальную задержку для надёжности.

    Args:
        max_retries: Максимальное количество попыток (по умолчанию 5)
        base_delay: Базовая задержка в секундах (по умолчанию 0.5)
        **kwargs: Дополнительные параметры для initialize()

    Returns:
        bool: True если подключение успешно, False иначе

    Пример:
        # Попытки: 0.5s → 1s → 2s → 4s → 8s (всего ~16s)
        if mt5_ensure_connected(max_retries=5, base_delay=0.5):
            # Безопасно работаем с MT5
            rates = mt5.copy_rates_from_pos(...)
    """
    import time

    manager = MT5ConnectionManager.get_instance()

    for attempt in range(max_retries):
        try:
            # Проверяем текущее подключение
            if manager.is_connected():
                # Дополнительная проверка что соединение живо
                try:
                    account = mt5.account_info()
                    if account is not None:
                        logger.debug(f"[MT5] Соединение активно (попытка {attempt + 1}/{max_retries})")
                        return True
                except Exception as e:
                    logger.debug(f"[MT5] account_info не доступен: {e}")

            # Пытаемся инициализировать
            logger.info(f"[MT5] Попытка подключения {attempt + 1}/{max_retries}...")
            result = manager.initialize(**kwargs)

            if result and manager.is_connected():
                # Финальная проверка
                account = mt5.account_info()
                if account is not None:
                    logger.info(f"[MT5] ✅ Подключение успешно (попытка {attempt + 1}/{max_retries})")
                    return True
                else:
                    logger.warning(f"[MT5] Инициализация прошла, но account_info недоступен")
            else:
                logger.warning(f"[MT5] Инициализация не удалась (попытка {attempt + 1}/{max_retries})")

            # Переподключение не удалосьась — закрываем и пробуем снова
            try:
                manager.shutdown()
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"[MT5] Ошибка при попытке подключения: {e}")

        # Экспоненциальная задержка перед следующей попыткой
        if attempt < max_retries - 1:
            delay = base_delay * (2**attempt)  # 0.5s → 1s → 2s → 4s → 8s
            logger.info(f"[MT5] Ожидание {delay:.1f}s перед следующей попыткой...")
            time.sleep(delay)

    logger.critical(f"[MT5] ❌ Не удалось подключиться после {max_retries} попыток")
    return False
