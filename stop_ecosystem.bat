@echo off
REM Genesis Trading System - Остановка всей экосистемы
REM Использование: stop_ecosystem.bat [--volumes]

setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Цвета
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "NC=[0m"

REM Флаг для удаления volumes
set "REMOVE_VOLUMES=false"

REM Парсинг аргументов
:parse_args
if "%~1"=="" goto :end_parse_args
if /i "%~1"=="--volumes" (
    set "REMOVE_VOLUMES=true"
    shift
    goto :parse_args
)
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--help" goto :show_help
shift
goto :parse_args

:end_parse_args

echo %BLUE%
echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Genesis Trading System - Остановка экосистемы         ║
echo ╚═══════════════════════════════════════════════════════════╝
echo %NC%

REM Проверка Docker Compose
where docker-compose >nul 2>nul
if %errorlevel% neq 0 (
    docker compose version >nul 2>nul
    if %errorlevel% neq 0 (
        echo %RED%✗ Docker Compose не доступен%NC%
        exit /b 1
    )
    set "COMPOSE_CMD=docker compose"
) else (
    set "COMPOSE_CMD=docker-compose"
)

if "%REMOVE_VOLUMES%"=="true" (
    echo %RED%⚠ ВНИМАНИЕ: Все данные баз данных будут удалены!%NC%
    set /p response="Продолжить? (y/N): "
    if /i not "!response!"=="y" (
        echo Отменено
        exit /b 0
    )

    echo %YELLOW%→ Остановка и удаление контейнеров и volumes...%NC%
    %COMPOSE_CMD% down --volumes --remove-orphans
) else (
    echo %YELLOW%→ Остановка контейнеров с базами данных...%NC%
    %COMPOSE_CMD% down --remove-orphans
)

echo.
echo %GREEN%✓ Экосистема остановлена%NC%
echo.

if "%REMOVE_VOLUMES%"=="true" (
    echo %RED%⚠ Все данные баз данных удалены!%NC%
) else (
    echo Данные сохранены в volumes. Для полного удаления используйте:
    echo   %~nx0 --volumes
)
echo.

exit /b 0

:show_help
echo Использование: %~nx0 [OPTIONS]
echo.
echo OPTIONS:
echo   --volumes    Удалить все volumes (данные будут потеряны!)
echo   -h, --help   Показать эту справку
exit /b 0
