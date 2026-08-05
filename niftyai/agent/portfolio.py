"""
Capital ledger — the hard cap on everything the agent may deploy.

RULE: ₹1,20,000 across ALL instruments combined, not per instrument. If NIFTY
positions consume the lot, BANKNIFTY and SENSEX cannot trade until something
closes. The ledger is portfolio-wide precisely so one index cannot starve the
others by accident and, more importantly, so the total can never exceed the cap.

WHY FIXED LOTS WAS DANGEROUS
    The agent used LOTS = 10 regardless of price. At today's premiums that is
        NIFTY      20.00 x 75 x 10 = Rs   15,000
        SENSEX    231.10 x 10 x 10 = Rs   23,110
        BANKNIFTY 391.00 x 15 x 10 = Rs   58,650
    so a single BANKNIFTY entry took half the account, and three concurrent
    trades would have blown through the cap without anything noticing.

SIZING is the tighter of two limits, both of which must hold:
    capital  lots = available / (entry x lot_size)
    risk     lots = (MAX_RISK_PCT x capital) / ((entry - stop) x lot_size)
The capital limit stops over-deployment; the risk limit stops a single trade
losing more than MAX_RISK_PCT of the account when it hits its stop. A long
option is fully paid, so capital at risk of total loss is the whole premium —
which is why the risk limit usually binds first, and should.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

PATH          = "niftyai/agent/portfolio.json"
CAPITAL       = 120_000.0     # rupees, hard cap across all instruments
MAX_RISK_PCT  = 0.02          # most of the account one trade may lose at its stop
MIN_LOTS      = 1
MAX_LOTS      = 10            # the spec's ceiling; capital may reduce it, never raise


def _blank():
    return {"capital": CAPITAL, "open": [], "history": [],
            "updated": datetime.now().isoformat(timespec="seconds")}


def load() -> dict:
    if os.path.exists(PATH):
        try:
            p = json.load(open(PATH))
            p.setdefault("capital", CAPITAL)
            p.setdefault("open", [])
            p.setdefault("history", [])
            return p
        except Exception:
            pass
    return _blank()


def save(p: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    p["updated"] = datetime.now().isoformat(timespec="seconds")
    with open(PATH, "w") as f:
        json.dump(p, f, indent=2, sort_keys=True)


def deployed(p: dict) -> float:
    return round(sum(float(o.get("deployed", 0)) for o in p.get("open", [])), 2)


def available(p: dict) -> float:
    return round(max(0.0, float(p.get("capital", CAPITAL)) - deployed(p)), 2)


def size(p, entry, stop, lot_size, max_lots=MAX_LOTS):
    """
    (lots, detail) — the largest position both limits allow. lots=0 means the
    trade must be skipped, and detail says which limit bound.
    """
    entry, stop, lot_size = float(entry), float(stop), int(lot_size)
    if entry <= 0 or lot_size <= 0:
        return 0, {"reason": "bad entry/lot_size"}
    per_lot_cost = entry * lot_size
    per_lot_risk = max(entry - stop, 0.0) * lot_size

    avail = available(p)
    cap_lots = int(avail // per_lot_cost) if per_lot_cost > 0 else 0
    risk_budget = float(p.get("capital", CAPITAL)) * MAX_RISK_PCT
    risk_lots = int(risk_budget // per_lot_risk) if per_lot_risk > 0 else max_lots

    lots = max(0, min(cap_lots, risk_lots, max_lots))
    bind = ("capital" if cap_lots <= min(risk_lots, max_lots)
            else "risk" if risk_lots <= max_lots else "max_lots")
    return lots, {
        "available": avail, "per_lot_cost": round(per_lot_cost, 2),
        "per_lot_risk": round(per_lot_risk, 2), "risk_budget": round(risk_budget, 2),
        "cap_lots": cap_lots, "risk_lots": risk_lots, "max_lots": max_lots,
        "binding": bind,
        "deploy": round(lots * per_lot_cost, 2),
        "risk": round(lots * per_lot_risk, 2),
    }


def can_open(p, instrument, entry, stop, lot_size, max_lots=MAX_LOTS):
    lots, d = size(p, entry, stop, lot_size, max_lots)
    if lots < MIN_LOTS:
        d["reason"] = (f"no capital: available Rs {d.get('available',0):,.0f}, "
                       f"one lot costs Rs {d.get('per_lot_cost',0):,.0f}"
                       if d.get("cap_lots", 0) < 1 else
                       f"risk cap: one lot risks Rs {d.get('per_lot_risk',0):,.0f} "
                       f"against a Rs {d.get('risk_budget',0):,.0f} budget")
    return lots, d


def open_position(p, instrument, strike, opt_type, entry, stop, lots, lot_size,
                  trade_id=None):
    rec = {
        "id": trade_id or f"{instrument}-{strike}{opt_type}-{datetime.now():%Y%m%d%H%M%S}",
        "instrument": instrument, "strike": strike, "opt_type": opt_type,
        "entry": round(float(entry), 2), "stop": round(float(stop), 2),
        "lots": int(lots), "lot_size": int(lot_size),
        "deployed": round(float(entry) * int(lots) * int(lot_size), 2),
        "risk": round(max(float(entry) - float(stop), 0) * int(lots) * int(lot_size), 2),
        "opened": datetime.now().isoformat(timespec="seconds"),
    }
    p.setdefault("open", []).append(rec)
    return rec


def close_position(p, trade_id, exit_price, why=""):
    for i, o in enumerate(p.get("open", [])):
        if o["id"] == trade_id:
            rec = p["open"].pop(i)
            rec["exit"] = round(float(exit_price), 2)
            rec["pnl"] = round((float(exit_price) - rec["entry"])
                               * rec["lots"] * rec["lot_size"], 2)
            rec["closed"] = datetime.now().isoformat(timespec="seconds")
            rec["why"] = why
            p.setdefault("history", []).append(rec)
            return rec
    return None


def summary(p) -> dict:
    hist = p.get("history", [])
    pnl = round(sum(float(h.get("pnl", 0)) for h in hist), 2)
    return {
        "capital": p.get("capital", CAPITAL),
        "deployed": deployed(p), "available": available(p),
        "open_positions": len(p.get("open", [])),
        "closed": len(hist), "realised_pnl": pnl,
        "utilisation_pct": round(deployed(p) / max(p.get("capital", CAPITAL), 1) * 100, 1),
    }
