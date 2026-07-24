@echo off
echo ========================================
echo   Genesis Trading System - Быстрый запуск
echo ========================================
echo.

REM Переходим в директорию скрипта
cd /d "%~dp0"

REM Проверяем Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не найден!
    echo Установите Python 3.10+ и добавьте в PATH
    pause
    exit /b 1
)

echo Запуск системы...
echo.

REM Запускаем основное приложение
python main_pyside.py

if errorlevel 1 (
    echo.
    echo Ошибка запуска (код: %errorlevel%)
    echo.
    echo Возможные решения:
    echo 1. Установите зависимости: pip install -r requirements.txt
    echo 2. Проверьте конфигурацию в configs/settings.json
    echo 3. Для MT5: проверьте логин/пароль и путь к терминалу
    pause
    exit /b %errorlevel%
)

echo.
echo Система завершена.
pause