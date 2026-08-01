"""
Train the hit-probability model.

THE REQUIRED MOVE IS A FEATURE (f_req_move). Each training row is paired with a
randomly drawn threshold and labelled y = (fwd_max_ret >= threshold), so one
model answers "P(premium rises r% within the horizon)" for ANY r rather than a
single hardcoded one. That is required by the problem: on one card the PE leg
needed +31.8% and the CE leg +11.6%.

Thresholds are drawn per row instead of expanding every row across a grid —
same information at 1/K the rows, and it avoids K near-duplicate rows sharing a
timestamp, which would leak across the train/valid boundary.

VALIDATION IS TIME-ORDERED: the validation set is strictly later than training.
A random split would let the model interpolate between adjacent 5-min bars of
the same contract and report a meaningless score.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from niftyai.config import settings as S      # noqa: E402
from niftyai.features import engineer          # noqa: E402

THRESH_LO, THRESH_HI = 0.05, 0.60      # plausible required-move range


def load(path: str) -> pd.DataFrame:
    if path.endswith(".parquet") and os.path.exists(path):
        return pd.read_parquet(path)
    csv = path.replace(".parquet", ".csv")
    if os.path.exists(csv):
        return pd.read_csv(csv, parse_dates=["ts"])
    raise SystemExit(f"dataset not found: {path}")


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def calibration_table(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges = np.unique(edges)
    rows = []
    for i in range(len(edges) - 1):
        m = (p >= edges[i]) & (p <= edges[i + 1] if i == len(edges) - 2 else p < edges[i + 1])
        if m.sum() < 20:
            continue
        rows.append((float(p[m].mean()), float(y[m].mean()), int(m.sum())))
    return rows


def main():
    import lightgbm as lgb

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="niftyai/datasets/train.parquet")
    ap.add_argument("--model-out", default=S.MODEL_PATH)
    ap.add_argument("--meta-out", default=S.META_PATH)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    df = load(a.data).sort_values("ts").reset_index(drop=True)
    print(f"rows={len(df):,}  span {df['ts'].min()} .. {df['ts'].max()}")

    # pair every row with a random required move, then label against it
    df["f_req_move"] = rng.uniform(THRESH_LO, THRESH_HI, len(df))
    df["y"] = (df["fwd_max_ret"] >= df["f_req_move"]).astype(int)
    print(f"label base rate: {df['y'].mean():.4f}")

    feats = engineer.feature_columns(df)
    if "f_req_move" not in feats:
        feats.append("f_req_move")
    feats = sorted(set(feats))

    # time-ordered split on the TIMESTAMP, so no contract straddles the boundary
    cut_ts = df["ts"].quantile(1 - S.VALID_FRACTION)
    tr, va = df[df["ts"] < cut_ts], df[df["ts"] >= cut_ts]
    print(f"train={len(tr):,}  valid={len(va):,}  cut at {cut_ts}")
    if len(va) < 500:
        raise SystemExit("validation split too small — collect more data first")

    dtr = lgb.Dataset(tr[feats], tr["y"])
    dva = lgb.Dataset(va[feats], va["y"], reference=dtr)
    booster = lgb.train(
        S.LGBM_PARAMS, dtr,
        num_boost_round=S.NUM_BOOST_ROUND,
        valid_sets=[dva], valid_names=["valid"],
        callbacks=[lgb.early_stopping(S.EARLY_STOPPING, verbose=False),
                   lgb.log_evaluation(50)],
    )

    p = booster.predict(va[feats], num_iteration=booster.best_iteration)
    y = va["y"].to_numpy()
    try:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(y, p))
    except Exception:
        order = np.argsort(p)
        r = np.empty_like(order, dtype=float); r[order] = np.arange(len(p))
        n1, n0 = y.sum(), len(y) - y.sum()
        auc = float((r[y == 1].sum() - n1 * (n1 - 1) / 2) / (n1 * n0)) if n1 and n0 else float("nan")

    base = float(y.mean())
    print(f"\nvalid AUC   = {auc:.4f}")
    print(f"valid Brier = {brier(y, p):.4f}   (base rate {base:.4f} -> "
          f"{brier(y, np.full_like(p, base)):.4f})")
    print("\ncalibration (predicted -> actual, n):")
    for pm, am, n in calibration_table(y, p):
        print(f"   {pm:6.3f} -> {am:6.3f}   n={n}")

    os.makedirs(os.path.dirname(a.model_out), exist_ok=True)
    booster.save_model(a.model_out, num_iteration=booster.best_iteration)
    imp = sorted(zip(feats, booster.feature_importance("gain")),
                 key=lambda x: -x[1])[:20]
    meta = {
        "features": feats,
        "horizon_bars": S.HORIZON_BARS,
        "bar_minutes": S.BAR_MINUTES,
        "rows": int(len(df)),
        "trained_through": str(df["ts"].max()),
        "valid_auc": auc,
        "valid_brier": brier(y, p),
        "base_rate": base,
        "best_iteration": int(booster.best_iteration or S.NUM_BOOST_ROUND),
        "top_features": [[f, float(g)] for f, g in imp],
        "threshold_range": [THRESH_LO, THRESH_HI],
    }
    with open(a.meta_out, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nsaved {a.model_out}\nsaved {a.meta_out}")
    print("\ntop features by gain:")
    for f_, g in imp[:10]:
        print(f"   {f_:<18} {g:,.0f}")


if __name__ == "__main__":
    main()
