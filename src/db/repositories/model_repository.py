# src/db/repositories/model_repository.py (новый, расширенный)
"""
ModelRepository — управление ML-моделями, скалерами и чемпионами.
Отвечает за сохранение, загрузку, продвижение и деактивацию моделей.
"""

import io
import json
import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from sqlalchemy.orm import Session

from src.db.database_manager import RestrictedUnpickler, safe_pickle_loads
from src.db.models import Scaler, TrainedModel
from src.ml.architectures import SimpleLSTM, TimeSeriesTransformer

logger = logging.getLogger(__name__)


class ModelRepository:
    """Репозиторий для работы с ML-моделями и скалерами."""

    def __init__(self, session_factory, config, write_queue=None):
        self.session_factory = session_factory
        self.config = config
        self.write_queue = write_queue

    def load_champion_models(
        self, symbol: str, timeframe: int
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Any], Optional[Any]]:
        """Загрузить модели-чемпионы для символа/таймфрейма."""
        session: Session = self.session_factory()
        try:
            model_types_query = (
                session.query(TrainedModel.model_type)
                .filter_by(symbol=symbol, timeframe=timeframe, is_champion=True)
                .distinct()
            )
            model_types = [row[0] for row in model_types_query]

            if not model_types:
                return None, None, None

            champion_models = {}
            for model_type in model_types:
                model_record = (
                    session.query(TrainedModel)
                    .filter_by(symbol=symbol, timeframe=timeframe, model_type=model_type, is_champion=True)
                    .first()
                )
                if not model_record:
                    continue

                model = None
                if model_type == "LSTM_PyTorch":
                    model = SimpleLSTM(input_dim=len(model_record.features_list))
                    buffer = io.BytesIO(model_record.model_data)
                    model.load_state_dict(torch.load(buffer, map_location="cpu", weights_only=True))
                    model.eval()  # Eval-режим для инференса
                    logger.debug(f"✅ LSTM модель загружена для {symbol}")
                elif model_type == "Transformer_PyTorch":
                    model = TimeSeriesTransformer(input_dim=len(model_record.features_list))
                    buffer = io.BytesIO(model_record.model_data)
                    model.load_state_dict(torch.load(buffer, map_location="cpu", weights_only=True))
                    model.eval()  # Eval-режим для инференса
                    logger.debug(f"✅ Transformer модель загружена для {symbol}")
                elif model_type == "LightGBM":
                    import lightgbm as lgb

                    model = lgb.Booster(model_str=model_record.model_data)

                champion_models[model_type] = model

            scaler_record = session.query(Scaler).filter_by(symbol=symbol).first()
            if not scaler_record:
                logger.warning(f"[{symbol}] Скалеры не найдены")
                return champion_models, None, None

            x_scaler = safe_pickle_loads(scaler_record.x_scaler_data)
            y_scaler = safe_pickle_loads(scaler_record.y_scaler_data) if scaler_record.y_scaler_data else x_scaler

            return champion_models, x_scaler, y_scaler

        except Exception as e:
            logger.error(f"Ошибка загрузки моделей для {symbol}: {e}")
            return None, None, None
        finally:
            session.close()

    def load_model_components_by_id(self, model_id: int) -> Optional[Dict]:
        """Загрузить компоненты модели по ID."""
        session: Session = self.session_factory()
        try:
            model_record = session.query(TrainedModel).filter_by(id=model_id).first()
            if not model_record:
                logger.warning(f"Модель с ID {model_id} не найдена")
                return None

            model = None
            if model_record.model_type == "LSTM_PyTorch":
                model = SimpleLSTM(input_dim=len(model_record.features_list))
                buffer = io.BytesIO(model_record.model_data)
                model.load_state_dict(torch.load(buffer, map_location="cpu", weights_only=True))
                model.eval()  # Eval-режим для инференса
                logger.debug(f"✅ LSTM модель загружена (ID: {model_id})")
            elif model_record.model_type == "Transformer_PyTorch":
                model = TimeSeriesTransformer(input_dim=len(model_record.features_list))
                buffer = io.BytesIO(model_record.model_data)
                model.load_state_dict(torch.load(buffer, map_location="cpu", weights_only=True))
                model.eval()  # Eval-режим для инференса
                logger.debug(f"✅ Transformer модель загружена (ID: {model_id})")
            elif model_record.model_type == "LightGBM":
                import lightgbm as lgb

                model = lgb.Booster(model_str=model_record.model_data)

            scaler_record = session.query(Scaler).filter_by(symbol=model_record.symbol).first()
            x_scaler = safe_pickle_loads(scaler_record.x_scaler_data) if scaler_record else None
            y_scaler = (
                safe_pickle_loads(scaler_record.y_scaler_data) if scaler_record and scaler_record.y_scaler_data else x_scaler
            )

            return {
                "model": model,
                "model_type": model_record.model_type,
                "symbol": model_record.symbol,
                "features": model_record.features_list,
                "x_scaler": x_scaler,
                "y_scaler": y_scaler,
            }
        except Exception as e:
            logger.error(f"Ошибка загрузки модели {model_id}: {e}")
            return None
        finally:
            session.close()

    def save_model_and_scalers(
        self,
        symbol: str,
        timeframe: int,
        model,
        model_type: str,
        x_scaler,
        y_scaler,
        features_list: List[str],
        training_batch_id: str,
        hyperparameters: Optional[Dict] = None,
    ) -> Optional[int]:
        """Сохранить модель и скалеры (синхронно)."""
        return self._save_model_and_scalers_internal(
            symbol,
            timeframe,
            model,
            model_type,
            x_scaler,
            y_scaler,
            features_list,
            training_batch_id,
            hyperparameters,
        )

    def _save_model_and_scalers_internal(
        self,
        symbol: str,
        timeframe: int,
        model,
        model_type: str,
        x_scaler,
        y_scaler,
        features_list: List[str],
        training_batch_id: str,
        hyperparameters: Optional[Dict] = None,
    ) -> Optional[int]:
        """Внутренний метод сохранения модели."""
        session: Session = self.session_factory()
        try:
            # Сериализация модели
            if isinstance(model, nn.Module):
                buffer = io.BytesIO()
                torch.save(model.state_dict(), buffer)
                model_data = buffer.getvalue()
            elif model_type == "LightGBM":
                model_data = model.model_to_string()
            else:
                model_data = pickle.dumps(model)

            # Определение версии
            last_version = (
                session.query(TrainedModel.version)
                .filter_by(symbol=symbol, timeframe=timeframe, model_type=model_type)
                .order_by(TrainedModel.version.desc())
                .first()
            )
            new_version = (last_version[0] + 1) if last_version else 1

            # Деактивация старых чемпионов
            session.query(TrainedModel).filter_by(
                symbol=symbol, timeframe=timeframe, model_type=model_type, is_champion=True
            ).update({"is_champion": False})

            # Создание новой записи
            new_model = TrainedModel(
                symbol=symbol,
                timeframe=timeframe,
                model_type=model_type,
                version=new_version,
                is_champion=True,
                model_data=model_data,
                features_list=features_list,
                training_batch_id=training_batch_id,
                hyperparameters=json.dumps(hyperparameters) if hyperparameters else None,
                trained_at=datetime.now(),
            )
            session.add(new_model)
            session.flush()

            # Сохранение скалеров
            scaler_record = session.query(Scaler).filter_by(symbol=symbol).first()
            if scaler_record:
                scaler_record.x_scaler_data = pickle.dumps(x_scaler)
                scaler_record.y_scaler_data = pickle.dumps(y_scaler) if y_scaler else None
            else:
                scaler_record = Scaler(
                    symbol=symbol,
                    x_scaler_data=pickle.dumps(x_scaler),
                    y_scaler_data=pickle.dumps(y_scaler) if y_scaler else None,
                )
                session.add(scaler_record)

            session.commit()

            # Обновление метаданных
            self._update_model_metadata_file(new_model)

            return new_model.id

        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка сохранения модели {symbol}: {e}")
            return None
        finally:
            session.close()

    def promote_challenger_to_champion(self, challenger_id: int, report: dict):
        """Продвинуть претендента в чемпионы."""
        self._promote_challenger_to_champion_internal(challenger_id, report)

    def _promote_challenger_to_champion_internal(self, challenger_id: int, report: dict):
        """Внутренний метод продвижения."""
        session: Session = self.session_factory()
        try:
            challenger = session.query(TrainedModel).filter_by(id=challenger_id).first()
            if not challenger:
                logger.warning(f"Претендент {challenger_id} не найден")
                return

            # Деактивация текущего чемпиона
            session.query(TrainedModel).filter_by(
                symbol=challenger.symbol,
                timeframe=challenger.timeframe,
                model_type=challenger.model_type,
                is_champion=True,
            ).update({"is_champion": False})

            # Активация нового чемпиона
            challenger.is_champion = True
            challenger.performance_report = json.dumps(self._convert_numpy_types(report))
            challenger.trained_at = datetime.now()

            session.commit()
            logger.info(f"Модель {challenger_id} продвинута в чемпионы для {challenger.symbol}")

            self._update_model_metadata_file(challenger)

        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка продвижения претендента {challenger_id}: {e}")
        finally:
            session.close()

    def demote_champion(self, model_id: int) -> bool:
        """Разжаловать чемпиона."""
        session: Session = self.session_factory()
        try:
            model = session.query(TrainedModel).filter_by(id=model_id, is_champion=True).first()
            if not model:
                logger.warning(f"Модель {model_id} не является чемпионом")
                return False

            model.is_champion = False
            session.commit()
            logger.info(f"Модель {model_id} разжалована из чемпионов")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка разжалования модели {model_id}: {e}")
            return False
        finally:
            session.close()

    def get_all_models_for_gui(self) -> List[Dict]:
        """Получить все модели для GUI."""
        session: Session = self.session_factory()
        try:
            models = session.query(TrainedModel).order_by(TrainedModel.trained_at.desc()).all()
            result = []
            for m in models:
                perf = json.loads(m.performance_report) if m.performance_report else {}
                result.append(
                    {
                        "id": m.id,
                        "symbol": m.symbol,
                        "type": m.model_type,
                        "version": m.version,
                        "status": "champion" if m.is_champion else "active",
                        "sharpe": perf.get("sharpe_ratio", 0),
                        "profit_factor": perf.get("profit_factor", 0),
                        "date": m.trained_at.isoformat() if m.trained_at else "N/A",
                    }
                )
            return result
        except Exception as e:
            logger.error(f"Ошибка получения списка моделей: {e}")
            return []
        finally:
            session.close()

    def _update_model_metadata_file(self, champion_model):
        """Обновить JSON файл метаданных модели."""
        try:
            # Используем MODEL_DIR если доступен, иначе fallback
            if hasattr(self.config, "MODEL_DIR") and self.config.MODEL_DIR:
                metadata_dir = Path(self.config.MODEL_DIR)
            else:
                metadata_dir = Path(self.config.DATABASE_FOLDER) / "ai_models"
            metadata_dir.mkdir(parents=True, exist_ok=True)

            metadata_file = metadata_dir / f"{champion_model.symbol}_metadata.json"

            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            else:
                metadata = {"symbol": champion_model.symbol, "models": {}}

            model_key = f"{champion_model.model_type}_TF{champion_model.timeframe}"
            metadata["models"][model_key] = {
                "model_id": champion_model.id,
                "version": champion_model.version,
                "trained_at": champion_model.trained_at.isoformat() if champion_model.trained_at else None,
                "features": champion_model.features_list,
                "hyperparameters": json.loads(champion_model.hyperparameters) if champion_model.hyperparameters else {},
                "performance": json.loads(champion_model.performance_report) if champion_model.performance_report else {},
                "is_champion": champion_model.is_champion,
            }

            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.debug(f"Метаданные обновлены: {metadata_file}")
        except Exception as e:
            logger.error(f"Ошибка обновления метаданных: {e}")

    @staticmethod
    def _convert_numpy_types(obj):
        """Конвертация numpy типов в Python для JSON сериализации."""
        if isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: ModelRepository._convert_numpy_types(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [ModelRepository._convert_numpy_types(i) for i in obj]
        return obj
