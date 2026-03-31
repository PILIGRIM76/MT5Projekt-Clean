# tests/unit/test_data_models.py
"""
Unit тесты для моделей данных.

Проверяет:
- Валидацию Pydantic моделей
- Обработку ошибок валидации
- Корректность значений по умолчанию
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.data_models import ClosePositionRequest, NewsItemPydantic, OrderType, SignalType, TradeRequest, TradeSignal


class TestTradeSignal:
    """Тесты для TradeSignal."""

    def test_create_valid_signal(self):
        """Создание валидного сигнала."""
        signal = TradeSignal(type=SignalType.BUY, confidence=0.75, symbol="EURUSD")

        # use_enum_values=True конвертирует Enum в строку
        assert signal.type == "BUY"  # или SignalType.BUY.value
        assert signal.confidence == 0.75
        assert signal.symbol == "EURUSD"

    def test_symbol_validation_six_letters(self):
        """Валидация символа - 6 букв."""
        signal = TradeSignal(type=SignalType.BUY, confidence=0.75, symbol="GBPUSD")
        assert signal.symbol == "GBPUSD"

    def test_symbol_validation_special(self):
        """Валидация специальных символов."""
        for symbol in ["BITCOIN", "GOLD", "SILVER", "XAUUSD", "XAGUSD"]:
            signal = TradeSignal(type=SignalType.BUY, confidence=0.75, symbol=symbol)
            assert signal.symbol == symbol.upper()

    def test_symbol_validation_invalid(self):
        """Валидация невалидного символа."""
        with pytest.raises(ValidationError) as exc_info:
            TradeSignal(type=SignalType.BUY, confidence=0.75, symbol="INVALID_SYMBOL")
        assert "Неверный формат символа" in str(exc_info.value)

    def test_confidence_validation_low(self):
        """Валидация низкой уверенности."""
        with pytest.raises(ValidationError) as exc_info:
            TradeSignal(type=SignalType.BUY, confidence=0.2, symbol="EURUSD")  # Ниже порога 0.3
        assert "Уверенность сигнала слишком низкая" in str(exc_info.value)

    def test_confidence_validation_range(self):
        """Валидация диапазона уверенности."""
        with pytest.raises(ValidationError):
            TradeSignal(type=SignalType.BUY, confidence=1.5, symbol="EURUSD")  # Выше 1.0

    def test_tp_sl_validation(self):
        """Валидация TP > SL."""
        signal = TradeSignal(type=SignalType.BUY, confidence=0.75, symbol="EURUSD", stop_loss=1.0950, take_profit=1.1050)
        assert signal.stop_loss == 1.0950
        assert signal.take_profit == 1.1050

    def test_tp_less_than_sl(self):
        """TP меньше SL - ошибка."""
        with pytest.raises(ValidationError) as exc_info:
            TradeSignal(
                type=SignalType.BUY, confidence=0.75, symbol="EURUSD", stop_loss=1.0950, take_profit=1.0940  # Меньше SL
            )
        assert "Take-Profit" in str(exc_info.value)


class TestTradeRequest:
    """Тесты для TradeRequest."""

    def test_create_valid_request(self):
        """Создание валидного запроса."""
        request = TradeRequest(symbol="EURUSD", lot=0.5, order_type=OrderType.BUY)

        assert request.symbol == "EURUSD"
        assert request.lot == 0.5
        assert request.order_type == "BUY"

    def test_symbol_uppercase_conversion(self):
        """Конверсия символа в верхний регистр."""
        request = TradeRequest(symbol="eurusd", lot=0.5, order_type=OrderType.BUY)
        assert request.symbol == "EURUSD"

    def test_lot_validation_max(self):
        """Валидация максимального лота."""
        with pytest.raises(ValidationError) as exc_info:
            TradeRequest(symbol="EURUSD", lot=60.0, order_type=OrderType.BUY)  # Больше 50
        assert "Объем сделки слишком большой" in str(exc_info.value)

    def test_lot_validation_zero(self):
        """Валидация нулевого лота."""
        with pytest.raises(ValidationError):
            TradeRequest(symbol="EURUSD", lot=0.0, order_type=OrderType.BUY)

    def test_order_type_validation(self):
        """Валидация типа ордера."""
        with pytest.raises(ValidationError):
            TradeRequest(symbol="EURUSD", lot=0.5, order_type="INVALID")


class TestClosePositionRequest:
    """Тесты для ClosePositionRequest."""

    def test_create_valid_request(self):
        """Создание валидного запроса."""
        request = ClosePositionRequest(ticket=12345)

        assert request.ticket == 12345
        assert request.partial_lot is None

    def test_partial_lot_valid(self):
        """Валидный partial_lot."""
        request = ClosePositionRequest(ticket=12345, partial_lot=0.05)
        assert request.partial_lot == 0.05

    def test_partial_lot_too_large(self):
        """Слишком большой partial_lot."""
        with pytest.raises(ValidationError) as exc_info:
            ClosePositionRequest(ticket=12345, partial_lot=60.0)
        assert "Объем частичного закрытия слишком большой" in str(exc_info.value)

    def test_ticket_validation(self):
        """Валидация тикета."""
        with pytest.raises(ValidationError):
            ClosePositionRequest(ticket=0)


class TestNewsItemPydantic:
    """Тесты для NewsItemPydantic."""

    def test_create_valid_news(self):
        """Создание валидной новости."""
        news = NewsItemPydantic(
            source="TestSource",
            text="Это тестовая новость длиной больше 10 символов",
            timestamp=datetime.now(),
            asset="EURUSD",
        )

        assert news.source == "TestSource"
        assert news.asset == "EURUSD"

    def test_text_validation_short(self):
        """Валидация короткого текста."""
        with pytest.raises(ValidationError) as exc_info:
            NewsItemPydantic(source="TestSource", text="Коротко", timestamp=datetime.now())
        assert "Текст новости слишком короткий" in str(exc_info.value)

    def test_sentiment_validation(self):
        """Валидация сентимента."""
        # Валидные значения
        for sentiment in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            news = NewsItemPydantic(
                source="TestSource", text="Тестовая новость достаточной длины", timestamp=datetime.now(), sentiment=sentiment
            )
            assert news.sentiment == sentiment

        # Невалидное значение
        with pytest.raises(ValidationError):
            NewsItemPydantic(source="TestSource", text="Тестовая новость", timestamp=datetime.now(), sentiment=1.5)
