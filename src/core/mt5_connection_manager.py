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
    
    _instance: Optional['MT5ConnectionManager'] = None
    _lock = threading.Lock()
    
    def __init__(self):
        if MT5ConnectionManager._instance is not None:
            raise RuntimeError("Используйте MT5ConnectionManager.get_instance()")
        
        self._initialized = False
        self._login: Optional[int] = None
        self._server: Optional[str] = None
        self._path: Optional[str] = None
        self._lock = threading.RLock()  # Reentrant lock для вложенных вызовов
        
        MT5ConnectionManager._instance = self

    @classmethod
    def get_instance(cls) -> 'MT5ConnectionManager':
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
        with self._lock:
            # Если уже подключены — проверяем связь
            if self._initialized:
                if self._is_connected():
                    return True
                else:
                    logger.warning("[MT5] Соединение потеряно. Переподключение...")
                    self._force_shutdown()
            
            logger.info(f"[MT5] Инициализация подключения...")
            
            try:
                # Сохраняем параметры для переподключения
                self._path = path
                self._login = login
                self._server = server
                
                # Пробуем подключиться
                if path:
                    result = mt5.initialize(
                        path=path,
                        login=login,
                        password=password,
                        server=server,
                        timeout=timeout,
                    )
                else:
                    result = mt5.initialize(
                        login=login,
                        password=password,
                        server=server,
                        timeout=timeout,
                    )
                
                if result:
                    self._initialized = True
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
            self._server = None

    def is_connected(self) -> bool:
        """Проверить, активно ли подключение."""
        with self._lock:
            return self._initialized and self._is_connected()

    def _is_connected(self) -> bool:
        """Внутренняя проверка без блокировки (вызывать внутри with self._lock)."""
        try:
            # Простейшая проверка — запрос версии терминала
            version = mt5.version()
            return version is not None
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


def mt5_ensure_connected(**kwargs) -> bool:
    """
    Гарантировать подключение перед выполнением операции.
    Если не подключено — инициализирует.
    """
    manager = MT5ConnectionManager.get_instance()
    if not manager.is_connected():
        return manager.initialize(**kwargs)
    return True
