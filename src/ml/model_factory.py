# src/ml/model_factory.py
import logging
import os

import torch
from typing import Any, Dict, Optional

import lightgbm as lgb

from src.core.config_models import Settings
from src.ml.architectures import TimeSeriesTransformer, SimpleLSTM  # Наша PyTorch LSTM модель

logger = logging.getLogger(__name__)


class ModelFactory:
    """
    Фабрика для создания необученных экземпляров моделей различных архитектур.
    """

    def __init__(self, config: Settings):
        self.config = config
        logger.info("ModelFactory (v2.0 - Multi-Arch) инициализирована.")

    def create_model(self, model_type: str, model_params: Dict) -> Optional[Any]:
        """
        Создает и возвращает экземпляр модели по ее типу.

        Args:
            model_type (str): Тип модели (например, 'LSTM_PyTorch', 'LightGBM').
            model_params (Dict): Словарь с параметрами для инициализации модели.

        Returns:
            Экземпляр необученной модели или None в случае ошибки.
        """
        logger.info(f"Запрос на создание модели типа: '{model_type}'")

        if model_type.upper() == 'LSTM_PYTORCH':
            return self._build_pytorch_lstm(model_params)

        elif model_type.upper() == 'LIGHTGBM':
            return self._build_lightgbm_model(model_params)

        elif model_type.upper() == 'TRANSFORMER_PYTORCH':
            return self._build_pytorch_transformer(model_params)



        else:
            logger.error(f"Неизвестный тип модели запрошен у ModelFactory: {model_type}")
            return None

    def _build_pytorch_lstm(self, params: Dict) -> SimpleLSTM:
        """Собирает PyTorch LSTM модель."""
        # Ожидаемые параметры: 'input_dim', 'hidden_dim', 'num_layers', 'output_dim'
        try:
            model = SimpleLSTM(
                input_dim=params['input_dim'],
                hidden_dim=params.get('hidden_dim', 64),
                num_layers=params.get('num_layers', 2),
                output_dim=params.get('output_dim', 1)
            )
            logger.info(f"Создана модель SimpleLSTM с input_dim={params['input_dim']}.")
            return model
        except KeyError as e:
            logger.error(f"Отсутствует необходимый параметр для создания LSTM: {e}")
            return None

    def _build_pytorch_transformer(self, params: Dict) -> TimeSeriesTransformer:
        """Собирает PyTorch TimeSeriesTransformer модель."""
        try:
            model = TimeSeriesTransformer(
                input_dim=params['input_dim'],
                d_model=params.get('d_model', 64),
                nhead=params.get('nhead', 4),
                nlayers=params.get('nlayers', 2)
            )
            logger.info(f"Создана модель TimeSeriesTransformer с input_dim={params['input_dim']}.")
            return model
        except KeyError as e:
            logger.error(f"Отсутствует необходимый параметр для создания Transformer: {e}")
            return None

    def _build_lightgbm_model(self, params: Dict) -> lgb.LGBMRegressor:
        """Собирает LightGBM модель."""

        final_params = {
            'objective': 'regression_l1',
            'metric': 'rmse',
            'n_estimators': 1000,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 1,
            'verbose': -1,
            'seed': 42,
            'boosting_type': 'gbdt'
        }
        final_params.update(params)

        # =================================================================
        # === ИСПРАВЛЕНИЕ: ПРИНУДИТЕЛЬНОЕ ИСПОЛЬЗОВАНИЕ CPU С ОГРАНИЧЕНИЕМ ===
        # =================================================================
        # LightGBM будет использовать OMP_NUM_THREADS, установленный в .bat (4 ядра).
        final_params['device'] = 'cpu'
        final_params['n_jobs'] = int(os.environ.get('OMP_NUM_THREADS', 4))  # Берем из переменной окружения
        logger.info(f"LightGBM принудительно использует CPU с n_jobs={final_params['n_jobs']}.")
        # =================================================================

        final_params.pop('input_dim', None)

        model = lgb.LGBMRegressor(**final_params)
        logger.info("Создана модель LGBMRegressor.")
        return model