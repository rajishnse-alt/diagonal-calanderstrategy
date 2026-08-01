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
from niftyai.data import cache                      # noqa: E402
from niftyai.data import upstox                     # noqa: E402
from niftyai.features import engineer               # noqa: E402

to_frame = cache.to_frame          # single definition, shared with predict.py


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default=S.DEFAULT_INSTRUMENT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-contracts", type=int, default=0, help="0 = no cap")
    ap.add_argument("--days", type=int, default=S.OPTION_HISTORY_DAYS)
    ap.add_argument("--index-days", type=int, default=S.INDEX_HISTORY_DAYS)
    ap.add_argument("--no-cache", action="store_true",
                    help="bypass the archive (API only) — for debugging")
    a = ap.parse_args()

    inst = a.instrument.upper()
    P = S.paths(inst)
    out_path = a.out or P["dataset"]

    ikey = S.cfg(inst)["underlying_key"]
    idx = (to_frame(upstox.index_candles(inst, days=a.index_days)) if a.no_cache
           else cache.get(inst, ikey, days=a.index_days, is_index=True))
    print(f"[{inst}] underlying bars: {len(idx):,}"
          f"{'' if idx.empty else '  ' + str(idx['ts'].min().date()) + ' .. ' + str(idx['ts'].max().date())}",
          flush=True)
    spot = float(idx["close"].iloc[-1]) if not idx.empty else None

    contracts = upstox.option_contracts(inst, spot=spot)
    if a.max_contracts:
        contracts = contracts[:a.max_contracts]
    print(f"[{inst}] contracts to scan: {len(contracts)} (spot {spot})", flush=True)

    frames, kept, skipped = [], 0, 0
    for n, c in enumerate(contracts, 1):
        df = (to_frame(upstox.candles(c["instrument_key"], days=a.days))
              if a.no_cache else
              cache.get(inst, c["instrument_key"], days=a.days))
        if len(df) < S.MIN_BARS_PER_CONTRACT:
            skipped += 1
            continue
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
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        data.to_parquet(out_path, index=False)
    except Exception:
        out_path = out_path.replace(".parquet", ".csv")
        data.to_csv(out_path, index=False)
    _at_default = (data["fwd_max_ret"] >= S.TARGET_PCT).mean()
    print(f"\nrows={len(data):,}  contracts={kept}  "
          f"hit-rate@{S.TARGET_PCT:.2%}={_at_default:.4f}  "
          f"median fwd_max_ret={data['fwd_max_ret'].median():.4f}")
    print(f"span {data['ts'].min()} .. {data['ts'].max()}")
    print(f"written: {out_path}")
    if not a.no_cache:
        print(f"cache: {cache.stats(inst)}")


if __name__ == "__main__":
    main()
