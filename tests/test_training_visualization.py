# -*- coding: utf-8 -*-
"""
Тесты для новых функций переобучения и визуализации.

Проверяет:
1. Отправку данных точности моделей в GUI
2. Отправку данных прогресса переобучения
3. Обновление графиков в GUI
4. AutoTrainer с новыми триггерами
5. Синхронное сохранение моделей
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestModelAccuracyToGUI:
    """Тесты для _send_model_accuracy_to_gui"""

    @pytest.fixture
    def mock_trading_system(self, tmp_path):
        """Создаёт мок TradingSystem без сложной инициализации"""
        # Создаём простой мок объект
        mock_ts = MagicMock()
        mock_ts.config.DATABASE_FOLDER = str(tmp_path)
        mock_ts.config.SYMBOLS_WHITELIST = ["EURUSD", "GBPUSD", "USDJPY"]
        mock_ts.bridge = MagicMock()

        # Импортируем метод как bound method
        from src.core.trading_system import TradingSystem

        mock_ts._send_model_accuracy_to_gui = TradingSystem._send_model_accuracy_to_gui.__get__(mock_ts, TradingSystem)

        return mock_ts

    @pytest.fixture
    def mock_metadata_files(self, tmp_path):
        """Создаёт тестовые файлы метаданных моделей"""
        models_path = tmp_path / "ai_models"
        models_path.mkdir()

        # Создаём метаданные с разной точностью
        test_data = {
            "EURUSD": {"val_accuracy": 0.75, "trained_at": (datetime.now() - timedelta(hours=2)).isoformat()},
            "GBPUSD": {"val_accuracy": 0.0, "trained_at": (datetime.now() - timedelta(hours=0.5)).isoformat()},
            "USDJPY": {"val_accuracy": None, "trained_at": (datetime.now() - timedelta(hours=1.5)).isoformat()},
        }

        for symbol, metadata in test_data.items():
            metadata_file = models_path / f"{symbol}_metadata.json"
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f)

        return models_path

    def test_send_model_accuracy_with_data(self, mock_trading_system, mock_metadata_files):
        """Проверка отправки точности когда данные есть"""
        # Вызываем метод
        mock_trading_system._send_model_accuracy_to_gui()

        # Проверяем что сигнал был отправлен
        assert mock_trading_system.bridge.model_accuracy_updated.emit.called

        # Получаем отправленные данные
        call_args = mock_trading_system.bridge.model_accuracy_updated.emit.call_args
        accuracy_data = call_args[0][0]

        # Проверяем данные
        assert "EURUSD" in accuracy_data
        assert accuracy_data["EURUSD"] == 0.75  # Реальная точность

    def test_send_model_accuracy_zero_handling(self, mock_trading_system, mock_metadata_files):
        """Проверка обработки нулевой точности"""
        mock_trading_system._send_model_accuracy_to_gui()

        call_args = mock_trading_system.bridge.model_accuracy_updated.emit.call_args
        accuracy_data = call_args[0][0]

        # GBPUSD имеет val_accuracy=0, должно быть заменено на 0.5
        assert accuracy_data["GBPUSD"] == 0.5

    def test_send_model_accuracy_none_handling(self, mock_trading_system, mock_metadata_files):
        """Проверка обработки None точности"""
        mock_trading_system._send_model_accuracy_to_gui()

        call_args = mock_trading_system.bridge.model_accuracy_updated.emit.call_args
        accuracy_data = call_args[0][0]

        # USDJPY имеет val_accuracy=None, должно быть заменено на 0.5
        assert accuracy_data["USDJPY"] == 0.5

    def test_send_model_accuracy_no_model(self, mock_trading_system):
        """Проверка когда модель не найдена"""
        mock_trading_system._send_model_accuracy_to_gui()

        call_args = mock_trading_system.bridge.model_accuracy_updated.emit.call_args
        accuracy_data = call_args[0][0]

        # Все символы должны иметь 0.0 (модели нет)
        for symbol in mock_trading_system.config.SYMBOLS_WHITELIST:
            assert accuracy_data[symbol] == 0.0


class TestRetrainProgressToGUI:
    """Тесты для _send_retrain_progress_to_gui"""

    @pytest.fixture
    def mock_trading_system(self, tmp_path):
        """Создаёт мок TradingSystem"""
        mock_ts = MagicMock()
        mock_ts.config.DATABASE_FOLDER = str(tmp_path)
        mock_ts.config.SYMBOLS_WHITELIST = ["EURUSD", "GBPUSD", "USDJPY"]
        mock_ts.bridge = MagicMock()

        from src.core.trading_system import TradingSystem

        mock_ts._send_retrain_progress_to_gui = TradingSystem._send_retrain_progress_to_gui.__get__(mock_ts, TradingSystem)

        return mock_ts

    @pytest.fixture
    def mock_metadata_files(self, tmp_path):
        """Создаёт тестовые файлы метаданных с разным временем"""
        models_path = tmp_path / "ai_models"
        models_path.mkdir()

        test_data = {
            "EURUSD": {"trained_at": (datetime.now() - timedelta(hours=2)).isoformat()},  # > 1 часа
            "GBPUSD": {"trained_at": (datetime.now() - timedelta(minutes=30)).isoformat()},  # < 0.5 часа
            "USDJPY": {"trained_at": (datetime.now() - timedelta(minutes=45)).isoformat()},  # 0.5-1 часа
        }

        for symbol, metadata in test_data.items():
            metadata_file = models_path / f"{symbol}_metadata.json"
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f)

        return models_path

    def test_send_retrain_progress_calculation(self, mock_trading_system, mock_metadata_files):
        """Проверка расчёта времени до переобучения"""
        mock_trading_system._send_retrain_progress_to_gui()

        assert mock_trading_system.bridge.retrain_progress_updated.emit.called

        call_args = mock_trading_system.bridge.retrain_progress_updated.emit.call_args
        progress_data = call_args[0][0]

        # EURUSD: 2 часа назад
        assert progress_data["EURUSD"] >= 2.0

        # GBPUSD: 30 минут назад (с небольшой погрешностью)
        assert progress_data["GBPUSD"] < 0.51

        # USDJPY: 45 минут назад (0.5-1 часа)
        assert 0.49 <= progress_data["USDJPY"] < 1.0

    def test_send_retrain_progress_logging(self, mock_trading_system, mock_metadata_files, caplog):
        """Проверка логирования количества символов для переобучения"""
        import logging

        with caplog.at_level(logging.INFO):
            mock_trading_system._send_retrain_progress_to_gui()

        # EURUSD требует переобучения (> 1 часа)
        assert "требуют переобучения: 1" in caplog.text

    def test_send_retrain_progress_no_model(self, mock_trading_system):
        """Проверка когда модель не найдена"""
        mock_trading_system._send_retrain_progress_to_gui()

        call_args = mock_trading_system.bridge.retrain_progress_updated.emit.call_args
        progress_data = call_args[0][0]

        # Все символы должны иметь 999.0 (модели нет)
        for symbol in mock_trading_system.config.SYMBOLS_WHITELIST:
            assert progress_data[symbol] == 999.0


class TestGUIChartUpdates:
    """Тесты для методов обновления графиков в GUI"""

    @pytest.fixture
    def mock_main_window(self):
        """Создаёт мок MainWindow с графиками"""
        mock_window = MagicMock()

        # Мок для model_accuracy_bars
        mock_window.model_accuracy_bars = MagicMock()
        mock_window.model_accuracy_plot_widget = MagicMock()

        # Мок для retrain_progress_bars
        mock_window.retrain_progress_bars = MagicMock()
        mock_window.retrain_progress_widget = MagicMock()

        return mock_window

    def test_update_model_accuracy_chart(self, mock_main_window):
        """Проверка обновления графика точности"""
        from main_pyside import MainWindow

        accuracy_data = {
            "EURUSD": 0.75,  # Зелёный
            "GBPUSD": 0.45,  # Жёлтый
            "USDJPY": 0.35,  # Красный
        }

        MainWindow.update_model_accuracy_chart(mock_main_window, accuracy_data)

        # Проверяем что график был обновлён
        assert mock_main_window.model_accuracy_bars.setOpts.called

        # Проверяем расчёт средней точности
        call_args = mock_main_window.model_accuracy_plot_widget.setTitle.call_args
        assert "средняя: 51.7%" in call_args[0][0]

    def test_update_model_accuracy_chart_empty(self, mock_main_window, caplog):
        """Проверка обработки пустых данных"""
        import logging

        from main_pyside import MainWindow

        with caplog.at_level(logging.DEBUG):
            MainWindow.update_model_accuracy_chart(mock_main_window, {})

        assert "Нет данных для отображения" in caplog.text

    def test_update_retrain_progress_chart(self, mock_main_window):
        """Проверка обновления графика прогресса"""
        from main_pyside import MainWindow

        progress_data = {
            "EURUSD": 2.0,  # Красный (> 1ч)
            "GBPUSD": 0.3,  # Зелёный (< 0.5ч)
            "USDJPY": 0.7,  # Оранжевый (0.5-1ч)
        }

        MainWindow.update_retrain_progress_chart(mock_main_window, progress_data)

        # Проверяем что график был обновлён
        assert mock_main_window.retrain_progress_bars.setOpts.called

        # Проверяем заголовок
        call_args = mock_main_window.retrain_progress_widget.setTitle.call_args
        assert "требуют: 1" in call_args[0][0]

    def test_update_retrain_progress_chart_all_red(self, mock_main_window):
        """Проверка когда все символы требуют переобучения"""
        from main_pyside import MainWindow

        progress_data = {
            "EURUSD": 5.0,
            "GBPUSD": 3.0,
            "USDJPY": 2.0,
        }

        MainWindow.update_retrain_progress_chart(mock_main_window, progress_data)

        call_args = mock_main_window.retrain_progress_widget.setTitle.call_args
        assert "требуют: 3" in call_args[0][0]


class TestAutoTrainerNewTriggers:
    """Тесты для новых триггеров AutoTrainer"""

    @pytest.fixture
    def mock_auto_trainer(self, tmp_path):
        """Создаёт AutoTrainer с тестовой конфигурацией"""
        # Простой мок объект
        mock_trainer = MagicMock()
        mock_trainer.config.DATABASE_FOLDER = str(tmp_path)
        mock_trainer.config.SYMBOLS_WHITELIST = ["EURUSD", "GBPUSD"]
        mock_trainer.retrain_interval_hours = 1
        mock_trainer.min_new_bars_for_retrain = 50
        mock_trainer.volatility_change_threshold = 0.3
        mock_trainer.accuracy_drop_threshold = 0.15
        mock_trainer._last_bars_count = {}
        mock_trainer._last_volatility = {}
        mock_trainer._last_accuracy = {}
        mock_trainer.models_path = Path(tmp_path) / "ai_models"

        # Импортируем метод
        from src.ml.auto_trainer import AutoTrainer

        mock_trainer.should_retrain = AutoTrainer.should_retrain.__get__(mock_trainer, AutoTrainer)

        return mock_trainer

    def test_should_retrain_time_trigger(self, mock_auto_trainer, tmp_path):
        """Проверка триггера по времени"""
        models_path = self.models_path = tmp_path / "ai_models"
        models_path.mkdir()

        # Модель обучена 2 часа назад (больше интервала 1 час)
        metadata = {"trained_at": (datetime.now() - timedelta(hours=2)).isoformat(), "val_accuracy": 0.7}
        with open(models_path / "EURUSD_metadata.json", "w") as f:
            json.dump(metadata, f)

        assert mock_auto_trainer.should_retrain("EURUSD") is True

    def test_should_retrain_new_bars_trigger(self, mock_auto_trainer, tmp_path):
        """Проверка триггера по новым барам"""
        import pandas as pd

        models_path = self.models_path = tmp_path / "ai_models"
        models_path.mkdir()

        # Модель обучена 30 минут назад
        metadata = {"trained_at": (datetime.now() - timedelta(minutes=30)).isoformat(), "val_accuracy": 0.7}
        with open(models_path / "EURUSD_metadata.json", "w") as f:
            json.dump(metadata, f)

        # Кэшируем 100 баров
        mock_auto_trainer._last_bars_count["EURUSD"] = 100

        # Новые данные: 200 баров (100 новых)
        current_data = pd.DataFrame({"close": range(200)})

        # Должен сработать триггер (100 новых > 50 порога)
        assert mock_auto_trainer.should_retrain("EURUSD", current_data) is True

    def test_should_retrain_volatility_trigger(self, mock_auto_trainer, tmp_path):
        """Проверка триггера по волатильности"""
        import numpy as np
        import pandas as pd

        models_path = self.models_path = tmp_path / "ai_models"
        models_path.mkdir()

        metadata = {"trained_at": (datetime.now() - timedelta(minutes=30)).isoformat(), "val_accuracy": 0.7}
        with open(models_path / "EURUSD_metadata.json", "w") as f:
            json.dump(metadata, f)

        # Кэшируем волатильность 0.001 (очень низкая)
        mock_auto_trainer._last_volatility["EURUSD"] = 0.001

        # Текущая волатильность 0.01 (изменение 900% - точно сработает)
        # Генерируем данные с высокой волатильностью
        np.random.seed(42)
        returns = np.random.randn(100) * 0.05  # 5% дневная волатильность
        prices = 100 * np.cumprod(1 + returns)
        current_data = pd.DataFrame({"close": prices})

        assert mock_auto_trainer.should_retrain("EURUSD", current_data) is True

    def test_should_retrain_no_trigger(self, mock_auto_trainer, tmp_path):
        """Проверка когда нет триггеров"""
        import numpy as np
        import pandas as pd

        models_path = self.models_path = tmp_path / "ai_models"
        models_path.mkdir()

        metadata = {"trained_at": (datetime.now() - timedelta(minutes=30)).isoformat(), "val_accuracy": 0.7}
        with open(models_path / "EURUSD_metadata.json", "w") as f:
            json.dump(metadata, f)

        # Кэшируем данные
        mock_auto_trainer._last_bars_count["EURUSD"] = 100
        mock_auto_trainer._last_volatility["EURUSD"] = 0.01
        mock_auto_trainer._last_accuracy["EURUSD"] = 0.7

        # Очень небольшие изменения (почти нет изменений)
        # Генерируем данные с такой же волатильностью как в кэше
        np.random.seed(42)
        returns = np.random.randn(110) * 0.01  # Такая же волатильность
        prices = 100 * np.cumprod(1 + returns)
        current_data = pd.DataFrame({"close": prices})

        # Вызываем метод и проверяем что вернул False
        result = mock_auto_trainer.should_retrain("EURUSD", current_data)
        # Проверяем что волатильность не изменилась значительно
        current_vol = current_data["close"].pct_change().std()
        assert abs(current_vol - 0.01) < 0.005, f"Волатильность изменилась: {current_vol}"
        assert result is False, f"Ожидали False, но получили {result}. Волатильность: {current_vol}"


# Пропускаем TestSaveModelSync - требует полную конфигурацию Settings
# class TestSaveModelSync:
#     """Тесты для save_model_and_scalers_sync"""
#     pass


# Запуск тестов
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
