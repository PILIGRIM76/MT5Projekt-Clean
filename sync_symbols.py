import MetaTrader5 as mt5
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

# Путь к конфигу
CONFIG_PATH = Path("configs/settings.json")


def clean_json_content(content):
    """Удаляет комментарии // из JSON перед парсингом"""
    return "\n".join(line for line in content.splitlines() if not line.strip().startswith("//"))


def get_asset_category(symbol_info):
    """
    Определяет категорию актива на основе пути в дереве символов MT5.
    Адаптировано под Alpari и общие стандарты.
    """
    path = symbol_info.path.upper()
    name = symbol_info.name.upper()

    # 1. Криптовалюты
    if "CRYPTO" in path or "BITCOIN" in name or "ETHEREUM" in name:
        return "CRYPTO"

    # 2. Индексы
    if "INDIC" in path or "INDEX" in path or name in ["NAS100", "US500", "US30", "GER40", "DE40"]:
        return "INDICES"

    # 3. Сырье (Нефть, Газ, Металлы)
    if "COMMOD" in path or "METAL" in path or "ENERGY" in path or "OIL" in path or "SPOT" in path:
        # Исключаем валютные пары с золотом, если они лежат в форексе, но обычно XAUUSD это Commodities
        return "COMMODITIES"

    # 4. Акции (CFD)
    if "STOCK" in path or "SHARE" in path or "NASDAQ" in path or "NYSE" in path or "CFD" in name:
        return "NYSE"

    # 5. Форекс (по умолчанию)
    if "FOREX" in path or "FX" in path or "MAJOR" in path or "MINOR" in path:
        return "FOREX"

    # Если не удалось определить, считаем Форексом (самый безопасный вариант)
    return "FOREX"


def main():
    print("--- Синхронизация символов с MT5 ---")

    # 1. Подключение к MT5
    if not mt5.initialize():
        print("❌ Ошибка: Не удалось подключиться к MetaTrader 5.")
        print("Убедитесь, что терминал запущен.")
        return

    # 2. Получение видимых символов
    # Мы берем только visible=True, чтобы пользователь сам выбрал в терминале, чем торговать
    symbols = mt5.symbols_get(visible=True)

    if not symbols:
        print("❌ Ошибка: В 'Обзоре рынка' (Market Watch) нет символов!")
        print("Добавьте символы в терминале (Ctrl+M -> Ctrl+U) и запустите скрипт снова.")
        mt5.shutdown()
        return

    print(f"✅ Найдено активных символов в терминале: {len(symbols)}")

    # 3. Формирование списков
    new_whitelist = []
    new_asset_types = {}

    print("\nОбработка символов:")
    for s in symbols:
        category = get_asset_category(s)
        new_whitelist.append(s.name)
        new_asset_types[s.name] = category
        print(f"  - {s.name:<15} -> {category}")

    mt5.shutdown()

    # 4. Чтение текущего конфига
    if not CONFIG_PATH.exists():
        print(f"❌ Файл {CONFIG_PATH} не найден.")
        return

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = clean_json_content(f.read())
            current_config = json.loads(content)
    except Exception as e:
        print(f"❌ Ошибка чтения конфига: {e}")
        return

    # 5. Создание бэкапа
    backup_name = f"configs/settings_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy(CONFIG_PATH, backup_name)
    print(f"\n💾 Создан бэкап настроек: {backup_name}")

    # 6. Обновление конфига
    current_config["SYMBOLS_WHITELIST"] = new_whitelist
    current_config["asset_types"] = new_asset_types

    # Обновляем TOP_N_SYMBOLS, чтобы он не был меньше количества символов
    if current_config.get("TOP_N_SYMBOLS", 10) < len(new_whitelist):
        current_config["TOP_N_SYMBOLS"] = len(new_whitelist)

    # 7. Запись
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(current_config, f, indent=2, ensure_ascii=False)

    print("\n✅ Файл configs/settings.json успешно обновлен!")
    print(f"Теперь в системе {len(new_whitelist)} символов с правильными именами.")
    print("Перезапустите main_pyside.py, чтобы применить изменения.")


if __name__ == "__main__":
    main()