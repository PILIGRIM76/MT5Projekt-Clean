# src/core/config_models.py
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# --- Вложенные модели с документацией ---


class ScreenerVolatilitySettings(BaseModel):
    ideal_min_percent: float = Field(default=0.05, description="Минимальная идеальная волатильность (ATR/close) в %.")
    ideal_max_percent: float = Field(default=0.5, description="Максимальная идеальная волатильность (ATR/close) в %.")


class ScreenerTrendSettings(BaseModel):
    adx_threshold: int = Field(default=20, description="Порог ADX для определения наличия тренда.")


class ScreenerLiquiditySettings(BaseModel):
    ideal_max_spread_pips: float = Field(default=5.0, description="Максимальный идеальный спред в пипсах.")


class ScreenerWeightsSettings(BaseModel):
    volatility: float = Field(default=0.6, description="Вес оценки волатильности в итоговом ранге.")
    trend: float = Field(default=0.3, description="Вес оценки тренда в итоговом ранге.")
    liquidity: float = Field(default=0.1, description="Вес оценки ликвидности в итоговом ранге.")


class BreakoutStrategyParams(BaseModel):
    window: int = Field(default=15, description="Окно (количество баров) для определения канала пробоя.")


class MeanReversionStrategyParams(BaseModel):
    window: int = Field(default=50, description="Окно для расчета скользящей средней.")
    std_dev_multiplier: float = Field(default=1.9, description="Множитель стандартного отклонения для каналов.")
    confirmation_buffer_std_dev_fraction: float = Field(
        default=0.05, description="Буфер для подтверждения возврата к среднему."
    )


class MACrossoverTimeframeParams(BaseModel):
    short_window: int = Field(default=15, description="Период короткой скользящей средней.")
    long_window: int = Field(default=35, description="Период длинной скользящей средней.")


class MACrossoverStrategyParams(BaseModel):
    timeframe_params: Dict[str, MACrossoverTimeframeParams] = Field(
        default_factory=lambda: {
            "default": MACrossoverTimeframeParams(short_window=15, long_window=35),
            "low": MACrossoverTimeframeParams(short_window=10, long_window=25),
            "high": MACrossoverTimeframeParams(short_window=50, long_window=200),
        },
        description="Параметры MA для разных уровней волатильности.",
    )


class StrategiesParams(BaseModel):
    breakout: BreakoutStrategyParams = Field(default_factory=BreakoutStrategyParams)
    mean_reversion: MeanReversionStrategyParams = Field(default_factory=MeanReversionStrategyParams)
    ma_crossover: MACrossoverStrategyParams = Field(default_factory=MACrossoverStrategyParams)


class OptimizerSettings(BaseModel):
    ideal_volatility: float = Field(default=0.005, description="Целевая волатильность для выбора оптимального таймфрейма.")
    timeframes_to_check: Dict[str, int] = Field(
        default_factory=lambda: {"M1": 1, "M5": 5, "M15": 15, "H1": 16385, "H4": 16388, "D1": 16408},
        description="Словарь таймфреймов для проверки оптимизатором.",
    )
    MAX_OPEN_POSITIONS: int = Field(default=10, description="Макс. позиций для системного бэктестера.")
    MAX_HOLD_BARS: int = Field(default=24, description="Макс. время удержания позиции в барах для системного бэктестера.")
    CORRELATION_THRESHOLD: float = Field(default=0.7, description="Порог корреляции для системного бэктестера.")


class ModelCandidate(BaseModel):
    type: str = Field(default="LSTM_PyTorch", description="Тип модели для обучения (напр. 'LSTM_PyTorch').")
    k: Any = Field(default="all", description="Параметр для выбора признаков ('all' или число).")


class RDCycleSettings(BaseModel):
    sharpe_ratio_threshold: float = Field(default=1.2, description="Минимальный коэф. Шарпа для прохождения R&D.")
    max_drawdown_threshold: float = Field(default=15.0, description="Макс. просадка в % для прохождения R&D.")
    performance_check_trades_min: int = Field(default=20, description="Мин. кол-во сделок для оценки производительности.")
    profit_factor_threshold: float = Field(default=1.1, description="Минимальный профит-фактор для прохождения R&D.")
    model_candidates: List[ModelCandidate] = Field(
        default_factory=lambda: [{"type": "LSTM_PyTorch", "k": 10}, {"type": "LightGBM", "k": "all"}],
        description="Список моделей-кандидатов для обучения в R&D цикле.",
    )


