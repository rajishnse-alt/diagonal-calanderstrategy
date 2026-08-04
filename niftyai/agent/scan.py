"""
WRAPPER 2 — background scanner across NIFTY / BANKNIFTY / SENSEX.

Evaluates every instrument on the same rules and RANKS the armed setups by the
reward-to-risk they actually offer, rather than trading whichever one is
looked at first:

    expected R = (Tg - entry) / (k x ATR)

That is the same geometry learn.py tunes, so the scanner and the learner agree
on what "good" means. Only setups whose expected R clears MIN_RR are proposed —
a triggered setup offering 0.5R is a losing trade taken on time.

Ranking by expected R also handles the instrument choice implicitly: BANKNIFTY
premiums move differently from NIFTY's, and the R calculation normalises that,
so the comparison is like-for-like instead of "bigger premium looks better".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from niftyai.agent import paper as P, params as PR, rules as R   # noqa: E402
from niftyai.collector import snapshot as SNAP                    # noqa: E402
from niftyai.config import settings as S                          # noqa: E402

RET, LOW, HIGH, TAR = 0.1306, 0.1929, 0.1504, 0.2611
MIN_RR = 1.5          # below this the setup is not worth the risk
DECISIONS = "niftyai/agent/decisions"


def _series(key):
    from datetime import timedelta
    to = datetime.now(SNAP.IST).date()
    return SNAP.bars(key, to, to - timedelta(days=12))


def evaluate(instrument, params):
    """Return a ranked-candidate dict for one instrument, or None."""
    snap = SNAP.snapshot(instrument)
    if not snap or snap.get("pcr") is None or snap.get("spot_hma") is None:
        return None
    pcr, spot, s_hma, atm = snap["pcr"], snap["spot"], snap["spot_hma"], snap["atm"]
    step = S.cfg(instrument)["strike_step"]

    ce_b = R.Band(snap["anchor_ce_h"], round((snap["anchor_ce_h"] or 0) * (1 - RET), 2),
                  snap["anchor_ce_ltp"]) if snap["anchor_ce_h"] else None
    pe_b = R.Band(snap["anchor_pe_h"], round((snap["anchor_pe_h"] or 0) * (1 - RET), 2),
                  snap["anchor_pe_ltp"]) if snap["anchor_pe_h"] else None
    if not ce_b or not pe_b:
        return None

    side = "BULLISH" if pcr > R.PCR_BULL else ("BEARISH" if pcr < R.PCR_BEAR else None)
    if side is None:
        return {"instrument": instrument, "pcr": pcr, "side": None,
                "reason": f"PCR {pcr} between {R.PCR_BEAR} and {R.PCR_BULL}"}

    typ = "CE" if side == "BULLISH" else "PE"
    anchor_h = pe_b.high if side == "BULLISH" else ce_b.high
    lo = anchor_h * LOW
    hi = lo * (1 + HIGH)
    mid = (lo + hi) / 2

    rows = [r for r in SNAP.contracts(instrument)
            if r["type"] == typ and abs(r["strike"] - atm) <= 10 * step]
    if not rows:
        return None
    exp = min(r["expiry"] for r in rows)
    best = None
    for r in [x for x in rows if x["expiry"] == exp]:
        b = _series(r["key"])
        if len(b) < 60:
            continue
        today = [x for x in b if str(x[0])[:10] == str(datetime.now(SNAP.IST).date())]
        first5 = float((today or b)[0][4])
        d = abs(first5 - mid)
        if best is None or d < best[0]:
            best = (d, r, b, today or b[-75:])
    if best is None:
        return None
    _, r, b, today = best
    closes = [float(x[4]) for x in b]
    cand = R.Candidate(strike=int(r["strike"]), opt_type=typ, ltp=closes[-1],
                       proj_high=round(hi, 2), target=round(hi * (1 + TAR), 2),
                       hma=SNAP.hma(closes),
                       day_low=min(float(x[3]) for x in today))
    sig = (R.bullish(instrument, pcr, spot, s_hma, pe_b, cand) if side == "BULLISH"
           else R.bearish(instrument, pcr, spot, s_hma, ce_b, cand))

    a = P.atr(b)
    k = PR.stop_mult_for(params, (a / cand.ltp) if (a and cand.ltp) else None)
    sl = P.initial_stop(cand.day_low, cand.ltp, a, k)
    risk = max(cand.ltp - sl, 1e-9)
    exp_r = (cand.target - cand.ltp) / risk
    return {
        "instrument": instrument, "side": side, "pcr": pcr, "spot": spot,
        "spot_hma": s_hma, "expiry": str(exp),
        "strike": cand.strike, "opt_type": typ, "ltp": round(cand.ltp, 2),
        "proj_high": cand.proj_high, "target": cand.target,
        "hma": round(cand.hma, 2) if cand.hma else None,
        "atr": round(a, 2) if a else None, "k": k,
        "stop": sl, "risk_per_lot": round(risk, 2),
        "expected_r": round(exp_r, 2),
        "armed": sig.armed, "triggered": sig.triggered,
        "tradeable": bool(sig.triggered and exp_r >= MIN_RR),
        "reasons": sig.reasons,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default="NIFTY,BANKNIFTY,SENSEX")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    params = PR.load()
    out = []
    for name in [x.strip().upper() for x in a.instruments.split(",") if x.strip()]:
        try:
            r = evaluate(name, params)
        except Exception as e:
            r = {"instrument": name, "error": f"{type(e).__name__}: {e}"}
        if r:
            out.append(r)

    ranked = sorted([r for r in out if r.get("expected_r") is not None],
                    key=lambda r: -r["expected_r"])
    print(f"{'instrument':<11}{'side':<9}{'PCR':>7}{'strike':>8}{'ltp':>8}"
          f"{'stop':>8}{'expR':>7}  state")
    for r in ranked:
        state = ("TRADE" if r["tradeable"] else
                 "triggered/lowRR" if r["triggered"] else
                 "armed" if r["armed"] else "no setup")
        print(f"{r['instrument']:<11}{r['side'] or '-':<9}{r['pcr']:>7.4f}"
              f"{r['strike']:>8}{r['ltp']:>8.2f}{r['stop']:>8.2f}"
              f"{r['expected_r']:>7.2f}  {state}")
    for r in out:
        if r.get("expected_r") is None:
            print(f"{r['instrument']:<11}{'-':<9}{'':>7}{'':>8}{'':>8}{'':>8}{'':>7}  "
                  f"{r.get('reason') or r.get('error') or 'no data'}")

    pick = next((r for r in ranked if r["tradeable"]), None)
    print("\nDECISION:", (f"{pick['instrument']} {pick['strike']}{pick['opt_type']} "
                          f"expR {pick['expected_r']}") if pick
          else f"stand aside — nothing triggered with expR >= {MIN_RR}")
    if a.write:
        os.makedirs(DECISIONS, exist_ok=True)
        p = os.path.join(DECISIONS, f"{datetime.now(SNAP.IST):%Y-%m-%d}.jsonl")
        with open(p, "a") as f:
            f.write(json.dumps({"ts": datetime.now(SNAP.IST).isoformat(timespec="seconds"),
                                "ranked": ranked, "pick": pick}) + "\n")
        print("written:", p)


if __name__ == "__main__":
    main()
