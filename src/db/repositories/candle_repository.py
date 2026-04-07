# src/db/repositories/candle_repository.py
"""
CandleRepository — работа со свечными данными.
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from src.db.models import CandleData

logger = logging.getLogger(__name__)


class CandleRepository:
    """Репозиторий для управления свечными данными."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def save_candle(self, candle_data: dict) -> bool:
        """Сохранить одну свечу."""
        session: Session = self.session_factory()
        try:
            candle = CandleData(
                symbol=candle_data["symbol"],
                timeframe=candle_data["timeframe"],
                timestamp=candle_data["timestamp"],
                open=candle_data["open"],
                high=candle_data["high"],
                low=candle_data["low"],
                close=candle_data["close"],
                tick_volume=candle_data.get("tick_volume"),
            )
            session.merge(candle)  # merge для избежания дубликатов
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении свечи: {e}")
            return False
        finally:
            session.close()

    def save_candles_batch(self, candles: List[dict]) -> int:
        """Пакетное сохранение свечей."""
        if not candles:
            return 0
        session: Session = self.session_factory()
        saved_count = 0
        try:
            for c in candles:
                candle = CandleData(
                    symbol=c["symbol"],
                    timeframe=c["timeframe"],
                    timestamp=c["timestamp"],
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    tick_volume=c.get("tick_volume"),
                )
                session.merge(candle)
                saved_count += 1
            session.commit()
            return saved_count
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при пакетном сохранении свечей: {e}")
            return 0
        finally:
            session.close()

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
        start_date: Optional[datetime] = None,
    ) -> List[CandleData]:
        """Получить свечи по символу и таймфрейму."""
        session: Session = self.session_factory()
        try:
            query = (
                session.query(CandleData)
                .filter_by(symbol=symbol, timeframe=timeframe)
                .order_by(CandleData.timestamp.asc())
            )
            if start_date:
                query = query.filter(CandleData.timestamp >= start_date)
            return query.limit(limit).all()
        finally:
            session.close()

    def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[CandleData]:
        """Получить последнюю свечу."""
        session: Session = self.session_factory()
        try:
            return (
                session.query(CandleData)
                .filter_by(symbol=symbol, timeframe=timeframe)
                .order_by(CandleData.timestamp.desc())
                .first()
            )
        finally:
            session.close()
