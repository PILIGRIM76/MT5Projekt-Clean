# tests/unit/test_position_sizer.py
"""
Тесты для Position Sizing Optimizer.

Проверяет:
- Все методы расчёта (Fixed, Kelly, Volatility, Risk Parity)
- Валидацию результатов
- Сравнение методов
- Статистику
"""

import pytest
from unittest.mock import MagicMock
import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.risk.position_sizer import (
    PositionSizer,
    SizingMethod,
    FixedFractionalSizer,
    KellyCriterionSizer,
    VolatilityAdjustedSizer,
    RiskParitySizer,
    PositionSizeResult
)
from src.data_models import SignalType
from src.core.config_models import Settings


@pytest.fixture
def sample_config():
    """Фикстура с тестовой конфигурацией."""
    config_dict = {
        'position_sizing': {
            'method': 'fixed_fractional',
            'fixed_risk_percent': 0.01,
            'kelly_use_half': True,
            'kelly_max_percent': 0.25,
            'volatility_atr_multiplier': 2.0,
            'risk_parity_total_risk': 0.05,
            'risk_parity_max_positions': 5,
            'min_lot': 0.01,
            'max_lot': 100.0,
            'lot_step': 0.01
        }
    }
    return Settings(**config_dict)


class TestFixedFractionalSizer:
    """Тесты Fixed Fractional метода."""
    
    def test_basic_calculation(self):
        """Тест базового расчёта."""
        sizer = FixedFractionalSizer(risk_percent=0.01)
        
        result = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950
        )
        
        # Риск 1% от 100000 = 1000 USD
        assert result.risk_usd == 1000.0
        assert result.risk_percent == 1.0
        
        # Стоп-лосс 50 pips
        assert result.stop_loss_pips == 50.0
        
        # Lot = 1000 / (50 * 10) = 2.0
        assert result.lot == 2.0
        assert result.method == SizingMethod.FIXED_FRACTIONAL
    
    def test_zero_stop_loss(self):
        """Тест с нулевым стоп-лоссом."""
        sizer = FixedFractionalSizer(risk_percent=0.01)
        
        result = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.1000  # Тот же уровень
        )
        
        assert result.lot == 0.0
        assert result.validation_passed is False


class TestKellyCriterionSizer:
    """Тесты Kelly Criterion."""
    
    def test_kelly_with_stats(self):
        """Тест с статистикой стратегии."""
        sizer = KellyCriterionSizer(use_half_kelly=True)
        
        strategy_stats = {
            'win_rate': 0.60,  # 60% побед
            'profit_factor': 2.0  # Прибыль/Убыток = 2
        }
        
        result = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950,
            strategy_stats=strategy_stats
        )
        
        # Kelly = 0.60 - (1-0.60)/2.0 = 0.60 - 0.20 = 0.40
        # Half-Kelly = 0.20
        assert result.risk_percent == pytest.approx(20.0, rel=0.1)
        assert result.method == SizingMethod.HALF_KELLY
    
    def test_kelly_no_stats(self):
        """Тест без статистики (значения по умолчанию)."""
        sizer = KellyCriterionSizer(use_half_kelly=True)
        
        result = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950
        )
        
        # Должны использоваться значения по умолчанию
        assert result.lot >= 0
        assert 'win_rate' in result.metadata
        assert 'profit_factor' in result.metadata
    
    def test_kelly_max_limit(self):
        """Тест ограничения максимума Келли."""
        sizer = KellyCriterionSizer(use_half_kelly=False, max_kelly_percent=0.10)
        
        # Очень хорошая статистика
        strategy_stats = {
            'win_rate': 0.80,
            'profit_factor': 5.0
        }
        
        result = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950,
            strategy_stats=strategy_stats
        )
        
        # Должно быть ограничено max_kelly_percent
        assert result.risk_percent <= 10.0


class TestVolatilityAdjustedSizer:
    """Тесты Volatility Adjusted."""
    
    def test_basic_calculation(self):
        """Тест базового расчёта."""
        sizer = VolatilityAdjustedSizer(
            target_risk_percent=0.01,
            atr_multiplier=2.0
        )
        
        result = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950,
            atr=0.0050  # 50 pips
        )
        
        # ATR 50 pips * multiplier 2.0 = 100 pips для расчёта
        assert 'atr' in result.metadata
        assert result.metadata['atr'] == 0.0050
        assert result.metadata['atr_pips'] == 50.0
    
    def test_high_volatility_reduces_lot(self):
        """Тест что высокая волатильность уменьшает лот."""
        sizer = VolatilityAdjustedSizer(target_risk_percent=0.01)
        
        # Низкая волатильность
        result_low_vol = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0990,
            atr=0.0010  # 10 pips
        )
        
        # Высокая волатильность
        result_high_vol = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950,
            atr=0.0100  # 100 pips
        )
        
        # При высокой волатильности лот должен быть меньше
        assert result_high_vol.lot < result_low_vol.lot


