"""
diagonal_strategy.py  ·  NIFTY Diagonal Spread Builder
────────────────────────────────────────────────────────
Strategy:
  SHORT LEG — Sell ATM+6 CE + ATM-6 PE in current expiry
              (6 steps × 50 = 300 pts OTM either side)
  LONG LEG  — Buy 2 lots of matching strikes in 5-week+ expiry
              where LTP ≈ 50% of the sold strike LTP

Run:  streamlit run diagonal_strategy.py
"""

import streamlit as st
import requests
import math
import time
from datetime import datetime, timedelta
import pytz

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(page_title="NIFTY Diagonal Builder", page_icon="📐", layout="wide")

# ── Theme toggle (read before injecting CSS) ───────────────────────────────
_light_mode = st.session_state.get("light_mode", False)

_dark_vars = """
    --bg:       #080c14; --surface: #0d1321; --border: #1c2840; --border2: #253352;
    --text:     #c8d8f0; --muted:   #5a7090; --text-inv:#080c14;
    --ce:       #4d9fff; --pe:      #cc66ff;
    --bull:     #00e676; --bull-dim:#003318;
    --bear:     #ff5252; --bear-dim:#2a0808;
    --gold:     #ffc940; --gold-dim:#2a1e00;
    --date-bg:  #0d1a2e; --date-text:#7eb8ff;
    --strike-bg:#1a0a28; --strike-text:#cc66ff;
"""
_light_vars = """
    --bg:       #f0f4fb; --surface: #ffffff; --border: #d0daea; --border2: #b0c4de;
    --text:     #1a2540; --muted:   #6a80a0; --text-inv:#ffffff;
    --ce:       #1565c0; --pe:      #7b1fa2;
    --bull:     #1b7e42; --bull-dim:#d4f5e2;
    --bear:     #c62828; --bear-dim:#fde8e8;
    --gold:     #e65100; --gold-dim:#fff3e0;
    --date-bg:  #ddeeff; --date-text:#1565c0;
    --strike-bg:#f3e5f5; --strike-text:#7b1fa2;
"""
_theme_vars = _light_vars if _light_mode else _dark_vars

_chain_atm  = "#fdf8e1" if _light_mode else "#1a1400"
_chain_sell = "#fdecea" if _light_mode else "#1a0808"
_chain_buy  = "#e8f5e9" if _light_mode else "#003318"

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@700;800&display=swap');
  :root {{ {_theme_vars} --mono:'JetBrains Mono',monospace; --hdr:'Syne',sans-serif; }}
  html,body,.stApp {{ background:var(--bg)!important; color:var(--text); }}
  .block-container  {{ padding:.75rem 1.2rem 1rem!important; }}
  h1,h2,h3          {{ font-family:var(--hdr); color:var(--text); }}
  .sec-hdr {{
    font-family:var(--hdr); font-size:11px; font-weight:700;
    color:var(--muted); letter-spacing:2px; text-transform:uppercase;
    margin:1.1rem 0 .45rem; padding-bottom:5px; border-bottom:1px solid var(--border);
  }}
  .card {{ background:var(--surface); border:1px solid var(--border);
           border-radius:10px; padding:.75rem 1rem; margin-bottom:.5rem; }}
  .card-ce   {{ border-left:4px solid var(--ce); }}
  .card-pe   {{ border-left:4px solid var(--pe); }}
  .card-bull {{ border-left:4px solid var(--bull); }}
  .card-gold {{ border-left:4px solid var(--gold); }}
  .mono {{ font-family:var(--mono); }}
  .lbl  {{ color:var(--muted); font-size:10px; letter-spacing:1px; text-transform:uppercase; }}
  .val-big  {{ font-family:var(--mono); font-size:20px; font-weight:700; color:var(--text); }}
  .val-ce   {{ color:var(--ce);   font-weight:700; }}
  .val-pe   {{ color:var(--pe);   font-weight:700; }}
  .val-bull {{ color:var(--bull); font-weight:700; }}
  .val-bear {{ color:var(--bear); font-weight:700; }}
  .val-gold {{ color:var(--gold); font-weight:700; }}

  /* ── Date & Strike pills ── */
  .date-pill {{
    display:inline-block; font-family:var(--mono); font-size:11px; font-weight:700;
    background:var(--date-bg); color:var(--date-text);
    border:1px solid var(--ce); border-radius:4px;
    padding:1px 7px; letter-spacing:.5px;
  }}
  .strike-pill {{
    display:inline-block; font-family:var(--mono); font-size:13px; font-weight:800;
    background:var(--strike-bg); color:var(--strike-text);
    border:1px solid var(--pe); border-radius:4px;
    padding:2px 9px; letter-spacing:.5px;
  }}
  .strike-pill-ce {{
    display:inline-block; font-family:var(--mono); font-size:13px; font-weight:800;
    background:var(--date-bg); color:var(--ce);
    border:1px solid var(--ce); border-radius:4px;
    padding:2px 9px; letter-spacing:.5px;
  }}
  .strike-pill-buy {{
    display:inline-block; font-family:var(--mono); font-size:13px; font-weight:800;
    background:var(--bull-dim); color:var(--bull);
    border:1px solid var(--bull); border-radius:4px;
    padding:2px 9px; letter-spacing:.5px;
  }}

  .tag {{ display:inline-block; font-size:9px; font-weight:700;
          padding:2px 7px; border-radius:3px; letter-spacing:.5px; }}
  .tag-sell {{ background:var(--bear-dim); color:var(--bear); border:1px solid var(--bear); }}
  .tag-buy  {{ background:var(--bull-dim); color:var(--bull); border:1px solid var(--bull); }}
  .tag-ce   {{ background:var(--date-bg);  color:var(--ce);   border:1px solid var(--ce); }}
  .tag-pe   {{ background:var(--strike-bg);color:var(--pe);   border:1px solid var(--pe); }}
  .chain-table {{ width:100%; border-collapse:collapse; font-family:var(--mono); font-size:11px; }}
  .chain-table th {{ color:var(--muted); font-size:9px; letter-spacing:1.5px; text-transform:uppercase;
                     padding:4px 8px; border-bottom:1px solid var(--border); text-align:center; }}
  .chain-table td {{ padding:5px 8px; border-bottom:1px solid var(--border); text-align:center;
                     color:var(--text); }}
  .chain-table .atm-row  {{ background:{_chain_atm};  font-weight:700; }}
  .chain-table .sell-row {{ background:{_chain_sell}; }}
  .chain-table .buy-row  {{ background:{_chain_buy};  }}
  .strike-col {{ color:var(--muted); }}
  .atm-tag  {{ display:inline-block; background:var(--gold-dim); color:var(--gold);
               font-size:8px; padding:1px 4px; border-radius:2px; margin-left:4px;
               font-family:var(--mono); border:1px solid var(--gold); }}
  .sell-tag {{ display:inline-block; background:var(--bear-dim); color:var(--bear);
               font-size:8px; padding:1px 4px; border-radius:2px; margin-left:4px;
               font-family:var(--mono); border:1px solid var(--bear); }}
  .buy-tag  {{ display:inline-block; background:var(--bull-dim); color:var(--bull);
               font-size:8px; padding:1px 4px; border-radius:2px; margin-left:4px;
               font-family:var(--mono); border:1px solid var(--bull); }}
  .login-box {{ background:var(--surface); border:1px solid var(--border2);
                border-radius:14px; padding:2.5rem 2rem; text-align:center;
                max-width:460px; margin:3rem auto; }}
  .err-box {{ background:var(--bear-dim); border:1px solid var(--bear); border-radius:8px;
              padding:.6rem .9rem; color:var(--bear); font-family:var(--mono); font-size:12px; }}
  #MainMenu,footer,header {{ visibility:hidden; }}
  div[data-testid="stSelectbox"] label {{
    font-family:var(--mono)!important; font-size:11px!important; color:var(--muted)!important; }}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# CONSTANTS — NIFTY ONLY
# ─────────────────────────────────────────────
IST          = pytz.timezone("Asia/Kolkata")
SYMBOL       = "NIFTY"
STEP         = 50           # NIFTY strike step
LOT_SIZE     = 75           # NIFTY lot size (check current SEBI notification)
SHORT_STEPS  = 6            # ATM ± 6 steps = ±300 pts
BUY_LOTS     = 2            # Fixed long lots per spec

INSTRUMENT_KEY  = "NSE_INDEX|Nifty 50"
UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL= "https://api.upstox.com/v2/login/authorization/token"
UPSTOX_OC_URLS  = [
    "https://api.upstox.com/v2/option/chain",   # v2 returns OI in market_data
    "https://api.upstox.com/v3/option/chain",   # v3 fallback (OI may differ)
]
UPSTOX_CONTRACT_URL = "https://api.upstox.com/v2/option/contract"


# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────
def secrets_ok():
    try:
        st.secrets["upstox"]["api_key"]
        st.secrets["upstox"]["api_secret"]
        st.secrets["upstox"]["redirect_uri"]
        return True
    except Exception:
        return False

def hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

def build_auth_url(k, r):
    return f"{UPSTOX_AUTH_URL}?response_type=code&client_id={k}&redirect_uri={r}"

def exchange_code(k, s, r, code):
    try:
        d = requests.post(
            UPSTOX_TOKEN_URL,
            data={"code":code,"client_id":k,"client_secret":s,"redirect_uri":r,"grant_type":"authorization_code"},
            headers={"Accept":"application/json"}, timeout=15,
        ).json()
        return (d["access_token"], None) if "access_token" in d else (None, str(d))
    except Exception as e:
        return None, str(e)


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────
def fetch_expiries(tok):
    try:
        r = requests.get(UPSTOX_CONTRACT_URL,
                         params={"instrument_key": INSTRUMENT_KEY},
                         headers=hdr(tok), timeout=15)
        if r.status_code == 401:
            return None, "token_expired"
        d = r.json()
        if d.get("status") == "success" and d.get("data"):
            raw = d["data"]
            dates = (
                [str(x.get("expiry") or x.get("expiry_date") or "") for x in raw]
                if isinstance(raw[0], dict) else [str(x) for x in raw]
            )
            dates = sorted(set(x for x in dates if x))
            return (dates, None) if dates else (None, "Empty")
        return None, str(d)
    except Exception as e:
        return None, str(e)


def fetch_chain(tok, expiry):
    for url in UPSTOX_OC_URLS:
        try:
            r = requests.get(url,
                             params={"instrument_key": INSTRUMENT_KEY, "expiry_date": expiry},
                             headers=hdr(tok), timeout=15)
            if r.status_code == 401:
                return None, "token_expired"
            d = r.json()
            if d.get("status") == "success":
                data = d.get("data") or []
                if data:
                    return data, None
        except Exception as e:
            pass
    return None, "Chain fetch failed"


def _get_oi(md):
    """Try every known Upstox field name for open interest."""
    for key in ("oi", "open_interest", "openInterest", "open_int", "OI"):
        v = md.get(key)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return 0.0

def _get_oi_chg(md):
    """Try every known Upstox field name for intraday OI change."""
    for key in ("oi_day_change", "change_oi", "day_change_oi", "oi_change", "oiChange", "changeOi"):
        v = md.get(key)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return 0.0


def parse_chain(data):
    ce_map, pe_map, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg = {}, {}, {}, {}, {}, {}
    spot = None
    for row in data:
        s = float(row.get("strike_price", 0))
        if spot is None:
            sp = row.get("underlying_spot_price")
            if sp:
                spot = float(sp)
        c = (row.get("call_options") or {}).get("market_data") or {}
        p = (row.get("put_options")  or {}).get("market_data") or {}
        ce_map[s]     = float(c.get("ltp") or 0)
        pe_map[s]     = float(p.get("ltp") or 0)
        ce_oi[s]      = _get_oi(c)
        pe_oi[s]      = _get_oi(p)
        ce_oi_chg[s]  = _get_oi_chg(c)
        pe_oi_chg[s]  = _get_oi_chg(p)
    if spot is None:
        common = set(ce_map) & set(pe_map)
        if common:
            spot = float(min(common, key=lambda s: abs(ce_map[s] - pe_map[s])))
    atm = int(round(spot / STEP) * STEP) if spot else 0
    return spot, atm, ce_map, pe_map, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg


def calc_pcr_spcl(ce_map, pe_map, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, atm, vix_day_open=None, n_strikes=10):
    """
    PCR      = sum(PE OI) / sum(CE OI)  within ATM ± n_strikes.
    PCR_CHG  = sum(PE OI change) / sum(CE OI change)  — shows intraday build-up direction.
    SPCL VAL = (base + (base - sqrt(vix_open))) / 2
               where base = sqrt(ce_atm + pe_atm) * π / 2
    Sentiment uses contrarian scale: high PCR → more puts → bullish contrarian signal.
    """
    strikes     = [atm + i * STEP for i in range(-n_strikes, n_strikes + 1)]
    tot_ce      = sum(ce_oi.get(float(s), 0)     for s in strikes)
    tot_pe      = sum(pe_oi.get(float(s), 0)     for s in strikes)
    tot_ce_chg  = sum(max(ce_oi_chg.get(float(s), 0), 0) for s in strikes)
    tot_pe_chg  = sum(max(pe_oi_chg.get(float(s), 0), 0) for s in strikes)

    pcr     = (tot_pe / tot_ce)         if tot_ce     > 0 else 0.0
    pcr_chg = (tot_pe_chg / tot_ce_chg) if tot_ce_chg > 0 else 0.0

    # SPCL VAL — exact formula from atm_tracker
    ce_atm  = ce_map.get(float(atm), 0)
    pe_atm  = pe_map.get(float(atm), 0)
    spcl    = None
    if ce_atm and pe_atm and vix_day_open:
        base_spcl = (math.sqrt(ce_atm + pe_atm) * math.pi) / 2
        vix_sqrt  = math.sqrt(vix_day_open)
        spcl      = (base_spcl + (base_spcl - vix_sqrt)) / 2

    if   pcr >= 1.3: sentiment = ("VERY BULLISH", "var(--bull)")
    elif pcr >= 1.1: sentiment = ("BULLISH",      "var(--bull)")
    elif pcr >= 0.9: sentiment = ("NEUTRAL",       "var(--gold)")
    elif pcr >= 0.7: sentiment = ("BEARISH",       "var(--bear)")
    else:            sentiment = ("VERY BEARISH",  "var(--bear)")

    return pcr, pcr_chg, tot_ce, tot_pe, spcl, ce_atm, pe_atm, sentiment


def fetch_vix(tok):
    """Fetch India VIX open and current LTP from Upstox market-quote API."""
    try:
        r = requests.get(
            "https://api.upstox.com/v2/market-quote/quotes",
            params={"instrument_key": "NSE_INDEX|India VIX"},
            headers=hdr(tok), timeout=10,
        )
        if r.status_code == 401:
            return None, None, "token_expired"
        d = r.json()
        if d.get("status") == "success":
            data = d.get("data", {})
            # response key uses colon separator
            vd = (data.get("NSE_INDEX:India VIX")
                  or data.get("NSE_INDEX|India VIX")
                  or next(iter(data.values()), None))
            if vd:
                ohlc     = vd.get("ohlc", {})
                open_vix = float(ohlc.get("open") or 0)
                curr_vix = float(vd.get("last_price") or 0)
                return open_vix, curr_vix, None
        return None, None, str(d)
    except Exception as e:
        return None, None, str(e)


def weeks_out(expiry_str):
    try:
        return ((datetime.strptime(expiry_str, "%Y-%m-%d").date()
                 - datetime.now(IST).date()).days / 7.0)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────
# STRATEGY LOGIC
# ─────────────────────────────────────────────
def find_long_candidates(sell_ltp, far_map, atm, opt_type, ltp_ratio_pct, n=8):
    """
    Rank far-expiry strikes by proximity of LTP to (sell_ltp × ratio%).
    CE: only OTM (strike >= atm - STEP).
    PE: only OTM (strike <= atm + STEP).
    """
    if sell_ltp <= 0:
        return []
    target = sell_ltp * ltp_ratio_pct / 100.0
    cands  = []
    for strike, ltp in far_map.items():
        if ltp <= 0:
            continue
        if opt_type == "CE" and strike < atm - STEP:
            continue
        if opt_type == "PE" and strike > atm + STEP:
            continue
        diff_abs = abs(ltp - target)
        diff_pct = diff_abs / target * 100 if target > 0 else 999
        cands.append({"strike": int(strike), "ltp": ltp,
                      "target": target, "diff_abs": diff_abs, "diff_pct": diff_pct})
    cands.sort(key=lambda x: x["diff_abs"])
    return cands[:n]


