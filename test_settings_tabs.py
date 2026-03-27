"""
Тестовый файл для проверки всех вкладок окна настроек.
Проверяет загрузку, отображение и сохранение настроек.
"""

import sys
import os
import json
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QTimer
from src.gui.settings_window import SettingsWindow
from src.core.config_loader import load_config
from src.utils.scheduler_manager import SchedulerManager


def test_settings_window():
    """Тестирование окна настроек."""
    print("=" * 80)
    print("🧪 ТЕСТИРОВАНИЕ ОКНА НАСТРОЕК")
    print("=" * 80)
    
    # Инициализация QApplication
    app = QApplication(sys.argv)
    
    # Загрузка конфигурации
    print("\n📂 Загрузка конфигурации...")
    try:
        config = load_config()
        print("✅ Конфигурация загружена успешно")
    except Exception as e:
        print(f"❌ Ошибка загрузки конфигурации: {e}")
        return False
    
    # Создание менеджера планировщика
    print("\n⏰ Создание SchedulerManager...")
    try:
        scheduler_manager = SchedulerManager()
        print("✅ SchedulerManager создан")
    except Exception as e:
        print(f"❌ Ошибка создания SchedulerManager: {e}")
        return False
    
    # Создание окна настроек
    print("\n🪟 Создание SettingsWindow...")
    try:
        settings_window = SettingsWindow(scheduler_manager, config, None)
        print("✅ SettingsWindow создано")
    except Exception as e:
        print(f"❌ Ошибка создания SettingsWindow: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Тестирование вкладок
    print("\n" + "=" * 80)
    print("📑 ТЕСТИРОВАНИЕ ВКЛАДОК")
    print("=" * 80)
    
    tabs = [
        ("R&D (AI)", 0),
        ("Подключение MT5", 1),
        ("API Ключи", 2),
        ("Торговля", 3),
        ("Пути к данным", 4),
        ("Планировщик", 5),
    ]
    
    all_passed = True
    
    for tab_name, tab_index in tabs:
        print(f"\n{'─' * 80}")
        print(f"📋 Вкладка: {tab_name} (индекс {tab_index})")
        print(f"{'─' * 80}")
        
        try:
            widget = settings_window.tab_widget.widget(tab_index)
            if widget:
                print(f"✅ Вкладка '{tab_name}' существует и доступна")
                
                # Проверка видимых элементов
                children = widget.findChildren(QWidget)
                print(f"   📊 Найдено элементов: {len(children)}")
                
            else:
                print(f"❌ Вкладка '{tab_name}' не найдена")
                all_passed = False
                
        except Exception as e:
            print(f"❌ Ошибка доступа к вкладке '{tab_name}': {e}")
            all_passed = False
    
    # Тестирование элементов управления
    print("\n" + "=" * 80)
    print("🎛️ ТЕСТИРОВАНИЕ ЭЛЕМЕНТОВ УПРАВЛЕНИЯ")
    print("=" * 80)
    
    test_cases = [
        # R&D (AI)
        ("gp_pop_spin", "SpinBox", "Размер популяции GP"),
        ("gp_gen_spin", "SpinBox", "Количество поколений GP"),
        
        # Торговля
        ("risk_percentage_spinbox", "DoubleSpinBox", "Риск на сделку (%)"),
        ("risk_reward_ratio_spinbox", "DoubleSpinBox", "Risk/Reward Ratio"),
        ("max_daily_drawdown_spinbox", "DoubleSpinBox", "Макс. дневная просадка"),
        ("max_open_positions_spinbox", "SpinBox", "Макс. позиций"),
        ("trading_modes_widget", "TradingModesWidget", "Режимы торговли"),
        ("trading_modes_enable_checkbox", "CheckBox", "Включить режимы"),
        
        # Пути к данным
        ("db_folder_edit", "LineEdit", "Путь к БД"),
        ("logs_folder_edit", "LineEdit", "Путь к логам"),
        ("hf_cache_edit", "LineEdit", "HF Models Cache"),
        
        # Web Dashboard
        ("web_enabled_checkbox", "CheckBox", "Web Dashboard включен"),
        ("web_host_edit", "LineEdit", "Web хост"),
        ("web_port_spinbox", "SpinBox", "Web порт"),
        
        # Планировщик
        ("autostart_checkbox", "CheckBox", "Автозапуск"),
        ("maintenance_checkbox", "CheckBox", "Ежедневное обслуживание"),
        ("optimization_checkbox", "CheckBox", "Еженедельная оптимизация"),
        ("auto_retrain_checkbox", "CheckBox", "Автообучение"),
        ("auto_retrain_time_edit", "TimeEdit", "Время автообучения"),
        ("auto_retrain_interval_spin", "SpinBox", "Интервал автообучения"),
        ("auto_retrain_max_symbols_spin", "SpinBox", "Макс. символов для обучения"),
        ("auto_retrain_max_workers_spin", "SpinBox", "Потоков обучения"),
    ]
    
    for attr_name, widget_type, description in test_cases:
        try:
            widget = getattr(settings_window, attr_name, None)
            if widget:
                widget_class = widget.__class__.__name__
                print(f"✅ {description:40} [{widget_class}]")
            else:
                print(f"❌ {description:40} [НЕ НАЙДЕНО]")
                all_passed = False
        except Exception as e:
            print(f"❌ {description:40} [ОШИБКА: {e}]")
            all_passed = False
    
    # Тестирование загрузки настроек
    print("\n" + "=" * 80)
    print("💾 ТЕСТИРОВАНИЕ ЗАГРУЗКИ НАСТРОЕК")
    print("=" * 80)
    
    try:
        # Проверяем значения из конфигурации
        print(f"\n📊 Значения из конфигурации:")
        print(f"   GP_POPULATION_SIZE: {config.GP_POPULATION_SIZE}")
        print(f"   GP_GENERATIONS: {config.GP_GENERATIONS}")
        print(f"   RISK_PERCENTAGE: {config.RISK_PERCENTAGE}")
        print(f"   RISK_REWARD_RATIO: {config.RISK_REWARD_RATIO}")
        print(f"   MAX_DAILY_DRAWDOWN_PERCENT: {config.MAX_DAILY_DRAWDOWN_PERCENT}")
        print(f"   MAX_OPEN_POSITIONS: {config.MAX_OPEN_POSITIONS}")
        print(f"   SYMBOLS_WHITELIST: {len(config.SYMBOLS_WHITELIST)} символов")
        
        # Проверяем, что виджеты получили значения
        print(f"\n📊 Значения в виджетах:")
        print(f"   gp_pop_spin: {settings_window.gp_pop_spin.value()}")
        print(f"   gp_gen_spin: {settings_window.gp_gen_spin.value()}")
        print(f"   risk_percentage_spinbox: {settings_window.risk_percentage_spinbox.value()}")
        print(f"   risk_reward_ratio_spinbox: {settings_window.risk_reward_ratio_spinbox.value()}")
        print(f"   max_daily_drawdown_spinbox: {settings_window.max_daily_drawdown_spinbox.value()}")
        print(f"   max_open_positions_spinbox: {settings_window.max_open_positions_spinbox.value()}")
        print(f"   symbols_table rows: {settings_window.symbols_table.rowCount()}")
        
        # Сравнение значений
        print(f"\n🔍 Сравнение значений:")
        checks = [
            (config.GP_POPULATION_SIZE == settings_window.gp_pop_spin.value(), "GP_POPULATION_SIZE"),
            (config.GP_GENERATIONS == settings_window.gp_gen_spin.value(), "GP_GENERATIONS"),
            (config.RISK_PERCENTAGE == settings_window.risk_percentage_spinbox.value(), "RISK_PERCENTAGE"),
            (config.RISK_REWARD_RATIO == settings_window.risk_reward_ratio_spinbox.value(), "RISK_REWARD_RATIO"),
            (config.MAX_DAILY_DRAWDOWN_PERCENT == settings_window.max_daily_drawdown_spinbox.value(), "MAX_DAILY_DRAWDOWN"),
            (config.MAX_OPEN_POSITIONS == settings_window.max_open_positions_spinbox.value(), "MAX_OPEN_POSITIONS"),
            (len(config.SYMBOLS_WHITELIST) == settings_window.symbols_table.rowCount(), "SYMBOLS_WHITELIST"),
        ]
        
        for check, name in checks:
            if check:
                print(f"   ✅ {name}: совпадает")
            else:
                print(f"   ❌ {name}: НЕ совпадает")
                all_passed = False
                
    except Exception as e:
        print(f"❌ Ошибка тестирования настроек: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    # Тестирование торговли (режимы)
    print("\n" + "=" * 80)
    print("📊 ТЕСТИРОВАНИЕ РЕЖИМОВ ТОРГОВЛИ")
    print("=" * 80)
    
    try:
        if hasattr(settings_window, 'trading_modes_widget'):
            tm_widget = settings_window.trading_modes_widget
            
            # Проверка карточек режимов
            print(f"\n📋 Доступные режимы:")
            for mode_id, card in tm_widget.mode_cards.items():
                print(f"   ✅ {mode_id}: {card.mode_data['name']}")
            
            # Проверка переключателя
            print(f"\n🎛️ Переключатель режимов:")
            print(f"   Включен: {settings_window.trading_modes_enable_checkbox.isChecked()}")
            print(f"   modes_container enabled: {tm_widget.modes_container.isEnabled()}")
            
            # Проверка индикатора
            print(f"\n📍 Текущий режим:")
            print(f"   {tm_widget.current_mode_label.text()}")
            
        else:
            print("❌ trading_modes_widget не найден")
            all_passed = False
            
    except Exception as e:
        print(f"❌ Ошибка тестирования режимов: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    # Тестирование сохранения
    print("\n" + "=" * 80)
    print("💾 ТЕСТИРОВАНИЕ СОХРАНЕНИЯ НАСТРОЕК")
    print("=" * 80)
    
    try:
        # Изменяем некоторые значения
        print("\n✏️ Изменение значений...")
        old_gp_pop = settings_window.gp_pop_spin.value()
        old_risk = settings_window.risk_percentage_spinbox.value()
        
        settings_window.gp_pop_spin.setValue(old_gp_pop + 10)
        settings_window.risk_percentage_spinbox.setValue(old_risk + 0.1)
        
        print(f"   GP_POPULATION_SIZE: {old_gp_pop} → {settings_window.gp_pop_spin.value()}")
        print(f"   RISK_PERCENTAGE: {old_risk} → {settings_window.risk_percentage_spinbox.value()}")
        
        # Сохраняем настройки
        print("\n💾 Сохранение настроек...")
        settings_window.save_settings()
        print("✅ Настройки сохранены")
        
        # Проверяем файл настроек
        settings_path = Path("configs/settings.json")
        if settings_path.exists():
            with open(settings_path, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
            
            print(f"\n📊 Проверка сохранённых значений:")
            print(f"   GP_POPULATION_SIZE: {saved_config.get('GP_POPULATION_SIZE', 'НЕ НАЙДЕНО')}")
            print(f"   RISK_PERCENTAGE: {saved_config.get('RISK_PERCENTAGE', 'НЕ НАЙДЕНО')}")
            
            # Восстанавливаем значения
            settings_window.gp_pop_spin.setValue(old_gp_pop)
            settings_window.risk_percentage_spinbox.setValue(old_risk)
            settings_window.save_settings()
            print("\n↩️ Значения восстановлены")
        else:
            print("❌ Файл настроек не найден")
            all_passed = False
            
    except Exception as e:
        print(f"❌ Ошибка тестирования сохранения: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    # Закрытие
    print("\n" + "=" * 80)
    print("🏁 ЗАВЕРШЕНИЕ ТЕСТИРОВАНИЯ")
    print("=" * 80)
    
    settings_window.close()
    app.quit()
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    else:
        print("⚠️ НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ")
    print("=" * 80)
    
    return all_passed


if __name__ == "__main__":
    success = test_settings_window()
    sys.exit(0 if success else 1)
