# src/db/models.py
"""
SQLAlchemy модели данных для базы данных Genesis Trading System.
Вынесены из database_manager.py для снижения связанности (Аудит v4, Task P1).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class NewsArticle(Base):
    __tablename__ = "news_articles"
    id = Column(Integer, primary_key=True)
    vector_id = Column(String, unique=True, nullable=False, index=True)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True)

    def __repr__(self):
        return f"<NewsArticle(id={self.id}, vector_id='{self.vector_id}', source='{self.source}')>"


class StrategicModel(Base):
    __tablename__ = "strategic_models"
    id = Column(Integer, primary_key=True)
    model_data = Column(LargeBinary, nullable=False)
    training_date = Column(DateTime, default=datetime.utcnow)
    version = Column(Integer, default=1)
    features_json = Column(Text, nullable=True)
    classes_json = Column(Text, nullable=True)


class TrainedModel(Base):
    __tablename__ = "trained_models"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(Integer, nullable=False)
    model_type = Column(String, nullable=False, default="LSTM", index=True)
    model_data = Column(LargeBinary, nullable=False)
    training_date = Column(DateTime, default=datetime.utcnow)
    version = Column(Integer, default=1)
    features_json = Column(Text, nullable=True)
    is_champion = Column(Boolean, default=False, nullable=False, index=True)
    performance_report = Column(Text, nullable=True)
    training_batch_id = Column(String, nullable=True, index=True)
    hyperparameters_json = Column(Text, nullable=True)


class Scaler(Base):
    __tablename__ = "scalers"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, unique=True)
    x_scaler_data = Column(LargeBinary, nullable=False)
    y_scaler_data = Column(LargeBinary, nullable=False)


class TradeHistory(Base):
    __tablename__ = "trade_history"
    id = Column(Integer, primary_key=True)
    ticket = Column(Integer, unique=True, nullable=False)
    symbol = Column(String, nullable=False)
    strategy = Column(String, nullable=True, default="External")

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
    """

    __tablename__ = "trade_audit"

    id = Column(Integer, primary_key=True)
    trade_ticket = Column(Integer, nullable=False, index=True, comment="Тикет сделки")
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True, comment="Время аудита")

    decision_maker = Column(String, nullable=False, comment="Источник решения")
    strategy_name = Column(String, nullable=True, comment="Название стратегии")

    market_regime = Column(String, nullable=True, comment="Текущий режим рынка")
    capital_allocation = Column(Float, nullable=True, comment="Аллокация капитала")
    consensus_score = Column(Float, nullable=True, comment="Оценка консенсуса")
    kg_sentiment = Column(Float, nullable=True, comment="Сентимент из Графа Знаний")

    risk_checks = Column(Text, nullable=True, comment="JSON с результатами проверок риска")

    account_balance = Column(Float, nullable=True, comment="Баланс аккаунта")
    account_equity = Column(Float, nullable=True, comment="Эквити аккаунта")
    open_positions_count = Column(Integer, nullable=True, comment="Количество открытых позиций")
    portfolio_var = Column(Float, nullable=True, comment="Portfolio VaR (99%)")

    execution_status = Column(String, nullable=False, comment="Статус: EXECUTED, REJECTED, FAILED")
    rejection_reason = Column(String, nullable=True, comment="Причина отклонения")
    execution_time_ms = Column(Float, nullable=True, comment="Время исполнения в мс")

    def __repr__(self):
        return f"<TradeAudit(ticket={self.trade_ticket}, status={self.execution_status})>"


class StrategyPerformance(Base):
    __tablename__ = "strategy_performance"
    id = Column(Integer, primary_key=True)
    strategy_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    market_regime = Column(String, nullable=False, index=True)
    profit_factor = Column(Float, nullable=False)
    win_rate = Column(Float, nullable=False)
    trade_count = Column(Integer, nullable=False)
    status = Column(String, default="live", nullable=False, index=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("strategy_name", "symbol", "market_regime", name="_strategy_symbol_regime_uc"),)


class ActiveDirective(Base):
    __tablename__ = "active_directives"
    id = Column(Integer, primary_key=True)
    directive_type = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class HumanFeedback(Base):
    __tablename__ = "human_feedback"
    id = Column(Integer, primary_key=True)
    trade_ticket = Column(Integer, nullable=False, index=True)
    model_id = Column(Integer, nullable=True)
    feedback = Column(Integer, nullable=False)
    market_state_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Entity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)

    def __repr__(self):
        return f"<Entity(name='{self.name}', type='{self.entity_type}')>"


class Relation(Base):
    __tablename__ = "relations"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    relation_type = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    context_json = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation_type", "timestamp", name="_relation_uc"),)

    def __repr__(self):
        return f"<Relation(source={self.source_id}, target={self.target_id}, type='{self.relation_type}')>"


class CandleData(Base):
    """
    Таблица для хранения свечных данных (OHLCV).
    """

    __tablename__ = "candle_data"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True, comment="Торговый инструмент")
    timeframe = Column(String, nullable=False, index=True, comment="Таймфрейм")
    timestamp = Column(DateTime, nullable=False, index=True, comment="Время свечи")
    open = Column(Float, nullable=False, comment="Цена открытия")
    high = Column(Float, nullable=False, comment="Максимум")
    low = Column(Float, nullable=False, comment="Минимум")
    close = Column(Float, nullable=False, comment="Цена закрытия")
    tick_volume = Column(Integer, nullable=True, comment="Тиковый объём")

    __table_args__ = (UniqueConstraint("symbol", "timeframe", "timestamp", name="_candle_data_uc"),)

    def __repr__(self):
        return f"<CandleData(symbol='{self.symbol}', timeframe='{self.timeframe}', timestamp={self.timestamp})>"


