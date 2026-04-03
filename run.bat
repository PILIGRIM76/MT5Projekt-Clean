@echo off
REM Genesis Trading System - Запуск с проверкой зависимостей
REM Использование: run.bat

setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Genesis Trading System - Запуск                       ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

REM Активация venv
if exist venv\Scripts\activate.bat (
    echo Активация виртуального окружения...
    call venv\Scripts\activate.bat
) else (
    echo Ошибка: venv не найдено!
    echo Выполните: setup.bat
    exit /b 1
)

REM Проверка основных зависимостей
echo.
echo Проверка зависимостей...

python -c "import PySide6" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo Ошибка: PySide6 не установлен!
    echo Установка базовых зависимостей...
    pip install PySide6 pyqtgraph pydantic python-dotenv numpy pandas matplotlib MetaTrader5
)

python -c "import src" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo Ошибка: проект не найден!
    exit /b 1
)

echo.
echo ✓ Зависимости установлены
echo.
echo ═══════════════════════════════════════════════════════════
echo  Запуск приложения...
echo ═══════════════════════════════════════════════════════════
echo.

REM Запуск приложения
python main_pyside.py

if %errorlevel% neq 0 (
    echo.
    echo Ошибка запуска (код: %errorlevel%)
    echo.
    echo Для установки всех зависимостей выполните:
    echo   pip install -r requirements.txt
    exit /b %errorlevel%
)

endlocal
