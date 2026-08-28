"""Unit tests for FeatureEngineer."""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

try:
    from src.ml.feature_engineer import FeatureEngineer
except ImportError:
    FeatureEngineer = MagicMock


class TestFeatureEngineerValidation:
    """Tests for input validation."""

    @pytest.fixture
    def feature_engineer(self):
        mock_config = MagicMock()
        mock_config.lookback_period = 30
        return FeatureEngineer(config=mock_config)

    def test_handles_empty_dataframe(self, feature_engineer):
        """Should handle empty DataFrame gracefully."""
        empty_df = pd.DataFrame()
        # FeatureEngineer logs error and returns input df when empty
        result = feature_engineer.generate_features(empty_df, symbol="EURUSD")
        assert isinstance(result, pd.DataFrame)

    def test_handles_dataframe_without_datetime_index(self, feature_engineer):
        """Should handle DataFrame without proper datetime index."""
        invalid_df = pd.DataFrame({"date": [1, 2], "volume": [100, 200]})
        # FeatureEngineer handles missing index gracefully
        result = feature_engineer.generate_features(invalid_df, symbol="EURUSD")
        assert isinstance(result, pd.DataFrame)


class TestFeatureEngineerGeneration:
    """Tests for feature generation."""

    @pytest.fixture
    def feature_engineer(self):
        mock_config = MagicMock()
        mock_config.lookback_period = 30
        return FeatureEngineer(config=mock_config)

    @pytest.fixture
    def sample_ohlcv(self):
        """Creates realistic mock OHLCV DataFrame."""
        dates = pd.date_range(start="2023-01-01", periods=100, freq="h")
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        high = close + np.random.uniform(0.5, 2.0, 100)
        low = close - np.random.uniform(0.5, 2.0, 100)
        open_price = low + np.random.uniform(0.1, 1.0, 100)
        volume = np.random.randint(1000, 5000, 100)
        return pd.DataFrame({
            "open": open_price, "high": high, "low": low,
            "close": close, "volume": volume
        }, index=dates)

    def test_generate_features_returns_dataframe(self, feature_engineer, sample_ohlcv):
        result_df = feature_engineer.generate_features(sample_ohlcv.copy(), symbol="EURUSD")
        assert isinstance(result_df, pd.DataFrame)

    def test_generate_features_preserves_columns(self, feature_engineer, sample_ohlcv):
        result_df = feature_engineer.generate_features(sample_ohlcv.copy(), symbol="EURUSD")
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result_df.columns


class TestFeatureEngineerNaNHandling:
    """Tests for NaN handling."""

    @pytest.fixture
    def feature_engineer(self):
        mock_config = MagicMock()
        return FeatureEngineer(config=mock_config)

    @pytest.fixture
    def df_with_nans(self):
        dates = pd.date_range(start="2023-01-01", periods=10, freq="h")
        return pd.DataFrame({
            "open": [1.0, 2.0, np.nan, 4.0, 5.0, np.nan, 7.0, 8.0, 9.0, 10.0],
            "high": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
            "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5],
            "close": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5],
            "volume": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        }, index=dates)

    def test_handles_nans_gracefully(self, feature_engineer, df_with_nans):
        result_df = feature_engineer.generate_features(df_with_nans.copy(), symbol="EURUSD")
        assert isinstance(result_df, pd.DataFrame)


class TestFeatureEngineerEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def feature_engineer(self):
        mock_config = MagicMock()
        return FeatureEngineer(config=mock_config)

    def test_single_row_dataframe(self, feature_engineer):
        """Should handle single-row DataFrame."""
        dates = pd.date_range(start="2023-01-01", periods=1, freq="h")
        single_row_df = pd.DataFrame({
            "open": [100.0], "high": [101.0], "low": [99.0],
            "close": [100.5], "volume": [1000]
        }, index=dates)
        result_df = feature_engineer.generate_features(single_row_df, symbol="EURUSD")
        assert isinstance(result_df, pd.DataFrame)

    def test_inf_values_handled(self, feature_engineer):
        """Should handle infinity values."""
        dates = pd.date_range(start="2023-01-01", periods=5, freq="h")
        df_with_inf = pd.DataFrame({
            "open": [100.0, 101.0, np.inf, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0, -np.inf],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [100.5, 101.5, np.inf, 102.5, 103.5],
            "volume": [1000, 2000, 3000, 4000, 5000]
        }, index=dates)
        result_df = feature_engineer.generate_features(df_with_inf.copy(), symbol="EURUSD")
        assert isinstance(result_df, pd.DataFrame)


class TestFeatureEngineerIntegration:
    """Integration tests."""

    @pytest.fixture
    def feature_engineer(self):
        mock_config = MagicMock()
        mock_config.lookback_period = 30
        return FeatureEngineer(config=mock_config)

    def test_full_pipeline(self, feature_engineer):
        """Full pipeline with realistic market data."""
        dates = pd.date_range(start="2023-01-01", periods=100, freq="h")
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        df = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": np.random.randint(1000, 10000, 100)
        }, index=dates)
        result = feature_engineer.generate_features(df, symbol="BTCUSD")
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "close" in result.columns

