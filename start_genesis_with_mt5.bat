@echo off
echo ==================================================
echo   Genesis Trading System - Запуск с MT5
echo ==================================================
echo.

REM Запуск PowerShell скрипта
powershell -ExecutionPolicy Bypass -File "%~dp0start_genesis_with_mt5.ps1"

pause
