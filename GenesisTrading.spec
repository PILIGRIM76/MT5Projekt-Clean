# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main_pyside.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('configs', 'configs'),
        ('assets', 'assets'),
        ('logs', 'logs'),
        ('database', 'database'),
        ('README.md', '.'),
    ],
    hiddenimports=[
        'src.core.trading_system',
        'src.db.database_manager',
        'src.data.data_provider',
        'src.ml.model_factory',
        'src.strategies.strategy_loader',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
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
