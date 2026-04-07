# src/db/repositories/model_repository.py
"""
ModelRepository — работа с ML-моделями и скалерами.
"""

import io
import json
import logging
import pickle
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import torch
from sqlalchemy.orm import Session

from src.db.models import Scaler, StrategicModel, TrainedModel

logger = logging.getLogger(__name__)


class ModelRepository:
    """Репозиторий для управления ML-моделями."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def save_trained_model(
        self,
        symbol: str,
        timeframe: int,
        model_type: str,
        model_data: bytes,
        features: List[str],
        hyperparameters: Dict,
        is_champion: bool = False,
        performance_report: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> int:
        """Сохранить обученную модель в БД."""
        session: Session = self.session_factory()
        try:
            model = TrainedModel(
                symbol=symbol,
                timeframe=timeframe,
                model_type=model_type,
                model_data=model_data,
                features_json=json.dumps(features),
                hyperparameters_json=json.dumps(hyperparameters),
                is_champion=is_champion,
                performance_report=performance_report,
                training_batch_id=batch_id,
                version=1,
            )
            session.add(model)
            session.commit()
            model_id = model.id
            logger.info(f"💾 Модель {model_type} для {symbol} сохранена с ID={model_id}")
            return model_id
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении модели для {symbol}: {e}")
            return -1
        finally:
            session.close()

    def save_scalers(self, symbol: str, x_scaler, y_scaler) -> bool:
        """Сохранить скалеры для символа."""
        session: Session = self.session_factory()
        try:
            scaler_record = session.query(Scaler).filter_by(symbol=symbol).first()
            if scaler_record:
                scaler_record.x_scaler_data = pickle.dumps(x_scaler)
                scaler_record.y_scaler_data = pickle.dumps(y_scaler)
            else:
                scaler_record = Scaler(
                    symbol=symbol,
                    x_scaler_data=pickle.dumps(x_scaler),
                    y_scaler_data=pickle.dumps(y_scaler),
                )
                session.add(scaler_record)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при сохранении скалеров для {symbol}: {e}")
            return False
        finally:
            session.close()

    def load_scalers(self, symbol: str) -> Tuple[Any, Any]:
        """Загрузить скалеры для символа."""
        session: Session = self.session_factory()
        try:
            scaler_record = session.query(Scaler).filter_by(symbol=symbol).first()
            if not scaler_record:
                logger.warning(f"[{symbol}] Scaler не найден в БД")
                return None, None

            x_scaler = pickle.loads(scaler_record.x_scaler_data)
            y_scaler_data = scaler_record.y_scaler_data
            if y_scaler_data:
                y_scaler = pickle.loads(y_scaler_data)
            else:
                logger.warning(f"[{symbol}] y_scaler не найден. Используем x_scaler как fallback")
                y_scaler = x_scaler

            return x_scaler, y_scaler
        except Exception as e:
            logger.error(f"Ошибка при загрузке скалеров для {symbol}: {e}")
            return None, None
        finally:
            session.close()

    def get_champion_models(self, symbol: str, timeframe: int) -> List[TrainedModel]:
        """Получить список моделей-чемпионов для символа/таймфрейма."""
        session: Session = self.session_factory()
        try:
            return (
                session.query(TrainedModel)
                .filter_by(symbol=symbol, timeframe=timeframe, is_champion=True)
                .order_by(TrainedModel.version.desc())
                .all()
            )
        finally:
            session.close()

    def update_model_champion_status(self, model_id: int, is_champion: bool) -> bool:
        """Обновить статус чемпиона модели."""
        session: Session = self.session_factory()
        try:
            model = session.query(TrainedModel).filter_by(id=model_id).first()
            if model:
                model.is_champion = is_champion
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления статуса чемпиона модели {model_id}: {e}")
            return False
        finally:
            session.close()

    def get_model_by_id(self, model_id: int) -> Optional[TrainedModel]:
        """Получить модель по ID."""
        session: Session = self.session_factory()
        try:
            return session.query(TrainedModel).filter_by(id=model_id).first()
        finally:
            session.close()

    def get_all_models_for_gui(self) -> List[Dict]:
        """Получить все модели для отображения в GUI."""
        session: Session = self.session_factory()
        try:
            models = session.query(TrainedModel).order_by(TrainedModel.training_date.desc()).all()
            return [
                {
                    "id": m.id,
                    "symbol": m.symbol,
                    "model_type": m.model_type,
                    "version": m.version,
                    "is_champion": m.is_champion,
                    "training_date": m.training_date.isoformat() if m.training_date else "",
                    "performance_report": m.performance_report,
                }
                for m in models
            ]
        finally:
            session.close()
