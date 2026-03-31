# src/ml/architectures.py
import logging
import math

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


# --- АРХИТЕКТУРА LSTM (УПРОЩЕННАЯ) ---


class SimpleLSTM(nn.Module):
    """
    Более простая и стабильная LSTM-модель без LayerNorm.
    Использует стандартный многослойный LSTM от PyTorch.
    """

    def __init__(self, input_dim, hidden_dim, num_layers, output_dim):
        super(SimpleLSTM, self).__init__()
        # Используем один многослойный LSTM, что более эффективно
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,  # Важно для соответствия формату данных
        )

        self.dropout = nn.Dropout(0.1)
        self.fc = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):
        # --- ИСПРАВЛЕНИЕ 1: Клиппинг входных данных (сохраняем) ---
        x = torch.clamp(x, min=-10.0, max=10.0)
        # ----------------------------------------------------------

        # Проверка на NaN/inf на входе (можно удалить после клиппинга, но оставим для лога)
        if not torch.all(torch.isfinite(x)):
            logger.warning("!!! ВНИМАНИЕ: NaN или inf на входе в модель SimpleLSTM !!!")

        out, _ = self.lstm(x)
        out = self.dropout(out)

        # Проверка на NaN/inf после LSTM
        if not torch.all(torch.isfinite(out)):
            logger.warning("!!! ВНИМАНИЕ: NaN или inf на выходе из LSTM слоя !!!")
            out = torch.clamp(out, min=-1e5, max=1e5)
            # ----------------------------------------------------------

        out = self.fc(out[:, -1, :])

        # Проверка на NaN/inf на финальном выходе
        if not torch.all(torch.isfinite(out)):
            logger.warning("!!! ВНИМАНИЕ: NaN или inf на финальном выходе из модели !!!")
            # --- ИСПРАВЛЕНИЕ 3: Принудительный клиппинг финального выхода ---
            out = torch.clamp(out, min=-1e5, max=1e5)
            # ----------------------------------------------------------------

        return out


# --- АРХИТЕКТУРА TRANSFORMER ---
class PositionalEncoding(nn.Module):
    """Внедряет информацию о позиции токенов в последовательности."""

    def __init__(self, d_model: int, dropout: float = 0.1, max_len: int = 5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model))
        pe = torch.zeros(max_len, 1, d_model)
        pe[:, 0, 0::2] = torch.sin(position * div_term)
        pe[:, 0, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.pe[: x.size(0)]
        return self.dropout(x)


class TimeSeriesTransformer(nn.Module):
    """
    Архитектура Transformer, адаптированная для задач регрессии временных рядов.
    """

    def __init__(
        self, input_dim: int, d_model: int = 64, nhead: int = 4, d_hid: int = 128, nlayers: int = 2, dropout: float = 0.2
    ):
        super().__init__()
        self.model_type = "Transformer"
        self.pos_encoder = PositionalEncoding(d_model, dropout)
        encoder_layers = nn.TransformerEncoderLayer(d_model, nhead, d_hid, dropout, batch_first=True)
        self.transformer_encoder = nn.TransformerEncoder(encoder_layers, nlayers)
        self.encoder = nn.Linear(input_dim, d_model)
        self.d_model = d_model
        self.decoder = nn.Linear(d_model, 1)

    def forward(self, src: torch.Tensor) -> torch.Tensor:
        """
        Args:
            src: Tensor of shape (batch_size, seq_len, input_dim)
        """
        # 1. Линейное преобразование и масштабирование
        src = self.encoder(src) * math.sqrt(self.d_model)  # Shape: (batch_size, seq_len, d_model)

        # 2. Позиционное кодирование
        src = self.pos_encoder(src)

        # 3. Transformer Encoder
        output = self.transformer_encoder(src)  # Shape: (batch_size, seq_len, d_model)

        # 4. Декодер (берем только последний токен для прогноза)
        output = self.decoder(output[:, -1, :])  # Shape: (batch_size, 1)

        return output
