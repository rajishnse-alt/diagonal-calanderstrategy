"""
First 5-minute Spot vs Future referral candle.

RULE
  1. 5-min candles for the SPOT and the FRONT-MONTH FUTURE.
  2. Count "common points": each of the future's O/H/L/C that falls inside the
     spot's L..H, plus each of the spot's O/H/L/C inside the future's L..H.
     8 points total. A candle qualifies when the count is > 6 or < 3.
  3. That candle is the referral candle for BOTH instruments. Mark the outer
     envelope — the higher of the two highs and the lower of the two lows —
     labelled by whichever side owns it: SH/FH and SL/FL.

THE BASIS PROBLEM — READ BEFORE TRUSTING THE RAW COUNT.
Raw prices are compared, so the two ranges must be able to overlap at all. They
can only do that when the basis is small, and the basis is NOT small all cycle:

    2026-07-15  JUL front, ~1 day to expiry : basis  +4.90 -> 6 of 8 raw
    2026-08-05  AUG front, 20 days to expiry: basis +82.90 -> 2 of 8 on the
                first candle and 0 of 8 on every one after

At +83 no spot value can sit inside the future's range, so the raw count
collapses and EVERY candle scores "<3" and qualifies: 75 of 75 on 2026-08-05.
The rule stops discriminating entirely. This is not a wrong-contract error —
NSE_FO|58072 IS the front month; the basis genuinely is that wide early in a
contract cycle and only converges to zero at expiry.

So both counts are computed and reported: raw (as specified) and basis-adjusted
(future shifted onto spot by F.C - S.C, comparing candle SHAPE). On 2026-08-05
adjusted gave 2 of 75 qualifying against raw's 75 of 75. The scanner flags the
degeneracy rather than silently marking every candle a referral.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from niftyai.config import settings as S      # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
H   = {"Accept": "application/json"}
V3  = "https://api.upstox.com/v3/historical-candle"
CDN = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"

MATCH_HIGH = 6      # strictly MORE than this
MATCH_LOW  = 3      # strictly LESS than this
OUT = "niftyai/data_log/referral"

_DUMP = None


def _get(url, tries=3):
    for _ in range(tries):
        try:
            r = requests.get(url, headers=H, timeout=45)
            if r.status_code == 200:
                return (r.json().get("data") or {}).get("candles") or []
        except requests.RequestException:
            pass
    return []


def bars(key, day):
    """5-min candles for one session, oldest-first. Sorted, never assumed."""
    e = urllib.parse.quote(key, safe="")
    c = _get(f"{V3}/{e}/minutes/5/{day}/{day}")
    if not c:
        c = _get(f"{V3}/intraday/{e}/minutes/5")
    return sorted(c, key=lambda x: str(x[0]))


def front_future(instrument):
    """
    (instrument_key, expiry) of the NEAREST-expiry future — the front month.
    Matches on underlying_key, which also excludes NIFTYNXT50.
    """
    global _DUMP
    if _DUMP is None:
        raw = requests.get(CDN, timeout=180).content
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        _DUMP = json.loads(raw)
    c = S.cfg(instrument)
    today = datetime.now(IST).date()
    best = None
    for i in _DUMP:
        if not isinstance(i, dict) or i.get("instrument_type") != "FUT":
            continue
        if i.get("underlying_key") != c["underlying_key"]:
            continue
        n = float(i.get("expiry") or 0)
        e = datetime.fromtimestamp(n / 1000 if n > 1e11 else n, IST).date()
        if e < today:
            continue
        if best is None or e < best[1]:
            best = (i["instrument_key"], e)
    return best or (None, None)


def ohlc(row):
    return {"O": float(row[1]), "H": float(row[2]),
            "L": float(row[3]), "C": float(row[4])}


def common_points_adj(s, f):
    """
    Same count, but with the future shifted onto spot by the basis (F.C - S.C)
    first — so it compares candle SHAPE rather than absolute level.

    Needed because the basis is not small all cycle. Measured on NIFTY:
        2026-07-15, JUL front, 1 day from expiry : basis  +4.90 -> 6 of 8
        2026-08-05, AUG front, 20 days out      : basis +82.90 -> 2 of 8, and
                                                  0 of 8 on every later candle
    At a large basis NO spot value can fall inside the future's range, so the
    raw count collapses to 0-2 and EVERY candle scores "<3" and qualifies —
    the rule stops discriminating. Reported alongside the raw count so the
    degeneracy is visible instead of silently firing on all 75 candles.
    """
    b = f["C"] - s["C"]
    return common_points(s, {k: v - b for k, v in f.items()})


def common_points(s, f):
    """
    How many of the 8 OHLC values sit inside the OTHER instrument's L..H.
    Returns (count, detail) — detail names each point so a disputed count can
    be checked rather than argued about.
    """
    detail, n = {}, 0
    for k, v in f.items():
        hit = s["L"] <= v <= s["H"]
        detail[f"F.{k}"] = hit
        n += hit
    for k, v in s.items():
        hit = f["L"] <= v <= f["H"]
        detail[f"S.{k}"] = hit
        n += hit
    return n, detail


def qualifies(n):
    return n > MATCH_HIGH or n < MATCH_LOW


def levels(s, f):
    """Outer envelope of both instruments, labelled by owner."""
    if f["H"] >= s["H"]:
        hi, hi_lbl = f["H"], "FH"
    else:
        hi, hi_lbl = s["H"], "SH"
    if f["L"] <= s["L"]:
        lo, lo_lbl = f["L"], "FL"
    else:
        lo, lo_lbl = s["L"], "SL"
    return {"high": round(hi, 2), "high_label": hi_lbl,
            "low": round(lo, 2), "low_label": lo_lbl,
            "range": round(hi - lo, 2)}


def find(instrument="NIFTY", day=None, scan_all=True):
    """
    Referral candle for one session.

    scan_all=True  -> first candle of the session that qualifies (>6 or <3)
    scan_all=False -> only the 09:15 candle is considered
    """
    day = day or str(datetime.now(IST).date())
    fkey, fexp = front_future(instrument)
    if not fkey:
        return {"instrument": instrument, "day": day, "error": "no front-month future"}
    skey = S.cfg(instrument)["underlying_key"]
    sb, fb = bars(skey, day), bars(fkey, day)
    if not sb or not fb:
        return {"instrument": instrument, "day": day,
                "error": f"no bars (spot {len(sb)}, future {len(fb)})"}

    fmap = {str(r[0])[:16]: r for r in fb}
    out = {"instrument": instrument, "day": day, "future": fkey,
           "future_expiry": str(fexp), "scanned": 0, "candles": []}
    referral = None
    for srow in sb:
        ts = str(srow[0])[:16]
        frow = fmap.get(ts)
        if not frow:
            continue                      # no paired future bar — cannot compare
        s, f = ohlc(srow), ohlc(frow)
        n, detail = common_points(s, f)
        out["scanned"] += 1
        n_adj, _ = common_points_adj(s, f)
        rec = {"ts": ts, "matches": n, "matches_adj": n_adj,
               "qualifies": qualifies(n), "qualifies_adj": qualifies(n_adj),
               "basis": round(f["C"] - s["C"], 2),
               "spot": s, "fut": f, "detail": detail}
        out["candles"].append(rec)
        if referral is None and qualifies(n):
            referral = {**rec, **levels(s, f)}
            if not scan_all:
                break
        if not scan_all:
            break                          # only the first (09:15) candle
    out["referral"] = referral
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="NIFTY")
    ap.add_argument("--day", default=None)
    ap.add_argument("--first-only", action="store_true",
                    help="consider only the 09:15 candle")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    r = find(a.instrument, a.day, scan_all=not a.first_only)
    if r.get("error"):
        print(f"{r['instrument']} {r['day']}: {r['error']}")
        return
    print(f"{r['instrument']} {r['day']}  front future {r['future']} "
          f"(exp {r['future_expiry']})  paired candles {r['scanned']}")
    _q = sum(1 for c in r["candles"] if c["qualifies"])
    _qa = sum(1 for c in r["candles"] if c["qualifies_adj"])
    print(f"qualifying candles: raw {_q}/{r['scanned']}   "
          f"basis-adjusted {_qa}/{r['scanned']}"
          + ("   <-- raw is degenerate, basis too large"
             if _q > r["scanned"] * 0.5 else ""))
    print(f"{'time':<6}{'raw':>5}{'adj':>5}{'basis':>9}  spot H/L            fut H/L")
    for c in r["candles"][:8]:
        print(f"{c['ts'][11:]:<6}{c['matches']:>5}{c['matches_adj']:>5}{c['basis']:>9.2f}  "
              f"{c['spot']['H']:>9.2f}/{c['spot']['L']:<9.2f}  "
              f"{c['fut']['H']:>9.2f}/{c['fut']['L']:<9.2f}"
              f"{'   <-- REFERRAL' if c['qualifies'] else ''}")
    ref = r.get("referral")
    if ref:
        print(f"\nREFERRAL CANDLE {ref['ts'][11:]}  ({ref['matches']} of 8 matches)")
        print(f"   {ref['high_label']} {ref['high']:,.2f}   <- mark")
        print(f"   {ref['low_label']} {ref['low']:,.2f}   <- mark")
        print(f"   range {ref['range']:,.2f}")
    else:
        print(f"\nno referral candle — every paired candle scored "
              f"{MATCH_LOW}..{MATCH_HIGH} matches")
    if a.write:
        os.makedirs(OUT, exist_ok=True)
        p = os.path.join(OUT, f"{r['instrument']}_{r['day']}.json")
        json.dump(r, open(p, "w"), indent=2)
        print(f"written: {p}")


if __name__ == "__main__":
    main()