class FundamentalData(Base):
    """
    Фундаментальные данные компаний из Yahoo Finance.
    """

    __tablename__ = "fundamental_data"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    pe_ratio = Column(Float, nullable=True)
    forward_pe = Column(Float, nullable=True)
    peg_ratio = Column(Float, nullable=True)
    price_to_book = Column(Float, nullable=True)
    price_to_sales = Column(Float, nullable=True)
    enterprise_value = Column(Float, nullable=True)
    ev_to_revenue = Column(Float, nullable=True)
    ev_to_ebitda = Column(Float, nullable=True)

    eps = Column(Float, nullable=True)
    revenue = Column(Float, nullable=True)
    net_income = Column(Float, nullable=True)
    profit_margin = Column(Float, nullable=True)
    operating_margin = Column(Float, nullable=True)
    roe = Column(Float, nullable=True)
    roa = Column(Float, nullable=True)
    debt_to_equity = Column(Float, nullable=True)
    current_ratio = Column(Float, nullable=True)

    market_cap = Column(Float, nullable=True)
    shares_outstanding = Column(Float, nullable=True)
    float_shares = Column(Float, nullable=True)

    dividend_yield = Column(Float, nullable=True)
    dividend_rate = Column(Float, nullable=True)
    payout_ratio = Column(Float, nullable=True)
    five_year_avg_dividend_yield = Column(Float, nullable=True)

    target_mean_price = Column(Float, nullable=True)
    target_high_price = Column(Float, nullable=True)
    target_low_price = Column(Float, nullable=True)
    recommendation_mean = Column(Float, nullable=True)
    number_of_analyst_opinions = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<FundamentalData(symbol='{self.symbol}', PE={self.pe_ratio})>"


class EarningsCalendar(Base):
    """
    Календарь отчетов компаний.
    """

    __tablename__ = "earnings_calendar"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    earnings_date = Column(DateTime, nullable=False, index=True)
    eps_estimate = Column(Float, nullable=True)
    eps_actual = Column(Float, nullable=True)
    revenue_estimate = Column(Float, nullable=True)
    reported_revenue = Column(Float, nullable=True)
    surprise_percent = Column(Float, nullable=True)
    quarter = Column(String, nullable=True)
    year = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<EarningsCalendar(symbol='{self.symbol}', date={self.earnings_date})>"


class InsiderTrades(Base):
    """
    Данные о торговлях инсайдеров.
    """

    __tablename__ = "insider_trades"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    insider_name = Column(String, nullable=True)
    position = Column(String, nullable=True)
    transaction_type = Column(String, nullable=False)
    shares = Column(Integer, nullable=True)
    price_per_share = Column(Float, nullable=True)
    total_value = Column(Float, nullable=True)
    shares_owned_after = Column(Integer, nullable=True)
    filing_date = Column(DateTime, nullable=False, index=True)
    transaction_date = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<InsiderTrades(symbol='{self.symbol}', type='{self.transaction_type}')>"


class MarketSentiment(Base):
    """
    Индексы настроений рынка.
    """

    __tablename__ = "market_sentiment"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)

    fear_greed_index = Column(Integer, nullable=True)
    fear_greed_classification = Column(String, nullable=True)

    vix = Column(Float, nullable=True)
    vix_52_week_high = Column(Float, nullable=True)
    vix_52_week_low = Column(Float, nullable=True)

    put_call_ratio = Column(Float, nullable=True)

    aii_bullish_percent = Column(Float, nullable=True)
    aii_bearish_percent = Column(Float, nullable=True)
    aii_neutral_percent = Column(Float, nullable=True)

    overall_sentiment_score = Column(Float, nullable=True)

    def __repr__(self):
        return f"<MarketSentiment(F&G={self.fear_greed_index}, VIX={self.vix})>"


class GoogleTrends(Base):
    """
    Данные Google Trends.
    """

    __tablename__ = "google_trends"

    id = Column(Integer, primary_key=True)
    keyword = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    interest_score = Column(Integer, nullable=False)
    related_queries = Column(Text, nullable=True)
    region = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("keyword", "timestamp", "region", name="_trends_keyword_time_region"),)

    def __repr__(self):
        return f"<GoogleTrends(keyword='{self.keyword}', score={self.interest_score})>"


class DataEnrichmentLog(Base):
    """
    Лог загрузки внешних данных.
    """

    __tablename__ = "data_enrichment_log"

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    status = Column(String, nullable=False)
    records_fetched = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    def __repr__(self):
        return f"<DataEnrichmentLog(source='{self.source}', status='{self.status}')>"


class DefiMetrics(Base):
    """
    Метрики DeFi протоколов.
    """

    __tablename__ = "defi_metrics"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    chain = Column(String, nullable=False, index=True)
    protocol = Column(String, nullable=False, index=True)
    metric_type = Column(String, nullable=False, index=True)
    asset = Column(String, nullable=True, index=True)
    value = Column(Float, nullable=False)
    pool_id = Column(String, nullable=True, index=True)
    extra_data = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("chain", "protocol", "asset", "metric_type", "timestamp", name="_defi_metric_uc"),)

    def __repr__(self):
        return f"<DefiMetrics(chain='{self.chain}', protocol='{self.protocol}', {self.metric_type}={self.value}%)>"
