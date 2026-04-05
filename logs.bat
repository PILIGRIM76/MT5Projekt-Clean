@echo off
REM Genesis Trading System - Просмотр логов
REM Использование: logs.bat [service] [--follow]

setlocal enabledelayedexpansion

cd /d "%~dp0"

set "SERVICE="
set "FOLLOW="

REM Парсинг аргументов
:parse_args
if "%~1"=="" goto :end_parse_args
if /i "%~1"=="-f" (
    set "FOLLOW=-f"
    shift
    goto :parse_args
)
if /i "%~1"=="--follow" (
    set "FOLLOW=-f"
    shift
    goto :parse_args
)
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--help" goto :show_help
set "SERVICE=%~1"
shift
goto :parse_args

:end_parse_args

REM Проверка Docker Compose
where docker-compose >nul 2>nul
if %errorlevel% neq 0 (
    docker compose version >nul 2>nul
    if %errorlevel% neq 0 (
        echo Docker Compose не доступен
        exit /b 1
    )
    set "COMPOSE_CMD=docker compose"
) else (
    set "COMPOSE_CMD=docker-compose"
)

if defined FOLLOW (
    if defined SERVICE (
        echo Логи сервиса '%SERVICE%' (режим реального времени)...
        %COMPOSE_CMD% logs %FOLLOW% %SERVICE%
    ) else (
        echo Логи всех сервисов (режим реального времени)...
        %COMPOSE_CMD% logs %FOLLOW%
    )
) else (
    if defined SERVICE (
        echo Логи сервиса '%SERVICE%'...
        %COMPOSE_CMD% logs %SERVICE%
    ) else (
        echo Логи всех сервисов...
        %COMPOSE_CMD% logs
    )
)

exit /b 0

:show_help
echo Использование: %~nx0 [SERVICE] [OPTIONS]
echo.
echo SERVICE: db, timescaledb, questdb, qdrant, redis,
echo          trading-system, prometheus, grafana, nginx
echo.
echo OPTIONS:
echo   -f, --follow    Режим реального времени (tail -f)
echo   -h, --help      Показать эту справку
echo.
echo Примеры:
echo   %~nx0 trading-system        Логи trading-system
echo   %~nx0 db                    Логи PostgreSQL
echo   %~nx0 -f                    Все логи в реальном времени
echo   %~nx0 db -f                 Логи PostgreSQL в реальном времени
exit /b 0