class OnlineLearningSettings(BaseModel):
    enabled: bool = Field(default=False, description="Включить/отключить онлайн-дообучение моделей.")
    learning_rate: float = Field(default=0.0001, description="Скорость обучения для корректировки весов.")
    adjustment_factor: float = Field(default=0.1, description="Коэффициент силы корректировки цели.")
    max_expected_profit: float = Field(default=100.0, description="Ожидаемая макс. прибыль со сделки для нормализации.")


class AnomalyDetectorSettings(BaseModel):
    enabled: bool = Field(default=True, description="Включить/отключить детектор аномалий.")
    training_data_bars: int = Field(default=5000, description="Кол-во баров для обучения автоэнкодера.")
    features: List[str] = Field(
        default_factory=lambda: ["ATR_NORM", "SKEW_60", "KURT_60", "VOLA_60", "DIST_EMA_50"],
        description="Список признаков для детектора аномалий.",
    )
    threshold_std_multiplier: float = Field(default=3.0, description="Множитель СКО для определения порога аномалии.")
    risk_off_duration_hours: int = Field(default=4, description="На сколько часов блокировать торговлю после аномалии.")
    epochs: int = Field(default=50)
    batch_size: int = Field(default=32)


# --- НОВЫЙ КЛАСС: Веса для Многофакторного Консенсуса ---
class ConsensusWeights(BaseModel):
    ai_forecast: float = Field(default=0.4, description="Вес прогноза AI-модели.")
    classic_strategies: float = Field(default=0.3, description="Вес подтверждения от классических стратегий.")
    sentiment_kg: float = Field(default=0.2, description="Вес сентимента из Графа Знаний.")
    on_chain_data: float = Field(default=0.1, description="Вес подтверждения от On-Chain данных (для крипто).")


# --------------------------------------------------------


class ConceptDriftSettings(BaseModel):
    enabled: bool = Field(default=True, description="Включить детектор дрейфа концепции.")
    adwin_delta: float = Field(default=0.002, description="Чувствительность ADWIN (меньше = чувствительнее).")
    min_window_size: int = Field(default=30, description="Минимальный размер окна для начала проверки.")


class MarketRegimeSettings(BaseModel):
    adx_threshold: float = Field(default=25, description="Порог ADX для определения тренда.")
    volatility_high_percentile: float = Field(
        default=0.80, description="Верхний процентиль для определения высокой волатильности."
    )
    volatility_low_percentile: float = Field(
        default=0.20, description="Нижний процентиль для определения низкой волатильности."
    )
    ema_slope_threshold: float = Field(default=0.0001, description="Порог наклона EMA для подтверждения тренда.")
    volatility_rank_window: int = Field(default=252, description="Окно для расчета исторического ранга волатильности.")


class PreMortemSettings(BaseModel):
    enabled: bool = Field(default=True, description="Включить/отключить pre-mortem анализ (симуляция Монте-Карло).")
    num_simulations: int = Field(default=1000, description="Количество симуляций Монте-Карло.")
    simulation_horizon_bars: int = Field(default=20, description="Горизонт симуляции в барах.")
    tail_risk_multiplier: float = Field(
        default=2.0, description="Множитель для определения 'катастрофического' убытка (X * SL)."
    )
    tail_risk_probability_threshold: float = Field(
        default=0.05, description="Макс. допустимая вероятность катастрофического убытка."
    )


class TrailingProfitSettings(BaseModel):
    enabled: bool = Field(default=True, description="Включить механизм защиты прибыли (Trailing Profit).")
    activation_threshold_percent: float = Field(default=0.3, description="Минимальная прибыль (%) для активации трейлинга.")
    pullback_percent: float = Field(
        default=0.15, description="Допустимый откат прибыли (%). Если цена откатит на этот % от пика, сделка закроется."
    )


