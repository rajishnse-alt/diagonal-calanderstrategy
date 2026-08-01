"""
Build the labelled hit-probability dataset.

LABEL: for each bar t of each contract,
       y = 1 if max(high[t+1 .. t+HORIZON_BARS]) >= close[t] * (1 + TARGET_PCT)

Only FUTURE bars count, and the entry reference is close[t], so no row can see
its own outcome. Rows without a full horizon ahead are dropped rather than
labelled 0 — labelling a truncated window 0 would teach the model that the end
of the sample never hits its target.

Also archives raw candles to niftyai/datasets/candles/, because an option's
history vanishes from the API once it expires; the archive is how the training
set outlives the ~1 month the API retains.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from niftyai.config import settings as S          # noqa: E402
from niftyai.data import upstox                    # noqa: E402
from niftyai.features import engineer              # noqa: E402

COLS = ["ts", "open", "high", "low", "close", "volume", "oi"]


def to_frame(raw: list[list]) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame(raw, columns=COLS[:len(raw[0])])
    for c in ("open", "high", "low", "close", "volume", "oi"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts"] = pd.to_datetime(df["ts"], format="mixed", utc=True) \
                 .dt.tz_convert(upstox.IST).dt.tz_localize(None)
    return df.sort_values("ts").reset_index(drop=True)


def forward_max_return(df: pd.DataFrame, horizon: int) -> pd.Series:
    """
    max(high[t+1 .. t+horizon]) / close[t] - 1

    Stored instead of a 0/1 label ON PURPOSE. The card's targets are NOT a
    fixed distance from the current price — on the same card PE needed +31.8%
    (30.80 -> 40.58) while CE needed +11.6% (31.10 -> 34.70). A model trained
    against one hardcoded threshold answers neither. Keeping the continuous
    forward max makes the dataset threshold-agnostic: the required move becomes
    a FEATURE at training time, so one model serves any target.

    NaN for the last `horizon` bars — a truncated window must be dropped, not
    labelled 0, or the model learns that sample-ends never reach their target.
    """
    s = df["high"].astype(float)
    # reverse-rolling: r.rolling(H).max() reversed gives max(s[t .. t+H-1]);
    # shift(-1) moves it to max(s[t+1 .. t+H]), excluding the current bar.
    fwd_incl = s[::-1].rolling(horizon, min_periods=horizon).max()[::-1]
    fwd = fwd_incl.shift(-1)
    return fwd / df["close"].astype(float).clip(lower=0.05) - 1.0


def archive(df: pd.DataFrame, key: str) -> None:
    os.makedirs(S.ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(S.ARCHIVE_DIR, key.replace("|", "_") + ".csv")
    if os.path.exists(path):
        old = pd.read_csv(path, parse_dates=["ts"])
        df  = pd.concat([old, df]).drop_duplicates("ts").sort_values("ts")
    df.to_csv(path, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="niftyai/datasets/train.parquet")
    ap.add_argument("--max-contracts", type=int, default=0, help="0 = no cap")
    ap.add_argument("--days", type=int, default=S.MAX_RANGE_DAYS)
    ap.add_argument("--no-archive", action="store_true")
    a = ap.parse_args()

    idx = to_frame(upstox.index_candles(days=a.days))
    print(f"underlying bars: {len(idx)}", flush=True)
    spot = float(idx["close"].iloc[-1]) if not idx.empty else None

    contracts = upstox.option_contracts(max_strike_dist=S.MAX_STRIKE_DIST, spot=spot)
    if a.max_contracts:
        contracts = contracts[:a.max_contracts]
    print(f"contracts to scan: {len(contracts)} (spot {spot})", flush=True)

    frames, kept, skipped = [], 0, 0
    for n, c in enumerate(contracts, 1):
        raw = upstox.candles(c["instrument_key"], days=a.days)
        df  = to_frame(raw)
        if len(df) < S.MIN_BARS_PER_CONTRACT:
            skipped += 1
            continue
        if not a.no_archive:
            archive(df, c["instrument_key"])
        df["opt_type"]  = c["opt_type"]
        df["strike"]    = c["strike"]
        df["moneyness"] = (c["strike"] - spot) / spot if spot else 0.0
        df["dte"]       = [(c["expiry"] - t.date()).days for t in df["ts"]]
        feat = engineer.build(df, idx)
        feat["fwd_max_ret"]    = forward_max_return(df, S.HORIZON_BARS)
        feat["instrument_key"] = c["instrument_key"]
        feat = feat[feat["fwd_max_ret"].notna() & (feat["close"] >= S.MIN_PREMIUM)]
        if not feat.empty:
            frames.append(feat)
            kept += 1
        if n % 25 == 0:
            print(f"   {n}/{len(contracts)} scanned, {kept} kept, {skipped} thin", flush=True)

    if not frames:
        print("no usable contracts", file=sys.stderr)
        sys.exit(1)

    data = pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    try:
        data.to_parquet(a.out, index=False)
    except Exception:
        a.out = a.out.replace(".parquet", ".csv")
        data.to_csv(a.out, index=False)
    _at_default = (data["fwd_max_ret"] >= S.TARGET_PCT).mean()
    print(f"\nrows={len(data):,}  contracts={kept}  "
          f"hit-rate@{S.TARGET_PCT:.2%}={_at_default:.4f}  "
          f"median fwd_max_ret={data['fwd_max_ret'].median():.4f}")
    print(f"span {data['ts'].min()} .. {data['ts'].max()}")
    print(f"written: {a.out}")


if __name__ == "__main__":
    main()
