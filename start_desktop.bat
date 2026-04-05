@echo off
REM Genesis Trading System - Запуск десктопного приложения PySide6
REM Использование: start_desktop.bat

setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Цвета
set "BLUE=[94m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "NC=[0m"

echo %BLUE%
echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Genesis Trading System - Десктопное приложение        ║
echo ╚═══════════════════════════════════════════════════════════╝
echo %NC%

REM Проверка Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo %RED%✗ Python не установлен или не в PATH%NC%
    exit /b 1
)

REM Проверка .env файла
if not exist .env (
    echo %YELLOW%⚠ Файл .env не найден. Создаю из .env.example...%NC%
    if exist .env.example (
        copy .env.example .env >nul
        echo %GREEN%✓ .env создан%NC%
    ) else (
        echo %YELLOW%⚠ .env.example не найден%NC%
    )
)

REM Проверка виртуального окружения
if exist venv\Scripts\activate.bat (
    echo %YELLOW%→ Активация виртуального окружения...%NC%
    call venv\Scripts\activate.bat
)

REM Установка зависимостей (если нужно)
echo %YELLOW%→ Проверка зависимостей...%NC%
pip install -q -r requirements.txt 2>nul

REM Запуск приложения
echo %GREEN%→ Запуск PySide6 приложения...%NC%
echo.
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo  Приложение запущено в отдельном окне!
echo  Базы данных должны быть запущены через: start_all.bat
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo.

python main_pyside.py

if %errorlevel% neq 0 (
    echo.
    echo %RED%✗ Ошибка запуска приложения%NC%
    exit /b %errorlevel%
)

echo.
echo %GREEN%✓ Приложение остановлено%NC%
echo.

endlocal
