# src/db/command_manager.py
"""
CQRS: Command Manager - только запись.

Оптимизирован для операций создания, обновления и удаления.
Не возвращает данные, только статусы операций.
"""

from sqlalchemy.orm import Session, sessionmaker
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import json

from .database_manager import TradeHistory, TradeAudit, StrategyPerformance

logger = logging.getLogger(__name__)


class CommandManager:
    """
    Менеджер команд (только запись).
    
    Ответственность:
    - Создание записей
    - Обновление записей
    - Удаление записей
    - Транзакции
    """
    
    def __init__(self, session_factory: sessionmaker):
        """
        Инициализация Command Manager.
        
        Args:
            session_factory: Фабрика сессий SQLAlchemy
        """
        self.session_factory = session_factory
        logger.info("CommandManager инициализирован")
    
    # ===========================================
    # Trade History Commands
    # ===========================================
    
    def create_trade(self, trade_data: Dict[str, Any]) -> Optional[int]:
        """
        Создание записи о сделке.
        
        Args:
            trade_data: Данные сделки
            
        Returns:
            ID созданной сделки или None при ошибке
            
        Example:
            command_manager.create_trade({
                'ticket': 12345,
                'symbol': 'EURUSD',
                'strategy': 'BreakoutStrategy',
                'trade_type': 'BUY',
                'volume': 0.1,
                'price_open': 1.1000,
                'time_open': datetime.now(),
                'timeframe': 'H1'
            })
        """
        with self.session_factory() as session:
            try:
                trade = TradeHistory(
                    ticket=trade_data['ticket'],
                    symbol=trade_data['symbol'],
                    strategy=trade_data.get('strategy', 'External'),
                    trade_type=trade_data['trade_type'],
                    volume=trade_data['volume'],
                    price_open=trade_data['price_open'],
                    price_close=trade_data.get('price_close', trade_data['price_open']),
                    time_open=trade_data['time_open'],
                    time_close=trade_data.get('time_close', datetime.utcnow()),
                    profit=trade_data.get('profit', 0),
                    timeframe=trade_data['timeframe'],
                    xai_data=json.dumps(trade_data.get('xai_data')) if trade_data.get('xai_data') else None,
                    market_regime=trade_data.get('market_regime'),
                    news_sentiment=trade_data.get('news_sentiment'),
                    volatility_metric=trade_data.get('volatility_metric')
                )
                
                session.add(trade)
                session.commit()
                session.refresh(trade)
                
                logger.info(f"Создана запись о сделке #{trade.ticket}")
                return trade.id
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка создания сделки: {e}", exc_info=True)
                return None
    
    def update_trade_close(
        self,
        ticket: int,
        exit_price: float,
        profit: float,
        close_time: Optional[datetime] = None,
        close_reason: str = "TP/SL"
    ) -> bool:
        """
        Обновление сделки при закрытии.
        
        Args:
            ticket: Тикет сделки
            exit_price: Цена закрытия
            profit: Прибыль/убыток
            close_time: Время закрытия
            close_reason: Причина закрытия
            
        Returns:
            True если успешно
        """
        with self.session_factory() as session:
            try:
                trade = session.query(TradeHistory).filter_by(ticket=ticket).first()
                
                if not trade:
                    logger.warning(f"Сделка #{ticket} не найдена для обновления")
                    return False
                
                trade.exit_price = exit_price
                trade.close_time = close_time or datetime.utcnow()
                trade.profit = profit
                trade.close_reason = close_reason
                
                session.commit()
                logger.info(f"Обновлена сделка #{ticket}: profit={profit}")
                return True
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка обновления сделки #{ticket}: {e}", exc_info=True)
                return False
    
    def delete_trade(self, ticket: int) -> bool:
        """
        Удаление сделки.
        
        Args:
            ticket: Тикет сделки
            
        Returns:
            True если успешно
        """
        with self.session_factory() as session:
            try:
                trade = session.query(TradeHistory).filter_by(ticket=ticket).first()
                
                if not trade:
                    return False
                
                session.delete(trade)
                session.commit()
                
                logger.info(f"Удалена сделка #{ticket}")
                return True
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка удаления сделки #{ticket}: {e}", exc_info=True)
                return False
    
    # ===========================================
    # Audit Log Commands
    # ===========================================
    
    def create_audit_log(
        self,
        trade_ticket: int,
        decision_maker: str,
        strategy_name: Optional[str] = None,
        market_regime: Optional[str] = None,
        capital_allocation: Optional[float] = None,
        consensus_score: Optional[float] = None,
        kg_sentiment: Optional[float] = None,
        risk_checks: Optional[Dict[str, bool]] = None,
        account_balance: Optional[float] = None,
        account_equity: Optional[float] = None,
        open_positions_count: Optional[int] = None,
        portfolio_var: Optional[float] = None,
        execution_status: str = "EXECUTED",
        rejection_reason: Optional[str] = None,
        execution_time_ms: Optional[float] = None
    ) -> Optional[int]:
        """
        Создание записи аудита.
        
        Args:
            trade_ticket: Тикет сделки
            decision_maker: Источник решения
            strategy_name: Название стратегии
            market_regime: Режим рынка
            capital_allocation: Аллокация капитала
            consensus_score: Уверенность
            kg_sentiment: Сентимент KG
            risk_checks: Проверки риска
            account_balance: Баланс
            account_equity: Эквити
            open_positions_count: Открытые позиции
            portfolio_var: Portfolio VaR
            execution_status: Статус исполнения
            rejection_reason: Причина отклонения
            execution_time_ms: Время исполнения
            
        Returns:
            ID записи аудита или None
        """
        with self.session_factory() as session:
            try:
                audit = TradeAudit(
                    trade_ticket=trade_ticket,
                    decision_maker=decision_maker,
                    strategy_name=strategy_name,
                    market_regime=market_regime,
                    capital_allocation=capital_allocation,
                    consensus_score=consensus_score,
                    kg_sentiment=kg_sentiment,
                    risk_checks=json.dumps(risk_checks) if risk_checks else None,
                    account_balance=account_balance,
                    account_equity=account_equity,
                    open_positions_count=open_positions_count,
                    portfolio_var=portfolio_var,
                    execution_status=execution_status,
                    rejection_reason=rejection_reason,
                    execution_time_ms=execution_time_ms
                )
                
                session.add(audit)
                session.commit()
                session.refresh(audit)
                
                logger.info(f"Создан audit log для сделки #{trade_ticket}: {execution_status}")
                return audit.id
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка создания audit log: {e}", exc_info=True)
                return None
    
    # ===========================================
    # Strategy Performance Commands
    # ===========================================
    
    def upsert_strategy_performance(
        self,
        strategy_name: str,
        symbol: str,
        market_regime: str,
        profit_factor: float,
        win_rate: float,
        trade_count: int,
        status: str = "live"
    ) -> Optional[int]:
        """
        Обновление или создание записи производительности стратегии.
        
        Args:
            strategy_name: Название стратегии
            symbol: Инструмент
            market_regime: Режим рынка
            profit_factor: Профит-фактор
            win_rate: Win rate
            trade_count: Количество сделок
            status: Статус
            
        Returns:
            ID записи или None
        """
        with self.session_factory() as session:
            try:
                # Попытка найти существующую запись
                perf = session.query(StrategyPerformance).filter_by(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    market_regime=market_regime
                ).first()
                
                if perf:
                    # Обновление
                    perf.profit_factor = profit_factor
                    perf.win_rate = win_rate
                    perf.trade_count = trade_count
                    perf.status = status
                    perf.last_updated = datetime.utcnow()
                else:
                    # Создание
                    perf = StrategyPerformance(
                        strategy_name=strategy_name,
                        symbol=symbol,
                        market_regime=market_regime,
                        profit_factor=profit_factor,
                        win_rate=win_rate,
                        trade_count=trade_count,
                        status=status
                    )
                    session.add(perf)
                
                session.commit()
                
                if not perf.id:
                    session.refresh(perf)
                
                logger.info(
                    f"{'Обновлена' if perf else 'Создана'} запись производительности "
                    f"для {strategy_name} на {symbol}"
                )
                return perf.id
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка upsert производительности стратегии: {e}", exc_info=True)
                return None
    
    def update_strategy_status(
        self,
        strategy_name: str,
        symbol: str,
        market_regime: str,
        status: str
    ) -> bool:
        """
        Обновление статуса стратегии.
        
        Args:
            strategy_name: Название стратегии
            symbol: Инструмент
            market_regime: Режим рынка
            status: Новый статус
            
        Returns:
            True если успешно
        """
        with self.session_factory() as session:
            try:
                perf = session.query(StrategyPerformance).filter_by(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    market_regime=market_regime
                ).first()
                
                if perf:
                    perf.status = status
                    perf.last_updated = datetime.utcnow()
                    session.commit()
                    logger.info(f"Статус стратегии {strategy_name} обновлен на {status}")
                    return True
                else:
                    logger.warning(f"Производительность стратегии {strategy_name} не найдена")
                    return False
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка обновления статуса стратегии: {e}", exc_info=True)
                return False
    
    # ===========================================
    # Bulk Operations
    # ===========================================
    
    def bulk_create_trades(self, trades_data: List[Dict[str, Any]]) -> int:
        """
        Массовое создание сделок.
        
        Args:
            trades_data: Список данных сделок
            
        Returns:
            Количество успешно созданных сделок
        """
        with self.session_factory() as session:
            success_count = 0
            
            try:
                for trade_data in trades_data:
                    trade = TradeHistory(
                        ticket=trade_data['ticket'],
                        symbol=trade_data['symbol'],
                        strategy=trade_data.get('strategy', 'External'),
                        trade_type=trade_data['trade_type'],
                        volume=trade_data['volume'],
                        price_open=trade_data['price_open'],
                        price_close=trade_data.get('price_close', trade_data['price_open']),
                        time_open=trade_data['time_open'],
                        time_close=trade_data.get('time_close', datetime.utcnow()),
                        profit=trade_data.get('profit', 0),
                        timeframe=trade_data['timeframe']
                    )
                    session.add(trade)
                    success_count += 1
                
                session.commit()
                logger.info(f"Массово создано {success_count} сделок")
                return success_count
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка массового создания сделок: {e}", exc_info=True)
                return success_count
    
    def bulk_update_strategy_status(
        self,
        updates: List[Dict[str, str]]
    ) -> int:
        """
        Массовое обновление статусов стратегий.
        
        Args:
            updates: Список обновлений
                [{'strategy_name': ..., 'symbol': ..., 'market_regime': ..., 'status': ...}]
            
        Returns:
            Количество успешно обновленных
        """
        with self.session_factory() as session:
            success_count = 0
            
            try:
                for update in updates:
                    perf = session.query(StrategyPerformance).filter_by(
                        strategy_name=update['strategy_name'],
                        symbol=update['symbol'],
                        market_regime=update['market_regime']
                    ).first()
                    
                    if perf:
                        perf.status = update['status']
                        perf.last_updated = datetime.utcnow()
                        success_count += 1
                
                session.commit()
                logger.info(f"Массово обновлено {success_count} статусов стратегий")
                return success_count
                
            except Exception as e:
                session.rollback()
                logger.error(f"Ошибка массового обновления статусов: {e}", exc_info=True)
                return success_count
