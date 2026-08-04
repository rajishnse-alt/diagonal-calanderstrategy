"""
Trade journal — committed to the repo so every virtual trade is reviewable.

Two files per instrument:
  niftyai/journal/<INSTRUMENT>_trades.csv   one row per closed trade (machine)
  niftyai/journal/<INSTRUMENT>_journal.md   human-readable log, newest first

The CSV carries the R multiple against the INITIAL risk, which is the number
the 1:3 requirement is judged on — not the raw P&L. A trade can be green and
still fail the mandate.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime

DIR = "niftyai/journal"
FIELDS = ["date", "entry_ts", "instrument", "side", "strike", "opt_type",
          "entry", "init_sl", "target", "risk_per_lot", "rr_needed_1_3",
          "lots", "exits", "pnl_per_lot", "r_multiple", "met_1_3", "status"]


def _paths(instrument):
    i = instrument.upper()
    return (os.path.join(DIR, f"{i}_trades.csv"),
            os.path.join(DIR, f"{i}_journal.md"))


def record(trade, note: str = "") -> dict:
    """Append one closed trade. Returns the row written."""
    os.makedirs(DIR, exist_ok=True)
    csv_p, md_p = _paths(trade.instrument)
    row = {
        "date":        trade.entry_ts[:10],
        "entry_ts":    trade.entry_ts,
        "instrument":  trade.instrument,
        "side":        trade.side,
        "strike":      trade.strike,
        "opt_type":    trade.opt_type,
        "entry":       round(trade.entry, 2),
        "init_sl":     round(trade.init_sl, 2),
        "target":      round(trade.target, 2),
        "risk_per_lot": round(trade.risk_per_lot, 2),
        "rr_needed_1_3": round(trade.reward_needed, 2),
        "lots":        trade.lots,
        "exits":       "; ".join(f"{e['why']}@{e['price']}x{e['lots']}"
                                 for e in trade.exits),
        "pnl_per_lot": trade.pnl_per_lot,
        "r_multiple":  trade.r_multiple,
        "met_1_3":     bool(trade.r_multiple is not None and trade.r_multiple >= 3),
        "status":      trade.status,
    }
    new = not os.path.exists(csv_p)
    with open(csv_p, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)

    entry = (
        f"\n## {row['entry_ts']} — {row['strike']}{row['opt_type']} "
        f"({row['side']})\n\n"
        f"- entry **{row['entry']}**, initial SL **{row['init_sl']}** "
        f"(risk {row['risk_per_lot']}/lot), target **{row['target']}**\n"
        f"- exits: {row['exits'] or '—'}\n"
        f"- result: **{row['pnl_per_lot']:+}/lot**, "
        f"**R {row['r_multiple']:+}** — 1:3 {'MET' if row['met_1_3'] else 'NOT met'} "
        f"(needed {row['rr_needed_1_3']})\n"
    )
    if note:
        entry += f"- note: {note}\n"
    prev = ""
    if os.path.exists(md_p):
        with open(md_p) as f:
            prev = f.read()
    hdr = f"# {trade.instrument} — virtual trade journal\n"
    body = prev[len(hdr):] if prev.startswith(hdr) else prev
    with open(md_p, "w") as f:
        f.write(hdr + entry + body)         # newest first
    return row


def stats(instrument) -> dict:
    """Rolling review — what the agent has to learn from."""
    csv_p, _ = _paths(instrument)
    if not os.path.exists(csv_p):
        return {}
    rows = list(csv.DictReader(open(csv_p)))
    rs = [float(r["r_multiple"]) for r in rows if r.get("r_multiple") not in (None, "", "None")]
    if not rs:
        return {"trades": len(rows)}
    wins = [r for r in rs if r > 0]
    met  = [r for r in rs if r >= 3]
    return {
        "trades": len(rs),
        "avg_r": round(sum(rs) / len(rs), 2),
        "win_rate": round(len(wins) / len(rs), 3),
        "met_1_3": len(met),
        "met_1_3_rate": round(len(met) / len(rs), 3),
        "best_r": round(max(rs), 2),
        "worst_r": round(min(rs), 2),
        "generated": datetime.now().isoformat(timespec="seconds"),
    }