class RiskEngineSettings(BaseModel):
    confidence_risk_map: Dict[str, float] = Field(
        default={"low": 0.5, "medium": 1.0, "high": 1.5}, description="Множители риска в зависимости от уверенности сигнала."
    )

    recent_trades_for_dynamic_risk: int = Field(
        default=20, description="Кол-во последних сделок для оценки динамического риска."
    )
    drawdown_sensitivity_threshold: float = Field(
        default=2.0, description="Порог текущей просадки в %, при котором риск снижается до минимума."
    )
    portfolio_var_confidence_level: float = Field(default=0.99, description="Уровень доверия для расчета VaR портфеля.")
    toxic_regime_update_interval_sec: int = Field(
        default=3600, description="Как часто обновлять кэш 'токсичных' режимов (в секундах)."
    )
    toxic_regime_risk_multiplier: float = Field(default=0.5, description="Множитель риска, применяемый в 'токсичном' режиме.")
    hedge_risk_reduction_factor: float = Field(
        default=0.5, description="Какую долю избыточного риска покрывать хеджирующей сделкой."
    )

    # Поля для торговых режимов
    stop_loss_atr_multiplier: float = Field(default=3.0, description="Множитель ATR для стоп-лосса.")
    risk_reward_ratio: float = Field(default=2.5, description="Соотношение риск/прибыль.")
    enable_all_risk_checks: bool = Field(default=True, description="Включить все проверки риска.")

    pre_mortem: PreMortemSettings = Field(default_factory=PreMortemSettings)

    trailing_profit: TrailingProfitSettings = Field(default_factory=TrailingProfitSettings)


class RLManagerRewardSettings(BaseModel):
    hold_reward_multiplier: float = Field(default=0.01, description="Награда за удержание прибыльной позиции (за бар).")
    partial_close_multiplier: float = Field(default=0.5, description="Награда за частичное закрытие прибыльной позиции.")
    move_sl_to_be_reward: float = Field(default=0.25, description="Награда за перевод стопа в безубыток.")
    move_sl_to_be_penalty: float = Field(default=-0.1, description="Штраф за попытку перевода в б/у убыточной позиции.")
    sl_hit_penalty: float = Field(default=-1.0, description="Штраф за срабатывание стоп-лосса.")
    tp_hit_reward: float = Field(default=1.0, description="Награда за срабатывание тейк-профита.")


class RLManagerSettings(BaseModel):
    training_timesteps_per_trade: int = Field(default=2000, description="Кол-во шагов обучения на одну реальную сделку.")
    rewards: RLManagerRewardSettings = Field(default_factory=RLManagerRewardSettings)


class OrchestratorSettings(BaseModel):
    decision_interval_seconds: int = Field(
        default=14400, description="Интервал принятия решений Оркестратором (перераспределение капитала)."
    )
    training_interval_seconds: int = Field(default=604800, description="Интервал дообучения RL-модели Оркестратора.")


class SystemSettings(BaseModel):
    initial_history_sync_days: int = Field(
        default=90, description="Глубина первоначальной синхронизации истории сделок (в днях)."
    )
    history_sync_margin_minutes: int = Field(default=5, description="Запас времени для повторного запроса истории сделок.")


class VectorDBSettings(BaseModel):
    enabled: bool = Field(default=True, description="Включить/отключить использование векторной БД.")
    path: str = Field(default="database/vector_db", description="Путь для хранения локальной векторной БД.")
    collection_name: str = Field(default="news_and_events", description="Имя коллекции в векторной БД.")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="Модель для создания эмбеддингов.")
    cleanup_enabled: bool = Field(default=True, description="Включить автоматическую очистку VectorDB.")
    max_age_days: int = Field(default=90, description="Максимальный возраст документов для хранения (в днях).")
    cleanup_interval_hours: int = Field(default=24, description="Интервал запуска очистки (в часах).")


