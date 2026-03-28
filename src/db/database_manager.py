# src/db/database_manager.py
import logging
import os
import pandas as pd
import pickle
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import Optional, List, Any, Tuple, Dict
import io
import queue
import numpy as np
import torch
import torch.nn as nn
from sqlalchemy import create_engine, Column, Integer, String, Float, LargeBinary, DateTime, Text, inspect, text, \
    UniqueConstraint, func, Boolean, event
from sqlalchemy.orm import sessionmaker, declarative_base, aliased
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError
from MetaTrader5 import ORDER_TYPE_BUY
from src.ml.architectures import TimeSeriesTransformer, SimpleLSTM
from src.core.config_models import Settings

KerasModel = None
lgb = None

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

logger = logging.getLogger(__name__)
Base = declarative_base()


class NewsArticle(Base):
    __tablename__ = 'news_articles'
    id = Column(Integer, primary_key=True)
    vector_id = Column(String, unique=True, nullable=False, index=True)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True)

    def __repr__(self):
        return f"<NewsArticle(id={self.id}, vector_id='{self.vector_id}', source='{self.source}')>"




class StrategicModel(Base):
    __tablename__ = 'strategic_models'
    id = Column(Integer, primary_key=True)
    model_data = Column(LargeBinary, nullable=False)
    training_date = Column(DateTime, default=datetime.utcnow)
    version = Column(Integer, default=1)
    features_json = Column(Text, nullable=True)
    classes_json = Column(Text, nullable=True)


class TrainedModel(Base):
    __tablename__ = 'trained_models'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(Integer, nullable=False)
    model_type = Column(String, nullable=False, default='LSTM', index=True)
    model_data = Column(LargeBinary, nullable=False)
    training_date = Column(DateTime, default=datetime.utcnow)
    version = Column(Integer, default=1)
    features_json = Column(Text, nullable=True)
    is_champion = Column(Boolean, default=False, nullable=False, index=True)
    performance_report = Column(Text, nullable=True)
    training_batch_id = Column(String, nullable=True, index=True)
    hyperparameters_json = Column(Text, nullable=True)


class Scaler(Base):
    __tablename__ = 'scalers'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, unique=True)
    x_scaler_data = Column(LargeBinary, nullable=False)
    y_scaler_data = Column(LargeBinary, nullable=False)


class TradeHistory(Base):
    __tablename__ = 'trade_history'
    id = Column(Integer, primary_key=True)
    ticket = Column(Integer, unique=True, nullable=False)
    symbol = Column(String, nullable=False)
    strategy = Column(String, nullable=True, default='External')

    trade_type = Column(String, nullable=False)
    volume = Column(Float, nullable=False)
    price_open = Column(Float, nullable=False)
    price_close = Column(Float, nullable=False)
    time_open = Column(DateTime, nullable=False)
    time_close = Column(DateTime, nullable=False)
    profit = Column(Float, nullable=False)
    timeframe = Column(String, nullable=False)
    xai_data = Column(Text, nullable=True)
    market_regime = Column(String, nullable=True)
    news_sentiment = Column(Float, nullable=True)
    volatility_metric = Column(Float, nullable=True)


class TradeAudit(Base):
    """
    Таблица аудита торговых решений.
    
    Сохраняет полный контекст принятия решения о сделке:
    - Кто принял решение (AI, стратегия, человек)
    - Обоснование решения (режим рынка, аллокация, сентимент)
    - Проверки риска (Pre-Mortem, VaR, корреляция, drawdown)
    - Контекст аккаунта (баланс, эквити, открытые позиции)
    - Результат исполнения (успех/отказ/ошибка, время исполнения)
    """
    __tablename__ = 'trade_audit'
    
    id = Column(Integer, primary_key=True)
    trade_ticket = Column(Integer, nullable=False, index=True, comment="Тикет сделки (связь с TradeHistory.ticket)")
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True, comment="Время аудита")
    
    # Кто принял решение
    decision_maker = Column(String, nullable=False, comment="Источник решения: AI_Model, RLTradeManager, ClassicStrategy, Human")
    strategy_name = Column(String, nullable=True, comment="Название стратегии")
    
    # Обоснование решения
    market_regime = Column(String, nullable=True, comment="Текущий режим рынка")
    capital_allocation = Column(Float, nullable=True, comment="Аллокация капитала для стратегии")
    consensus_score = Column(Float, nullable=True, comment="Оценка консенсуса (уверенность)")
    kg_sentiment = Column(Float, nullable=True, comment="Сентимент из Графа Знаний")
    
    # Проверки риска (JSON)
    risk_checks = Column(Text, nullable=True, comment="JSON с результатами проверок риска")
    # Формат: {
    #   "pre_mortem_passed": true,
    #   "var_check_passed": true,
    #   "correlation_check_passed": true,
    #   "daily_drawdown_ok": true
    # }
    
    # Контекст аккаунта
    account_balance = Column(Float, nullable=True, comment="Баланс аккаунта на момент решения")
    account_equity = Column(Float, nullable=True, comment="Эквити аккаунта на момент решения")
    open_positions_count = Column(Integer, nullable=True, comment="Количество открытых позиций")
    portfolio_var = Column(Float, nullable=True, comment="Portfolio VaR (99%)")
    
    # Результат
    execution_status = Column(String, nullable=False, comment="Статус: EXECUTED, REJECTED, FAILED")
    rejection_reason = Column(String, nullable=True, comment="Причина отклонения (если есть)")
    execution_time_ms = Column(Float, nullable=True, comment="Время исполнения в миллисекундах")
    
    def __repr__(self):
        return f"<TradeAudit(ticket={self.trade_ticket}, status={self.execution_status}, time={self.timestamp})>"


class StrategyPerformance(Base):
    __tablename__ = 'strategy_performance'
    id = Column(Integer, primary_key=True)
    strategy_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    market_regime = Column(String, nullable=False, index=True)
    profit_factor = Column(Float, nullable=False)
    win_rate = Column(Float, nullable=False)
    trade_count = Column(Integer, nullable=False)
    status = Column(String, default='live', nullable=False, index=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint('strategy_name', 'symbol', 'market_regime', name='_strategy_symbol_regime_uc'),)


class ActiveDirective(Base):
    __tablename__ = 'active_directives'
    id = Column(Integer, primary_key=True)
    directive_type = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class HumanFeedback(Base):
    __tablename__ = 'human_feedback'
    id = Column(Integer, primary_key=True)
    trade_ticket = Column(Integer, nullable=False, index=True)
    model_id = Column(Integer, nullable=True)
    feedback = Column(Integer, nullable=False)
    market_state_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Entity(Base):
    __tablename__ = 'entities'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)

    def __repr__(self):
        return f"<Entity(name='{self.name}', type='{self.entity_type}')>"


class Relation(Base):
    __tablename__ = 'relations'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    relation_type = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    context_json = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint('source_id', 'target_id', 'relation_type', 'timestamp', name='_relation_uc'),
    )

    def __repr__(self):
        return f"<Relation(source={self.source_id}, target={self.target_id}, type='{self.relation_type}')>"