def auto_adjust_sell_strike(base_steps, atm, near_map, far_map, opt_type, ltp_ratio_pct, n=8):
    """
    Walk sell strike toward ATM from base_steps until the best long-leg LTP
    is <= sell LTP (prevents paying more for the hedge than you collect).
    CE and PE are adjusted independently.
    Returns: (final_steps, sell_strike, sell_ltp, candidates, was_adjusted)
    """
    for steps in range(base_steps, 0, -1):
        sell_strike = (atm + steps * STEP) if opt_type == "CE" else (atm - steps * STEP)
        sell_ltp    = near_map.get(float(sell_strike), 0)
        if sell_ltp <= 0:
            continue
        cands = find_long_candidates(sell_ltp, far_map, atm, opt_type, ltp_ratio_pct, n)
        # Sell LTP must be at least (100/ltp_ratio_pct)× the long LTP
        # e.g. ratio=50% → sell must be ≥ 2× long
        if cands and cands[0]["ltp"] <= sell_ltp * ltp_ratio_pct / 100:
            return steps, int(sell_strike), sell_ltp, cands, (steps != base_steps)
    # Fallback — return base even if ratio still not met
    sell_strike = (atm + base_steps * STEP) if opt_type == "CE" else (atm - base_steps * STEP)
    sell_ltp    = near_map.get(float(sell_strike), 0)
    cands       = find_long_candidates(sell_ltp, far_map, atm, opt_type, ltp_ratio_pct, n)
    return base_steps, int(sell_strike), sell_ltp, cands, False


def payoff_near_expiry(legs, spot_val, lot_size):
    """P&L at near-expiry. Far legs estimated at 60% time value retained."""
    pnl = 0.0
    for leg in legs:
        K    = leg["strike"]
        ltp  = leg["ltp"]
        lots = leg["lots"]
        intr = max(spot_val - K, 0) if leg["opt_type"] == "CE" else max(K - spot_val, 0)
        if leg["is_near"]:
            gain = (ltp - intr) if leg["is_sell"] else (intr - ltp)
        else:
            residual = ltp * 0.60
            gain = (residual - ltp) if leg["is_sell"] else (residual - ltp)
        pnl += gain * lots * lot_size
    return pnl


def make_payoff_svg(legs, atm, lot_size, sell_ce_s, sell_pe_s, width=720, height=220):
    lo = atm - 14 * STEP
    hi = atm + 14 * STEP
    pts = [(s, payoff_near_expiry(legs, float(s), lot_size))
           for s in range(int(lo), int(hi) + 1, STEP)]
    pnls  = [p[1] for p in pts]
    max_p = max(pnls) if pnls else 1
    min_p = min(pnls) if pnls else -1
    y_rng = max(abs(max_p), abs(min_p), 1)
    mg = 42
    pw = width  - 2 * mg
    ph = height - 2 * mg

    tx = lambda s:  mg + (s - lo) / (hi - lo) * pw
    ty = lambda v:  mg + ph / 2 - (v / y_rng) * (ph / 2)
    zy = ty(0)

    svg = [f'<svg width="{width}" height="{height}" '
           f'style="background:#0a0e1a;border:1px solid #1c2840;border-radius:8px;">']

    # Zero line
    svg.append(f'<line x1="{mg}" y1="{zy}" x2="{width-mg}" y2="{zy}" '
               f'stroke="#253352" stroke-width="1"/>')
    svg.append(f'<text x="{mg-4}" y="{zy+4}" font-size="9" fill="#4a6080" text-anchor="end">0</text>')

    # ATM line
    ax = tx(atm)
    svg.append(f'<line x1="{ax}" y1="{mg}" x2="{ax}" y2="{mg+ph}" '
               f'stroke="#ffc940" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>')
    svg.append(f'<text x="{ax}" y="{mg-6}" font-size="9" fill="#ffc940" text-anchor="middle">ATM {atm}</text>')

    # Short strike lines
    for s, color in [(sell_ce_s, "#2979ff"), (sell_pe_s, "#ab47bc")]:
        sx = tx(s)
        svg.append(f'<line x1="{sx}" y1="{mg}" x2="{sx}" y2="{mg+ph}" '
                   f'stroke="{color}" stroke-width="1" stroke-dasharray="3,3" opacity="0.7"/>')
        svg.append(f'<text x="{sx}" y="{mg+ph+14}" font-size="8" fill="{color}" '
                   f'text-anchor="middle">{s}(S)</text>')

    # Long strike lines
    for leg in legs:
        if not leg["is_near"] and not leg["is_sell"]:
            sx = tx(leg["strike"])
            svg.append(f'<line x1="{sx}" y1="{mg}" x2="{sx}" y2="{mg+ph}" '
                       f'stroke="#00e676" stroke-width="1" stroke-dasharray="2,5" opacity="0.4"/>')
            svg.append(f'<text x="{sx}" y="{mg+ph+24}" font-size="8" fill="#00e676" '
                       f'text-anchor="middle">{leg["strike"]}(B)</text>')

    # Fill profit
    path = (f"M {tx(pts[0][0])},{zy} "
            + " ".join(f"L {tx(s)},{ty(v)}" for s, v in pts)
            + f" L {tx(pts[-1][0])},{zy} Z")
    svg.append(f'<path d="{path}" fill="#00e676" opacity="0.10"/>')

    # Fill loss
    loss_path = (f"M {tx(pts[0][0])},{zy} "
                 + " ".join(f"L {tx(s)},{ty(min(v, 0))}" for s, v in pts)
                 + f" L {tx(pts[-1][0])},{zy} Z")
    svg.append(f'<path d="{loss_path}" fill="#ff5252" opacity="0.15"/>')

    # Payoff line
    poly = " ".join(f"{tx(s)},{ty(v)}" for s, v in pts)
    svg.append(f'<polyline points="{poly}" fill="none" stroke="#00e676" stroke-width="2" opacity="0.85"/>')

    # Labels
    svg.append(f'<text x="{mg+4}" y="{mg+12}" font-size="9" fill="#00e676">Max ₹{int(max_p):,}</text>')
    svg.append(f'<text x="{mg+4}" y="{mg+ph-4}" font-size="9" fill="#ff5252">Floor ₹{int(min_p):,}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
now      = datetime.now(IST)
mkt_open = now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) <= (15, 30)
dot      = "🟢" if mkt_open else "🔴"

