@echo off
REM Genesis Trading System - Установка всех зависимостей
REM Использование: install_all.bat

setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Genesis Trading System - Установка зависимостей       ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

REM Активация venv
if exist venv\Scripts\activate.bat (
    echo Активация виртуального окружения...
    call venv\Scripts\activate.bat
) else (
    echo Ошибка: venv не найдено!
    exit /b 1
)

echo.
echo [1/3] Установка PySide6 (может занять 10-20 минут)...
echo.
pip install PySide6 --no-cache-dir

echo.
echo [2/3] Установка остальных зависимостей...
echo.
pip install cryptography httpx sentence-transformers lightgbm scikit-learn fastapi uvicorn websockets aiohttp asyncpg --no-cache-dir

echo.
echo [3/3] Проверка установки...
echo.

python -c "import PySide6; print('PySide6:', PySide6.__version__)" 2>nul
if %errorlevel% equ 0 (
    echo ✓ PySide6 установлен
) else (
    echo ✗ PySide6 НЕ установлен
)

python -c "import cryptography" 2>nul
if %errorlevel% equ 0 (
    echo ✓ cryptography установлен
) else (
    echo ✗ cryptography НЕ установлен
)

python -c "import httpx" 2>nul
if %errorlevel% equ 0 (
    echo ✓ httpx установлен
) else (
    echo ✗ httpx НЕ установлен
)

echo.
echo ═══════════════════════════════════════════════════════════
echo  Установка завершена!
echo ═══════════════════════════════════════════════════════════
echo.
echo Для запуска выполните:
echo   run.bat
echo   или
echo   python main_pyside.py
echo.

endlocal
