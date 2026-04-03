-- init-db.sql
-- Инициализация PostgreSQL базы данных для Genesis Trading System
-- Создание расширений и базовых таблиц

-- Включаем необходимые расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- Для нечеткого поиска
CREATE EXTENSION IF NOT EXISTS "btree_gin";  -- Для составных индексов

-- ===========================================
-- Таблица: Пользователи и настройки
-- ===========================================
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    settings JSONB DEFAULT '{}'::jsonb
);

-- ===========================================
-- Таблица: Торговые позиции (активные)
-- ===========================================
CREATE TABLE IF NOT EXISTS active_positions (
    id BIGSERIAL PRIMARY KEY,
    ticket BIGINT UNIQUE NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    order_type VARCHAR(20) NOT NULL,  -- BUY, SELL
    volume DOUBLE PRECISION NOT NULL,
    open_price DOUBLE PRECISION NOT NULL,
    current_price DOUBLE PRECISION,
    sl DOUBLE PRECISION,
    tp DOUBLE PRECISION,
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ,
    close_price DOUBLE PRECISION,
    profit DOUBLE PRECISION DEFAULT 0,
    swap DOUBLE PRECISION DEFAULT 0,
    commission DOUBLE PRECISION DEFAULT 0,
    magic BIGINT,
    comment TEXT,
    status VARCHAR(50) DEFAULT 'OPEN',  -- OPEN, CLOSED, PARTIAL
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_active_positions_symbol ON active_positions(symbol);
CREATE INDEX idx_active_positions_status ON active_positions(status);
CREATE INDEX idx_active_positions_open_time ON active_positions(open_time DESC);

-- ===========================================
-- Таблица: История сделок (полная)
-- ===========================================
CREATE TABLE IF NOT EXISTS trade_history (
    id BIGSERIAL PRIMARY KEY,
    ticket BIGINT UNIQUE NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    open_price DOUBLE PRECISION NOT NULL,
    close_price DOUBLE PRECISION,
    sl DOUBLE PRECISION,
    tp DOUBLE PRECISION,
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ,
    profit DOUBLE PRECISION DEFAULT 0,
    swap DOUBLE PRECISION DEFAULT 0,
    commission DOUBLE PRECISION DEFAULT 0,
    magic BIGINT,
    comment TEXT,
    strategy_name VARCHAR(100),
    model_type VARCHAR(50),  -- LSTM, Transformer, LightGBM, etc.
    signal_confidence DOUBLE PRECISION,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trade_history_symbol ON trade_history(symbol);
CREATE INDEX idx_trade_history_close_time ON trade_history(close_time DESC);
CREATE INDEX idx_trade_history_profit ON trade_history(profit);
CREATE INDEX idx_trade_history_strategy ON trade_history(strategy_name);

-- ===========================================
-- Таблица: Аудит торговых решений
-- ===========================================
CREATE TABLE IF NOT EXISTS trade_audit (
    id BIGSERIAL PRIMARY KEY,
    trade_ticket BIGINT NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    decision_type VARCHAR(50) NOT NULL,  -- OPEN, CLOSE, MODIFY
    reason TEXT,
    ai_signal VARCHAR(20),  -- BUY, SELL, HOLD
    ai_confidence DOUBLE PRECISION,
    classic_signal VARCHAR(20),
    sentiment_score DOUBLE PRECISION,
    risk_score DOUBLE PRECISION,
    market_regime VARCHAR(50),
    features_used JSONB,
    model_predictions JSONB,
    human_override BOOLEAN DEFAULT FALSE,
    override_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trade_audit_ticket ON trade_audit(trade_ticket);
CREATE INDEX idx_trade_audit_symbol ON trade_audit(symbol);
CREATE INDEX idx_trade_audit_created ON trade_audit(created_at DESC);

-- ===========================================
-- Таблица: Производительность стратегий
-- ===========================================
CREATE TABLE IF NOT EXISTS strategy_performance (
    id BIGSERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(50),
    timeframe INTEGER,
    date DATE NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_profit DOUBLE PRECISION DEFAULT 0,
    max_drawdown DOUBLE PRECISION DEFAULT 0,
    sharpe_ratio DOUBLE PRECISION,
    profit_factor DOUBLE PRECISION,
    win_rate DOUBLE PRECISION,
    avg_win DOUBLE PRECISION,
    avg_loss DOUBLE PRECISION,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_name, symbol, timeframe, date)
);

CREATE INDEX idx_strategy_performance_name ON strategy_performance(strategy_name);
CREATE INDEX idx_strategy_performance_date ON strategy_performance(date DESC);

-- ===========================================
-- Таблица: Обратная связь от человека
-- ===========================================
CREATE TABLE IF NOT EXISTS human_feedback (
    id BIGSERIAL PRIMARY KEY,
    trade_ticket BIGINT,
    symbol VARCHAR(50) NOT NULL,
    feedback_type VARCHAR(50) NOT NULL,  -- APPROVE, REJECT, MODIFY
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    suggested_action VARCHAR(50),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_human_feedback_trade ON human_feedback(trade_ticket);
CREATE INDEX idx_human_feedback_type ON human_feedback(feedback_type);

-- ===========================================
-- Таблица: Активные директивы (RL оркестратор)
-- ===========================================
CREATE TABLE IF NOT EXISTS active_directives (
    id BIGSERIAL PRIMARY KEY,
    directive_name VARCHAR(100) UNIQUE NOT NULL,
    directive_type VARCHAR(50) NOT NULL,
    priority INTEGER DEFAULT 1,
    parameters JSONB NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    valid_from TIMESTAMPTZ DEFAULT NOW(),
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_active_directives_name ON active_directives(directive_name);
CREATE INDEX idx_active_directives_active ON active_directives(is_active);

-- ===========================================
-- Таблица: Новости и статьи
-- ===========================================
CREATE TABLE IF NOT EXISTS news_articles (
    id BIGSERIAL PRIMARY KEY,
    vector_id VARCHAR(100) UNIQUE NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    source VARCHAR(100),
    author VARCHAR(100),
    url TEXT,
    symbols TEXT[],  -- Массив связанных символов
    sentiment_score DOUBLE PRECISION,
    sentiment_label VARCHAR(20),  -- POSITIVE, NEGATIVE, NEUTRAL
    categories TEXT[],
    published_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_news_articles_published ON news_articles(published_at DESC);
CREATE INDEX idx_news_articles_symbols ON news_articles USING GIN(symbols);
CREATE INDEX idx_news_articles_sentiment ON news_articles(sentiment_label);

-- ===========================================
-- Таблица: Сущности графа знаний
-- ===========================================
CREATE TABLE IF NOT EXISTS entities (
    id BIGSERIAL PRIMARY KEY,
    entity_id VARCHAR(100) UNIQUE NOT NULL,
    entity_type VARCHAR(50) NOT NULL,  -- COMPANY, PERSON, EVENT, etc.
    name VARCHAR(255) NOT NULL,
    description TEXT,
    properties JSONB DEFAULT '{}'::jsonb,
    embedding VECTOR(384),  -- Для семантического поиска
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_name ON entities(name);

-- ===========================================
-- Таблица: Отношения графа знаний
-- ===========================================
CREATE TABLE IF NOT EXISTS relations (
    id BIGSERIAL PRIMARY KEY,
    relation_id VARCHAR(100) UNIQUE NOT NULL,
    source_entity_id VARCHAR(100) NOT NULL REFERENCES entities(entity_id),
    target_entity_id VARCHAR(100) NOT NULL REFERENCES entities(entity_id),
    relation_type VARCHAR(50) NOT NULL,  -- OWNS, WORKS_FOR, CAUSED, etc.
    weight DOUBLE PRECISION DEFAULT 1.0,
    properties JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_entity_id, target_entity_id, relation_type)
);

CREATE INDEX idx_relations_source ON relations(source_entity_id);
CREATE INDEX idx_relations_target ON relations(target_entity_id);
CREATE INDEX idx_relations_type ON relations(relation_type);

-- ===========================================
-- Таблица: Обученные модели
-- ===========================================
CREATE TABLE IF NOT EXISTS trained_models (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    timeframe INTEGER NOT NULL,
    model_type VARCHAR(50) NOT NULL,  -- LSTM, Transformer, LightGBM
    version INTEGER NOT NULL,
    is_champion BOOLEAN DEFAULT FALSE,
    performance_metrics JSONB,
    hyperparameters JSONB,
    features_used TEXT[],
    training_date TIMESTAMPTZ DEFAULT NOW(),
    model_path VARCHAR(500),
    model_data BYTEA,  -- Сериализованная модель
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trained_models_symbol ON trained_models(symbol, timeframe);
CREATE INDEX idx_trained_models_champion ON trained_models(is_champion);
CREATE INDEX idx_trained_models_type ON trained_models(model_type);

-- ===========================================
-- Таблица: Скалеры (нормализация данных)
-- ===========================================
CREATE TABLE IF NOT EXISTS scalers (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(50) UNIQUE NOT NULL,
    x_scaler_data BYTEA NOT NULL,
    y_scaler_data BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===========================================
-- Таблица: Метрики системы (для Prometheus)
-- ===========================================
CREATE TABLE IF NOT EXISTS system_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    labels JSONB DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_system_metrics_name ON system_metrics(metric_name);
CREATE INDEX idx_system_metrics_timestamp ON system_metrics(timestamp DESC);

-- ===========================================
-- Функция: Обновление updated_at
-- ===========================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Триггеры для auto-update updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_active_positions_updated_at BEFORE UPDATE ON active_positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_entities_updated_at BEFORE UPDATE ON entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scalers_updated_at BEFORE UPDATE ON scalers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Начальные данные
-- ===========================================
INSERT INTO users (username, email, settings)
VALUES ('admin', 'admin@genesis.trading', '{"theme": "dark", "notifications": true}')
ON CONFLICT (username) DO NOTHING;

-- ===========================================
-- Представления (Views)
-- ===========================================

-- Активные позиции с текущим PnL
CREATE OR REPLACE VIEW v_active_positions_summary AS
SELECT
    symbol,
    COUNT(*) as position_count,
    SUM(volume) as total_volume,
    AVG(open_price) as avg_entry_price,
    SUM(profit) as total_profit,
    MAX(open_time) as last_opened
FROM active_positions
WHERE status = 'OPEN'
GROUP BY symbol;

-- Дневной PnL
CREATE OR REPLACE VIEW v_daily_pnl AS
SELECT
    DATE(close_time) as trade_date,
    COUNT(*) as total_trades,
    SUM(profit) as total_profit,
    AVG(profit) as avg_profit,
    MAX(profit) as max_profit,
    MIN(profit) as min_profit,
    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) as losing_trades
FROM trade_history
WHERE close_time IS NOT NULL
GROUP BY DATE(close_time)
ORDER BY trade_date DESC;

-- Производительность стратегий за все время
CREATE OR REPLACE VIEW v_strategy_performance_summary AS
SELECT
    strategy_name,
    COUNT(DISTINCT date) as trading_days,
    SUM(total_trades) as total_trades,
    SUM(total_profit) as total_profit,
    AVG(sharpe_ratio) as avg_sharpe,
    AVG(profit_factor) as avg_profit_factor,
    AVG(win_rate) as avg_win_rate
FROM strategy_performance
GROUP BY strategy_name
ORDER BY total_profit DESC;

COMMENT ON TABLE active_positions IS 'Активные торговые позиции';
COMMENT ON TABLE trade_history IS 'Полная история сделок';
COMMENT ON TABLE trade_audit IS 'Аудит торговых решений с контекстом';
COMMENT ON TABLE strategy_performance IS 'Производительность стратегий по дням';
COMMENT ON TABLE human_feedback IS 'Обратная связь от человека для RL';
COMMENT ON TABLE active_directives is 'Директивы от RL оркестратора';
