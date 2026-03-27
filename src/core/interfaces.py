# src/core/interfaces.py
"""
Интерфейсы для основных компонентов Trading System.

Обеспечивает:
- Четкие контракты между компонентами
- Возможность мокирования для тестов
- Слабую связанность через Dependency Injection
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
import pandas as pd


# ===========================================
# MT5 Connector Interface
# ===========================================

class ITerminalConnector(ABC):
    """Интерфейс для подключения к торговому терминалу."""

    @abstractmethod
    def initialize(self) -> bool:
        """
        Инициализация подключения.
        
        Returns:
            True если успешно
        """
        pass

    @abstractmethod
    def shutdown(self) -> bool:
        """
        Завершение подключения.
        
        Returns:
            True если успешно
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Проверка подключения.
        
        Returns:
            True если подключено
        """
        pass

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """
        Получение информации об аккаунте.
        
        Returns:
            Данные аккаунта
        """
        pass


# Примечание: MT5Connector - это интерфейс, а не реализация
# Реализация находится в src.core.mt5_connector
# Этот класс здесь только для типизации и документации


# ===========================================
# Data Provider Interface
# ===========================================

class IDataProvider(ABC):
    """Интерфейс для получения рыночных данных."""

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        timeframe: int,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Получение исторических данных.
        
        Args:
            symbol: Торговый инструмент
            timeframe: Таймфрейм (константа MT5)
            start_date: Начало периода
            end_date: Конец периода
            
        Returns:
            DataFrame с данными OHLCV
        """
        pass

    @abstractmethod
    def get_realtime_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        """
        Получение котировок реального времени.
        
        Args:
            symbols: Список инструментов
            
        Returns:
            Словарь {symbol: quote_data}
        """
        pass

    @abstractmethod
    def get_news(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Получение новостей.
        
        Args:
            limit: Максимальное количество
            
        Returns:
            Список новостей
        """
        pass

    @abstractmethod
    def refresh_rates(self, symbols: List[str]) -> bool:
        """
        Обновление котировок.
        
        Args:
            symbols: Список инструментов для обновления
            
        Returns:
            True если успешно
        """
        pass


# ===========================================
# Database Manager Interfaces
# ===========================================

class IDatabaseManager(ABC):
    """Интерфейс для работы с основной БД."""

    @abstractmethod
    def save_trade(self, trade_data: Dict[str, Any]) -> int:
        """
        Сохранение сделки.
        
        Args:
            trade_data: Данные сделки
            
        Returns:
            ID сохраненной сделки
        """
        pass

    @abstractmethod
    def get_trade_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """
        Получение истории сделок.
        
        Args:
            symbol: Фильтр по инструменту
            limit: Максимальное количество
            
        Returns:
            Список сделок
        """
        pass

    @abstractmethod
    def get_strategy_performance(self, strategy_name: str) -> Dict[str, Any]:
        """
        Получение статистики стратегии.
        
        Args:
            strategy_name: Название стратегии
            
        Returns:
            Статистика производительности
        """
        pass

    @abstractmethod
    def get_open_positions(self) -> List[Dict]:
        """
        Получение открытых позиций.
        
        Returns:
            Список открытых позиций
        """
        pass


class IVectorDBManager(ABC):
    """Интерфейс для работы с векторной БД."""

    @abstractmethod
    def add_documents(self, documents: List[Dict[str, Any]]) -> bool:
        """
        Добавление документов.
        
        Args:
            documents: Список документов
            
        Returns:
            True если успешно
        """
        pass

    @abstractmethod
    def query_similar(
        self,
        query_text: str,
        n_results: int = 5,
        threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Поиск похожих документов.
        
        Args:
            query_text: Текст запроса
            n_results: Количество результатов
            threshold: Порог схожести
            
        Returns:
            Список похожих документов
        """
        pass

    @abstractmethod
    def cleanup_old_documents(self, max_age_days: int = 90) -> int:
        """
        Очистка старых документов.
        
        Args:
            max_age_days: Максимальный возраст в днях
            
        Returns:
            Количество удаленных документов
        """
        pass


# ===========================================
# Risk Engine Interface
# ===========================================

class IRiskEngine(ABC):
    """Интерфейс для управления рисками."""

    @abstractmethod
    def calculate_position_size(
        self,
        symbol: str,
        df: pd.DataFrame,
        account_info: Any,
        trade_type: str,
        confidence: str,
        strategy_name: str
    ) -> tuple:
        """
        Расчет размера позиции.
        
        Args:
            symbol: Торговый инструмент
            df: Данные для анализа
            account_info: Информация об аккаунте
            trade_type: Тип сделки (BUY/SELL)
            confidence: Уровень уверенности
            strategy_name: Название стратегии
            
        Returns:
            (lot_size, stop_loss) или (None, None) если запрещено
        """
        pass

    @abstractmethod
    def is_trade_safe(self, symbol: str, signal: Dict[str, Any]) -> bool:
        """
        Проверка безопасности сделки.
        
        Args:
            symbol: Торговый инструмент
            signal: Данные сигнала
            
        Returns:
            True если сделка безопасна
        """
        pass

    @abstractmethod
    def calculate_portfolio_var(
        self,
        open_positions: List[Dict],
        data_dict: Dict[str, pd.DataFrame]
    ) -> Optional[float]:
        """
        Расчет VaR портфеля.
        
        Args:
            open_positions: Открытые позиции
            data_dict: Рыночные данные
            
        Returns:
            Portfolio VaR в процентах
        """
        pass

    @abstractmethod
    def check_daily_drawdown(self) -> bool:
        """
        Проверка дневного лимита просадки.
        
        Returns:
            True если лимит не превышен
        """
        pass

    @abstractmethod
    def check_correlation(self, symbol: str) -> bool:
        """
        Проверка корреляции с открытыми позициями.
        
        Args:
            symbol: Торговый инструмент
            
        Returns:
            True если корреляция в норме
        """
        pass


# ===========================================
# Trading System Interfaces
# ===========================================

class ITradingSystem(ABC):
    """Интерфейс торговой системы."""

    @abstractmethod
    def start(self) -> bool:
        """
        Запуск системы.
        
        Returns:
            True если успешно
        """
        pass

    @abstractmethod
    def stop(self) -> bool:
        """
        Остановка системы.
        
        Returns:
            True если успешно
        """
        pass

    @abstractmethod
    def execute_trade(self, signal: Dict[str, Any]) -> bool:
        """
        Исполнение торгового сигнала.
        
        Args:
            signal: Данные сигнала
            
        Returns:
            True если сделка исполнена
        """
        pass

    @abstractmethod
    def close_position(self, ticket: int) -> bool:
        """
        Закрытие позиции.
        
        Args:
            ticket: Номер тикета
            
        Returns:
            True если успешно
        """
        pass

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """
        Получение информации об аккаунте.
        
        Returns:
            Данные аккаунта
        """
        pass


# ===========================================
# Strategy Interface
# ===========================================

class IStrategy(ABC):
    """Интерфейс торговой стратегии."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Название стратегии."""
        pass

    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Генерация торгового сигнала.
        
        Args:
            symbol: Торговый инструмент
            df: Рыночные данные
            context: Дополнительный контекст
            
        Returns:
            Данные сигнала или None
        """
        pass

    @abstractmethod
    def get_parameters(self) -> Dict[str, Any]:
        """
        Получение параметров стратегии.
        
        Returns:
            Словарь параметров
        """
        pass

    @abstractmethod
    def set_parameters(self, parameters: Dict[str, Any]) -> None:
        """
        Установка параметров стратегии.
        
        Args:
            parameters: Новые параметры
        """
        pass


# ===========================================
# Model Factory Interface
# ===========================================

class IModelFactory(ABC):
    """Интерфейс фабрики ML моделей."""

    @abstractmethod
    def create_model(self, model_type: str, **kwargs) -> Any:
        """
        Создание модели.
        
        Args:
            model_type: Тип модели
            **kwargs: Дополнительные параметры
            
        Returns:
            Экземпляр модели
        """
        pass

    @abstractmethod
    def load_model(self, model_id: int) -> Any:
        """
        Загрузка модели из БД.
        
        Args:
            model_id: ID модели
            
        Returns:
            Загруженная модель
        """
        pass

    @abstractmethod
    def save_model(self, model: Any, symbol: str, timeframe: int) -> int:
        """
        Сохранение модели в БД.
        
        Args:
            model: Модель для сохранения
            symbol: Торговый инструмент
            timeframe: Таймфрейм
            
        Returns:
            ID сохраненной модели
        """
        pass


# ===========================================
# Event Bus Interface
# ===========================================

class IEventBus(ABC):
    """Интерфейс шины событий."""

    @abstractmethod
    def subscribe(self, event_type: str, callback: callable) -> None:
        """
        Подписка на событие.
        
        Args:
            event_type: Тип события
            callback: Функция обратного вызова
        """
        pass

    @abstractmethod
    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Публикация события.
        
        Args:
            event_type: Тип события
            data: Данные события
        """
        pass

    @abstractmethod
    def unsubscribe(self, event_type: str, callback: callable) -> None:
        """
        Отписка от события.
        
        Args:
            event_type: Тип события
            callback: Функция обратного вызова
        """
        pass


# ===========================================
# Cache Manager Interface
# ===========================================

class ICacheManager(ABC):
    """Интерфейс менеджера кэша."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """
        Получение значения из кэша.
        
        Args:
            key: Ключ кэша
            
        Returns:
            Значение или None
        """
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Установка значения в кэш.
        
        Args:
            key: Ключ кэша
            value: Значение
            ttl: Время жизни в секундах
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Удаление значения из кэша.
        
        Args:
            key: Ключ кэша
            
        Returns:
            True если удалено
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """Очистка всего кэша."""
        pass
