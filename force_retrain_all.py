"""
Скрипт для экстренного переобучения моделей с исправлением scaler mismatch
Удаляет старые модели и скалеры, запускает автоматическое переобучение.

Использование:
    python force_retrain_all.py                    # Переобучить все символы
    python force_retrain_all.py EURUSD AUDJPY     # Конкретные символы
    python force_retrain_all.py --cleanup-only    # Только удалить старые модели
"""

import json
import logging
import queue
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from src.core.config_loader import load_config
from src.db.database_manager import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

logger.info("=" * 60)
logger.info("  СКРИПТ ЭКСТРЕННОГО ПЕРЕОБУЧЕНИЯ МОДЕЛЕЙ")
logger.info("  Исправление scaler mismatch")
logger.info("=" * 60)


def load_all_symbols_from_config() -> list:
    """Загружает все символы из конфигурации."""
    config = load_config()
    symbols = config.SYMBOLS_WHITELIST
    logger.info(f"Загружено {len(symbols)} символов из конфигурации")
    return symbols


def delete_old_models_and_scalers(db_manager: DatabaseManager, symbols: list) -> dict:
    """
    Удаляет старые модели и скалеры из БД.

    Returns:
        dict: Статистика удалений
    """
    stats = {"models_deleted": 0, "scalers_deleted": 0, "symbols_processed": 0, "errors": 0}

    for symbol in symbols:
        try:
            logger.info(f"\n{'='*50}")
            logger.info(f"Обработка: {symbol}")

            # 1. Удаляем champion_models
            check_models = "SELECT COUNT(*) as count FROM champion_models WHERE symbol = ?"
            result = db_manager.execute_query(check_models, (symbol,), fetch_one=True)

            if result and result[0] > 0:
                count_before = result[0]
                delete_models = "DELETE FROM champion_models WHERE symbol = ?"
                db_manager.execute_query(delete_models, (symbol,))
                stats["models_deleted"] += count_before
                logger.info(f"  ✓ Удалено моделей: {count_before}")
            else:
                logger.info(f"  - Моделей не найдено")

            # 2. Удаляем scalers
            check_scalers = "SELECT COUNT(*) as count FROM scalers WHERE symbol = ?"
            result = db_manager.execute_query(check_scalers, (symbol,), fetch_one=True)

            if result and result[0] > 0:
                count_before = result[0]
                delete_scalers = "DELETE FROM scalers WHERE symbol = ?"
                db_manager.execute_query(delete_scalers, (symbol,))
                stats["scalers_deleted"] += count_before
                logger.info(f"  ✓ Удалено скалеров: {count_before}")
            else:
                logger.info(f"  - Скалеров не найдено")

            # 3. Удаляем файлы .joblib из папки ai_models
            model_dir = Path("F:/Enjen/database/ai_models")
            if model_dir.exists():
                for pattern in [
                    f"{symbol}_model.joblib",
                    f"{symbol}_scaler.joblib",
                    f"{symbol}_x_scaler.joblib",
                    f"{symbol}_y_scaler.joblib",
                ]:
                    file_path = model_dir / pattern
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"  ✓ Удален файл: {pattern}")

            stats["symbols_processed"] += 1

        except Exception as e:
            logger.error(f"  ✗ Ошибка: {e}", exc_info=True)
            stats["errors"] += 1

    return stats


def cleanup_old_joblib_files(dry_run: bool = True) -> dict:
    """
    Проверяет и удаляет старые .joblib файлы с несоответствующими скалерами.

    Args:
        dry_run: Если True, только показывает что будет удалено

    Returns:
        dict: Статистика
    """
    import joblib

    model_dir = Path("F:/Enjen/database/ai_models")
    if not model_dir.exists():
        logger.warning(f"Директория моделей не найдена: {model_dir}")
        return {"checked": 0, "mismatched": 0, "deleted": 0}

    stats = {"checked": 0, "mismatched": 0, "deleted": 0}

    logger.info(f"\nПроверка скалеров в: {model_dir}")
    logger.info("-" * 50)

    for scaler_file in model_dir.glob("*_scaler.joblib"):
        stats["checked"] += 1

        try:
            scaler = joblib.load(scaler_file)
            n_features = getattr(scaler, "n_features_in_", None)

            if n_features is None:
                logger.warning(f"  ⚠ {scaler_file.name}: n_features_in_ отсутствует")
                continue

            # Проверяем ожидаемое количество признаков (20 из FEATURES_TO_USE)
            expected_features = 20  # Из конфигурации FEATURES_TO_USE

            if n_features != expected_features:
                stats["mismatched"] += 1
                logger.warning(
                    f"  ✗ MISMATCH: {scaler_file.name}\n"
                    f"    Текущие признаки: {n_features}\n"
                    f"    Ожидаемые: {expected_features}"
                )

                if not dry_run:
                    scaler_file.unlink()
                    stats["deleted"] += 1
                    logger.info(f"    ✓ Удален")
            else:
                logger.info(f"  ✓ OK: {scaler_file.name} ({n_features} признаков)")

        except Exception as e:
            logger.error(f"  ✗ Ошибка чтения {scaler_file.name}: {e}")

    return stats


