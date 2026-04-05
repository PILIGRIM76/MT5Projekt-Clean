@echo off
REM =============================================================================
REM setup_precommit.bat — Установка pre-commit hooks для Genesis Trading System
REM =============================================================================

echo ========================================================================
echo  Установка pre-commit hooks
echo ========================================================================
echo.

REM Проверка наличия Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не найден. Установите Python 3.10+
    exit /b 1
)

echo [1/4] Установка pre-commit...
pip install pre-commit black isort flake8 mypy bandit safety yamllint

echo.
echo [2/4] Установка pre-commit hooks...
pre-commit install

echo.
echo [3/4] Запуск pre-commit для всех файлов...
pre-commit run --all-files

echo.
echo [4/4] Создание .git/hooks/pre-commit symlink...
if exist .git\hooks\pre-commit (
    echo [INFO] Hook уже существует
) else (
    echo [INFO] Hook будет создан автоматически при следующем commit
)

echo.
echo ========================================================================
echo  Установка завершена!
echo ========================================================================
echo.
echo Для ручной проверки используйте:
echo   pre-commit run --all-files
echo.
echo Для отключения hook используйте:
echo   pre-commit uninstall
echo.
pause
