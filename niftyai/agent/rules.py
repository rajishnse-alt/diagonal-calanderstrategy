"""
Entry rules for the paper-trading agent. Pure functions, no I/O — so every
condition is testable against the worked examples from the card.

BULLISH  -> buy the CE the app suggests
    1. PCR above PCR_BULL            (instrument's own PCR)
    2. PeSPCL "floating candles": the PE anchor's LTP is BELOW its band low
       e.g. band "171.30 | 148.93" -> low 148.93, LTP must be under 148.93
    3. spot ABOVE its HMA
    then ARM the suggested CE and enter only once that option trades
    ABOVE both its ->CE H and its own HMA.

BEARISH -> buy the PE the app suggests   (mirror)
    1. PCR below PCR_BEAR
    2. CeSPCL floating: CE anchor LTP below its band low
    3. spot BELOW its HMA
    then ARM the suggested PE, enter above ->PE H and above its own HMA.

The band is rendered "H | L" where L = H x (1 - 13.06%). "Floating candles"
means price has broken under the LOWER edge, so the test is against L, not H.

Entry is ARMED, not immediate: in the bullish example the suggested CE is at
14.90 while ->CE H is 38.01, so nothing is bought until it clears 38.01.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

PCR_BULL = 1.02      # PCR strictly above this for a long-CE setup
PCR_BEAR = 0.90      # PCR strictly below this for a long-PE setup


@dataclass
class Band:
    """The 'H | L' pair on a SPCL row. low = high x (1 - 13.06%)."""
    high: float
    low: float
    ltp: float | None = None

    def floating(self) -> bool:
        """True when price has broken BELOW the lower edge of the band."""
        if self.ltp is None or self.low is None:
            return False
        return float(self.ltp) < float(self.low)


@dataclass
class Candidate:
    """The strike the card suggests, with the levels the entry is judged on."""
    strike: int
    opt_type: str            # "CE" | "PE"
    ltp: float
    proj_high: float         # ->CE H / ->PE H — the breakout level
    target: float            # Tg (+26.11%)
    hma: float | None = None
    day_low: float | None = None

    def triggered(self) -> bool:
        """Above BOTH the projected high and its own HMA."""
        if self.ltp is None or self.proj_high is None:
            return False
        if float(self.ltp) <= float(self.proj_high):
            return False
        if self.hma is None:          # no HMA -> cannot confirm, do not enter
            return False
        return float(self.ltp) > float(self.hma)


@dataclass
class Signal:
    side: str                # "BULLISH" | "BEARISH"
    instrument: str
    candidate: Candidate
    pcr: float
    spot: float
    spot_hma: float
    armed: bool              # setup valid
    triggered: bool          # candidate has cleared its levels -> enter now
    reasons: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["candidate"] = asdict(self.candidate)
        return d


def _check(side, instrument, pcr, spot, spot_hma, anchor_band, cand,
           pcr_bull=PCR_BULL, pcr_bear=PCR_BEAR) -> Signal:
    r = []
    if side == "BULLISH":
        ok_pcr = pcr is not None and float(pcr) > pcr_bull
        r.append(f"PCR {pcr} > {pcr_bull}: {ok_pcr}")
        ok_spot = spot is not None and spot_hma is not None and float(spot) > float(spot_hma)
        r.append(f"spot {spot} > HMA {spot_hma}: {ok_spot}")
    else:
        ok_pcr = pcr is not None and float(pcr) < pcr_bear
        r.append(f"PCR {pcr} < {pcr_bear}: {ok_pcr}")
        ok_spot = spot is not None and spot_hma is not None and float(spot) < float(spot_hma)
        r.append(f"spot {spot} < HMA {spot_hma}: {ok_spot}")

    ok_float = anchor_band.floating() if anchor_band else False
    r.append(f"anchor LTP {getattr(anchor_band,'ltp',None)} < band low "
             f"{getattr(anchor_band,'low',None)}: {ok_float}")

    armed = bool(ok_pcr and ok_spot and ok_float and cand is not None)
    trig  = bool(armed and cand.triggered())
    if cand is not None:
        r.append(f"{cand.strike}{cand.opt_type} {cand.ltp} > projH "
                 f"{cand.proj_high} and > HMA {cand.hma}: {cand.triggered()}")
    return Signal(side=side, instrument=instrument, candidate=cand, pcr=pcr,
                  spot=spot, spot_hma=spot_hma, armed=armed, triggered=trig,
                  reasons=r)


def bullish(instrument, pcr, spot, spot_hma, pe_anchor_band, ce_candidate,
            **kw) -> Signal:
    return _check("BULLISH", instrument, pcr, spot, spot_hma,
                  pe_anchor_band, ce_candidate, **kw)


def bearish(instrument, pcr, spot, spot_hma, ce_anchor_band, pe_candidate,
            **kw) -> Signal:
    return _check("BEARISH", instrument, pcr, spot, spot_hma,
                  ce_anchor_band, pe_candidate, **kw)


def evaluate(instrument, pcr, spot, spot_hma, ce_band, pe_band,
             ce_candidate, pe_candidate, **kw) -> Signal | None:
    """
    Both sides checked; at most one can be armed since the PCR thresholds do
    not overlap (>1.02 vs <0.90). Returns the armed signal, else None.
    """
    b = bullish(instrument, pcr, spot, spot_hma, pe_band, ce_candidate, **kw)
    if b.armed:
        return b
    s = bearish(instrument, pcr, spot, spot_hma, ce_band, pe_candidate, **kw)
    return s if s.armed else None
