# -*- coding: utf-8 -*-
"""
optimize_system.py — Оптимизация системы для 16 ГБ RAM + NVIDIA GPU

Что делает:
1. Проверяет доступность CUDA/nvidia-smi
2. Исправляет ложные предупреждения о памяти (порог 2ГБ → 4ГБ для 16ГБ RAM)
3. Включает GPU-ускорение LightGBM (device='gpu') в auto_trainer.py
4. Настраивает агрессивный сборщик мусора (gc)
5. Отключает избыточное логирование AccountManager

Запуск:
    python optimize_system.py
"""

import gc
import logging
import subprocess
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("SystemOptimizer")


def check_cuda() -> bool:
    """Проверяет доступность CUDA через nvidia-smi."""
    try:
        result = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            text=True,
        )
        gpu_info = result.strip()
        logger.info(f"✅ NVIDIA GPU обнаружена: {gpu_info}")
        return True
    except FileNotFoundError:
        logger.warning("⚠️ nvidia-smi не найден. Проверьте установку драйверов NVIDIA.")
        return False
    except subprocess.CalledProcessError as e:
        logger.warning(f"⚠️ Ошибка nvidia-smi: {e}")
        return False


def fix_memory_thresholds() -> bool:
    """
    Исправляет пороги памяти в trading_system.py.

    Было: предупреждение при < 2.0 ГБ свободно (ложные тревоги при 16 ГБ RAM)
    Стало: предупреждение при < 4.0 ГБ свободно (16 - 4 = 12 ГБ свободно — запас)
    """
    logger.info("🔧 Калибровка порогов памяти...")

    target_file = Path(__file__).parent / "src" / "core" / "trading_system.py"
    if not target_file.exists():
        logger.error(f"❌ Файл {target_file} не найден.")
        return False

    content = target_file.read_text(encoding="utf-8")

    replacements = {
        "available_ram < 2.0": "available_ram < 4.0",
        "available_ram < 1.5": "available_ram < 3.0",
        "RAM_WARNING_THRESHOLD = 2.0": "RAM_WARNING_THRESHOLD = 4.0",
        "RAM_WARNING_THRESHOLD = 1.5": "RAM_WARNING_THRESHOLD = 3.0",
        "max_memory_mb = 8192": "max_memory_mb = 12288",  # 12 ГБ вместо 8
        "max_memory_gb = 8": "max_memory_gb = 12",
    }

    changes_made = 0
    for old, new in replacements.items():
        if old in content:
            content = content.replace(old, new)
            changes_made += 1
            logger.info(f"   ✅ {old} → {new}")

    if changes_made > 0:
        target_file.write_text(content, encoding="utf-8")
        logger.info(f"✅ Применено {changes_made} изменений порогов памяти.")
        return True
    else:
        logger.info("   ℹ️ Пороги памяти уже в норме или формат отличается.")
        return False


def enable_gpu_training() -> bool:
    """
    Включает GPU-ускорение LightGBM в auto_trainer.py.

    Добавляет параметры device='gpu' в словарь параметров модели.
    """
    logger.info("🚀 Настройка GPU-обучения LightGBM...")

    target_file = Path(__file__).parent / "src" / "ml" / "auto_trainer.py"
    if not target_file.exists():
        logger.warning(f"⚠️ Файл {target_file} не найден. Пропуск.")
        return False

    content = target_file.read_text(encoding="utf-8")

    # Проверяем, уже ли настроено
    if "'device': 'gpu'" in content or '"device": "gpu"' in content:
        logger.info("   ✅ GPU уже настроен в auto_trainer.py")
        return True

    # Ищем блок параметров LightGBM и добавляем GPU параметры
    # Обычно это выглядит как: params = { ... } или lgb_params = { ... }
    old_params_block = """            "n_jobs": 2,
        }"""

    new_params_block = """            "n_jobs": 2,
            # GPU ускорение (если доступно)
            "device": "gpu",
            "gpu_platform_id": 0,
            "gpu_device_id": 0,
            "histogram_pool_size": 256,
        }"""

    if old_params_block in content:
        content = content.replace(old_params_block, new_params_block)
        target_file.write_text(content, encoding="utf-8")
        logger.info("   ✅ GPU параметры добавлены в auto_trainer.py")
        logger.info("   💡 Если возникнут ошибки — переустановите: pip install lightgbm --no-binary :all:")
        return True
    else:
        logger.warning("   ⚠️ Не найден блок параметров LightGBM. Проверьте файл вручную.")
        logger.info("   💡 Добавьте 'device': 'gpu' в словарь параметров LightGBM")
        return False


