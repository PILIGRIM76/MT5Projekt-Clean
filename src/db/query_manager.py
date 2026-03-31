# src/db/query_manager.py
"""
CQRS: Query Manager - только чтение.

Оптимизирован для выполнения запросов и аналитики.
Возвращает pandas DataFrame для удобной обработки данных.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker

from .database_manager import StrategyPerformance, TradeAudit, TradeHistory

logger = logging.getLogger(__name__)


class QueryManager:
    """
    Менеджер запросов (только чтение).

    Ответственность:
    - Чтение данных из БД
    - Аналитика и агрегация
    - Возврат данных в формате DataFrame
    """

    def __init__(self, session_factory: sessionmaker):
        """
        Инициализация Query Manager.

        Args:
            session_factory: Фабрика сессий SQLAlchemy
        """
        self.session_factory = session_factory
        logger.info("QueryManager инициализирован")

    # ===========================================
    # Trade History Queries
    # ===========================================

    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        strategy_name: Optional[str] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Получение истории сделок.

        Args:
            symbol: Фильтр по инструменту
            start_date: Начало периода
            end_date: Конец периода
            strategy_name: Фильтр по стратегии
            limit: Максимальное количество

        Returns:
            DataFrame с историей сделок
        """
        with self.session_factory() as session:
            query = select(TradeHistory).order_by(TradeHistory.time_close.desc()).limit(limit)

            if symbol:
                query = query.where(TradeHistory.symbol == symbol)

            if start_date:
                query = query.where(TradeHistory.time_close >= start_date)

            if end_date:
                query = query.where(TradeHistory.time_close <= end_date)

            if strategy_name:
                query = query.where(TradeHistory.strategy == strategy_name)

            results = session.execute(query).scalars().all()

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(
                [
                    {
                        "id": r.id,
                        "ticket": r.ticket,
                        "symbol": r.symbol,
                        "strategy": r.strategy,
                        "trade_type": r.trade_type,
                        "volume": r.volume,
                        "price_open": r.price_open,
                        "price_close": r.price_close,
                        "time_open": r.time_open,
                        "time_close": r.time_close,
                        "profit": r.profit,
                        "timeframe": r.timeframe,
                        "market_regime": r.market_regime,
                        "news_sentiment": r.news_sentiment,
                    }
                    for r in results
                ]
            )

    def get_closed_trades_today(self) -> pd.DataFrame:
        """
        Получение сделок, закрытых сегодня.

        Returns:
            DataFrame с сегодняшними сделками
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.get_trade_history(start_date=today)

    # ===========================================
    # Strategy Performance Queries
    # ===========================================

    def get_strategy_statistics(self, strategy_name: str) -> Dict[str, Any]:
        """
        Статистика стратегии.

        Args:
            strategy_name: Название стратегии

        Returns:
            Словарь со статистикой
        """
        with self.session_factory() as session:
            query = select(
                func.count(TradeHistory.id).label("total_trades"),
                func.sum(TradeHistory.profit).label("total_profit"),
                func.avg(TradeHistory.profit).label("avg_profit"),
                func.max(TradeHistory.profit).label("max_profit"),
                func.min(TradeHistory.profit).label("min_profit"),
                func.sum(case((TradeHistory.profit > 0, 1), else_=0)).label("wins"),
                func.sum(case((TradeHistory.profit <= 0, 1), else_=0)).label("losses"),
            ).where(TradeHistory.strategy == strategy_name)

            result = session.execute(query).one()

            total_trades = result.total_trades or 0
            wins = result.wins or 0
            losses = result.losses or 0

            win_rate = wins / total_trades if total_trades > 0 else 0
            profit_factor = abs(wins / losses) if losses > 0 else float("inf")

            return {
                "strategy_name": strategy_name,
                "total_trades": total_trades,
                "total_profit": result.total_profit or 0,
                "avg_profit": result.avg_profit or 0,
                "max_profit": result.max_profit or 0,
                "min_profit": result.min_profit or 0,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "wins": wins,
                "losses": losses,
            }

    def get_all_strategy_performance(self) -> pd.DataFrame:
        """
        Производительность всех стратегий.

        Returns:
            DataFrame с производительностью
        """
        with self.session_factory() as session:
            query = select(StrategyPerformance).order_by(StrategyPerformance.profit_factor.desc())

            results = session.execute(query).scalars().all()

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(
                [
                    {
                        "strategy_name": r.strategy_name,
                        "symbol": r.symbol,
                        "market_regime": r.market_regime,
                        "profit_factor": r.profit_factor,
                        "win_rate": r.win_rate,
                        "trade_count": r.trade_count,
                        "status": r.status,
                    }
                    for r in results
                ]
            )

    # ===========================================
    # Portfolio Queries
    # ===========================================

    def get_portfolio_metrics(self) -> Dict[str, Any]:
        """
        Метрики портфеля.

        Returns:
            Словарь с метриками портфеля
        """
        with self.session_factory() as session:
            # Общая прибыль
            total_profit_query = select(func.sum(TradeHistory.profit))
            total_profit = session.execute(total_profit_query).scalar() or 0

            # Прибыль по стратегиям
            strategy_profit_query = select(TradeHistory.strategy, func.sum(TradeHistory.profit).label("profit")).group_by(
                TradeHistory.strategy
            )
            strategy_profit = {r.strategy: r.profit for r in session.execute(strategy_profit_query)}

            # Прибыль по символам
            symbol_profit_query = select(TradeHistory.symbol, func.sum(TradeHistory.profit).label("profit")).group_by(
                TradeHistory.symbol
            )
            symbol_profit = {r.symbol: r.profit for r in session.execute(symbol_profit_query)}

            # Сегодняшняя прибыль
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_profit_query = select(func.sum(TradeHistory.profit)).where(TradeHistory.time_close >= today)
            today_profit = session.execute(today_profit_query).scalar() or 0

            return {
                "total_profit": total_profit,
                "strategy_profit": strategy_profit,
                "symbol_profit": symbol_profit,
                "today_profit": today_profit,
                "total_trades": session.query(TradeHistory).count(),
            }

    def get_symbol_performance(self, symbol: str) -> Dict[str, Any]:
        """
        Производительность по символу.

        Args:
            symbol: Торговый инструмент

        Returns:
            Словарь с метриками
        """
        with self.session_factory() as session:
            query = select(
                func.count(TradeHistory.id).label("total_trades"),
                func.sum(TradeHistory.profit).label("total_profit"),
                func.avg(TradeHistory.profit).label("avg_profit"),
                func.max(TradeHistory.profit).label("max_profit"),
                func.min(TradeHistory.profit).label("min_profit"),
            ).where(TradeHistory.symbol == symbol)

            result = session.execute(query).one()

            return {
                "symbol": symbol,
                "total_trades": result.total_trades or 0,
                "total_profit": result.total_profit or 0,
                "avg_profit": result.avg_profit or 0,
                "max_profit": result.max_profit or 0,
                "min_profit": result.min_profit or 0,
            }

    # ===========================================
    # Audit Log Queries
    # ===========================================

    def get_audit_logs(
        self, trade_ticket: Optional[int] = None, execution_status: Optional[str] = None, limit: int = 100
    ) -> pd.DataFrame:
        """
        Получение записей аудита.

        Args:
            trade_ticket: Фильтр по тику сделки
            execution_status: Фильтр по статусу
            limit: Максимальное количество

        Returns:
            DataFrame с записями аудита
        """
        with self.session_factory() as session:
            query = select(TradeAudit).order_by(TradeAudit.timestamp.desc()).limit(limit)

            if trade_ticket:
                query = query.where(TradeAudit.trade_ticket == trade_ticket)

            if execution_status:
                query = query.where(TradeAudit.execution_status == execution_status)

            results = session.execute(query).scalars().all()

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(
                [
                    {
                        "id": r.id,
                        "trade_ticket": r.trade_ticket,
                        "timestamp": r.timestamp,
                        "decision_maker": r.decision_maker,
                        "strategy_name": r.strategy_name,
                        "market_regime": r.market_regime,
                        "consensus_score": r.consensus_score,
                        "execution_status": r.execution_status,
                        "rejection_reason": r.rejection_reason,
                        "execution_time_ms": r.execution_time_ms,
                    }
                    for r in results
                ]
            )

    def get_audit_statistics(self) -> Dict[str, Any]:
        """
        Статистика аудита.

        Returns:
            Словарь со статистикой
        """
        with self.session_factory() as session:
            total = session.query(TradeAudit).count()
            executed = session.query(TradeAudit).filter(TradeAudit.execution_status == "EXECUTED").count()
            rejected = session.query(TradeAudit).filter(TradeAudit.execution_status == "REJECTED").count()
            failed = session.query(TradeAudit).filter(TradeAudit.execution_status == "FAILED").count()

            return {
                "total_audits": total,
                "executed": executed,
                "rejected": rejected,
                "failed": failed,
                "execution_rate": executed / total if total > 0 else 0,
                "rejection_rate": rejected / total if total > 0 else 0,
            }

    # ===========================================
    # Analytics Queries
    # ===========================================

    def get_monthly_performance(self, year: int) -> pd.DataFrame:
        """
        Месячная производительность.

        Args:
            year: Год

        Returns:
            DataFrame с месячной производительностью
        """
        with self.session_factory() as session:
            query = (
                select(
                    func.strftime("%m", TradeHistory.time_close).label("month"),
                    func.sum(TradeHistory.profit).label("profit"),
                    func.count(TradeHistory.id).label("trades"),
                    func.avg(TradeHistory.profit).label("avg_profit"),
                )
                .where(func.strftime("%Y", TradeHistory.time_close) == str(year))
                .group_by(func.strftime("%m", TradeHistory.time_close))
                .order_by("month")
            )

            results = session.execute(query).all()

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(
                [{"month": int(r.month), "profit": r.profit, "trades": r.trades, "avg_profit": r.avg_profit} for r in results]
            )

    def get_drawdown_periods(self, threshold: float = -5.0) -> pd.DataFrame:
        """
        Периоды просадки.

        Args:
            threshold: Порог просадки в процентах

        Returns:
            DataFrame с периодами просадки
        """
        # Сложный запрос для определения периодов просадки
        # Упрощенная версия - возврат убыточных сделок
        with self.session_factory() as session:
            query = (
                select(TradeHistory.ticket, TradeHistory.symbol, TradeHistory.time_close, TradeHistory.profit)
                .where(TradeHistory.profit < threshold)
                .order_by(TradeHistory.time_close.desc())
                .limit(50)
            )

            results = session.execute(query).all()

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(
                [{"ticket": r.ticket, "symbol": r.symbol, "time_close": r.time_close, "profit": r.profit} for r in results]
            )
