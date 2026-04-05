@echo off
REM Genesis Trading System - Проверка статуса
REM Использование: status.bat

setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Цвета
set "BLUE=[94m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "CYAN=[96m"
set "NC=[0m"

echo %BLUE%
echo ╔═══════════════════════════════════════════════════════════╗
echo ║     Genesis Trading System - Статус экосистемы            ║
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

echo %CYAN%КОНТЕЙНЕРЫ:%NC%
echo.

REM Проверка каждого сервиса
for %%s in (db timescaledb questdb qdrant redis trading-system prometheus grafana) do (
    %COMPOSE_CMD% ps --format json %%s >nul 2>nul
    if %errorlevel% equ 0 (
        echo %GREEN%  ● %%s%NC%
    ) else (
        echo %RED%  ○ %%s%NC%
    )
)

echo.
echo %CYAN%БАЗЫ ДАННЫХ:%NC%
echo.

REM Проверка PostgreSQL
echo   PostgreSQL (localhost:5432):
%COMPOSE_CMD% ps db >nul 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%     ● RUNNING%NC%
) else (
    echo %RED%     ○ NOT AVAILABLE%NC%
)

REM Проверка TimescaleDB
echo   TimescaleDB (localhost:5433):
%COMPOSE_CMD% ps timescaledb >nul 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%     ● RUNNING%NC%
) else (
    echo %RED%     ○ NOT AVAILABLE%NC%
)

REM Проверка QuestDB
echo   QuestDB (localhost:9000):
%COMPOSE_CMD% ps questdb >nul 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%     ● RUNNING%NC%
) else (
    echo %RED%     ○ NOT AVAILABLE%NC%
)

REM Проверка Qdrant
echo   Qdrant (localhost:6333):
%COMPOSE_CMD% ps qdrant >nul 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%     ● RUNNING%NC%
) else (
    echo %RED%     ○ NOT AVAILABLE%NC%
)

REM Проверка Redis
echo   Redis (localhost:6379):
%COMPOSE_CMD% ps redis >nul 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%     ● RUNNING%NC%
) else (
    echo %RED%     ○ NOT AVAILABLE%NC%
)

echo.
echo ═══════════════════════════════════════════════════════════
echo.
echo Управление:
echo   Запуск:     start_all.bat
echo   Остановка:  stop_all.bat
echo   Логи:       logs.bat [service]
echo   Статус:     status.bat
echo.
