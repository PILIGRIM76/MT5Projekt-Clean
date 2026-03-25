@echo off
chcp 65001 >nul
REM ===================================================================
REM Genesis Trading System - Скрипт инициализации Git репозитория
REM ===================================================================

setlocal enabledelayedexpansion

echo ============================================================
echo   Genesis Trading System - Инициализация Git
echo ============================================================
echo.

REM === Проверка Git ===
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git не найден!
    echo.
    echo Установите Git: https://git-scm.com/download/win
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

REM === Инициализация Git ===
if not exist ".git" (
    echo [1/5] Инициализация Git репозитория...
    git init
    echo [OK] Git репозиторий создан
) else (
    echo [OK] Git репозиторий уже существует
)
echo.

REM === Создание .gitignore ===
if not exist ".gitignore" (
    echo [2/5] Создание .gitignore...
    copy /Y ".github\workflows\.gitignore.template" ".gitignore" >nul 2>&1 || (
        echo # Python
        *.pyc
        __pycache__/
        *.pyo
        *.pyd
        .Python
        *.so
        build/
        dist/
        *.egg-info/
        .eggs/
        
        # Виртуальное окружение
        venv/
        env/
        .venv/
        
        # IDE
        .idea/
        .vscode/
        *.iml
        *.swp
        *.swo
        
        # Логи и базы данных
        *.log
        logs/
        *.db
        *.db-journal
        database/*.db
        ai_models/
        
        # Конфигурации пользователя
        configs/settings.json
        configs/*.local.json
        .env
        
        # Временные файлы
        *.tmp
        *.bak
        Thumbs.db
        desktop.ini
        
        # Сборка
        GenesisTrading_Build/stubs/
        GenesisTrading_Build/build/
        
        # macOS
        .DS_Store
        .AppleDouble
        .LSOverride
        
        # Windows
        $RECYCLE.BIN/
        System Volume Information/
    )
    echo [OK] .gitignore создан
) else (
    echo [OK] .gitignore уже существует
)
echo.

REM === Добавление файлов ===
echo [3/5] Добавление файлов...
git add .
git status --short | findstr /C:"A " >nul
if errorlevel 1 (
    echo [WARN] Нет новых файлов для добавления
) else (
    echo [OK] Файлы добавлены
)
echo.

REM === Первый коммит ===
echo [4/5] Создание первого коммита...
git log --oneline | findstr /C:"Initial commit" >nul
if errorlevel 1 (
    git commit -m "Initial commit: Genesis Trading System v13.0.0"
    echo [OK] Первый коммит создан
) else (
    echo [OK] Первый коммит уже существует
)
echo.

REM === Проверка удалённого репозитория ===
echo [5/5] Проверка удалённого репозитория...
git remote -v | findstr /C:"origin" >nul
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   СЛЕДУЮЩИЕ ШАГИ:
    echo ============================================================
    echo.
    echo 1. Создайте репозиторий на GitHub:
    echo    https://github.com/new
    echo.
    echo 2. Введите имя репозитория: MT5Projekt-Clean
    echo.
    echo 3. Выполните команду:
    echo    git remote add origin https://github.com/ВАШ_НИК/MT5Projekt-Clean.git
    echo    git push -u origin main
    echo.
    echo ============================================================
) else (
    echo [OK] Удалённый репозиторий настроен
    echo.
    echo Для обновления выполните:
    echo   git push origin main
)
echo.

echo ============================================================
echo   ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА
echo ============================================================
echo.

pause