class TestRiskParitySizer:
    """Тесты Risk Parity."""
    
    def test_equal_risk_distribution(self):
        """Тест равного распределения риска."""
        sizer = RiskParitySizer(
            total_risk_percent=0.05,
            max_positions=5
        )
        
        result = sizer.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950
        )
        
        # Риск на позицию = 5% / 5 = 1%
        assert result.risk_percent == pytest.approx(1.0, rel=0.1)
        assert 'risk_per_position_percent' in result.metadata


class TestPositionSizer:
    """Тесты главного PositionSizer."""
    
    def test_init_default_method(self, sample_config):
        """Тест инициализации с методом по умолчанию."""
        ps = PositionSizer(sample_config)
        
        assert ps.method == SizingMethod.FIXED_FRACTIONAL
    
    def test_calculate_with_default_method(self, sample_config):
        """Тест расчёта с методом по умолчанию."""
        ps = PositionSizer(sample_config)
        
        result = ps.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950
        )
        
        assert result.method == SizingMethod.FIXED_FRACTIONAL
        assert result.lot > 0
    
    def test_calculate_with_specific_method(self, sample_config):
        """Тест расчёта с конкретным методом."""
        ps = PositionSizer(sample_config)
        
        result = ps.calculate_with_method(
            method=SizingMethod.HALF_KELLY,
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950,
            strategy_stats={'win_rate': 0.55, 'profit_factor': 1.5}
        )
        
        assert result.method == SizingMethod.HALF_KELLY
    
    def test_compare_methods(self, sample_config):
        """Тест сравнения всех методов."""
        ps = PositionSizer(sample_config)
        
        results = ps.compare_methods(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=100000,
            entry_price=1.1000,
            stop_loss_price=1.0950,
            atr=0.0050,
            strategy_stats={'win_rate': 0.55, 'profit_factor': 1.5}
        )
        
        # Должны быть результаты для всех методов
        assert len(results) == 5
        assert 'fixed_fractional' in results
        assert 'half_kelly' in results
        assert 'volatility_adjusted' in results
        assert 'risk_parity' in results
        
        # Все методы должны вернуть валидные результаты
        for method_name, result in results.items():
            assert result.lot >= 0
            assert result.risk_usd >= 0
    
    def test_validation_min_lot(self, sample_config):
        """Тест валидации минимума лота."""
        sample_config.position_sizing.min_lot = 0.1
        
        ps = PositionSizer(sample_config)
        
        result = ps.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=1000,  # Маленький счёт
            entry_price=1.1000,
            stop_loss_price=1.0950
        )
        
        # Лот должен быть округлён до минимума
        assert result.lot >= 0.01
    
    def test_validation_max_lot(self, sample_config):
        """Тест валидации максимума лота."""
        sample_config.position_sizing.max_lot = 1.0
        
        ps = PositionSizer(sample_config)
        
        result = ps.calculate(
            symbol='EURUSD',
            signal_type=SignalType.BUY,
            account_equity=1000000,  # Большой счёт
            entry_price=1.1000,
            stop_loss_price=1.0950
        )
        
        # Лот должен быть ограничен максимумом
        assert result.lot <= 1.0
    
    def test_statistics_tracking(self, sample_config):
        """Тест отслеживания статистики."""
        ps = PositionSizer(sample_config)
        
        # Несколько расчётов
        for i in range(5):
            ps.calculate(
                symbol='EURUSD',
                signal_type=SignalType.BUY,
                account_equity=100000,
                entry_price=1.1000,
                stop_loss_price=1.0950
            )
        
        stats = ps.get_statistics()
        
        assert stats['total_calculations'] == 5
        assert 'fixed_fractional' in stats['by_method']
        assert stats['by_method']['fixed_fractional'] == 5
        assert stats['avg_lot'] > 0
    
    def test_set_method(self, sample_config):
        """Тест смены метода."""
        ps = PositionSizer(sample_config)
        
        assert ps.method == SizingMethod.FIXED_FRACTIONAL
        
        ps.set_method(SizingMethod.HALF_KELLY)
        
        assert ps.method == SizingMethod.HALF_KELLY


class TestPositionSizeResult:
    """Тесты PositionSizeResult."""
    
    def test_to_dict(self):
        """Тест конвертации в словарь."""
        result = PositionSizeResult(
            lot=1.5,
            method=SizingMethod.FIXED_FRACTIONAL,
            risk_usd=150.0,
            risk_percent=1.0,
            stop_loss_pips=50.0
        )
        
        data = result.to_dict()
        
        assert data['lot'] == 1.5
        assert data['method'] == 'fixed_fractional'
        assert data['risk_usd'] == 150.0
        assert data['risk_percent'] == 1.0
        assert data['stop_loss_pips'] == 50.0
        assert data['validation_passed'] is True
    
    def test_metadata(self):
        """Тест метаданных."""
        result = PositionSizeResult(
            lot=1.0,
            method=SizingMethod.HALF_KELLY,
            risk_usd=100.0,
            risk_percent=2.0,
            stop_loss_pips=100.0,
            metadata={'win_rate': 0.55, 'profit_factor': 1.5}
        )
        
        assert 'win_rate' in result.metadata
        assert 'profit_factor' in result.metadata


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
