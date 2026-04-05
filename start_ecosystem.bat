@echo off
REM Genesis Trading System - Запуск всей экосистемы (БД + Desktop приложение)
REM Использование: start_ecosystem.bat

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
echo ║     Genesis Trading System - Запуск экосистемы            ║
echo ║     (Базы данных + Десктопное приложение PySide6)         ║
echo ╚═══════════════════════════════════════════════════════════╝
echo %NC%

REM Проверка Docker
where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo %RED%✗ Docker не установлен%NC%
    echo %YELLOW%Установите Docker Desktop: https://www.docker.com/products/docker-desktop%NC%
    exit /b 1
)

REM Проверка Docker Compose
where docker-compose >nul 2>nul
if %errorlevel% neq 0 (
    docker compose version >nul 2>nul
    if %errorlevel% neq 0 (
        echo %RED%✗ Docker Compose не установлен%NC%
        exit /b 1
    )
    set "COMPOSE_CMD=docker compose"
) else (
    set "COMPOSE_CMD=docker-compose"
)

REM Проверка Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo %RED%✗ Python не установлен%NC%
    exit /b 1
)

REM Проверка .env файла
if not exist .env (
    echo %YELLOW%⚠ Файл .env не найден. Создаю из .env.example...%NC%
    if exist .env.example (
        copy .env.example .env >nul
        echo %GREEN%✓ .env создан. Отредактируйте с вашими настройками%NC%
    )
)

REM Шаг 1: Запуск баз данных
echo.
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo  ШАГ 1: Запуск баз данных (PostgreSQL, TimescaleDB, Qdrant...)
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo.

echo %YELLOW%→ Запуск контейнеров с базами данных...%NC%
%COMPOSE_CMD% up -d db timescaledb questdb qdrant redis

echo.
echo %YELLOW%→ Ожидание готовности баз данных...%NC%
timeout /t 10 /nobreak >nul

REM Проверка готовности PostgreSQL
echo %YELLOW%→ Проверка PostgreSQL...%NC%
%COMPOSE_CMD% exec db pg_isready -U trading_user >nul 2>&1
if %errorlevel% equ 0 (
    echo %GREEN%  ✓ PostgreSQL готов%NC%
) else (
    echo %RED%  ✗ PostgreSQL не готов%NC%
)

REM Проверка готовности TimescaleDB
echo %YELLOW%→ Проверка TimescaleDB...%NC%
%COMPOSE_CMD% exec timescaledb pg_isready -U trading_user >nul 2>&1
if %errorlevel% equ 0 (
    echo %GREEN%  ✓ TimescaleDB готов%NC%
) else (
    echo %RED%  ✗ TimescaleDB не готов%NC%
)

REM Проверка готовности Redis
echo %YELLOW%→ Проверка Redis...%NC%
%COMPOSE_CMD% exec redis redis-cli ping >nul 2>&1
if %errorlevel% equ 0 (
    echo %GREEN%  ✓ Redis готов%NC%
) else (
    echo %RED%  ✗ Redis не готов%NC%
)

echo.
echo %GREEN%✓ Базы данных запущены и готовы к работе%NC%
echo.

REM Шаг 2: Запуск десктопного приложения
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo  ШАГ 2: Запуск десктопного приложения PySide6
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo.

REM Проверка виртуального окружения
if exist venv\Scripts\activate.bat (
    echo %YELLOW%→ Активация виртуального окружения...%NC%
    call venv\Scripts\activate.bat
)

REM Установка зависимостей
echo %YELLOW%→ Проверка зависимостей...%NC%
pip install -q -r requirements.txt 2>nul

REM Запуск приложения
echo %GREEN%→ Запуск PySide6 приложения...%NC%
echo.
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo  Приложение будет запущено в отдельном окне!
echo  Подключение к базам данных:
echo    PostgreSQL:   localhost:5432
echo    TimescaleDB:  localhost:5433
echo    Qdrant:       localhost:6333
echo    Redis:        localhost:6379
echo %BLUE%═══════════════════════════════════════════════════════════%NC%
echo.

python main_pyside.py

if %errorlevel% neq 0 (
    echo.
    echo %RED%✗ Ошибка запуска приложения (код: %errorlevel%)%NC%
    echo.
    echo %YELLOW%Для остановки баз данных выполните: stop_ecosystem.bat%NC%
    exit /b %errorlevel%
)

echo.
echo %GREEN%✓ Приложение остановлено%NC%
echo.

endlocal
