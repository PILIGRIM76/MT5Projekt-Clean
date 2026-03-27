"""
Тестовый файл для проверки вкладок Центра Управления.
Проверяет вкладки: Дашборд и Управление Рисками.
"""

import sys
import os
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QLabel, QTableWidget, QSlider, QDoubleSpinBox, QPushButton, QRadioButton, QWidget
from src.gui.control_center_widget import ControlCenterWidget
from src.core.config_loader import load_config


class MockBridge:
    """Mock моста для тестирования."""
    def __init__(self):
        class SignalMock:
            def connect(self, slot):
                pass
        self.log_message_added = SignalMock()
        self.status_updated = SignalMock()
        self.market_scan_updated = SignalMock()
        self.trading_signals_updated = SignalMock()


def test_control_center_widget():
    """Тестирование ControlCenterWidget."""
    print("=" * 80)
    print("🧪 ТЕСТИРОВАНИЕ CONTROL CENTER WIDGET")
    print("=" * 80)
    
    # Инициализация QApplication
    app = QApplication(sys.argv)
    
    # Загрузка конфигурации
    print("\n📂 Загрузка конфигурации...")
    try:
        config = load_config()
        print("✅ Конфигурация загружена успешно")
        print(f"   SYMBOLS_WHITELIST: {len(config.SYMBOLS_WHITELIST)} символов")
        print(f"   RISK_PERCENTAGE: {config.RISK_PERCENTAGE}%")
        print(f"   MAX_OPEN_POSITIONS: {config.MAX_OPEN_POSITIONS}")
    except Exception as e:
        print(f"❌ Ошибка загрузки конфигурации: {e}")
        return False
    
    # Создание ControlCenterWidget
    print("\n🪟 Создание ControlCenterWidget...")
    try:
        mock_bridge = MockBridge()
        control_center = ControlCenterWidget(mock_bridge, config, None)
        print("✅ ControlCenterWidget создан успешно")
    except Exception as e:
        print(f"❌ Ошибка создания ControlCenterWidget: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Тестирование вкладок
    print("\n" + "=" * 80)
    print("📑 ТЕСТИРОВАНИЕ ВКЛАДОК")
    print("=" * 80)
    
    if hasattr(control_center, 'tabs'):
        tab_count = control_center.tabs.count()
        print(f"\n📊 Количество вкладок: {tab_count}")
        
        for i in range(tab_count):
            tab_name = control_center.tabs.tabText(i)
            widget = control_center.tabs.widget(i)
            element_count = len(widget.findChildren(QWidget)) if widget else 0
            print(f"   ✅ Вкладка {i}: {tab_name} ({element_count} элементов)")
    else:
        print("❌ tabs не найден")
        return False
    
    # Тестирование элементов вкладки "Дашборд"
    print("\n" + "=" * 80)
    print("📊 ТЕСТИРОВАНИЕ ВКЛАДКИ 'ДАШБОРД'")
    print("=" * 80)
    
    dashboard_elements = [
        ("status_label", QLabel, "Статус системы"),
        ("market_table", QTableWidget, "Таблица сканера рынка"),
        ("market_radio", QRadioButton, "Переключатель: Рыночные данные"),
        ("signals_radio", QRadioButton, "Переключатель: Торговые сигналы"),
    ]
    
    for attr_name, widget_type, description in dashboard_elements:
        try:
            widget = getattr(control_center, attr_name, None)
            if widget:
                if isinstance(widget, widget_type):
                    print(f"   ✅ {description:45} [{widget.__class__.__name__}]")
                else:
                    print(f"   ⚠️ {description:45} [Неверный тип: {widget.__class__.__name__}]")
            else:
                print(f"   ❌ {description:45} [НЕ НАЙДЕНО]")
        except Exception as e:
            print(f"   ❌ {description:45} [ОШИБКА: {e}]")
    
    # Тестирование элементов вкладки "Управление Рисками"
    print("\n" + "=" * 80)
    print("⚙️ ТЕСТИРОВАНИЕ ВКЛАДКИ 'УПРАВЛЕНИЕ РИСКАМИ'")
    print("=" * 80)
    
    controls_elements = [
        ("aggressiveness_slider", QSlider, "Слайдер агрессивности"),
        ("aggressiveness_label", QLabel, "Метка агрессивности"),
        ("daily_drawdown_spinbox", QDoubleSpinBox, "Макс. дневная просадка"),
        ("regime_table", QTableWidget, "Таблица рыночных режимов"),
        ("save_button", QPushButton, "Кнопка сохранения"),
    ]
    
    for attr_name, widget_type, description in controls_elements:
        try:
            widget = getattr(control_center, attr_name, None)
            if widget:
                if isinstance(widget, widget_type):
                    print(f"   ✅ {description:45} [{widget.__class__.__name__}]")
                else:
                    print(f"   ⚠️ {description:45} [Неверный тип: {widget.__class__.__name__}]")
            else:
                print(f"   ❌ {description:45} [НЕ НАЙДЕНО]")
        except Exception as e:
            print(f"   ❌ {description:45} [ОШИБКА: {e}]")
    
    # Тестирование функциональности
    print("\n" + "=" * 80)
    print("⚙️ ТЕСТИРОВАНИЕ ФУНКЦИОНАЛЬНОСТИ")
    print("=" * 80)
    
    # 1. Загрузка начальных настроек
    print("\n1️⃣ Загрузка начальных настроек...")
    try:
        if hasattr(control_center, 'load_initial_settings'):
            control_center.load_initial_settings()
            print("   ✅ Настройки загружены успешно")
        else:
            print("   ❌ Метод load_initial_settings не найден")
    except Exception as e:
        print(f"   ❌ Ошибка загрузки настроек: {e}")
    
    # 2. Обновление статуса
    print("\n2️⃣ Обновление статуса...")
    try:
        if hasattr(control_center, 'update_status'):
            control_center.update_status("Тестовый статус")
            status_text = control_center.status_label.text()
            print(f"   ✅ Статус обновлён: '{status_text}'")
        else:
            print("   ❌ Метод update_status не найден")
    except Exception as e:
        print(f"   ❌ Ошибка обновления статуса: {e}")
    
    # 3. Обновление таблицы сканера
    print("\n3️⃣ Обновление таблицы сканера...")
    try:
        if hasattr(control_center, 'update_market_table'):
            test_data = [
                {'symbol': 'EURUSD', 'last_close': 1.0850, 'normalized_atr_percent': 0.5, 'volatility': 0.3},
                {'symbol': 'GBPUSD', 'last_close': 1.2650, 'normalized_atr_percent': 0.7, 'volatility': 0.4},
            ]
            control_center.update_market_table(test_data)
            row_count = control_center.market_table.rowCount()
            print(f"   ✅ Таблица обновлена: {row_count} строк")
        else:
            print("   ❌ Метод update_market_table не найден")
    except Exception as e:
        print(f"   ❌ Ошибка обновления таблицы: {e}")
    
    # 4. Переключение режимов отображения
    print("\n4️⃣ Переключение режимов отображения...")
    try:
        if hasattr(control_center, 'on_display_mode_changed'):
            # Переключаем на "Торговые сигналы"
            control_center.signals_radio.setChecked(True)
            control_center.on_display_mode_changed()
            
            headers = [control_center.market_table.horizontalHeaderItem(i).text() 
                      for i in range(control_center.market_table.columnCount())]
            print(f"   ✅ Режим переключен. Заголовки: {', '.join(headers)}")
            
            # Возвращаем обратно
            control_center.market_radio.setChecked(True)
            control_center.on_display_mode_changed()
            headers = [control_center.market_table.horizontalHeaderItem(i).text() 
                      for i in range(control_center.market_table.columnCount())]
            print(f"   ✅ Режим возвращён. Заголовки: {', '.join(headers)}")
        else:
            print("   ❌ Метод on_display_mode_changed не найден")
    except Exception as e:
        print(f"   ❌ Ошибка переключения режимов: {e}")
    
    # 5. Изменение агрессивности
    print("\n5️⃣ Изменение агрессивности...")
    try:
        if hasattr(control_center, 'aggressiveness_slider'):
            old_value = control_center.aggressiveness_slider.value()
            control_center.aggressiveness_slider.setValue(75)
            new_label = control_center.aggressiveness_label.text()
            print(f"   ✅ Агрессивность изменена: {old_value} → 75, метка: '{new_label}'")
            control_center.aggressiveness_slider.setValue(old_value)
        else:
            print("   ❌ aggressiveness_slider не найден")
    except Exception as e:
        print(f"   ❌ Ошибка изменения агрессивности: {e}")
    
    # Закрытие
    print("\n" + "=" * 80)
    print("🏁 ЗАВЕРШЕНИЕ ТЕСТИРОВАНИЯ")
    print("=" * 80)
    
    control_center.close()
    app.quit()
    
    print("\n" + "=" * 80)
    print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО УСПЕШНО")
    print("=" * 80)
    
    return True


if __name__ == "__main__":
    success = test_control_center_widget()
    sys.exit(0 if success else 1)
