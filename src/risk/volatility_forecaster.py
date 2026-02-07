# src/risk/volatility_forecaster.py
import logging
import pandas as pd
import numpy as np
from arch import arch_model

logger = logging.getLogger(__name__)


class VolatilityForecaster:
    """
    Прогнозирует волатильность с использованием модели GARCH.
    """

    def predict_next_volatility(self, series: pd.Series) -> float:
        """
        Обучает модель GARCH(1,1) на предоставленных данных и прогнозирует
        волатильность на следующий период.

        Args:
            series (pd.Series): Временной ряд цен закрытия.

        Returns:
            float: Предсказанное значение волатильности (в десятичной дроби, напр. 0.01 = 1%).
        """
        if series is None or len(series) < 252:
            logger.warning("Недостаточно данных (минимум 252) для прогнозирования волатильности GARCH.")
            return 0.0

        try:
            # GARCH требует доходность, а не цены. Умножаем на 100 для лучшей сходимости.
            returns = 100 * series.pct_change().dropna()

            if returns.var() < 1e-8:
                logger.warning("Дисперсия доходности слишком мала для GARCH модели.")
                return 0.0

            # Создаем и обучаем модель GARCH(1,1)
            # mean='Zero' для финансовых рядов, vol='Garch'
            model = arch_model(returns, mean='Zero', vol='Garch', p=1, q=1, rescale=False)

            # Используем try/except для fit, так как GARCH может не сойтись
            try:
                res = model.fit(disp='off', show_warning=False)
            except Exception as e:
                logger.warning(f"GARCH(1,1) не сошелся: {e}. Возврат 0.0.")
                return 0.0

            # Прогнозируем на 1 шаг вперед
            forecast = res.forecast(horizon=1)

            # Извлекаем предсказанную дисперсию и берем квадратный корень
            predicted_variance = forecast.variance.iloc[-1, 0]
            predicted_std_dev = np.sqrt(predicted_variance)

            # Возвращаем предсказанное стандартное отклонение (в виде десятичной дроби)
            return predicted_std_dev / 100

        except Exception as e:
            logger.error(f"Критическая ошибка при прогнозировании волатильности GARCH: {e}", exc_info=True)
            return 0.0

