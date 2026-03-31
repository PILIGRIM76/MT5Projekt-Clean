# src/core/services/__init__.py
"""
Пакет сервисов Genesis Trading System.

Сервисы — это компоненты с управляемым жизненным циклом:
- start(): Запуск сервиса
- stop(): Остановка сервиса
- health_check(): Проверка здоровья

Доступные сервисы:
- BaseService: Абстрактный базовый класс
- DataService: Управление рыночными данными
- MLService: Машинное обучение (признаки, модели, предсказания)
- ExecutionService: Исполнение ордеров и управление рисками
"""

from src.core.services.base_service import BaseService
from src.core.services.data_service import DataService
from src.core.services.execution_service import ExecutionService
from src.core.services.ml_service import MLService

__all__ = [
    "BaseService",
    "DataService",
    "MLService",
    "ExecutionService",
]