st.markdown(
    f"<h1 style='margin-bottom:2px;'>📐 NIFTY Diagonal Spread Builder</h1>"
    f"<p class='mono' style='font-size:11px;color:var(--muted);margin-bottom:1rem;'>"
    f"{dot} {'OPEN' if mkt_open else 'CLOSED'} &nbsp;·&nbsp; "
    f"{now.strftime('%d %b %Y %H:%M IST')} &nbsp;·&nbsp; "
    f"Sell ATM±{SHORT_STEPS} ({SHORT_STEPS*STEP} pts OTM) current expiry &nbsp;·&nbsp; "
    f"Buy 2L far expiry at ~50% LTP</p>",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
if not secrets_ok():
    st.error("Add Upstox credentials to `.streamlit/secrets.toml`")
    st.code('[upstox]\napi_key="..."\napi_secret="..."\nredirect_uri="http://localhost:8501"', language="toml")
    st.stop()

api_key      = st.secrets["upstox"]["api_key"]
api_secret   = st.secrets["upstox"]["api_secret"]
redirect_uri = st.secrets["upstox"]["redirect_uri"]

if "access_token" not in st.session_state:
    try:
        baked = st.secrets["upstox"].get("access_token", "")
        if baked:
            st.session_state.update(access_token=baked, token_acquired=time.time())
    except Exception:
        pass

qp = st.query_params
if qp.get("code") and "access_token" not in st.session_state:
    with st.spinner("Completing Upstox login…"):
        tok, err = exchange_code(api_key, api_secret, redirect_uri, qp["code"])
    if tok:
        st.session_state.update(access_token=tok, token_acquired=time.time())
        st.query_params.clear(); st.rerun()
    else:
        st.error(f"Login failed: {err}"); st.stop()

if "access_token" in st.session_state:
    if time.time() - st.session_state.get("token_acquired", 0) > 86400:
        del st.session_state["access_token"]; st.rerun()

if "access_token" not in st.session_state:
    auth_url = build_auth_url(api_key, redirect_uri)
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("### 🔐 Login with Upstox")
    st.markdown("<p style='color:#4a6080;font-size:12px;font-family:monospace;'>One click per trading day</p>",
                unsafe_allow_html=True)
    st.link_button("CONNECT →", auth_url, use_container_width=False)
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

token = st.session_state["access_token"]

# ─────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>⚙️ Parameters</div>", unsafe_allow_html=True)
col_p1, col_p2 = st.columns([2, 2])
with col_p1:
    sell_lots = st.number_input("Short Leg Lots (SELL)", min_value=1, max_value=20, value=1)
with col_p2:
    ltp_ratio = st.slider("Long LTP target (% of Sell LTP)", 30, 80, 50, 5,
                          help="Far strike selected where LTP ≈ this % of the sold LTP")

# ─────────────────────────────────────────────
# EXPIRY DATES
# ─────────────────────────────────────────────
with st.spinner("Fetching NIFTY expiry dates…"):
    all_exp, exp_err = fetch_expiries(token)

if exp_err == "token_expired":
    del st.session_state["access_token"]; st.rerun()
if exp_err or not all_exp:
    st.error(f"Expiry fetch failed: {exp_err}"); st.stop()

today         = datetime.now(IST).date()
near_cutoff   = today + timedelta(weeks=3)
far_cutoff    = today + timedelta(weeks=5)
near_expiries = [d for d in all_exp if datetime.strptime(d,"%Y-%m-%d").date() <= near_cutoff] or all_exp[:2]
far_expiries  = [d for d in all_exp if datetime.strptime(d,"%Y-%m-%d").date() >= far_cutoff]  or all_exp[4:]

col_e1, col_e2 = st.columns(2)
with col_e1:
    near_exp = st.selectbox(f"📅 Current Expiry — SELL ({len(near_expiries)} available)", near_expiries)
with col_e2:
    far_exp  = st.selectbox(f"📅 Far Expiry — BUY ≥5 weeks ({len(far_expiries)} available)", far_expiries)

nw = weeks_out(near_exp)
fw = weeks_out(far_exp)
st.markdown(
    f"<p class='mono' style='font-size:11px;color:var(--muted);'>"
    f"Near <b style='color:#ffc940'>{near_exp}</b> ({nw:.1f} wks) &nbsp;│&nbsp; "
    f"Far  <b style='color:#00e676'>{far_exp}</b> ({fw:.1f} wks) &nbsp;│&nbsp; "
    f"Gap <b style='color:white'>{fw-nw:.1f} wks</b></p>",
    unsafe_allow_html=True,
)
if fw < 4.5:
    st.warning(f"⚠️ Far expiry is only {fw:.1f} weeks away — strategy works best with 5+ weeks gap.")

# ─────────────────────────────────────────────
# LOAD CHAINS
# ─────────────────────────────────────────────
with st.spinner("Loading option chains…"):
    near_raw, ne = fetch_chain(token, near_exp)
    far_raw,  fe = fetch_chain(token, far_exp)

for err in [ne, fe]:
    if err == "token_expired":
        del st.session_state["access_token"]; st.rerun()
if ne or not near_raw:
    st.error(f"Near chain error: {ne}"); st.stop()
if fe or not far_raw:
    st.error(f"Far chain error: {fe}"); st.stop()

spot, atm, near_ce, near_pe, near_ce_oi, near_pe_oi, near_ce_oi_chg, near_pe_oi_chg = parse_chain(near_raw)
_,    _,   far_ce,  far_pe,  _,          _,           _,              _               = parse_chain(far_raw)

# ── VIX fetch (needed before strike selection) ──────────────────────────────
_open_vix, _curr_vix, _vix_err = fetch_vix(token)
if _vix_err == "token_expired":
    del st.session_state["access_token"]; st.rerun()

_days_to_exp = max(
    (datetime.strptime(near_exp, "%Y-%m-%d").date() - now.date()).days, 1
)

if _open_vix and _curr_vix and spot:
    _eff_vix   = max(_open_vix, _curr_vix)
    _daily_vix = _eff_vix / math.sqrt(252)
    _exp_1s    = spot * (_eff_vix / 100) * math.sqrt(_days_to_exp / 252)
    _exp_2s    = _exp_1s * 2
    _steps_1s  = max(1, round(_exp_1s / STEP))
    _steps_2s  = max(1, round(_exp_2s / STEP))
    _vix_ok    = True
else:
    _eff_vix = _daily_vix = _exp_1s = _exp_2s = 0.0
    _steps_1s = _steps_2s = SHORT_STEPS          # fallback to constant
    _vix_ok   = False

# Seed session_state with VIX default only when VIX value changes
# (preserves user override across auto-refreshes, resets when VIX shifts)
_vix_default = _steps_1s  # VIX-implied steps (or fallback SHORT_STEPS)
if st.session_state.get("_last_vix_default") != _vix_default:
    st.session_state["_last_vix_default"] = _vix_default
    st.session_state["short_steps_val"]   = _vix_default

# short_steps slider is rendered inside the VIX section below;
# read the current value from session_state here so strike calc uses it
short_steps = st.session_state.get("short_steps_val", _vix_default)

# ─────────────────────────────────────────────
# AUTO-ADJUST SELL STRIKES — CE and PE independently
# Walk toward ATM until long LTP <= sell LTP (ratio makes sense)
# ─────────────────────────────────────────────
ce_steps, sell_ce_strike, sell_ce_ltp, ce_cands, ce_adjusted = \
    auto_adjust_sell_strike(short_steps, atm, near_ce, far_ce, "CE", ltp_ratio)
pe_steps, sell_pe_strike, sell_pe_ltp, pe_cands, pe_adjusted = \
    auto_adjust_sell_strike(short_steps, atm, near_pe, far_pe, "PE", ltp_ratio)

best_ce = ce_cands[0] if ce_cands else {"strike": sell_ce_strike, "ltp": 0, "diff_pct": 99}
best_pe = pe_cands[0] if pe_cands else {"strike": sell_pe_strike, "ltp": 0, "diff_pct": 99}

# ─────────────────────────────────────────────
# MARKET SNAPSHOT
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>📊 Market Snapshot</div>", unsafe_allow_html=True)

# Row 1 — Spot + ATM
r1c1, r1c2 = st.columns(2)
with r1c1:
    st.markdown(f"<div class='card'><div class='lbl'>NIFTY Spot</div>"
                f"<div class='val-big'>₹{spot:,.2f}</div></div>", unsafe_allow_html=True)
with r1c2:
    st.markdown(f"<div class='card card-gold'><div class='lbl'>ATM Strike</div>"
                f"<div class='val-big val-gold'>{atm}</div></div>", unsafe_allow_html=True)

# Row 1b — PCR + SPCL (near chain, using exact atm_tracker formulas)
try:
    _pcr, _pcr_chg, _tot_ce_oi, _tot_pe_oi, _spcl, _atm_ce, _atm_pe, (_sent_lbl, _sent_col) = \
        calc_pcr_spcl(near_ce, near_pe, near_ce_oi, near_pe_oi,
                      near_ce_oi_chg, near_pe_oi_chg, atm,
                      vix_day_open=_open_vix if _vix_ok else None)
except Exception as _pcr_ex:
    st.error(f"PCR calc error: {_pcr_ex}")
    _pcr = _pcr_chg = _tot_ce_oi = _tot_pe_oi = _atm_ce = _atm_pe = 0.0
    _spcl = None
    _sent_lbl, _sent_col = "N/A", "var(--muted)"

_prev_pcr = st.session_state.get("prev_pcr", _pcr)
st.session_state["prev_pcr"] = _pcr
_pcr_delta = _pcr - _prev_pcr
_pcr_has_oi = _tot_ce_oi > 0

# ATM-specific OI (single strike)
_atm_ce_oi = near_ce_oi.get(float(atm), 0)
_atm_pe_oi = near_pe_oi.get(float(atm), 0)
_atm_pcr   = (_atm_pe_oi / _atm_ce_oi) if _atm_ce_oi > 0 else 0.0
_atm_has_oi = _atm_ce_oi > 0

pb1, pb2, pb3 = st.columns(3)
with pb1:
    if _pcr_has_oi:
        _pcr_dir_col = "var(--bull)" if _pcr_delta > 0.01 else ("var(--bear)" if _pcr_delta < -0.01 else "var(--muted)")
        _pcr_dir_sym = "↑" if _pcr_delta > 0.01 else ("↓" if _pcr_delta < -0.01 else "→")
        # ATM PCR pill
        _atm_pcr_str = f"{_atm_pcr:.2f}" if _atm_has_oi else "—"
        _atm_pcr_col = "var(--bull)" if _atm_pcr >= 1.1 else ("var(--bear)" if _atm_pcr < 0.9 and _atm_has_oi else "var(--gold)")
        st.markdown(
            f"<div class='card' style='border-left:4px solid {_sent_col};'>"
            f"<div class='lbl'>PCR OI &nbsp;·&nbsp; ATM±10 strikes</div>"
            f"<div style='display:flex;align-items:baseline;gap:10px;margin:.25rem 0;'>"
            f"<span class='val-big' style='color:{_sent_col};'>{_pcr:.2f}</span>"
            f"<span style='font-family:var(--mono);font-size:11px;font-weight:700;"
            f"background:{_sent_col};color:var(--text-inv);border-radius:3px;padding:2px 7px;'>{_sent_lbl}</span>"
            f"</div>"
            f"<div class='lbl'>"
            f"<span style='color:{_pcr_dir_col};font-weight:700;'>{_pcr_chg:.2f}{_pcr_dir_sym}{_pcr:.2f}</span>"
            f" &nbsp;·&nbsp; CE:ATM+10 | PE:ATM-10<br>"
            f"CE OI <b>{_tot_ce_oi/1e5:.1f}L</b> &nbsp;·&nbsp; PE OI <b>{_tot_pe_oi/1e5:.1f}L</b>"
            f"</div>"
            f"<div style='margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--border);'>"
            f"<span class='lbl'>ATM <span class='strike-pill-ce'>{atm}</span> PCR &nbsp;</span>"
            f"<span style='font-family:var(--mono);font-size:14px;font-weight:700;color:{_atm_pcr_col};'>{_atm_pcr_str}</span>"
            f"<span class='lbl'> &nbsp;CE {_atm_ce_oi/1e5:.1f}L / PE {_atm_pe_oi/1e5:.1f}L</span>"
            f"</div></div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div class='card'><div class='lbl'>PCR OI</div>"
            f"<div class='val-big' style='color:var(--muted);'>N/A</div>"
            f"<div class='lbl'>OI not available in feed</div></div>",
            unsafe_allow_html=True)
with pb2:
    if _spcl is not None:
        _spcl_col   = "var(--bull)" if _spcl > 0 else "var(--muted)"
        st.markdown(
            f"<div class='card card-gold'>"
            f"<div class='lbl'>SPCL VAL &nbsp;·&nbsp; (√(CE+PE)×π/2 adj VIX)</div>"
            f"<div class='val-big val-gold'>{_spcl:.2f}</div>"
            f"<div class='lbl'>"
            f"ATM CE <b style='color:var(--ce);'>₹{_atm_ce:.2f}</b> &nbsp;+&nbsp; "
            f"ATM PE <b style='color:var(--pe);'>₹{_atm_pe:.2f}</b> &nbsp;·&nbsp; "
            f"<span class='strike-pill-ce'>{atm}</span>"
            f"</div></div>",
            unsafe_allow_html=True)
    else:
        _straddle = _atm_ce + _atm_pe
        st.markdown(
            f"<div class='card card-gold'>"
            f"<div class='lbl'>ATM Straddle (VIX unavailable for SPCL)</div>"
            f"<div class='val-big val-gold'>{_straddle:.2f}</div>"
            f"<div class='lbl'>"
            f"CE <b style='color:var(--ce);'>₹{_atm_ce:.2f}</b> + PE <b style='color:var(--pe);'>₹{_atm_pe:.2f}</b>"
            f"</div></div>",
            unsafe_allow_html=True)
with pb3:
    _sell_ce_ltp2 = near_ce.get(float(sell_ce_strike), 0)
    _sell_pe_ltp2 = near_pe.get(float(sell_pe_strike), 0)
    _strangle_val = _sell_ce_ltp2 + _sell_pe_ltp2
    st.markdown(
        f"<div class='card' style='border-left:4px solid var(--bear);'>"
        f"<div class='lbl'>Sell Strangle Premium</div>"
        f"<div class='val-big val-bear'>₹{_strangle_val:.2f}</div>"
        f"<div class='lbl'>"
        f"CE <span class='strike-pill-ce'>{sell_ce_strike}</span> ₹{_sell_ce_ltp2:.2f} &nbsp;+&nbsp; "
        f"PE <span class='strike-pill'>{sell_pe_strike}</span> ₹{_sell_pe_ltp2:.2f}"
        f"</div></div>",
        unsafe_allow_html=True)

# Row 2 — CE legs
r2c1, r2c2 = st.columns(2)
ce_buy_pct = f"{best_ce['ltp']/sell_ce_ltp*100:.0f}% of sell LTP" if sell_ce_ltp > 0 and best_ce['ltp'] > 0 else ""
_ce_adj_note = f" &nbsp;<span style='color:var(--gold);font-size:9px;'>⚙️ adj from {short_steps}</span>" if ce_adjusted else ""
with r2c1:
    st.markdown(
        f"<div class='card card-ce'>"
        f"<div class='lbl'>"
        f"<span class='date-pill'>📅 {near_exp}</span>"
        f"&nbsp; CE SELL — ATM+{ce_steps}{_ce_adj_note}"
        f"</div>"
        f"<div class='val-big val-ce'>₹{sell_ce_ltp:.2f}</div>"
        f"<div style='margin-top:4px;'><span class='strike-pill-ce'>{sell_ce_strike}</span></div>"
        f"</div>", unsafe_allow_html=True)
with r2c2:
    _ce_ratio_ok = best_ce['ltp'] <= sell_ce_ltp
    _ce_ratio_icon = "✅" if _ce_ratio_ok else "⚠️"
    st.markdown(
        f"<div class='card card-bull'>"
        f"<div class='lbl'>"
        f"<span class='date-pill' style='background:var(--bull-dim);color:var(--bull);border-color:var(--bull);'>📅 {far_exp}</span>"
        f"&nbsp; CE BUY (far) — best match"
        f"</div>"
        f"<div class='val-big val-bull'>₹{best_ce['ltp']:.2f}</div>"
        f"<div style='margin-top:4px;'><span class='strike-pill-buy'>{int(best_ce['strike'])}</span>"
        f"&nbsp;<span class='lbl'>{ce_buy_pct} {_ce_ratio_icon}</span></div>"
        f"</div>", unsafe_allow_html=True)

# Row 3 — PE legs
r3c1, r3c2 = st.columns(2)
pe_buy_pct = f"{best_pe['ltp']/sell_pe_ltp*100:.0f}% of sell LTP" if sell_pe_ltp > 0 and best_pe['ltp'] > 0 else ""
_pe_adj_note = f" &nbsp;<span style='color:var(--gold);font-size:9px;'>⚙️ adj from {short_steps}</span>" if pe_adjusted else ""
with r3c1:
    st.markdown(
        f"<div class='card card-pe'>"
        f"<div class='lbl'>"
        f"<span class='date-pill' style='border-color:var(--pe);color:var(--pe);'>📅 {near_exp}</span>"
        f"&nbsp; PE SELL — ATM-{pe_steps}{_pe_adj_note}"
        f"</div>"
        f"<div class='val-big val-pe'>₹{sell_pe_ltp:.2f}</div>"
        f"<div style='margin-top:4px;'><span class='strike-pill'>{sell_pe_strike}</span></div>"
        f"</div>", unsafe_allow_html=True)
with r3c2:
    _pe_ratio_ok = best_pe['ltp'] <= sell_pe_ltp
    _pe_ratio_icon = "✅" if _pe_ratio_ok else "⚠️"
    st.markdown(
        f"<div class='card card-bull'>"
        f"<div class='lbl'>"
        f"<span class='date-pill' style='background:var(--bull-dim);color:var(--bull);border-color:var(--bull);'>📅 {far_exp}</span>"
        f"&nbsp; PE BUY (far) — best match"
        f"</div>"
        f"<div class='val-big val-bull'>₹{best_pe['ltp']:.2f}</div>"
        f"<div style='margin-top:4px;'><span class='strike-pill-buy'>{int(best_pe['strike'])}</span>"
        f"&nbsp;<span class='lbl'>{pe_buy_pct} {_pe_ratio_icon}</span></div>"
        f"</div>", unsafe_allow_html=True)

if sell_ce_ltp == 0 or sell_pe_ltp == 0:
    st.warning(f"⚠️ Sell strikes ({sell_ce_strike}/{sell_pe_strike}) have zero LTP — "
               f"try a smaller steps value or check market hours.")
if ce_adjusted or pe_adjusted:
    _adj_parts = []
    if ce_adjusted: _adj_parts.append(f"CE moved to {ce_steps} steps (was {short_steps})")
    if pe_adjusted: _adj_parts.append(f"PE moved to {pe_steps} steps (was {short_steps})")
    st.info(f"⚙️ Sell strikes auto-adjusted: {' · '.join(_adj_parts)} — long leg was more expensive than short at requested distance.")

# ─────────────────────────────────────────────
# VIX ANALYSIS — expected move & auto-derived strikes
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>🌡️ India VIX — Expected Move &amp; Auto Strike Selection</div>",
            unsafe_allow_html=True)

