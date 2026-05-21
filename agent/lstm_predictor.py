from __future__ import annotations
"""
LSTM Prijsrichting Voorspeller met Attention.
Voorspelt: omhoog / neutraal / omlaag voor de volgende kaars.
"""
import os
import numpy as np
import pandas as pd
from pathlib import Path

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


class _AttentionLayer(nn.Module):
    def __init__(self, hidden_size: int):
        super().__init__()
        self.attn = nn.Linear(hidden_size, 1)

    def forward(self, lstm_out):
        weights = torch.softmax(self.attn(lstm_out), dim=1)
        return (weights * lstm_out).sum(dim=1)


class _LSTMModel(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 128, num_layers: int = 2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                            batch_first=True, dropout=0.3)
        self.attention = _AttentionLayer(hidden_size)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 3),  # 0=omlaag, 1=neutraal, 2=omhoog
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        ctx = self.attention(out)
        return self.head(ctx)


class LSTMPredictor:
    """
    Gebruik:
        predictor = LSTMPredictor(model_path="models/lstm_predictor.pt")
        predictor.train(df, feature_cols)  # Eenmalig trainen
        signal, confidence = predictor.predict(df, feature_cols)
    """

    def __init__(self, model_path: str = "models/lstm_predictor.pt",
                 window_size: int = 60, hidden_size: int = 128):
        self.model_path = Path(model_path)
        self.window_size = window_size
        self.hidden_size = hidden_size
        self.model: "_LSTMModel | None" = None
        self._scaler: "dict | None" = None  # mean/std per feature kolom
        self.device = "cuda" if (TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"
        self._load()

    def _load(self):
        if not TORCH_AVAILABLE or not self.model_path.exists():
            return
        try:
            checkpoint = torch.load(self.model_path, map_location=self.device, weights_only=False)
            input_size = checkpoint["input_size"]
            self.model = _LSTMModel(input_size, self.hidden_size).to(self.device)
            self.model.load_state_dict(checkpoint["state_dict"])
            self.model.eval()
            self._scaler = checkpoint.get("scaler", None)
        except Exception:
            self.model = None

    def train(self, df: pd.DataFrame, feature_cols: list[str],
              epochs: int = 30, batch_size: int = 64, lr: float = 1e-3) -> float:
        if not TORCH_AVAILABLE:
            return 0.0

        X, y, scaler = self._build_dataset(df, feature_cols)
        if len(X) < 100:
            return 0.0

        split = int(len(X) * 0.85)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        train_ds = TensorDataset(torch.FloatTensor(X_train), torch.LongTensor(y_train))
        train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

        input_size = X.shape[2]
        model = _LSTMModel(input_size, self.hidden_size).to(self.device)
        optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)

        # Gewogen loss: "neutraal" is oververtegenwoordigd (~35% van samples).
        # Zonder weights leert het model te vaak neutraal te voorspellen → lage directionale accuracy.
        counts = np.bincount(y_train, minlength=3).astype(np.float32)
        counts = np.maximum(counts, 1)
        class_weights = torch.FloatTensor(counts.sum() / (3 * counts)).to(self.device)
        criterion = nn.CrossEntropyLoss(weight=class_weights)
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs)

        best_val_acc = 0.0
        best_state = None  # Geïnitialiseerd voor de loop — voorkomt NameError
        train_loss = 0.0
        for epoch in range(epochs):
            model.train()
            train_loss = 0.0
            for xb, yb in train_dl:
                xb, yb = xb.to(self.device), yb.to(self.device)
                optimizer.zero_grad()
                batch_loss = criterion(model(xb), yb)
                batch_loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                train_loss += batch_loss.item()
            scheduler.step()

            # Validatie
            model.eval()
            with torch.no_grad():
                xv = torch.FloatTensor(X_val).to(self.device)
                yv = torch.LongTensor(y_val).to(self.device)
                preds = model(xv).argmax(dim=1)
                val_acc = (preds == yv).float().mean().item()

            # Voortgang elke 5 epochs
            if (epoch + 1) % 5 == 0 or epoch == 0:
                pct = (epoch + 1) / epochs * 100
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                avg_loss = train_loss / max(len(train_dl), 1)
                print(f"LSTM [{bar}] {pct:5.1f}% epoch {epoch+1:3d}/{epochs} | loss={avg_loss:.4f} | val_acc={val_acc:.1%}", flush=True)

            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_state = {
                    "state_dict": model.state_dict(),
                    "input_size": input_size,
                    "scaler": scaler,
                }

        # Fallback: sla laatste staat op als validatie nooit verbeterde
        if best_state is None:
            best_state = {
                "state_dict": model.state_dict(),
                "input_size": input_size,
                "scaler": scaler,
            }

        self.model_path.parent.mkdir(exist_ok=True)
        torch.save(best_state, self.model_path)
        self._scaler = scaler
        self.model = _LSTMModel(input_size, self.hidden_size).to(self.device)
        self.model.load_state_dict(best_state["state_dict"])
        self.model.eval()
        return best_val_acc

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> tuple[int, float]:
        """Returns: (signaal, confidence)  signaal: +1 omhoog, -1 omlaag, 0 neutraal"""
        if self.model is None or not TORCH_AVAILABLE:
            return 0, 0.0

        data = df[feature_cols].values
        if len(data) < self.window_size:
            return 0, 0.0

        window = data[-self.window_size:].astype(np.float32)
        window = np.nan_to_num(window, nan=0.0, posinf=1.0, neginf=-1.0)
        # Zelfde normalisatie als tijdens training toepassen
        if self._scaler is not None:
            window = (window - self._scaler["mean"]) / (self._scaler["std"] + 1e-8)
            window = np.clip(window, -10.0, 10.0)
        x = torch.FloatTensor(window).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1).cpu().numpy()[0]

        pred_class = int(probs.argmax())  # 0=omlaag, 1=neutraal, 2=omhoog
        confidence = float(probs[pred_class])

        action_map = {2: 1, 1: 0, 0: -1}
        return action_map[pred_class], confidence

    def _build_dataset(self, df: pd.DataFrame, feature_cols: list[str]):
        data = df[feature_cols].values.astype(np.float32)
        data = np.nan_to_num(data, nan=0.0, posinf=1.0, neginf=-1.0)

        # Z-score normalisatie per feature kolom — voorkomt dat grote waarden
        # (EMA-prijzen ~77000) andere features (RSI 0-100) overheersen
        mean = data.mean(axis=0)
        std = data.std(axis=0)
        scaler = {"mean": mean, "std": std}
        data_norm = (data - mean) / (std + 1e-8)
        data_norm = np.clip(data_norm, -10.0, 10.0)

        closes = df["close"].values
        X, y = [], []
        for i in range(self.window_size, len(data_norm) - 1):
            window = data_norm[i - self.window_size:i]
            future_return = (closes[i + 1] - closes[i]) / closes[i]

            # Drempel 0.2%: bij 0.1% waren ook ruis-kaarsen "directional" → slechte labels.
            # 0.2% filtert bid-ask spread weg maar behoudt genoeg directionale samples.
            if future_return > 0.002:
                label = 2  # omhoog
            elif future_return < -0.002:
                label = 0  # omlaag
            else:
                label = 1  # neutraal

            X.append(window)
            y.append(label)

        return np.array(X), np.array(y), scaler
