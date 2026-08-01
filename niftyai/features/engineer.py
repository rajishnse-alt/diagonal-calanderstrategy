"""
Feature engineering for the hit-probability model.

Deliberately ~40 features, not the ~300 in the platform sketch. Every feature
here is computable from data this repo can actually obtain right now (5-min
OHLCV for the contract plus the underlying). Greeks, IV rank, max pain, gamma
exposure and news sentiment are all in the sketch but none of them are
available from the public endpoints used here, and inventing proxies for them
would inflate the count without adding information.

EVERY feature is causal: computed from data at or before bar t, never after.
Shifted where needed so the row that predicts bar t+1..t+H cannot see them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / (dn + 1e-12))


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _tsi(s: pd.Series, long: int = 25, short: int = 13) -> pd.Series:
    d = s.diff()
    ds = d.ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    da = d.abs().ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    return 100 * ds / (da + 1e-12)


def _hma(s: pd.Series, n: int = 50) -> pd.Series:
    def w(x, m):
        return x.rolling(m).apply(
            lambda v: np.dot(v, np.arange(1, m + 1)) / (m * (m + 1) / 2), raw=True)
    half, sq = max(1, n // 2), max(1, int(round(np.sqrt(n))))
    return w(2 * w(s, half) - w(s, n), sq)


def build(opt: pd.DataFrame, idx: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    opt: 5-min OHLCV for ONE contract, oldest-first, columns
         [ts, open, high, low, close, volume, oi]
    idx: 5-min OHLCV for the underlying, same shape (optional but recommended)
    Returns the frame with feature columns appended.
    """
    d = opt.copy().reset_index(drop=True)
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]

    # ── premium level & shape ────────────────────────────────────────────────
    d["f_close"]      = c
    d["f_log_close"]  = np.log(c.clip(lower=0.05))
    d["f_hl_range"]   = (h - l) / c.clip(lower=0.05)
    d["f_body"]       = (c - d["open"]) / c.clip(lower=0.05)
    d["f_upper_wick"] = (h - np.maximum(c, d["open"])) / c.clip(lower=0.05)
    d["f_lower_wick"] = (np.minimum(c, d["open"]) - l) / c.clip(lower=0.05)

    # ── returns over several lookbacks ───────────────────────────────────────
    for n in (1, 3, 6, 12, 24, 48):
        d[f"f_ret_{n}"] = c.pct_change(n)
    # ── realised volatility ──────────────────────────────────────────────────
    r1 = c.pct_change()
    for n in (6, 12, 24, 48):
        d[f"f_vol_{n}"] = r1.rolling(n).std()

    # ── distance from rolling extremes: how much room to the target ──────────
    for n in (12, 24, 75):
        rmax, rmin = h.rolling(n).max(), l.rolling(n).min()
        d[f"f_dist_hi_{n}"] = (rmax - c) / c.clip(lower=0.05)
        d[f"f_dist_lo_{n}"] = (c - rmin) / c.clip(lower=0.05)

    # ── indicators ───────────────────────────────────────────────────────────
    d["f_rsi"]      = _rsi(c)
    d["f_atr_rel"]  = _atr(d) / c.clip(lower=0.05)
    d["f_tsi"]      = _tsi(c)
    hma            = _hma(c, 50)
    d["f_hma_rel"]  = (c - hma) / c.clip(lower=0.05)
    d["f_hma_slope"] = hma.diff(3) / c.clip(lower=0.05)
    for n in (12, 48):
        ema = c.ewm(span=n, adjust=False).mean()
        d[f"f_ema_rel_{n}"] = (c - ema) / c.clip(lower=0.05)
    bb_m = c.rolling(20).mean()
    bb_s = c.rolling(20).std()
    d["f_bb_pos"] = (c - bb_m) / (2 * bb_s + 1e-12)

    # ── volume / open interest ───────────────────────────────────────────────
    d["f_vol_rel"] = v / (v.rolling(48).mean() + 1e-9)
    if "oi" in d:
        oi = d["oi"].astype(float)
        d["f_oi_chg_6"]  = oi.pct_change(6).replace([np.inf, -np.inf], np.nan)
        d["f_oi_chg_24"] = oi.pct_change(24).replace([np.inf, -np.inf], np.nan)

    # ── contract context ─────────────────────────────────────────────────────
    d["f_is_ce"]      = (d.get("opt_type", "CE") == "CE").astype(int) if "opt_type" in d else 0
    if "moneyness" in d:
        d["f_moneyness"] = d["moneyness"]
    if "dte" in d:
        d["f_dte"] = d["dte"]

    # ── time of day / session position ───────────────────────────────────────
    ts = pd.to_datetime(d["ts"])
    d["f_minute_of_day"] = ts.dt.hour * 60 + ts.dt.minute
    d["f_bars_left"]     = (15 * 60 + 30 - d["f_minute_of_day"]) / 5.0
    d["f_dow"]           = ts.dt.dayofweek

    # ── underlying context ───────────────────────────────────────────────────
    if idx is not None and not idx.empty:
        i = idx.copy()
        i["ts"] = pd.to_datetime(i["ts"])
        i = i.set_index("ts")
        ic = i["close"]
        u = pd.DataFrame({
            "f_idx_ret_6":  ic.pct_change(6),
            "f_idx_ret_24": ic.pct_change(24),
            "f_idx_vol_24": ic.pct_change().rolling(24).std(),
            "f_idx_rsi":    _rsi(ic),
        })
        d = d.join(u.reindex(ts).reset_index(drop=True))

    return d


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("f_")]
