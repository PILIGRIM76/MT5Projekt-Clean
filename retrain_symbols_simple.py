"""
Простой скрипт для удаления моделей из базы данных
Использование: python retrain_symbols_simple.py BITCOIN USDJPY
"""
import sys
import sqlite3
from pathlib import Path

print("="*60)
print("СКРИПТ УДАЛЕНИЯ МОДЕЛЕЙ ДЛЯ ПЕРЕОБУЧЕНИЯ")
print("="*60)

# Проверяем аргументы
if len(sys.argv) < 2:
    print("\nОшибка: Не указаны символы для переобучения")
    print("Использование: python retrain_symbols_simple.py SYMBOL1 SYMBOL2 ...")
    print("Пример: python retrain_symbols_simple.py BITCOIN USDJPY")
    sys.exit(1)

symbols = sys.argv[1:]
print(f"\nСимволы для переобучения: {', '.join(symbols)}")

# Путь к базе данных
db_path = Path("F:/Enjen/trading_system.db")

if not db_path.exists():
    print(f"\nОшибка: База данных не найдена по пути: {db_path}")
    print("Проверьте путь в configs/settings.json")
    sys.exit(1)

print(f"\nПодключение к базе данных: {db_path}")

try:
    # Подключаемся к базе данных
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    total_deleted = 0
    
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"Обработка символа: {symbol}")
        print(f"{'='*60}")
        
        # Проверяем количество моделей
        cursor.execute("SELECT COUNT(*) FROM trained_models WHERE symbol = ?", (symbol,))
        count_before = cursor.fetchone()[0]
        
        if count_before > 0:
            print(f"Найдено моделей: {count_before}")
            
            # Удаляем модели
            cursor.execute("DELETE FROM trained_models WHERE symbol = ?", (symbol,))
            conn.commit()
            
            # Проверяем результат
            cursor.execute("SELECT COUNT(*) FROM trained_models WHERE symbol = ?", (symbol,))
            count_after = cursor.fetchone()[0]
            
            deleted = count_before - count_after
            total_deleted += deleted
            
            print(f"✓ Удалено моделей: {deleted}")
        else:
            print(f"⚠ Модели не найдены в базе данных")
    
    conn.close()
    
    print("\n" + "="*60)
    print(f"ПРОЦЕСС ЗАВЕРШЕН!")
    print(f"Всего удалено моделей: {total_deleted}")
    print("="*60)
    
    if total_deleted > 0:
        print("\nСледующие шаги:")
        print("1. Запустите торговую систему: python main_pyside.py")
        print("2. R&D цикл автоматически переобучит модели (каждые 5 минут)")
        print("3. Новые модели будут использовать 20 признаков (без KG)")
        print("4. Проверьте логи на наличие сообщений [R&D]")
    
except Exception as e:
    print(f"\n✗ Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
