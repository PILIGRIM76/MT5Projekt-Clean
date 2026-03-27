@echo off
REM Type checking script for mypy

echo ========================================
echo  Type Checking with mypy
echo ========================================

REM Check if mypy is installed
python -m pip show mypy >nul 2>&1
if errorlevel 1 (
    echo mypy not found. Installing...
    python -m pip install mypy
)

echo.
echo Running mypy...
python -m mypy --config-file mypy.ini

if errorlevel 0 (
    echo.
    echo ========================================
    echo  Type checking completed successfully!
    echo ========================================
) else (
    echo.
    echo ========================================
    echo  Type issues found!
    echo ========================================
)

pause
