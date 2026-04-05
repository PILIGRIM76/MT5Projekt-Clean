# -*- coding: utf-8 -*-
"""
Быстрая оптимизация Genesis Trading System для снижения нагрузки на ПК.
Запустите: python optimize_performance.py
"""

import json
import os
import sys
from pathlib import Path


def load_config():
    """Загрузка конфигурации"""
    config_path = Path(__file__).parent / "configs" / "settings.json"
    if not config_path.exists():
        print("❌ configs/settings.json не найден!")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        content = "\n".join(line for line in f if not line.strip().startswith("//"))
        return json.loads(content), config_path


def save_config(config, config_path):
    """Сохранение конфигурации"""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"✅ Конфигурация сохранена: {config_path}")


def optimize_config(config):
    """Оптимизация конфигурации для снижения нагрузки"""
    print("\n" + "=" * 60)
    print("⚙️ ОПТИМИЗАЦИЯ КОНФИГУРАЦИИ")
    print("=" * 60)

    changes = []

    # 1. Уменьшить количество символов для сканирования
    current_top = config.get("TOP_N_SYMBOLS", 17)
    if current_top > 10:
        config["TOP_N_SYMBOLS"] = 10
        changes.append(f"TOP_N_SYMBOLS: {current_top} → 10 (сканировать меньше символов)")

    # 2. Увеличить интервал торговли
    current_interval = config.get("TRADE_INTERVAL_SECONDS", 15)
    if current_interval < 30:
        config["TRADE_INTERVAL_SECONDS"] = 30
        changes.append(f"TRADE_INTERVAL_SECONDS: {current_interval} → 30 (реже проверять)")

    # 3. Уменьшить MAX_OPEN_POSITIONS
    current_positions = config.get("MAX_OPEN_POSITIONS", 10)
    if current_positions > 5:
        config["MAX_OPEN_POSITIONS"] = 5
        changes.append(f"MAX_OPEN_POSITIONS: {current_positions} → 5 (меньше позиций)")

    # 4. Отключить Web Dashboard если не нужен
    web_enabled = config.get("web_dashboard", {}).get("enabled", True)
    if web_enabled:
        config.setdefault("web_dashboard", {})["enabled"] = False
        changes.append("Web Dashboard: ОТКЛЮЧЁН (экономит ~200 MB RAM)")

    # 5. Отключить VectorDB cleanup если не нужен постоянно
    vector_db = config.get("vector_db", {})
    if vector_db.get("cleanup_enabled", True):
        vector_db["cleanup_enabled"] = False
        changes.append("VectorDB cleanup: ОТКЛЮЧЁН (фоновая задача)")

    # 6. Отключить Graph Visualization
    if config.get("ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION", False):
        config["ENABLE_KNOWLEDGE_GRAPH_VISUALIZATION"] = False
        changes.append("Knowledge Graph Visual: ОТКЛЮЧЁН (тяжёлая отрисовка)")

    # 7. Уменьшить GP параметры
    if config.get("GP_POPULATION_SIZE", 50) > 30:
        config["GP_POPULATION_SIZE"] = 30
        changes.append(f"GP_POPULATION_SIZE: {config.get('GP_POPULATION_SIZE', 50)} → 30")

    if config.get("GP_GENERATIONS", 20) > 15:
        config["GP_GENERATIONS"] = 15
        changes.append(f"GP_GENERATIONS: {config.get('GP_GENERATIONS', 20)} → 15")

    # 8. Увеличить интервал переобучения
    if config.get("TRAINING_INTERVAL_SECONDS", 86400) < 172800:
        config["TRAINING_INTERVAL_SECONDS"] = 172800  # 48 часов вместо 24
        changes.append("TRAINING_INTERVAL: 24ч → 48ч (реже переобучение)")

    # 9. Отключить авто-переобучение если включено
    auto_retrain = config.get("auto_retraining", {})
    if auto_retrain.get("enabled", True):
        auto_retrain["enabled"] = False
        changes.append("Auto Retraining: ОТКЛЮЧЁН (запускать вручную)")

    return changes


def main():
    print("\n" + "=" * 60)
    print("🚀 GENESIS TRADING - ОПТИМИЗАЦИЯ ПРОИЗВОДИТЕЛЬНОСТИ")
    print("=" * 60)

    config, config_path = load_config()
    changes = optimize_config(config)

    if not changes:
        print("\n✅ Конфигурация уже оптимизирована!")
        return

    print("\n📋 Планируемые изменения:")
    for i, change in enumerate(changes, 1):
        print(f"  {i}. {change}")

    print("\n" + "=" * 60)
    confirm = input("\nПрименить оптимизацию? (y/n) [y]: ").strip().lower()

    if confirm in ["", "y", "yes"]:
        save_config(config, config_path)
        print("\n✅ Оптимизация применена!")
        print("\n💡 Рекомендации:")
        print("  1. Перезапустите Genesis Trading")
        print("  2. Закройте другие тяжёлые приложения")
        print("  3. Используйте SSD для папки БД")
        print("  4. Убедитесь что достаточно RAM (минимум 8 GB)")
        print("\n📊 Ожидаемый результат:")
        print("  - CPU: -30-50% нагрузки")
        print("  - RAM: -500 MB - 1 GB")
        print("  - Диск: меньше операций записи")
    else:
        print("\n❌ Оптимизация отменена")


if __name__ == "__main__":
    main()
