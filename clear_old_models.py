# Очистка старых моделей AI
# Запустите: python clear_old_models.py

import os
import shutil
from pathlib import Path


def clear_old_models():
    """Удаляет старые модели и скалеры для чистого переобучения"""

    # Путь к моделям (измените если нужно)
    models_path = Path("F:/Enjen/database/ai_models")

    if not models_path.exists():
        print(f"❌ Папка не найдена: {models_path}")
        return

    print(f"📂 Папка моделей: {models_path}")
    print(f"📊 Размер до очистки: {get_folder_size(models_path) / 1024 / 1024:.2f} MB")

    # Считаем файлы
    model_files = list(models_path.glob("*_model.joblib"))
    scaler_files = list(models_path.glob("*_scaler.joblib"))
    metadata_files = list(models_path.glob("*_metadata.json"))

    print(f"\n📋 Найдено файлов:")
    print(f"  • Моделей (.joblib): {len(model_files)}")
    print(f"  • Скалеров (.joblib): {len(scaler_files)}")
    print(f"  • Метаданных (.json): {len(metadata_files)}")

    if not model_files and not scaler_files:
        print("\n✅ Папка уже пуста, очистка не нужна")
        return

    # Запрос подтверждения
    print("\n⚠️ ВНИМАНИЕ: Это удалит ВСЕ старые модели!")
    print("   Система будет вынуждена обучить их с нуля.")
    print("   Это может занять время (зависит от количества символов).")

    response = input("\nПродолжить? (да/нет): ").strip().lower()

    if response not in ["да", "y", "yes"]:
        print("❌ Операция отменена")
        return

    # Удаление
    print("\n🗑️ Удаление файлов...")

    deleted_count = 0
    for file_pattern, name in [
        ("*_model.joblib", "модели"),
        ("*_scaler.joblib", "скалеры"),
        ("*_metadata.json", "метаданные"),
    ]:
        for file_path in models_path.glob(file_pattern):
            try:
                file_path.unlink()
                deleted_count += 1
                print(f"  ✅ Удален: {file_path.name}")
            except Exception as e:
                print(f"  ❌ Ошибка удаления {file_path.name}: {e}")

    print(f"\n✅ Удалено файлов: {deleted_count}")
    print(f"📊 Размер после очистки: {get_folder_size(models_path) / 1024 / 1024:.2f} MB")
    print("\n🎯 ГОТОВО! Теперь перезапустите систему.")
    print("   Модели будут переобучены с правильным количеством признаков.")


def get_folder_size(path):
    """Получает размер папки в байтах"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    return total_size


if __name__ == "__main__":
    print("=" * 60)
    print("🧹 ОЧИСТКА СТАРЫХ МОДЕЛЕЙ AI")
    print("=" * 60)
    print()
    clear_old_models()
