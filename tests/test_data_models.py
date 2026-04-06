# -*- coding: utf-8 -*-
"""
Тесты для Pydantic data models — валидация данных.

По аудиту: data_models уже имеют Pydantic валидацию с extra="forbid",
но нет тестов.
"""

import pytest
from src.data_models import TradeSignal, SignalType


class TestTradeSignal:
    """Тесты валидации TradeSignal."""

    def test_valid_buy_signal(self):
        """Валидный BUY сигнал."""
        signal = TradeSignal(
            symbol="EURUSD",
            type=SignalType.BUY,
            confidence=0.85,
            stop_loss=1.0800,
            take_profit=1.0950,
        )
        assert signal.symbol == "EURUSD"
        # use_enum_values=True конвертирует enum в строку
        assert signal.type in [SignalType.BUY, "BUY"]
        assert signal.stop_loss == 1.0800

    def test_valid_sell_signal(self):
        """Валидный SELL сигнал."""
        signal = TradeSignal(
            symbol="GBPUSD",
            type=SignalType.SELL,
            confidence=0.75,
            stop_loss=1.2550,
            take_profit=1.2700,  # Для модели TP всегда > SL
        )
        assert signal.type in [SignalType.SELL, "SELL"]

    def test_tp_must_be_gt_sl_for_buy(self):
        """Модель требует TP > SL для обоих направлений."""
        with pytest.raises(Exception):
            TradeSignal(
                symbol="EURUSD",
                type=SignalType.BUY,
                confidence=0.8,
                stop_loss=1.0800,
                take_profit=1.0750,  # TP < SL — ошибка
            )

    def test_confidence_minimum_threshold(self):
        """Confidence должен быть >= 0.3."""
        with pytest.raises(Exception):
            TradeSignal(
                symbol="EURUSD",
                type=SignalType.BUY,
                confidence=0.1,  # Слишком низкая
                stop_loss=1.0800,
                take_profit=1.0950,
            )

    def test_valid_symbol_format(self):
        """Символ должен быть в правильном формате."""
        signal = TradeSignal(
            symbol="EURUSD",
            type=SignalType.BUY,
            confidence=0.8,
            stop_loss=1.0800,
            take_profit=1.0950,
        )
        assert signal.symbol == "EURUSD"

    def test_special_symbols_allowed(self):
        """Специальные символы разрешены."""
        for sym in ["BITCOIN", "XAUUSD", "XAGUSD", "BTCUSD"]:
            signal = TradeSignal(
                symbol=sym,
                type=SignalType.BUY,
                confidence=0.8,
                stop_loss=100.0,
                take_profit=200.0,
            )
            assert signal.symbol == sym

    def test_extra_fields_forbidden(self):
        """Лишние поля запрещены (extra='forbid')."""
        with pytest.raises(Exception):
            TradeSignal(
                symbol="EURUSD",
                type=SignalType.BUY,
                confidence=0.8,
                stop_loss=1.0800,
                take_profit=1.0950,
                extra_field="should_fail",
            )

    def test_missing_required_fields(self):
        """Отсутствующие обязательные поля вызывают ошибку."""
        with pytest.raises(Exception):
            TradeSignal(symbol="EURUSD")  # Нет type, confidence

    def test_negative_price_rejected(self):
        """Отрицательная цена отклоняется."""
        with pytest.raises(Exception):
            TradeSignal(
                symbol="EURUSD",
                type=SignalType.BUY,
                confidence=0.8,
                stop_loss=-1.0,
                take_profit=-0.5,
            )

    def test_predicted_price_optional(self):
        """Predicted price — опциональное поле."""
        signal = TradeSignal(
            symbol="EURUSD",
            type=SignalType.BUY,
            confidence=0.8,
            stop_loss=1.0800,
            take_profit=1.0950,
            predicted_price=1.0900,
        )
        assert signal.predicted_price == 1.0900

    def test_strategy_name_optional(self):
        """Strategy name — опциональное поле."""
        signal = TradeSignal(
            symbol="EURUSD",
            type=SignalType.BUY,
            confidence=0.8,
            stop_loss=1.0800,
            take_profit=1.0950,
        )
        assert signal.strategy_name is None

    def test_confidence_bounds(self):
        """Confidence должен быть в диапазоне [0.3, 1.0]."""
        # Граница 1.0 — валидна
        signal = TradeSignal(
            symbol="EURUSD",
            type=SignalType.BUY,
            confidence=1.0,
            stop_loss=1.0800,
            take_profit=1.0950,
        )
        assert signal.confidence == 1.0

        # Выше 1.0 — ошибка
        with pytest.raises(Exception):
            TradeSignal(
                symbol="EURUSD",
                type=SignalType.BUY,
                confidence=1.5,
                stop_loss=1.0800,
                take_profit=1.0950,
            )

    def test_empty_symbol_rejected(self):
        """Пустой символ отклоняется."""
        with pytest.raises(Exception):
            TradeSignal(
                symbol="",
                type=SignalType.BUY,
                confidence=0.8,
                stop_loss=1.0800,
                take_profit=1.0950,
            )

    def test_invalid_symbol_format_rejected(self):
        """Неверный формат символа отклоняется."""
        with pytest.raises(Exception):
            TradeSignal(
                symbol="eurusd",  # lowercase
                type=SignalType.BUY,
                confidence=0.8,
                stop_loss=1.0800,
                take_profit=1.0950,
            )
