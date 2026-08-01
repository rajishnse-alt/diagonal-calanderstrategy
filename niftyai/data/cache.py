"""
Durable candle cache.

WHY THIS EXISTS
    An option's history is only available from its listing date, and once the
    contract expires it vanishes from the instrument dump entirely — the data
    becomes unreachable. Anything not archived while the contract is live is
    lost permanently. The cache is therefore the ONLY path to a training set
    deeper than the API's rolling window.

WHY MONTH PARTITIONS
    <instrument>/<key>/<YYYY-MM>.parquet. Once a month closes its file never
    changes again, so git stores that blob once. A single append-only file per
    contract would rewrite the whole object on every run and the repo would
    grow by the full dataset size daily.

Reads merge cache + API and only fetch the window the cache is missing, so a
daily run costs one short request per contract instead of a full backfill.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd

from niftyai.config import settings as S
from niftyai.data import upstox

COLS = ["ts", "open", "high", "low", "close", "volume", "oi"]


NUMERIC = ("open", "high", "low", "close", "volume", "oi")


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    """
    Force float dtypes on the price columns.

    Needed on EVERY path out of the cache, not just on fresh API rows: a
    parquet round-trip can hand these back as dtype=object (a column that ever
    held None comes back boxed), and numpy then tries to call .log() on a
    Python float — "loop of ufunc does not support argument 0 of type float
    which has no callable log method". The failure surfaces deep inside feature
    engineering, far from the cause.
    """
    if df.empty:
        return df
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df


def to_frame(raw: list[list]) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame(raw, columns=COLS[:len(raw[0])])
    df = coerce(df)
    df["ts"] = (pd.to_datetime(df["ts"], format="mixed", utc=True)
                  .dt.tz_convert(upstox.IST).dt.tz_localize(None))
    return df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


def _dir(instrument: str, key: str) -> str:
    return os.path.join(S.ARCHIVE_DIR, instrument.upper(), key.replace("|", "_"))


def read(instrument: str, key: str) -> pd.DataFrame:
    d = _dir(instrument, key)
    if not os.path.isdir(d):
        return pd.DataFrame(columns=COLS)
    parts = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".parquet"):
            try:
                parts.append(pd.read_parquet(os.path.join(d, f)))
            except Exception:
                continue
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = (pd.concat(parts, ignore_index=True)
            .drop_duplicates("ts").sort_values("ts").reset_index(drop=True))
    df["ts"] = pd.to_datetime(df["ts"])
    return coerce(df)


def write(instrument: str, key: str, df: pd.DataFrame) -> int:
    """Merge into month partitions. Returns rows added."""
    if df.empty:
        return 0
    d = _dir(instrument, key)
    os.makedirs(d, exist_ok=True)
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    added = 0
    for period, chunk in df.groupby(df["ts"].dt.to_period("M")):
        path = os.path.join(d, f"{period}.parquet")
        if os.path.exists(path):
            try:
                old = pd.read_parquet(path)
            except Exception:
                old = pd.DataFrame(columns=COLS)
            before = len(old)
            merged = (pd.concat([old, chunk], ignore_index=True)
                        .drop_duplicates("ts").sort_values("ts"))
            if len(merged) == before:
                continue                      # nothing new — leave the blob alone
            added += len(merged) - before
        else:
            merged = chunk.sort_values("ts")
            added += len(merged)
        merged.to_parquet(path, index=False)
    return added


def get(instrument: str, key: str, days: int, is_index: bool = False,
        refresh_days: int = 3) -> pd.DataFrame:
    """
    Cached candles, topped up from the API.

    Fetches only what the cache lacks: a full backfill on a cold cache, else
    just the last `refresh_days` (which also re-pulls the most recent days so a
    partial final session gets completed).
    """
    cached = read(instrument, key)
    want_from = upstox.today_ist() - timedelta(days=days)

    if cached.empty:
        need_days = days
    else:
        newest = cached["ts"].max().date()
        oldest = cached["ts"].min().date()
        gap_recent = (upstox.today_ist() - newest).days
        need_days = max(gap_recent + refresh_days, 0)
        if oldest > want_from:
            need_days = days                  # cache does not reach far enough back

    if need_days > 0:
        raw = (upstox.index_candles(instrument, days=need_days) if is_index
               else upstox.candles(key, days=need_days))
        fresh = to_frame(raw)
        if not fresh.empty:
            write(instrument, key, fresh)
            cached = (pd.concat([cached, fresh], ignore_index=True)
                        .drop_duplicates("ts").sort_values("ts").reset_index(drop=True))
    if not cached.empty:
        cached = cached[cached["ts"] >= pd.Timestamp(want_from)].reset_index(drop=True)
    return coerce(cached)


def stats(instrument: str) -> dict:
    root = os.path.join(S.ARCHIVE_DIR, instrument.upper())
    if not os.path.isdir(root):
        return {"contracts": 0, "files": 0, "mb": 0.0}
    files = rows_mb = 0
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith(".parquet"):
                files += 1
                rows_mb += os.path.getsize(os.path.join(dirpath, n))
    return {"contracts": len(os.listdir(root)), "files": files,
            "mb": round(rows_mb / 1e6, 2)}
