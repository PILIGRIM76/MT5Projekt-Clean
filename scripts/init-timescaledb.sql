-- init-timescaledb.sql
-- Инициализация TimescaleDB для хранения временных рядов
-- Свечные данные, тики, стакан заявок

-- Включаем расширение TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ===========================================
-- Hypertable: Свечные данные (Candle Data)
-- ===========================================

-- Создаем таблицу для свечных данных
CREATE TABLE IF NOT EXISTS candle_data (
    id BIGSERIAL,
    symbol VARCHAR(50) NOT NULL,
    timeframe INTEGER NOT NULL,  -- В секундах: 60=M1, 300=M5, 900=M15, etc.
    timestamp TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT DEFAULT 0,
    tick_volume BIGINT DEFAULT 0,
    spread INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Создаем индекс для эффективного поиска
CREATE INDEX IF NOT EXISTS idx_candle_data_symbol_time
ON candle_data (symbol, timestamp DESC);

-- Превращаем в hypertable (автоматическое партиционирование)
SELECT create_hypertable('candle_data', 'timestamp', if_not_exists => TRUE);

-- ===========================================
-- Hypertable: Тиковые данные (Tick Data)
-- ===========================================

CREATE TABLE IF NOT EXISTS tick_data (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    bid DOUBLE PRECISION NOT NULL,
    ask DOUBLE PRECISION NOT NULL,
    last DOUBLE PRECISION,
    volume BIGINT,
    flags INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tick_data_symbol_time
ON tick_data (symbol, timestamp DESC);

SELECT create_hypertable('tick_data', 'timestamp', if_not_exists => TRUE);

-- ===========================================
-- Hypertable: Стакан заявок (Order Book)
-- ===========================================

CREATE TABLE IF NOT EXISTS orderbook_data (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    bid_price DOUBLE PRECISION[],
    bid_volume DOUBLE PRECISION[],
    ask_price DOUBLE PRECISION[],
    ask_volume DOUBLE PRECISION[],
    spread DOUBLE PRECISION,
    mid_price DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_orderbook_data_symbol_time
ON orderbook_data (symbol, timestamp DESC);

SELECT create_hypertable('orderbook_data', 'timestamp', if_not_exists => TRUE);

-- ===========================================
-- Compression (Сжатие данных)
-- ===========================================

-- Включаем сжатие для candle_data
ALTER TABLE candle_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);

-- Добавляем политику сжатия для данных старше 7 дней
SELECT add_compression_policy('candle_data', INTERVAL '7 days', if_not_exists => TRUE);

-- Включаем сжатие для tick_data
ALTER TABLE tick_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);

SELECT add_compression_policy('tick_data', INTERVAL '1 day', if_not_exists => TRUE);

-- ===========================================
-- Continuous Aggregates (Непрерывные агрегаты)
-- ===========================================

-- Агрегат для минутных свечей -> часовые свечи
CREATE MATERIALIZED VIEW IF NOT EXISTS candle_data_1h
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    timeframe,
    time_bucket('1 hour', timestamp) AS bucket,
    first(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, timestamp) AS close,
    sum(volume) AS volume,
    sum(tick_volume) AS tick_volume,
    avg(spread) AS spread
FROM candle_data
GROUP BY symbol, timeframe, bucket
WITH NO DATA;

-- Агрегат для часовых свечей -> дневные свечи
CREATE MATERIALIZED VIEW IF NOT EXISTS candle_data_1d
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 day', timestamp) AS bucket,
    first(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, timestamp) AS close,
    sum(volume) AS volume,
    sum(tick_volume) AS tick_volume
FROM candle_data
GROUP BY symbol, bucket
WITH NO DATA;

-- Добавляем политику обновления для агрегатов
SELECT add_continuous_aggregate_policy('candle_data_1h',
    start_offset => INTERVAL '2 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('candle_data_1d',
    start_offset => INTERVAL '30 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

-- ===========================================
-- Retention Policies (Политики хранения)
-- ===========================================

-- Удаляем тиковые данные старше 30 дней
SELECT add_retention_policy('tick_data', INTERVAL '30 days', if_not_exists => TRUE);

-- Удаляем свечные данные старше 1 года
SELECT add_retention_policy('candle_data', INTERVAL '1 year', if_not_exists => TRUE);

-- ===========================================
-- Функции для работы с данными
-- ===========================================

-- Функция: Получение последней свечи
CREATE OR REPLACE FUNCTION get_latest_candle(
    p_symbol VARCHAR,
    p_timeframe INTEGER
)
RETURNS TABLE (
    timestamp TIMESTAMPTZ,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    tick_volume BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT c.timestamp, c.open, c.high, c.low, c.close, c.volume, c.tick_volume
    FROM candle_data c
    WHERE c.symbol = p_symbol
      AND c.timeframe = p_timeframe
    ORDER BY c.timestamp DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Функция: Получение свечей за период
CREATE OR REPLACE FUNCTION get_candles_range(
    p_symbol VARCHAR,
    p_timeframe INTEGER,
    p_start TIMESTAMPTZ,
    p_end TIMESTAMPTZ,
    p_limit INTEGER DEFAULT NULL
)
RETURNS TABLE (
    timestamp TIMESTAMPTZ,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    tick_volume BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT c.timestamp, c.open, c.high, c.low, c.close, c.volume, c.tick_volume
    FROM candle_data c
    WHERE c.symbol = p_symbol
      AND c.timeframe = p_timeframe
      AND c.timestamp BETWEEN p_start AND p_end
    ORDER BY c.timestamp ASC
    LIMIT COALESCE(p_limit, NULL);
END;
$$ LANGUAGE plpgsql;

-- Функция: Получение N последних свечей
CREATE OR REPLACE FUNCTION get_last_candles(
    p_symbol VARCHAR,
    p_timeframe INTEGER,
    p_count INTEGER
)
RETURNS TABLE (
    timestamp TIMESTAMPTZ,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    tick_volume BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT c.timestamp, c.open, c.high, c.low, c.close, c.volume, c.tick_volume
    FROM candle_data c
    WHERE c.symbol = p_symbol
      AND c.timeframe = p_timeframe
    ORDER BY c.timestamp DESC
    LIMIT p_count;
END;
$$ LANGUAGE plpgsql;

-- ===========================================
-- Статистика и мониторинг
-- ===========================================

-- Представление: Статистика по свечным данным
CREATE OR REPLACE VIEW v_candle_data_stats AS
SELECT
    symbol,
    timeframe,
    COUNT(*) as total_rows,
    MIN(timestamp) as first_timestamp,
    MAX(timestamp) as last_timestamp,
    pg_size_pretty(pg_total_relation_size('candle_data')) as total_size
FROM candle_data
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;

-- Представление: Количество записей по временным интервалам
CREATE OR REPLACE VIEW v_data_volume_by_day AS
SELECT
    DATE(timestamp) as data_date,
    symbol,
    timeframe,
    COUNT(*) as row_count,
    MIN(timestamp) as first_record,
    MAX(timestamp) as last_record
FROM candle_data
GROUP BY DATE(timestamp), symbol, timeframe
ORDER BY data_date DESC;

-- ===========================================
-- Индексы для ускорения частых запросов
-- ===========================================

-- Составной индекс для быстрых выборок
CREATE INDEX IF NOT EXISTS idx_candle_data_symbol_tf_time
ON candle_data (symbol, timeframe, timestamp DESC);

-- Индекс для агрегаций по символам
CREATE INDEX IF NOT EXISTS idx_candle_data_symbol_only
ON candle_data (symbol);

-- ===========================================
-- Комментарии
-- ===========================================

COMMENT ON TABLE candle_data IS 'Свечные данные (OHLCV) - основная hypertable';
COMMENT ON TABLE tick_data IS 'Тиковые данные - для высокочастотного анализа';
COMMENT ON TABLE orderbook_data IS 'Стакан заявок - для анализа ликвидности';
COMMENT ON MATERIALIZED VIEW candle_data_1h IS 'Часовые агрегаты свечных данных';
COMMENT ON MATERIALIZED VIEW candle_data_1d IS 'Дневные агрегаты свечных данных';
