# 🚀 Запуск Genesis Trading System с MT5
# Этот скрипт автоматически запускает MT5 терминал перед запуском Genesis

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Genesis Trading System - Запуск с MT5" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Шаг 1: Проверка конфигурации
Write-Host "[1/4] Проверка конфигурации..." -ForegroundColor Yellow
$configPath = "F:\MT5Qoder\MT5Projekt-Clean\configs\settings.json"

if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $mt5Path = $config.MT5_PATH
    Write-Host "  ✓ Конфигурация найдена" -ForegroundColor Green
    Write-Host "  Путь к MT5: $mt5Path" -ForegroundColor Gray
} else {
    Write-Host "  ✗ ОШИБКА: Файл конфигурации не найден!" -ForegroundColor Red
    Write-Host "  Проверьте наличие: $configPath" -ForegroundColor Gray
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# Шаг 2: Проверка наличия MT5
Write-Host ""
Write-Host "[2/4] Проверка MetaTrader 5..." -ForegroundColor Yellow

if (-not (Test-Path $mt5Path)) {
    Write-Host "  ✗ ОШИБКА: MT5 терминал не найден по пути: $mt5Path" -ForegroundColor Red
    Write-Host "  Проверьте правильность пути в configs/settings.json" -ForegroundColor Gray
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

Write-Host "  ✓ MT5 терминал найден" -ForegroundColor Green

# Шаг 3: Проверка запущен ли MT5
Write-Host ""
Write-Host "[3/4] Проверка статуса MT5..." -ForegroundColor Yellow

$mt5Process = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue

if ($mt5Process) {
    Write-Host "  ✓ MT5 уже запущен (PID: $($mt5Process.Id))" -ForegroundColor Green
} else {
    Write-Host "  ℹ MT5 не запущен. Запуск..." -ForegroundColor Cyan

    try {
        Start-Process -FilePath $mt5Path -WindowStyle Normal
        Write-Host "  ✓ MT5 запущен" -ForegroundColor Green

        # Ждем пока MT5 полностью загрузится (до 30 секунд)
        Write-Host "  ⏳ Ожидание загрузки MT5..." -ForegroundColor Gray
        $maxWait = 30
        $waited = 0
        $interval = 2

        while ($waited -lt $maxWait) {
            $mt5Process = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
            if ($mt5Process) {
                # Проверяем что терминал полностью загрузился
                Start-Sleep -Seconds 5
                Write-Host "  ✓ MT5 готов к работе" -ForegroundColor Green
                break
            }
            Start-Sleep -Seconds $interval
            $waited += $interval
            Write-Host "  ... ожидание ($waited сек)" -ForegroundColor Gray
        }

        if (-not $mt5Process) {
            Write-Host "  ✗ ОШИБКА: Не удалось запустить MT5 за $maxWait секунд" -ForegroundColor Red
            Read-Host "Нажмите Enter для выхода"
            exit 1
        }
    }
    catch {
        Write-Host "  ✗ ОШИБКА при запуске MT5: $_" -ForegroundColor Red
        Read-Host "Нажмите Enter для выхода"
        exit 1
    }
}

# Шаг 4: Запуск Genesis Trading System
Write-Host ""
Write-Host "[4/4] Запуск Genesis Trading System..." -ForegroundColor Yellow

$genesisPath = "F:\MT5Qoder\MT5Projekt-Clean\venv311\Scripts\python.exe"
$genesisScript = "F:\MT5Qoder\MT5Projekt-Clean\main_pyside.py"
$genesisDir = "F:\MT5Qoder\MT5Projekt-Clean"

if (-not (Test-Path $genesisPath)) {
    Write-Host "  ✗ ОШИБКА: Python не найден по пути: $genesisPath" -ForegroundColor Red
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

if (-not (Test-Path $genesisScript)) {
    Write-Host "  ✗ ОШИБКА: main_pyside.py не найден" -ForegroundColor Red
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

try {
    Write-Host "  ✓ Запуск GUI..." -ForegroundColor Green
    Start-Process -FilePath $genesisPath -ArgumentList $genesisScript -WorkingDirectory $genesisDir -WindowStyle Normal
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host "  Genesis Trading System успешно запущен!" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "MT5 терминал работает в фоне." -ForegroundColor Cyan
    Write-Host "Для остановки обоих приложений:" -ForegroundColor Cyan
    Write-Host "  1. Закройте Genesis Trading System" -ForegroundColor Cyan
    Write-Host "  2. Закройте MT5 терминал вручную" -ForegroundColor Cyan
    Write-Host ""
}
catch {
    Write-Host "  ✗ ОШИБКА при запуске Genesis: $_" -ForegroundColor Red
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

Write-Host "Готово! Нажмите Enter для завершения скрипта..." -ForegroundColor Gray
Read-Host
