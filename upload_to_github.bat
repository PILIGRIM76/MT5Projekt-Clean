@echo off
chcp 65001 >nul
REM ===================================================================
REM Genesis Trading System - Загрузка на GitHub
REM ===================================================================

setlocal enabledelayedexpansion

echo ============================================================
echo   Genesis Trading System - Загрузка на GitHub
echo ============================================================
echo.

REM === Проверка Git ===
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git не найден!
    echo.
    echo Установите Git: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo [OK] Git найден
echo.

REM === Переход в директорию проекта ===
cd /d "%~dp0"
echo [INFO] Директория проекта: %CD%
echo.

REM === Проверка удалённого репозитория ===
git remote -v | findstr /C:"origin" >nul
if errorlevel 1 (
    echo.
    echo [ERROR] Удалённый репозиторий не настроен!
    echo.
    echo Сначала выполните:
    echo   git remote add origin https://github.com/ВАШ_НИК/MT5Projekt-Clean.git
    echo.
    pause
    exit /b 1
)

echo [OK] Удалённый репозиторий настроен
echo.

REM === Получение имени пользователя ===
for /f "tokens=*" %%i in ('git config user.name') do set USERNAME=%%i
echo [INFO] Пользователь: %USERNAME%
echo.

REM === Добавление файлов ===
echo [1/4] Добавление файлов...
git add .
echo [OK] Файлы добавлены
echo.

REM === Коммит ===
echo [2/4] Создание коммита...
git commit -m "Update: Genesis Trading System v13.0.0"
if errorlevel 1 (
    echo [INFO] Нет изменений для коммита
)
echo.

REM === Получение текущей ветки ===
for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%i
echo [INFO] Ветка: %BRANCH%
echo.

REM === Push ===
echo [3/4] Отправка на GitHub...
git push origin %BRANCH%
if errorlevel 1 (
    echo.
    echo [ERROR] Не удалось отправить на GitHub!
    echo.
    echo Возможные причины:
    echo   - Нет доступа к репозиторию
    echo   - Изменился удалённый репозиторий
    echo   - Проблемы с сетью
    echo.
    pause
    exit /b 1
)
echo [OK] Файлы отправлены
echo.

REM === Создание тега ===
echo.
echo [4/4] Создание тега версии...
set /p VERSION="Введите версию (например, 13.0.0): "
if "!VERSION!"=="" (
    echo [WARN] Версия не указана, пропускаем тег
) else (
    git tag v!VERSION!
    git push origin v!VERSION!
    echo [OK] Тег v!VERSION! создан
)
echo.

echo ============================================================
echo   ЗАГРУЗКА ЗАВЕРШЕНА
echo ============================================================
echo.
echo Репозиторий: https://github.com/ВАШ_НИК/MT5Projekt-Clean
echo.
echo Следующие шаги:
echo   1. Перейдите на GitHub
echo   2. Проверьте вкладку Actions
echo   3. Дождитесь завершения сборки
echo   4. Скачайте артефакт
echo.
echo ============================================================

pause
