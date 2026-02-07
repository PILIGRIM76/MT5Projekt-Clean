# src/core/interfaces.py
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import MetaTrader5 as mt5


class ITerminalConnector(ABC):
    """
    Абстрактный интерфейс для взаимодействия с торговым терминалом.
    Позволяет подменять реальный MT5 на симулятор (SimulatedBroker).
    """

    @abstractmethod
    def initialize(self, path: str = None, login: int = None, password: str = None, server: str = None) -> bool:
        """Инициализация подключения к терминалу."""
        pass

    @abstractmethod
    def shutdown(self):
        """Закрытие подключения."""
        pass

    @abstractmethod
    def get_account_info(self):
        """Получение информации о счете (баланс, эквити и т.д.)."""
        pass

    @abstractmethod
    def get_positions(self, symbol: str = None, ticket: int = None):
        """Получение открытых позиций."""
        pass

    @abstractmethod
    def get_orders(self, ticket: int = None, symbol: str = None):
        """Получение активных ордеров."""
        pass

    @abstractmethod
    def get_history_orders(self, ticket: int = None, position: int = None):
        """Получение истории ордеров."""
        pass

    @abstractmethod
    def get_history_deals(self, date_from: datetime = None, date_to: datetime = None, ticket: int = None):
        """Получение истории сделок."""
        pass

    @abstractmethod
    def symbol_info(self, symbol: str):
        """Получение спецификации инструмента."""
        pass

    @abstractmethod
    def symbol_info_tick(self, symbol: str):
        """Получение последнего тика (цены) по инструменту."""
        pass

    @abstractmethod
    def order_send(self, request: dict):
        """Отправка торгового запроса."""
        pass

    @abstractmethod
    def order_check(self, request: dict):
        """Проверка торгового запроса без отправки."""
        pass


class MT5Connector(ITerminalConnector):
    """
    Реальная реализация коннектора, использующая библиотеку MetaTrader5.
    Проксирует вызовы к функциям mt5.*.
    """

    def initialize(self, path: str = None, login: int = None, password: str = None, server: str = None) -> bool:
        # Формируем словарь аргументов, исключая None, так как mt5.initialize не любит явные None
        kwargs = {}
        if path: kwargs['path'] = path
        if login: kwargs['login'] = login
        if password: kwargs['password'] = password
        if server: kwargs['server'] = server

        return mt5.initialize(**kwargs)

    def shutdown(self):
        mt5.shutdown()

    def get_account_info(self):
        return mt5.account_info()

    def get_positions(self, symbol: str = None, ticket: int = None):
        if ticket is not None:
            return mt5.positions_get(ticket=ticket)
        if symbol is not None:
            return mt5.positions_get(symbol=symbol)
        return mt5.positions_get()

    def get_orders(self, ticket: int = None, symbol: str = None):
        if ticket is not None:
            return mt5.orders_get(ticket=ticket)
        if symbol is not None:
            return mt5.orders_get(symbol=symbol)
        return mt5.orders_get()

    def get_history_orders(self, ticket: int = None, position: int = None):
        if ticket is not None:
            return mt5.history_orders_get(ticket=ticket)
        if position is not None:
            return mt5.history_orders_get(position=position)
        return None

    def get_history_deals(self, date_from: datetime = None, date_to: datetime = None, ticket: int = None):
        # MT5 API позволяет получать сделки либо по датам, либо по тикету
        if ticket is not None:
            return mt5.history_deals_get(ticket=ticket)

        if date_from and date_to:
            return mt5.history_deals_get(date_from, date_to)

        return None

    def symbol_info(self, symbol: str):
        return mt5.symbol_info(symbol)

    def symbol_info_tick(self, symbol: str):
        return mt5.symbol_info_tick(symbol)

    def order_send(self, request: dict):
        return mt5.order_send(request)

    def order_check(self, request: dict):
        return mt5.order_check(request)