if not _vix_ok:
    st.warning(f"VIX data unavailable ({_vix_err}) — strikes defaulted to {SHORT_STEPS} steps.")
else:
    # Derived range bounds (rounded to nearest strike)
    _upper_1s = round((spot + _exp_1s) / STEP) * STEP
    _lower_1s = round((spot - _exp_1s) / STEP) * STEP
    _upper_2s = round((spot + _exp_2s) / STEP) * STEP
    _lower_2s = round((spot - _exp_2s) / STEP) * STEP

    _vix_trend = ("↑ expanding" if _curr_vix > _open_vix
                  else ("↓ contracting" if _curr_vix < _open_vix else "→ unchanged"))

    # ── Row 1: VIX cards ────────────────────────
    _v1, _v2, _v3, _v4 = st.columns(4)
    with _v1:
        st.markdown(
            f"<div class='card'><div class='lbl'>VIX Open</div>"
            f"<div class='val-big val-gold'>{_open_vix:.2f}</div></div>",
            unsafe_allow_html=True)
    with _v2:
        _vcol = "var(--bear)" if _curr_vix > _open_vix else "var(--bull)"
        st.markdown(
            f"<div class='card'><div class='lbl'>VIX Current ({_vix_trend})</div>"
            f"<div class='val-big' style='color:{_vcol};'>{_curr_vix:.2f}</div></div>",
            unsafe_allow_html=True)
    with _v3:
        st.markdown(
            f"<div class='card card-gold'><div class='lbl'>Effective VIX (higher of two)</div>"
            f"<div class='val-big val-gold'>{_eff_vix:.2f}</div>"
            f"<div class='lbl'>Daily σ: {_daily_vix:.2f}%</div></div>",
            unsafe_allow_html=True)
    with _v4:
        st.markdown(
            f"<div class='card'><div class='lbl'>DTE → sell strike</div>"
            f"<div class='val-big'>{_days_to_exp}d</div>"
            f"<div class='lbl'>{near_exp}</div></div>",
            unsafe_allow_html=True)

    # ── Strike selector slider (VIX-defaulted, user-adjustable) ────────────
    _sl_col1, _sl_col2 = st.columns([3, 1])
    with _sl_col1:
        short_steps = st.slider(
            f"OTM Steps for Sell Leg  ·  VIX suggests {_steps_1s} steps ({_steps_1s * STEP} pts)  ·  2σ = {_steps_2s} steps",
            min_value=1, max_value=20,
            value=st.session_state.get("short_steps_val", _vix_default),
            key="short_steps_slider",
            help="Default = VIX 1σ range. Drag right → safer (less premium). Drag left → more premium (higher risk).",
        )
        st.session_state["short_steps_val"] = short_steps
    with _sl_col2:
        if st.button("↺ Reset to VIX", help="Reset to VIX-implied 1σ steps"):
            st.session_state["short_steps_val"]   = _vix_default
            st.session_state["_last_vix_default"] = _vix_default
            st.rerun()

    # ── Row 2: Expected move + actual strike positions ──────────────────────
    _m1, _m2 = st.columns(2)
    with _m1:
        def _vs_vix_label(steps, opt):
            if steps == _steps_1s: return "✅ at VIX 1σ"
            if steps > _steps_1s:  return f"↗ {steps - _steps_1s} steps wider than 1σ"
            return f"↙ {_steps_1s - steps} steps tighter than 1σ (auto-adjusted)"
        _ce_pos = _vs_vix_label(ce_steps, "CE")
        _pe_pos = _vs_vix_label(pe_steps, "PE")
        st.markdown(
            f"<div class='card card-bull'>"
            f"<div class='lbl'>1σ Expected Move — {_days_to_exp} days to expiry</div>"
            f"<div class='val-big val-bull'>± {_exp_1s:,.0f} pts</div>"
            f"<div class='lbl'>"
            f"Upper: <b style='color:var(--ce);'>{_upper_1s:,}</b> &nbsp;·&nbsp; "
            f"Lower: <b style='color:var(--pe);'>{_lower_1s:,}</b><br>"
            f"CE: {sell_ce_strike} ({ce_steps} steps) → {_ce_pos}<br>"
            f"PE: {sell_pe_strike} ({pe_steps} steps) → {_pe_pos}"
            f"</div></div>",
            unsafe_allow_html=True)
    with _m2:
        st.markdown(
            f"<div class='card' style='border-left:3px solid var(--bear);'>"
            f"<div class='lbl'>2σ Move — tail / danger zone</div>"
            f"<div class='val-big val-bear'>± {_exp_2s:,.0f} pts</div>"
            f"<div class='lbl'>"
            f"Upper: <b style='color:var(--ce);'>{_upper_2s:,}</b> &nbsp;·&nbsp; "
            f"Lower: <b style='color:var(--pe);'>{_lower_2s:,}</b><br>"
            f"<b style='color:var(--bear);'>{_steps_2s} steps OTM</b><br>"
            f"CE sell: {'✅ beyond 2σ' if ce_steps >= _steps_2s else ('⚠️ 1–2σ zone' if ce_steps >= _steps_1s else '🔴 inside 1σ')} &nbsp;·&nbsp; "
            f"PE sell: {'✅ beyond 2σ' if pe_steps >= _steps_2s else ('⚠️ 1–2σ zone' if pe_steps >= _steps_1s else '🔴 inside 1σ')}"
            f"</div></div>",
            unsafe_allow_html=True)

