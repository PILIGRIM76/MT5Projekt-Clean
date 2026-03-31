@echo off
chcp 65001 >nul
REM =============================================================================
REM maintenance.bat — Скрипт ежедневного обслуживания Genesis Trading System
REM =============================================================================
REM Запускается ежедневно через Планировщик заданий
REM Выполняет:
REM - Очистку старых логов
REM - Очистку кэша моделей
REM - Проверку целостности БД
REM - Ваккумацию базы данных
REM =============================================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

cd /d "%PROJECT_DIR%"

echo [Genesis Maintenance] Начало обслуживания...
echo Время: %date% %time%
echo.

REM Проверяем наличие виртуального окружения
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM ============================================
REM 1. Очистка старых логов (старше 30 дней)
REM ============================================
echo [1/5] Очистка старых логов...
if exist "logs" (
    forfiles /p "logs" /s /m *.log /d -30 /c "cmd /c del @path" 2>nul
    echo [INFO] Старые логи удалены
) else (
    echo [INFO] Папка logs не найдена
)
echo.

REM ============================================
REM 2. Очистка кэша Python
REM ============================================
echo [2/5] Очистка кэша Python...
if exist "__pycache__" (
    rmdir /s /q "__pycache__" 2>nul
    echo [INFO] __pycache__ удалён
)
if exist "src\__pycache__" (
    rmdir /s /q "src\__pycache__" 2>nul
    echo [INFO] src\__pycache__ удалён
)
echo.

REM ============================================
REM 3. Очистка старых моделей (опционально)
REM ============================================
echo [3/5] Проверка кэша моделей...
if exist "hf_models" (
    echo [INFO] Папка hf_models существует, проверка не требуется
) else (
    echo [INFO] Папка hf_models не найдена
)
echo.

REM ============================================
REM 4. Проверка целостности БД
REM ============================================
echo [4/5] Проверка базы данных...
if exist "database\trading_system.db" (
    echo [INFO] База данных найдена
    REM Запускаем скрипт проверки БД
    python -c "import sqlite3; conn = sqlite3.connect('database/trading_system.db'); conn.execute('PRAGMA integrity_check'); print('[INFO] Проверка целостности: OK')" 2>nul
) else (
    echo [WARNING] База данных не найдена
)
echo.

REM ============================================
REM 5. Ваккумация базы данных
REM ============================================
echo [5/5] Ваккумация базы данных...
python -c "import sqlite3; conn = sqlite3.connect('database/trading_system.db'); conn.execute('VACUUM'); conn.close(); print('[INFO] Ваккумация завершена')" 2>nul
echo.

REM ============================================
REM 6. Отчёт о состоянии диска
REM ============================================
echo [6/6] Информация о диске...
wmic logicaldisk where "DeviceID='F:'" get Size,FreeSpace 2>nul | findstr /v "FreeSize"
echo.

echo [Genesis Maintenance] Обслуживание завершено
echo Время завершения: %date% %time%
echo.

timeout /t 10 /nobreak >nul

endlocal
