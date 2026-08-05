"""
Reconcile the DERIVED PCR against the APP's published pcr_range.

WHY THIS EXISTS
    The app's PCR comes from the authenticated option chain. Upstox tokens
    expire daily, so that path can NEVER run unattended — which makes the
    derived (public OI) PCR the only candidate for a 09:00 start with nobody
    logged in. But on 2026-08-05 the two disagreed badly: derived 0.59-0.65
    against the app's logged 1.11-1.12. A gate calibrated on one and fed the
    other will simply trade the wrong side, which is exactly what happened.

    The two cannot be compared retrospectively: expired contracts vanish from
    the instrument dump, so a past row cannot be recomputed. The comparison has
    to be made from rows captured at the SAME minute while both were live.
    This runs after each session, joins the two logs on timestamp, and reports
    the ratio — so the calibration comes from data rather than a guess.

Run:  python niftyai/collector/reconcile.py --instrument NIFTY
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

APP  = {"NIFTY": "pcr_data/pcr_log_nifty.csv",
        "BANKNIFTY": "pcr_data/pcr_log_banknifty.csv",
        "SENSEX": "pcr_data/pcr_log_sensex.csv"}
MINE = "niftyai/data_log"
OUT  = "niftyai/collector/pcr_reconciliation.json"
TOL_MIN = 8          # rows within this many minutes are "the same moment"


def _app_rows(inst):
    p = APP.get(inst)
    if not p or not os.path.exists(p):
        return []
    out = []
    for r in csv.DictReader(open(p)):
        # Only rows the APP itself wrote: the collector leaves vix/spcl blank,
        # so a populated vix column identifies an app-authored row. Comparing
        # the collector against itself would prove nothing.
        if r.get("expiry_type") != "near" or not r.get("pcr_range"):
            continue
        if not (r.get("vix_curr") or r.get("spcl")):
            continue
        try:
            out.append((datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M"),
                        float(r["pcr_range"]), r.get("expiry")))
        except (ValueError, KeyError):
            continue
    return out


def _mine_rows(inst):
    if not os.path.isdir(MINE):
        return []
    out = []
    for f in sorted(os.listdir(MINE)):
        if not f.startswith(f"{inst}_") or not f.endswith(".csv"):
            continue
        for r in csv.DictReader(open(os.path.join(MINE, f))):
            try:
                out.append((datetime.fromisoformat(r["ts"]).replace(tzinfo=None),
                            float(r["pcr"]), r.get("expiry")))
            except (ValueError, KeyError, TypeError):
                continue
    return out


def reconcile(inst):
    app, mine = _app_rows(inst), _mine_rows(inst)
    pairs = []
    for at, av, aexp in app:
        best = None
        for mt, mv, mexp in mine:
            if mexp and aexp and mexp != aexp:
                continue                      # different expiry is not a pair
            d = abs((at - mt).total_seconds()) / 60
            if d <= TOL_MIN and (best is None or d < best[0]):
                best = (d, mt, mv)
        if best:
            pairs.append({"ts": at.isoformat(timespec="minutes"),
                          "app": av, "derived": best[2],
                          "ratio": round(av / best[2], 4) if best[2] else None,
                          "gap_min": round(best[0], 1)})
    res = {"instrument": inst, "pairs": len(pairs),
           "app_rows": len(app), "derived_rows": len(mine),
           "generated": datetime.now().isoformat(timespec="seconds"),
           "samples": pairs[-20:]}
    rs = [p["ratio"] for p in pairs if p["ratio"]]
    if rs:
        rs_sorted = sorted(rs)
        res["ratio_mean"] = round(sum(rs) / len(rs), 4)
        res["ratio_median"] = round(rs_sorted[len(rs_sorted) // 2], 4)
        res["ratio_min"], res["ratio_max"] = round(min(rs), 4), round(max(rs), 4)
        res["verdict"] = ("derived is usable as-is"
                          if 0.95 <= res["ratio_median"] <= 1.05 else
                          f"derived differs by x{res['ratio_median']} — thresholds "
                          f"calibrated on the app's scale must NOT be applied to it")
    else:
        res["verdict"] = ("no overlapping rows yet — the app must log at least once "
                          "while the collector is also running")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="NIFTY")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    names = list(APP) if a.all else [a.instrument.upper()]
    allres = {}
    for n in names:
        r = reconcile(n)
        allres[n] = r
        print(f"{n}: {r['pairs']} paired rows "
              f"(app {r['app_rows']}, derived {r['derived_rows']})")
        if r.get("ratio_median"):
            print(f"   ratio app/derived  median {r['ratio_median']}  "
                  f"mean {r['ratio_mean']}  range {r['ratio_min']}-{r['ratio_max']}")
        print(f"   -> {r['verdict']}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(allres, open(OUT, "w"), indent=2)
    print(f"\nwritten: {OUT}")