# ─────────────────────────────────────────────
# COMBINED OPTION CHAIN — near + far side by side
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>📋 Option Chain — Near vs Far (ATM ±10)</div>", unsafe_allow_html=True)

# Target LTPs (ce_cands / pe_cands / best_ce / best_pe computed above before snapshot)
target_ce = sell_ce_ltp * ltp_ratio / 100.0
target_pe = sell_pe_ltp * ltp_ratio / 100.0

# Build table: ±10 strikes around ATM
rows_html = ""
for i in range(-10, 11):
    s       = atm + i * STEP
    nce_ltp = near_ce.get(float(s), 0)
    npe_ltp = near_pe.get(float(s), 0)
    fce_ltp = far_ce.get(float(s),  0)
    fpe_ltp = far_pe.get(float(s),  0)

    is_atm       = s == atm
    is_sell_ce   = s == sell_ce_strike
    is_sell_pe   = s == sell_pe_strike
    is_best_ce   = s == best_ce["strike"]
    is_best_pe   = s == best_pe["strike"]

    row_cls = ""
    if is_atm:       row_cls = "atm-row"
    elif is_sell_ce or is_sell_pe: row_cls = "sell-row"
    elif is_best_ce or is_best_pe: row_cls = "buy-row"

    # Strike label
    if   is_atm:      step_lbl = f"{s} <span class='atm-tag'>ATM</span>"
    elif is_sell_ce:  step_lbl = f"{s} <span class='sell-tag'>CE SELL</span>"
    elif is_sell_pe:  step_lbl = f"{s} <span class='sell-tag'>PE SELL</span>"
    elif is_best_ce:  step_lbl = f"{s} <span class='buy-tag'>CE BUY★</span>"
    elif is_best_pe:  step_lbl = f"{s} <span class='buy-tag'>PE BUY★</span>"
    else:             step_lbl = str(s)

    # CE LTP colouring
    nce_col = "var(--bear)" if is_sell_ce else ("var(--ce)" if nce_ltp > 0 else "var(--muted)")
    fce_col = "var(--bull)" if is_best_ce else ("var(--ce)" if fce_ltp > 0 else "var(--muted)")

    # PE LTP colouring
    npe_col = "var(--bear)" if is_sell_pe else ("var(--pe)" if npe_ltp > 0 else "var(--muted)")
    fpe_col = "var(--bull)" if is_best_pe else ("var(--pe)" if fpe_ltp > 0 else "var(--muted)")

    # Ratio hint for far CE / PE
    fce_ratio_str = (f"<span style='color:#4a6080;font-size:9px;'> ({fce_ltp/sell_ce_ltp*100:.0f}%)</span>"
                     if sell_ce_ltp > 0 and fce_ltp > 0 else "")
    fpe_ratio_str = (f"<span style='color:#4a6080;font-size:9px;'> ({fpe_ltp/sell_pe_ltp*100:.0f}%)</span>"
                     if sell_pe_ltp > 0 and fpe_ltp > 0 else "")

    rows_html += (
        f"<tr class='{row_cls}'>"
        # Near CE
        f"<td style='color:{nce_col};'>{'🔴 ' if is_sell_ce else ''}{'₹'+str(round(nce_ltp,2)) if nce_ltp else '—'}</td>"
        # Strike
        f"<td class='strike-col'>{step_lbl}</td>"
        # Near PE
        f"<td style='color:{npe_col};'>{'🔴 ' if is_sell_pe else ''}{'₹'+str(round(npe_ltp,2)) if npe_ltp else '—'}</td>"
        # Far CE
        f"<td style='color:{fce_col};'>{'🟢 ' if is_best_ce else ''}{'₹'+str(round(fce_ltp,2)) if fce_ltp else '—'}{fce_ratio_str}</td>"
        # Far PE
        f"<td style='color:{fpe_col};'>{'🟢 ' if is_best_pe else ''}{'₹'+str(round(fpe_ltp,2)) if fpe_ltp else '—'}{fpe_ratio_str}</td>"
        f"</tr>"
    )

