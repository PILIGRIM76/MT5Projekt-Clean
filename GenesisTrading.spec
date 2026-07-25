# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main_pyside.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('configs', 'configs'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'src.core.trading_system', 'src.core.event_bus', 'src.core.config_loader',
        'src.core.config_models', 'src.core.config_writer', 'src.core.orchestrator',
        'src.core.hot_reload_manager', 'src.core.circuit_breaker', 'src.core.lock_manager',
        'src.core.task_queue', 'src.core.health_monitor', 'src.core.resource_governor',
        'src.core.safety_monitor', 'src.core.secrets_manager', 'src.core.secure_config',
        'src.core.mt5_connection_manager', 'src.core.paper_trading_engine',
        'src.core.online_learner', 'src.core.training_scheduler',
        'src.core.services.ml_service', 'src.core.services.orchestrator_service',
        'src.core.services.risk_service', 'src.core.services.execution_service',
        'src.core.services.signal_service', 'src.core.services.data_service',
        'src.core.services.portfolio_service', 'src.core.services.monitoring_service',
        'src.core.services.trading_service', 'src.core.services.trade_executor',
        'src.db.database_manager', 'src.db.multi_database_manager',
        'src.db.vector_db_manager', 'src.db.models',
        'src.ml.model_factory', 'src.ml.feature_engineer', 'src.ml.predictor',
        'src.ml.ensemble_predictor', 'src.ml.consensus_engine',
        'src.ml.genetic_programming_core', 'src.ml.orchestrator_env',
        'src.ml.rl_trade_manager', 'src.ml.news_enrichment', 'src.ml.championship',
        'src.ml.auto_trainer', 'src.ml.retrain_scheduler',
        'src.strategies.strategy_loader', 'src.strategies.breakout',
        'src.strategies.mean_reversion', 'src.strategies.moving_average_crossover',
        'src.strategies.adaptive', 'src.strategies.strategy_optimizer',
        'src.risk.circuit_breaker', 'src.monitoring.alert_manager',
        'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
        'src.gui.trading_system_adapter', 'src.gui.sound_manager',
        'src.gui.widgets.graph_widgets', 'src.gui.widgets.bridges',
        'src.gui.trading_modes_widget', 'src.gui.unified_trading_settings',
        'src.utils.worker', 'src.utils.logger', 'src.utils.scheduler_manager',
        'src.utils.cache_manager', 'src.utils.device_manager',
        'src.data.data_provider', 'src.analysis.strategy_optimizer',
        'src.web.server', 'src.social.bus',
        'pyqtgraph', 'numpy', 'pandas', 'scipy', 'sklearn', 'torch',
        'stable_baselines3', 'lightgbm', 'httpx', 'dotenv', 'pydantic', 'MetaTrader5',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    cipher=block_cipher, noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='GenesisTrading',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=True, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None, icon=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='GenesisTrading',
)
