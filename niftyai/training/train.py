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


def auc_score(y, p) -> float:
    """
    Rank-based AUC with no sklearn dependency.

    The sklearn import used to sit in a bare try/except, so on a runner without
    scikit-learn every fold silently reported nan and the summary then crashed
    on an empty array. Compute it directly instead of depending on an optional
    package for a core metric.
    """
    y = np.asarray(y); p = np.asarray(p, dtype=float)
    n1 = float(y.sum()); n0 = float(len(y) - n1)
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    sp = p[order]
    i = 0
    while i < len(sp):                       # average ranks within ties
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


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


def walk_forward(df, feats, folds, lgb):
    """
    Purged walk-forward validation.

    One held-out window is a coin flip on this much data — NIFTY's single split
    landed at AUC 0.42 and SENSEX's at 0.645, which says more about which three
    days got held out than about the model. Expanding-window folds, each with
    the same HORIZON purge, give a distribution instead of one draw.

    Reported against the RIGHT baseline: a model is only useful if it beats
    predicting the fold's own base rate, so Brier is shown next to that.
    """
    purge = pd.Timedelta(minutes=S.HORIZON_BARS * S.BAR_MINUTES)
    edges = [df["ts"].quantile(q) for q in np.linspace(0.4, 1.0, folds + 1)]
    print(f"\n{'='*72}\nWALK-FORWARD  ({folds} expanding folds, {purge} purge)\n{'='*72}")
    print(f"{'fold':>4} {'train':>9} {'valid':>8} {'base':>7} {'AUC':>7} "
          f"{'Brier':>8} {'vs base':>9}")
    aucs, edges_beaten = [], 0
    for k in range(folds):
        v_lo, v_hi = edges[k], edges[k + 1]
        tr = df[df["ts"] < v_lo - purge]
        va = df[(df["ts"] >= v_lo) & (df["ts"] < v_hi)]
        if len(tr) < 2000 or len(va) < 500:
            print(f"{k:>4}  skipped (train={len(tr):,} valid={len(va):,})")
            continue
        b = lgb.train(S.LGBM_PARAMS, lgb.Dataset(tr[feats], tr["y"]),
                      num_boost_round=S.NUM_BOOST_ROUND,
                      valid_sets=[lgb.Dataset(va[feats], va["y"])],
                      callbacks=[lgb.early_stopping(S.EARLY_STOPPING, verbose=False)])
        p = b.predict(va[feats], num_iteration=b.best_iteration)
        y = va["y"].to_numpy()
        base = float(y.mean())
        auc = auc_score(y, p)
        bs, bs_base = brier(y, p), brier(y, np.full_like(p, base))
        better = bs < bs_base
        edges_beaten += better
        aucs.append(auc)
        print(f"{k:>4} {len(tr):>9,} {len(va):>8,} {base:>7.3f} {auc:>7.3f} "
              f"{bs:>8.4f} {bs_base:>9.4f} {'BEAT' if better else 'worse'}")
    arr = np.array([x for x in aucs if x == x])
    if arr.size:
        print(f"\nAUC across folds: mean {arr.mean():.3f}  sd {arr.std():.3f}  "
              f"min {arr.min():.3f}  max {arr.max():.3f}")
        print(f"folds beating the base rate on Brier: {edges_beaten}/{len(aucs)}")
        # Fold-to-fold spread is large, so judge the MEAN against 0.5 with its
        # standard error rather than celebrating a good fold or despairing at a
        # bad one. A single split is one draw from this distribution.
        se = arr.std(ddof=1) / np.sqrt(len(arr)) if len(arr) > 1 else float("nan")
        lo, hi = arr.mean() - 1.96 * se, arr.mean() + 1.96 * se
        print(f"mean AUC 95% CI: {lo:.3f} - {hi:.3f}")
        if lo > 0.5:
            print("VERDICT: edge is statistically distinguishable from random. "
                  "Calibrate before using the probabilities as probabilities.")
        elif arr.mean() > 0.5:
            print("VERDICT: suggestive but NOT established — the CI still "
                  "includes 0.5. Keep accumulating history; do not trade it yet.")
        else:
            print("VERDICT: no usable edge. Keep accumulating history.")
    print("=" * 72)


def main():
    import lightgbm as lgb

    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default=S.DEFAULT_INSTRUMENT)
    ap.add_argument("--data", default=None)
    ap.add_argument("--model-out", default=None)
    ap.add_argument("--meta-out", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--walk-forward", type=int, default=5,
                    help="purged expanding folds; 0/1 disables")
    ap.add_argument("--cv-only", action="store_true",
                    help="report walk-forward and stop, do not save a model")
    a = ap.parse_args()

    inst = a.instrument.upper()
    P = S.paths(inst)
    a.data      = a.data      or P["dataset"]
    a.model_out = a.model_out or P["model"]
    a.meta_out  = a.meta_out  or P["meta"]
    print(f"[{inst}]")

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

    if a.walk_forward > 1:
        walk_forward(df, feats, a.walk_forward, lgb)
        if a.cv_only:
            return

    # Time-ordered split with a PURGE GAP.
    #
    # A plain cut leaks: row t's label is max(high[t+1 .. t+HORIZON]) , so any
    # training row within HORIZON bars of the boundary has a label computed from
    # bars that live in the validation period. Measured on SENSEX, the unpurged
    # split reported AUC 0.945 with predictions of 0.72 against an actual 0.44 —
    # the score was reading its own answers. Dropping the overlap is what makes
    # the number mean anything.
    cut_ts  = df["ts"].quantile(1 - S.VALID_FRACTION)
    purge   = pd.Timedelta(minutes=S.HORIZON_BARS * S.BAR_MINUTES)
    tr = df[df["ts"] < cut_ts - purge]
    va = df[df["ts"] >= cut_ts]
    dropped = len(df) - len(tr) - len(va)
    print(f"train={len(tr):,}  valid={len(va):,}  cut at {cut_ts}  "
          f"(purged {dropped:,} rows within {purge} of the cut)")
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
    auc = auc_score(y, p)

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
        "instrument": inst,
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
