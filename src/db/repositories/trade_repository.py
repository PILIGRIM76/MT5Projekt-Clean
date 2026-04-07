# src/db/repositories/trade_repository.py
"""
TradeRepository — работа с историей сделок и аудитом.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import TradeAudit, TradeHistory

logger = logging.getLogger(__name__)


class TradeRepository:
    """Репозиторий для управления торговыми операциями."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def save_trade(self, trade_data: Dict[str, Any]) -> int:
        """Сохранить сделку в историю."""
        session: Session = self.session_factory()
        try:
            trade = TradeHistory(
                ticket=trade_data.get("ticket"),
                symbol=trade_data.get("symbol"),
                strategy=trade_data.get("strategy", "External"),
                trade_type=trade_data.get("trade_type"),
                volume=trade_data.get("volume"),
                price_open=trade_data.get("price_open"),
                price_close=trade_data.get("price_close"),
                time_open=trade_data.get("time_open"),
                time_close=trade_data.get("time_close"),
                profit=trade_data.get("profit"),
                timeframe=trade_data.get("timeframe"),
                xai_data=trade_data.get("xai_data"),
                market_regime=trade_data.get("market_regime"),
                news_sentiment=trade_data.get("news_sentiment"),
                volatility_metric=trade_data.get("volatility_metric"),
            )
            session.add(trade)
            session.commit()
            return trade.id
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении сделки {trade_data.get('ticket')}: {e}")
            return -1
        finally:
            session.close()

    def save_audit(self, audit_data: Dict[str, Any]) -> int:
        """Сохранить запись аудита."""
        session: Session = self.session_factory()
        try:
            audit = TradeAudit(
                trade_ticket=audit_data.get("trade_ticket"),
                decision_maker=audit_data.get("decision_maker"),
                strategy_name=audit_data.get("strategy_name"),
                market_regime=audit_data.get("market_regime"),
                capital_allocation=audit_data.get("capital_allocation"),
                consensus_score=audit_data.get("consensus_score"),
                kg_sentiment=audit_data.get("kg_sentiment"),
                risk_checks=json.dumps(audit_data.get("risk_checks", {})),
                account_balance=audit_data.get("account_balance"),
                account_equity=audit_data.get("account_equity"),
                open_positions_count=audit_data.get("open_positions_count"),
                portfolio_var=audit_data.get("portfolio_var"),
                execution_status=audit_data.get("execution_status"),
                rejection_reason=audit_data.get("rejection_reason"),
                execution_time_ms=audit_data.get("execution_time_ms"),
            )
            session.add(audit)
            session.commit()
            return audit.id
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении аудита: {e}")
            return -1
        finally:
            session.close()

    def get_recent_trades(self, limit: int = 100) -> List[TradeHistory]:
        """Получить последние сделки."""
        session: Session = self.session_factory()
        try:
            return session.query(TradeHistory).order_by(TradeHistory.time_close.desc()).limit(limit).all()
        finally:
            session.close()

    def get_trade_stats(self, symbol: str = None) -> Dict[str, Any]:
        """Получить статистику торговли."""
        session: Session = self.session_factory()
        try:
            query = session.query(
                func.count(TradeHistory.id).label("total_trades"),
                func.avg(TradeHistory.profit).label("avg_profit"),
                func.sum(TradeHistory.profit).label("total_profit"),
            )
            if symbol:
                query = query.filter(TradeHistory.symbol == symbol)
            result = query.first()
            return {
                "total_trades": result.total_trades if result else 0,
                "avg_profit": float(result.avg_profit) if result and result.avg_profit else 0,
                "total_profit": float(result.total_profit) if result and result.total_profit else 0,
            }
        finally:
            session.close()
