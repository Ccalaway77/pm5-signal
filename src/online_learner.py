"""
online_learner.py — incremental (partial_fit) model with an honest
prequential accuracy log.

v2 changes:
- L2 regularization (alpha) so coefficients cannot explode to ±30
- clip raw features before scaling
- clip predicted P(up) so a huge intercept cannot print p≈0 or p≈1
- optional path suffix so a fresh regularized book can train
  without wiping data/model_btc.json
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
    def __init__(
        self,
        model_path: str,
        metrics_path: str,
        min_rows_before_trusted: int = 30,
        sgd_alpha: float = 0.01,
        feature_clip: float = 8.0,
        p_clip_low: float = 0.12,
        p_clip_high: float = 0.88,
    ):
        self.model_path = Path(model_path)
        self.metrics_path = Path(metrics_path)
        self.min_rows_before_trusted = min_rows_before_trusted
        self.sgd_alpha = float(sgd_alpha)
        self.feature_clip = float(feature_clip)
        self.p_clip_low = float(p_clip_low)
        self.p_clip_high = float(p_clip_high)

        self.scaler = StandardScaler()
        self.clf = self._new_clf()
        self._fitted = False
        self.n_seen = 0
        self._correct_prequential = 0
        self.feature_order: Optional[list] = None

        self._load()

    def _new_clf(self) -> SGDClassifier:
        return SGDClassifier(
            loss="log_loss",
            penalty="l2",
            alpha=self.sgd_alpha,
            random_state=0,
        )

    def _load(self):
        if not self.model_path.exists():
            return
        state = json.loads(self.model_path.read_text())
        self.n_seen = state["n_seen"]
        self._correct_prequential = state["correct_prequential"]
        self.feature_order = state["feature_order"]
        if state.get("coef") is not None:
            self.clf = self._new_clf()
            self.clf.coef_ = np.array([state["coef"]])
            self.clf.intercept_ = np.array(state["intercept"])
            self.clf.classes_ = np.array([0, 1])
            self._fitted = True
        if state.get("scaler_mean") is not None:
            self.scaler.mean_ = np.array(state["scaler_mean"])
            self.scaler.var_ = np.array(state["scaler_var"])
            safe_var = np.where(self.scaler.var_ == 0, 1.0, self.scaler.var_)
            self.scaler.scale_ = np.sqrt(safe_var)
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
            "sgd_alpha": self.sgd_alpha,
        }
        self.model_path.write_text(json.dumps(state))

    def _vectorize(self, features: Dict[str, float]) -> np.ndarray:
        if self.feature_order is None:
            self.feature_order = sorted(features.keys())
        raw = np.array([[features.get(k, 0.0) for k in self.feature_order]], dtype=float)
        return np.clip(raw, -self.feature_clip, self.feature_clip)

    def predict_proba(self, features: Dict[str, float]) -> float:
        if not self._fitted or self.n_seen < self.min_rows_before_trusted:
            return 0.5
        x_scaled = self.scaler.transform(self._vectorize(features))
        p = float(self.clf.predict_proba(x_scaled)[0][1])
        if p != p:
            return 0.5
        return min(self.p_clip_high, max(self.p_clip_low, p))

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
            "model": self.model_path.name,
        }
        with self.metrics_path.open("a") as f:
            f.write(json.dumps(row) + "\n")


def learner_from_cfg(market_key: str, cfg: dict, suffix: str = "") -> OnlineLearner:
    lc = cfg.get("learner", {})
    return OnlineLearner(
        model_path=f"data/model_{market_key}{suffix}.json",
        metrics_path="data/metrics.jsonl",
        min_rows_before_trusted=lc.get("min_rows_before_trusted", 30),
        sgd_alpha=lc.get("sgd_alpha", 0.01),
        feature_clip=lc.get("feature_clip", 8.0),
        p_clip_low=lc.get("p_clip_low", 0.12),
        p_clip_high=lc.get("p_clip_high", 0.88),
    )
