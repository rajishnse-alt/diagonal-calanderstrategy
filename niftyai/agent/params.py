"""
Learned parameters, persisted to git so each day starts from what the last day
taught it.

WHY THE STOP IS VOLATILITY-SCALED
    The spec's stop — day low − 0.11% — put risk at 9.71 on a 20.00 entry (49%
    of the premium) while Tg sat +5.19 away. That is 0.53R, so 1:3 was
    unreachable by construction, not by bad luck.
    The stop is now the TIGHTER of the two:  max(day_low_stop, entry - k*ATR).
    The day-low rule still caps how far the stop can ever sit, so the original
    intent survives; k scales it to the volatility actually present.

Everything here is bounded. An adaptive parameter with no clamp will happily
walk to a degenerate value on a small sample — a k of 0.1 would show a
beautiful R multiple and stop out on every tick.
"""
from __future__ import annotations

import json
import os

PATH = "niftyai/agent/params.json"

DEFAULTS = {
    "atr_stop_mult": 1.5,     # entry - k*ATR
    "atr_trail_mult": 1.5,    # runner trail
    "book_fraction": 0.80,
    "rr_target": 3.0,
    "_bounds": {              # hard clamps — learning may not leave these
        "atr_stop_mult":  [0.8, 3.0],
        "atr_trail_mult": [1.0, 4.0],
        "book_fraction":  [0.5, 0.9],
    },
    "_meta": {"trades_seen": 0, "last_update": None, "by_regime": {}},
}


def load() -> dict:
    if os.path.exists(PATH):
        try:
            p = json.load(open(PATH))
            for k, v in DEFAULTS.items():
                p.setdefault(k, v)
            return p
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULTS))


def save(p: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(p, f, indent=2, sort_keys=True)


def clamp(p: dict, key: str, value: float) -> float:
    lo, hi = p.get("_bounds", {}).get(key, [-1e9, 1e9])
    return max(lo, min(hi, value))


def regime(atr_pct: float | None) -> str:
    """
    Volatility bucket from ATR as a fraction of the option premium. Options
    behave very differently at 3% vs 15% ATR, so one global k is a compromise
    across regimes that barely resemble each other.
    """
    if atr_pct is None:
        return "unknown"
    if atr_pct < 0.04:
        return "low"
    if atr_pct < 0.09:
        return "mid"
    return "high"


def stop_mult_for(p: dict, atr_pct: float | None) -> float:
    """Per-regime k once that regime has enough trades; else the global one."""
    r = regime(atr_pct)
    by = (p.get("_meta") or {}).get("by_regime", {}).get(r)
    if by and by.get("n", 0) >= 8 and by.get("atr_stop_mult"):
        return clamp(p, "atr_stop_mult", by["atr_stop_mult"])
    return clamp(p, "atr_stop_mult", p.get("atr_stop_mult", 1.5))
