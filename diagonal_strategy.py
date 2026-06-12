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
import base64
import csv
import io
import urllib.parse
from datetime import datetime, timedelta
import pytz
try:
    from scipy.optimize import minimize as _scipy_minimize
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

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
BUY_LOTS     = 1            # Far monthly long leg — always 1L per side

INSTRUMENT_KEY  = "NSE_INDEX|Nifty 50"
UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL= "https://api.upstox.com/v2/login/authorization/token"
UPSTOX_OC_URLS  = [
    "https://api.upstox.com/v2/option/chain",   # v2 returns OI in market_data
    "https://api.upstox.com/v3/option/chain",   # v3 fallback (OI may differ)
]
UPSTOX_CONTRACT_URL = "https://api.upstox.com/v2/option/contract"

# ── Strategy registry ───────────────────────────────────────────────────────
# Add new strategies here. Each entry: trigger condition is evaluated at runtime.
STRATEGY_REGISTRY = [
    {
        "id":        "hv_ratio",
        "name":      "High VIX Ratio Spread",
        "emoji":     "⚡",
        "color":     "#ff5252",
        "regime":    "High Volatility",
        "trigger":   "VIX > 15",
        "structure": "Sell δ 18–21 (2L, DTE>5 expiry) · BUY ±500 OTM hedge (1L same expiry) · "
                     "BUY same sell strike far monthly (DTE ≥ 3× sell DTE) as backstop",
        "why":       "Elevated IV makes OTM options expensive → collect premium at delta-defined "
                     "distance. Extra OTM short adds income. Far-month long caps unlimited risk.",
        "best_for":  "VIX > 15, event-driven spikes, range-bound post-spike",
    },
    {
        "id":        "diagonal",
        "name":      "Diagonal Calendar Spread",
        "emoji":     "📐",
        "color":     "#4d9fff",
        "regime":    "Normal Volatility",
        "trigger":   "VIX ≤ 15 (default)",
        "structure": "Sell ATM ± VIX-1σ steps near expiry · "
                     "Buy matching strikes far expiry (≥ 5 wks) at ~50% of sold LTP",
        "why":       "Low IV → exploit term structure decay; near-leg theta decays faster. "
                     "Far long provides hedge and benefits if IV expands.",
        "best_for":  "VIX < 15, trending/sideways market, low near-term event risk",
    },
]

# ── GitHub PCR log ──────────────────────────────────────────────────────────
GITHUB_OWNER    = "rajishnse-alt"
GITHUB_REPO     = "diagonal-calanderstrategy"
GITHUB_BRANCH   = "main"
PCR_CSV_PATH    = "pcr_data/pcr_log.csv"
PCR_RETENTION   = 35   # days to keep
PCR_LOG_INTERVAL= 180  # seconds between writes (3 min)
PCR_COLUMNS     = [
    "timestamp","date","expiry_type","expiry","spot","atm",
    "pcr_range","pcr_atm","ce_oi_L","pe_oi_L","atm_ce_oi_L","atm_pe_oi_L",
    "pcr_chg","vix_open","vix_curr","spcl",
]


def _gh_hdr(tok):
    return {"Authorization": f"token {tok}",
            "Accept": "application/vnd.github.v3+json"}


