@echo off
chcp 65001 >nul
REM ===================================================================
REM Genesis Trading System - Полностью автоматическая загрузка на GitHub
REM Использует GitHub CLI (gh)
REM ===================================================================

setlocal enabledelayedexpansion

echo ============================================================
echo   Genesis Trading System - Автоматическая загрузка на GitHub
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

REM === Проверка GitHub CLI ===
gh --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] GitHub CLI (gh) не найден!
    echo.
    echo Для автоматической загрузки установите:
    echo   https://cli.github.com/
    echo.
    echo Или загрузите вручную через браузер.
    echo.
    goto MANUAL
)

echo [OK] GitHub CLI найден
echo.

REM === Переход в директорию проекта ===
cd /d "%~dp0"
echo [INFO] Директория проекта: %CD%
echo.

REM === Проверка авторизации ===
echo [1/6] Проверка авторизации на GitHub...
gh auth status >nul 2>&1
if errorlevel 1 (
    echo.
    echo [INFO] Требуется авторизация...
    echo.
    gh auth login
    if errorlevel 1 (
        echo [ERROR] Авторизация не удалась!
        goto MANUAL
    )
)

echo [OK] Авторизация успешна
echo.

REM === Проверка существования репозитория ===
echo [2/6] Проверка репозитория...
gh repo view PILIGRIM76/MT5Projekt-Clean >nul 2>&1
if errorlevel 1 (
    echo [INFO] Репозиторий не найден, создаю...
    echo.
    gh repo create MT5Projekt-Clean --public --source=. --remote=origin --push
    if errorlevel 1 (
        echo [ERROR] Не удалось создать репозиторий!
        goto MANUAL
    )
) else (
    echo [OK] Репозиторий существует
)

echo.

REM === Добавление файлов ===
echo [3/6] Добавление файлов...
git add .
echo [OK] Файлы добавлены
echo.

REM === Коммит ===
echo [4/6] Создание коммита...
git commit -m "Genesis Trading System v13.0.0 - Автоматическая загрузка"
if errorlevel 1 (
    echo [INFO] Нет изменений для коммита
)
echo.

REM === Установка главной ветки ===
echo [5/6] Настройка ветки...
git branch -M main
git push -u origin main
if errorlevel 1 (
    echo [ERROR] Не удалось отправить на GitHub!
    goto MANUAL
)
echo [OK] Файлы загружены
echo.

REM === Создание тега ===
echo [6/6] Создание тега версии...
git tag v13.0.0
git push origin v13.0.0
if errorlevel 1 (
    echo [WARN] Не удалось отправить тег
) else (
    echo [OK] Тег v13.0.0 создан
)
echo.

echo ============================================================
echo   ЗАГРУЗКА ЗАВЕРШЕНА!
echo ============================================================
echo.
echo Репозиторий: https://github.com/PILIGRIM76/MT5Projekt-Clean
echo.
echo Следующие шаги:
echo   1. Перейдите на вкладку Actions
echo   2. Дождитесь завершения сборки ^(30-50 минут^)
echo   3. Скачайте артефакт из раздела Artifacts
echo.
echo ============================================================

pause
exit /b 0

:MANUAL
echo.
echo ============================================================
echo   РУЧНАЯ ЗАГРУЗКА
echo ============================================================
echo.
echo 1. Перейдите: https://github.com/new
echo.
echo 2. Создайте репозиторий:
echo    - Имя: MT5Projekt-Clean
echo    - Visibility: Public
echo    - НЕ ставьте галочку "Initialize with README"
echo.
echo 3. Выполните команды:
echo    git remote add origin https://github.com/PILIGRIM76/MT5Projekt-Clean.git
echo    git branch -M main
echo    git push -u origin main
echo    git tag v13.0.0
echo    git push origin v13.0.0
echo.
echo ============================================================

pause
exit /b 0
