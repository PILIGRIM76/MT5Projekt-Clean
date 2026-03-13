@echo off
echo ========================================
echo Genesis Trading System - Build EXE
echo ========================================
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat

echo [1/4] Cleaning old build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist GenesisTrading.spec del GenesisTrading.spec

echo.
echo [2/4] Installing PyInstaller...
pip install pyinstaller

echo.
echo [3/4] Building EXE (this may take 10-15 minutes)...
pyinstaller genesis_trading.spec --clean --noconfirm

echo.
echo [4/4] Copying additional files...
if exist dist\GenesisTrading (
    echo Copying configs...
    xcopy /E /I /Y configs dist\GenesisTrading\configs
    
    echo Copying documentation...
    copy README.md dist\GenesisTrading\
    copy QUICK_START.md dist\GenesisTrading\
    copy TROUBLESHOOTING_PROMPT.md dist\GenesisTrading\
    copy QUICK_FIX_GUIDE.md dist\GenesisTrading\
    
    echo Creating database folder...
    mkdir dist\GenesisTrading\database 2>nul
    mkdir dist\GenesisTrading\logs 2>nul
    
    echo.
    echo ========================================
    echo BUILD COMPLETE!
    echo ========================================
    echo.
    echo EXE location: dist\GenesisTrading\GenesisTrading.exe
    echo.
    echo IMPORTANT: Before running, configure:
    echo   - dist\GenesisTrading\configs\settings.json
    echo   - Add your MT5 credentials and API keys
    echo.
    echo To create installer, run: create_installer.bat
    echo ========================================
) else (
    echo.
    echo ========================================
    echo BUILD FAILED!
    echo ========================================
    echo Check the output above for errors.
)

pause
