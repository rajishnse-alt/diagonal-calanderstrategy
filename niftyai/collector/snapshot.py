"""
WRAPPER 1 — unattended market-data capture.

Runs in GitHub Actions from 09:00 IST whether or not the Streamlit app is ever
opened. That was the whole problem: PCR was only written while someone had the
app running, which is why 2026-08-03 has three rows and 2026-07-22 has 109.

NO ACCESS TOKEN. The option chain endpoint needs auth, but open interest is
column 6 of the PUBLIC historical-candle response:

    ['2026-08-03T15:35:00+05:30', 14.85, 16.3, 13.5, 14.45, 2651675, 5685290]
     ts                            o      h     l     c     volume    OI

so PCR = sum(PE OI) / sum(CE OI) is computable without logging in anywhere.
Verified on NSE_FO|65859: OI ranges 3.7M .. 11.2M across the session.

Writes one row per instrument per run to niftyai/data_log/<INST>_<YYYY-MM>.csv,
month-partitioned so a closed month's file stops changing and git stores it once.
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
from niftyai.config import settings as S      # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
H   = {"Accept": "application/json"}
V3  = "https://api.upstox.com/v3/historical-candle"
CDN = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
OUT = "niftyai/data_log"

FIELDS = ["ts", "instrument", "expiry", "spot", "atm", "pcr", "ce_oi", "pe_oi",
          "strikes", "spot_hma", "anchor_ce_h", "anchor_ce_ltp",
          "anchor_pe_h", "anchor_pe_ltp", "source"]


def _get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=H, timeout=45)
            if r.status_code == 200:
                return (r.json().get("data") or {}).get("candles") or []
        except requests.RequestException:
            pass
    return []


def bars(key, to, frm):
    e = urllib.parse.quote(key, safe="")
    c = _get(f"{V3}/{e}/minutes/5/{to}/{frm}")
    c += _get(f"{V3}/intraday/{e}/minutes/5")
    seen, out = set(), []
    for x in sorted(c, key=lambda r: str(r[0])):     # sort, never assume order
        if str(x[0]) not in seen:
            seen.add(str(x[0])); out.append(x)
    return out


def wma(v, n):
    if len(v) < n:
        return None
    w = v[-n:]
    return sum(x * (i + 1) for i, x in enumerate(w)) / (n * (n + 1) / 2)


def hma(closes, length=50):
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


_INST = None


def contracts(instrument):
    global _INST
    if _INST is None:
        raw = requests.get(CDN, timeout=180).content
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        _INST = json.loads(raw)
    c = S.cfg(instrument)
    today = datetime.now(IST).date()
    rows = []
    for i in _INST:
        if not isinstance(i, dict) or i.get("segment") != c["segment"]:
            continue
        if i.get("instrument_type") not in ("CE", "PE"):
            continue
        if i.get("underlying_key") != c["underlying_key"]:
            continue
        v = i.get("expiry")
        n = float(v)
        e = datetime.fromtimestamp(n / 1000 if n > 1e11 else n, IST).date()
        if e < today:
            continue
        rows.append({"key": i["instrument_key"], "strike": float(i["strike_price"]),
                     "type": i["instrument_type"], "expiry": e})
    return rows


def snapshot(instrument, band_steps=12):
    """One row of state for the agent. Returns dict or None."""
    c = S.cfg(instrument)
    step = c["strike_step"]
    to = datetime.now(IST).date()
    frm = to - timedelta(days=12)

    idx = bars(c["underlying_key"], to, frm)
    if not idx:
        return None
    closes = [float(x[4]) for x in idx]
    spot = closes[-1]
    atm = int(round(spot / step) * step)

    rows = contracts(instrument)
    if not rows:
        return None
    exp = min(r["expiry"] for r in rows)
    near = [r for r in rows if r["expiry"] == exp
            and abs(r["strike"] - atm) <= band_steps * step]

    ce_oi = pe_oi = 0.0
    n_str = 0
    anchor = {"CE": (None, None), "PE": (None, None)}
    for r in near:
        b = bars(r["key"], to, frm)
        if not b:
            continue
        today_b = [x for x in b if str(x[0])[:10] == str(to)] or b[-75:]
        last = today_b[-1]
        oi = float(last[6]) if len(last) > 6 and last[6] else 0.0
        if r["type"] == "CE":
            ce_oi += oi
        else:
            pe_oi += oi
        n_str += 1
        if int(r["strike"]) == atm:
            hi = max(float(x[2]) for x in today_b)
            anchor[r["type"]] = (round(hi, 2), float(last[4]))

    pcr = round(pe_oi / ce_oi, 4) if ce_oi else None
    return {
        "ts": datetime.now(IST).isoformat(timespec="seconds"),
        "instrument": instrument, "expiry": str(exp),
        "spot": round(spot, 2), "atm": atm, "pcr": pcr,
        "ce_oi": round(ce_oi), "pe_oi": round(pe_oi), "strikes": n_str,
        "spot_hma": round(hma(closes), 2) if hma(closes) else None,
        "anchor_ce_h": anchor["CE"][0], "anchor_ce_ltp": anchor["CE"][1],
        "anchor_pe_h": anchor["PE"][0], "anchor_pe_ltp": anchor["PE"][1],
        "source": "public-candle-OI",
    }


def write(row):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f"{row['instrument']}_{row['ts'][:7]}.csv")
    new = not os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k) for k in FIELDS})
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default="NIFTY,BANKNIFTY,SENSEX")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    for name in [x.strip().upper() for x in a.instruments.split(",") if x.strip()]:
        try:
            row = snapshot(name)
        except SystemExit:
            raise
        except Exception as e:
            print(f"{name}: FAILED {type(e).__name__}: {e}")
            continue
        if not row:
            print(f"{name}: no data")
            continue
        print(f"{name}: spot {row['spot']} atm {row['atm']} PCR {row['pcr']} "
              f"({row['strikes']} strikes, CE {row['ce_oi']:,} PE {row['pe_oi']:,})")
        if not a.dry_run:
            print(f"   -> {write(row)}")


if __name__ == "__main__":
    main()
