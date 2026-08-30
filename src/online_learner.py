"""
online_learner.py — incremental (partial_fit) model with an honest
prequential accuracy log.

Why prequential eval instead of a train/test split: a single held-out split
at n=30-50 has huge variance (55% vs 50% accuracy is well within noise).
Scoring each row's prediction BEFORE training on it, then updating, means
every point is genuinely out-of-sample at the moment it's scored — the
resulting rolling accuracy is a much more honest read of real performance,
and it's a continuous series you can chart instead of a single number.

One instance per market (pass a distinct model_path per market_key from
harvest.py) so BTC and ETH don't share weights.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler


class OnlineLearner:
    def __init__(self, model_path: str, metrics_path: str, min_rows_before_trusted: int = 30):
        self.model_path = Path(model_path)
        self.metrics_path = Path(metrics_path)
        self.min_rows_before_trusted = min_rows_before_trusted

        self.scaler = StandardScaler()
        self.clf = SGDClassifier(loss="log_loss", random_state=0)
        self._fitted = False
        self.n_seen = 0
        self._correct_prequential = 0
        self.feature_order: Optional[list] = None

        self._load()

    def _load(self):
        if not self.model_path.exists():
            return
        state = json.loads(self.model_path.read_text())
        self.n_seen = state["n_seen"]
        self._correct_prequential = state["correct_prequential"]
        self.feature_order = state["feature_order"]
        if state.get("coef") is not None:
            self.clf.coef_ = np.array([state["coef"]])
            self.clf.intercept_ = np.array(state["intercept"])
            self.clf.classes_ = np.array([0, 1])
            self._fitted = True
        if state.get("scaler_mean") is not None:
            self.scaler.mean_ = np.array(state["scaler_mean"])
            self.scaler.var_ = np.array(state["scaler_var"])
            # Guard against zero-variance features (e.g. a constant feature,
            # or only 1-2 samples seen so far) — without this, transform()
            # divides by zero and every prediction blows up to inf/nan.
            # This mirrors what StandardScaler.partial_fit does internally,
            # which we lose by reconstructing scale_ by hand on reload.
            safe_var = np.where(self.scaler.var_ == 0, 1.0, self.scaler.var_)
            self.scaler.scale_ = np.sqrt(safe_var)
            # This sklearn version expects an array here (it calls
            # `.shape` on it internally during partial_fit), not a bare int.
            self.scaler.n_samples_seen_ = np.array(self.n_seen)

    def _save(self):
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "n_seen": self.n_seen,
            "correct_prequential": self._correct_prequential,
            "feature_order": self.feature_order,
            "coef": self.clf.coef_[0].tolist() if self._fitted else None,
            "intercept": self.clf.intercept_.tolist() if self._fitted else None,
            "scaler_mean": self.scaler.mean_.tolist() if getattr(self.scaler, "mean_", None) is not None else None,
            "scaler_var": self.scaler.var_.tolist() if getattr(self.scaler, "var_", None) is not None else None,
        }
        self.model_path.write_text(json.dumps(state))

    def _vectorize(self, features: Dict[str, float]) -> np.ndarray:
        if self.feature_order is None:
            self.feature_order = sorted(features.keys())
        return np.array([[features.get(k, 0.0) for k in self.feature_order]])

    def predict_proba(self, features: Dict[str, float]) -> float:
        if not self._fitted or self.n_seen < self.min_rows_before_trusted:
            return 0.5
        x_scaled = self.scaler.transform(self._vectorize(features))
        return float(self.clf.predict_proba(x_scaled)[0][1])

    def observe(self, features: Dict[str, float], label_up: int, market_key: str = "unknown") -> Optional[float]:
        x = self._vectorize(features)

        correct = None
        if self._fitted and self.n_seen >= 1:
            x_scaled = self.scaler.transform(x)
            pred = int(self.clf.predict(x_scaled)[0])
            correct = int(pred == label_up)

        self.scaler.partial_fit(x)
        x_scaled = self.scaler.transform(x)
        self.clf.partial_fit(x_scaled, [label_up], classes=[0, 1])
        self._fitted = True
        self.n_seen += 1
        if correct is not None:
            self._correct_prequential += correct

        prequential_acc = self._correct_prequential / (self.n_seen - 1) if self.n_seen > 1 else None
        self._log_metric(market_key, prequential_acc)
        self._save()
        return prequential_acc

    def is_trusted(self) -> bool:
        return self.n_seen >= self.min_rows_before_trusted

    def _log_metric(self, market_key: str, prequential_acc: Optional[float]):
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.time(),
            "market": market_key,
            "n_seen": self.n_seen,
            "prequential_acc": prequential_acc,
            "trusted": self.is_trusted(),
        }
        with self.metrics_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