# WebSettings
class WebSettings(BaseModel):
    enabled: bool = Field(default=True, description="Включить веб-дашборд.")
    host: str = Field(default="0.0.0.0", description="Хост для веб-сервера.")
    port: int = Field(default=8000, description="Порт для веб-сервера.")


class AutoRetrainingSettings(BaseModel):
    """Settings for automatic model retraining scheduler."""

    enabled: bool = Field(default=True, description="Включить автоматическое переобучение моделей.")
    schedule_time: str = Field(default="02:00", description="Время запуска обучения в формате HH:MM.")
    interval_hours: float = Field(default=0.5, description="Интервал между запусками в часах (0.5 = 30 мин).")
    max_symbols: int = Field(default=30, description="Макс. кол-во символов для обучения.")
    max_workers: int = Field(default=3, description="Кол-во параллельных потоков обучения.")


class ChampionshipSettings(BaseModel):
    """Настройки чемпионата моделей (автоматический отбор лучших)."""

    enabled: bool = Field(default=True, description="Включить чемпионат моделей")
    evaluation_window: int = Field(default=2000, description="Размер окна данных для оценки (в барах)")
    min_sharpe_ratio: float = Field(default=0.3, description="Минимальный Sharpe ratio для прохождения порога")
    min_win_rate: float = Field(default=0.40, description="Минимальный Win Rate")
    max_drawdown_percent: float = Field(default=20.0, description="Максимальная просадка в %")
    min_profit_factor: float = Field(default=0.8, description="Минимальный Profit Factor")
    interval_days: int = Field(default=7, description="Интервал проведения чемпионата (в днях)")
    quarantine_days: int = Field(default=3, description="Период карантина для новой модели (в днях)")
    commission_per_trade: float = Field(default=0.0001, description="Комиссия за сделку (для симуляции)")
    slippage_percent: float = Field(default=0.0002, description="Проскальзывание (для симуляции)")
    walk_forward_splits: int = Field(default=5, description="Количество сплитов для walk-forward валидации")
    candidate_models: List[str] = Field(
        default_factory=lambda: ["EURUSD_model", "GBPUSD_model", "XAUUSD_model"],
        description="Список моделей-кандидатов для участия в чемпионате",
    )


# === НАСТРОЙКИ УВЕДОМЛЕНИЙ ===
class TelegramChannelSettings(BaseModel):
    """Настройки Telegram канала."""

    enabled: bool = Field(default=False, description="Включить Telegram уведомления")
    bot_token_env: str = Field(default="TELEGRAM_BOT_TOKEN", description="Переменная окружения для токена")
    chat_id_env: str = Field(default="TELEGRAM_CHAT_ID", description="Переменная окружения для Chat ID")


class EmailChannelSettings(BaseModel):
    """Настройки Email канала."""

    enabled: bool = Field(default=False, description="Включить Email уведомления")
    smtp_server: str = Field(default="smtp.gmail.com", description="SMTP сервер")
    smtp_port: int = Field(default=587, description="SMTP порт")
    use_tls: bool = Field(default=True, description="Использовать TLS")
    from_email_env: str = Field(default="ALERT_EMAIL_FROM", description="Переменная для Email отправителя")
    password_env: str = Field(default="ALERT_EMAIL_PASSWORD", description="Переменная для пароля")
    recipients_env: str = Field(default="ALERT_EMAIL_RECIPIENTS", description="Переменная для получателей")


class PushChannelSettings(BaseModel):
    """Настройки Push уведомлений."""

    enabled: bool = Field(default=False, description="Включить Push уведомления")
    user_key_env: str = Field(default="PUSHOVER_USER_KEY", description="Переменная для ключа пользователя")
    api_token_env: str = Field(default="PUSHOVER_API_TOKEN", description="Переменная для API токена")


class RateLimitSettings(BaseModel):
    """Настройки ограничения частоты уведомлений."""

    max_per_minute: int = Field(default=10, description="Максимум уведомлений в минуту")
    cooldown_seconds: int = Field(default=60, description="Пауза между уведомлениями в секундах")


