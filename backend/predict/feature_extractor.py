"""
Feature Extractor — TA signal dict → fixed-length numpy array for XGBoost.

Signal dict schema (from StrategyEngine):
  {
    "bot": str, "symbol": str, "action": str, "confidence": float,
    "price": float,
    "meta": {
      # Momentum strategy
      "ema_short": float, "ema_long": float, "spread_pct": float,
      # StatArb / range scalp strategies
      "bb_position": float,   # Bollinger band position 0–1
      # Engine-injected extras (added by process_tick enrichment)
      "atr_norm": float,      # ATR / price
      "momentum_z": float,    # (price - sma20) / std20
      # Orchestrator signal_event extras
      "ema_50": float, "ema_200": float,
      "rsi_14": float, "volume_surge_ratio": float,
    }
  }

Missing optional fields default to 0.5 (neutral).
"""

from __future__ import annotations
import math
import numpy as np

FEATURE_NAMES = [
    "ema_spread_ratio",   # (ema_fast - ema_slow) / ema_slow
    "rsi_14_norm",        # rsi_14 / 100.0
    "volume_surge_ratio", # vol / 20-bar sma vol
    "golden_cross_flag",  # bool → 1.0/0.0
    "rsi_gate_flag",      # rsi in 40–60 zone → 1.0/0.0
    "volume_surge_flag",  # vol > threshold → 1.0/0.0
    "bb_position",        # Bollinger band position (0.0 = lower, 1.0 = upper)
    "atr_norm",           # ATR / price (normalised volatility)
    "momentum_z",         # (price - sma20) / std20
    "confidence_raw",     # original TA signal confidence
]

_NEUTRAL = 0.5  # default for missing optional features


def extract_features(signal: dict) -> np.ndarray:
    """
    Extract a 10-dimensional feature vector from a strategy signal dict
    (or an orchestrator signal_event dict).

    Returns np.ndarray shape (10,), dtype float32.
    """
    meta = signal.get("meta", {}) or {}
    conf = float(signal.get("confidence", _NEUTRAL))
    price = float(signal.get("price", 1.0)) or 1.0

    # ── EMA spread ─────────────────────────────────────────────────────────
    ema_fast = float(meta.get("ema_short") or signal.get("ema_50") or 0.0)
    ema_slow = float(meta.get("ema_long") or signal.get("ema_200") or 0.0)
    if ema_slow > 0:
        ema_spread_ratio = (ema_fast - ema_slow) / ema_slow
    elif "spread_pct" in meta:
        ema_spread_ratio = float(meta["spread_pct"]) / 100.0
    else:
        ema_spread_ratio = 0.0

    # ── RSI ────────────────────────────────────────────────────────────────
    rsi_raw = float(meta.get("rsi_14") or signal.get("rsi_14") or 50.0)
    rsi_14_norm = rsi_raw / 100.0
    rsi_gate_flag = 1.0 if 0.40 <= rsi_14_norm <= 0.60 else 0.0

    # ── Volume surge ───────────────────────────────────────────────────────
    vsr = float(meta.get("volume_surge_ratio") or signal.get("volume_surge_ratio") or _NEUTRAL)
    volume_surge_flag = 1.0 if vsr >= 1.5 else 0.0

    # ── Golden cross flag ──────────────────────────────────────────────────
    cond = signal.get("conditions", {}) or {}
    golden_cross_flag = 1.0 if cond.get("golden_cross") else 0.0
    if golden_cross_flag == 0.0 and ema_fast > ema_slow and ema_slow > 0:
        golden_cross_flag = 1.0

    # ── Bollinger band position ────────────────────────────────────────────
    bb_position = float(meta.get("bb_position", _NEUTRAL))
    bb_position = max(0.0, min(1.0, bb_position))

    # ── ATR (normalised) ───────────────────────────────────────────────────
    atr_raw = float(meta.get("atr", 0.0))
    atr_norm = (atr_raw / price) if (atr_raw > 0 and price > 0) else float(meta.get("atr_norm", _NEUTRAL))
    atr_norm = max(0.0, min(1.0, atr_norm))

    # ── Momentum z-score ──────────────────────────────────────────────────
    momentum_z = float(meta.get("momentum_z", 0.0))
    momentum_z = max(-4.0, min(4.0, momentum_z))  # clip to ±4σ

    features = np.array([
        ema_spread_ratio,
        rsi_14_norm,
        vsr,
        golden_cross_flag,
        rsi_gate_flag,
        volume_surge_flag,
        bb_position,
        atr_norm,
        momentum_z,
        conf,
    ], dtype=np.float32)

    # Replace NaN/Inf with neutral fallback
    features = np.where(np.isfinite(features), features, _NEUTRAL)
    return features


def compute_market_implied_prob(features: np.ndarray) -> float:
    """
    Derive a market-implied probability of an up-move from the momentum z-score.

    p_mkt = sigmoid(z) = 1 / (1 + exp(-z))

    A z-score of 0 → 50% (no directional edge).
    A z-score of +2 → ~88% (strong upward momentum vs 20-bar mean).
    """
    z = float(features[8])  # index 8 = momentum_z
    return round(1.0 / (1.0 + math.exp(-z)), 4)
