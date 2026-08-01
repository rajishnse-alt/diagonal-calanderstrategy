"""
Upstox data access.

PUBLIC endpoints only — no access token. Verified 2026-08-01: both
/v3/historical-candle and the instrument dump answer unauthenticated for
NSE_INDEX, NSE_FO, BSE_INDEX and BSE_FO keys. That is what lets CI run this.

Backfill chunks every request to the measured per-unit maximum span, because
exceeding it returns HTTP 400 UDAPI1148 rather than a truncated result — a
single wide request silently yields NOTHING.
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import requests

from niftyai.config import settings as S

IST = timezone(timedelta(hours=5, minutes=30))
HDR = {"Accept": "application/json"}
V3  = "https://api.upstox.com/v3/historical-candle"
CDN = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"

_INSTRUMENTS: list | None = None


def today_ist() -> date:
    return datetime.now(IST).date()


def parse_expiry(v):
    """Epoch MILLISECONDS in the dump; ISO elsewhere."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)) or str(v).isdigit():
            n = float(v)
            return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, IST).date()
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def load_instruments(force: bool = False) -> list:
    global _INSTRUMENTS
    if _INSTRUMENTS is not None and not force:
        return _INSTRUMENTS
    raw = requests.get(CDN, timeout=180).content
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass                      # sometimes served already decompressed
    _INSTRUMENTS = json.loads(raw)
    return _INSTRUMENTS


def option_contracts(instrument: str,
                     expiries_to_scan: int = S.EXPIRIES_TO_SCAN,
                     spot: float | None = None,
                     all_expiries: bool = False) -> list[dict]:
    """
    Live option contracts for one instrument.

    Matches on underlying_key, never underlying_symbol: a NIFTY row carries
    underlying_symbol "NIFTY" while "Nifty 50" appears only in underlying_key,
    and matching the symbol also drags in NIFTYNXT50.
    """
    c = S.cfg(instrument)
    today = today_ist()
    rows = []
    for i in load_instruments():
        if not isinstance(i, dict):
            continue
        if i.get("segment") != c["segment"]:
            continue
        if i.get("instrument_type") not in ("CE", "PE"):
            continue
        if i.get("underlying_key") != c["underlying_key"]:
            continue
        exp = parse_expiry(i.get("expiry"))
        if not exp or exp < today:
            continue
        strike = float(i.get("strike_price") or 0)
        if strike <= 0:
            continue
        rows.append({
            "instrument_key": i.get("instrument_key"),
            "trading_symbol": i.get("trading_symbol"),
            "strike": strike,
            "opt_type": i.get("instrument_type"),
            "expiry": exp,
        })
    if not all_expiries:
        keep = sorted({r["expiry"] for r in rows})[:expiries_to_scan]
        rows = [r for r in rows if r["expiry"] in keep]
    if spot:
        rows = [r for r in rows if abs(r["strike"] - spot) <= c["max_strike_dist"]]
    return sorted(rows, key=lambda r: (r["expiry"], r["opt_type"], r["strike"]))


def _get(url: str, retries: int = 2) -> list:
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HDR, timeout=60)
            if r.status_code == 200:
                return (r.json().get("data") or {}).get("candles") or []
            if r.status_code == 400:
                return []                     # bad range / no such window
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return []
        except requests.RequestException:
            if attempt == retries:
                return []
            time.sleep(1)
    return []


def history(instrument_key: str, unit: str = "minutes", interval: str = "5",
            days: int = 730, until: date | None = None,
            include_today: bool = True, stop_on_empty: bool = True) -> list[list]:
    """
    Candles OLDEST-FIRST, backfilled in chunks of the measured maximum span.

    stop_on_empty: an empty chunk means the contract's listing date was passed —
    for options there is genuinely nothing earlier, so stop rather than grind
    through 26 pointless requests. Set False for indices, where a single quiet
    window (a long holiday) should not abort the walk.
    """
    enc  = urllib.parse.quote(instrument_key, safe="")
    span = S.MAX_SPAN_DAYS.get(unit, 28)
    to   = until or today_ist()
    out: list[list] = []
    remaining = days
    empty_streak = 0
    while remaining > 0:
        chunk = min(remaining, span)
        frm = to - timedelta(days=chunk)
        got = _get(f"{V3}/{enc}/{unit}/{interval}/{to}/{frm}")
        if got:
            out = list(reversed(got)) + out
            empty_streak = 0
        else:
            empty_streak += 1
            if stop_on_empty or empty_streak >= 3:
                break
        to = frm - timedelta(days=1)
        remaining -= chunk
    if include_today and until is None:
        out += list(reversed(_get(f"{V3}/intraday/{enc}/{unit}/{interval}")))
    seen, dedup = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0])
            dedup.append(c)
    return dedup


def candles(instrument_key: str, days: int = S.OPTION_HISTORY_DAYS,
            include_today: bool = True) -> list[list]:
    """5-min option candles. Stops at the listing date."""
    return history(instrument_key, "minutes", str(S.BAR_MINUTES),
                   days=days, include_today=include_today, stop_on_empty=True)


def index_candles(instrument: str, days: int = S.INDEX_HISTORY_DAYS,
                  include_today: bool = True) -> list[list]:
    """5-min index candles — verified available at least 24 months back."""
    return history(S.cfg(instrument)["underlying_key"], "minutes",
                   str(S.BAR_MINUTES), days=days,
                   include_today=include_today, stop_on_empty=False)
