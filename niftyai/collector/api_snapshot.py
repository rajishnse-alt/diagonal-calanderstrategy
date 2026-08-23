"""
The DURABLE half of the JSON API — written by GitHub Actions, not the app.

    https://raw.githubusercontent.com/rajishnse-alt/diagonal-calanderstrategy/main/api/snapshot_NIFTY.json

WHY THIS EXISTS ALONGSIDE THE APP'S OWN ENDPOINT
    diagonal_strategy.py writes the same payload to static/snapshot_<INST>.json,
    served at /app/static/... on the Streamlit domain. That one is LIVE but not
    RELIABLE: Community Cloud keeps nothing across container restarts, and a
    sleeping app writes nothing at all. This one is the reverse — a few minutes
    behind, but present whether or not anyone has ever opened the app.

    Same schema, so a client can fall back from one to the other without
    changing how it reads the payload. `source` says which produced it.

NO TOKEN REQUIRED
    Everything here comes from the PUBLIC historical-candle endpoint, including
    open interest, which is column 6 of the candle row. That is what lets this
    run unattended at 09:00 with nobody logged in.

    The fields the app derives from the AUTHENTICATED option chain — SPCL bands
    and the projected L/H — are NOT recomputed here. They are read from the
    app's own pcr_data log when it is recent, and left null when it is not.
    A null is honest; a number invented from a different source would silently
    disagree with the card and be impossible to reconcile later.

Run:  python niftyai/collector/api_snapshot.py --instruments NIFTY,BANKNIFTY,SENSEX
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from niftyai.collector import referral as R          # noqa: E402
from niftyai.collector import snapshot as SNAP       # noqa: E402
from niftyai.config import settings as CFG           # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
OUT_DIR = "api"
APP_LOG = SNAP.APP_LOG                       # reuse, do not restate the paths
APP_FRESH_MIN = 40                        # older than this is not "now"

_SPCL_TAR_PCT = 26.11                     # must track diagonal_strategy.py


def index_bars(instrument, day):
    """Today's 5-min index candles, oldest-first. Public endpoint, no token."""
    key = CFG.cfg(instrument)["underlying_key"]
    rows = R.bars(key, day) or []
    return sorted(rows, key=lambda r: str(r[0]))


def ladder(spot):
    """n^2 around round(sqrt(spot)), forced odd. Same grid the card draws."""
    root = round(math.sqrt(int(spot)))
    out = []
    for i in range(-3, 4):
        n = root + i
        v = n * n
        if v % 2 == 0:
            v += 1
        out.append({"level": v, "pivot": n == root})
    return out


def levels_from(bars):
    """
    The 5-min and day blocks.

    Support comes off the day HIGH and resistance off the day LOW - crossed on
    purpose; that is what puts the pair either side of spot.
    """
    if not bars:
        return None, None
    f = bars[0]
    fh, fl = float(f[2]), float(f[3])
    five = {"high": round(fh, 2), "low": round(fl, 2),
            "critical_resistance": round(fh * 1.002611, 2),
            "strong_support": round(fl * 0.997389, 2)}
    hi = max(float(b[2]) for b in bars)
    lo = min(float(b[3]) for b in bars if float(b[3]) > 0)
    day = {"high": round(hi, 2), "low": round(lo, 2),
           "support": round(hi - math.sqrt(hi), 2),
           "resistance": round(lo + math.sqrt(lo), 2),
           "previous_session": False}
    return five, day


def app_row(instrument):
    """
    The app's most recent log row, if it is recent enough to still describe now.

    Only rows the APP itself wrote count - the collector leaves vix and spcl
    blank, so a populated one of those identifies an app-authored row. Reading
    the collector's own rows back would prove nothing.
    """
    p = APP_LOG.get(instrument)
    if not p or not os.path.exists(p):
        return None
    best = None
    try:
        with open(p) as fh:
            for r in csv.DictReader(fh):
                if not (r.get("vix_curr") or r.get("spcl")):
                    continue
                try:
                    t = datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M")
                except (ValueError, KeyError):
                    continue
                if best is None or t > best[0]:
                    best = (t, r)
    except OSError:
        return None
    if not best:
        return None
    age = (datetime.now(IST).replace(tzinfo=None) - best[0]).total_seconds() / 60
    if age > APP_FRESH_MIN:
        return None
    return dict(best[1], _age_min=round(age, 1))


def fnum(v, dp=2):
    try:
        return None if v in (None, "") else round(float(v), dp)
    except (TypeError, ValueError):
        return None


