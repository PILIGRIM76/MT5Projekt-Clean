# -*- mode: python ; coding: utf-8 -*-


import os
from pathlib import Path

# Найти путь к stable_baselines3
try:
    import stable_baselines3
    sb3_path = Path(stable_baselines3.__file__).parent
    version_file = sb3_path / 'version.txt'
    sb3_datas = [(str(version_file), 'stable_baselines3')] if version_file.exists() else []
except:
    sb3_datas = []

a = Analysis(
    ['main_pyside.py'],
    pathex=[],
    binaries=[],
    datas=sb3_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GenesisTrading',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
