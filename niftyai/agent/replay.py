"""
Replay the agent over a real session, bar by bar, with no look-ahead.

Every value at bar t is built only from bars <= t: the anchor's running day
high, the projections off it, the candidate's HMA and day low. That is the
whole point — a backtest that peeks at the closing high would arm setups the
live agent could never have seen.

    python niftyai/agent/replay.py --date 2026-08-03 --expiry 2026-08-04
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from niftyai.agent import journal as J, paper as P, params as PR, rules as R  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
H   = {"Accept": "application/json"}
V3  = "https://api.upstox.com/v3/historical-candle"
CDN = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"

RET, LOW, HIGH, TAR = 0.1306, 0.1929, 0.1504, 0.2611   # SPCL constants


def wma(v, n):
    if len(v) < n:
        return None
    w = v[-n:]
    return sum(x * (i + 1) for i, x in enumerate(w)) / (n * (n + 1) / 2)


def hma_at(closes, length=50):
    """HMA at the END of `closes`. None when short."""
    n, half, sq = length, length // 2, int(round(math.sqrt(length)))
    if len(closes) < n + sq:
        return None
    raw = []
    for j in range(len(closes) - sq, len(closes)):
        a, b = wma(closes[:j + 1], half), wma(closes[:j + 1], n)
        if a is None or b is None:
            return None
        raw.append(2 * a - b)
    return wma(raw, sq)


def candles(key, to, frm):
    e = urllib.parse.quote(key, safe="")
    try:
        r = requests.get(f"{V3}/{e}/minutes/5/{to}/{frm}", headers=H, timeout=45)
        c = (r.json().get("data") or {}).get("candles") or []
    except requests.RequestException:
        return []
    return sorted(c, key=lambda x: str(x[0]))          # oldest-first, never assume


def instruments():
    raw = requests.get(CDN, timeout=180).content
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass
    return json.loads(raw)


def exp_of(v):
    n = float(v)
    return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, IST).date()


def pcr_series(path, day):
    """{HH:MM: pcr_range} from the repo's own near-expiry PCR log."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for row in csv.DictReader(f):
            if row.get("date") == day and row.get("expiry_type") == "near":
                try:
                    out[row["timestamp"][11:16]] = float(row["pcr_range"])
                except (ValueError, KeyError):
                    pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--expiry", required=True)
    ap.add_argument("--anchor", type=int, default=None, help="ATM anchor strike")
    ap.add_argument("--instrument", default="NIFTY")
    ap.add_argument("--index-key", default="NSE_INDEX|Nifty 50")
    ap.add_argument("--pcr", default="pcr_data/pcr_log_nifty.csv")
    ap.add_argument("--max-trades", type=int, default=3)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--journal", action="store_true",
                    help="append closed trades to niftyai/journal/ (committed to git)")
    a = ap.parse_args()

    day = a.date
    exp = datetime.strptime(a.expiry, "%Y-%m-%d").date()
    frm = (datetime.strptime(day, "%Y-%m-%d").date() - timedelta(days=12)).isoformat()

    inst = instruments()
    opts = [i for i in inst if isinstance(i, dict) and i.get("segment") == "NSE_FO"
            and i.get("underlying_key") == a.index_key
            and i.get("instrument_type") in ("CE", "PE")
            and exp_of(i["expiry"]) == exp]
    if not opts:
        sys.exit(f"no contracts for expiry {exp}")

    idx = candles(a.index_key, day, frm)
    today_idx = [c for c in idx if str(c[0])[:10] == day]
    if not today_idx:
        sys.exit(f"no index bars for {day}")
    anchor = a.anchor or int(round(float(today_idx[0][4]) / 50) * 50)
    print(f"[{a.instrument}] {day}  expiry {exp}  anchor {anchor}  "
          f"index bars {len(today_idx)}")

    def key_for(strike, typ):
        m = [o for o in opts if o["instrument_type"] == typ
             and abs(float(o["strike_price"]) - strike) < 1]
        return m[0]["instrument_key"] if m else None

    series = {}
    for typ in ("CE", "PE"):
        k = key_for(anchor, typ)
        series[("anchor", typ)] = candles(k, day, frm) if k else []

    pcrs = pcr_series(a.pcr, day)
    if not pcrs:
        print("!! no PCR rows for this date — the PCR gate cannot be evaluated")
    idx_closes = [float(c[4]) for c in idx]
    idx_pos = {str(c[0]): i for i, c in enumerate(idx)}

    # candidate universe: strikes around the anchor, cached per side
    cand_keys = {}
    for off in range(-2, 9):
        for typ in ("CE", "PE"):
            s = anchor + off * 50
            k = key_for(s, typ)
            if k:
                cand_keys[(s, typ)] = k
    cand_series = {}

    def bars(strike, typ):
        if (strike, typ) not in cand_series:
            cand_series[(strike, typ)] = candles(cand_keys[(strike, typ)], day, frm)
        return cand_series[(strike, typ)]

    PARAMS = PR.load()
    trades, open_t, last_pcr = [], None, None
    day_bars = [c for c in series[("anchor", "CE")] if str(c[0])[:10] == day]
    print(f"anchor bars today: {len(day_bars)}\n")
    print(f"{'time':<6}{'PCR':>7}{'spot':>10}{'spotHMA':>9}  gate")

    for bar in day_bars:
        ts = str(bar[0]); hhmm = ts[11:16]
        # Forward-fill: the PCR log is written every ~3 min (10:03, 10:12...),
        # which never lands exactly on a 5-min bar boundary. Exact matching
        # meant last_pcr stayed None all session and no gate was ever evaluated.
        _av = [(t, v) for t, v in pcrs.items() if t <= hhmm]
        if _av:
            last_pcr = max(_av)[1]
        if last_pcr is None:
            continue
        ip = idx_pos.get(ts)
        if ip is None:
            continue
        spot = idx_closes[ip]
        s_hma = hma_at(idx_closes[:ip + 1])
        if s_hma is None:
            continue

        def anchor_band(typ):
            rows = [c for c in series[("anchor", typ)]
                    if str(c[0])[:10] == day and str(c[0]) <= ts]
            if not rows:
                return None
            hi = max(float(r[2]) for r in rows)
            return R.Band(high=round(hi, 2), low=round(hi * (1 - RET), 2),
                          ltp=float(rows[-1][4]))

        ce_b, pe_b = anchor_band("CE"), anchor_band("PE")
        if not ce_b or not pe_b:
            continue

        # cross-leg projections, both directions
        pce_lo = pe_b.high * LOW;  pce_hi = pce_lo * (1 + HIGH)
        ppe_lo = ce_b.high * LOW;  ppe_hi = ppe_lo * (1 + HIGH)

        def candidate(typ, lo, hi):
            mid = (lo + hi) / 2
            best = None
            for (s, t), _ in cand_keys.items():
                if t != typ:
                    continue
                rows = [c for c in bars(s, t) if str(c[0])[:10] == day]
                if not rows:
                    continue
                first5 = float(rows[0][4])
                d = abs(first5 - mid)
                if best is None or d < best[0]:
                    best = (d, s)
            if best is None:
                return None, None
            s = best[1]
            rows = [c for c in bars(s, typ) if str(c[0]) <= ts]
            today_rows = [c for c in rows if str(c[0])[:10] == day]
            if not today_rows:
                return None, None
            cl = [float(c[4]) for c in rows]
            return R.Candidate(
                strike=s, opt_type=typ, ltp=cl[-1],
                proj_high=round(hi, 2), target=round(hi * (1 + TAR), 2),
                hma=hma_at(cl),
                day_low=min(float(c[3]) for c in today_rows),
            ), today_rows

        sig = None
        if last_pcr > R.PCR_BULL:
            c, rows = candidate("CE", pce_lo, pce_hi)
            if c:
                sig = R.bullish(a.instrument, last_pcr, spot, s_hma, pe_b, c)
        elif last_pcr < R.PCR_BEAR:
            c, rows = candidate("PE", ppe_lo, ppe_hi)
            if c:
                sig = R.bearish(a.instrument, last_pcr, spot, s_hma, ce_b, c)

        gate = "-"
        if sig:
            gate = ("TRIGGERED" if sig.triggered else
                    ("armed" if sig.armed else "no"))
        print(f"{hhmm:<6}{last_pcr:>7.4f}{spot:>10.2f}{s_hma:>9.2f}  {gate}"
              + (f"  {sig.candidate.strike}{sig.candidate.opt_type} "
                 f"ltp {sig.candidate.ltp:.2f} projH {sig.candidate.proj_high:.2f} "
                 f"hma {sig.candidate.hma if sig.candidate.hma is None else round(sig.candidate.hma,2)}"
                 if sig else ""))

        # manage an open position on this bar
        if open_t and open_t.status == "OPEN":
            orows = [c for c in bars(open_t.strike, open_t.opt_type)
                     if str(c[0]) <= ts]
            if orows:
                av = P.atr(orows)
                for f in open_t.update(ts, float(orows[-1][4]), av):
                    print(f"        FILL {f['why']} {f['lots']} lots @ {f['price']}")
                if open_t.status == "CLOSED":
                    trades.append(open_t); open_t = None

        if (sig and sig.triggered and open_t is None
                and len(trades) < a.max_trades and sig.candidate.day_low):
            _crows = [c for c in bars(sig.candidate.strike, sig.candidate.opt_type)
                      if str(c[0]) <= ts]
            _catr = P.atr(_crows)
            open_t = P.open_trade(sig, ts, sig.candidate.day_low,
                                  atr_val=_catr, params=PARAMS)
            print(f"        ENTER {open_t.strike}{open_t.opt_type} {open_t.lots} lots "
                  f"@ {open_t.entry:.2f}  SL {open_t.sl:.2f}  Tg {open_t.target:.2f}"
                  f"  (risk {open_t.risk_per_lot:.2f}/lot, 1:3 needs "
                  f"{open_t.reward_needed:.2f})")

    if open_t:
        last = [c for c in bars(open_t.strike, open_t.opt_type)
                if str(c[0])[:10] == day][-1]
        open_t._exit(str(last[0]), open_t.lots_open, float(last[4]), "EOD")
        trades.append(open_t)

    print(f"\n{'='*70}\nTRADES: {len(trades)}")
    for t in trades:
        print(f"  {t.strike}{t.opt_type} {t.side} entry {t.entry:.2f} "
              f"SL {t.init_sl:.2f} Tg {t.target:.2f} -> "
              f"{t.pnl_per_lot:+.2f}/lot  R {t.r_multiple:+.2f}")
        for e in t.exits:
            print(f"      {e['ts'][11:16]}  {e['why']:<12} {e['lots']} @ {e['price']}")
    if a.journal:
        for t in trades:
            J.record(t, note=f"replay of {day}, expiry {exp}")
        print(f"\njournal: {J.stats(a.instrument)}")
    if trades:
        rs = [t.r_multiple for t in trades if t.r_multiple is not None]
        wins = [r for r in rs if r > 0]
        print(f"\n  avg R {sum(rs)/len(rs):+.2f}   wins {len(wins)}/{len(rs)}"
              f"   met 1:3 {sum(1 for r in rs if r >= 3)}/{len(rs)}")
    if a.json_out:
        os.makedirs(os.path.dirname(a.json_out), exist_ok=True)
        with open(a.json_out, "w") as f:
            json.dump([t.to_dict() for t in trades], f, indent=2)
        print(f"\nwritten: {a.json_out}")


if __name__ == "__main__":
    main()
