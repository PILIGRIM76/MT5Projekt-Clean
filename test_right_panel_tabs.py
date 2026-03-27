"""
Тестовый файл для проверки всех вкладок правой панели главного окна.
Проверяет вкладки: Основной График, Центр Управления, Аналитика, Сканер Рынка, и другие.
"""

import sys
import os
import json
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from src.gui.control_center_widget import ControlCenterWidget
from src.core.config_loader import load_config


def test_right_panel_tabs():
    """Тестирование вкладок правой панели."""
    print("=" * 80)
    print("🧪 ТЕСТИРОВАНИЕ ВКЛАДОК ПРАВОЙ ПАНЕЛИ")
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
    
    # Список вкладок для проверки
    expected_tabs = [
        ("Основной График", 0),
        ("Центр Управления", 1),
        ("Аналитика", 2),
        ("Сканер Рынка", 3),
        ("Панель Оркестратора", 4),
        ("R&D Центр", 5),
        ("Центр Рефлексии", 6),
        ("Менеджер Моделей", 7),
        ("Граф Знаний", 8),
        ("Векторная БД (RAG)", 9),
        ("Анализ Сделки (XAI)", 10),
        ("Бэктестер", 11),
    ]
    
    print(f"\n📋 Ожидаемые вкладки ({len(expected_tabs)}):")
    for tab_name, tab_index in expected_tabs:
        print(f"   {tab_index}. {tab_name}")
    
    # Тестирование ControlCenterWidget
    print("\n" + "=" * 80)
    print("📑 ТЕСТИРОВАНИЕ ControlCenterWidget (Центр Управления)")
    print("=" * 80)
    
    try:
        # Создаём mock bridge
        class MockBridge:
            def __init__(self):
                self.log_message_added = SignalMock()
                self.status_updated = SignalMock()
                self.market_scan_updated = SignalMock()
                self.trading_signals_updated = SignalMock()
        
        class SignalMock:
            def connect(self, slot):
                pass
        
        mock_bridge = MockBridge()
        
        # Создаём ControlCenterWidget
        control_center = ControlCenterWidget(mock_bridge, config, None)
        print("✅ ControlCenterWidget создан")
        
        # Проверяем вкладки ControlCenterWidget
        if hasattr(control_center, 'tabs'):
            tab_count = control_center.tabs.count()
            print(f"📊 Количество вкладок в Центре Управления: {tab_count}")
            
            for i in range(tab_count):
                tab_name = control_center.tabs.tabText(i)
                print(f"   ✅ Вкладка {i}: {tab_name}")
        else:
            print("❌ tabs не найден в ControlCenterWidget")
            
        # Проверяем элементы управления
        print(f"\n🎛️ Элементы управления:")
        
        elements = [
            ("status_label", "Статус"),
            ("market_table", "Таблица сканера"),
            ("market_radio", "Переключатель Рыночные данные"),
            ("signals_radio", "Переключатель Торговые сигналы"),
            ("aggressiveness_slider", "Слайдер агрессивности"),
            ("aggressiveness_label", "Метка агрессивности"),
            ("daily_drawdown_spinbox", "Макс. дневная просадка"),
            ("regime_table", "Таблица режимов"),
            ("save_button", "Кнопка Сохранить"),
        ]
        
        for attr_name, description in elements:
            try:
                widget = getattr(control_center, attr_name, None)
                if widget:
                    widget_class = widget.__class__.__name__
                    print(f"   ✅ {description:40} [{widget_class}]")
                else:
                    print(f"   ❌ {description:40} [НЕ НАЙДЕНО]")
            except Exception as e:
                print(f"   ❌ {description:40} [ОШИБКА: {e}]")
        
        # Проверяем загрузку начальных настроек
        print(f"\n💾 Загрузка начальных настроек:")
        try:
            if hasattr(control_center, 'load_initial_settings'):
                control_center.load_initial_settings()
                print("   ✅ Начальные настройки загружены")
            else:
                print("   ❌ Метод load_initial_settings не найден")
        except Exception as e:
            print(f"   ❌ Ошибка загрузки настроек: {e}")
            
    except Exception as e:
        print(f"❌ Ошибка тестирования ControlCenterWidget: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Тестирование других виджетов (создание)
    print("\n" + "=" * 80)
    print("📑 ТЕСТИРОВАНИЕ ДРУГИХ ВКЛАДОК")
    print("=" * 80)
    
    # Проверяем, что виджеты могут быть созданы
    test_widgets = [
        ("ChartWidget", "Основной График", "src.gui.chart_widget", "ChartWidget"),
        ("AnalyticsWidget", "Аналитика", "src.gui.analytics_widget", "AnalyticsWidget"),
        ("ScannerWidget", "Сканер Рынка", "src.gui.scanner_widget", "ScannerWidget"),
        ("OrchestratorWidget", "Панель Оркестратора", "src.gui.orchestrator_widget", "OrchestratorWidget"),
        ("RnDCenterWidget", "R&D Центр", "src.gui.rd_center_widget", "RnDCenterWidget"),
        ("ReflexionWidget", "Центр Рефлексии", "src.gui.reflexion_widget", "ReflexionWidget"),
        ("ModelManagerWidget", "Менеджер Моделей", "src.gui.model_manager_widget", "ModelManagerWidget"),
        ("KnowledgeGraphWidget", "Граф Знаний", "src.gui.knowledge_graph_widget", "KnowledgeGraphWidget"),
        ("VectorDBWidget", "Векторная БД", "src.gui.vector_db_widget", "VectorDBWidget"),
        ("XAIWidget", "Анализ Сделки (XAI)", "src.gui.xai_widget", "XAIWidget"),
        ("BacktesterWidget", "Бэктестер", "src.gui.backtester_widget", "BacktesterWidget"),
    ]
    
    for widget_class, tab_name, module_name, class_name in test_widgets:
        try:
            # Пытаемся импортировать модуль
            module = __import__(module_name, fromlist=[class_name])
            widget_class = getattr(module, class_name)
            
            # Пробуем создать (без реальных данных)
            print(f"   ⏳ {tab_name:35} ...", end=" ")
            
            # Для некоторых виджетов нужны специальные параметры
            if class_name == "ChartWidget":
                # ChartWidget требует больше параметров
                print("⚠️ Требуется MT5")
            elif class_name == "ControlCenterWidget":
                # Уже протестирован
                print("✅ Уже протестирован")
            else:
                # Пробуем создать с минимальными параметрами
                try:
                    widget = widget_class()
                    print(f"✅ [{widget_class.__name__}]")
                except TypeError as te:
                    # Если нужны параметры
                    print(f"⚠️ Требуются параметры: {te}")
                except Exception as e:
                    print(f"❌ Ошибка: {e}")
                    
        except ImportError as ie:
            print(f"   ❌ {tab_name:35} [Модуль не найден: {module_name}]")
        except Exception as e:
            print(f"   ❌ {tab_name:35} [ОШИБКА: {e}]")
    
    # Закрытие
    print("\n" + "=" * 80)
    print("🏁 ЗАВЕРШЕНИЕ ТЕСТИРОВАНИЯ")
    print("=" * 80)
    
    control_center.close()
    app.quit()
    
    print("\n" + "=" * 80)
    print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 80)
    
    return True


if __name__ == "__main__":
    success = test_right_panel_tabs()
    sys.exit(0 if success else 1)
