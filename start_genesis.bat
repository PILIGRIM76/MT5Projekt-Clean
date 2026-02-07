@echo off
REM Этот скрипт автоматически запускает торговую систему Genesis

REM Переходим в директорию, где находится сам .bat файл
cd /d %~dp0

REM =================================================================
REM === КРИТИЧЕСКИЙ ШАГ: ОГРАНИЧЕНИЕ ЯДЕР CPU ДЛЯ РАЗГРУЗКИ ===
REM =================================================================
REM Установите здесь желаемое количество ядер (например, 4 или 6).
REM Это предотвратит 100% загрузку процессора библиотеками LightGBM, NumPy и Numba.

REM Установите здесь 4, чтобы оставить 2 ядра свободными для GUI и ОС.
set OMP_NUM_THREADS=2
set MKL_NUM_THREADS=2
set NUMBA_NUM_THREADS=2
set TORCH_NUM_THREADS=2

REM Переходим в директорию, где находится сам .bat файл
cd /d %~dp0

echo Ограничение CPU: OMP_NUM_THREADS=%OMP_NUM_THREADS%
call venv\Scripts\activate

echo Запуск Genesis Trader...
start "GenesisTrader" venv\Scripts\pythonw.exe main_pyside.py

exit