st.markdown(
    f"<table class='chain-table'><thead><tr>"
    f"<th>Near CE LTP<br><small>{near_exp}</small></th>"
    f"<th>Strike</th>"
    f"<th>Near PE LTP<br><small>{near_exp}</small></th>"
    f"<th>Far CE LTP<br><small>{far_exp}</small></th>"
    f"<th>Far PE LTP<br><small>{far_exp}</small></th>"
    f"</tr></thead><tbody>{rows_html}</tbody></table>",
    unsafe_allow_html=True,
)
st.caption(
    f"🔴 = Short strike (sell) &nbsp;│&nbsp; 🟢 = Best auto-matched long (buy) &nbsp;│&nbsp; "
    f"% in far columns = ratio vs sold LTP &nbsp;│&nbsp; Target ratio: {ltp_ratio}%"
)

# ─────────────────────────────────────────────
# LONG LEG SELECTORS — far expiry
# ─────────────────────────────────────────────
st.markdown(
    f"<div class='sec-hdr'>🟢 Long Leg Selection — Far Expiry ({far_exp}) · {BUY_LOTS} lots · "
    f"Target LTP ≈ {ltp_ratio}% of sold LTP</div>",
    unsafe_allow_html=True,
)

col_lce, col_lpe = st.columns(2)

with col_lce:
    if not ce_cands:
        st.warning("No CE candidates found in far chain.")
        buy_ce_strike = sell_ce_strike
        buy_ce_ltp    = far_ce.get(float(buy_ce_strike), 0)
    else:
        def _ce_label(i, m):
            tag = "✅ best match" if i == 0 else f"{m['diff_pct']:.1f}% off target"
            return (f"CE {m['strike']}  ·  LTP ₹{m['ltp']:.2f}  ·  "
                    f"{m['ltp']/sell_ce_ltp*100:.0f}% of ₹{sell_ce_ltp:.2f}  ({tag})")
        ce_opts = {_ce_label(i, m): m for i, m in enumerate(ce_cands)}
        sel_ce    = st.selectbox("BUY CE Strike — Far Expiry", list(ce_opts.keys()), key="buy_ce")
        best_sel_ce = ce_opts[sel_ce]
        buy_ce_strike = best_sel_ce["strike"]
        buy_ce_ltp    = best_sel_ce["ltp"]

    ratio_ce_actual = buy_ce_ltp / sell_ce_ltp * 100 if sell_ce_ltp > 0 else 0
    ratio_ce_ok     = abs(ratio_ce_actual - ltp_ratio) < 20

    st.markdown(
        f"<div class='card card-ce'>"
        f"<span class='tag tag-buy'>BUY {BUY_LOTS}L</span>&nbsp;"
        f"<span class='tag tag-ce'>CE</span>&nbsp;&nbsp;"
        f"<span class='mono'>Strike <b>{buy_ce_strike}</b> &nbsp;│&nbsp; "
        f"LTP <b style='color:var(--bull)'>₹{buy_ce_ltp:.2f}</b> &nbsp;│&nbsp; "
        f"Ratio <b style='color:{'var(--bull)' if ratio_ce_ok else 'var(--gold)'}'>{'✅' if ratio_ce_ok else '⚠️'} "
        f"{ratio_ce_actual:.0f}% of sell LTP</b> &nbsp;│&nbsp; "
        f"Cost <b style='color:var(--bear)'>₹{buy_ce_ltp*BUY_LOTS*LOT_SIZE:,.0f}</b>"
        f"</span></div>",
        unsafe_allow_html=True,
    )

