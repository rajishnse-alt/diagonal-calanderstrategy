"""
Daily learning pass — adjusts the stop multiplier from realised trades.

THE LEVER, and why it is this one:
    risk = k x ATR, and the target is fixed by the card (Tg). So
        R_at_target = (Tg - entry) / (k x ATR)
    and the k that would put the target exactly on the 1:3 mandate is
        k* = (Tg - entry) / (RR_TARGET x ATR)
    Measured on 2026-08-03: at k=1.5 risk was 3.36 and Tg only 1.54R. No
    amount of patience fixes that — the geometry has to change.

BUT k IS TWO-SIDED. Shrinking it lifts R at the target and simultaneously
raises the stop-out rate, so this optimises against BOTH: it moves toward k*
only while stop-outs stay under MAX_STOP_RATE, and backs off when they do not.
A one-sided objective would drive k to its floor and stop out on every tick.

Guardrails: minimum sample before acting, a capped step per run, and the hard
clamps in params.py. Learning on three trades is noise-fitting.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from niftyai.agent import journal as J, params as PR      # noqa: E402

MIN_TRADES     = 5      # below this, report only
MAX_STEP       = 0.15   # most k may move in one pass
MAX_STOP_RATE  = 0.55   # stop-outs above this = k is too tight
LOG_FMT = "niftyai/agent/learning_log_{}.md"


def _rows(instrument):
    path, _ = J._paths(instrument)
    if not os.path.exists(path):
        return []
    out = []
    for r in csv.DictReader(open(path)):
        try:
            r["r_multiple"] = float(r["r_multiple"])
            r["entry"] = float(r["entry"])
            r["target"] = float(r["target"])
            r["risk_per_lot"] = float(r["risk_per_lot"])
        except (TypeError, ValueError):
            continue
        out.append(r)
    return out


def analyse(instrument):
    rows = _rows(instrument)
    if not rows:
        return {"trades": 0}
    rs = [r["r_multiple"] for r in rows]
    stopped = [r for r in rows if "SL@" in (r.get("exits") or "")
               and "TARGET" not in (r.get("exits") or "")]
    # what k would have placed the target exactly at RR_TARGET?
    ks = []
    for r in rows:
        reward = r["target"] - r["entry"]
        if reward > 0 and r["risk_per_lot"] > 0:
            r_at_tgt = reward / r["risk_per_lot"]
            if r_at_tgt > 0:
                # risk must shrink by this factor, and risk is linear in k
                ks.append(r_at_tgt / PR.DEFAULTS["rr_target"])
    return {
        "trades": len(rows),
        "avg_r": round(sum(rs) / len(rs), 3),
        "win_rate": round(sum(1 for x in rs if x > 0) / len(rs), 3),
        "met_1_3": sum(1 for x in rs if x >= 3),
        "stop_rate": round(len(stopped) / len(rows), 3),
        "k_scale_needed": round(sum(ks) / len(ks), 3) if ks else None,
    }


def update(instrument, apply=True, min_trades=None):
    p = PR.load(instrument)
    a = analyse(instrument)
    note = []
    _floor = MIN_TRADES if min_trades is None else min_trades
    if a.get("trades", 0) < _floor:
        note.append(f"only {a.get('trades',0)} trades — need {_floor} before "
                    f"touching parameters; reporting only")
        a["action"] = "report_only"
        _log(instrument, a, p, note)
        return a, p

    cur = p["atr_stop_mult"]
    scale = a.get("k_scale_needed")
    target_k = cur * scale if scale else cur

    if a["stop_rate"] > MAX_STOP_RATE:
        # too many stops — loosen regardless of what the R geometry wants
        target_k = cur * 1.15
        note.append(f"stop rate {a['stop_rate']} > {MAX_STOP_RATE}: loosening")
    else:
        note.append(f"stop rate {a['stop_rate']} acceptable; moving k toward "
                    f"the value that puts Tg at 1:3")

    step = max(-MAX_STEP, min(MAX_STEP, target_k - cur))
    new_k = PR.clamp(p, "atr_stop_mult", cur + step)
    note.append(f"k {cur:.3f} -> {new_k:.3f} (wanted {target_k:.3f}, "
                f"step capped at {MAX_STEP})")

    if apply:
        p["atr_stop_mult"] = round(new_k, 3)
        meta = p.setdefault("_meta", {})
        meta["trades_seen"] = a["trades"]
        meta["last_update"] = datetime.now().isoformat(timespec="seconds")
        PR.save(p, instrument)
    a["action"] = "updated" if apply else "dry_run"
    a["k_before"], a["k_after"] = round(cur, 3), round(new_k, 3)
    _log(instrument, a, p, note)
    return a, p


def _log(instrument, a, p, notes):
    LOG = LOG_FMT.format(instrument.upper())
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    prev = open(LOG).read() if os.path.exists(LOG) else ""
    hdr = "# Agent learning log\n"
    body = prev[len(hdr):] if prev.startswith(hdr) else prev
    entry = (f"\n## {datetime.now().isoformat(timespec='seconds')} — {instrument}\n\n"
             f"```\n{json.dumps(a, indent=2)}\n```\n"
             + "".join(f"- {n}\n" for n in notes))
    with open(LOG, "w") as f:
        f.write(hdr + entry + body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="NIFTY")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-trades", type=int, default=None,
                    help="override the sample floor (demonstration only)")
    args = ap.parse_args()
    stats, params = update(args.instrument, apply=not args.dry_run,
                           min_trades=args.min_trades)
    print(json.dumps(stats, indent=2))
    print(f"atr_stop_mult now {params['atr_stop_mult']}")
