# tests/unit/test_cqrs.py
"""
Unit тесты для CQRS компонентов.

Проверяет:
- Query Manager (чтение)
- Command Manager (запись)
- Корректность операций
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.query_manager import QueryManager
from src.db.command_manager import CommandManager
from src.db.database_manager import Base, TradeHistory, TradeAudit


class TestQueryManager:
    """Тесты для Query Manager."""
    
    @pytest.fixture
    def test_session(self):
        """Тестовая сессия БД."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        yield session
        
        session.close()
    
    @pytest.fixture
    def query_manager(self, test_session):
        """Query Manager с тестовой сессией."""
        Session = sessionmaker(bind=test_session.get_bind())
        return QueryManager(Session)
    
    @pytest.fixture
    def sample_trades(self, test_session):
        """Пример данных для тестов."""
        trades = [
            TradeHistory(
                ticket=1001,
                symbol="EURUSD",
                strategy="BreakoutStrategy",
                trade_type="BUY",
                volume=0.1,
                price_open=1.1000,
                price_close=1.1050,
                time_open=datetime.now() - timedelta(hours=2),
                time_close=datetime.now() - timedelta(hours=1),
                profit=50.0,
                timeframe="H1"
            ),
            TradeHistory(
                ticket=1002,
                symbol="GBPUSD",
                strategy="MeanReversionStrategy",
                trade_type="SELL",
                volume=0.2,
                price_open=1.3000,
                price_close=1.2980,
                time_open=datetime.now() - timedelta(hours=3),
                time_close=datetime.now() - timedelta(hours=2),
                profit=40.0,
                timeframe="H1"
            ),
            TradeHistory(
                ticket=1003,
                symbol="EURUSD",
                strategy="BreakoutStrategy",
                trade_type="BUY",
                volume=0.1,
                price_open=1.1050,
                price_close=1.1030,
                time_open=datetime.now() - timedelta(hours=1),
                time_close=datetime.now(),
                profit=-20.0,
                timeframe="H1"
            )
        ]
        
        for trade in trades:
            test_session.add(trade)
        test_session.commit()
        
        return trades
    
    def test_get_trade_history(self, query_manager, sample_trades):
        """Получение истории сделок."""
        df = query_manager.get_trade_history(limit=10)
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert 'ticket' in df.columns
        assert 'symbol' in df.columns
        assert 'profit' in df.columns
    
    def test_get_trade_history_filter_symbol(self, query_manager, sample_trades):
        """Фильтрация по символу."""
        df = query_manager.get_trade_history(symbol="EURUSD")
        
        assert len(df) == 2
        assert all(df['symbol'] == 'EURUSD')
    
    def test_get_trade_history_filter_strategy(self, query_manager, sample_trades):
        """Фильтрация по стратегии."""
        df = query_manager.get_trade_history(strategy_name="BreakoutStrategy")
        
        assert len(df) == 2
        assert all(df['strategy'] == 'BreakoutStrategy')
    
    def test_get_closed_trades_today(self, query_manager, sample_trades):
        """Сегодняшние сделки."""
        df = query_manager.get_closed_trades_today()
        
        # Все сделки из sample_trades сегодня
        assert len(df) > 0
    
    def test_get_strategy_statistics(self, query_manager, sample_trades):
        """Статистика стратегии."""
        stats = query_manager.get_strategy_statistics("BreakoutStrategy")
        
        assert stats['strategy_name'] == "BreakoutStrategy"
        assert stats['total_trades'] == 2
        assert stats['total_profit'] == 30.0  # 50 - 20
        assert stats['win_rate'] == 0.5  # 1 win, 1 loss
    
    def test_get_portfolio_metrics(self, query_manager, sample_trades):
        """Метрики портфеля."""
        metrics = query_manager.get_portfolio_metrics()
        
        assert 'total_profit' in metrics
        assert 'strategy_profit' in metrics
        assert 'symbol_profit' in metrics
        assert metrics['total_profit'] == 70.0  # 50 + 40 - 20
    
    def test_get_symbol_performance(self, query_manager, sample_trades):
        """Производительность символа."""
        perf = query_manager.get_symbol_performance("EURUSD")
        
        assert perf['symbol'] == "EURUSD"
        assert perf['total_trades'] == 2
        assert perf['total_profit'] == 30.0  # 50 - 20
    
    def test_get_audit_logs_empty(self, query_manager):
        """Получение audit логов (пусто)."""
        df = query_manager.get_audit_logs()
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
    
    def test_get_audit_statistics_empty(self, query_manager):
        """Статистика аудита (пусто)."""
        stats = query_manager.get_audit_statistics()
        
        assert stats['total_audits'] == 0
        assert stats['executed'] == 0
        assert stats['rejected'] == 0