with col_lpe:
    if not pe_cands:
        st.warning("No PE candidates found in far chain.")
        buy_pe_strike = sell_pe_strike
        buy_pe_ltp    = far_pe.get(float(buy_pe_strike), 0)
    else:
        def _pe_label(i, m):
            tag = "✅ best match" if i == 0 else f"{m['diff_pct']:.1f}% off target"
            return (f"PE {m['strike']}  ·  LTP ₹{m['ltp']:.2f}  ·  "
                    f"{m['ltp']/sell_pe_ltp*100:.0f}% of ₹{sell_pe_ltp:.2f}  ({tag})")
        pe_opts = {_pe_label(i, m): m for i, m in enumerate(pe_cands)}
        sel_pe    = st.selectbox("BUY PE Strike — Far Expiry", list(pe_opts.keys()), key="buy_pe")
        best_sel_pe = pe_opts[sel_pe]
        buy_pe_strike = best_sel_pe["strike"]
        buy_pe_ltp    = best_sel_pe["ltp"]

    ratio_pe_actual = buy_pe_ltp / sell_pe_ltp * 100 if sell_pe_ltp > 0 else 0
    ratio_pe_ok     = abs(ratio_pe_actual - ltp_ratio) < 20

    st.markdown(
        f"<div class='card card-pe'>"
        f"<span class='tag tag-buy'>BUY {BUY_LOTS}L</span>&nbsp;"
        f"<span class='tag tag-pe'>PE</span>&nbsp;&nbsp;"
        f"<span class='mono'>Strike <b>{buy_pe_strike}</b> &nbsp;│&nbsp; "
        f"LTP <b style='color:var(--bull)'>₹{buy_pe_ltp:.2f}</b> &nbsp;│&nbsp; "
        f"Ratio <b style='color:{'var(--bull)' if ratio_pe_ok else 'var(--gold)'}'>{'✅' if ratio_pe_ok else '⚠️'} "
        f"{ratio_pe_actual:.0f}% of sell LTP</b> &nbsp;│&nbsp; "
        f"Cost <b style='color:var(--bear)'>₹{buy_pe_ltp*BUY_LOTS*LOT_SIZE:,.0f}</b>"
        f"</span></div>",
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────
# TRADE SCHEDULER
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>⏰ Trade Scheduler</div>", unsafe_allow_html=True)

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

sched_col1, sched_col2, sched_col3 = st.columns([2, 2, 3])
with sched_col1:
    sched_day = st.selectbox(
        "Initiate on Day",
        WEEKDAY_NAMES,
        index=st.session_state.get("sched_day_idx", 0),
        key="sched_day_sel",
    )
    st.session_state["sched_day_idx"] = WEEKDAY_NAMES.index(sched_day)
with sched_col2:
    sched_time_str = st.text_input(
        "At Time (HH:MM, 24h IST)",
        value=st.session_state.get("sched_time_str", "15:15"),
        key="sched_time_inp",
    )
    st.session_state["sched_time_str"] = sched_time_str
with sched_col3:
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.info(f"📌 Current schedule: **{sched_day} {sched_time_str} IST** — keep running app, it will alert when it's time.")

# Parse schedule and compute next trigger
_sched_ok = False
try:
    _th, _tm = [int(x) for x in sched_time_str.split(":")]
    _target_weekday = WEEKDAY_NAMES.index(sched_day)  # 0=Mon … 4=Fri
    _sched_ok = True
except Exception:
    st.warning("⚠️ Invalid time format — use HH:MM (e.g. 15:15)")

if _sched_ok:
    _now_dt   = now  # already datetime with IST tz
    _now_wd   = _now_dt.weekday()          # 0=Mon
    _days_fwd = (_target_weekday - _now_wd) % 7
    _next_trigger = _now_dt.replace(hour=_th, minute=_tm, second=0, microsecond=0)
    if _days_fwd > 0:
        _next_trigger += timedelta(days=_days_fwd)
    elif _days_fwd == 0 and _now_dt >= _next_trigger:
        _next_trigger += timedelta(days=7)   # same weekday but already past → next week

    _delta = _next_trigger - _now_dt
    _delta_secs = int(_delta.total_seconds())
    _hrs, _rem  = divmod(_delta_secs, 3600)
    _mins, _secs = divmod(_rem, 60)
    _countdown_str = f"{_hrs}h {_mins}m {_secs}s"

    # Within 5 min past trigger on the right day → FIRE ALERT
    _on_trigger_day = (_now_dt.weekday() == _target_weekday)
    _trigger_time_today = _now_dt.replace(hour=_th, minute=_tm, second=0, microsecond=0)
    _secs_past = (_now_dt - _trigger_time_today).total_seconds()
    _is_trigger_window = _on_trigger_day and (0 <= _secs_past <= 300)   # 0–5 min window

    if _is_trigger_window:
        st.markdown(
            f"<div style='background:#003318;border:2px solid #00e676;border-radius:10px;"
            f"padding:1rem 1.5rem;text-align:center;'>"
            f"<div style='font-family:var(--hdr);font-size:22px;color:#00e676;'>🚨 INITIATE POSITIONS NOW</div>"
            f"<div style='font-family:var(--mono);font-size:13px;color:#c8d8f0;margin-top:.4rem;'>"
            f"It is {sched_day} {sched_time_str} IST &nbsp;·&nbsp; "
            f"CE SELL {sell_ce_strike} @₹{sell_ce_ltp:.2f} &nbsp;·&nbsp; "
            f"PE SELL {sell_pe_strike} @₹{sell_pe_ltp:.2f}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        _bar_pct = max(0, min(100, int(100 - _delta_secs / (7 * 86400) * 100)))
        st.markdown(
            f"<div style='background:var(--surface);border:1px solid var(--border);"
            f"border-radius:10px;padding:.75rem 1rem;'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-family:var(--mono);font-size:11px;color:var(--muted);'>NEXT TRIGGER</span>"
            f"<span style='font-family:var(--mono);font-size:16px;font-weight:700;color:#ffc940;'>"
            f"⏳ {_countdown_str}</span>"
            f"<span style='font-family:var(--mono);font-size:11px;color:var(--muted);'>"
            f"{_next_trigger.strftime('%a %d %b %Y %H:%M IST')}</span>"
            f"</div>"
            f"<div style='background:var(--border);border-radius:4px;height:4px;margin-top:.5rem;'>"
            f"<div style='background:var(--gold);height:4px;width:{_bar_pct}%;border-radius:4px;'></div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────
# SUMMARY & NET PREMIUM
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>💰 Position Summary</div>", unsafe_allow_html=True)

total_sell = (sell_ce_ltp * sell_lots + sell_pe_ltp * sell_lots) * LOT_SIZE
total_buy  = (buy_ce_ltp  * BUY_LOTS  + buy_pe_ltp  * BUY_LOTS)  * LOT_SIZE
net        = total_sell - total_buy
be_up      = sell_ce_strike + sell_ce_ltp
be_dn      = sell_pe_strike - sell_pe_ltp

legs = [
    {"opt_type":"CE","strike":sell_ce_strike,"ltp":sell_ce_ltp,"lots":sell_lots,"is_sell":True, "is_near":True},
    {"opt_type":"PE","strike":sell_pe_strike,"ltp":sell_pe_ltp,"lots":sell_lots,"is_sell":True, "is_near":True},
    {"opt_type":"CE","strike":buy_ce_strike, "ltp":buy_ce_ltp, "lots":BUY_LOTS, "is_sell":False,"is_near":False},
    {"opt_type":"PE","strike":buy_pe_strike, "ltp":buy_pe_ltp, "lots":BUY_LOTS, "is_sell":False,"is_near":False},
]

col_n, col_s, col_b, col_beu, col_bed = st.columns(5)
with col_n:
    lbl = "NET CREDIT" if net >= 0 else "NET DEBIT"
    st.markdown(
        f"<div class='card card-{'bull' if net>=0 else 'gold'}'>"
        f"<div class='lbl'>{lbl}</div>"
        f"<div class='val-big {'val-bull' if net>=0 else 'val-bear'}'>₹{abs(net):,.0f}</div></div>",
        unsafe_allow_html=True)
with col_s:
    st.markdown(
        f"<div class='card'><div class='lbl'>Premium Collected</div>"
        f"<div class='val-big val-bull'>₹{total_sell:,.0f}</div>"
        f"<div class='lbl'>{sell_lots}L × CE+PE short</div></div>", unsafe_allow_html=True)
with col_b:
    st.markdown(
        f"<div class='card'><div class='lbl'>Premium Paid</div>"
        f"<div class='val-big val-bear'>₹{total_buy:,.0f}</div>"
        f"<div class='lbl'>{BUY_LOTS}L × CE+PE long</div></div>", unsafe_allow_html=True)
with col_beu:
    st.markdown(
        f"<div class='card card-ce'><div class='lbl'>CE Breakeven ↑</div>"
        f"<div class='val-big val-ce'>{be_up:,.0f}</div>"
        f"<div class='lbl'>{sell_ce_strike} + {sell_ce_ltp:.0f}</div></div>", unsafe_allow_html=True)
with col_bed:
    st.markdown(
        f"<div class='card card-pe'><div class='lbl'>PE Breakeven ↓</div>"
        f"<div class='val-big val-pe'>{be_dn:,.0f}</div>"
        f"<div class='lbl'>{sell_pe_strike} − {sell_pe_ltp:.0f}</div></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# PAYOFF CHART
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>📈 Payoff at Near Expiry (far legs ~60% time value retained)</div>",
            unsafe_allow_html=True)
st.markdown(make_payoff_svg(legs, atm, LOT_SIZE, sell_ce_strike, sell_pe_strike), unsafe_allow_html=True)
st.caption(
    f"Blue dashed = CE short {sell_ce_strike} &nbsp;│&nbsp; "
    f"Purple dashed = PE short {sell_pe_strike} &nbsp;│&nbsp; "
    f"Green faint = long legs ({buy_ce_strike}, {buy_pe_strike}) &nbsp;│&nbsp; "
    f"Gold = ATM {atm}"
)

# ─────────────────────────────────────────────
# STRATEGY NOTES
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>⚠️ Notes</div>", unsafe_allow_html=True)
st.markdown(
    f"<div class='card'><span class='mono' style='font-size:11px;line-height:2;'>"
    f"• <b>Short</b> ({near_exp}): Sell {sell_lots}L CE {sell_ce_strike} @ ₹{sell_ce_ltp:.2f} + "
    f"{sell_lots}L PE {sell_pe_strike} @ ₹{sell_pe_ltp:.2f} "
    f"→ <span class='val-bull'>Collect ₹{total_sell:,.0f}</span><br>"
    f"• <b>Long</b> ({far_exp}): Buy {BUY_LOTS}L CE {buy_ce_strike} @ ₹{buy_ce_ltp:.2f} + "
    f"{BUY_LOTS}L PE {buy_pe_strike} @ ₹{buy_pe_ltp:.2f} "
    f"→ <span class='val-bear'>Pay ₹{total_buy:,.0f}</span><br>"
    f"• Net: <span class='{'val-bull' if net>=0 else 'val-bear'}'>{'Credit' if net>=0 else 'Debit'} "
    f"₹{abs(net):,.0f}</span> &nbsp;·&nbsp; "
    f"CE ratio {ratio_ce_actual:.0f}% &nbsp;·&nbsp; PE ratio {ratio_pe_actual:.0f}%<br>"
    f"• Ideal: near leg expires worthless every week → roll the short to next expiry &nbsp;·&nbsp; "
    f"far longs act as long-dated tail protection<br>"
    f"• CE sell at <b>{ce_steps} steps</b> ({sell_ce_strike}) · PE sell at <b>{pe_steps} steps</b> ({sell_pe_strike})"
    f"{' · auto-adjusted to ensure long < short LTP' if (ce_adjusted or pe_adjusted) else ''}"
    f" &nbsp;·&nbsp; VIX 1σ default = {_steps_1s if _vix_ok else 'N/A'} steps · use slider to override"
    f"</span></div>",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📐 NIFTY Diagonal")
    _theme_label = "☀️ Light mode" if not _light_mode else "🌙 Dark mode"
    if st.toggle(_theme_label, value=_light_mode, key="theme_toggle"):
        if not st.session_state.get("light_mode", False):
            st.session_state["light_mode"] = True
            st.rerun()
    else:
        if st.session_state.get("light_mode", False):
            st.session_state["light_mode"] = False
            st.rerun()
    st.divider()
    st.markdown(f"Spot **₹{spot:,.2f}** · ATM **{atm}**")
    st.markdown(f"Near `{near_exp}` · Far `{far_exp}`")
    st.divider()
    st.metric("Net Premium", f"₹{abs(net):,.0f}", f"{'Credit ↑' if net>=0 else 'Debit ↓'}")
    st.metric("Short CE", f"{sell_ce_strike}  @₹{sell_ce_ltp:.2f}")
    st.metric("Short PE", f"{sell_pe_strike}  @₹{sell_pe_ltp:.2f}")
    st.metric("Long CE", f"{buy_ce_strike}  @₹{buy_ce_ltp:.2f} ({ratio_ce_actual:.0f}%)")
    st.metric("Long PE", f"{buy_pe_strike}  @₹{buy_pe_ltp:.2f} ({ratio_pe_actual:.0f}%)")
    st.metric("BE ↑", f"{int(be_up):,}")
    st.metric("BE ↓", f"{int(be_dn):,}")
    st.divider()
    if _open_vix and _curr_vix:
        st.metric("VIX (eff)", f"{_eff_vix:.2f}",
                  f"{'↑' if _curr_vix > _open_vix else '↓'} open {_open_vix:.2f}")
        st.metric("1σ move", f"±{_exp_1s:,.0f} pts", f"{_steps_1s} steps OTM")
    st.divider()
    refresh_secs = st.slider("🔄 Auto-refresh (sec)", min_value=15, max_value=120, value=30, step=5)
    st.caption(f"Updated {now.strftime('%H:%M:%S IST')}")
    st.divider()
    if st.button("🔓 Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# ─────────────────────────────────────────────
# AUTO-REFRESH — live prices + scheduler tick
# ─────────────────────────────────────────────
time.sleep(refresh_secs)
st.rerun()