def main():
    """Основная логика скрипта."""
    import argparse

    parser = argparse.ArgumentParser(description="Экстренное переобучение моделей")
    parser.add_argument(
        "symbols", nargs="*", help="Список символов для переобучения (если не указано, используются все из конфига)"
    )
    parser.add_argument("--cleanup-only", action="store_true", help="Только удалить старые модели без запуска переобучения")
    parser.add_argument("--check-scalers", action="store_true", help="Проверить скалеры на mismatch и удалить проблемные")
    parser.add_argument("--dry-run", action="store_true", help="Показать что будет сделано без фактического удаления")

    args = parser.parse_args()

    # Режим проверки скалеров
    if args.check_scalers:
        logger.info("\nРЕЖИМ: Проверка скалеров на mismatch")
        stats = cleanup_old_joblib_files(dry_run=args.dry_run)

        logger.info("\n" + "=" * 60)
        logger.info("РЕЗУЛЬТАТ ПРОВЕРКИ СКАЛЕРОВ:")
        logger.info(f"  Проверено: {stats['checked']}")
        logger.info(f"  Найдено mismatch: {stats['mismatched']}")
        logger.info(f"  Удалено: {stats['deleted']}")
        logger.info("=" * 60)

        if stats["mismatched"] > 0 and not args.dry_run:
            logger.info("\nСледующие шаги:")
            logger.info("1. Запустите систему: python main_pyside.py")
            logger.info("2. R&D цикл автоматически переобучит модели")
            logger.info("3. Новые скалеры будут созданы с правильным количеством признаков")

        return

    # Определяем символы
    symbols = args.symbols if args.symbols else load_all_symbols_from_config()

    if not symbols:
        logger.error("Не указано ни одного символа!")
        sys.exit(1)

    logger.info(f"\nЦелевые символы ({len(symbols)}):")
    for i, sym in enumerate(symbols, 1):
        logger.info(f"  {i}. {sym}")

    # Инициализация
    logger.info("\nЗагрузка конфигурации...")
    config = load_config()

    write_queue = queue.Queue()

    logger.info("Инициализация базы данных...")
    db_manager = DatabaseManager(config, write_queue)

    # Удаление старых моделей
    logger.info("\n" + "=" * 60)
    logger.info("ШАГ 1: Удаление старых моделей и скалеров")
    logger.info("=" * 60)

    delete_stats = delete_old_models_and_scalers(db_manager, symbols)

    logger.info("\n" + "=" * 60)
    logger.info("СТАТИСТИКА УДАЛЕНИЯ:")
    logger.info(f"  Символов обработано: {delete_stats['symbols_processed']}")
    logger.info(f"  Удалено моделей: {delete_stats['models_deleted']}")
    logger.info(f"  Удалено скалеров: {delete_stats['scalers_deleted']}")
    logger.info(f"  Ошибок: {delete_stats['errors']}")
    logger.info("=" * 60)

    if delete_stats["errors"] > 0:
        logger.warning("\n⚠ Были ошибки при удалении. Проверьте логи выше.")

    if args.cleanup_only:
        logger.info("\n✅ Очистка завершена!")
        logger.info("\nСледующие шаги:")
        logger.info("1. Запустите систему: python main_pyside.py")
        logger.info("2. Включите R&D цикл в настройках")
        logger.info("3. Модели будут переобучены автоматически")
        return

    logger.info("\n" + "=" * 60)
    logger.info("ШАГ 2: Запуск автоматического переобучения")
    logger.info("=" * 60)
    logger.info("\n✅ Удаление завершено!")
    logger.info("\nСледующие шаги:")
    logger.info("1. Запустите торговую систему: python main_pyside.py")
    logger.info("2. Перейдите в Training → Auto-Retrain")
    logger.info("3. Нажмите 'Start' для запуска автоматического переобучения")
    logger.info("4. Либо система сама запустит переобучение по расписанию")
    logger.info("\nМониторинг прогресса:")
    logger.info("  - Логи с тегом [R&D] или [AutoTrainer]")
    logger.info("  - Проверьте папку: F:/Enjen/database/ai_models/")
    logger.info("  - Новые файлы должны появиться: {SYMBOL}_model.joblib")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n⚠ Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"\n\n✗ КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        sys.exit(1)
