@echo off
chcp 65001 >nul
echo ================================================================================
echo МОНИТОРИНГ ОБУЧЕНИЯ МОДЕЛЕЙ
echo ================================================================================
echo.
echo Выберите режим:
echo 1 - Показать общую статистику
echo 2 - Показать последние сессии обучения
echo 3 - Мониторинг в реальном времени (5 минут)
echo 4 - Всё вместе
echo.
set /p choice="Ваш выбор (1-4): "

if "%choice%"=="1" (
    python monitor_training.py --stats
) else if "%choice%"=="2" (
    python monitor_training.py --recent
) else if "%choice%"=="3" (
    python monitor_training.py --monitor --duration 300
) else if "%choice%"=="4" (
    python monitor_training.py
) else (
    echo Неверный выбор!
)

echo.
pause
