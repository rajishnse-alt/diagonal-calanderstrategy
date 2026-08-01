"""
P(target hit) for the CE and PE legs on the SPCL card.

Writes niftyai/prediction/latest.json, which the Streamlit app reads. Designed
to run unattended in GitHub Actions: public endpoints only, no access token, no
local state beyond the committed model file.

Legs are supplied as strike:TYPE:target, e.g.
    --legs 24200:PE:40.58,24500:CE:34.70
`target` is the absolute Tg premium from the card. The required move is derived
as target/last_close - 1 and fed to the model as f_req_move.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from niftyai.config import settings as S              # noqa: E402
from niftyai.data import cache                          # noqa: E402
from niftyai.data import upstox                         # noqa: E402
from niftyai.features import engineer                   # noqa: E402

to_frame = cache.to_frame


def resolve(strike: float, opt_type: str, contracts: list[dict]) -> dict | None:
    for c in contracts:                     # already sorted nearest-expiry first
        if c["opt_type"] == opt_type and abs(c["strike"] - strike) < 1:
            return c
    return None


def main():
    import lightgbm as lgb

    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default=S.DEFAULT_INSTRUMENT)
    ap.add_argument("--legs", required=True, help="strike:TYPE:target, comma separated")
    ap.add_argument("--model", default=None)
    ap.add_argument("--meta", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    inst = a.instrument.upper()
    P = S.paths(inst)
    a.model = a.model or P["model"]
    a.meta  = a.meta  or P["meta"]
    a.out   = a.out   or P["pred"]

    if not os.path.exists(a.model):
        raise SystemExit(f"no model at {a.model} — run niftyai/training/train.py first")
    booster = lgb.Booster(model_file=a.model)
    meta = json.load(open(a.meta)) if os.path.exists(a.meta) else {}
    feats = meta.get("features") or booster.feature_name()

    legs = []
    for part in a.legs.split(","):
        s, t, tgt = part.split(":")
        legs.append((float(s), t.upper(), float(tgt)))

    ikey = S.cfg(inst)["underlying_key"]
    idx  = cache.get(inst, ikey, days=S.INDEX_HISTORY_DAYS, is_index=True)
    spot = float(idx["close"].iloc[-1]) if not idx.empty else None
    contracts = upstox.option_contracts(inst, spot=spot)

    out = {
        "instrument": inst,
        "generated_at": datetime.now(upstox.IST).isoformat(timespec="seconds"),
        "spot": spot,
        "horizon_bars": S.HORIZON_BARS,
        "bar_minutes": S.BAR_MINUTES,
        "model": {k: meta.get(k) for k in
                  ("valid_auc", "valid_brier", "base_rate", "trained_through", "rows")},
        "legs": [],
    }

    for strike, opt_type, target in legs:
        c = resolve(strike, opt_type, contracts)
        if not c:
            out["legs"].append({"strike": strike, "opt_type": opt_type,
                                "error": "contract not found"})
            continue
        df = cache.get(inst, c["instrument_key"], days=S.OPTION_HISTORY_DAYS)
        if df.empty:
            out["legs"].append({"strike": strike, "opt_type": opt_type,
                                "error": "no candles"})
            continue
        df["opt_type"]  = opt_type
        df["strike"]    = strike
        df["moneyness"] = (strike - spot) / spot if spot else 0.0
        df["dte"]       = [(c["expiry"] - t.date()).days for t in df["ts"]]
        feat = engineer.build(df, idx)

        last  = float(df["close"].iloc[-1])
        req   = target / max(last, 0.05) - 1.0
        row   = feat.iloc[[-1]].copy()
        row["f_req_move"] = req
        for f in feats:
            if f not in row:
                row[f] = 0.0
        p = float(booster.predict(row[feats])[0])

        out["legs"].append({
            "strike": strike, "opt_type": opt_type,
            "instrument_key": c["instrument_key"],
            "expiry": str(c["expiry"]),
            "last_close": round(last, 2),
            "target": target,
            "required_move_pct": round(req * 100, 2),
            "p_hit": round(p, 4),
            "as_of_bar": str(df["ts"].iloc[-1]),
        })

    ok = [l for l in out["legs"] if "p_hit" in l]
    if len(ok) == 2:
        hi, lo = sorted(ok, key=lambda l: -l["p_hit"])
        out["comparison"] = {
            "higher": f"{int(hi['strike'])} {hi['opt_type']}",
            "higher_p": hi["p_hit"],
            "lower":  f"{int(lo['strike'])} {lo['opt_type']}",
            "lower_p": lo["p_hit"],
            "ratio": round(hi["p_hit"] / max(lo["p_hit"], 1e-9), 2),
        }

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=2)

    print(json.dumps(out, indent=2))
    print(f"\nwritten: {a.out}")


if __name__ == "__main__":
    main()
