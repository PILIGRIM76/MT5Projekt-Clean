"""
Pre-flight check: Автоматическая проверка системы перед запуском.
Запускайте перед каждым стартом main_pyside.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent

def check_env():
    print("🔍 Проверка .env...")
    load_dotenv()
    required_vars = ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_PATH"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        print(f"❌ ОШИБКА: Отсутствуют переменные в .env: {', '.join(missing)}")
        return False
    print("✅ Переменные окружения заполнены.")
    return True

def check_mt5_path():
    print("🔍 Проверка пути к MetaTrader 5...")
    mt5_path = os.getenv("MT5_PATH")
    if not Path(mt5_path).exists():
        print(f"❌ ОШИБКА: Файл терминала не найден: {mt5_path}")
        return False
    print(f"✅ Терминал найден: {mt5_path}")
    return True

def check_directories():
    print("🔍 Проверка директорий...")
    dirs_to_check = ["database", "logs", "ai_models"]
    for d in dirs_to_check:
        path = BASE_DIR / d
        path.mkdir(parents=True, exist_ok=True)
        print(f"  ✅ Директория '{d}' готова.")
    return True

def check_dependencies():
    print("🔍 Проверка критических зависимостей...")
    try:
        import MetaTrader5
        import pandas
        import pydantic
        print("✅ Все критические библиотеки импортируются.")
        return True
    except ImportError as e:
        print(f"❌ ОШИБКА: {e}")
        print("💡 Решение: pip install -r requirements.txt")
        return False

def check_secrets_not_in_json():
    print("🔍 Проверка безопасности (секреты не в settings.json)...")
    settings_path = BASE_DIR / "configs" / "settings.json"
    if not settings_path.exists():
        print("⚠️ settings.json не найден (это ОК, если используется .env)")
        return True
    
    try:
        import json
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        
        dangerous_keys = ["MT5_PASSWORD", "TELEGRAM_BOT_TOKEN", "FINNHUB_API_KEY"]
        found = [k for k in dangerous_keys if k in settings and settings[k] and not settings[k].startswith("${")]
        
        if found:
            print(f"❌ ОШИБКА: Секреты в открытом виде в settings.json: {found}")
            return False
        print("✅ Секреты не найдены в открытом виде.")
        return True
    except Exception as e:
        print(f"⚠️ Не удалось проверить settings.json: {e}")
        return True

def main():
    print("="*60)
    print("🚀 GENESIS TRADING SYSTEM: PRE-FLIGHT CHECK")
    print("="*60)
    
    checks = [
        check_env(),
        check_mt5_path(),
        check_directories(),
        check_dependencies(),
        check_secrets_not_in_json(),
    ]
    
    print("="*60)
    if all(checks):
        print("🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ! Система готова к запуску.")
        print("💡 Теперь запустите: python main_pyside.py")
        sys.exit(0)
    else:
        print("⚠️ ОБНАРУЖЕНЫ ПРОБЛЕМЫ. Исправьте ошибки выше.")
        sys.exit(1)

if __name__ == "__main__":
    main()