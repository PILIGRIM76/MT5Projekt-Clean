@echo off
chcp 65001 >nul
REM ===================================================================
REM Genesis Trading System - Быстрая настройка GitHub
REM ===================================================================

setlocal enabledelayedexpansion

echo ============================================================
echo   Genesis Trading System - Быстрая настройка GitHub
echo ============================================================
echo.
echo Этот скрипт поможет настроить GitHub репозиторий
echo.

REM === Проверка Git ===
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git не найден!
    echo.
    echo 1. Установите Git: https://git-scm.com/download/win
    echo 2. Запустите этот скрипт снова
    echo.
    pause
    exit /b 1
)

echo [OK] Git найден
echo.

REM === Переход в директорию проекта ===
cd /d "%~dp0"
echo [INFO] Директория проекта: %CD%
echo.

REM === Меню ===
:MENU
echo ============================================================
echo   МЕНЮ
echo ============================================================
echo.
echo 1. Инициализировать Git репозиторий
echo 2. Настроить удалённый репозиторий
echo 3. Загрузить на GitHub
echo 4. Создать тег версии
echo 5. Проверить статус
echo 6. Выход
echo.

set /p CHOICE="Выберите действие (1-6): "

if "%CHOICE%"=="1" goto INIT
if "%CHOICE%"=="2" goto REMOTE
if "%CHOICE%"=="3" goto PUSH
if "%CHOICE%"=="4" goto TAG
if "%CHOICE%"=="5" goto STATUS
if "%CHOICE%"=="6" goto END

echo [ERROR] Неверный выбор
goto MENU

:INIT
echo.
echo ============================================================
echo   Инициализация Git репозитория
echo ============================================================
echo.

if not exist ".git" (
    git init
    echo [OK] Git репозиторий создан
) else (
    echo [OK] Git репозиторий уже существует
)

if not exist ".gitignore" (
    copy /Y ".github\workflows\.gitignore.template" ".gitignore" >nul 2>&1 || (
        echo # Python
        __pycache__/
        *.pyc
        *.pyo
        *.pyd
        build/
        dist/
        *.log
        logs/
        *.db
        database/*.db
        configs/settings.json
        ai_models/
        .venv/
        venv/
        env/
        .idea/
        .vscode/
    ) > ".gitignore"
    echo [OK] .gitignore создан
) else (
    echo [OK] .gitignore уже существует
)

git add .
echo [OK] Файлы добавлены

git log --oneline | findstr /C:"Initial commit" >nul
if errorlevel 1 (
    git commit -m "Initial commit: Genesis Trading System v13.0.0"
    echo [OK] Первый коммит создан
) else (
    echo [OK] Первый коммит уже существует
)

echo.
echo [SUCCESS] Инициализация завершена!
echo.
pause
goto MENU

:REMOTE
echo.
echo ============================================================
echo   Настройка удалённого репозитория
echo ============================================================
echo.

git remote -v | findstr /C:"origin" >nul
if errorlevel 1 (
    echo.
    echo Введите URL вашего репозитория:
    echo Пример: https://github.com/PILIGRIM76/MT5Projekt-Clean.git
    echo.
    set /p REPO_URL="URL: "
    
    if "!REPO_URL!"=="" (
        echo [ERROR] URL не введён
    ) else (
        git remote add origin !REPO_URL!
        echo [OK] Удалённый репозиторий настроен
    )
) else (
    echo [OK] Удалённый репозиторий уже настроен
    git remote -v
)

echo.
pause
goto MENU

:PUSH
echo.
echo ============================================================
echo   Загрузка на GitHub
echo ============================================================
echo.

git remote -v | findstr /C:"origin" >nul
if errorlevel 1 (
    echo [ERROR] Сначала настройте удалённый репозиторий (пункт 2)
    pause
    goto MENU
)

git add .
echo [OK] Файлы добавлены

git commit -m "Update: Genesis Trading System v13.0.0"
if errorlevel 1 (
    echo [INFO] Нет изменений для коммита
)

for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%i

echo [INFO] Отправка в ветку %BRANCH%...
git push origin %BRANCH%
if errorlevel 1 (
    echo [ERROR] Не удалось отправить на GitHub
) else (
    echo [OK] Файлы отправлены на GitHub
)

echo.
echo ============================================================
echo   СЛЕДУЮЩИЕ ШАГИ:
echo ============================================================
echo.
echo 1. Перейдите на GitHub
echo 2. Откройте вкладку Actions
echo 3. Дождитесь завершения сборки
echo 4. Скачайте артефакт
echo.
pause
goto MENU

:TAG
echo.
echo ============================================================
echo   Создание тега версии
echo ============================================================
echo.

set /p VERSION="Введите версию (например, 13.0.0): "
if "!VERSION!"=="" (
    echo [ERROR] Версия не указана
    pause
    goto MENU
)

git tag v!VERSION!
echo [OK] Тег v!VERSION! создан

git push origin v!VERSION!
if errorlevel 1 (
    echo [ERROR] Не удалось отправить тег
) else (
    echo [OK] Тег отправлен на GitHub
    echo.
    echo GitHub Actions автоматически создаст Release!
)

echo.
pause
goto MENU

:STATUS
echo.
echo ============================================================
echo   Статус репозитория
echo ============================================================
echo.

git status
echo.

git remote -v
echo.

git log --oneline -5
echo.

pause
goto MENU

:END
echo.
echo ============================================================
echo   Настройка завершена!
echo ============================================================
echo.
echo Удачи! 🚀
echo.
timeout /t 2 >nul
exit /b 0
