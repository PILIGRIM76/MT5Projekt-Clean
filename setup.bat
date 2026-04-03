@echo off
REM Genesis Trading System - Быстрая настройка
REM Использование: setup.bat

setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Genesis Trading System - Настройка                    ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

REM Шаг 1: Создание .env
if not exist .env (
    echo [1/4] Создание файла .env...
    copy .env.example .env
    echo ✓ .env создан
    echo   Откройте .env и заполните вашими данными!
) else (
    echo [1/4] .env уже существует
)

REM Шаг 2: Создание venv
if not exist venv (
    echo.
    echo [2/4] Создание виртуального окружения...
    python -m venv venv
    echo ✓ Виртуальное окружение создано
) else (
    echo.
    echo [2/4] Виртуальное окружение уже существует
)

REM Шаг 3: Активация venv
echo.
echo [3/4] Активация виртуального окружения...
call venv\Scripts\activate.bat
echo ✓ Виртуальное окружение активировано

REM Шаг 4: Установка зависимостей
echo.
echo [4/4] Установка зависимостей...
pip install --upgrade pip
pip install -r requirements.txt
echo ✓ Зависимости установлены

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Настройка завершена!                                  ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.
echo Следующие шаги:
echo   1. Откройте и отредактируйте .env файл
echo   2. Перезагрузите VS Code (Ctrl+Shift+P → Developer: Reload Window)
echo   3. Запустите: start_ecosystem.bat
echo.
echo Для запуска экосистемы выполните:
echo   start_ecosystem.bat
echo.

endlocal