class TestCommandManager:
    """Тесты для Command Manager."""
    
    @pytest.fixture
    def test_session(self):
        """Тестовая сессия БД."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        yield session
        
        session.close()
    
    @pytest.fixture
    def command_manager(self, test_session):
        """Command Manager с тестовой сессией."""
        Session = sessionmaker(bind=test_session.get_bind())
        return CommandManager(Session)
    
    def test_create_trade(self, command_manager):
        """Создание сделки."""
        trade_data = {
            'ticket': 12345,
            'symbol': 'EURUSD',
            'strategy': 'TestStrategy',
            'trade_type': 'BUY',
            'volume': 0.1,
            'price_open': 1.1000,
            'time_open': datetime.now(),
            'timeframe': 'H1'
        }
        
        trade_id = command_manager.create_trade(trade_data)
        
        assert trade_id is not None
        assert trade_id > 0
    
    def test_update_trade_close(self, command_manager):
        """Обновление сделки при закрытии."""
        # Сначала создаем
        trade_data = {
            'ticket': 12346,
            'symbol': 'EURUSD',
            'strategy': 'TestStrategy',
            'trade_type': 'BUY',
            'volume': 0.1,
            'price_open': 1.1000,
            'time_open': datetime.now(),
            'timeframe': 'H1'
        }
        command_manager.create_trade(trade_data)
        
        # Обновляем при закрытии
        result = command_manager.update_trade_close(
            ticket=12346,
            exit_price=1.1050,
            profit=50.0,
            close_reason="TP"
        )
        
        assert result is True
    
    def test_delete_trade(self, command_manager):
        """Удаление сделки."""
        # Создаем
        trade_data = {
            'ticket': 12347,
            'symbol': 'EURUSD',
            'strategy': 'TestStrategy',
            'trade_type': 'BUY',
            'volume': 0.1,
            'price_open': 1.1000,
            'time_open': datetime.now(),
            'timeframe': 'H1'
        }
        command_manager.create_trade(trade_data)
        
        # Удаляем
        result = command_manager.delete_trade(12347)
        assert result is True
    
    def test_create_audit_log(self, command_manager):
        """Создание audit записи."""
        audit_id = command_manager.create_audit_log(
            trade_ticket=12345,
            decision_maker="AI_Model",
            strategy_name="BreakoutStrategy",
            market_regime="Strong Trend",
            consensus_score=0.75,
            risk_checks={
                "pre_mortem_passed": True,
                "var_check_passed": True
            },
            execution_status="EXECUTED",
            execution_time_ms=125.5
        )
        
        assert audit_id is not None
        assert audit_id > 0
    
    def test_upsert_strategy_performance_new(self, command_manager):
        """Создание записи производительности."""
        perf_id = command_manager.upsert_strategy_performance(
            strategy_name="TestStrategy",
            symbol="EURUSD",
            market_regime="Strong Trend",
            profit_factor=2.5,
            win_rate=0.65,
            trade_count=100
        )
        
        assert perf_id is not None
        assert perf_id > 0
    
    def test_upsert_strategy_performance_update(self, command_manager):
        """Обновление записи производительности."""
        # Создаем
        command_manager.upsert_strategy_performance(
            strategy_name="TestStrategy",
            symbol="EURUSD",
            market_regime="Strong Trend",
            profit_factor=2.5,
            win_rate=0.65,
            trade_count=100
        )
        
        # Обновляем
        perf_id = command_manager.upsert_strategy_performance(
            strategy_name="TestStrategy",
            symbol="EURUSD",
            market_regime="Strong Trend",
            profit_factor=3.0,
            win_rate=0.70,
            trade_count=150
        )
        
        assert perf_id is not None
    
    def test_update_strategy_status(self, command_manager):
        """Обновление статуса стратегии."""
        # Создаем
        command_manager.upsert_strategy_performance(
            strategy_name="TestStrategy",
            symbol="EURUSD",
            market_regime="Strong Trend",
            profit_factor=2.5,
            win_rate=0.65,
            trade_count=100,
            status="live"
        )
        
        # Обновляем статус
        result = command_manager.update_strategy_status(
            strategy_name="TestStrategy",
            symbol="EURUSD",
            market_regime="Strong Trend",
            status="paused"
        )
        
        assert result is True
    
    def test_bulk_create_trades(self, command_manager):
        """Массовое создание сделок."""
        trades_data = [
            {
                'ticket': 2001 + i,
                'symbol': 'EURUSD',
                'strategy': 'TestStrategy',
                'trade_type': 'BUY',
                'volume': 0.1,
                'price_open': 1.1000,
                'time_open': datetime.now(),
                'timeframe': 'H1'  # Добавлено timeframe
            }
            for i in range(5)
        ]
        
        count = command_manager.bulk_create_trades(trades_data)
        
        assert count == 5