class QuietHoursSettings(BaseModel):
    """Настройки тихих часов."""

    enabled: bool = Field(default=False, description="Включить тихие часы")
    start: str = Field(default="22:00", description="Время начала тихих часов")
    end: str = Field(default="08:00", description="Время окончания тихих часов")
    timezone: str = Field(default="UTC", description="Часовой пояс")


class DailyDigestSettings(BaseModel):
    """Настройки ежедневного дайджеста."""

    enabled: bool = Field(default=True, description="Включить ежедневный дайджест")
    time: str = Field(default="20:00", description="Время отправки дайджеста")
    timezone: str = Field(default="UTC", description="Часовой пояс")


class AlertingSettings(BaseModel):
    """Общие настройки системы уведомлений."""

    enabled: bool = Field(default=False, description="Включить систему уведомлений")
    channels: Dict[str, Any] = Field(
        default_factory=lambda: {"telegram": {"enabled": False}, "email": {"enabled": False}, "push": {"enabled": False}},
        description="Настройки каналов уведомлений",
    )
    rate_limit: Dict[str, Any] = Field(
        default_factory=lambda: {"max_per_minute": 10, "cooldown_seconds": 60}, description="Ограничение частоты уведомлений"
    )
    quiet_hours: Dict[str, Any] = Field(
        default_factory=lambda: {"enabled": False, "start": "22:00", "end": "08:00", "timezone": "UTC"},
        description="Настройки тихих часов",
    )
    daily_digest: Dict[str, Any] = Field(
        default_factory=lambda: {"enabled": True, "time": "20:00", "timezone": "UTC"},
        description="Настройки ежедневного дайджеста",
    )


# --- Основная модель конфигурации ---
class CryptoExchangeConfig(BaseModel):
    """Конфигурация крипто-биржи."""

    enabled: bool = Field(default=False, description="Включить эту биржу")
    api_key_env: str = Field(default="", description="Переменная окружения для API Key")
    api_secret_env: str = Field(default="", description="Переменная окружения для API Secret")
    sandbox: bool = Field(default=False, description="Использовать тестнет/sandbox")
    symbols: List[str] = Field(default_factory=list, description="Список торговых пар (напр. BTC/USDT)")
    default_leverage: int = Field(default=1, description="Кредитное плечо по умолчанию")
    market_type: str = Field(default="spot", description="Тип рынка: spot или future")


class CryptoExchangesSettings(BaseModel):
    """Общие настройки крипто-бирж."""

    enabled: bool = Field(default=False, description="Включить поддержку крипто-бирж")
    default_exchange: str = Field(default="binance", description="Биржа по умолчанию")
    exchanges: Dict[str, CryptoExchangeConfig] = Field(
        default_factory=lambda: {
            "binance": CryptoExchangeConfig(
                enabled=False,
                api_key_env="BINANCE_API_KEY",
                api_secret_env="BINANCE_API_SECRET",
                sandbox=False,
                symbols=["BTC/USDT", "ETH/USDT"],
                default_leverage=1,
                market_type="spot",
            ),
            "bybit": CryptoExchangeConfig(
                enabled=False,
                api_key_env="BYBIT_API_KEY",
                api_secret_env="BYBIT_API_SECRET",
                sandbox=False,
                symbols=["BTC/USDT", "ETH/USDT"],
                default_leverage=1,
                market_type="spot",
            ),
        },
        description="Конфигурации крипто-бирж",
    )