def gh_get_csv(gh_tok):
    """Fetch PCR CSV from GitHub. Returns (csv_text, sha) or (None, None) on error."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/contents/{PCR_CSV_PATH}",
            headers=_gh_hdr(gh_tok),
            params={"ref": GITHUB_BRANCH},
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            text = base64.b64decode(d["content"]).decode("utf-8")
            return text, d["sha"]
        if r.status_code == 404:
            return "", None          # file doesn't exist yet — create it
    except Exception:
        pass
    return None, None                # network / auth error


def gh_put_csv(gh_tok, content, sha, msg):
    """Write CSV to GitHub. sha=None creates the file."""
    try:
        payload = {
            "message": msg,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/contents/{PCR_CSV_PATH}",
            json=payload,
            headers=_gh_hdr(gh_tok),
            timeout=30,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def append_pcr_log(gh_tok, new_rows):
    """
    Append new_rows (list of dicts) to the GitHub PCR CSV.
    Prunes entries older than PCR_RETENTION days.
    Returns True on success.
    """
    existing, sha = gh_get_csv(gh_tok)
    if existing is None:
        return False            # API error; skip silently

    cutoff = datetime.now(IST).date() - timedelta(days=PCR_RETENTION)
    kept   = []
    if existing.strip():
        for row in csv.DictReader(io.StringIO(existing)):
            try:
                if datetime.strptime(row["date"], "%Y-%m-%d").date() >= cutoff:
                    kept.append(row)
            except Exception:
                pass

    # Deduplicate: skip rows whose (timestamp, expiry) already exist
    seen = {(r["timestamp"], r["expiry"]) for r in kept}
    for row in new_rows:
        if (row["timestamp"], row["expiry"]) not in seen:
            kept.append(row)

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=PCR_COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(kept)

    ts_label = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    return gh_put_csv(gh_tok, buf.getvalue(), sha, f"PCR log {ts_label}")


def load_pcr_history(gh_tok):
    """Return list-of-dicts from the GitHub PCR CSV, or [] on error."""
    text, _ = gh_get_csv(gh_tok)
    if not text:
        return []
    try:
        return list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return []


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
    return (
        f"{UPSTOX_AUTH_URL}?response_type=code"
        f"&client_id={urllib.parse.quote(k, safe='')}"
        f"&redirect_uri={urllib.parse.quote(r, safe='')}"
    )

def exchange_code(k, s, r, code):
    try:
        d = requests.post(
            UPSTOX_TOKEN_URL,
            data={"code":code,"client_id":k,"client_secret":s,"redirect_uri":r,"grant_type":"authorization_code"},
            headers={"Accept":"application/json"}, timeout=15,
        ).json()
        if "access_token" in d:
            return d["access_token"], None
        # Return a safe error message — never echo back credentials or raw response
        err_code = d.get("error", d.get("errorCode", "unknown"))
        err_msg  = d.get("error_description", d.get("message", "Token exchange failed"))
        return None, f"{err_code}: {err_msg}"
    except Exception:
        return None, "Token exchange request failed. Please try logging in again."


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


_NSE_FO_HIST = "https://www.nseindia.com/api/historical/fo/daily"
_NSE_HOME    = "https://www.nseindia.com"
_NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _prev_biz_day():
    today = datetime.now(IST).date()
    prev  = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def fetch_nse_fo_hist(expiry_str, strike, option_type):
    """
    Fetch previous trading day H, L, OI from NSE FO daily historical.
    Returns dict {high, low, oi, date} or None.
    """
    try:
        exp_dt     = datetime.strptime(expiry_str, "%Y-%m-%d")
        expiry_nse = exp_dt.strftime("%d-%b-%Y")          # "16-Jun-2026"
        prev       = _prev_biz_day()
        date_str   = prev.strftime("%d-%m-%Y")             # "10-06-2026"

        sess = requests.Session()
        sess.headers.update(_NSE_HEADERS)
        sess.get(_NSE_HOME, timeout=8)                     # prime cookies
        sess.get("https://www.nseindia.com/option-chain", timeout=8)

        r = sess.get(
            _NSE_FO_HIST,
            params={
                "from":           date_str,
                "to":             date_str,
                "instrumentType": "OPTIDX",
                "symbol":         "NIFTY",
                "expiryDate":     expiry_nse,
                "optionType":     option_type,
                "strikePrice":    str(int(strike)),
            },
            timeout=15,
        )
        rows = r.json().get("data") or []
        if not rows:
            return None
        row = rows[-1]
        h = float(row.get("FH_TRADE_HIGH_PRICE") or 0)
        l = float(row.get("FH_TRADE_LOW_PRICE")  or 0)
        o = float(row.get("FH_OPEN_INT")         or 0)
        if h <= 0 or l <= 0 or o <= 0:
            return None
        return {"date": str(prev), "high": h, "low": l, "oi": o}
    except Exception:
        return None


def fetch_upstox_fo_hist(tok, chain_data, atm_strike, option_type):
    """
    Fallback: fetch prev-day H, L, OI from Upstox historical candle.
    option_type: "CE" or "PE"
    """
    try:
        side_key = "call_options" if option_type == "CE" else "put_options"
        inst_key = None
        for row in chain_data:
            if int(float(row.get("strike_price", 0))) == int(atm_strike):
                inst_key = (row.get(side_key) or {}).get("instrument_key")
                break
        if not inst_key:
            return None
        today     = datetime.now(IST).date()
        from_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        to_date   = today.strftime("%Y-%m-%d")
        enc       = urllib.parse.quote(inst_key, safe="")
        r = requests.get(
            f"https://api.upstox.com/v2/historical-candle/{enc}/day/{to_date}/{from_date}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {tok}"},
            timeout=10,
        )
        candles = (r.json().get("data") or {}).get("candles") or []
        today_s = today.isoformat()
        prev = sorted([c for c in candles if str(c[0])[:10] < today_s],
                      key=lambda c: c[0], reverse=True)
        if not prev:
            return None
        c = prev[0]
        h, l, oi = float(c[2]), float(c[3]), float(c[6]) if len(c) > 6 else 0.0
        if h <= 0 or l <= 0 or oi <= 0:
            return None
        return {"date": str(c[0])[:10], "high": h, "low": l, "oi": oi}
    except Exception:
        return None


def calc_spp(expiry_str, atm_strike, tok=None, chain_data=None):
    """
    SPP (UIP concept):
      spp = (ce_median × ce_OI + pe_median × pe_OI) / (ce_OI + pe_OI)
    Tries NSE FO historical first; falls back to Upstox if NSE is blocked.
    Returns: (spp, ce_h, ce_l, pe_h, pe_l, ce_oi_L, pe_oi_L, date_used) or all-None.
    """
    # Primary: NSE
    ce_can = fetch_nse_fo_hist(expiry_str, atm_strike, "CE")
    pe_can = fetch_nse_fo_hist(expiry_str, atm_strike, "PE")
    src    = "NSE"

    # Fallback: Upstox
    if (not ce_can or not pe_can) and tok and chain_data:
        ce_can = fetch_upstox_fo_hist(tok, chain_data, atm_strike, "CE")
        pe_can = fetch_upstox_fo_hist(tok, chain_data, atm_strike, "PE")
        src    = "Upstox"

    if not ce_can or not pe_can:
        return None, None, None, None, None, None, None, None

    ce_h, ce_l, ce_oi = ce_can["high"], ce_can["low"], ce_can["oi"]
    pe_h, pe_l, pe_oi = pe_can["high"], pe_can["low"], pe_can["oi"]

    ce_oi_L = ce_oi / 1e5
    pe_oi_L = pe_oi / 1e5
    ce_med  = (ce_h + ce_l) / 2
    pe_med  = (pe_h + pe_l) / 2
    tot_oi  = ce_oi + pe_oi
    spp     = (ce_med * ce_oi + pe_med * pe_oi) / tot_oi if tot_oi > 0 else (ce_med + pe_med) / 2

    date_lbl = f"{ce_can['date']} ({src})"
    return round(spp, 2), ce_h, ce_l, pe_h, pe_l, round(ce_oi_L, 2), round(pe_oi_L, 2), date_lbl


def parse_chain(data):
    ce_map, pe_map, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg = {}, {}, {}, {}, {}, {}
    ce_gamma, pe_gamma = {}, {}          # API greeks — gamma per strike
    spot = None
    for row in data:
        s = float(row.get("strike_price", 0))
        if spot is None:
            sp = row.get("underlying_spot_price")
            if sp:
                spot = float(sp)
        c  = (row.get("call_options") or {}).get("market_data")    or {}
        p  = (row.get("put_options")  or {}).get("market_data")    or {}
        cg = (row.get("call_options") or {}).get("option_greeks")  or {}
        pg = (row.get("put_options")  or {}).get("option_greeks")  or {}
        ce_map[s]     = float(c.get("ltp") or 0)
        pe_map[s]     = float(p.get("ltp") or 0)
        ce_oi[s]      = _get_oi(c)
        pe_oi[s]      = _get_oi(p)
        ce_oi_chg[s]  = _get_oi_chg(c)
        pe_oi_chg[s]  = _get_oi_chg(p)
        # gamma is always positive; abs() guards against sign conventions
        ce_gamma[s]   = abs(float(cg.get("gamma") or 0))
        pe_gamma[s]   = abs(float(pg.get("gamma") or 0))
    if spot is None:
        common = set(ce_map) & set(pe_map)
        if common:
            spot = float(min(common, key=lambda s: abs(ce_map[s] - pe_map[s])))
    atm = int(round(spot / STEP) * STEP) if spot else 0
    return spot, atm, ce_map, pe_map, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, ce_gamma, pe_gamma


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


def fetch_vix_and_nifty_open(tok):
    """
    Single call: fetch India VIX (open + LTP) AND NIFTY 50 day-open price.
    Returns (open_vix, curr_vix, nifty_day_open, err).
    nifty_day_open is the day's OHLC open — used to anchor SPP ATM for the day.
    """
    try:
        r = requests.get(
            "https://api.upstox.com/v2/market-quote/quotes",
            params={"instrument_key": "NSE_INDEX|India VIX,NSE_INDEX|Nifty 50"},
            headers=hdr(tok), timeout=10,
        )
        if r.status_code == 401:
            return None, None, None, "token_expired"
        d = r.json()
        if d.get("status") == "success":
            data = d.get("data", {})
            vd = (data.get("NSE_INDEX:India VIX")
                  or data.get("NSE_INDEX|India VIX"))
            nd = (data.get("NSE_INDEX:Nifty 50")
                  or data.get("NSE_INDEX|Nifty 50"))
            open_vix      = float((vd or {}).get("ohlc", {}).get("open") or 0) if vd else None
            curr_vix      = float((vd or {}).get("last_price") or 0)           if vd else None
            nifty_day_open= float((nd or {}).get("ohlc", {}).get("open") or 0) if nd else None
            return open_vix, curr_vix, nifty_day_open, None
        return None, None, None, str(d)
    except Exception as e:
        return None, None, None, str(e)

# backward-compat alias used elsewhere
def fetch_vix(tok):
    open_vix, curr_vix, _, err = fetch_vix_and_nifty_open(tok)
    return open_vix, curr_vix, err


def weeks_out(expiry_str):
    try:
        return ((datetime.strptime(expiry_str, "%Y-%m-%d").date()
                 - datetime.now(IST).date()).days / 7.0)
    except Exception:
        return 0.0

