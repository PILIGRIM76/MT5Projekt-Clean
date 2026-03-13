@echo off
title Genesis Trading System - Full Build
color 0A

echo.
echo  ╔════════════════════════════════════════════════════════════╗
echo  ║                                                            ║
echo  ║        GENESIS TRADING SYSTEM - RELEASE BUILD             ║
echo  ║                                                            ║
echo  ╚════════════════════════════════════════════════════════════╝
echo.
echo  This script will:
echo    1. Build EXE from source
echo    2. Create portable ZIP package
echo    3. Create Windows installer (if Inno Setup installed)
echo.
echo  Estimated time: 15-20 minutes
echo.
pause

REM Step 1: Build EXE
echo.
echo ════════════════════════════════════════════════════════════
echo  STEP 1/3: Building EXE
echo ════════════════════════════════════════════════════════════
call build_exe.bat
if errorlevel 1 (
    echo.
    echo ERROR: EXE build failed!
    pause
    exit /b 1
)

REM Step 2: Create portable version
echo.
echo ════════════════════════════════════════════════════════════
echo  STEP 2/3: Creating Portable Package
echo ════════════════════════════════════════════════════════════
call create_portable.bat
if errorlevel 1 (
    echo.
    echo ERROR: Portable package creation failed!
    pause
    exit /b 1
)

REM Step 3: Create installer (if Inno Setup is installed)
echo.
echo ════════════════════════════════════════════════════════════
echo  STEP 3/3: Creating Windows Installer
echo ════════════════════════════════════════════════════════════

where iscc >nul 2>&1
if %errorlevel% equ 0 (
    echo Inno Setup found! Creating installer...
    iscc installer_script.iss
    if errorlevel 1 (
        echo WARNING: Installer creation failed, but portable version is ready.
    ) else (
        echo.
        echo ✓ Installer created successfully!
    )
) else (
    echo.
    echo Inno Setup not found. Skipping installer creation.
    echo.
    echo To create installer:
    echo   1. Download Inno Setup from https://jrsoftware.org/isdl.php
    echo   2. Install it
    echo   3. Run: iscc installer_script.iss
    echo.
    echo Portable version is ready to use!
)

REM Summary
echo.
echo.
echo  ╔════════════════════════════════════════════════════════════╗
echo  ║                                                            ║
echo  ║                    BUILD COMPLETE!                         ║
echo  ║                                                            ║
echo  ╚════════════════════════════════════════════════════════════╝
echo.
echo  📦 DELIVERABLES:
echo.
echo    1. Portable ZIP:
echo       GenesisTrading_Portable_v1.0.0.zip
echo.
if exist installer_output\GenesisTrading_Setup_v1.0.0.exe (
    echo    2. Windows Installer:
    echo       installer_output\GenesisTrading_Setup_v1.0.0.exe
    echo.
)
echo  📊 PACKAGE SIZES:
echo.
dir GenesisTrading_Portable_v1.0.0.zip 2>nul | find ".zip"
if exist installer_output\GenesisTrading_Setup_v1.0.0.exe (
    dir installer_output\GenesisTrading_Setup_v1.0.0.exe | find ".exe"
)
echo.
echo  📝 NEXT STEPS:
echo.
echo    1. Test the portable version
echo    2. Test the installer (if created)
echo    3. Upload to GitHub Releases
echo    4. Update README.md with download links
echo.
echo  ⚠️  IMPORTANT:
echo.
echo    Users need to configure settings.json before first run!
echo    See QUICK_START.md for instructions.
echo.
echo  ════════════════════════════════════════════════════════════
echo.

pause