class Settings(BaseModel):

    # --- MT5 Connection (из .env) ---
    MT5_LOGIN: str = Field(description="Логин счета MetaTrader 5.")
    MT5_PASSWORD: str = Field(description="Пароль счета MetaTrader 5.")
    MT5_SERVER: str = Field(description="Имя сервера MetaTrader 5.")
    MT5_PATH: str = Field(description="Полный путь к terminal64.exe.")

    # --- API Keys (из .env) ---
    FINNHUB_API_KEY: str
    ALPHA_VANTAGE_API_KEY: str
    NEWS_API_KEY: str
    POLYGON_API_KEY: str
    TWELVE_DATA_API_KEY: str
    FCS_API_KEY: str
    TELEGRAM_API_ID: str
    TELEGRAM_API_HASH: str
    TWITTER_BEARER_TOKEN: str
    SANTIMENT_API_KEY: str
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    FRED_API_KEY: str

    # --- General Settings ---
    SYMBOLS_WHITELIST: List[str] = Field(description="Список инструментов, разрешенных для торговли.")
    INTER_MARKET_SYMBOLS: List[str] = Field(default=[], description="Символы для межрыночного анализа (напр. DXY, VIX).")
    INTER_MARKET_SYMBOL_ALIASES: Dict[str, List[str]] = Field(
        default_factory=dict, description="Псевдонимы для межрыночных символов."
    )
    IGNORE_HISTORICAL_DRAWDOWN_ON_START: bool = Field(
        default=True, description="Игнорировать просадку до запуска системы при расчете дневного лимита."
    )

    TOP_N_SYMBOLS: int = Field(default=10, description="Количество лучших символов, отбираемых сканером для анализа.")

    screener_volatility: ScreenerVolatilitySettings = Field(default_factory=ScreenerVolatilitySettings)
    screener_trend: ScreenerTrendSettings = Field(default_factory=ScreenerTrendSettings)
    screener_liquidity: ScreenerLiquiditySettings = Field(default_factory=ScreenerLiquiditySettings)
    screener_weights: ScreenerWeightsSettings = Field(default_factory=ScreenerWeightsSettings)

    # --- ML Model Path Settings ---
    MODEL_DIR: str = Field(
        default="",
        description="Путь к директории с AI-моделями. Поддерживает абсолютные/относительные пути и переопределение через env MODEL_DIR.",
    )
    MODEL_FORMAT: str = Field(
        default="keras",
        description="Формат моделей: 'keras' (.h5/.keras), 'pytorch' (.pt), 'onnx' (.onnx).",
    )
    ACTIVE_MODEL: str = Field(
        default="lstm_v4",
        description="Имя активной модели (без расширения). Используется для загрузки при старте.",
    )
    BACKUP_MODEL: str = Field(
        default="lstm_v3",
        description="Имя резервной модели для fallback при повреждении активной модели.",
    )
    # --- ML Settings ---
    INPUT_LAYER_SIZE: int = Field(default=60, description="Размер входной последовательности (кол-во баров) для нейросетей.")
    TRAINING_DATA_POINTS: int = Field(default=2000, description="Кол-во баров для набора данных при обучении моделей.")
    PREDICTION_DATA_POINTS: int = Field(default=300, description="Кол-во баров, запрашиваемых для формирования прогноза.")
    FEATURES_TO_USE: List[str] = Field(description="Список признаков, используемых AI-моделями.")

    # --- Genetic Programming ---
    GP_POPULATION_SIZE: int
    GP_GENERATIONS: int
    GP_MUTATION_RATE: float
    GP_CROSSOVER_RATE: float
    GP_ELITISM_SIZE: int
    GP_TOURNAMENT_SIZE: int
    GP_TRIGGER_WIN_RATE: float
    GP_MIN_TRADES_SAMPLE: int

    # --- Trade Logic ---
    ENTRY_THRESHOLD: float = Field(description="Минимальное прогнозируемое изменение цены (в %) для открытия сделки AI.")
    CONSENSUS_THRESHOLD: float
    SENTIMENT_THRESHOLD: float
    DIVERGENCE_BLOCK_MINUTES: int

    # --- НОВОЕ ПОЛЕ: Веса Консенсуса ---
    CONSENSUS_WEIGHTS: ConsensusWeights = Field(default_factory=ConsensusWeights)
    # -----------------------------------

    # --- Risk Management ---
    RISK_PERCENTAGE: float = Field(description="Базовый процент риска на сделку.")
    DYNAMIC_RISK_MIN_PERCENT: float = Field(
        description="Минимальный процент риска при использовании динамического управления."
    )
    STOP_LOSS_ATR_MULTIPLIER: float = Field(description="Множитель ATR для установки Stop Loss.")
    RISK_REWARD_RATIO: float = Field(description="Соотношение Прибыль/Риск.")
    MAX_DAILY_DRAWDOWN_PERCENT: float = Field(
        description="Макс. дневная просадка в %, после которой торговля останавливается."
    )
    MAX_OPEN_POSITIONS: int = Field(description="Максимальное кол-во одновременно открытых позиций.")
    CORRELATION_THRESHOLD: float = Field(description="Порог корреляции для блокировки однонаправленных сделок.")
    MAX_PORTFOLIO_VAR_PERCENT: float = Field(
        default=5.0, description="Максимальный VaR портфеля в %, при превышении которого включается хеджирование."
    )
    PORTFOLIO_VOLATILITY_THRESHOLD: float = Field(default=0.05, description="Порог волатильности портфеля.")

    # --- Trading Modes Support ---
    max_positions: int = Field(default=10, description="Максимальное количество позиций для режима торговли.")
    max_daily_drawdown: float = Field(default=5.0, description="Максимальная дневная просадка для режима торговли.")
    stop_loss_atr_multiplier: float = Field(default=3.0, description="Множитель ATR для Stop Loss в режиме торговли.")
    risk_reward_ratio: float = Field(default=2.5, description="Соотношение прибыль/риск в режиме торговли.")
    risk_percentage: float = Field(default=0.5, description="Процент риска на сделку в режиме торговли.")
    enable_all_risk_checks: bool = Field(default=True, description="Включить все проверки риска для режима торговли.")

    # --- Profit Control & Reentry ---
    MAX_PROFIT_PER_TRADE_PERCENT: float = Field(default=5.0, description="Макс. прибыль в % для закрытия сделки.")
    PROFIT_TARGET_MODE: str = Field(default="auto", description="Режим целевой прибыли: 'auto' или 'manual'.")
    PROFIT_TARGET_MANUAL_PERCENT: float = Field(default=5.0, description="Фиксированная целевая прибыль в % (ручной режим).")
    REENTRY_COOLDOWN_AFTER_PROFIT: int = Field(
        default=60, description="Пауза в минутах перед повторным входом после прибыльной сделки."
    )
    REENTRY_COOLDOWN_AFTER_LOSS: int = Field(
        default=30, description="Пауза в минутах перед повторным входом после убыточной сделки."
    )
    REENTRY_COOLDOWN_AFTER_BREAKEVEN: int = Field(
        default=45, description="Пауза в минутах перед повторным входом после безубытка."
    )

    # --- Strategy Settings ---
    STRATEGY_REGIME_MAPPING: Dict[str, str] = Field(description="Сопоставление режимов рынка и стратегий.")
    STRATEGY_WEIGHTS: Dict[str, float] = Field(description="Веса для подтверждающих классических стратегий.")
    STRATEGY_MIN_WIN_RATE_THRESHOLD: float = 0.45
    strategies: StrategiesParams = Field(default_factory=StrategiesParams)

    # --- News & Data Sources ---
    IMPORTANT_NEWS_ENTITIES: List[str] = Field(
        default_factory=list, description="Ключевые слова для определения важных новостей."
    )
    NEWS_CACHE_DURATION_MINUTES: int
    telegram_channels: List[str] = Field(default_factory=list, description="Список Telegram каналов для парсинга.")
    twitter_influencers: List[str] = Field(default_factory=list, description="Список Twitter аккаунтов для парсинга.")
    rss_feeds: List[str] = Field(default_factory=list, description="Список RSS-лент для парсинга.")
    news_api_queries: List[str] = Field(default_factory=list, description="Поисковые запросы для NewsAPI.")
    source_weights: Dict[str, float] = Field(
        default_factory=dict, description="Веса для различных источников данных в ConsensusEngine."
    )
    economic_calendar: Dict[str, Any] = Field(default_factory=dict, description="Настройки для экономического календаря.")

    # --- Other components ---
    optimizer: OptimizerSettings = Field(default_factory=OptimizerSettings)
    trading_sessions: Dict[str, List[str]]
    asset_types: Dict[str, str]
    DATABASE_FOLDER: str
    DATABASE_NAME: str

    HF_MODELS_CACHE_DIR: Optional[str] = Field(
        default=None,
        description="Папка для кэширования больших AI-моделей от Hugging Face. Если не указано, используется стандартная папка. Требуется перезапуск.",
    )
    ORCHESTRATOR_MODEL_PATH: Optional[str] = Field(
        default=None,
        description="Путь к файлу модели Оркестратора (PPO). По умолчанию: DATABASE_FOLDER/orchestrator_ppo_model.zip",
    )
    TRADE_INTERVAL_SECONDS: int
    TRAINING_INTERVAL_SECONDS: int
    EXCLUDED_SYMBOLS: List[str]
    rd_cycle_config: RDCycleSettings
    online_learning: OnlineLearningSettings
    anomaly_detector: AnomalyDetectorSettings

    concept_drift: ConceptDriftSettings = Field(default_factory=ConceptDriftSettings)

    market_regime: MarketRegimeSettings = Field(default_factory=MarketRegimeSettings)
    risk: RiskEngineSettings = Field(default_factory=RiskEngineSettings)
    rl_manager: RLManagerSettings = Field(default_factory=RLManagerSettings)
    orchestrator_settings: OrchestratorSettings = Field(alias="orchestrator", default_factory=OrchestratorSettings)
    system: SystemSettings = Field(default_factory=SystemSettings)
    vector_db: VectorDBSettings = Field(default_factory=VectorDBSettings)
    backtester_initial_balance: float = 10000.0

    graph_database: dict = Field(default_factory=dict, description="Настройки графовой базы данных.")
    ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION: bool = Field(
        default=False, description="Включает/отключает отрисовку Графа Знаний в GUI."
    )

    # --- GUI Settings ---
    GUI_THEME: str = Field(
        default="Темная",
        description="Тема интерфейса: 'Светлая' или 'Темная'",
    )
    ALWAYS_ON_TOP: bool = Field(
        default=False,
        description="Режим Always on Top — окно всегда поверх остальных",
    )
    USE_CUSTOM_TITLE_BAR: bool = Field(
        default=False,
        description="Использовать кастомную рамку окна без системных декораций",
    )
    ANIMATIONS_ENABLED: bool = Field(
        default=True,
        description="Включить анимации интерфейса (переключения, уведомления, пульсации)",
    )

    EVENT_BLOCK_WINDOW_HOURS: int
    ALLOW_WEEKEND_TRADING: bool
    WEEKEND_CLASSIC_STRATEGIES_ENABLED: bool = Field(default=True, description="Разрешить классические стратегии в выходные")
    CRYPTO_THRESHOLDS: dict = Field(
        default_factory=lambda: {
            "profit_factor": 0.5,
            "win_rate": 0.25,
            "sharpe_ratio": 0.1,
            "max_drawdown": 25.0,
            "total_trades": 5,
        },
        description="Сниженные пороги для криптовалют",
    )
    FOREX_THRESHOLDS: dict = Field(
        default_factory=lambda: {
            "profit_factor": 0.5,
            "win_rate": 0.25,
            "sharpe_ratio": 0.1,
            "max_drawdown": 20.0,
            "total_trades": 10,
        },
        description="Сниженные пороги для Forex на период обучения",
    )
    TEMPORARY_RELAXED_MODE: bool = Field(
        default=True, description="Временный режим со сниженными порогами для всех инструментов"
    )

    model_config = {"case_sensitive": False, "coerce_numbers_to_str": True}

    auto_retraining: AutoRetrainingSettings = Field(default_factory=AutoRetrainingSettings)
    championship: ChampionshipSettings = Field(
        default_factory=ChampionshipSettings, description="Настройки чемпионата моделей"
    )
    alerting: AlertingSettings = Field(default_factory=AlertingSettings, description="Настройки системы уведомлений")
    crypto_exchanges: CryptoExchangesSettings = Field(
        default_factory=CryptoExchangesSettings, description="Настройки крипто-бирж (ccxt)"
    )
    social_trading: Dict[str, Any] = Field(
        default_factory=dict, description="Настройки социальной торговли (копирование сделок)"
    )
    news_scheduler: Dict[str, Any] = Field(default_factory=dict, description="Настройки планировщика загрузки новостей")
