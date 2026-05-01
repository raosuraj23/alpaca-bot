"""
XGBoost Signal Classifier — probability gate before LLM ensemble.

Trains on (signal_features, win) pairs from closed trades.
Predicts P(win) for incoming TA signals.
Rejects signals where P(win) < XGBOOST_MIN_CONFIDENCE or
edge (P(win) - market_implied_prob) < MIN_EDGE.

Cold-start behaviour: if model is untrained (<50 samples), gate passes all signals
with a logged warning, so the system trades and accumulates training data.
"""

from __future__ import annotations
import logging
import math
import os
import pathlib
from collections import deque
from typing import Optional

import numpy as np

from config import settings
from predict.feature_extractor import FEATURE_NAMES

logger = logging.getLogger(__name__)

_MODEL_DIR  = pathlib.Path(__file__).parent.parent / "models"
_MODEL_PATH = _MODEL_DIR / "xgboost_signal.pkl"

MIN_TRAINING_SAMPLES = 50
COLD_START_MIN_MKT_PROB = 0.65  # require directional conviction before XGBoost is trained


class XGBoostSignalClassifier:
    """
    Wraps an XGBClassifier trained on (signal_features, win) pairs.
    Thread-safe for read (predict/gate) operations; training is done
    synchronously in a background executor during nightly consolidation.
    """

    def __init__(self) -> None:
        self._model = None
        self._trained = False
        self._edge_window: deque[float] = deque(maxlen=50)  # rolling window for mispricing z-score
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(self, features: np.ndarray) -> float:
        """Return P(win) for a feature vector. Falls back to 0.5 if untrained."""
        if not self._trained or self._model is None:
            return 0.5
        try:
            prob = float(self._model.predict_proba(features.reshape(1, -1))[0][1])
            return round(prob, 4)
        except Exception as exc:
            logger.debug("[XGBOOST] predict failed: %s", exc)
            return 0.5

    def gate(self, features: np.ndarray, market_implied_prob: float) -> dict:
        """
        Apply probability and edge gates.

        Returns:
            {
              "approved": bool,
              "xgboost_prob": float,
              "market_implied_prob": float,
              "edge": float,
              "mispricing_z_score": float | None,
              "reason": str,
            }
        """
        xgb_prob = self.predict(features)
        edge = round(xgb_prob - market_implied_prob, 4)

        # Compute rolling mispricing z-score: edge / rolling_sigma of recent edges
        self._edge_window.append(edge)
        mispricing_z: float | None = None
        if len(self._edge_window) >= 5:
            vals = list(self._edge_window)
            mean_e = sum(vals) / len(vals)
            variance = sum((v - mean_e) ** 2 for v in vals) / len(vals)
            sigma = math.sqrt(variance)
            if sigma > 0:
                mispricing_z = round(edge / sigma, 4)

        if not self._trained:
            if market_implied_prob < COLD_START_MIN_MKT_PROB:
                return {
                    "approved": False,
                    "xgboost_prob": xgb_prob,
                    "market_implied_prob": round(market_implied_prob, 4),
                    "edge": edge,
                    "mispricing_z_score": mispricing_z,
                    "cold_start": True,
                    "reason": (
                        f"cold_start: market_implied_prob={market_implied_prob:.3f} "
                        f"< {COLD_START_MIN_MKT_PROB:.2f} — insufficient directional conviction"
                    ),
                }
            return {
                "approved": True,
                "xgboost_prob": xgb_prob,
                "market_implied_prob": round(market_implied_prob, 4),
                "edge": edge,
                "mispricing_z_score": mispricing_z,
                "cold_start": True,
                "reason": "cold_start — directional conviction gate passed, accumulating training data",
            }

        min_conf = settings.xgboost_min_confidence
        min_edge = settings.min_edge

        if xgb_prob < min_conf:
            return {
                "approved": False,
                "xgboost_prob": xgb_prob,
                "market_implied_prob": round(market_implied_prob, 4),
                "edge": edge,
                "mispricing_z_score": mispricing_z,
                "reason": f"XGBoost P(win)={xgb_prob:.3f} < threshold {min_conf:.2f}",
            }

        if edge < min_edge:
            return {
                "approved": False,
                "xgboost_prob": xgb_prob,
                "market_implied_prob": round(market_implied_prob, 4),
                "edge": edge,
                "mispricing_z_score": mispricing_z,
                "reason": (
                    f"edge={edge:.3f} (P(win)={xgb_prob:.3f} - p_mkt={market_implied_prob:.3f}) "
                    f"< min_edge {min_edge:.2f}"
                ),
            }

        return {
            "approved": True,
            "xgboost_prob": xgb_prob,
            "market_implied_prob": round(market_implied_prob, 4),
            "edge": edge,
            "mispricing_z_score": mispricing_z,
            "reason": (
                f"approved — P(win)={xgb_prob:.3f} edge={edge:+.3f} "
                f"(threshold: conf≥{min_conf:.2f}, edge≥{min_edge:.2f})"
            ),
        }

    def train(self, db_session=None) -> bool:
        """
        Train XGBoost on (signal_features, win) pairs from closed trades.

        Reads directly from SQLite via the stdlib sqlite3 module (avoids
        SQLAlchemy async/greenlet context issues when called from a
        background thread or at startup).

        Returns True if the model was trained/updated, False otherwise.
        """
        try:
            import sqlite3
            import json
            from config import settings

            db_url = settings.database_url  # e.g. "sqlite:///./trading_bot.db"
            db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                """
                SELECT s.signal_features, ct.win
                FROM signals s
                JOIN closed_trades ct
                  ON s.strategy = ct.bot_id
                 AND s.symbol   = ct.symbol
                 AND ABS(
                       (strftime('%s', s.timestamp) - strftime('%s', ct.entry_time))
                     ) < 300
                WHERE s.signal_features IS NOT NULL
                  AND ct.win IS NOT NULL
                ORDER BY s.timestamp DESC
                LIMIT 2000
                """
            ).fetchall()
            conn.close()

            if len(rows) < MIN_TRAINING_SAMPLES:
                logger.info(
                    "[XGBOOST] Insufficient training data: %d samples (need %d)",
                    len(rows), MIN_TRAINING_SAMPLES,
                )
                return False

            X, y = [], []
            for row in rows:
                raw = row[0]
                win = int(row[1])
                feats = raw if isinstance(raw, list) else json.loads(raw)
                if len(feats) == len(FEATURE_NAMES):
                    X.append(feats)
                    y.append(win)

            if len(X) < MIN_TRAINING_SAMPLES:
                logger.info("[XGBOOST] Too few valid feature rows: %d", len(X))
                return False

            X_arr = np.array(X, dtype=np.float32)
            y_arr = np.array(y, dtype=np.int32)

            from xgboost import XGBClassifier
            import joblib

            model = XGBClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                eval_metric="logloss",
                use_label_encoder=False,
                verbosity=0,
            )
            model.fit(X_arr, y_arr)

            _MODEL_DIR.mkdir(parents=True, exist_ok=True)
            joblib.dump(model, _MODEL_PATH)
            self._model = model
            self._trained = True

            # Log feature importances at INFO level
            importances = dict(zip(FEATURE_NAMES, model.feature_importances_))
            top = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:3]
            logger.info(
                "[XGBOOST] Trained on %d samples. Top features: %s",
                len(X),
                ", ".join(f"{k}={v:.3f}" for k, v in top),
            )
            return True

        except Exception as exc:
            logger.error("[XGBOOST] Training failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load persisted model from disk if it exists."""
        if not _MODEL_PATH.exists():
            logger.info("[XGBOOST] No persisted model found at %s — cold start", _MODEL_PATH)
            return
        try:
            import joblib
            self._model = joblib.load(_MODEL_PATH)
            self._trained = True
            logger.info("[XGBOOST] Loaded model from %s", _MODEL_PATH)
        except Exception as exc:
            logger.warning("[XGBOOST] Could not load model: %s — starting cold", exc)


# Module-level singleton — imported by orchestrator and main pipeline
xgb_classifier = XGBoostSignalClassifier()
