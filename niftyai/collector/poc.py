"""
POC price and sweep state — port of BigBeluga's
"Structural Liquidity & POC Matrix", the two outputs asked for: pocPrice, Tcol.

Tcol (sweep state)
    H = highest(liquidityLen), L = lowest(liquidityLen)
    highg = this bar's high == H     lowg = this bar's low == L
        if lowg  -> Tcol = bearCol
        if highg -> Tcol = bullCol
    Both are checked in that order each bar, so when a bar is BOTH the period
    high and the period low, highg wins. Tcol is a `var` — it persists until
    the next sweep, it does not reset.

pocPrice (volume profile point of control)
    atr  = ATR(100) * 0.2                      -> bin height
    bins span profBot..profTop, the last swept low and high
    each bar from `start` to now drops its VOLUME into the bin its CLOSE falls in
    pocPrice = profBot + pocBinIdx*atr + atr/2  -> middle of the fullest bin

Deliberately faithful rather than tidied: the profile is built from CLOSE
prices (not the bar's range) and `start` is the earlier of the two sweep bars,
both as written in the original.
"""
from __future__ import annotations


def _atr(candles, n=100):
    """Wilder ATR over [ts,o,h,l,c,...] rows, oldest-first."""
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l = float(candles[i][2]), float(candles[i][3])
        pc = float(candles[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return None
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def analyse(candles, liq_len=100, fade=100, atr_len=100, atr_mult=0.2,
            prof_offset=50):
    """
    Returns {poc, tcol, prof_top, prof_bot, atr_bin, bins, start} or None.
    tcol is "BULL" | "BEAR" | None.
    """
    n = len(candles)
    if n < max(liq_len, atr_len) + 2:
        return None
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    vols = [float(c[5]) if len(c) > 5 and c[5] else 0.0 for c in candles]

    tcol = None
    count_up = count_dn = 0
    top = bottom = None
    idx_top = idx_bot = 0
    prof_top = prof_bot = 0.0

    for i in range(liq_len - 1, n):
        win_h = highs[i - liq_len + 1: i + 1]
        win_l = lows[i - liq_len + 1: i + 1]
        highg = highs[i] == max(win_h)
        lowg = lows[i] == min(win_l)

        # ── top sweep ────────────────────────────────────────────────────────
        prev_top = top
        if highg and count_up == 0:
            count_up = 1
        if highg:
            top = max(win_h)
        if count_up >= 1:
            count_up += 1
        if count_up == fade:
            count_up, top = 0, None
        if count_up == 2:
            idx_top, prof_top = i, (top or 0.0)
        if top != prev_top and prev_top is not None:
            count_up, top = 0, None

        # ── bottom sweep ─────────────────────────────────────────────────────
        prev_bot = bottom
        if lowg and count_dn == 0:
            count_dn = 1
        if lowg:
            bottom = min(win_l)
        if count_dn >= 1:
            count_dn += 1
        if count_dn == fade:
            count_dn, bottom = 0, None
        if count_dn == 2:
            idx_bot, prof_bot = i, (bottom or 0.0)
        if bottom != prev_bot and prev_bot is not None:
            count_dn, bottom = 0, None

        # ── Tcol: order matters, highg overrides lowg on the same bar ────────
        if lowg:
            tcol = "BEAR"
        if highg:
            tcol = "BULL"

    a = _atr(candles, atr_len)
    if not a:
        return {"poc": None, "tcol": tcol, "prof_top": prof_top,
                "prof_bot": prof_bot, "atr_bin": None, "bins": 0, "start": 0}
    atr_bin = a * atr_mult
    height = prof_top - prof_bot
    if atr_bin <= 0 or height <= 0:
        return {"poc": None, "tcol": tcol, "prof_top": prof_top,
                "prof_bot": prof_bot, "atr_bin": round(atr_bin, 4),
                "bins": 0, "start": 0}

    size = max(1, round(height / atr_bin))
    vol_bins = [0.0] * size
    start = min(idx_bot, idx_top)
    for i in range(start, n):
        b = int((closes[i] - prof_bot) // atr_bin)
        if 0 <= b < size:
            vol_bins[b] += vols[i]

    max_vol = max(vol_bins)
    if max_vol <= 0:
        return {"poc": None, "tcol": tcol, "prof_top": prof_top,
                "prof_bot": prof_bot, "atr_bin": round(atr_bin, 4),
                "bins": size, "start": start}
    poc_idx = vol_bins.index(max_vol)
    poc = prof_bot + poc_idx * atr_bin + atr_bin / 2
    return {"poc": round(poc, 2), "tcol": tcol,
            "prof_top": round(prof_top, 2), "prof_bot": round(prof_bot, 2),
            "atr_bin": round(atr_bin, 4), "bins": size, "start": start,
            "poc_bin": poc_idx, "poc_vol_share": round(max_vol / sum(vol_bins), 3)
            if sum(vol_bins) else None}