def build(instrument, day=None):
    day = day or str(datetime.now(IST).date())
    bars = index_bars(instrument, day)
    prev_session = False
    if not bars:
        # Pre-market, holiday, or a run before the first candle prints. Fall
        # back to the last session and SAY SO, so yesterday's levels can never
        # be mistaken for today's.
        probe = datetime.now(IST).date()
        for _ in range(6):
            probe -= timedelta(days=1)
            bars = index_bars(instrument, str(probe))
            if bars:
                day, prev_session = str(probe), True
                break

    five, dayblk = levels_from(bars)
    if dayblk:
        dayblk["previous_session"] = prev_session
    spot = float(bars[-1][4]) if bars else None

    snap = None
    try:
        snap = SNAP.snapshot(instrument)
    except Exception as e:
        print(f"  {instrument}: snapshot failed - {type(e).__name__}: {e}")

    ref = {}
    try:
        r = R.find(instrument, day, scan_all=True)
        latest = (r or {}).get("latest")
        if latest:
            lv = latest["levels"]
            ref = {"time": latest["ts"][11:16], "matches": latest["matches"],
                   "qualified": len(r.get("qualifying") or []),
                   "scanned": r.get("scanned"),
                   "basis": lv["basis"], "state": lv["state"],
                   "up": {"level": lv["up_trigger"]["cross_above"],
                          "watch": lv["up_trigger"]["watch"]},
                   "down": {"level": lv["down_trigger"]["cross_below"],
                            "watch": lv["down_trigger"]["watch"]}}
        else:
            ref = {"scanned": (r or {}).get("scanned", 0), "qualified": 0,
                   "error": (r or {}).get("error")}
    except Exception as e:
        ref = {"error": f"{type(e).__name__}: {e}"}

    app = app_row(instrument)
    spcl = {"ce": None, "pe": None, "proj_pe_low": None, "proj_pe_high": None,
            "proj_ce_low": None, "proj_ce_high": None,
            "tg_pe": None, "tg_ce": None}
    if app:
        # The app publishes one SPCL figure per row; the projected legs are not
        # in the log, so they stay null rather than being back-solved.
        spcl["ce"] = spcl["pe"] = fnum(app.get("spcl"))

    return {
        "schema": 1,
        "stale": False,
        "generated": datetime.now(IST).isoformat(timespec="seconds"),
        "source": "github-actions/public-candle-OI",
        "instrument": instrument,
        "session": day,
        "expiry": (snap or {}).get("expiry"),
        "spot": fnum(spot),
        "atm": (snap or {}).get("atm"),
        "vix": fnum((app or {}).get("vix_curr")),
        "ladder": ladder(spot) if spot else [],
        "five_min": five or {},
        "day": dayblk or {},
        "referral": ref,
        "futures": {"expiry": (R.front_future(instrument) or (None, None))[1]},
        "pcr": {"near": fnum((snap or {}).get("pcr"), 4),
                "atm": fnum((snap or {}).get("pcr_atm"), 4),
                "ce_oi": (snap or {}).get("ce_oi"),
                "pe_oi": (snap or {}).get("pe_oi"),
                "app_pcr_range": fnum((app or {}).get("pcr_range"), 4)},
        "spcl": spcl,
        "suggested": {"pe_strike": None, "ce_strike": None,
                      "anchor_ce_ltp": fnum((snap or {}).get("anchor_ce_ltp")),
                      "anchor_pe_ltp": fnum((snap or {}).get("anchor_pe_ltp")),
                      "spot_hma": fnum((snap or {}).get("spot_hma"))},
        "app_log_age_min": (app or {}).get("_age_min"),
    }


def write(payload):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "snapshot_%s.json" % payload["instrument"])
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    os.replace(tmp, path)       # never leave a half-written file for a poller
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default="NIFTY,BANKNIFTY,SENSEX")
    ap.add_argument("--day", help="YYYY-MM-DD, defaults to today IST")
    a = ap.parse_args()
    for name in [x.strip().upper() for x in a.instruments.split(",") if x.strip()]:
        try:
            p = build(name, a.day)
        except Exception as e:
            print(f"{name}: FAILED {type(e).__name__}: {e}")
            continue
        path = write(p)
        print(f"{name}: {path}  spot={p['spot']}  pcr={p['pcr']['near']}  "
              f"ref={p['referral'].get('qualified', 0)} qualified  "
              f"session={p['session']}"
              + ("  [PREV SESSION]" if p["day"].get("previous_session") else ""))


if __name__ == "__main__":
    main()
