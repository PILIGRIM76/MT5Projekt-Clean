# -*- coding: utf-8 -*-
"""
setup_launcher.py - Конфигурационный мастер для Genesis Trading System
Запускается перед основным GUI для настройки путей и параметров
"""
import os
import sys
import json
from pathlib import Path
from typing import Optional


def print_header(text: str):
    """Вывод заголовка"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_step(step: int, text: str):
    """Вывод шага"""
    print(f"\n[Шаг {step}] {text}")
    print("-" * 40)


def get_user_input(prompt: str, default: Optional[str] = None, required: bool = True) -> str:
    """Получение ввода от пользователя с опциональным значением по умолчанию"""
    if default:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "
    
    while True:
        try:
            user_input = input(full_prompt).strip()
            if not user_input:
                if default:
                    return default
                elif not required:
                    return ""
                print("❌ Это поле обязательно для заполнения!")
                continue
            return user_input
        except (EOFError, KeyboardInterrupt):
            print("\n\n⚠ Прервано пользователем")
            sys.exit(1)


def verify_file_path(path: str, file_name: str = "файл") -> bool:
    """Проверка существования файла"""
    if not path:
        return False
    full_path = Path(path)
    if full_path.exists():
        print(f"✓ {file_name} найден: {path}")
        return True
    else:
        print(f"⚠ {file_name} не найден: {path}")
        return False


def verify_dir_path(path: str, dir_name: str = "папка") -> bool:
    """Проверка существования директории"""
    if not path:
        return False
    full_path = Path(path)
    if full_path.exists() and full_path.is_dir():
        print(f"✓ {dir_name} найдена: {path}")
        return True
    else:
        print(f"⚠ {dir_name} не найдена: {path}")
        # Предложим создать
        create = get_user_input("Создать эту папку? (y/n)", default="y")
        if create.lower() == 'y':
            try:
                full_path.mkdir(parents=True, exist_ok=True)
                print(f"✓ Папка создана: {path}")
                return True
            except Exception as e:
                print(f"❌ Ошибка создания папки: {e}")
                return False
        return False


def load_existing_config(config_path: Path) -> dict:
    """Загрузка существующей конфигурации"""
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = "".join(line for line in f if not line.strip().startswith("//"))
                return json.loads(content)
        except Exception as e:
            print(f"⚠ Ошибка чтения конфига: {e}")
    return {}


def save_config(config_path: Path, config: dict):
    """Сохранение конфигурации"""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Конфигурация сохранена: {config_path}")
    except Exception as e:
        print(f"❌ Ошибка сохранения конфига: {e}")
        raise


def setup_paths(config: dict) -> dict:
    """Настройка путей к файлам и папкам"""
    print_step(1, "Настройка путей")
    
    # MT5 путь
    print("\n📁 Укажите путь к MetaTrader 5:")
    default_mt5 = config.get('MT5_PATH', 'C:/Program Files/MetaTrader 5/terminal64.exe')
    mt5_path = get_user_input("Путь к terminal64.exe", default=default_mt5)
    if verify_file_path(mt5_path, "terminal64.exe"):
        config['MT5_PATH'] = mt5_path.replace('\\', '/')
    
    # Базы данных
    print("\n📁 Укажите папку для баз данных:")
    default_db = config.get('DATABASE_FOLDER', 'database')
    db_folder = get_user_input("Папка для БД", default=default_db)
    if verify_dir_path(db_folder, "папка баз данных"):
        config['DATABASE_FOLDER'] = db_folder.replace('\\', '/')
    
    # Логи
    print("\n📁 Укажите папку для логов:")
    default_logs = config.get('LOGS_FOLDER', 'logs')
    logs_folder = get_user_input("Папка для логов", default=default_logs)
    if verify_dir_path(logs_folder, "папка логов"):
        config['LOGS_FOLDER'] = logs_folder.replace('\\', '/')
    
    # Кэш моделей HuggingFace
    print("\n📁 Укажите папку для кэша AI-моделей (опционально):")
    default_hf = config.get('HF_MODELS_CACHE_DIR', '')
    hf_folder = get_user_input("Папка для AI-моделей", default=default_hf, required=False)
    if hf_folder:
        if verify_dir_path(hf_folder, "папка кэша моделей"):
            config['HF_MODELS_CACHE_DIR'] = hf_folder.replace('\\', '/')
    
    return config


def setup_mt5_credentials(config: dict) -> dict:
    """Настройка учетных данных MT5"""
    print_step(2, "Настройка MetaTrader 5")
    
    print("\n🔐 Введите учетные данные MT5:")
    
    # Логин
    default_login = str(config.get('MT5_LOGIN', ''))
    login = get_user_input("MT5 Login", default=default_login if default_login else None)
    config['MT5_LOGIN'] = login
    
    # Пароль
    default_password = config.get('MT5_PASSWORD', '')
    password = get_user_input("MT5 Пароль", default=default_password if default_password else None)
    config['MT5_PASSWORD'] = password
    
    # Сервер
    default_server = config.get('MT5_SERVER', '')
    server = get_user_input("MT5 Сервер", default=default_server if default_server else None)
    config['MT5_SERVER'] = server
    
    print(f"\n✓ Данные MT5 сохранены (логин: {login})")
    return config


def setup_api_keys(config: dict) -> dict:
    """Настройка API ключей"""
    print_step(3, "Настройка API ключей (опционально)")
    
    print("\n🔑 API ключи для внешних данных (можно пропустить):")
    
    apis = {
        'FINNHUB_API_KEY': 'Finnhub (анализ рынка)',
        'ALPHA_VANTAGE_API_KEY': 'Alpha Vantage (финансовые данные)',
        'NEWS_API_KEY': 'NewsAPI (новости)',
        'POLYGON_API_KEY': 'Polygon.io (рыночные данные)',
        'TWELVE_DATA_API_KEY': 'Twelve Data (котировки)',
        'FCS_API_KEY': 'FCS (финансовые данные)',
        'FRED_API_KEY': 'FRED (экономические данные)',
    }
    
    for key, description in apis.items():
        default_value = config.get(key, '')
        print(f"\n  {description}")
        value = get_user_input(f"  {key}", default=default_value if default_value else "", required=False)
        if value:
            config[key] = value
    
    # Neo4J
    print("\n🗄️  Графовая база Neo4J (опционально):")
    default_uri = config.get('NEO4J_URI', 'bolt://localhost:7687')
    config['NEO4J_URI'] = get_user_input("  Neo4J URI", default=default_uri, required=False)
    default_user = config.get('NEO4J_USER', 'neo4j')
    config['NEO4J_USER'] = get_user_input("  Neo4J User", default=default_user, required=False)
    default_pass = config.get('NEO4J_PASSWORD', '')
    config['NEO4J_PASSWORD'] = get_user_input("  Neo4J Password", default=default_pass if default_pass else "", required=False)
    
    return config


def setup_trading_params(config: dict) -> dict:
    """Настройка торговых параметров"""
    print_step(4, "Настройка торговых параметров")
    
    print("\n💰 Базовые торговые настройки:")
    
    # Риск
    default_risk = config.get('RISK_PERCENTAGE', 0.5)
    risk = get_user_input("Риск на сделку (%)", default=str(default_risk))
    try:
        config['RISK_PERCENTAGE'] = float(risk)
    except ValueError:
        print(f"⚠ Неверное значение, установлено {default_risk}")
        config['RISK_PERCENTAGE'] = default_risk
    
    # Макс позиций
    default_positions = config.get('MAX_OPEN_POSITIONS', 5)
    positions = get_user_input("Макс. открытых позиций", default=str(default_positions))
    try:
        config['MAX_OPEN_POSITIONS'] = int(positions)
    except ValueError:
        print(f"⚠ Неверное значение, установлено {default_positions}")
        config['MAX_OPEN_POSITIONS'] = default_positions
    
    # Таймфрейм
    default_interval = config.get('TRADE_INTERVAL_SECONDS', 60)
    interval = get_user_input("Интервал торговли (секунды)", default=str(default_interval))
    try:
        config['TRADE_INTERVAL_SECONDS'] = int(interval)
    except ValueError:
        print(f"⚠ Неверное значение, установлено {default_interval}")
        config['TRADE_INTERVAL_SECONDS'] = default_interval
    
    return config


def main():
    """Основная функция"""
    print_header("🚀 Genesis Trading System - Конфигурационный мастер")
    
    print("\nЭта программа поможет вам настроить Genesis Trading System.")
    print("Следуйте инструкциям для настройки путей и параметров.\n")
    
    # Определяем путь к конфигу
    if getattr(sys, 'frozen', False):
        # Запущено из EXE
        base_path = Path(sys.executable).parent
    else:
        # Запущено из исходников
        base_path = Path(__file__).parent
    
    config_path = base_path / 'configs' / 'settings.json'
    print(f"📄 Файл конфигурации: {config_path}")
    
    # Загружаем существующий конфиг или создаем новый
    config = load_existing_config(config_path)
    if config:
        print("✓ Существующая конфигурация загружена")
    else:
        print("⚠ Конфигурация не найдена, будет создана новая")
        # Базовые настройки по умолчанию
        config = {
            "SYMBOLS_WHITELIST": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BITCOIN"],
            "DATABASE_FOLDER": "database",
            "LOGS_FOLDER": "logs",
            "RISK_PERCENTAGE": 0.5,
            "MAX_OPEN_POSITIONS": 5,
            "TRADE_INTERVAL_SECONDS": 60,
            "strategies": {
                "breakout": {"window": 15},
                "mean_reversion": {"window": 50, "std_dev_multiplier": 1.9},
                "ma_crossover": {
                    "timeframe_params": {
                        "default": {"short_window": 15, "long_window": 35},
                        "low": {"short_window": 10, "long_window": 25},
                        "high": {"short_window": 50, "long_window": 200}
                    }
                }
            },
            "web_dashboard": {"enabled": True, "host": "0.0.0.0", "port": 8000},
            "vector_db": {"enabled": True, "path": "database/vector_db"}
        }
    
    try:
        # Шаг 1: Пути
        config = setup_paths(config)
        
        # Шаг 2: MT5
        config = setup_mt5_credentials(config)
        
        # Шаг 3: API ключи
        config = setup_api_keys(config)
        
        # Шаг 4: Торговые параметры
        config = setup_trading_params(config)
        
        # Сохранение
        print_header("💾 Сохранение конфигурации")
        save_config(config_path, config)
        
        # Финальное сообщение
        print_header("✅ Настройка завершена!")
        print("\n📋 Следующие шаги:")
        print("  1. Проверьте файл configs/settings.json при необходимости")
        print("  2. Запустите GenesisTrading.exe для начала работы")
        print("  3. При необходимости настройте дополнительные параметры через GUI\n")
        
        # Предложение запустить GUI
        run_gui = get_user_input("Запустить Genesis Trading System сейчас? (y/n)", default="y")
        if run_gui.lower() == 'y':
            print("\n🚀 Запуск Genesis Trading System...")
            # Запускаем основной исполняемый файл
            if getattr(sys, 'frozen', False):
                # Мы уже в EXE, нужно запустить основное приложение
                main_exe = Path(sys.executable).parent / 'GenesisTrading.exe'
                if main_exe.exists():
                    os.system(f'"{main_exe}"')
                else:
                    print("⚠ GenesisTrading.exe не найден")
            else:
                # Запускаем main_pyside.py
                main_py = Path(__file__).parent / 'main_pyside.py'
                if main_py.exists():
                    os.execv(sys.executable, [sys.executable, str(main_py)])
                else:
                    print("⚠ main_pyside.py не найден")
        else:
            print("\n👋 Для запуска откройте GenesisTrading.exe")
        
    except KeyboardInterrupt:
        print("\n\n⚠ Настройка прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