class DatabaseManager:
    def __init__(self, config: Settings, write_queue: queue.Queue):
        db_folder = Path(config.DATABASE_FOLDER)
        db_folder.mkdir(exist_ok=True)
        db_path = db_folder / config.DATABASE_NAME

        self.engine = create_engine(f'sqlite:///{db_path}', connect_args={'timeout': 30})







        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                logger.info("Режим WAL для SQLite успешно активирован.")
            finally:
                cursor.close()

        self.Session = sessionmaker(bind=self.engine)
        self.config = config
        self.write_queue = write_queue
        self._check_and_migrate_schema()
        Base.metadata.create_all(self.engine)
        logger.info(f"DatabaseManager инициализирован. База данных: {db_path}")

    def load_champion_models(self, symbol: str, timeframe: int) -> Tuple[
        Optional[Dict[str, Any]], Optional[Any], Optional[Any]]:
        session = self.Session()
        try:
            model_types_query = session.query(TrainedModel.model_type).filter_by(symbol=symbol, timeframe=timeframe,
                                                                                 is_champion=True).distinct()
            model_types = [row[0] for row in model_types_query]
            champion_models = {}

            device = torch.device("cpu")
            logger.info(f"Загрузка моделей для {symbol} на устройство: {device}")

            for m_type in model_types:
                model_record = session.query(TrainedModel).filter_by(symbol=symbol, timeframe=timeframe,
                                                                     model_type=m_type, is_champion=True).order_by(
                    TrainedModel.version.desc()).first()
                if not model_record:
                    continue
                model = None
                try:
                    if "PyTorch" in m_type:
                        features = json.loads(model_record.features_json) if model_record.features_json else []
                        input_dim = len(features)
                        params = json.loads(
                            model_record.hyperparameters_json) if model_record.hyperparameters_json else {}

                        if model_record.model_type == 'LSTM_PyTorch':
                            model = SimpleLSTM(
                                input_dim=input_dim,
                                hidden_dim=params.get('hidden_dim', 64),
                                num_layers=params.get('num_layers', 2),
                                output_dim=1
                            ).to(device)
                        elif model_record.model_type == 'Transformer_PyTorch':
                            model = TimeSeriesTransformer(
                                input_dim=input_dim,
                                d_model=params.get('d_model', 64),
                                nhead=params.get('nhead', 4),
                                nlayers=params.get('nlayers', 2)
                            ).to(device)
                        else:
                            logger.error(f"Неизвестный PyTorch тип модели: {model_record.model_type}")
                            continue

                        buffer = io.BytesIO(model_record.model_data)
                        model.load_state_dict(torch.load(buffer, map_location='cpu'))
                        model.eval()
                    elif lgb and 'LightGBM' in m_type:
                        model = pickle.loads(model_record.model_data)
                except Exception as e:
                    logger.error(f"Не удалось загрузить модель {m_type} для {symbol}: {e}")
                    continue
                if model:
                    features = json.loads(model_record.features_json) if model_record.features_json else []
                    champion_models[m_type] = {"model": model, "features": features}

            if not champion_models:
                return None, None, None

            scaler_record = session.query(Scaler).filter_by(symbol=symbol).first()
            if not scaler_record:
                return None, None, None
            x_scaler = pickle.loads(scaler_record.x_scaler_data)
            y_scaler = pickle.loads(scaler_record.y_scaler_data)
            return champion_models, x_scaler, y_scaler
        except Exception as e:
            logger.error(f"Критическая ошибка при загрузке моделей-чемпионов для {symbol}: {e}")
            return None, None, None
        finally:
            session.close()

    def get_historical_pnl_for_kg_sentiment(self, current_kg_sentiment: float) -> float:
        """
        Возвращает суммарный PnL исторических сделок, совершенных при схожем
        направлении сентимента (положительный или отрицательный).
        Используется ConsensusEngine для проверки причинности (TZ 2.3).
        """
        session = self.Session()
        try:
            # 1. Определяем направление текущего сентимента
            if current_kg_sentiment > self.config.SENTIMENT_THRESHOLD:
                # Ищем сделки, где сентимент был положительным
                sentiment_filter = TradeHistory.news_sentiment > self.config.SENTIMENT_THRESHOLD
            elif current_kg_sentiment < -self.config.SENTIMENT_THRESHOLD:
                # Ищем сделки, где сентимент был отрицательным
                sentiment_filter = TradeHistory.news_sentiment < -self.config.SENTIMENT_THRESHOLD
            else:
                # Нейтральный сентимент не используем для оценки PnL
                return 0.0

            # 2. Запрашиваем суммарный PnL для сделок с этим направлением сентимента
            total_pnl = session.query(func.sum(TradeHistory.profit)).filter(
                sentiment_filter
            ).scalar()

            # 3. Возвращаем PnL (или 0.0, если нет сделок)
            return float(total_pnl) if total_pnl is not None else 0.0

        except Exception as e:
            logger.error(f"Ошибка при расчете исторического PnL по KG сентименту: {e}")
            return 0.0
        finally:
            session.close()

    def get_strategies_by_status(self, status: str) -> List[Dict]:
        session = self.Session()
        try:
            results = session.query(StrategyPerformance).filter(
                StrategyPerformance.status == status
            ).all()

            return [
                {
                    "strategy_name": r.strategy_name,
                    "incubation_start_date": r.incubation_start_date,
                    "profit_factor": r.profit_factor,
                    "trade_count": r.trade_count
                } for r in results
            ]
        except Exception as e:
            logger.error(f"Ошибка при получении стратегий со статусом '{status}': {e}")
            return []
        finally:
            session.close()

    def update_strategy_status(self, strategy_name: str, new_status: str) -> bool:
        session = self.Session()
        try:
            updated_rows = session.query(StrategyPerformance).filter(
                StrategyPerformance.strategy_name == strategy_name
            ).update(
                {'status': new_status},
                synchronize_session=False
            )
            session.commit()
            return updated_rows > 0
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении статуса стратегии '{strategy_name}' на '{new_status}': {e}")
            return False
        finally:
            session.close()

    def get_period_pnl(self, start_time: datetime) -> Tuple[float, float]:
        """
        Рассчитывает чистый PnL и максимальную просадку (по закрытым сделкам)
        с момента start_time.

        Возвращает: (total_pnl, max_drawdown_percent)
        """
        session = self.Session()
        try:
            # 1. Получаем все сделки с момента start_time
            trades = session.query(TradeHistory).filter(
                TradeHistory.time_close >= start_time
            ).order_by(TradeHistory.time_close.asc()).all()

            if not trades:
                return 0.0, 0.0

            # 2. Расчет PnL и Drawdown
            pnl_series = pd.Series([t.profit for t in trades])
            total_pnl = pnl_series.sum()  # <-- PnL за период (корректно)

            # 3. Расчет Max Drawdown (DD)

            # Получаем PnL до начала периода
            pnl_before = session.query(func.sum(TradeHistory.profit)).filter(
                TradeHistory.time_close < start_time
            ).scalar() or 0.0

            # Начальная эквити для расчета DD в этом периоде
            starting_equity = self.config.backtester_initial_balance + pnl_before

            # Кривая эквити за период
            equity_curve = starting_equity + pnl_series.cumsum()

            # Максимальная эквити, достигнутая до текущего момента
            peak = equity_curve.expanding(min_periods=1).max()

            # Просадка (Peak - Trough) / Peak
            drawdown = (peak - equity_curve) / peak

            # Максимальная просадка за период (в процентах)
            max_drawdown = drawdown.max() * 100

            return float(total_pnl), float(max_drawdown)

        except Exception as e:

            logger.error(f"Ошибка при расчете PnL за период: {e}")
            return 0.0, 0.0
        finally:
            session.close()

    def get_champion_info(self, symbol: str, timeframe: int) -> Optional[Dict]:

        session = self.Session()
        try:
            champion = session.query(TrainedModel).filter_by(
                symbol=symbol,
                timeframe=timeframe,
                is_champion=True
            ).order_by(TrainedModel.version.desc()).first()

            if champion:
                return {
                    "id": champion.id,
                    "performance_report": champion.performance_report
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении информации о чемпионе для {symbol}: {e}")
            return None
        finally:
            session.close()

    def add_news_article(self, **kwargs):
        self.write_queue.put(('add_news_article', kwargs))

    def _add_news_article_internal(self, vector_id: str, content: str, source: str, timestamp: str):
        session = self.Session()
        try:
            ts = datetime.fromisoformat(timestamp)
            new_article = NewsArticle(
                vector_id=vector_id,
                content=content,
                source=source,
                timestamp=ts
            )
            session.add(new_article)
            session.commit()
        except IntegrityError:
            session.rollback()
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении статьи с vector_id={vector_id}: {e}")
        finally:
            session.close()

    def get_articles_by_vector_ids(self, vector_ids: List[str]) -> Dict[str, str]:
        session = self.Session()
        try:
            articles = session.query(NewsArticle).filter(NewsArticle.vector_id.in_(vector_ids)).all()
            return {article.vector_id: article.content for article in articles}
        except Exception as e:
            logger.error(f"Ошибка при получении статей по vector_ids: {e}")
            return {}
        finally:
            session.close()

    def _check_and_migrate_schema(self):
        logger.info("Проверка схемы базы данных на наличие обновлений...")
        try:
            with self.engine.connect() as connection:
                inspector = inspect(connection)
                with connection.begin():
                    table_name = TrainedModel.__tablename__
                    if inspector.has_table(table_name):
                        columns = [col['name'] for col in inspector.get_columns(table_name)]
                        if 'features_json' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN features_json TEXT'))
                        if 'model_type' not in columns:
                            connection.execute(
                                text(f"ALTER TABLE {table_name} ADD COLUMN model_type VARCHAR DEFAULT 'LSTM' NOT NULL"))
                        if 'is_champion' not in columns:
                            connection.execute(
                                text(f"ALTER TABLE {table_name} ADD COLUMN is_champion BOOLEAN DEFAULT FALSE NOT NULL"))
                        if 'performance_report' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN performance_report TEXT'))
                        if 'hyperparameters_json' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN hyperparameters_json TEXT'))
                        if 'training_batch_id' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN training_batch_id VARCHAR'))

                    table_name = TradeHistory.__tablename__
                    if inspector.has_table(table_name):
                        columns = [col['name'] for col in inspector.get_columns(table_name)]
                        if 'xai_data' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN xai_data TEXT'))
                        if 'market_regime' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN market_regime VARCHAR'))
                        if 'news_sentiment' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN news_sentiment FLOAT'))
                        if 'volatility_metric' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN volatility_metric FLOAT'))

                    table_name = StrategyPerformance.__tablename__
                    if inspector.has_table(table_name):
                        columns = [col['name'] for col in inspector.get_columns(table_name)]
                        if 'status' not in columns:
                            connection.execute(
                                text(f"ALTER TABLE {table_name} ADD COLUMN status VARCHAR DEFAULT 'live' NOT NULL"))

                        if 'incubation_start_date' not in columns:
                            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN incubation_start_date DATETIME'))


            logger.info("Проверка схемы базы данных завершена успешно.")
        except Exception as e:
            logger.error(f"Не удалось обновить схему базы данных: {e}")

    def update_trade_with_xai(self, **kwargs):
        self.write_queue.put(('update_trade_with_xai', kwargs))

    def _update_trade_with_xai_internal(self, ticket: int, xai_data: Dict) -> bool:
        if not xai_data:
            return False
        session = self.Session()
        try:
            trade = session.query(TradeHistory).filter_by(ticket=ticket).first()
            if trade:
                trade.xai_data = json.dumps(xai_data)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении XAI для сделки #{ticket}: {e}")
            return False
        finally:
            session.close()

    def get_all_logged_trade_tickets(self) -> set:
        session = self.Session()
        try:
            tickets = session.query(TradeHistory.ticket).all()
            return {ticket[0] for ticket in tickets}
        except Exception as e:
            logger.error(f"Ошибка при получении списка тикетов из БД: {e}")
            return set()
        finally:
            session.close()

    def get_feedback_data(self) -> List[Dict]:
        session = self.Session()
        try:
            feedback_records = session.query(HumanFeedback).filter(HumanFeedback.feedback.in_([1, -1])).all()
            results = []
            for record in feedback_records:
                try:
                    market_state = json.loads(record.market_state_json)
                    if 'prediction_input_sequence' in market_state:
                        results.append({
                            'feedback': record.feedback,
                            'sequence': np.array(market_state['prediction_input_sequence']),
                            'ticket': record.trade_ticket
                        })
                except (json.JSONDecodeError, KeyError):
                    pass
            return results
        except Exception as e:
            logger.error(f"Ошибка при извлечении данных обратной связи: {e}")
            return []
        finally:
            session.close()

    def save_human_feedback(self, trade_ticket: int, feedback: int, market_state: Dict) -> bool:
        session = self.Session()
        try:
            existing_feedback = session.query(HumanFeedback).filter_by(trade_ticket=trade_ticket).first()
            if existing_feedback:
                existing_feedback.feedback = feedback
                existing_feedback.created_at = datetime.utcnow()
            else:
                new_feedback = HumanFeedback(
                    trade_ticket=trade_ticket,
                    feedback=feedback,
                    market_state_json=json.dumps(market_state)
                )
                session.add(new_feedback)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении обратной связи для сделки #{trade_ticket}: {e}")
            return False
        finally:
            session.close()

    def update_strategy_performance(self, strategy_name: str, symbol: str, market_regime: str, report: dict,
                                    incubation_start_date=None):
        session = self.Session()
        try:
            record = session.query(StrategyPerformance).filter_by(strategy_name=strategy_name, symbol=symbol,
                                                                  market_regime=market_regime).first()
            if record:
                record.profit_factor = report.get('profit_factor', 0)
                record.win_rate = report.get('win_rate', 0)
                record.trade_count = report.get('total_trades', 0)
                record.status = status
                if incubation_start_date:
                    record.incubation_start_date = incubation_start_date
            else:
                record = StrategyPerformance(strategy_name=strategy_name, symbol=symbol, market_regime=market_regime,
                                             profit_factor=report.get('profit_factor', 0),
                                             win_rate=report.get('win_rate', 0),
                                             trade_count=report.get('total_trades', 0),
                                             status=status,
                                             incubation_start_date=incubation_start_date)



                session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Не удалось обновить производительность стратегии в БД: {e}")
        finally:
            session.close()

    def get_symbols_for_auto_exclusion(self, 
                                        min_trades: int = 10,
                                        max_loss_threshold: float = -500.0,
                                        profit_factor_threshold: float = 0.8,
                                        win_rate_threshold: float = 0.40) -> List[Dict]:
        """
        Анализирует символы и возвращает список кандидатов на исключение.
        
        Критерии исключения:
        - Минимум min_trades сделок для статистической значимости
        - Общий убыток > max_loss_threshold (по модулю)
        - Profit Factor < profit_factor_threshold
        - Win Rate < win_rate_threshold
        
        Returns:
            Список словарей: [{'symbol': 'EURUSD', 'total_profit': -500.5, 'trade_count': 20, 'pf': 0.65, 'wr': 0.35}]
        """
        session = self.Session()
        try:
            # Агрегируем статистику по символам из trade_history
            query = session.query(
                TradeHistory.symbol,
                func.sum(TradeHistory.profit).label('total_profit'),
                func.count(TradeHistory.id).label('trade_count'),
                func.avg(TradeHistory.profit).label('avg_profit')
            ).group_by(TradeHistory.symbol).having(
                func.count(TradeHistory.id) >= min_trades
            )
            
            results = query.all()
            exclusion_candidates = []
            
            for row in results:
                symbol = row.symbol
                total_profit = row.total_profit or 0
                trade_count = row.trade_count
                avg_profit = row.avg_profit or 0
                
                # Получаем profit factor и win rate из strategy_performance
                sp_query = session.query(
                    func.avg(StrategyPerformance.profit_factor).label('avg_pf'),
                    func.avg(StrategyPerformance.win_rate).label('avg_wr')
                ).filter(
                    StrategyPerformance.symbol == symbol,
                    StrategyPerformance.trade_count > 0
                )
                sp_result = sp_query.first()
                
                avg_pf = sp_result.avg_pf if sp_result and sp_result.avg_pf else 0
                avg_wr = sp_result.avg_wr if sp_result and sp_result.avg_wr else 0
                
                # Проверяем критерии исключения
                should_exclude = False
                reasons = []
                
                if total_profit < max_loss_threshold:
                    should_exclude = True
                    reasons.append(f"loss={total_profit:.2f}")
                
                if avg_pf < profit_factor_threshold and trade_count >= min_trades:
                    should_exclude = True
                    reasons.append(f"pf={avg_pf:.2f}")
                
                if avg_wr < win_rate_threshold and trade_count >= min_trades:
                    should_exclude = True
                    reasons.append(f"wr={avg_wr:.2f}")
                
                if should_exclude:
                    exclusion_candidates.append({
                        'symbol': symbol,
                        'total_profit': total_profit,
                        'trade_count': trade_count,
                        'profit_factor': avg_pf,
                        'win_rate': avg_wr,
                        'avg_profit': avg_profit,
                        'reasons': reasons
                    })
            
            # Сортируем по худшей производительности
            exclusion_candidates.sort(key=lambda x: x['total_profit'])
            
            logger.info(f"[AUTO-EXCLUDE] Найдено {len(exclusion_candidates)} кандидатов на исключение: "
                       f"{[c['symbol'] for c in exclusion_candidates]}")
            
            return exclusion_candidates
            
        except Exception as e:
            logger.error(f"Ошибка при анализе символов для исключения: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def get_symbols_for_auto_inclusion(self, 
                                        excluded_symbols: List[str],
                                        min_trades: int = 5,
                                        profit_factor_threshold: float = 1.2,
                                        win_rate_threshold: float = 0.55) -> List[Dict]:
        """
        Анализирует исключенные символы и возвращает кандидатов на повторное включение.
        
        Критерии включения:
        - Символ сейчас в списке исключенных
        - Profit Factor > profit_factor_threshold (улучшение)
        - Win Rate > win_rate_threshold
        
        Returns:
            Список словарей: [{'symbol': 'EURUSD', 'total_profit': 250.5, 'trade_count': 15, 'pf': 1.5, 'wr': 0.60}]
        """
        session = self.Session()
        try:
            inclusion_candidates = []
            
            for symbol in excluded_symbols:
                # Получаем свежую статистику
                query = session.query(
                    TradeHistory.symbol,
                    func.sum(TradeHistory.profit).label('total_profit'),
                    func.count(TradeHistory.id).label('trade_count')
                ).filter(
                    TradeHistory.symbol == symbol
                ).group_by(TradeHistory.symbol).first()
                
                if not query:
                    continue
                    
                total_profit = query.total_profit or 0
                trade_count = query.trade_count
                
                # Получаем profit factor и win rate
                sp_query = session.query(
                    func.avg(StrategyPerformance.profit_factor).label('avg_pf'),
                    func.avg(StrategyPerformance.win_rate).label('avg_wr')
                ).filter(
                    StrategyPerformance.symbol == symbol,
                    StrategyPerformance.trade_count > 0
                )
                sp_result = sp_query.first()
                
                if not sp_result:
                    continue
                
                avg_pf = sp_result.avg_pf or 0
                avg_wr = sp_result.avg_wr or 0
                
                # Проверяем критерии включения
                should_include = False
                reasons = []
                
                if avg_pf > profit_factor_threshold and trade_count >= min_trades:
                    should_include = True
                    reasons.append(f"pf={avg_pf:.2f}> {profit_factor_threshold}")
                
                if avg_wr > win_rate_threshold and trade_count >= min_trades:
                    should_include = True
                    reasons.append(f"wr={avg_wr:.2f}> {win_rate_threshold}")
                
                # Также включаем, если общая прибыль положительная
                if total_profit > 0 and trade_count >= min_trades * 2:
                    should_include = True
                    reasons.append(f"profit={total_profit:.2f}")
                
                if should_include:
                    inclusion_candidates.append({
                        'symbol': symbol,
                        'total_profit': total_profit,
                        'trade_count': trade_count,
                        'profit_factor': avg_pf,
                        'win_rate': avg_wr,
                        'reasons': reasons
                    })
            
            logger.info(f"[AUTO-INCLUDE] Найдено {len(inclusion_candidates)} кандидатов на включение: "
                       f"{[c['symbol'] for c in inclusion_candidates]}")
            
            return inclusion_candidates
            
        except Exception as e:
            logger.error(f"Ошибка при анализе символов для включения: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def find_weak_spots(self, profit_factor_threshold: float) -> List[Dict]:
        session = self.Session()
        try:
            # Ищем только среди 'live' и 'incubating' стратегий
            subquery = session.query(StrategyPerformance.symbol, StrategyPerformance.market_regime,
                                     func.max(StrategyPerformance.profit_factor).label('max_pf')).filter(
                StrategyPerformance.status.in_(['live', 'incubating'])
            ).group_by(
                StrategyPerformance.symbol, StrategyPerformance.market_regime
            ).subquery()

            # Слабые места - где максимальный PF ниже порога
            weak_spots_query = session.query(subquery.c.symbol, subquery.c.market_regime).filter(
                subquery.c.max_pf <= profit_factor_threshold
            )

            results = weak_spots_query.all()
            return [{"symbol": r.symbol, "market_regime": r.market_regime} for r in results]
        except Exception as e:
            logger.error(f"Ошибка при поиске 'слабых мест' в БД: {e}")
            return []
        finally:
            session.close()

    def get_strategy_avg_performance(self, strategy_name: str, market_regime: str) -> Optional[Dict]:
        session = self.Session()
        try:
            result = session.query(
                func.sum(StrategyPerformance.profit_factor * StrategyPerformance.trade_count) / func.sum(
                    StrategyPerformance.trade_count),
                func.sum(StrategyPerformance.win_rate * StrategyPerformance.trade_count) / func.sum(
                    StrategyPerformance.trade_count)).filter(StrategyPerformance.strategy_name == strategy_name,
                                                             StrategyPerformance.market_regime == market_regime,
                                                             StrategyPerformance.trade_count > 0).one_or_none()
            if result and result[0] is not None:
                return {"profit_factor": result[0], "win_rate": result[1]}
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении средней производительности для {strategy_name}: {e}")
            return None
        finally:
            session.close()

    def find_best_strategy_for_regime(self, market_regime: str) -> Optional[Dict]:
        session = self.Session()
        try:
            subquery = session.query(StrategyPerformance.strategy_name, (
                    func.sum(StrategyPerformance.profit_factor * StrategyPerformance.trade_count) / func.sum(
                StrategyPerformance.trade_count)).label('weighted_pf')).filter(
                StrategyPerformance.market_regime == market_regime, StrategyPerformance.trade_count > 10).group_by(
                StrategyPerformance.strategy_name).subquery()
            best_strategy = session.query(subquery.c.strategy_name, subquery.c.weighted_pf).order_by(
                subquery.c.weighted_pf.desc()).first()
            if best_strategy:
                return {"strategy_name": best_strategy.strategy_name, "profit_factor": best_strategy.weighted_pf}
            return None
        except Exception as e:
            logger.error(f"Ошибка при поиске лучшей стратегии для {market_regime}: {e}")
            return None
        finally:
            session.close()

    def get_best_model_type_for_regime(self, symbol: str, market_regime: str) -> Optional[str]:
        session = self.Session()
        try:
            model_type_expr = func.substr(StrategyPerformance.strategy_name, 1,
                                          func.instr(StrategyPerformance.strategy_name, '_') - 1)
            query = session.query(
                model_type_expr.label('model_type'),
                (func.sum(StrategyPerformance.profit_factor * StrategyPerformance.trade_count) / func.sum(
                    StrategyPerformance.trade_count)).label('weighted_pf')
            ).filter(
                StrategyPerformance.symbol == symbol,
                StrategyPerformance.market_regime == market_regime,
                StrategyPerformance.trade_count > 5,
                StrategyPerformance.strategy_name.like(r'%\_%')
            ).group_by('model_type').order_by(text('weighted_pf DESC'))

            best_model = query.first()
            if best_model and best_model.weighted_pf > 1.0:
                return best_model.model_type
            else:
                return None
        except Exception as e:
            logger.error(f"Ошибка при поиске лучшего типа модели: {e}", exc_info=True)
            return None
        finally:
            session.close()

    def get_toxic_regimes(self, last_n_trades: int = 100) -> List[str]:
        session = self.Session()
        try:
            subquery = session.query(TradeHistory.market_regime, TradeHistory.profit,
                                     func.row_number().over(partition_by=TradeHistory.market_regime,
                                                            order_by=TradeHistory.time_close.desc()).label(
                                         'rn')).filter(TradeHistory.market_regime.isnot(None)).subquery()
            query = session.query(subquery.c.market_regime, func.sum(subquery.c.profit).label('pnl_sum')).filter(
                subquery.c.rn <= last_n_trades).group_by(subquery.c.market_regime)
            toxic_regimes = []
            for regime, pnl_sum in query.all():
                if pnl_sum < 0:
                    toxic_regimes.append(regime)
            return toxic_regimes
        except Exception as e:
            logger.error(f"Ошибка при поиске токсичных режимов: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def log_trade(self, **kwargs):
        self.write_queue.put(('log_trade', kwargs))

    def _log_trade_internal(self, entry_deal: Any, exit_deal: Any, timeframe_str: str, total_profit: float,
                            xai_data: Optional[Dict] = None, market_context: Optional[Dict] = None) -> bool:
        session = self.Session()
        context = market_context or {}
        new_trade = TradeHistory(ticket=entry_deal.position_id, symbol=entry_deal.symbol,
                                 trade_type="BUY" if entry_deal.type == ORDER_TYPE_BUY else "SELL",
                                 volume=entry_deal.volume, price_open=entry_deal.price, price_close=exit_deal.price,
                                 time_open=datetime.fromtimestamp(entry_deal.time),
                                 time_close=datetime.fromtimestamp(exit_deal.time), profit=total_profit,
                                 timeframe=timeframe_str, xai_data=json.dumps(xai_data) if xai_data else None,
                                 market_regime=context.get('market_regime'),
                                 news_sentiment=context.get('news_sentiment'),
                                 volatility_metric=context.get('volatility_metric'))
        try:
            session.add(new_trade)
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка логирования сделки #{entry_deal.position_id} в БД: {e}", exc_info=True)
            return False
        finally:
            session.close()

    def get_trade_history(self) -> List[TradeHistory]:
        session = self.Session()
        try:
            return session.query(TradeHistory).order_by(TradeHistory.time_close.asc()).all()
        except Exception as e:
            logger.error(f"Ошибка чтения истории торгов: {e}")
            return []
        finally:
            session.close()

    # ===========================================
    # Audit Log методы
    # ===========================================
    
    def create_trade_audit(
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
        Создание записи аудита торговой операции.
        
        Args:
            trade_ticket: Тикет сделки
            decision_maker: Источник решения (AI_Model, RLTradeManager, ClassicStrategy, Human)
            strategy_name: Название стратегии
            market_regime: Текущий режим рынка
            capital_allocation: Аллокация капитала
            consensus_score: Оценка консенсуса
            kg_sentiment: Сентимент из KG
            risk_checks: Словарь проверок риска {check_name: passed}
            account_balance: Баланс аккаунта
            account_equity: Эквити аккаунта
            open_positions_count: Количество открытых позиций
            portfolio_var: Portfolio VaR
            execution_status: Статус исполнения (EXECUTED, REJECTED, FAILED)
            rejection_reason: Причина отклонения
            execution_time_ms: Время исполнения в мс
            
        Returns:
            ID созданной записи аудита или None при ошибке
        """
        session = self.Session()
        try:
            # Сериализация risk_checks в JSON
            risk_checks_json = json.dumps(risk_checks) if risk_checks else None
            
            audit_entry = TradeAudit(
                trade_ticket=trade_ticket,
                decision_maker=decision_maker,
                strategy_name=strategy_name,
                market_regime=market_regime,
                capital_allocation=capital_allocation,
                consensus_score=consensus_score,
                kg_sentiment=kg_sentiment,
                risk_checks=risk_checks_json,
                account_balance=account_balance,
                account_equity=account_equity,
                open_positions_count=open_positions_count,
                portfolio_var=portfolio_var,
                execution_status=execution_status,
                rejection_reason=rejection_reason,
                execution_time_ms=execution_time_ms
            )
            
            session.add(audit_entry)
            session.commit()
            session.refresh(audit_entry)
            
            logger.info(f"Audit: Сделка #{trade_ticket} - {execution_status}")
            return audit_entry.id
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка создания audit записи для сделки #{trade_ticket}: {e}", exc_info=True)
            return None
        finally:
            session.close()
    
    def get_audit_logs(
        self,
        trade_ticket: Optional[int] = None,
        execution_status: Optional[str] = None,
        limit: int = 100
    ) -> List[TradeAudit]:
        """
        Получение записей аудита.
        
        Args:
            trade_ticket: Фильтр по тику сделки (опционально)
            execution_status: Фильтр по статусу (опционально)
            limit: Максимальное количество записей
            
        Returns:
            Список записей TradeAudit
        """
        session = self.Session()
        try:
            query = session.query(TradeAudit)
            
            if trade_ticket:
                query = query.filter(TradeAudit.trade_ticket == trade_ticket)
            
            if execution_status:
                query = query.filter(TradeAudit.execution_status == execution_status)
            
            return query.order_by(TradeAudit.timestamp.desc()).limit(limit).all()
            
        except Exception as e:
            logger.error(f"Ошибка чтения audit логов: {e}")
            return []
        finally:
            session.close()
    
    def get_audit_statistics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Получение статистики audit логов.
        
        Args:
            start_date: Начальная дата (опционально)
            end_date: Конечная дата (опционно)
            
        Returns:
            Словарь со статистикой
        """
        session = self.Session()
        try:
            query = session.query(TradeAudit)
            
            if start_date:
                query = query.filter(TradeAudit.timestamp >= start_date)
            if end_date:
                query = query.filter(TradeAudit.timestamp <= end_date)
            
            total = query.count()
            executed = query.filter(TradeAudit.execution_status == "EXECUTED").count()
            rejected = query.filter(TradeAudit.execution_status == "REJECTED").count()
            failed = query.filter(TradeAudit.execution_status == "FAILED").count()
            
            # Средняя уверенность
            avg_confidence_result = session.query(func.avg(TradeAudit.consensus_score)).filter(
                TradeAudit.execution_status == "EXECUTED"
            ).scalar()
            avg_confidence = float(avg_confidence_result) if avg_confidence_result else 0.0
            
            # Среднее время исполнения
            avg_execution_time_result = session.query(func.avg(TradeAudit.execution_time_ms)).filter(
                TradeAudit.execution_time_ms.isnot(None)
            ).scalar()
            avg_execution_time = float(avg_execution_time_result) if avg_execution_time_result else 0.0
            
            return {
                "total_audits": total,
                "executed": executed,
                "rejected": rejected,
                "failed": failed,
                "execution_rate": executed / total if total > 0 else 0.0,
                "rejection_rate": rejected / total if total > 0 else 0.0,
                "avg_confidence_executed": avg_confidence,
                "avg_execution_time_ms": avg_execution_time
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики audit: {e}")
            return {}
        finally:
            session.close()
    
    def get_rejection_reasons(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Получение причин отклонения сделок.
        
        Args:
            limit: Максимальное количество записей
            
        Returns:
            Список словарей с причинами отклонения
        """
        session = self.Session()
        try:
            results = session.query(
                TradeAudit.trade_ticket,
                TradeAudit.timestamp,
                TradeAudit.decision_maker,
                TradeAudit.strategy_name,
                TradeAudit.rejection_reason,
                TradeAudit.risk_checks
            ).filter(
                TradeAudit.execution_status == "REJECTED"
            ).order_by(
                TradeAudit.timestamp.desc()
            ).limit(limit).all()
            
            return [
                {
                    "trade_ticket": r.trade_ticket,
                    "timestamp": r.timestamp,
                    "decision_maker": r.decision_maker,
                    "strategy_name": r.strategy_name,
                    "rejection_reason": r.rejection_reason,
                    "risk_checks": json.loads(r.risk_checks) if r.risk_checks else None
                }
                for r in results
            ]
            
        except Exception as e:
            logger.error(f"Ошибка получения причин отклонения: {e}")
            return []
        finally:
            session.close()

    def get_xai_data(self, ticket: int) -> Optional[Dict]:
        session = self.Session()
        try:
            trade = session.query(TradeHistory).filter_by(ticket=ticket).first()
            if trade and trade.xai_data:
                return json.loads(trade.xai_data)
            return None
        finally:
            session.close()

    def _save_model_and_scalers_internal(self, symbol: str, timeframe: int, model, model_type: str, x_scaler, y_scaler,
                                         features_list: List[str], training_batch_id: str,
                                         hyperparameters: Optional[Dict] = None) -> Optional[int]:
        session = self.Session()
        try:
            model_bytes = None
            if isinstance(model, nn.Module):
                buffer = io.BytesIO()
                torch.save(model.state_dict(), buffer)
                model_bytes = buffer.getvalue()
            elif lgb and isinstance(model, lgb.LGBMModel):
                model_bytes = pickle.dumps(model)
            else:
                logger.error(f"Неподдерживаемый тип модели для сохранения: {type(model)}")
                return None

            x_scaler_bytes = pickle.dumps(x_scaler)
            y_scaler_bytes = pickle.dumps(y_scaler)
            features_json_str = json.dumps(features_list)
            hyperparameters_json_str = json.dumps(hyperparameters) if hyperparameters else None

            model_record = session.query(TrainedModel).filter_by(symbol=symbol, timeframe=timeframe,
                                                                 model_type=model_type).order_by(
                TrainedModel.version.desc()).first()
            new_version = model_record.version + 1 if model_record else 1

            new_model_record = TrainedModel(
                symbol=symbol, timeframe=timeframe, model_type=model_type,
                model_data=model_bytes, version=new_version,
                features_json=features_json_str, is_champion=False,
                training_batch_id=training_batch_id,
                hyperparameters_json=hyperparameters_json_str
            )
            session.add(new_model_record)

            scaler_record = session.query(Scaler).filter_by(symbol=symbol).first()
            if scaler_record:
                scaler_record.x_scaler_data = x_scaler_bytes
                scaler_record.y_scaler_data = y_scaler_bytes
            else:
                new_scaler_record = Scaler(symbol=symbol, x_scaler_data=x_scaler_bytes, y_scaler_data=y_scaler_bytes)
                session.add(new_scaler_record)

            session.commit()
            logger.info(f"Модель {model_type} v{new_version} для {symbol} успешно сохранена. ID: {new_model_record.id}")
            return new_model_record.id
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении модели для {symbol}: {e}", exc_info=True)
            return None
        finally:
            session.close()

    def save_model_and_scalers(self, **kwargs):
        self.write_queue.put(('save_model_and_scalers', kwargs))



    def promote_challenger_to_champion(self, **kwargs):
        self.write_queue.put(('promote_challenger_to_champion', kwargs))

    def _promote_challenger_to_champion_internal(self, challenger_id: int, report: dict):
        session = self.Session()
        try:
            challenger = session.query(TrainedModel).filter_by(id=challenger_id).first()
            if not challenger:
                logger.error(f"Не удалось найти претендента с ID {challenger_id} для продвижения.")
                return

            old_champion = session.query(TrainedModel).filter_by(
                symbol=challenger.symbol,
                timeframe=challenger.timeframe,
                model_type=challenger.model_type,
                is_champion=True
            ).first()

            if old_champion:
                logger.info(
                    f"Разжалован старый чемпион: {old_champion.model_type} v{old_champion.version} (ID: {old_champion.id})")
                old_champion.is_champion = False

            challenger.is_champion = True
            
            # Преобразуем numpy float32 в обычные float для JSON сериализации
            import numpy as np
            def convert_numpy_types(obj):
                """Рекурсивно преобразует numpy типы в Python типы."""
                if isinstance(obj, np.floating):
                    return float(obj)
                elif isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, dict):
                    return {k: convert_numpy_types(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_numpy_types(item) for item in obj]
                else:
                    return obj
            
            report_converted = convert_numpy_types(report)
            challenger.performance_report = json.dumps(report_converted)
            
            session.commit()
            logger.critical(
                f"!!! НОВЫЙ ЧЕМПИОН: {challenger.model_type} v{challenger.version} для {challenger.symbol} (ID: {challenger.id}) !!!")
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при продвижении модели-претендента: {e}", exc_info=True)
        finally:
            session.close()

    def save_directives(self, directives: List[ActiveDirective]):
        session = self.Session()
        try:
            for directive in directives:
                session.merge(directive)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении директив: {e}")
        finally:
            session.close()

    def get_active_directives(self) -> List[ActiveDirective]:
        session = self.Session()
        try:
            now = datetime.utcnow()
            return session.query(ActiveDirective).filter(ActiveDirective.expires_at > now).all()
        except Exception as e:
            logger.error(f"Ошибка при загрузке активных директив: {e}")
            return []
        finally:
            session.close()

    def delete_directive_by_type(self, directive_type: str) -> bool:
        session = self.Session()
        try:
            directive_to_delete = session.query(ActiveDirective).filter_by(directive_type=directive_type).first()
            if directive_to_delete:
                session.delete(directive_to_delete)
                session.commit()
                logger.info(f"Директива '{directive_type}' успешно удалена из БД.")
                return True
            else:
                logger.warning(f"Директива '{directive_type}' не найдена в БД для удаления.")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при удалении директивы '{directive_type}': {e}")
            return False
        finally:
            session.close()

    def get_all_models_for_gui(self) -> List[Dict]:
        session = self.Session()
        try:
            models = session.query(TrainedModel).order_by(TrainedModel.symbol, TrainedModel.is_champion.desc(),
                                                          TrainedModel.training_date.desc()).all()
            result_list = []
            for model in models:
                report = {}
                if model.performance_report:
                    try:
                        report = json.loads(model.performance_report)
                    except (json.JSONDecodeError, TypeError):
                        pass
                result_list.append({
                    "id": model.id, "symbol": model.symbol, "type": model.model_type,
                    "version": model.version, "status": "Чемпион" if model.is_champion else "Претендент",
                    "sharpe": f"{report.get('sharpe_ratio', 0):.2f}",
                    "profit_factor": f"{report.get('profit_factor', 0):.2f}",
                    "date": model.training_date.strftime('%Y-%m-%d %H:%M')
                })
            return result_list
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей для GUI: {e}")
            return []
        finally:
            session.close()

    def demote_champion(self, model_id: int) -> bool:
        session = self.Session()
        try:
            model = session.query(TrainedModel).filter_by(id=model_id).first()
            if model and model.is_champion:
                model.is_champion = False
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при разжаловании чемпиона: {e}")
            return False
        finally:
            session.close()

    def get_or_create_entity(self, session, entity_name: str, entity_type: str = "Unknown") -> Optional[int]:
        try:
            entity = session.query(Entity).filter_by(name=entity_name).first()
            if entity:
                if entity.entity_type == "Unknown" and entity_type != "Unknown":
                    entity.entity_type = entity_type
                session.flush()
                return entity.id
            else:
                new_entity = Entity(name=entity_name, entity_type=entity_type)
                session.add(new_entity)
                session.flush()
                return new_entity.id
        except Exception as e:
            logger.error(f"Ошибка при поиске/создании сущности '{entity_name}': {e}")
            return None

    def add_relation(self, source_name: str, relation_type: str, target_name: str,
                     source_type: str = "Unknown", target_type: str = "Unknown",
                     context: Optional[Dict] = None):
        kwargs = {
            'source_name': source_name, 'relation_type': relation_type, 'target_name': target_name,
            'source_type': source_type, 'target_type': target_type, 'context': context
        }
        self.write_queue.put(('add_relation', kwargs))

    def _add_relation_internal(self, source_name: str, relation_type: str, target_name: str,
                               source_type: str = "Unknown", target_type: str = "Unknown",
                               context: Optional[Dict] = None):
        session = self.Session()
        try:
            source_id = self.get_or_create_entity(session, source_name, source_type)
            target_id = self.get_or_create_entity(session, target_name, target_type)

            if source_id is None or target_id is None:
                session.rollback()
                return

            time_threshold = datetime.utcnow() - timedelta(hours=1)
            existing_relation = session.query(Relation).filter(
                Relation.source_id == source_id,
                Relation.target_id == target_id,
                Relation.relation_type == relation_type.upper().replace(" ", "_"),
                Relation.timestamp >= time_threshold
            ).first()

            if existing_relation:
                return

            new_relation = Relation(
                source_id=source_id, target_id=target_id,
                relation_type=relation_type.upper().replace(" ", "_"),
                context_json=json.dumps(context) if context else None
            )
            session.add(new_relation)
            session.commit()
            logger.info(f"Сохранена новая связь: [{source_name}] --({relation_type.upper()})--> [{target_name}]")
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при добавлении связи: {e}")
        finally:
            session.close()

    def load_model_components_by_id(self, model_id: int) -> Optional[Dict]:
        session = self.Session()
        try:
            model_record = session.query(TrainedModel).filter_by(id=model_id).first()
            if not model_record:
                logger.error(f"Модель с ID {model_id} не найдена в базе данных.")
                return None

            scaler_record = session.query(Scaler).filter_by(symbol=model_record.symbol).first()
            if not scaler_record:
                logger.error(f"Скейлеры для символа {model_record.symbol} не найдены.")
                return None

            features = json.loads(model_record.features_json) if model_record.features_json else []
            model = None
            device = torch.device("cpu") # Загружаем на CPU для стабильности

            if "PyTorch" in model_record.model_type:
                params = json.loads(model_record.hyperparameters_json) if model_record.hyperparameters_json else {}
                input_dim = len(features)

                # --- ИСПРАВЛЕННАЯ ЛОГИКА СОЗДАНИЯ МОДЕЛИ ---
                if model_record.model_type == 'LSTM_PyTorch':
                    model = SimpleLSTM(
                        input_dim=input_dim,
                        hidden_dim=params.get('hidden_dim', 64),
                        num_layers=params.get('num_layers', 2),
                        output_dim=1
                    ).to(device)
                elif model_record.model_type == 'Transformer_PyTorch':
                    # Используем класс TimeSeriesTransformer
                    model = TimeSeriesTransformer(
                        input_dim=input_dim,
                        d_model=params.get('d_model', 64),
                        nhead=params.get('nhead', 4),
                        nlayers=params.get('nlayers', 2)
                    ).to(device)
                else:
                    logger.error(f"Неизвестный PyTorch тип модели: {model_record.model_type}")
                    return None
                # --- КОНЕЦ ИСПРАВЛЕННОЙ ЛОГИКИ ---

                buffer = io.BytesIO(model_record.model_data)
                # Загрузка state_dict с явным указанием map_location
                model.load_state_dict(torch.load(buffer, map_location='cpu'))
                model.eval()

            elif "LightGBM" in model_record.model_type:
                model = pickle.loads(model_record.model_data)

            else:
                logger.error(f"Неподдерживаемый тип модели для загрузки: {model_record.model_type}")
                return None

            return {
                "model": model,
                "model_type": model_record.model_type,
                "symbol": model_record.symbol,
                "features": features,
                "x_scaler": pickle.loads(scaler_record.x_scaler_data),
                "y_scaler": pickle.loads(scaler_record.y_scaler_data)
            }

        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при загрузке компонентов модели {model_id}: {e}", exc_info=True)
            return None
        finally:
            session.close()

    def get_all_live_strategy_performance(self) -> List[Dict]:
        session = self.Session()
        try:
            results = (
                session.query(
                    StrategyPerformance.strategy_name,
                    (func.sum(StrategyPerformance.profit_factor * StrategyPerformance.trade_count) /
                     func.sum(StrategyPerformance.trade_count)).label('weighted_profit_factor'),
                    (func.sum(StrategyPerformance.win_rate * StrategyPerformance.trade_count) /
                     func.sum(StrategyPerformance.trade_count)).label('weighted_win_rate'),
                    func.sum(StrategyPerformance.trade_count).label('total_trades')
                )
                .filter(StrategyPerformance.status == 'live')
                .group_by(StrategyPerformance.strategy_name)
                .all()
            )
            return [
                {
                    "strategy_name": r.strategy_name,
                    "profit_factor": r.weighted_profit_factor,
                    "win_rate": r.weighted_win_rate,
                    "trade_count": r.total_trades
                } for r in results
            ]
        except Exception as e:
            logger.error(f"Ошибка при получении производительности всех стратегий: {e}")
            return []
        finally:
            session.close()

    def deactivate_strategy(self, **kwargs):
        self.write_queue.put(('deactivate_strategy', kwargs))

    def _deactivate_strategy_internal(self, strategy_name: str) -> bool:
        session = self.Session()
        try:
            updated_rows = (
                session.query(StrategyPerformance)
                .filter(StrategyPerformance.strategy_name == strategy_name)
                .update({'status': 'inactive'}, synchronize_session=False)
            )
            session.commit()
            logger.warning(
                f"Стратегия '{strategy_name}' была деактивирована (уволена). Затронуто {updated_rows} записей.")
            return updated_rows > 0
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при деактивации стратегии '{strategy_name}': {e}")
            return False
        finally:
            session.close()

    def get_latest_relations(self, limit: int = 50) -> List[Dict]:
        session = self.Session()
        try:
            source_entity = aliased(Entity)
            target_entity = aliased(Entity)
            results = (
                session.query(
                    Relation.source_id,
                    Relation.target_id,
                    Relation.relation_type,
                    source_entity.name.label("source_name"),
                    target_entity.name.label("target_name")
                )
                .join(source_entity, Relation.source_id == source_entity.id)
                .join(target_entity, Relation.target_id == target_entity.id)
                .order_by(Relation.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [row._asdict() for row in results]
        except Exception as e:
            logger.error(f"Ошибка при получении последних связей из БД: {e}")
            return []
        finally:
            session.close()

    def get_graph_data(self, limit: int = 50) -> Optional[Dict[str, List]]:
        session = self.Session()
        try:
            source_alias = aliased(Entity)
            target_alias = aliased(Entity)

            results = (
                session.query(
                    Relation.source_id,
                    Relation.target_id,
                    Relation.relation_type,
                    source_alias.name.label("source_name"),
                    target_alias.name.label("target_name")
                )
                .join(source_alias, Relation.source_id == source_alias.id)
                .join(target_alias, Relation.target_id == target_alias.id)
                .order_by(Relation.timestamp.desc())
                .limit(limit)
                .all()
            )

            if not results:
                return None

            nodes = {}
            edges = []

            for row in results:
                if row.source_id not in nodes:
                    nodes[row.source_id] = {"id": row.source_id, "label": row.source_name}
                if row.target_id not in nodes:
                    nodes[row.target_id] = {"id": row.target_id, "label": row.target_name}

                edges.append({
                    "from": row.source_id,
                    "to": row.target_id,
                    "label": row.relation_type.replace("_", " ").lower()
                })

            return {"nodes": list(nodes.values()), "edges": edges}

        except Exception as e:
            logger.error(f"Ошибка при получении данных для графа знаний: {e}")
            return None
        finally:
            session.close()

    def log_trade_outcome_to_kg(self, trade_ticket: int, profit: float, market_regime: str, kg_cb_sentiment: float):
        """Обратная связь в KG: Ставит задачу в очередь записи."""
        self.write_queue.put(('log_trade_outcome_to_kg', {
            'trade_ticket': trade_ticket,
            'profit': profit,
            'market_regime': market_regime,
            'kg_cb_sentiment': kg_cb_sentiment
        }))

    # 2. Внутренний метод (выполняет запись) - ПЕРЕИМЕНОВАН
    def _log_trade_outcome_to_kg_internal(self, trade_ticket: int, profit: float, market_regime: str, kg_cb_sentiment: float):
        """
        Обратная связь в KG: Логирует исход сделки, связанный с KG-признаками.
        """
        session = self.Session()
        try:
            # 1. Определяем исход
            outcome = "PROFIT" if profit > 0 else "LOSS"

            # 2. Определяем уровень сентимента
            sentiment_level = "POSITIVE" if kg_cb_sentiment > 0.1 else "NEGATIVE" if kg_cb_sentiment < -0.1 else "NEUTRAL"
            sentiment_entity_name = f"CB_SENTIMENT_{sentiment_level}"
            outcome_entity_name = f"TRADE_OUTCOME_{outcome}"

            # 3. Создаем связь: KGSentiment -> LED_TO -> TradeOutcome
            # Используем MERGE для создания узлов и связи
            query = (
                f"MERGE (a:KGSentiment {{name: $sentiment_name}}) "
                f"MERGE (b:TradeOutcome {{name: $outcome_name}}) "
                f"MERGE (a)-[r:LED_TO {{profit: $profit, ticket: $ticket}}]->(b) "
                "RETURN a.name, type(r), b.name"
            )
            params = {
                "sentiment_name": sentiment_entity_name,
                "outcome_name": outcome_entity_name,
                "profit": float(profit),
                "ticket": trade_ticket
            }
            # Используем execute_query, который должен быть реализован в реальном проекте
            # Здесь мы просто логируем, так как прямого доступа к Neo4j нет
            logger.info(
                f"KG Feedback: Логирование связи: {sentiment_entity_name} -> {outcome_entity_name} (PnL: {profit:.2f})")

        except Exception as e:
            logger.error(f"Ошибка при логировании обратной связи в KG: {e}")
        finally:
            session.close()



    # --- ПРИВАТНЫЙ МЕТОД: Выполняет фактическую запись ---
    def _log_trade_outcome_to_kg_internal(self, trade_ticket: int, profit: float, market_regime: str,
                                          kg_cb_sentiment: float):
        """
        Обратная связь в KG: Логирует исход сделки, связанный с KG-признаками.
        """
        session = self.Session()
        try:
            # 1. Определяем исход
            outcome = "PROFIT" if profit > 0 else "LOSS"

            # 2. Определяем уровень сентимента
            sentiment_level = "POSITIVE" if kg_cb_sentiment > 0.1 else "NEGATIVE" if kg_cb_sentiment < -0.1 else "NEUTRAL"
            sentiment_entity_name = f"CB_SENTIMENT_{sentiment_level}"
            outcome_entity_name = f"TRADE_OUTCOME_{outcome}"

            # 3. Создаем связь: KGSentiment -> LED_TO -> TradeOutcome
            # Используем MERGE для создания узлов и связи
            # В реальном проекте здесь был бы вызов Neo4j, здесь - эмуляция через SQL

            # Эмуляция создания сущностей
            sentiment_id = self.get_or_create_entity(session, sentiment_entity_name, "KGSentiment")
            outcome_id = self.get_or_create_entity(session, outcome_entity_name, "TradeOutcome")

            if sentiment_id is None or outcome_id is None:
                session.rollback()
                return

            # Создание связи (Relation)
            new_relation = Relation(
                source_id=sentiment_id,
                target_id=outcome_id,
                relation_type="LED_TO",
                timestamp=datetime.utcnow(),
                context_json=json.dumps({"profit": float(profit), "ticket": trade_ticket, "regime": market_regime})
            )
            session.add(new_relation)
            session.commit()

            logger.critical(
                f"KG Feedback: Логирование связи: {sentiment_entity_name} -> {outcome_entity_name} (PnL: {profit:.2f})")

        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при логировании обратной связи в KG: {e}")
        finally:
            session.close()