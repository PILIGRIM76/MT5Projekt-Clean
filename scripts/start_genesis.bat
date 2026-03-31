@echo off
chcp 65001 >nul
REM =============================================================================
REM start_genesis.bat — Скрипт автозапуска Genesis Trading System
REM =============================================================================
REM Запускается при загрузке Windows через Планировщик заданий
REM =============================================================================

setlocal enabledelayedexpansion

REM Получаем директорию скрипта
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

REM Переходим в директорию проекта
cd /d "%PROJECT_DIR%"

echo [Genesis Trader] Запуск системы...
echo Время: %date% %time%
echo.

REM Проверяем наличие виртуального окружения
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Активация виртуального окружения...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Активация виртуального окружения (.venv)...
    call .venv\Scripts\activate.bat
) else (
    echo [WARNING] Виртуальное окружение не найдено, используем системный Python
)

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не найден в системе!
    pause
    exit /b 1
)

echo [INFO] Версия Python:
python --version
echo.

REM Запускаем основную программу
echo [INFO] Запуск main_pyside.py...
echo.

REM Логирование вывода
set "LOG_FILE=%PROJECT_DIR%\logs\autostart_%date:~-4,4%%date:~-7,2%%date:~-10,2%_%time:~0,2%%time:~3,2%.log"
set "LOG_FILE=%LOG_FILE: =0%"

python main_pyside.py > "%LOG_FILE%" 2>&1

if errorlevel 1 (
    echo [ERROR] Ошибка при запуске! Код ошибки: %errorlevel%
    echo [ERROR] Проверьте лог: %LOG_FILE%
) else (
    echo [INFO] Система успешно запущена
)

echo.
echo [Genesis Trader] Завершение скрипта
timeout /t 5 /nobreak >nul

endlocal
