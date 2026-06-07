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

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@700;800&display=swap');
  :root {
    --bg:       #080c14; --surface: #0d1321; --border: #1c2840; --border2: #253352;
    --text:     #c8d8f0; --muted:   #4a6080;
    --ce:       #2979ff; --pe:      #ab47bc;
    --bull:     #00e676; --bull-dim:#003318;
    --bear:     #ff5252; --bear-dim:#2a0808;
    --gold:     #ffc940; --gold-dim:#2a1e00;
    --mono: 'JetBrains Mono', monospace;
    --hdr:  'Syne', sans-serif;
  }
  html,body,.stApp { background:var(--bg)!important; color:var(--text); }
  .block-container  { padding:.75rem 1.2rem 1rem!important; }
  h1,h2,h3          { font-family:var(--hdr); color:white; }
  .sec-hdr {
    font-family:var(--hdr); font-size:11px; font-weight:700;
    color:var(--muted); letter-spacing:2px; text-transform:uppercase;
    margin:1.1rem 0 .45rem; padding-bottom:5px; border-bottom:1px solid var(--border);
  }
  .card { background:var(--surface); border:1px solid var(--border);
          border-radius:10px; padding:.75rem 1rem; margin-bottom:.5rem; }
  .card-ce   { border-left:3px solid var(--ce); }
  .card-pe   { border-left:3px solid var(--pe); }
  .card-bull { border-left:3px solid var(--bull); }
  .card-gold { border-left:3px solid var(--gold); }
  .mono { font-family:var(--mono); }
  .lbl  { color:var(--muted); font-size:10px; letter-spacing:1px; text-transform:uppercase; }
  .val-big  { font-family:var(--mono); font-size:20px; font-weight:700; color:white; }
  .val-ce   { color:var(--ce);   font-weight:600; }
  .val-pe   { color:var(--pe);   font-weight:600; }
  .val-bull { color:var(--bull); font-weight:700; }
  .val-bear { color:var(--bear); font-weight:700; }
  .val-gold { color:var(--gold); font-weight:600; }
  .tag { display:inline-block; font-size:9px; font-weight:700;
         padding:2px 7px; border-radius:3px; letter-spacing:.5px; }
  .tag-sell { background:var(--bear-dim); color:var(--bear); border:1px solid var(--bear); }
  .tag-buy  { background:var(--bull-dim); color:var(--bull); border:1px solid var(--bull); }
  .tag-ce   { background:#0d1e40; color:var(--ce); border:1px solid #1a3060; }
  .tag-pe   { background:#1e0a28; color:var(--pe); border:1px solid #3a1a50; }
  .chain-table { width:100%; border-collapse:collapse; font-family:var(--mono); font-size:11px; }
  .chain-table th { color:var(--muted); font-size:9px; letter-spacing:1.5px; text-transform:uppercase;
                    padding:4px 8px; border-bottom:1px solid var(--border); text-align:center; }
  .chain-table td { padding:5px 8px; border-bottom:1px solid var(--border); text-align:center; }
  .chain-table .atm-row { background:#1a1400; font-weight:700; }
  .chain-table .sell-row { background:#1a0808; }
  .chain-table .buy-row  { background:#003318; }
  .strike-col { color:var(--muted); }
  .atm-tag { display:inline-block; background:var(--gold-dim); color:var(--gold);
             font-size:8px; padding:1px 4px; border-radius:2px; margin-left:4px;
             font-family:var(--mono); border:1px solid var(--gold); }
  .sell-tag { display:inline-block; background:var(--bear-dim); color:var(--bear);
              font-size:8px; padding:1px 4px; border-radius:2px; margin-left:4px;
              font-family:var(--mono); border:1px solid var(--bear); }
  .buy-tag  { display:inline-block; background:var(--bull-dim); color:var(--bull);
              font-size:8px; padding:1px 4px; border-radius:2px; margin-left:4px;
              font-family:var(--mono); border:1px solid var(--bull); }
  .login-box { background:var(--surface); border:1px solid var(--border2);
               border-radius:14px; padding:2.5rem 2rem; text-align:center;
               max-width:460px; margin:3rem auto; }
  .err-box { background:#1a0808; border:1px solid #5a1a1a; border-radius:8px;
             padding:.6rem .9rem; color:#fc8181; font-family:var(--mono); font-size:12px; }
  #MainMenu,footer,header { visibility:hidden; }
  div[data-testid="stSelectbox"] label {
    font-family:var(--mono)!important; font-size:11px!important; color:var(--muted)!important; }
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
    "https://api.upstox.com/v3/option/chain",
    "https://api.upstox.com/v2/option/chain",
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


@st.cache_data(ttl=120)
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


def parse_chain(data):
    ce_map, pe_map = {}, {}
    spot = None
    for row in data:
        s = float(row.get("strike_price", 0))
        if spot is None:
            sp = row.get("underlying_spot_price")
            if sp:
                spot = float(sp)
        c = (row.get("call_options") or {}).get("market_data") or {}
        p = (row.get("put_options")  or {}).get("market_data") or {}
        ce_map[s] = float(c.get("ltp") or 0)
        pe_map[s] = float(p.get("ltp") or 0)
    if spot is None:
        common = set(ce_map) & set(pe_map)
        if common:
            spot = float(min(common, key=lambda s: abs(ce_map[s] - pe_map[s])))
    atm = int(round(spot / STEP) * STEP) if spot else 0
    return spot, atm, ce_map, pe_map


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
    st.markdown(f"""
    <div class='login-box'>
      <p style='font-family:var(--hdr);font-size:20px;font-weight:700;color:white;'>Login with Upstox</p>
      <p style='color:#4a6080;font-size:12px;font-family:var(--mono);margin-bottom:1.5rem;'>One click per trading day</p>
      <a href='{auth_url}'
         style='display:inline-block;background:linear-gradient(135deg,#2979ff,#651fff);
                color:white;padding:11px 28px;border-radius:8px;text-decoration:none;
                font-family:var(--mono);font-size:13px;font-weight:600;'>CONNECT →</a>
    </div>""", unsafe_allow_html=True)
    st.stop()

token = st.session_state["access_token"]

# ─────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>⚙️ Parameters</div>", unsafe_allow_html=True)
col_p1, col_p2, col_p3 = st.columns([2, 2, 2])
with col_p1:
    sell_lots = st.number_input("Short Leg Lots (SELL)", min_value=1, max_value=20, value=1)
with col_p2:
    ltp_ratio = st.slider("Long LTP target (% of Sell LTP)", 30, 80, 50, 5,
                          help="Far strike selected where LTP ≈ this % of the sold LTP")
with col_p3:
    short_steps = st.number_input("OTM Steps for Short (default 6 = 300 pts)", min_value=1, max_value=15, value=6)

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

spot, atm, near_ce, near_pe = parse_chain(near_raw)
_,    _,   far_ce,  far_pe  = parse_chain(far_raw)

# ATM ± SHORT_STEPS strikes
sell_ce_strike = atm + short_steps * STEP   # e.g. ATM + 300
sell_pe_strike = atm - short_steps * STEP   # e.g. ATM - 300
sell_ce_ltp    = near_ce.get(float(sell_ce_strike), 0)
sell_pe_ltp    = near_pe.get(float(sell_pe_strike), 0)

# ─────────────────────────────────────────────
# PRE-COMPUTE LONG CANDIDATES (needed for snapshot)
# ─────────────────────────────────────────────
ce_cands = find_long_candidates(sell_ce_ltp, far_ce, atm, "CE", ltp_ratio)
pe_cands = find_long_candidates(sell_pe_ltp, far_pe, atm, "PE", ltp_ratio)
best_ce  = ce_cands[0] if ce_cands else {"strike": sell_ce_strike, "ltp": 0, "diff_pct": 99}
best_pe  = pe_cands[0] if pe_cands else {"strike": sell_pe_strike, "ltp": 0, "diff_pct": 99}

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

# Row 2 — CE legs
r2c1, r2c2 = st.columns(2)
ce_buy_pct = f"{best_ce['ltp']/sell_ce_ltp*100:.0f}% of sell LTP" if sell_ce_ltp > 0 and best_ce['ltp'] > 0 else ""
with r2c1:
    st.markdown(
        f"<div class='card card-ce'>"
        f"<div class='lbl'>📅 {near_exp} &nbsp;|&nbsp; CE SELL — ATM+{short_steps}</div>"
        f"<div class='val-big val-ce'>₹{sell_ce_ltp:.2f}</div>"
        f"<div class='lbl'>Strike {sell_ce_strike}</div>"
        f"</div>", unsafe_allow_html=True)
with r2c2:
    st.markdown(
        f"<div class='card' style='border-left:3px solid var(--bull);'>"
        f"<div class='lbl'>📅 {far_exp} &nbsp;|&nbsp; CE BUY (far) — best match</div>"
        f"<div class='val-big' style='color:var(--bull);'>₹{best_ce['ltp']:.2f}</div>"
        f"<div class='lbl'>Strike {int(best_ce['strike'])} &nbsp;·&nbsp; {ce_buy_pct}</div>"
        f"</div>", unsafe_allow_html=True)

# Row 3 — PE legs
r3c1, r3c2 = st.columns(2)
pe_buy_pct = f"{best_pe['ltp']/sell_pe_ltp*100:.0f}% of sell LTP" if sell_pe_ltp > 0 and best_pe['ltp'] > 0 else ""
with r3c1:
    st.markdown(
        f"<div class='card card-pe'>"
        f"<div class='lbl'>📅 {near_exp} &nbsp;|&nbsp; PE SELL — ATM-{short_steps}</div>"
        f"<div class='val-big val-pe'>₹{sell_pe_ltp:.2f}</div>"
        f"<div class='lbl'>Strike {sell_pe_strike}</div>"
        f"</div>", unsafe_allow_html=True)
with r3c2:
    st.markdown(
        f"<div class='card' style='border-left:3px solid var(--bull);'>"
        f"<div class='lbl'>📅 {far_exp} &nbsp;|&nbsp; PE BUY (far) — best match</div>"
        f"<div class='val-big' style='color:var(--bull);'>₹{best_pe['ltp']:.2f}</div>"
        f"<div class='lbl'>Strike {int(best_pe['strike'])} &nbsp;·&nbsp; {pe_buy_pct}</div>"
        f"</div>", unsafe_allow_html=True)

if sell_ce_ltp == 0 or sell_pe_ltp == 0:
    st.warning(f"⚠️ ATM±{short_steps} ({sell_ce_strike}/{sell_pe_strike}) has zero LTP — "
               f"try a smaller steps value or check market hours.")

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
    f"• Adjust <b>OTM Steps</b> or <b>Long LTP target %</b> to fine-tune strikes"
    f"</span></div>",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📐 NIFTY Diagonal")
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
    if st.button("🔓 Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()
    st.caption(f"Updated {now.strftime('%H:%M:%S IST')}")
