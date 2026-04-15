# migrate_to_python311.ps1
<#
.SYNOPSIS
    Миграция Genesis Trading System на Python 3.11
.DESCRIPTION
    Автоматическая миграия с Python 3.14 на Python 3.11
    для совместимости с научными пакетами (torch, scipy, sklearn)
.NOTES
    Запускать из корня проекта: .\scripts\migrate_to_python311.ps1
#>

Set-Location $PSScriptRoot
$PROJECT_ROOT = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $PROJECT_ROOT

Write-Host "🚀 Genesis Trading System - Миграция на Python 3.11" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# Шаг 1: Проверка Python 3.11
Write-Host "`n📋 Шаг 1: Проверка наличия Python 3.11..." -ForegroundColor Yellow

$python311Paths = @(
    "C:\Users\zaytc\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Python311\python.exe",
    "C:\Program Files\Python311\python.exe"
)

$python311 = $null
foreach ($path in $python311Paths) {
    if (Test-Path $path) {
        $python311 = $path
        Write-Host "✅ Найден Python 3.11: $path" -ForegroundColor Green
        break
    }
}

if (-not $python311) {
    # Попробуем найти через py launcher
    $pyList = & py -3.11 --list 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Python 3.11 доступен через py launcher" -ForegroundColor Green
        $python311 = "py -3.11"
    } else {
        Write-Host "❌ Python 3.11 не найден!" -ForegroundColor Red
        Write-Host "`n📥 Скачайте и установите:" -ForegroundColor Yellow
        Write-Host "   https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -ForegroundColor Cyan
        Write-Host "   ⚠️ Обязательно отметьте 'Add Python to PATH' при установке!" -ForegroundColor Red
        exit 1
    }
}

# Шаг 2: Создание нового venv
Write-Host "`n📋 Шаг 2: Создание нового виртуального окружения..." -ForegroundColor Yellow

$venvPath = Join-Path $PROJECT_ROOT "venv311"

if (Test-Path $venvPath) {
    Write-Host "⚠️ venv311 уже существует. Удаляю..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvPath
}

Write-Host "Создаю venv311..." -ForegroundColor Cyan
if ($python311 -eq "py -3.11") {
    & py -3.11 -m venv venv311
} else {
    & $python311 -m venv venv311
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Не удалось создать виртуальное окружение" -ForegroundColor Red
    exit 1
}

Write-Host "✅ venv311 создан" -ForegroundColor Green

# Шаг 3: Активация и установка зависимостей
Write-Host "`n📋 Шаг 3: Установка зависимостей..." -ForegroundColor Yellow

$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
& $activateScript

Write-Host "Обновляю pip..." -ForegroundColor Cyan
python -m pip install --upgrade pip

if (Test-Path "requirements.txt") {
    Write-Host "Устанавливаю зависимости из requirements.txt..." -ForegroundColor Cyan
    pip install -r requirements.txt
} else {
    Write-Host "⚠️ requirements.txt не найден. Устанавливаю основные пакеты..." -ForegroundColor Yellow
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install scipy scikit-learn lightgbm
    pip install MetaTrader5 PySide6 pandas numpy
    pip install flask prometheus-client
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Ошибка установки зависимостей" -ForegroundColor Red
    exit 1
}

# Шаг 4: Проверка
Write-Host "`n📋 Шаг 4: Проверка установки..." -ForegroundColor Yellow

python -c "
import sys
print(f'Python версия: {sys.version}')
print(f'Python путь: {sys.executable}')

try:
    import torch
    print(f'✅ torch: {torch.__version__}, Tensor OK: {hasattr(torch, \"Tensor\")}')
except Exception as e:
    print(f'❌ torch: {e}')

try:
    import scipy
    print(f'✅ scipy: {scipy.__version__}')
except Exception as e:
    print(f'❌ scipy: {e}')

try:
    import sklearn
    print(f'✅ sklearn: {sklearn.__version__}')
except Exception as e:
    print(f'❌ sklearn: {e}')

try:
    import lightgbm
    print(f'✅ lightgbm: {lightgbm.__version__}')
except Exception as e:
    print(f'❌ lightgbm: {e}')
"

# Шаг 5: Инструкция по запуску
Write-Host "`n✅ МИГРАЦИЯ ЗАВЕРШЕНА!" -ForegroundColor Green
Write-Host "========================" -ForegroundColor Green
Write-Host "`n📌 Для запуска используйте новое окружение:" -ForegroundColor Yellow
Write-Host "   .\venv311\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "   python main_pyside.py" -ForegroundColor Cyan
Write-Host "`n📌 Или через VS Code:" -ForegroundColor Yellow
Write-Host "   1. Ctrl+Shift+P → Python: Select Interpreter" -ForegroundColor Cyan
Write-Host "   2. Выберите venv311\Scripts\python.exe" -ForegroundColor Cyan
Write-Host "   3. Запустите main_pyside.py" -ForegroundColor Cyan
