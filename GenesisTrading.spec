# -*- mode: python ; coding: utf-8 -*-
# Genesis Trading System - PyInstaller Spec File
# Для GitHub Actions

import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Директории
spec_dir = os.path.dirname(os.path.abspath(SPEC))
project_root = spec_dir

# Данные для включения
datas = [
    ('configs', 'configs'),
    ('assets', 'assets'),
    ('src', 'src'),
    ('README.md', '.'),
    ('QUICK_START.md', '.'),
    ('HOW_TO_RUN.md', '.'),
]

# Исключения
excluded_modules = [
    # Тесты
    'matplotlib.tests',
    'numpy.testing',
    'torch.testing',
    'pandas.tests',
    'sklearn.tests',
    
    # Jupyter
    'IPython',
    'jupyter',
    'notebook',
    'nbconvert',
    
    # Конфликтующие Qt
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    
    # Проблемные подмодули
    'nltk.twitter',
    'nltk.app',
    'optuna.multi_objective',
    'pyqtgraph.opengl',
]

# Скрытые импорты
hiddenimports = [
    # PySide6
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtCharts',
    'PySide6.QtMultimedia',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebChannel',
    
    # PyTorch
    'torch',
    'torchvision',
    'torchaudio',
    
    # Trading
    'MetaTrader5',
    
    # Data
    'numpy',
    'pandas',
    'scipy',
    'matplotlib',
    
    # ML
    'sklearn',
    'lightgbm',
    'stable_baselines3',
    'stable_baselines3.common',
    'gymnasium',
    'optuna',
    'shap',
    
    # NLP
    'transformers',
    'sentence_transformers',
    'sentencepiece',
    'nltk',
    
    # Web
    'fastapi',
    'fastapi.middleware',
    'fastapi.staticfiles',
    'uvicorn',
    'websockets',
    'jinja2',
    'schedule',
    
    # Utils
    'pydantic',
    'dotenv',
    'numba',
    'llvmlite',
    
    # Database
    'sqlalchemy',
    'faiss',
    'neo4j',
    
    # Trading system
    'arch',
    'pyqtgraph',
    
    # Network
    'httpx',
    'requests',
    'urllib3',
    'telethon',
    
    # Стандартные модули
    'pydoc',
    'doctest',
    'multiprocessing',
    'asyncio',
    'concurrent.futures',
    'dateutil',
    'dateutil.tz',
    'zoneinfo',
    'six.moves',
    'scipy.special',
    
    # Torch
    'torch.nn',
    'torch.optim',
    'torch.utils',
    'torch.distributed',
    'torch.multiprocessing',
    
    # Transformers
    'transformers.models',
    'transformers.benchmark',
]

# Runtime hooks для matplotlib
runtime_hooks = [
    os.path.join(spec_dir, 'hooks', 'mpl_patch.py'),
]

# Сборка
a = Analysis(
    ['main_pyside.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(spec_dir, 'hooks')],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=excluded_modules,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GenesisTrading',
    debug=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon=os.path.join(project_root, 'assets', 'icon.ico.ico') if os.path.exists(os.path.join(project_root, 'assets', 'icon.ico.ico')) else None,
)
