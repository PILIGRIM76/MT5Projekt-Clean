# src/db/repositories/__init__.py
"""
Репозитории для работы с базой данных.
Каждый репозиторий отвечает за свою сущность.
"""

from src.db.repositories.model_repository import ModelRepository
from src.db.repositories.trade_repository import TradeRepository
from src.db.repositories.candle_repository import CandleRepository

__all__ = ["ModelRepository", "TradeRepository", "CandleRepository"]
