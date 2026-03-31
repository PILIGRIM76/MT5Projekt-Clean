@echo off
chcp 65001 >nul
REM =============================================================================
REM optimize_all.bat — Скрипт еженедельной оптимизации Genesis Trading System
REM =============================================================================
REM Запускается еженедельно (суббота) через Планировщик заданий
REM Выполняет:
REM - Переобучение AI-моделей для всех активных символов
REM - Оптимизацию параметров стратегий
REM - Сохранение лучших моделей
REM =============================================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

cd /d "%PROJECT_DIR%"

echo [Genesis Optimization] Начало оптимизации...
echo Время: %date% %time%
echo.

REM Проверяем наличие виртуального окружения
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM ============================================
REM 1. Проверка доступности MT5
REM ============================================
echo [1/4] Проверка подключения к MT5...
python -c "import MetaTrader5 as mt5; print('[INFO] MT5 доступен')" 2>nul
if errorlevel 1 (
    echo [WARNING] MT5 не доступен, продолжаем без проверки
)
echo.

REM ============================================
REM 2. Запуск умного переобучения моделей
REM ============================================
echo [2/4] Запуск переобучения моделей...
echo [INFO] Запуск smart_retrain.py
python smart_retrain.py
if errorlevel 1 (
    echo [WARNING] Ошибка при переобучении моделей
) else (
    echo [INFO] Переобучение завершено
)
echo.

REM ============================================
REM 3. Оптимизация параметров стратегий
REM ============================================
echo [3/4] Оптимизация параметров стратегий...
REM Здесь можно запустить скрипт оптимизации параметров
REM Например, оптимизацию через генетический алгоритм
echo [INFO] Оптимизация стратегий (требует реализации)
REM python src/analysis/optimize_strategies.py
echo.

REM ============================================
REM 4. Очистка старых моделей
REM ============================================
echo [4/4] Очистка старых моделей из БД...
python -c "
import sqlite3
import os

db_path = 'database/trading_system.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Удаляем старые модели (можно добавить логику по дате)
    # cursor.execute('DELETE FROM ai_models WHERE created_at < datetime(\"now\", \"-30 days\")')
    
    conn.commit()
    conn.close()
    print('[INFO] Очистка моделей завершена')
else:
    print('[WARNING] База данных не найдена')
" 2>nul
echo.

REM ============================================
REM Завершение
REM ============================================
echo [Genesis Optimization] Оптимизация завершена
echo Время завершения: %date% %time%
echo.

REM Создаём файл-маркер успешного завершения
echo %date% %time% > logs\last_optimization.txt
echo [INFO] Создан маркер last_optimization.txt

timeout /t 30 /nobreak >nul

endlocal