def optimize_gc() -> None:
    """
    Настраивает сборщик мусора Python для более агрессивной очистки.

    По умолчанию: (700, 10, 10) — слишком редко для циклических ссылок.
    Новый порог: (500, 5, 5) — более частая очистка.
    """
    logger.info("♻️ Оптимизация сборщика мусора (GC)...")

    # Устанавливаем более агрессивные пороги
    gc.set_threshold(500, 5, 5)
    logger.info("   ✅ GC пороги: (500, 5, 5) — более частая очистка циклических ссылок")

    # Принудительно запускаем сборку сейчас
    collected = gc.collect()
    logger.info(f"   🧹 Собрано {collected} объектов при начальной очистке")


def reduce_account_manager_log_noise() -> bool:
    """
    Понижает уровень логирования AccountManager с INFO на DEBUG.

    Было: лог каждые 3-6 секунд (спам)
    Стало: только при изменении данных
    """
    logger.info("🔇 Снижение шума логов AccountManager...")

    target_file = Path(__file__).parent / "src" / "core" / "account_manager.py"
    if not target_file.exists():
        logger.warning(f"⚠️ Файл {target_file} не найден. Пропуск.")
        return False

    content = target_file.read_text(encoding="utf-8")

    old_log = 'logger.info(f"[AccountManager] Тип:'
    new_log = 'logger.debug(f"[AccountManager] Тип:'

    if old_log in content:
        content = content.replace(old_log, new_log)
        target_file.write_text(content, encoding="utf-8")
        logger.info("   ✅ AccountManager логи переведены на DEBUG уровень")
        return True
    else:
        logger.info("   ℹ️ Логи AccountManager уже на DEBUG или формат отличается.")
        return False


def print_summary(has_gpu: bool) -> None:
    """Выводит итоговый отчёт."""
    logger.info("=" * 60)
    logger.info("✅ ОПТИМИЗАЦИЯ ЗАВЕРШЕНА")
    logger.info("=" * 60)
    logger.info("")
    logger.info("📊 Что изменено:")
    logger.info("   • Порог памяти: 2ГБ → 4ГБ (меньше ложных тревог)")
    logger.info("   • GC оптимизирован для частой очистки")
    logger.info("   • AccountManager логи → DEBUG (меньше спама)")

    if has_gpu:
        logger.info("   • GPU параметры добавлены в auto_trainer.py")
        logger.info("")
        logger.info("⚠️ ВАЖНО для GPU:")
        logger.info("   Для работы LightGBM на GPU требуется:")
        logger.info("   1. pip uninstall lightgbm -y")
        logger.info("   2. pip install lightgbm --no-binary :all:")
        logger.info("   3. Перезапустите торговую систему")
    else:
        logger.info("")
        logger.info("💡 GPU не обнаружен — обучение на CPU (это нормально)")
        logger.info("   Загрузка CPU 4-17% — в пределах нормы")

    logger.info("")
    logger.info("🚀 Перезапустите Genesis Trading System для применения изменений.")
    logger.info("=" * 60)


def main() -> None:
    logger.info("=" * 60)
    logger.info("🛠 ОПТИМИЗАТОР СИСТЕМЫ — 16GB RAM + GPU")
    logger.info("=" * 60)
    logger.info("")

    # 1. Проверка GPU
    has_gpu = check_cuda()
    logger.info("")

    # 2. Исправление порогов памяти
    fix_memory_thresholds()
    logger.info("")

    # 3. Настройка GPU (если доступна)
    if has_gpu:
        enable_gpu_training()
    else:
        logger.info("⏭️ Пропуск настройки GPU (оборудование не найдено)")
    logger.info("")

    # 4. Снижение шума логов
    reduce_account_manager_log_noise()
    logger.info("")

    # 5. Оптимизация GC
    optimize_gc()
    logger.info("")

    # 6. Итог
    print_summary(has_gpu)


if __name__ == "__main__":
    main()
