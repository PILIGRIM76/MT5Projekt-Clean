# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Collect all data files
datas = [
    ('assets', 'assets'),
    ('configs/settings.example.json', 'configs'),
    ('README.md', '.'),
    ('QUICK_START.md', '.'),
    ('LICENSE', '.'),
    ('src', 'src'),  # Include entire src folder
]

# Add package metadata for transformers and dependencies
import os
import site
site_packages = site.getsitepackages()[0]

# Add stable_baselines3 version.txt
import stable_baselines3
sb3_path = os.path.dirname(stable_baselines3.__file__)
sb3_version = os.path.join(sb3_path, 'version.txt')
if os.path.exists(sb3_version):
    datas.append((sb3_version, 'stable_baselines3'))

# Critical packages that need metadata
metadata_packages = [
    'numpy', 'pandas', 'torch', 'transformers', 'sentence_transformers',
    'accelerate', 'tokenizers', 'huggingface_hub', 'safetensors',
    'sklearn', 'scipy', 'lightgbm', 'pydantic', 'pydantic_settings'
]

for pkg in metadata_packages:
    pkg_path = os.path.join(site_packages, f'{pkg}-*.dist-info')
    import glob
    for dist_info in glob.glob(pkg_path):
        if os.path.isdir(dist_info):
            pkg_name = os.path.basename(dist_info)
            datas.append((dist_info, pkg_name))

# Hidden imports for all dependencies
hiddenimports = [
    'MetaTrader5',
    'PySide6',
    'torch',
    'lightgbm',
    'sklearn',
    'pandas',
    'numpy',
    'faiss',
    'sentence_transformers',
    'transformers',
    'neo4j',
    'aiohttp',
    'asyncio',
    'websockets',
    'plotly',
    'matplotlib',
    'matplotlib.pyplot',
    'ta',
    'optuna',
    'stable_baselines3',
    'gymnasium',
    'deap',
    'chromadb',
    'feedparser',
    'beautifulsoup4',
    'requests',
    'sqlalchemy',
    'pydantic',
    'pydantic_settings',
    'pyqtgraph',
    'shap',
    'telethon',
    'telethon.sync',
    'ntscraper',
    'newsapi',
    'newsapi.newsapi_client',
    'httpx',
    'httpx._client',
    'arch',
    'arch.univariate',
    'nltk',
    'sentencepiece',
    'schedule',
    'dotenv',
    'python_dotenv',
    'uvicorn',
    'fastapi',
    'statsmodels',
    'statsmodels.sandbox',
    'statsmodels.sandbox.regression',
    'statsmodels.sandbox.regression.sympy_diff',
    # Utils modules (CRITICAL!)
    'src.utils',
    'src.utils.worker',
    'src.utils.analysis_utils',
    'src.utils.scheduler_manager',
    # Core modules
    'src.core.trading_system',
    'src.core.safety_monitor',
    'src.core.config_models',
    'src.core.orchestrator',
    'src.core.training_scheduler',
    'src.core.config_loader',
    'src.core.config_writer',
    'src.core.interfaces',
    'src.core.online_learner',
    'src.core.auto_updater',
    'src.core.session_manager',
    'src.core.services',
    'src.core.services.signal_service',
    # ML modules
    'src.ml.model_factory',
    'src.ml.feature_engineer',
    'src.ml.consensus_engine',
    'src.ml.rl_trade_manager',
    'src.ml.ai_backtester',
    'src.ml.architectures',
    'src.ml.genetic_programming_core',
    'src.ml.orchestrator_env',
    # Data modules
    'src.data.data_provider',
    'src.data.multi_source_aggregator',
    'src.data.blockchain_provider',
    'src.data.alternative_data_provider',
    'src.data.graph_db_manage',
    'src.data.knowledge_graph_querier',
    'src.data.proactive_data_finder',
    'src.data.web_scraper',
    # Analysis modules
    'src.analysis.market_screener',
    'src.analysis.market_regime_manager',
    'src.analysis.nlp_processor',
    'src.analysis.anomaly_detector',
    'src.analysis.gp_rd_manager',
    'src.analysis.drift_detector',
    'src.analysis.backtester',
    'src.analysis.event_driven_backtester',
    'src.analysis.simulators',
    'src.analysis.strategy_incubator',
    'src.analysis.strategy_optimizer',
    'src.analysis.stress_tester',
    'src.analysis.synthetic_indices',
    'src.analysis.system_backtester',
    # Risk modules
    'src.risk.risk_engine',
    'src.risk.auto_configurator',
    'src.risk.volatility_forecaster',
    # Database modules
    'src.db.database_manager',
    'src.db.vector_db_manager',
    # GUI modules
    'src.gui.main_window',
    'src.gui.modern_main_window',
    'src.gui.control_center_widget',
    'src.gui.log_utils',
    'src.gui.api_tester',
    'src.gui.settings_window',
    'src.gui.sound_manager',
    'src.gui.styles',
    'src.gui.dialogs',
    # Web modules
    'src.web.server',
    'src.web.data_models',
    # Strategies
    'src.strategies.strategy_loader',
    'src.strategies.breakout',
    'src.strategies.mean_reversion',
    'src.strategies.ma_crossover',
    'src.strategies.moving_average_crossover',
    'src.strategies.adaptive',
    'src.strategies.StrategyInterface',
    # Root modules
    'src.data_models',
    'src._version',
]

a = Analysis(
    ['main_pyside.py'],
    pathex=['src'],  # Add src to path
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'sphinx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GenesisTrading',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Show console for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico.ico' if os.path.exists('assets/icon.ico.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GenesisTrading',
)
