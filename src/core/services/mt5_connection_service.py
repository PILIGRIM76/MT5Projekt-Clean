# src/core/services/mt5_connection_service.py
"""
Сервис для тестирования MT5 подключения.

Вынесен из GUI для соблюдения архитектуры:
- GUI не должен напрямую обращаться к MT5
- Все MT5 операции через сервисы ядра
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from src.core.mt5_connection_manager import mt5_initialize

logger = logging.getLogger(__name__)


@dataclass
class ConnectionTestResult:
    """Результат теста подключения."""

    success: bool
    message: str
    login: Optional[int] = None
    server: Optional[str] = None


class MT5ConnectionService:
    """Сервис для тестирования подключения к MT5 терминалу."""

    def test_connection(self, login: str, password: str, server: str, path: str, timeout: int = 5000) -> ConnectionTestResult:
        """
        Тестирует подключение к MT5.

        Args:
            login: Логин счёта
            password: Пароль
            server: Сервер
            path: Путь к терминалу
            timeout: Таймаут в миллисекундах

        Returns:
            ConnectionTestResult с результатом подключения
        """
        if not all([login, password, server, path]):
            return ConnectionTestResult(success=False, message="Заполните все поля.")

        try:
            login_int = int(login)
        except (ValueError, TypeError):
            return ConnectionTestResult(success=False, message="Неверный формат логина.")

        logger.info(f"Тестирование подключения к {server}...")

        if not mt5_initialize(path=path, login=login_int, password=password, server=server, timeout=timeout):
            import MetaTrader5 as mt5

            err_code, err_msg = mt5.last_error()
            logger.warning(f"MT5 подключение не удалось: {err_msg}")
            return ConnectionTestResult(success=False, message=f"Ошибка MT5: {err_msg}")

        try:
            import MetaTrader5 as mt5

            account_info = mt5.account_info()
            if account_info is None:
                logger.warning("Не удалось получить информацию о счёте")
                return ConnectionTestResult(success=False, message="Неверные учетные данные.")

            logger.info(f"Успешное подключение: счёт #{account_info.login}")
            return ConnectionTestResult(
                success=True, message=f"Успех! Счет #{account_info.login}", login=account_info.login, server=server
            )
        except Exception as e:
            logger.error(f"Ошибка при получении информации о счёте: {e}")
            return ConnectionTestResult(success=False, message=f"Ошибка: {str(e)}")


_mt5_connection_service: Optional[MT5ConnectionService] = None


def get_mt5_connection_service() -> MT5ConnectionService:
    """Получить экземпляр сервиса."""
    global _mt5_connection_service
    if _mt5_connection_service is None:
        _mt5_connection_service = MT5ConnectionService()
    return _mt5_connection_service
