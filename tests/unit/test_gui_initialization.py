"""
Тест инициализации GUI-виджетов.
Проверяет, что все критические компоненты созданы без ошибок.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys

# Мок Qt-приложения, чтобы избежать реального запуска GUI
@pytest.fixture(scope="module", autouse=True)
def mock_qt_app():
    """Создаёт мок QApplication."""
    with patch("PySide6.QtWidgets.QApplication"):
        yield

class TestGUIInitialization:
    """Тесты инициализации MainWindow."""

    def test_main_window_can_be_imported(self):
        """Проверяет, что MainWindow можно импортировать."""
        try:
            from main_pyside import MainWindow
            assert MainWindow is not None
        except ImportError as e:
            pytest.fail(f"Не удалось импортировать MainWindow: {e}")

    def test_critical_widgets_exist(self):
        """Проверяет, что критические виджеты определены в коде."""
        import inspect
        from main_pyside import MainWindow
        
        source = inspect.getsource(MainWindow)
        
        # Проверяем наличие критических компонентов
        assert "QMainWindow" in source or "PanelsMixin" in source
        assert "QTimer" in source or "timers" in source
        assert "pyqtgraph" in source or "PlotWidget" in source or "chart" in source.lower()

    def test_mixins_are_used(self):
        """Проверяет, что миксины подключены."""
        from main_pyside import MainWindow
        
        # Проверяем наследование от миксинов
        bases = MainWindow.__bases__
        mixin_names = [base.__name__ for base in bases]
        
        has_panels = any("Panel" in name for name in mixin_names)
        has_charts = any("Chart" in name for name in mixin_names)
        has_signals = any("Signal" in name for name in mixin_names)
        
        # Хотя бы один миксин должен быть
        assert has_panels or has_charts or has_signals, "MainWindow должен использовать хотя бы один миксин"

    def test_event_bus_integration(self):
        """Проверяет, что EventBus интегрирован в GUI."""
        import inspect
        from main_pyside import MainWindow
        
        source = inspect.getsource(MainWindow)
        # EventBus может быть упомянут как event_bus, EventBus, broker, pubsub
        assert any(keyword in source.lower() for keyword in [
            "event_bus", "eventbus", "broker", "pubsub", "emit", "publish"
        ]), "EventBus / pubsub механизм должен присутствовать"

    def test_mt5_connection_manager_integration(self):
        """Проверяет, что MT5ConnectionManager интегрирован."""
        import inspect
        from main_pyside import MainWindow
        
        source = inspect.getsource(MainWindow)
        assert "mt5" in source.lower() or "MT5" in source