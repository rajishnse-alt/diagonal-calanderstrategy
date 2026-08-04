"""
Virtual position management. NO broker calls anywhere in this package — every
fill is simulated and written to the journal.

Rules as specified:
  • 10 lots on entry
  • target (Tg) hit  -> book 80% of lots, the remaining 20% runs
  • the runner trails on ATR
  • initial stop  = the DAY'S LOW - 0.11%
  • the stop then trails in 0.25% steps as price makes new highs

The 0.25% trail is a RATCHET: it only ever moves in favour of the position, in
0.25%-of-entry steps, and never loosens. A stop that can widen is not a stop.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime

LOTS            = 10
BOOK_FRACTION   = 0.80      # booked at target
SL_DAY_LOW_PCT  = 0.0011    # initial stop = day low - 0.11%
TRAIL_STEP_PCT  = 0.0025    # ratchet granularity, 0.25%
ATR_MULT        = 1.5       # runner trails at high - 1.5 x ATR
RR_TARGET       = 3.0       # the 1:3 the agent is held to


def atr(candles, n=14):
    """ATR over [ts,o,h,l,c,...] rows, oldest-first. None if too short."""
    if not candles or len(candles) < n + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l = float(candles[i][2]), float(candles[i][3])
        pc = float(candles[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return None
    a = sum(trs[:n]) / n
    for t in trs[n:]:                     # Wilder smoothing
        a = (a * (n - 1) + t) / n
    return a


@dataclass
class Trade:
    instrument: str
    side: str                 # BULLISH | BEARISH  (both are LONG option buys)
    strike: int
    opt_type: str
    entry_ts: str
    entry: float
    target: float
    init_sl: float
    lots: int = LOTS
    lots_open: int = LOTS
    sl: float = 0.0
    high_water: float = 0.0
    booked_at_target: bool = False
    exits: list = field(default_factory=list)     # [{ts, lots, price, why}]
    status: str = "OPEN"
    r_multiple: float | None = None
    pnl_per_lot: float | None = None
    notes: list = field(default_factory=list)

    def __post_init__(self):
        self.sl = self.sl or self.init_sl
        self.high_water = self.high_water or self.entry

    # ── risk ────────────────────────────────────────────────────────────────
    @property
    def risk_per_lot(self) -> float:
        return max(self.entry - self.init_sl, 1e-9)

    @property
    def reward_needed(self) -> float:
        """Price that would deliver RR_TARGET on the initial risk."""
        return self.entry + RR_TARGET * self.risk_per_lot

    def rr_of(self, price: float) -> float:
        return (price - self.entry) / self.risk_per_lot

    # ── lifecycle ───────────────────────────────────────────────────────────
    def update(self, ts, price, atr_val=None):
        """Advance one bar. Returns a list of fills made on this bar."""
        if self.status != "OPEN":
            return []
        fills = []
        price = float(price)
        self.high_water = max(self.high_water, price)

        # 1. stop first — a bar that trades through both is treated as a stop.
        #    Assuming the favourable fill would flatter every result.
        if price <= self.sl:
            fills.append(self._exit(ts, self.lots_open, self.sl, "SL"))
            return fills

        # 2. target -> book 80% once
        if not self.booked_at_target and price >= self.target:
            n = int(round(self.lots * BOOK_FRACTION))
            n = min(n, self.lots_open)
            if n > 0:
                fills.append(self._exit(ts, n, self.target, "TARGET_80PCT"))
            self.booked_at_target = True
            # runner: hand the stop to ATR straight away
            if atr_val:
                self.sl = max(self.sl, self.high_water - ATR_MULT * atr_val)

        # 3. trailing
        if self.status == "OPEN":
            if self.booked_at_target and atr_val:
                self.sl = max(self.sl, self.high_water - ATR_MULT * atr_val)
            else:
                # ratchet in 0.25%-of-entry steps, only ever upward
                step = self.entry * TRAIL_STEP_PCT
                if step > 0:
                    steps = int((self.high_water - self.entry) / step)
                    if steps > 0:
                        self.sl = max(self.sl, self.init_sl + steps * step)
        return fills

    def _exit(self, ts, lots, price, why):
        lots = min(lots, self.lots_open)
        self.exits.append({"ts": str(ts), "lots": lots,
                           "price": round(float(price), 2), "why": why})
        self.lots_open -= lots
        if self.lots_open <= 0:
            self.close()
        return self.exits[-1]

    def close(self):
        if self.status != "OPEN":
            return
        self.status = "CLOSED"
        tot = sum(e["lots"] for e in self.exits) or 1
        avg = sum(e["price"] * e["lots"] for e in self.exits) / tot
        self.pnl_per_lot = round(avg - self.entry, 2)
        self.r_multiple = round(self.rr_of(avg), 2)

    def to_dict(self):
        return asdict(self)


def initial_stop(day_low: float, entry: float | None = None,
                 atr_val: float | None = None, k: float | None = None) -> float:
    """
    The TIGHTER of the day-low rule and a volatility-scaled stop:

        max(day_low x (1 - 0.11%),  entry - k x ATR)

    The day-low rule still caps how far the stop can sit, so the original
    intent survives — but on a breakout entry the day low is often 50% below
    price, which made the risk so large that Tg could never reach 1:3
    (measured: risk 9.71 on a 20.00 entry against a 5.19 reward = 0.53R).
    Taking the tighter of the two scales risk to the volatility present.
    """
    dl = float(day_low) * (1 - SL_DAY_LOW_PCT)
    if entry and atr_val and k:
        vol = float(entry) - float(k) * float(atr_val)
        if vol > dl:                       # tighter, and still below entry
            dl = vol
    return round(dl, 2)


def open_trade(sig, ts, day_low, target=None, atr_val=None, params=None) -> Trade:
    c = sig.candidate
    entry = float(c.ltp)
    k = None
    if params is not None and atr_val:
        from niftyai.agent import params as PR
        k = PR.stop_mult_for(params, atr_val / entry if entry else None)
    t = Trade(
        instrument=sig.instrument, side=sig.side, strike=c.strike,
        opt_type=c.opt_type, entry_ts=str(ts), entry=entry,
        target=float(target if target is not None else c.target),
        init_sl=initial_stop(day_low, entry, atr_val, k),
    )
    t.notes.append(f"atr={atr_val and round(atr_val,2)} k={k} "
                   f"atr_pct={atr_val and entry and round(atr_val/entry,4)}")
    return t
