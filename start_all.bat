@echo off
REM Genesis Trading System - Запуск всех баз данных и экосистемы
REM Использование: start_all.bat [--databases-only] [--detach]

setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Цвета (ANSI escape codes)
set "BLUE=[94m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "NC=[0m"

REM Флаги
set "DATABASES_ONLY=false"
set "DETACH=true"

REM Парсинг аргументов
:parse_args
if "%~1"=="" goto :end_parse_args
if /i "%~1"=="--databases-only" (
    set "DATABASES_ONLY=true"
    shift
    goto :parse_args
)
if /i "%~1"=="--foreground" (
    set "DETACH=false"
    shift
    goto :parse_args
)
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--help" goto :show_help
shift
goto :parse_args

:end_parse_args

REM Показ заголовка
echo %BLUE%
echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Genesis Trading System - Запуск экосистемы            ║
echo ╚═══════════════════════════════════════════════════════════╝
echo %NC%

REM Проверка Docker
where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo %RED%✗ Docker не установлен%NC%
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

REM Проверка .env файла
if not exist .env (
    echo %YELLOW%⚠ Файл .env не найден. Создаю из .env.example...%NC%
    if exist .env.example (
        copy .env.example .env >nul
        echo %GREEN%✓ .env создан. Отредактируйте файл с вашими настройками%NC%
    ) else (
        echo %YELLOW%⚠ .env.example не найден. Продолжаю без .env...%NC%
    )
)

REM Остановка существующих контейнеров
echo %YELLOW%→ Остановка существующих контейнеров...%NC%
%COMPOSE_CMD% down --remove-orphans >nul 2>&1

REM Запуск баз данных
echo %BLUE%
echo ═══════════════════════════════════════════════════════════
echo   ЗАПУСК БАЗ ДАННЫХ
echo ═══════════════════════════════════════════════════════════
echo %NC%

echo %YELLOW%→ Запуск PostgreSQL, TimescaleDB, QuestDB, Qdrant, Redis...%NC%

if "%DETACH%"=="true" (
    %COMPOSE_CMD% up -d db timescaledb questdb qdrant redis
) else (
    %COMPOSE_CMD% up db timescaledb questdb qdrant redis
)

REM Ожидание готовности БД
echo.
echo %BLUE%→ Проверка готовности баз данных...%NC%
timeout /t 5 /nobreak >nul

echo %YELLOW%  Ожидание PostgreSQL...%NC%
timeout /t 3 /nobreak >nul
echo %GREEN%  ✓%NC%

echo %YELLOW%  Ожидание TimescaleDB...%NC%
timeout /t 3 /nobreak >nul
echo %GREEN%  ✓%NC%

echo %YELLOW%  Ожидание QuestDB...%NC%
timeout /t 3 /nobreak >nul
echo %GREEN%  ✓%NC%

echo %YELLOW%  Ожидание Qdrant...%NC%
timeout /t 3 /nobreak >nul
echo %GREEN%  ✓%NC%

echo %YELLOW%  Ожидание Redis...%NC%
timeout /t 2 /nobreak >nul
echo %GREEN%  ✓%NC%

echo.

REM Если только базы данных - завершаем
if "%DATABASES_ONLY%"=="true" (
    echo %GREEN%✓ Базы данных запущены!%NC%
    echo.
    echo Подключение к базам данных:
    echo   PostgreSQL:   localhost:5432 (trading)
    echo   TimescaleDB:  localhost:5433 (trading_ts)
    echo   QuestDB:      localhost:9000 (questdb)
    echo   Qdrant:       localhost:6333
    echo   Redis:        localhost:6379
    echo.
    exit /b 0
)

REM Запуск основного приложения
echo %BLUE%
echo ═══════════════════════════════════════════════════════════
echo   ЗАПУСК TRADING SYSTEM
echo ═══════════════════════════════════════════════════════════
echo %NC%

echo %YELLOW%→ Запуск trading-system...%NC%

if "%DETACH%"=="true" (
    %COMPOSE_CMD% up -d trading-system
) else (
    %COMPOSE_CMD% up trading-system
)

REM Ожидание готовности приложения
echo.
echo %BLUE%→ Ожидание запуска приложения...%NC%
timeout /t 10 /nobreak >nul

echo.
echo %GREEN%✓ Экосистема Genesis запущена!%NC%
echo.
echo Доступ к сервисам:
echo   Web Dashboard:    http://localhost:8000
echo   Grafana:          http://localhost:3000
echo   Prometheus:       http://localhost:9090
echo   QuestDB Console:  http://localhost:9001
echo.
echo Базы данных:
echo   PostgreSQL:       localhost:5432 (db: trading)
echo   TimescaleDB:      localhost:5433 (db: trading_ts)
echo   QuestDB:          localhost:9000 (db: questdb)
echo   Qdrant:           localhost:6333
echo   Redis:            localhost:6379
echo.
echo Остановка:
echo   stop_all.bat
echo.
echo Логи:
echo   logs.bat
echo.

exit /b 0

:show_help
echo Использование: %~nx0 [OPTIONS]
echo.
echo OPTIONS:
echo   --databases-only  Запустить только базы данных (без trading-system)
echo   --foreground      Запустить в foreground режиме
echo   -h, --help        Показать эту справку
exit /b 0
