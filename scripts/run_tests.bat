@echo off
REM Test runner script for pytest

echo ========================================
echo  Running Tests - Genesis Trading System
echo ========================================

REM Check if pytest is installed
python -m pip show pytest >nul 2>&1
if errorlevel 1 (
    echo pytest not found. Installing...
    python -m pip install pytest
)

echo.
echo Running pytest...
python -m pytest tests/ -v

if errorlevel 0 (
    echo.
    echo ========================================
    echo  All tests passed!
    echo ========================================
) else (
    echo.
    echo ========================================
    echo  Some tests failed!
    echo ========================================
)

pause
