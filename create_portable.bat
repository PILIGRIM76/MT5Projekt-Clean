@echo off
echo ========================================
echo Creating Portable ZIP Package
echo ========================================
echo.

if not exist "dist\GenesisTrading\GenesisTrading.exe" (
    echo ERROR: GenesisTrading.exe not found!
    echo Please run build_exe.bat first.
    pause
    exit /b 1
)

echo Fixing ma_crossover config issue...
powershell -Command "(Get-Content 'dist\GenesisTrading\configs\settings.json') -replace '\"ma_crossover\":\\s*\\{[^}]*\\}', '\"ma_crossover\": {}' | Set-Content 'dist\GenesisTrading\configs\settings.json'"

echo Copying additional files...

echo Copying configs...
xcopy /E /I /Y configs dist\GenesisTrading\configs

echo Copying setup launcher...
if exist "dist\GenesisSetup" (
    xcopy /E /I /Y dist\GenesisSetup dist\GenesisTrading\
    echo ✓ GenesisSetup.exe included
) else (
    echo ⚠ GenesisSetup.exe not found (optional)
)

echo Copying documentation...
copy README.md dist\GenesisTrading\
copy QUICK_START.md dist\GenesisTrading\
copy TROUBLESHOOTING_PROMPT.md dist\GenesisTrading\
copy QUICK_FIX_GUIDE.md dist\GenesisTrading\
copy HOW_TO_RUN.md dist\GenesisTrading\

echo Copying assets...
xcopy /E /I /Y assets dist\GenesisTrading\assets

echo Creating database and logs folders...
mkdir dist\GenesisTrading\database 2>nul
mkdir dist\GenesisTrading\logs 2>nul

echo.
echo Creating ZIP archive...
powershell -Command "Compress-Archive -Path 'dist\GenesisTrading\*' -DestinationPath 'GenesisTrading_Portable_v1.0.0.zip' -Force"

echo.
echo ========================================
echo PORTABLE PACKAGE CREATED!
echo ========================================
echo.
echo File: GenesisTrading_Portable_v1.0.0.zip
echo.
dir GenesisTrading_Portable_v1.0.0.zip
echo.
echo CONTENTS:
echo   - GenesisTrading.exe (main application)
echo   - GenesisSetup.exe (configuration wizard, optional)
echo.
echo USAGE:
echo   1. Run GenesisSetup.exe first to configure paths
echo   2. Then run GenesisTrading.exe for trading
echo.
echo ========================================
echo.

pause
