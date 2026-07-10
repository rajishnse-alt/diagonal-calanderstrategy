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
import json
import os
try:
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
    _AUTOREFRESH_OK = True
except ImportError:
    _AUTOREFRESH_OK = False
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

# ── Instrument registry ──────────────────────────────────────────────────────
INSTRUMENT_CONFIGS = {
    "NIFTY": {
        "key":     "NSE_INDEX|Nifty 50",
        "step":    50,
        "lot":     75,
        "symbol":  "NIFTY",
        "pcr_csv": "pcr_data/pcr_log_nifty.csv",
    },
    "BANKNIFTY": {
        "key":     "NSE_INDEX|Nifty Bank",
        "step":    100,
        "lot":     15,
        "symbol":  "BANKNIFTY",
        "pcr_csv": "pcr_data/pcr_log_banknifty.csv",
    },
    "SENSEX": {
        "key":     "BSE_INDEX|SENSEX",
        "step":    100,
        "lot":     10,
        "symbol":  "SENSEX",
        "pcr_csv": "pcr_data/pcr_log_sensex.csv",
    },
}

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
SPP_CACHE_FILE  = "pcr_data/spp_cache.json"   # persisted SPP history (survives restarts)
PCR_RETENTION   = 35   # days to keep
PCR_LOG_INTERVAL= 180  # seconds — overridden by user slider at runtime
PCR_COLUMNS     = [
    "timestamp","date","expiry_type","expiry","spot","atm",
    "pcr_range","pcr_atm","ce_oi_L","pe_oi_L","atm_ce_oi_L","atm_pe_oi_L",
    "pcr_chg","vix_open","vix_curr","spcl",
]


def _gh_hdr(tok):
    return {"Authorization": f"token {tok}",
            "Accept": "application/vnd.github.v3+json"}


# ── SPP GitHub + disk cache helpers ─────────────────────────────────────────
def _spp_gh_get(gh_tok):
    """Fetch spp_cache.json from GitHub. Returns (dict, sha) or ({}, None)."""
    if not gh_tok:
        return {}, None
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/contents/{SPP_CACHE_FILE}",
            headers=_gh_hdr(gh_tok),
            params={"ref": GITHUB_BRANCH},
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            data = json.loads(base64.b64decode(d["content"]).decode("utf-8"))
            cutoff = (datetime.now(IST) - timedelta(days=35)).date().isoformat()
            pruned = {k: v for k, v in data.items() if k.split("|")[0] >= cutoff}
            return pruned, d["sha"]
        if r.status_code == 404:
            return {}, None   # file doesn't exist yet
    except Exception:
        pass
    return {}, None


def _spp_gh_put(gh_tok, store: dict, sha):
    """Write spp_cache.json to GitHub. sha=None creates the file."""
    if not gh_tok:
        return False
    try:
        content = json.dumps(store, indent=2)
        payload = {
            "message": f"SPP cache update {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}",
            "content": base64.b64encode(content.encode()).decode(),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/contents/{SPP_CACHE_FILE}",
            json=payload,
            headers=_gh_hdr(gh_tok),
            timeout=30,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def _spp_load_disk():
    """Fallback: load from local disk when GitHub is unavailable."""
    try:
        if os.path.exists(SPP_CACHE_FILE):
            with open(SPP_CACHE_FILE, "r") as f:
                data = json.load(f)
            cutoff = (datetime.now(IST) - timedelta(days=35)).date().isoformat()
            return {k: v for k, v in data.items() if k.split("|")[0] >= cutoff}
    except Exception:
        pass
    return {}


def _spp_save_disk(store: dict):
    """Fallback: save to local disk (ephemeral on cloud, but useful locally)."""
    try:
        os.makedirs(os.path.dirname(SPP_CACHE_FILE), exist_ok=True)
        with open(SPP_CACHE_FILE, "w") as f:
            json.dump(store, f, indent=2)
    except Exception:
        pass


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
    return {
        "Authorization":  f"Bearer {tok}",
        "Accept":         "application/json",
        "Content-Type":   "application/json",   # required by Upstox v2 API
    }

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
    """
    Upstox option chain does NOT provide an intraday OI change field.
    Compute it as: current OI - prev_oi (previous day close OI).
    Falls back to explicit change fields if ever added by Upstox.
    """
    # Prefer explicit change fields (future-proof)
    for key in ("oi_day_change", "change_oi", "day_change_oi", "oi_change", "oiChange", "changeOi"):
        v = md.get(key)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    # Compute from oi - prev_oi (most reliable for Upstox v2)
    try:
        oi      = float(md.get("oi") or md.get("open_interest") or 0)
        prev_oi = float(md.get("prev_oi") or md.get("previous_oi") or 0)
        if oi > 0 or prev_oi > 0:
            return oi - prev_oi
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


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ideal_premium(expiry_str, strike_a, strike_b):
    """
    Ideal Premium (IP) — crossover-strike method:
      strike_a = last strike where CE LTP > PE LTP  (e.g. 23950)
      strike_b = first strike where PE LTP > CE LTP (e.g. 24000)
    Uses a SINGLE NSE session for all 4 calls to avoid rate-limiting.
    Returns (ip, lows_dict) or (None, {}).
    """
    try:
        exp_dt     = datetime.strptime(expiry_str, "%Y-%m-%d")
        expiry_nse = exp_dt.strftime("%d-%b-%Y")
        prev       = _prev_biz_day()
        date_str   = prev.strftime("%d-%m-%Y")

        sess = requests.Session()
        sess.headers.update(_NSE_HEADERS)
        sess.get("https://www.nseindia.com", timeout=8)
        sess.get("https://www.nseindia.com/option-chain", timeout=6)

        lows = {}
        for strike, otype in [(strike_a, "CE"), (strike_a, "PE"),
                               (strike_b, "CE"), (strike_b, "PE")]:
            try:
                r = sess.get(
                    _NSE_FO_HIST,
                    params={
                        "from":           date_str,
                        "to":             date_str,
                        "instrumentType": "OPTIDX",
                        "symbol":         "NIFTY",
                        "expiryDate":     expiry_nse,
                        "optionType":     otype,
                        "strikePrice":    str(int(strike)),
                    },
                    timeout=15,
                )
                rows = r.json().get("data") or []
                if rows:
                    row = rows[-1]
                    l   = float(row.get("FH_TRADE_LOW_PRICE") or 0)
                    if l > 0:
                        lows[f"{strike}_{otype}"] = l
            except Exception:
                continue

        if len(lows) == 4:
            return sum(lows.values()) / 4, lows
        # Partial: return whatever we got with None ip
        return None, lows
    except Exception:
        return None, {}


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


def fetch_atm_vwap(tok, chain_data, atm_strike):
    """
    Compute VWAP = Σ((H+L+C)/3 × Vol) / Σ(Vol) for ATM CE and PE.
    1. Tries Upstox v3 intraday 1-min API (current session).
    2. If empty (market closed / weekend), falls back to v2 historical
       1-minute candles for the previous business day.
    Returns (ce_vwap, pe_vwap, ce_vol, pe_vol) — any may be None.
    """
    ce_inst = pe_inst = None
    for row in chain_data:
        if int(float(row.get("strike_price", 0))) == int(atm_strike):
            ce_inst = (row.get("call_options") or {}).get("instrument_key")
            pe_inst = (row.get("put_options")  or {}).get("instrument_key")
            break

    _hdrs = {"Accept": "application/json", "Authorization": f"Bearer {tok}"}

    def _compute_vwap(candles):
        cum_tp_vol = cum_vol = 0.0
        for c in candles:
            try:
                h, l, cl, vol = float(c[2]), float(c[3]), float(c[4]), float(c[5])
                if vol > 0:
                    cum_tp_vol += ((h + l + cl) / 3) * vol
                    cum_vol    += vol
            except Exception:
                pass
        return (cum_tp_vol / cum_vol, cum_vol) if cum_vol > 0 else (None, None)

    def _vwap_for(inst_key):
        if not inst_key:
            return None, None
        enc = urllib.parse.quote(inst_key, safe="")
        # 1. Intraday v3 (today's session)
        try:
            r = requests.get(
                f"https://api.upstox.com/v3/historical-candle/intraday/{enc}/minutes/1",
                headers=_hdrs, timeout=10,
            )
            candles = (r.json().get("data") or {}).get("candles") or []
            if candles:
                return _compute_vwap(candles)
        except Exception:
            pass
        # 2. Historical v2 fallback — previous business day 1-min candles
        try:
            prev_day = _prev_biz_day().strftime("%Y-%m-%d")
            r = requests.get(
                f"https://api.upstox.com/v2/historical-candle/{enc}/1minute/{prev_day}/{prev_day}",
                headers=_hdrs, timeout=10,
            )
            candles = (r.json().get("data") or {}).get("candles") or []
            if candles:
                return _compute_vwap(candles)
        except Exception:
            pass
        return None, None

    ce_vwap, ce_vol = _vwap_for(ce_inst)
    pe_vwap, pe_vol = _vwap_for(pe_inst)
    return ce_vwap, pe_vwap, ce_vol, pe_vol


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


def calc_pcr_spcl(ce_map, pe_map, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, atm, vix_day_open=None, n_strikes=4):
    """
    PCR      = sum(PE OI) / sum(CE OI)
               CE: ATM + 4 OTM above  (ATM, ATM+1, …, ATM+4 steps)
               PE: ATM + 4 OTM below  (ATM, ATM-1, …, ATM-4 steps)
    PCR_CHG  = sum(PE OI change) / sum(CE OI change)  — shows intraday build-up direction.
    SPCL VAL = (base + (base - sqrt(vix_open))) / 2
               where base = sqrt(ce_atm + pe_atm) * π / 2
    Sentiment uses contrarian scale: high PCR → more puts → bullish contrarian signal.
    """
    ce_strikes  = [atm + i * STEP for i in range(0, n_strikes + 1)]   # ATM + 4 OTM calls
    pe_strikes  = [atm - i * STEP for i in range(0, n_strikes + 1)]   # ATM + 4 OTM puts
    tot_ce      = sum(ce_oi.get(float(s), 0)             for s in ce_strikes)
    tot_pe      = sum(pe_oi.get(float(s), 0)             for s in pe_strikes)
    tot_ce_chg  = sum(max(ce_oi_chg.get(float(s), 0), 0) for s in ce_strikes)
    tot_pe_chg  = sum(max(pe_oi_chg.get(float(s), 0), 0) for s in pe_strikes)

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


def fetch_vix_and_nifty_open(tok, spot_key="NSE_INDEX|Nifty 50"):
    """
    Single call: fetch India VIX (open + LTP) AND spot instrument day-open price.
    Returns (open_vix, curr_vix, nifty_day_open, err).
    nifty_day_open is the day's OHLC open — used to anchor SPP ATM for the day.
    """
    try:
        r = requests.get(
            "https://api.upstox.com/v2/market-quote/quotes",
            params={"instrument_key": f"NSE_INDEX|India VIX,{spot_key}"},
            headers=hdr(tok), timeout=10,
        )
        if r.status_code == 401:
            return None, None, None, "token_expired"
        d = r.json()
        if d.get("status") == "success":
            data = d.get("data", {})
            vd = (data.get("NSE_INDEX:India VIX")
                  or data.get("NSE_INDEX|India VIX"))
            _spot_key_c = spot_key.replace("|", ":")
            nd = (data.get(_spot_key_c) or data.get(spot_key))
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


@st.cache_data(ttl=3600, show_spinner=False)
def _get_nifty_fut_tokens(tok):
    """
    Resolve NIFTY futures numeric instrument keys (required by REST quotes API).
    PRIMARY  : Upstox v2/market/smartlist/futures (auth, Content-Type headers in hdr())
    FALLBACK : Upstox instruments master JSON (public CDN, no auth)
    Returns  : {expiry_str: (instrument_key, trading_symbol)}
    """
    import gzip as _gzip

    today = datetime.now(IST).date()

    def _parse_contracts(contracts):
        tokens = {}
        for item in contracts:
            if not isinstance(item, dict):
                continue
            sym  = (item.get("trading_symbol") or "").upper()
            ikey = item.get("instrument_key") or ""
            exp  = str(item.get("expiry") or "")[:10]
            if not ikey or not exp:
                continue
            if "NIFTY" not in sym:
                continue
            if any(x in sym for x in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "CPSE")):
                continue
            tokens[exp] = (ikey, sym)
        return tokens

    # ── PRIMARY: smartlist REST API ───────────────────────────────────────────
    try:
        r = requests.get(
            "https://api.upstox.com/v2/market/smartlist/futures",
            params={"asset_type": "INDEX", "category": "TOP_TRADED",
                    "page_number": 1, "page_size": 30},
            headers=hdr(tok), timeout=12,
        )
        if r.status_code == 200:
            raw = r.text.strip()
            if raw.startswith(("{", "[")):
                resp = r.json()
                contracts = resp if isinstance(resp, list) else resp.get("data", [])
                if isinstance(contracts, list):
                    tokens = _parse_contracts(contracts)
                    if tokens:
                        return tokens, None
    except Exception:
        pass

    # ── FALLBACK: instruments master JSON (public CDN, no auth) ───────────────
    INST_URLS = [
        "https://assets.upstox.com/market-quote/instruments/exchange/NSE_FO.json.gz",
        "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz",
    ]
    for url in INST_URLS:
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                continue
            raw = r.content
            try:
                raw = _gzip.decompress(raw)
            except Exception:
                pass   # server may have decompressed already
            instruments = json.loads(raw)
            nifty_rows = []
            for item in instruments:
                if not isinstance(item, dict):
                    continue
                if item.get("segment") != "NSE_FO" or item.get("instrument_type") != "FUT":
                    continue
                if item.get("underlying_symbol") != "NIFTY 50":   # Upstox exact name
                    continue
                exp_str = str(item.get("expiry") or "")[:10]
                ikey    = item.get("instrument_key", "")
                sym     = item.get("trading_symbol", "")
                if not ikey or not exp_str:
                    continue
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                except Exception:
                    continue
                if exp_date < today:
                    continue
                nifty_rows.append((exp_date, exp_str, ikey, sym))
            if nifty_rows:
                nifty_rows.sort(key=lambda x: x[0])
                tokens = {exp_str: (ikey, sym) for _, exp_str, ikey, sym in nifty_rows[:2]}
                return tokens, None
        except Exception:
            continue

    return {}, "smartlist + instruments master both unavailable"


def _dynamic_nifty_fut_keys():
    """
    Build NIFTY futures tradingsymbol keys from the calendar (no API needed).
    Format: NSE_FO|NIFTY{YY}{MONTHNAME}FUT  e.g. NSE_FO|NIFTY26JULYFUT
    Returns list of (label, instrument_key, approx_month_str) for cur + next month.
    """
    now = datetime.now(IST)
    result = []
    for days_offset, label in [(0, "CUR MONTH"), (32, "NEXT MONTH")]:
        d   = now + timedelta(days=days_offset)
        sym = f"NIFTY{d.strftime('%y')}{d.strftime('%B').upper()}FUT"
        result.append((label, f"NSE_FO|{sym}", d.strftime("%Y-%m")))
    return result


def _fetch_nse_futures_live():
    """
    Fetch live NIFTY Index Futures data from NSE India.
    URL: https://www.nseindia.com/api/quote-derivative?symbol=NIFTY
    No auth required — uses same session approach as fetch_nse_fo_hist.
    Returns list of dicts sorted by expiry (closest first), or [].
    """
    try:
        sess = requests.Session()
        sess.headers.update(_NSE_HEADERS)
        sess.get("https://www.nseindia.com", timeout=8)
        sess.get("https://www.nseindia.com/get-quotes/derivatives?symbol=NIFTY", timeout=8)
        r = sess.get(
            "https://www.nseindia.com/api/quote-derivative?symbol=NIFTY",
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data   = r.json()
        stocks = data.get("stocks") or []
        today  = datetime.now(IST).date()
        rows   = []
        for item in stocks:
            meta  = item.get("metadata") or {}
            itype = (meta.get("instrumentType") or "").lower()
            if "future" not in itype:
                continue
            # Parse expiry — NSE uses "24-Jul-2026" format
            exp_raw = meta.get("expiryDate") or ""
            try:
                exp_dt  = datetime.strptime(exp_raw, "%d-%b-%Y")
                exp_str = exp_dt.strftime("%Y-%m-%d")
            except Exception:
                try:
                    exp_dt  = datetime.strptime(exp_raw, "%d-%m-%Y")
                    exp_str = exp_dt.strftime("%Y-%m-%d")
                except Exception:
                    continue
            if exp_dt.date() < today:
                continue
            ltp        = float(meta.get("lastPrice")       or meta.get("last_price")    or 0)
            prev_close = float(meta.get("prevClosePrice")  or meta.get("closePrice")    or 0)
            oi         = float(meta.get("openInterest")    or 0)
            oi_chg     = float(meta.get("changeinOpenInterest") or meta.get("changeInOI") or 0)
            prev_oi    = max(oi - oi_chg, 0) if oi_chg else oi
            if ltp <= 0 or prev_close <= 0:
                continue
            rows.append({
                "expiry":     exp_str,
                "ltp":        ltp,
                "prev_close": prev_close,
                "oi":         oi,
                "prev_oi":    prev_oi,
                "symbol":     f"NIFTY-{exp_raw}",
            })
        rows.sort(key=lambda x: x["expiry"])
        return rows
    except Exception:
        return []


@st.cache_data(ttl=180, show_spinner=False)
def fetch_futures_buildup(tok, expiry_dates=None, underlying_key=None):
    """
    Fetch NIFTY futures build-up.
    Strategy:
      A) Try numeric keys (smartlist / CDN) → historical-candle + quotes  [LIVE]
      B) Fallback: dynamic tradingsymbol keys → historical-candle only    [HIST]
    Each row tagged with source: 'live' | 'hist'
    Returns (results, err_or_None)
    """
    def _classify(price_up, oi_up):
        if price_up and oi_up:      return "Long Build-up"
        if price_up and not oi_up:  return "Short Covering"
        if not price_up and oi_up:  return "Short Build-up"
        return "Long Unwinding"

    def _fetch_candles(ikey, today_str, from_str, tok):
        """Fetch day candles for an instrument key (tries both | and %7C)."""
        for enc in (ikey.replace("|", "%7C"), ikey):
            try:
                r = requests.get(
                    f"https://api.upstox.com/v2/historical-candle/{enc}/day/{today_str}/{from_str}",
                    headers=hdr(tok), timeout=10,
                )
                if r.status_code == 200:
                    return r.json().get("data", {}).get("candles", [])
            except Exception:
                pass
        return []

    today_dt  = datetime.now(IST).date()
    today_str = str(today_dt)
    from_str  = str(today_dt - timedelta(days=7))

    # ══ PATH A: numeric keys (smartlist / CDN) ════════════════════════════════
    all_tokens, _err = _get_nifty_fut_tokens(tok)
    if all_tokens:
        sorted_exps = sorted(exp for exp in all_tokens if exp >= today_str)[:2]
        if sorted_exps:
            labels_map = {e: ("CUR MONTH" if i == 0 else "NEXT MONTH")
                          for i, e in enumerate(sorted_exps)}
            fut_keys   = {e: all_tokens[e][0] for e in sorted_exps}
            sym_map    = {e: all_tokens[e][1] for e in sorted_exps}

            # Historical candles
            hist = {}
            for exp, ikey in fut_keys.items():
                candles = _fetch_candles(ikey, today_str, from_str, tok)
                if len(candles) >= 2:
                    hist[exp] = {"prev_close": float(candles[1][4]),
                                 "prev_oi":    float(candles[1][6]),
                                 "cur_oi":     float(candles[0][6])}
                elif len(candles) == 1:
                    hist[exp] = {"prev_close": float(candles[0][1]),
                                 "prev_oi":    float(candles[0][6]),
                                 "cur_oi":     float(candles[0][6])}

            # Live quotes
            quote_data = {}
            try:
                r = requests.get(
                    "https://api.upstox.com/v2/market-quote/quotes",
                    params={"instrument_key": ",".join(fut_keys.values())},
                    headers=hdr(tok), timeout=12,
                )
                if r.status_code == 200:
                    raw = r.json().get("data", {})
                    for exp, ikey in fut_keys.items():
                        qd = raw.get(ikey.replace("|", ":")) or raw.get(ikey) or {}
                        if qd:
                            quote_data[exp] = qd
            except Exception:
                pass

            results = []
            for exp in sorted_exps:
                qd = quote_data.get(exp, {})
                hd = hist.get(exp, {})
                ltp = float(qd.get("last_price") or 0)
                # Fallback LTP from today's candle close
                if ltp <= 0 and hd:
                    pass  # will try hist-only path below
                if ltp <= 0:
                    continue
                ohlc       = qd.get("ohlc", {})
                prev_close = hd.get("prev_close") or float(ohlc.get("close") or ohlc.get("prev_close") or 0)
                cur_oi     = float(qd.get("oi") or qd.get("open_interest") or hd.get("cur_oi") or 0)
                prev_oi    = hd.get("prev_oi") or float(qd.get("prev_oi") or cur_oi)
                if not prev_close:
                    continue
                px_chg = (ltp - prev_close) / prev_close * 100
                oi_chg = (cur_oi - prev_oi) / prev_oi * 100 if prev_oi else 0
                results.append({
                    "expiry": exp, "label": labels_map[exp], "symbol": sym_map[exp],
                    "ltp": ltp, "prev_close": prev_close,
                    "oi": cur_oi, "prev_oi": prev_oi,
                    "px_chg_pct": px_chg, "oi_chg_pct": oi_chg,
                    "buildup": _classify(ltp > prev_close, cur_oi > prev_oi),
                    "source": "live",
                })
            if results:
                return results, None

    # ══ PATH B: NSE India live derivatives API ════════════════════════════════
    nse_rows = _fetch_nse_futures_live()
    if nse_rows:
        labels  = ["CUR MONTH", "NEXT MONTH"]
        results = []
        for i, row in enumerate(nse_rows[:2]):
            px_chg = (row["ltp"] - row["prev_close"]) / row["prev_close"] * 100
            oi_chg = ((row["oi"] - row["prev_oi"]) / row["prev_oi"] * 100
                      if row["prev_oi"] else 0)
            results.append({
                "expiry":     row["expiry"],
                "label":      labels[i] if i < len(labels) else f"EXP {i+1}",
                "symbol":     row["symbol"],
                "ltp":        row["ltp"],
                "prev_close": row["prev_close"],
                "oi":         row["oi"],
                "prev_oi":    row["prev_oi"],
                "px_chg_pct": px_chg,
                "oi_chg_pct": oi_chg,
                "buildup":    _classify(row["ltp"] > row["prev_close"],
                                        row["oi"]  > row["prev_oi"]),
                "source":     "live",
            })
        if results:
            return results, None

    # ══ PATH C: dynamic tradingsymbol keys + historical candles only ══════════
    dyn_keys = _dynamic_nifty_fut_keys()   # [(label, ikey, month_str), ...]
    results  = []
    for label, ikey, month_str in dyn_keys:
        candles = _fetch_candles(ikey, today_str, from_str, tok)
        if not candles:
            continue
        # candles newest-first: [ts, open, high, low, close, volume, oi]
        cur_c   = candles[0]
        prev_c  = candles[1] if len(candles) >= 2 else candles[0]
        ltp        = float(cur_c[4])     # today's close = current price
        prev_close = float(prev_c[4])    # yesterday's close
        cur_oi     = float(cur_c[6])
        prev_oi    = float(prev_c[6])
        if ltp <= 0 or prev_close <= 0:
            continue
        px_chg = (ltp - prev_close) / prev_close * 100
        oi_chg = (cur_oi - prev_oi) / prev_oi * 100 if prev_oi else 0
        sym    = ikey.split("|")[-1]
        results.append({
            "expiry": month_str, "label": label, "symbol": sym,
            "ltp": ltp, "prev_close": prev_close,
            "oi": cur_oi, "prev_oi": prev_oi,
            "px_chg_pct": px_chg, "oi_chg_pct": oi_chg,
            "buildup": _classify(ltp > prev_close, cur_oi > prev_oi),
            "source": "hist",
        })
    if results:
        return results, None

    return None, "No futures data — all 3 paths failed (Upstox smartlist/CDN/NSE India)"


# ─────────────────────────────────────────────
# STRATEGY LOGIC
# ─────────────────────────────────────────────
def find_long_candidates(sell_ltp, far_map, atm, opt_type, ltp_ratio_pct, n=8,
                         oi_map=None, min_oi=100):
    """
    Rank far-expiry strikes by proximity of LTP to (sell_ltp × ratio%).
    CE: only OTM (strike >= atm - STEP).
    PE: only OTM (strike <= atm + STEP).
    Skips strikes with OI < min_oi (illiquid).
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
        # Liquidity gate
        if oi_map is not None and oi_map.get(float(strike), 0) < min_oi:
            continue
        diff_abs = abs(ltp - target)
        diff_pct = diff_abs / target * 100 if target > 0 else 999
        cands.append({"strike": int(strike), "ltp": ltp,
                      "target": target, "diff_abs": diff_abs, "diff_pct": diff_pct})
    cands.sort(key=lambda x: x["diff_abs"])
    return cands[:n]


def auto_adjust_sell_strike(base_steps, atm, near_map, far_map, opt_type, ltp_ratio_pct, n=8,
                            oi_map=None):
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
        cands = find_long_candidates(sell_ltp, far_map, atm, opt_type, ltp_ratio_pct, n, oi_map=oi_map)
        # Sell LTP must be at least (100/ltp_ratio_pct)× the long LTP
        # e.g. ratio=50% → sell must be ≥ 2× long
        if cands and cands[0]["ltp"] <= sell_ltp * ltp_ratio_pct / 100:
            return steps, int(sell_strike), sell_ltp, cands, (steps != base_steps)
    # Fallback — return base even if ratio still not met
    sell_strike = (atm + base_steps * STEP) if opt_type == "CE" else (atm - base_steps * STEP)
    sell_ltp    = near_map.get(float(sell_strike), 0)
    cands       = find_long_candidates(sell_ltp, far_map, atm, opt_type, ltp_ratio_pct, n, oi_map=oi_map)
    return base_steps, int(sell_strike), sell_ltp, cands, False


def find_strike_by_premium(near_map, atm, step, opt_type, tgt_low, tgt_high, max_steps=25):
    """
    Scan OTM strikes and return the one whose LTP falls within [tgt_low, tgt_high].
    CE scans upward from ATM, PE scans downward.
    If no strike is in range, returns the one closest to the midpoint.
    Returns (strike, ltp, in_range).
    """
    direction = 1 if opt_type == "CE" else -1
    tgt_mid   = (tgt_low + (tgt_high if tgt_high else tgt_low * 1.5)) / 2
    best_strike = best_ltp = None
    best_dist   = float("inf")
    in_range    = False
    for i in range(1, max_steps + 1):
        s   = atm + direction * i * step
        ltp = near_map.get(float(s), 0)
        if ltp <= 0:
            continue
        within = tgt_low <= ltp <= (tgt_high if tgt_high else float("inf"))
        dist   = abs(ltp - tgt_mid)
        if within and (not in_range or dist < best_dist):
            best_strike, best_ltp, best_dist, in_range = s, ltp, dist, True
        elif not in_range and dist < best_dist:
            best_strike, best_ltp, best_dist = s, ltp, dist
    return (int(best_strike), best_ltp, in_range) if best_strike else (None, None, False)


def bs_price(S, K, T, sigma, opt_type="CE", r=0.065):
    """Black-Scholes option price."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(S - K, 0) if opt_type == "CE" else max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2)))
    nd2 = 0.5 * (1.0 + math.erf(d2 / math.sqrt(2)))
    if opt_type == "CE":
        return S * nd1 - K * math.exp(-r * T) * nd2
    else:
        return K * math.exp(-r * T) * (1 - nd2) - S * (1 - nd1)


def bs_delta(S, K, T, sigma, opt_type="CE", r=0.065):
    """
    Black-Scholes delta.
    Returns absolute delta (0–1 range) for both CE and PE.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 1.0 if (opt_type == "CE" and S > K) else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2)))
    return nd1 if opt_type == "CE" else abs(nd1 - 1.0)


def bs_gamma(S, K, T, sigma, r=0.065):
    """
    Black-Scholes gamma (same for CE and PE).
    Gamma = phi(d1) / (S × sigma × sqrt(T))
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1   = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    phi  = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return phi / (S * sigma * math.sqrt(T))


def net_gamma_lots(legs, spot, sigma, r=0.065):
    """
    Net signed gamma of the position in units of gamma-per-lot.
    Uses api_gamma from leg dict if > 0 (Upstox greeks), else falls back to BS.
    Short legs contribute negative gamma; long legs positive.
    """
    total = 0.0
    for leg in legs:
        T      = leg.get("T", 0.0)
        api_g  = leg.get("api_gamma", 0.0)
        g      = api_g if api_g > 0 else bs_gamma(spot, leg["strike"], T, sigma, r)
        sign   = -1 if leg["is_sell"] else 1
        total += sign * g * leg["lots"]
    return total


def calc_wing_lots(legs_context, spot, sigma, wing_strike, wing_T,
                   gamma_fraction=1.0, min_lots=1, max_lots=50, r=0.065,
                   wing_api_gamma=0.0):
    """
    Solve for lots of a deep OTM wing buy needed to offset gamma_fraction of
    the net negative gamma in legs_context.
      gamma_fraction=1.0 → offset all remaining gamma (single wing)
    Uses wing_api_gamma (Upstox) when > 0, else falls back to BS.
    Returns an integer clamped to [min_lots, max_lots].
    """
    g_wing = wing_api_gamma if wing_api_gamma > 0 else bs_gamma(spot, wing_strike, wing_T, sigma, r)
    if g_wing <= 0:
        return min_lots
    net_g = net_gamma_lots(legs_context, spot, sigma, r)
    lots  = int(math.ceil((-net_g * gamma_fraction) / g_wing))
    return max(min_lots, min(lots, max_lots))


# keep old name as alias for backward compat
calc_wing_pe_lots = calc_wing_lots


def optimize_deep_otm_lots(spot, sigma,
                            ce_side_legs, pe_side_legs,
                            deep_ce_strike, deep_ce_ltp, deep_ce_api_gamma,
                            deep_pe_strike, deep_pe_ltp, deep_pe_api_gamma,
                            lot_size, wing_T,
                            min_lots=1, max_lots=12,
                            max_premium_spend=None, r=0.065):
    """
    Joint optimizer: find (qty_far_ce, qty_far_pe) for FAR LEGS (Long expiry)
    to symmetrize net gamma on both sides — flattens the intraday blue P&L line.

    Objective: minimize (total_gamma_CE_side - total_gamma_PE_side)²
    """
    # Resolve deep OTM gammas (API first, then BS)
    g_deep_ce = (deep_ce_api_gamma if deep_ce_api_gamma > 0
                 else bs_gamma(spot, deep_ce_strike, wing_T, sigma, r))
    g_deep_pe = (deep_pe_api_gamma if deep_pe_api_gamma > 0
                 else bs_gamma(spot, deep_pe_strike, wing_T, sigma, r))

    # Net gamma of each side from existing legs (negative = net short gamma)
    net_g_ce = net_gamma_lots(ce_side_legs, spot, sigma, r)
    net_g_pe = net_gamma_lots(pe_side_legs, spot, sigma, r)

    if not _SCIPY_OK or g_deep_ce <= 0 or g_deep_pe <= 0:
        # Fallback: independent per-side solving
        q_ce = calc_wing_lots(ce_side_legs, spot, sigma, deep_ce_strike, wing_T,
                              gamma_fraction=1.0, min_lots=min_lots, max_lots=max_lots,
                              wing_api_gamma=deep_ce_api_gamma)
        q_pe = calc_wing_lots(pe_side_legs, spot, sigma, deep_pe_strike, wing_T,
                              gamma_fraction=1.0, min_lots=min_lots, max_lots=max_lots,
                              wing_api_gamma=deep_pe_api_gamma)
        return q_ce, q_pe

    def objective(x):
        qty_ce, qty_pe = x[0], x[1]
        # Total gamma after adding far leg buys
        total_g_ce = net_g_ce + qty_ce * g_deep_ce
        total_g_pe = net_g_pe + qty_pe * g_deep_pe
        # Symmetry: squared difference → drives both sides to equal gamma exposure
        gamma_diff = (total_g_ce - total_g_pe) ** 2
        # Premium budget penalty
        cost_penalty = 0.0
        if max_premium_spend is not None and max_premium_spend > 0:
            cost = (qty_ce * deep_ce_ltp + qty_pe * deep_pe_ltp) * lot_size
            if cost > max_premium_spend:
                cost_penalty = ((cost - max_premium_spend) / max_premium_spend) ** 2 * 1e6
        return gamma_diff + cost_penalty

    result = _scipy_minimize(
        objective,
        x0=[max(min_lots, int(-net_g_ce / g_deep_ce)),
            max(min_lots, int(-net_g_pe / g_deep_pe))],
        bounds=[(min_lots, max_lots), (min_lots, max_lots)],
        method='L-BFGS-B'
    )
    qty_ce = max(min_lots, min(max_lots, int(round(result.x[0]))))
    qty_pe = max(min_lots, min(max_lots, int(round(result.x[1]))))
    return qty_ce, qty_pe


def solve_wing_lots_total_gamma(spot, sigma,
                                all_legs,
                                deep_ce_strike, deep_ce_api_gamma,
                                deep_pe_strike, deep_pe_api_gamma,
                                wing_T,
                                min_lots=1, max_lots=24, r=0.065):
    """
    Analytical solver for symmetric deep OTM wing lots.

    Computes total net gamma of the ENTIRE position (CE + PE combined),
    then finds a single lot count q (same for CE and PE wings) such that:

        total_net_gamma + q × (g_deep_ce + g_deep_pe) = 0
        => q = ceil(-total_net_gamma / (g_deep_ce + g_deep_pe))

    Gamma is option-type-agnostic (BS gamma is identical for CE and PE at
    same strike/T/sigma), so mixing CE/PE legs in all_legs is correct.
    Symmetric lots (same q on both sides) preserves delta neutrality.
    """
    g_deep_ce = (deep_ce_api_gamma if deep_ce_api_gamma > 0
                 else bs_gamma(spot, deep_ce_strike, wing_T, sigma, r))
    g_deep_pe = (deep_pe_api_gamma if deep_pe_api_gamma > 0
                 else bs_gamma(spot, deep_pe_strike, wing_T, sigma, r))

    total_net_g = net_gamma_lots(all_legs, spot, sigma, r)  # negative = net short
    g_sum = g_deep_ce + g_deep_pe
    if g_sum <= 0:
        return min_lots, min_lots

    q = int(math.ceil(-total_net_g / g_sum))
    q = max(min_lots, min(max_lots, q))
    return q, q


def nearest_chain_strike(chain_map, target, direction="below"):
    """
    Return the nearest strike in chain_map to target.
    direction='below' → largest available strike ≤ target
    direction='above' → smallest available strike ≥ target
    Falls back to nearest overall if none found in the preferred direction.
    """
    strikes = [s for s in chain_map if chain_map[s] > 0]
    if not strikes:
        return int(target)
    if direction == "below":
        candidates = [s for s in strikes if s <= target]
        return int(max(candidates)) if candidates else int(min(strikes, key=lambda s: abs(s - target)))
    else:
        candidates = [s for s in strikes if s >= target]
        return int(min(candidates)) if candidates else int(min(strikes, key=lambda s: abs(s - target)))


def find_deep_otm_strike(chain_map, sell_ltp, pct_lo=0.05, pct_hi=0.10,
                         min_strike=None, max_strike=None):
    """
    Find the deep OTM strike whose LTP ≈ sell_ltp × [pct_lo, pct_hi].

    The target range is expressed as a fraction of the SOLD option's premium so it
    automatically scales with market levels and volatility — e.g. if sell_ltp=₹50,
    the deep wing is selected at LTP ≈ ₹2.5–₹5 (5–10% of ₹50).

    Reference (Stockmock):
      CE sold ₹48.5 → deep CE ₹3.7  (7.6%)
      PE sold ₹88   → deep PE ₹6    (6.8%)

    Constraints:
      min_strike — deep CE must be ≥ this (enforces truly far OTM for calls)
      max_strike — deep PE must be ≤ this (enforces truly far OTM for puts)

    Returns (strike, ltp).  Returns (0, 0.0) if chain is empty.
    """
    ltp_lo = sell_ltp * pct_lo
    ltp_hi = sell_ltp * pct_hi
    ltp_mid = (ltp_lo + ltp_hi) / 2

    pool = {s: ltp for s, ltp in chain_map.items() if ltp > 0}
    if min_strike is not None:
        pool = {s: ltp for s, ltp in pool.items() if s >= min_strike}
    if max_strike is not None:
        pool = {s: ltp for s, ltp in pool.items() if s <= max_strike}
    if not pool:
        return 0, 0.0

    # Primary: strike whose LTP is inside the pct range
    candidates = [(s, ltp) for s, ltp in pool.items() if ltp_lo <= ltp <= ltp_hi]
    if candidates:
        best = min(candidates, key=lambda x: abs(x[1] - ltp_mid))
        return int(best[0]), best[1]

    # Fallback: closest LTP to midpoint regardless of range
    best = min(pool.items(), key=lambda x: abs(x[1] - ltp_mid))
    return int(best[0]), best[1]

# alias
find_deep_otm_pe_strike = find_deep_otm_strike


def find_delta_strikes(strike_map, spot, T, sigma, opt_type, delta_lo=0.12, delta_hi=0.18, r=0.065):
    """
    Return list of {strike, ltp, delta} where abs(delta) ∈ [delta_lo, delta_hi],
    sorted by closeness to mid-range delta target.
    """
    mid = (delta_lo + delta_hi) / 2
    cands = []
    for strike, ltp in strike_map.items():
        if ltp <= 0:
            continue
        d = bs_delta(spot, strike, T, sigma, opt_type, r)
        if delta_lo <= d <= delta_hi:
            cands.append({"strike": int(strike), "ltp": float(ltp), "delta": d})
    cands.sort(key=lambda x: abs(x["delta"] - mid))
    return cands


def get_monthly_expiries(all_exp):
    """
    Return set of expiry strings that are the last expiry of their calendar month.
    Works directly from the expiry list — no date-math assumptions.
    """
    month_last = {}
    for exp in sorted(all_exp):
        ym = exp[:7]          # "YYYY-MM"
        month_last[ym] = exp  # keeps overwriting → last entry per month wins
    return set(month_last.values())


def select_hv_far_expiry(all_exp, near_exp, near_dte):
    """
    Pick the MONTHLY expiry (last expiry of its calendar month in all_exp)
    with DTE >= 3 × near_dte.
    Falls back to nearest monthly expiry after near_exp, then any expiry.
    """
    monthly = get_monthly_expiries(all_exp)
    needed_dte = near_dte * 3
    # Pass 1: monthly expiry with sufficient DTE
    for exp in sorted(all_exp):
        if exp <= near_exp:
            continue
        if exp not in monthly:
            continue
        dte = (datetime.strptime(exp, "%Y-%m-%d").date()
               - datetime.now(IST).date()).days
        if dte >= needed_dte:
            return exp
    # Pass 2: any monthly expiry after near_exp
    for exp in sorted(all_exp):
        if exp > near_exp and exp in monthly:
            return exp
    # Pass 3: any expiry after near_exp
    for exp in sorted(all_exp):
        if exp > near_exp:
            return exp
    return None


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


def payoff_now(legs, spot_val, sigma, lot_size, r=0.065):
    """
    Intraday P&L at current date using Black-Scholes pricing for each leg.
    Each leg must have 'T' (annualised time to expiry at current moment).
    P&L = (current_bs_price − entry_ltp) × direction × lots × lot_size
    """
    pnl = 0.0
    for leg in legs:
        T = leg.get("T", 0.0)
        if T <= 0:
            # Expired — use intrinsic only
            cur = max(spot_val - leg["strike"], 0) if leg["opt_type"] == "CE" \
                  else max(leg["strike"] - spot_val, 0)
        else:
            cur = bs_price(S=spot_val, K=leg["strike"], T=T, sigma=sigma,
                           opt_type=leg["opt_type"], r=r)
        direction = -1 if leg["is_sell"] else 1
        pnl += direction * (cur - leg["ltp"]) * leg["lots"] * lot_size
    return pnl


def make_payoff_svg(legs, atm, lot_size, sell_ce_s, sell_pe_s,
                    sigma=0.15, spot=None, deployed_cap=0, cap_pct=1.6,
                    width=720, height=270):
    cur_spot = spot or atm

    # 1-day expected move (1σ) from VIX
    daily_move = cur_spot * sigma / math.sqrt(252)
    day_lo = cur_spot - daily_move
    day_hi = cur_spot + daily_move

    lo = atm - 14 * STEP
    hi = atm + 14 * STEP
    spots = list(range(int(lo), int(hi) + 1, STEP))

    # Expiry P&L (green curve)
    pts_exp = [(s, payoff_near_expiry(legs, float(s), lot_size)) for s in spots]
    # Intraday P&L using Black-Scholes at current time (blue curve)
    pts_now = [(s, payoff_now(legs, float(s), sigma, lot_size))  for s in spots]

    # Loss cap = 1.6% of deployed capital
    cap_loss = -(deployed_cap * cap_pct / 100) if deployed_cap > 0 else None

    # Worst intraday loss WITHIN the 1-day move band
    band_pnls = [v for s, v in pts_now if day_lo <= s <= day_hi]
    worst_intraday = min(band_pnls) if band_pnls else min(v for _, v in pts_now)
    worst_pct = abs(worst_intraday) / deployed_cap * 100 if deployed_cap > 0 else 0
    passes_cap = (cap_loss is None) or (worst_intraday >= cap_loss)

    all_pnls = [v for _, v in pts_exp] + [v for _, v in pts_now]
    max_p = max(all_pnls) if all_pnls else 1
    min_p = min(all_pnls) if all_pnls else -1
    if cap_loss is not None:
        min_p = min(min_p, cap_loss * 1.15)

    y_rng = max(abs(max_p), abs(min_p), 1)
    mg = 48
    pw = width  - 2 * mg
    ph = height - 2 * mg

    tx = lambda s: mg + (float(s) - lo) / (hi - lo) * pw
    ty = lambda v: mg + ph / 2 - (v / y_rng) * (ph / 2)
    zy = ty(0)

    svg = [f'<svg width="{width}" height="{height}" '
           f'style="background:#0a0e1a;border:1px solid #1c2840;border-radius:8px;">']

    # 1-day move band (shaded region)
    bx1 = max(tx(day_lo), mg)
    bx2 = min(tx(day_hi), mg + pw)
    svg.append(f'<rect x="{bx1:.1f}" y="{mg}" width="{max(bx2-bx1,0):.1f}" height="{ph}" '
               f'fill="#4d9fff" opacity="0.06" rx="2"/>')
    svg.append(f'<line x1="{bx1:.1f}" y1="{mg}" x2="{bx1:.1f}" y2="{mg+ph}" '
               f'stroke="#4d9fff" stroke-width="1" stroke-dasharray="3,3" opacity="0.4"/>')
    svg.append(f'<line x1="{bx2:.1f}" y1="{mg}" x2="{bx2:.1f}" y2="{mg+ph}" '
               f'stroke="#4d9fff" stroke-width="1" stroke-dasharray="3,3" opacity="0.4"/>')
    svg.append(f'<text x="{(bx1+bx2)/2:.0f}" y="{mg+ph+36}" font-size="8" fill="#4d9fff" '
               f'text-anchor="middle">1σ day ±{int(daily_move)}pts</text>')

    # Zero line
    svg.append(f'<line x1="{mg}" y1="{zy}" x2="{width-mg}" y2="{zy}" '
               f'stroke="#253352" stroke-width="1"/>')
    svg.append(f'<text x="{mg-4}" y="{zy+4}" font-size="9" fill="#4a6080" text-anchor="end">0</text>')

    # 1.6% cap line (full width)
    if cap_loss is not None:
        cy = ty(cap_loss)
        col_cap = "#ff5252" if not passes_cap else "#ff9800"
        svg.append(f'<line x1="{mg}" y1="{cy}" x2="{width-mg}" y2="{cy}" '
                   f'stroke="{col_cap}" stroke-width="1.5" stroke-dasharray="8,4" opacity="0.9"/>')
        svg.append(f'<text x="{mg+4}" y="{cy-4}" font-size="8" fill="{col_cap}">'
                   f'{cap_pct}% cap = ₹{abs(int(cap_loss)):,}</text>')

    # ATM / current spot lines
    ax = tx(atm)
    svg.append(f'<line x1="{ax}" y1="{mg}" x2="{ax}" y2="{mg+ph}" '
               f'stroke="#ffc940" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>')
    svg.append(f'<text x="{ax}" y="{mg-6}" font-size="9" fill="#ffc940" text-anchor="middle">ATM {atm}</text>')
    if cur_spot != atm:
        spx = tx(cur_spot)
        svg.append(f'<line x1="{spx}" y1="{mg}" x2="{spx}" y2="{mg+ph}" '
                   f'stroke="#ffffff" stroke-width="1" stroke-dasharray="2,4" opacity="0.3"/>')
        svg.append(f'<text x="{spx}" y="{mg-6}" font-size="8" fill="#aaaaaa" text-anchor="middle">{int(cur_spot)}</text>')

    # Short / long strike lines
    for s, color in [(sell_ce_s, "#2979ff"), (sell_pe_s, "#ab47bc")]:
        sx = tx(s)
        svg.append(f'<line x1="{sx}" y1="{mg}" x2="{sx}" y2="{mg+ph}" '
                   f'stroke="{color}" stroke-width="1" stroke-dasharray="3,3" opacity="0.7"/>')
        svg.append(f'<text x="{sx}" y="{mg+ph+14}" font-size="8" fill="{color}" text-anchor="middle">{s}(S)</text>')
    for leg in legs:
        if not leg["is_near"] and not leg["is_sell"]:
            sx = tx(leg["strike"])
            svg.append(f'<line x1="{sx}" y1="{mg}" x2="{sx}" y2="{mg+ph}" '
                       f'stroke="#00e676" stroke-width="1" stroke-dasharray="2,5" opacity="0.4"/>')
            svg.append(f'<text x="{sx}" y="{mg+ph+24}" font-size="8" fill="#00e676" text-anchor="middle">{leg["strike"]}(B)</text>')

    # Expiry P&L fill + line
    path = (f"M {tx(pts_exp[0][0])},{zy} "
            + " ".join(f"L {tx(s)},{ty(v)}" for s, v in pts_exp)
            + f" L {tx(pts_exp[-1][0])},{zy} Z")
    svg.append(f'<path d="{path}" fill="#00e676" opacity="0.07"/>')
    loss_path = (f"M {tx(pts_exp[0][0])},{zy} "
                 + " ".join(f"L {tx(s)},{ty(min(v, 0))}" for s, v in pts_exp)
                 + f" L {tx(pts_exp[-1][0])},{zy} Z")
    svg.append(f'<path d="{loss_path}" fill="#ff5252" opacity="0.10"/>')
    svg.append(f'<polyline points="{" ".join(f"{tx(s)},{ty(v)}" for s,v in pts_exp)}" '
               f'fill="none" stroke="#00e676" stroke-width="2" opacity="0.8"/>')

    # Intraday P&L line (blue dashed)
    svg.append(f'<polyline points="{" ".join(f"{tx(s)},{ty(v)}" for s,v in pts_now)}" '
               f'fill="none" stroke="#4d9fff" stroke-width="2.5" stroke-dasharray="7,3" opacity="0.95"/>')

    # Worst intraday loss dot WITHIN band
    worst_s = next((s for s, v in pts_now if v == worst_intraday), cur_spot)
    dot_col = "#ff5252" if not passes_cap else "#ffc940"
    dx = tx(worst_s); dy = ty(worst_intraday)
    svg.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="5" fill="{dot_col}" opacity="0.95"/>')
    svg.append(f'<text x="{dx:.1f}" y="{dy-8}" font-size="9" font-weight="bold" fill="{dot_col}" text-anchor="middle">'
               f'▼ {worst_pct:.1f}%</text>')

    # Legend + pass/fail badge
    lx = mg + 4
    pass_col = "#00e676" if passes_cap else "#ff5252"
    pass_txt = f"✅ WITHIN {cap_pct}% CAP" if passes_cap else f"❌ BREACH {cap_pct}% CAP"
    svg.append(f'<text x="{width-mg-4}" y="{mg+14}" font-size="10" font-weight="bold" '
               f'fill="{pass_col}" text-anchor="end">{pass_txt}</text>')
    svg.append(f'<text x="{width-mg-4}" y="{mg+26}" font-size="9" fill="{dot_col}" text-anchor="end">'
               f'Worst intraday (1σ band): ₹{abs(int(worst_intraday)):,} = {worst_pct:.1f}% of cap</text>')
    svg.append(f'<circle cx="{lx+4}" cy="{mg+12}" r="4" fill="#00e676"/>')
    svg.append(f'<text x="{lx+12}" y="{mg+16}" font-size="9" fill="#00e676">Expiry P&L</text>')
    svg.append(f'<line x1="{lx}" y1="{mg+26}" x2="{lx+10}" y2="{mg+26}" '
               f'stroke="#4d9fff" stroke-width="2" stroke-dasharray="5,2"/>')
    svg.append(f'<text x="{lx+14}" y="{mg+30}" font-size="9" fill="#4d9fff">Intraday P&L (today, BS-priced)</text>')

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
    f"<p class='mono' style='font-size:11px;color:var(--muted);margin-bottom:.4rem;'>"
    f"{dot} {'OPEN' if mkt_open else 'CLOSED'} &nbsp;·&nbsp; "
    f"{now.strftime('%d %b %Y %H:%M IST')}</p>",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
if not secrets_ok():
    st.error("Missing Upstox credentials in Streamlit secrets. Contact the app admin.")
    st.stop()

# Load secrets into local variables — never render these to the page
_ak = st.secrets["upstox"]["api_key"]
_as = st.secrets["upstox"]["api_secret"]
_ru = st.secrets["upstox"]["redirect_uri"]

# GitHub token — needed early for SPP cache bootstrap (before PCR section)
_gh_tok_early = None
try:
    _gh_tok_early = st.secrets["github"]["token"]
except Exception:
    pass

# Pre-load baked token if present in secrets
if "access_token" not in st.session_state:
    try:
        _baked = st.secrets["upstox"].get("access_token", "")
        if _baked:
            st.session_state.update(access_token=_baked, token_acquired=time.time())
    except Exception:
        pass

# Handle OAuth callback — consume code immediately and clear params
_qp_code = st.query_params.get("code")
if _qp_code and "access_token" not in st.session_state:
    st.query_params.clear()   # clear URL params NOW before any render
    with st.spinner("Completing Upstox login…"):
        _tok, _tok_err = exchange_code(_ak, _as, _ru, _qp_code)
    if _tok:
        st.session_state.update(access_token=_tok, token_acquired=time.time())
        st.rerun()
    else:
        st.error(f"Login failed — please try connecting again. ({_tok_err})")
        st.stop()
elif _qp_code:
    # Code arrived but token already present — just clear the URL
    st.query_params.clear()

# Expire token after 24 h
if "access_token" in st.session_state:
    if time.time() - st.session_state.get("token_acquired", 0) > 86400:
        del st.session_state["access_token"]; st.rerun()

if "access_token" not in st.session_state:
    _auth_url = build_auth_url(_ak, _ru)
    st.markdown(
        "<div style='border:1px solid var(--border);border-radius:12px;"
        "padding:1.5rem 2rem;max-width:320px;margin:2rem auto;text-align:center;'>",
        unsafe_allow_html=True,
    )
    st.markdown("### 🔐 Login with Upstox")
    st.markdown(
        "<p style='color:var(--muted);font-size:12px;'>One click per trading day</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<a href='{_auth_url}' target='_blank' rel='noopener noreferrer' style='"
        f"display:inline-block;padding:.5rem 1.4rem;border-radius:8px;"
        f"background:var(--gold);color:#000;font-weight:700;font-size:14px;"
        f"text-decoration:none;letter-spacing:.5px;'>CONNECT →</a>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

token = st.session_state["access_token"]
del _ak, _as, _ru   # no further need; prevent accidental render

# ── Instrument selector ───────────────────────────────────────────────────────
_inst_names  = list(INSTRUMENT_CONFIGS.keys())
_inst_choice = st.selectbox(
    "📈 Instrument",
    _inst_names,
    index=_inst_names.index(st.session_state.get("instrument", "NIFTY")),
    key="instrument",
)
_INST        = INSTRUMENT_CONFIGS[_inst_choice]
# Override runtime constants for selected instrument
STEP            = _INST["step"]
# Use live lot from session_state (updated each run from chain API); fall back to config
LOT_SIZE        = st.session_state.get(f"live_lot_{_inst_choice}", _INST["lot"])
SYMBOL          = _INST["symbol"]
INSTRUMENT_KEY  = _INST["key"]
PCR_CSV_PATH    = _INST["pcr_csv"]
WING_OFFSET     = 10 * STEP   # ±10 steps (500 NIFTY, 1000 BNIFTY/SENSEX)
DEEP_OTM_OFFSET = 18 * STEP   # deep OTM min distance

# ── VIX (early fetch — needed for strategy banner) ──────────────────────────
_open_vix, _curr_vix, _nifty_day_open, _vix_err_early = fetch_vix_and_nifty_open(token, spot_key=INSTRUMENT_KEY)
if _vix_err_early == "token_expired":
    del st.session_state["access_token"]; st.rerun()

if _open_vix and _curr_vix:
    _eff_vix   = (_open_vix + _curr_vix) / 2
    _vix_ok    = True
else:
    _eff_vix   = 0.0
    _vix_ok    = False

# Open ATM — anchored to NIFTY day-open price, falls back to current spot
_open_atm = (int(round(_nifty_day_open / STEP) * STEP)
             if _nifty_day_open and _nifty_day_open > 0 else None)

# ── VIX premium ranges scaled by lot size relative to NIFTY ─────────────────
# Use live NIFTY lot cached from last NIFTY chain fetch; fall back to config
_NIFTY_REF_LOT = st.session_state.get("live_lot_NIFTY", INSTRUMENT_CONFIGS["NIFTY"]["lot"])
_vix_lot_scale = _NIFTY_REF_LOT / max(LOT_SIZE, 1)
# Round to nearest 5 for readability
def _vp(x): return int(round(x * _vix_lot_scale / 5) * 5)
_vp_lo_l, _vp_lo_h   = _vp(28), _vp(35)   # VIX < 13
_vp_mid_l, _vp_mid_h = _vp(32), _vp(45)   # VIX 14-18
_vp_hi                = _vp(50)             # VIX > 19

# ── Strategy banner (rendered inline — no st.empty() placeholder) ────────────
_active_strat = STRATEGY_REGISTRY[0] if (_vix_ok and _eff_vix > 15.0) else STRATEGY_REGISTRY[1]
_sc = _active_strat["color"]
st.markdown(
    f"<div style='border-left:4px solid {_sc};background:var(--surface);"
    f"border:1px solid {_sc};border-radius:10px;padding:.6rem 1rem;margin-bottom:.75rem;"
    f"display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap;'>"
    f"<div style='min-width:220px;'>"
    f"<div style='font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;"
    f"color:{_sc};font-family:var(--mono);'>"
    f"{_active_strat['emoji']} Active Strategy</div>"
    f"<div style='font-size:16px;font-weight:800;color:var(--text);font-family:var(--hdr);'>"
    f"{_active_strat['name']}</div>"
    f"<div style='font-size:10px;color:var(--muted);margin-top:2px;'>"
    f"Regime: <b style='color:{_sc};'>{_active_strat['regime']}</b> &nbsp;·&nbsp; "
    f"Trigger: <code style='background:var(--border);padding:1px 5px;border-radius:3px;"
    f"font-size:10px;'>{_active_strat['trigger']}</code>"
    + (f" &nbsp;·&nbsp; VIX <b style='color:{_sc};'>{_eff_vix:.2f}</b>" if _vix_ok else "")
    + f"</div></div>"
    f"<div style='min-width:160px;'>"
    f"<div style='font-size:10px;color:var(--muted);letter-spacing:1px;text-transform:uppercase;"
    f"font-weight:700;margin-bottom:6px;'>VIX &amp; Premium</div>"
    + (
        "<div style='display:flex;flex-direction:column;gap:3px;'>"
        + (
            f"<div style='background:#003318;border-left:3px solid #00e676;border-radius:4px;"
            f"padding:2px 8px;font-size:12px;font-weight:700;color:#00e676;'>"
            f"&lt;13 &#8594; &#8377;{_vp_lo_l}-{_vp_lo_h}</div>"
            if _eff_vix < 13 else
            f"<div style='color:#5a7090;font-size:11px;padding:2px 8px;'>&lt;13 &#8594; &#8377;{_vp_lo_l}-{_vp_lo_h}</div>"
        )
        + (
            f"<div style='background:#2a1e00;border-left:3px solid #ffc940;border-radius:4px;"
            f"padding:2px 8px;font-size:12px;font-weight:700;color:#ffc940;'>"
            f"14-18 &#8594; &#8377;{_vp_mid_l}-{_vp_mid_h}</div>"
            if 13 <= _eff_vix <= 19 else
            f"<div style='color:#5a7090;font-size:11px;padding:2px 8px;'>14-18 &#8594; &#8377;{_vp_mid_l}-{_vp_mid_h}</div>"
        )
        + (
            f"<div style='background:#2a0808;border-left:3px solid #ff5252;border-radius:4px;"
            f"padding:2px 8px;font-size:12px;font-weight:700;color:#ff5252;'>"
            f"&gt;19 &#8594; &#8377;{_vp_hi}+</div>"
            if _eff_vix > 19 else
            f"<div style='color:#5a7090;font-size:11px;padding:2px 8px;'>&gt;19 &#8594; &#8377;{_vp_hi}+</div>"
        )
        + "</div>"
        if _vix_ok else
        f"<div style='color:#5a7090;font-size:11px;'>"
        f"&lt;13 &#8377;{_vp_lo_l}-{_vp_lo_h}<br>14-18 &#8377;{_vp_mid_l}-{_vp_mid_h}<br>&gt;19 &#8377;{_vp_hi}+</div>"
    )
    + f"</div>"
    f"<div style='flex:1;min-width:280px;'>"
    f"<div style='font-size:10px;color:var(--muted);letter-spacing:1px;text-transform:uppercase;"
    f"font-weight:700;margin-bottom:3px;'>Structure</div>"
    f"<div style='font-family:var(--mono);font-size:11px;color:var(--text);'>"
    f"{_active_strat['structure']}</div>"
    f"</div>"
    f"<div style='flex:1;min-width:260px;'>"
    f"<div style='font-size:10px;color:var(--muted);letter-spacing:1px;text-transform:uppercase;"
    f"font-weight:700;margin-bottom:3px;'>Why this strategy</div>"
    f"<div style='font-size:11px;color:var(--text);line-height:1.5;'>{_active_strat['why']}</div>"
    f"<div style='font-size:10px;color:var(--muted);margin-top:4px;'>"
    f"✅ Best for: {_active_strat['best_for']}</div>"
    f"</div></div>",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>⚙️ Parameters</div>", unsafe_allow_html=True)
col_p1, col_p2, col_p3 = st.columns([2, 2, 1])
with col_p1:
    sell_lots = st.number_input("Short Leg Lots (SELL)", min_value=1, max_value=20, value=2)
with col_p2:
    ltp_ratio = st.slider("Long LTP target (% of Sell LTP)", 30, 80, 50, 5,
                          help="Far strike selected where LTP ≈ this % of the sold LTP")
with col_p3:
    _refresh_mins = st.selectbox("🔄 Refresh", [1, 2, 3, 5, 10], index=2,
                                 help="Auto-refresh interval in minutes")
_refresh_secs = _refresh_mins * 60
PCR_LOG_INTERVAL = _refresh_secs   # align PCR logging to refresh cadence

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if _AUTOREFRESH_OK:
    _st_autorefresh(interval=_refresh_secs * 1000, key="auto_refresh")
else:
    st.caption(f"⚠️ Install `streamlit-autorefresh` for auto-refresh every {_refresh_mins} min.")

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
far_cutoff    = today + timedelta(weeks=2)
near_expiries = [d for d in all_exp if datetime.strptime(d,"%Y-%m-%d").date() <= near_cutoff] or all_exp[:2]
far_expiries  = [d for d in all_exp if datetime.strptime(d,"%Y-%m-%d").date() >= far_cutoff]  or all_exp[4:]

col_e1, col_e2 = st.columns(2)
with col_e1:
    near_exp = st.selectbox(f"📅 Current Expiry — SELL ({len(near_expiries)} available)", near_expiries)
with col_e2:
    far_exp  = st.selectbox(f"📅 Far Expiry — BUY ≥2 weeks ({len(far_expiries)} available)", far_expiries)

nw = weeks_out(near_exp)
fw = weeks_out(far_exp)
st.markdown(
    f"<p class='mono' style='font-size:11px;color:var(--muted);'>"
    f"Near <b style='color:#ffc940'>{near_exp}</b> ({nw:.1f} wks) &nbsp;│&nbsp; "
    f"Far  <b style='color:#00e676'>{far_exp}</b> ({fw:.1f} wks) &nbsp;│&nbsp; "
    f"Gap <b style='color:white'>{fw-nw:.1f} wks</b></p>",
    unsafe_allow_html=True,
)

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

# ── Live lot size from chain (auto-tracks exchange changes) ──────────────────
for _cl_row in near_raw:
    _cl_lot = _cl_row.get("lot_size")
    if _cl_lot:
        try:
            _cl_lot_int = int(float(_cl_lot))
            if _cl_lot_int > 0:
                LOT_SIZE = _cl_lot_int
                st.session_state[f"live_lot_{_inst_choice}"] = _cl_lot_int
                break
        except Exception:
            pass

spot, atm, near_ce, near_pe, near_ce_oi, near_pe_oi, near_ce_oi_chg, near_pe_oi_chg, near_ce_gamma, near_pe_gamma = parse_chain(near_raw)
_,    _,   far_ce,  far_pe,  far_ce_oi,  far_pe_oi,  far_ce_oi_chg,  far_pe_oi_chg,  far_ce_gamma,  far_pe_gamma  = parse_chain(far_raw)

# ── ATM CE/PE VWAP — from Upstox v3 intraday 1-min candles ──────────────────
# Cache key: changes when date, instrument, or ATM strike changes
# Only cache successful (non-None) results so failures retry on next refresh
_vwap_cache_key = f"{now.date().isoformat()}_{_inst_choice}_{atm}_{near_exp}"
_vwap_cached    = st.session_state.get("atm_vwap_cache", {})
_vwap_hit = (_vwap_cached.get("key") == _vwap_cache_key
             and _vwap_cached.get("ce_vwap") is not None)
if _vwap_hit:
    _atm_ce_vwap = _vwap_cached["ce_vwap"]
    _atm_pe_vwap = _vwap_cached["pe_vwap"]
    _atm_ce_vol  = _vwap_cached["ce_vol"]
    _atm_pe_vol  = _vwap_cached["pe_vol"]
else:
    _atm_ce_vwap = _atm_pe_vwap = _atm_ce_vol = _atm_pe_vol = None
    if token:
        _atm_ce_vwap, _atm_pe_vwap, _atm_ce_vol, _atm_pe_vol = \
            fetch_atm_vwap(token, near_raw, atm)
        if _atm_ce_vwap is not None:   # only cache on success
            st.session_state["atm_vwap_cache"] = {
                "key": _vwap_cache_key,
                "ce_vwap": _atm_ce_vwap, "pe_vwap": _atm_pe_vwap,
                "ce_vol": _atm_ce_vol,   "pe_vol": _atm_pe_vol,
            }

# ── Intraday OI baseline tracking ─────────────────────────────────────────────
# Upstox chain has no intraday OI change field — we snapshot OI on first load
# of the day and diff against it on every 3-min refresh.
# Key = date + near_exp so baseline resets when expiry changes.
_oi_base_key = f"{now.date().isoformat()}_{near_exp}_{_inst_choice}"
_oi_bl       = st.session_state.get("oi_baseline", {})
if _oi_bl.get("key") != _oi_base_key:
    # First load of this day/expiry — store as baseline
    st.session_state["oi_baseline"] = {
        "key": _oi_base_key,
        "ce":  dict(near_ce_oi),
        "pe":  dict(near_pe_oi),
    }
    _base_ce_oi = dict(near_ce_oi)
    _base_pe_oi = dict(near_pe_oi)
else:
    _base_ce_oi = _oi_bl["ce"]
    _base_pe_oi = _oi_bl["pe"]

# Per-strike intraday OI change (positive = OI added since session start)
_intra_ce_oi_chg = {s: near_ce_oi.get(s, 0) - _base_ce_oi.get(s, 0) for s in near_ce_oi}
_intra_pe_oi_chg = {s: near_pe_oi.get(s, 0) - _base_pe_oi.get(s, 0) for s in near_pe_oi}

# ── VIX derived values (spot-dependent, computed after chain load) ───────────
_days_to_exp = max(
    (datetime.strptime(near_exp, "%Y-%m-%d").date() - now.date()).days, 1
)
if _vix_ok and spot:
    _daily_vix = _eff_vix / math.sqrt(252)
    _exp_1s    = spot * (_eff_vix / 100) * math.sqrt(_days_to_exp / 252)
    _exp_2s    = _exp_1s * 2
    _steps_1s  = max(1, round(_exp_1s / STEP))
    _steps_2s  = max(1, round(_exp_2s / STEP))
else:
    _daily_vix = _exp_1s = _exp_2s = 0.0
    _steps_1s  = _steps_2s = SHORT_STEPS
    _range_hi_1s = _range_lo_1s = _ltp_hi_1s = _ltp_lo_1s = None

# ── Probable range banner (VIX × √DTE) ───────────────────────────────────────
if _vix_ok and spot:
    _range_hi_1s = int(round((atm + _exp_1s) / STEP) * STEP)
    _range_lo_1s = int(round((atm - _exp_1s) / STEP) * STEP)
    _range_hi_2s = int(round((atm + _exp_2s) / STEP) * STEP)
    _range_lo_2s = int(round((atm - _exp_2s) / STEP) * STEP)
    _daily_pts   = spot * (_eff_vix / 100) / math.sqrt(252)
    # LTPs at range strikes from near chain
    _ltp_hi_1s = near_ce.get(float(_range_hi_1s), 0)
    _ltp_lo_1s = near_pe.get(float(_range_lo_1s), 0)
    _ltp_hi_2s = near_ce.get(float(_range_hi_2s), 0)
    _ltp_lo_2s = near_pe.get(float(_range_lo_2s), 0)
    def _ltp_str(v): return f"₹{v:.1f}" if v else "—"
    st.markdown(
        f"<div style='background:rgba(255,201,64,0.07);border:1px solid rgba(255,201,64,0.25);"
        f"border-radius:6px;padding:.35rem .8rem;margin:.25rem 0 .4rem;display:flex;"
        f"flex-wrap:wrap;align-items:center;gap:.6rem;'>"
        f"<span style='color:var(--gold);font-weight:700;font-size:11px;letter-spacing:.5px;'>"
        f"📐 RANGE · {near_exp} &nbsp;<span style='color:var(--muted);font-weight:400;'>({_days_to_exp}d)</span></span>"
        f"<span style='color:var(--muted);font-size:10px;'>Daily&nbsp;1σ:</span>"
        f"<span style='font-family:var(--mono);font-size:12px;color:white;'>±{_daily_pts:.0f} pts</span>"
        f"<span style='color:var(--border);'>│</span>"
        f"<span style='color:var(--muted);font-size:10px;'>1σ&nbsp;({_exp_1s:.0f}pts):</span>"
        f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--pe);'>{_range_lo_1s}</span>"
        f"<span style='color:var(--muted);font-size:10px;'>({_ltp_str(_ltp_lo_1s)})</span>"
        f"<span style='color:var(--muted);font-size:11px;'>↔</span>"
        f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--ce);'>{_range_hi_1s}</span>"
        f"<span style='color:var(--muted);font-size:10px;'>({_ltp_str(_ltp_hi_1s)})</span>"
        f"<span style='color:var(--border);'>│</span>"
        f"<span style='color:var(--muted);font-size:10px;'>2σ&nbsp;({_exp_2s:.0f}pts):</span>"
        f"<span style='font-family:var(--mono);font-size:12px;color:var(--pe);'>{_range_lo_2s}</span>"
        f"<span style='color:var(--muted);font-size:10px;'>({_ltp_str(_ltp_lo_2s)})</span>"
        f"<span style='color:var(--muted);font-size:11px;'>↔</span>"
        f"<span style='font-family:var(--mono);font-size:12px;color:var(--ce);'>{_range_hi_2s}</span>"
        f"<span style='color:var(--muted);font-size:10px;'>({_ltp_str(_ltp_hi_2s)})</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

# Seed session_state with VIX default only when VIX value changes
# (preserves user override across auto-refreshes, resets when VIX shifts)
_vix_default = _steps_1s  # VIX-implied steps (or fallback SHORT_STEPS)
if st.session_state.get("_last_vix_default") != _vix_default:
    st.session_state["_last_vix_default"] = _vix_default
    st.session_state["short_steps_val"]   = _vix_default

# short_steps slider is rendered inside the VIX section below;
# read the current value from session_state here so strike calc uses it
short_steps = st.session_state.get("short_steps_val", _vix_default)

# ── VIX target premium range (per leg) ───────────────────────────────────────
if _vix_ok:
    if _eff_vix < 13:
        _vp_tgt_l, _vp_tgt_h = _vp_lo_l, _vp_lo_h
        _vp_tgt_band = f"VIX &lt;13"
    elif _eff_vix <= 19:
        _vp_tgt_l, _vp_tgt_h = _vp_mid_l, _vp_mid_h
        _vp_tgt_band = f"VIX 14-18"
    else:
        _vp_tgt_l, _vp_tgt_h = _vp_hi, None
        _vp_tgt_band = f"VIX &gt;19"
else:
    _vp_tgt_l = _vp_tgt_h = None
    _vp_tgt_band = ""

# ─────────────────────────────────────────────
# SELL STRIKES — chosen by VIX target premium when VIX is available,
# else fall back to step-based auto_adjust
# ─────────────────────────────────────────────
_vix_ce_strike = _vix_pe_strike = None
_vix_ce_ltp    = _vix_pe_ltp    = None
_vix_ce_in_range = _vix_pe_in_range = False

if _vp_tgt_l:
    _vix_ce_strike, _vix_ce_ltp, _vix_ce_in_range = \
        find_strike_by_premium(near_ce, atm, STEP, "CE", _vp_tgt_l, _vp_tgt_h)
    _vix_pe_strike, _vix_pe_ltp, _vix_pe_in_range = \
        find_strike_by_premium(near_pe, atm, STEP, "PE", _vp_tgt_l, _vp_tgt_h)

# Use VIX-premium strike if found, else fall back to step-based selection
if _vix_ce_strike and _vix_pe_strike:
    sell_ce_strike, sell_ce_ltp = _vix_ce_strike, _vix_ce_ltp
    sell_pe_strike, sell_pe_ltp = _vix_pe_strike, _vix_pe_ltp
    ce_steps = abs(sell_ce_strike - atm) // STEP
    pe_steps = abs(sell_pe_strike - atm) // STEP
    ce_cands = find_long_candidates(sell_ce_ltp, far_ce, atm, "CE", ltp_ratio, oi_map=far_ce_oi)
    pe_cands = find_long_candidates(sell_pe_ltp, far_pe, atm, "PE", ltp_ratio, oi_map=far_pe_oi)
    ce_adjusted = pe_adjusted = False
else:
    ce_steps, sell_ce_strike, sell_ce_ltp, ce_cands, ce_adjusted = \
        auto_adjust_sell_strike(short_steps, atm, near_ce, far_ce, "CE", ltp_ratio, oi_map=far_ce_oi)
    pe_steps, sell_pe_strike, sell_pe_ltp, pe_cands, pe_adjusted = \
        auto_adjust_sell_strike(short_steps, atm, near_pe, far_pe, "PE", ltp_ratio, oi_map=far_pe_oi)

best_ce = ce_cands[0] if ce_cands else {"strike": sell_ce_strike, "ltp": 0, "diff_pct": 99}
best_pe = pe_cands[0] if pe_cands else {"strike": sell_pe_strike, "ltp": 0, "diff_pct": 99}

# ── 3-Lot Sell / 1-Lot Buy diagonal computation ──────────────────────────────
# Sell 3 lots: per-leg target = VIX_strangle_target / 6
#              → 3 × (CE + PE) per unit = VIX_strangle_target
# Buy  1 lot : far expiry ATM straddle ≥ 70% of 3-lot sell total
_3lot_sell_lots = 3
_3lot_ce_strike = _3lot_pe_strike = _3lot_ce_ltp = _3lot_pe_ltp = None
_3lot_sell_total = None

if _vp_tgt_l:
    _per_leg_3lot_lo = _vp_tgt_l / 3          # = VIX_strangle_lo / 6
    _per_leg_3lot_hi = (_vp_tgt_h / 3) if _vp_tgt_h else None
    _3lot_ce_strike, _3lot_ce_ltp, _ = find_strike_by_premium(
        near_ce, atm, STEP, "CE", _per_leg_3lot_lo, _per_leg_3lot_hi)
    _3lot_pe_strike, _3lot_pe_ltp, _ = find_strike_by_premium(
        near_pe, atm, STEP, "PE", _per_leg_3lot_lo, _per_leg_3lot_hi)
    if _3lot_ce_ltp and _3lot_pe_ltp:
        _3lot_sell_total = _3lot_sell_lots * (_3lot_ce_ltp + _3lot_pe_ltp)

# ── Far-leg: find symmetric strangle closest to premium target ───────────────
def _find_far_by_premium(far_ce_map, far_pe_map, base, step, target_lo, target_hi,
                         max_steps=60, far_ce_oi_map=None, far_pe_oi_map=None, min_oi=50):
    """
    Scan outward from ATM. Two passes:
    Pass 1 — find widest strike where CE+PE is in [target_lo, target_hi]  (ideal)
    Pass 2 — if no in-band hit, return the strike where CE+PE is closest to midpoint
    Always returns a result with real LTP (never zeros out).
    """
    mid = (target_lo + target_hi) / 2.0
    band_best  = None                               # best in-band (widest)
    close_best = None                               # closest to mid overall
    close_dist = float("inf")

    for n in range(0, max_steps + 1):
        ce_s = base + n * step
        pe_s = base - n * step
        ce_l = far_ce_map.get(float(ce_s), 0)
        pe_l = far_pe_map.get(float(pe_s), 0)
        if ce_l <= 0 or pe_l <= 0:
            continue
        if far_ce_oi_map is not None and far_pe_oi_map is not None:
            if (far_ce_oi_map.get(float(ce_s), 0) < min_oi or
                    far_pe_oi_map.get(float(pe_s), 0) < min_oi):
                continue
        total = ce_l + pe_l
        row   = {"ce_strike": int(ce_s), "ce_ltp": ce_l,
                 "pe_strike": int(pe_s), "pe_ltp": pe_l}
        # In-band: keep widest
        if target_lo <= total <= target_hi:
            band_best = row
        # Track closest to midpoint regardless
        dist = abs(total - mid)
        if dist < close_dist:
            close_dist = dist
            close_best = row
        # Stop scanning when premium drops well below floor (no point going wider)
        if total < target_lo * 0.40:
            break

    return band_best if band_best else (close_best or
           {"ce_strike": int(base), "ce_ltp": 0.0,
            "pe_strike": int(base), "pe_ltp": 0.0})

_far_tgt_lo   = (_3lot_sell_total * 0.80) if _3lot_sell_total else 0
_far_tgt_hi   = (_3lot_sell_total * 1.40) if _3lot_sell_total else 0
_far_tgt_mid  = (_3lot_sell_total * 1.10) if _3lot_sell_total else 0  # ideal centre

# ── Auto-pick best far expiry across all far_expiries ────────────────────────
# Rules: (1) must not be the same ISO week as near_exp
#        (2) choose expiry whose far-leg combined premium is closest to 110% of sold
_near_week = datetime.strptime(near_exp, "%Y-%m-%d").isocalendar()[:2]  # (year, week)

def _week_of(exp_str):
    return datetime.strptime(exp_str, "%Y-%m-%d").isocalendar()[:2]

_diag_best_exp    = None
_diag_best_result = None
_diag_best_dist   = float("inf")
_diag_best_ce_m   = None
_diag_best_pe_m   = None
_diag_best_ce_oi  = None
_diag_best_pe_oi  = None
_diag_scan_log    = []   # [(exp, ce_strike, pe_strike, total, in_band, skipped_reason)]

for _cand_exp in far_expiries[:6]:
    if _week_of(_cand_exp) == _near_week:
        _diag_scan_log.append((_cand_exp, None, None, None, False, "same week as near"))
        continue
    try:
        _craw, _cerr = fetch_chain(token, _cand_exp)
        if _cerr or not _craw:
            _diag_scan_log.append((_cand_exp, None, None, None, False, f"chain err: {_cerr}"))
            continue
        _, _, _c_ce, _c_pe, _c_ce_oi, _c_pe_oi, *_ = parse_chain(_craw)
        _cres = _find_far_by_premium(
            _c_ce, _c_pe, atm, STEP, _far_tgt_lo, _far_tgt_hi,
            far_ce_oi_map=_c_ce_oi, far_pe_oi_map=_c_pe_oi,
        )
        _ctotal = _cres["ce_ltp"] + _cres["pe_ltp"]
        if _ctotal <= 0:
            _diag_scan_log.append((_cand_exp, None, None, 0, False, "no LTP data"))
            continue
        _in_band = _far_tgt_lo <= _ctotal <= _far_tgt_hi
        _dist    = abs(_ctotal - _far_tgt_mid) - (1e9 if _in_band else 0)
        _diag_scan_log.append((
            _cand_exp, _cres["ce_strike"], _cres["pe_strike"],
            _ctotal, _in_band, "✓" if _in_band else ("↑" if _ctotal > _far_tgt_hi else "↓")
        ))
        if _dist < _diag_best_dist:
            _diag_best_dist   = _dist
            _diag_best_exp    = _cand_exp
            _diag_best_result = _cres
            _diag_best_ce_m   = _c_ce
            _diag_best_pe_m   = _c_pe
            _diag_best_ce_oi  = _c_ce_oi
            _diag_best_pe_oi  = _c_pe_oi
    except Exception as _e:
        _diag_scan_log.append((_cand_exp, None, None, None, False, str(_e)[:30]))
        continue

# Use auto-selected expiry; fall back to user-selected far_exp if nothing found
if _diag_best_result:
    _diag_far_exp      = _diag_best_exp
    _far_atm_ce_strike = _diag_best_result["ce_strike"]
    _far_atm_ce_ltp    = _diag_best_result["ce_ltp"]
    _far_atm_pe_strike = _diag_best_result["pe_strike"]
    _far_atm_pe_ltp    = _diag_best_result["pe_ltp"]
    _fb_ce_map         = _diag_best_ce_m
    _fb_pe_map         = _diag_best_pe_m
    _fb_ce_oi_map      = _diag_best_ce_oi
    _fb_pe_oi_map      = _diag_best_pe_oi
else:
    _diag_far_exp      = far_exp
    _far_atm_ce_strike = atm
    _far_atm_ce_ltp    = 0.0
    _far_atm_pe_strike = atm
    _far_atm_pe_ltp    = 0.0
    _fb_ce_map         = far_ce
    _fb_pe_map         = far_pe
    _fb_ce_oi_map      = far_ce_oi
    _fb_pe_oi_map      = far_pe_oi

_far_atm_straddle = _far_atm_ce_ltp + _far_atm_pe_ltp

_buy_ok        = bool(_far_tgt_lo and _far_tgt_lo <= _far_atm_straddle <= _far_tgt_hi)
_buy_ratio_pct = ((_far_atm_straddle / _3lot_sell_total) * 100) if _3lot_sell_total else None

# ── Ratio Diagonal CE  (Sell 1 ATM CE near · Buy 2 far CE at 40–50% premium) ──

# ── Strike Lock: freeze ATM strike for 1 hour once market is open ──────────────
_rd_lock_key      = "rd_locked_atm"
_rd_lock_time_key = "rd_lock_time"
_rd_now           = now   # datetime.now(IST) already computed above

if mkt_open:
    _rd_existing_lock = st.session_state.get(_rd_lock_key)
    _rd_lock_time     = st.session_state.get(_rd_lock_time_key)
    if _rd_existing_lock is None or _rd_lock_time is None:
        # First render during market hours — lock the current ATM
        st.session_state[_rd_lock_key]      = atm
        st.session_state[_rd_lock_time_key] = _rd_now
        _rd_use_atm   = atm
        _rd_locked     = False   # just set; show as "just locked"
        _rd_lock_secs  = 0
    else:
        _rd_lock_secs = (_rd_now - _rd_lock_time).total_seconds()
        if _rd_lock_secs < 3600:
            # Within 1 hour — use locked ATM
            _rd_use_atm  = _rd_existing_lock
            _rd_locked    = True
        else:
            # Lock expired — reset to current ATM
            st.session_state[_rd_lock_key]      = atm
            st.session_state[_rd_lock_time_key] = _rd_now
            _rd_use_atm  = atm
            _rd_locked    = False
            _rd_lock_secs = 0
else:
    # Market closed — clear any stale lock and use live ATM
    st.session_state.pop(_rd_lock_key,      None)
    st.session_state.pop(_rd_lock_time_key, None)
    _rd_use_atm  = atm
    _rd_locked    = False
    _rd_lock_secs = 0

_rd_lock_remaining = max(0, 3600 - int(_rd_lock_secs))   # seconds left on lock
# ────────────────────────────────────────────────────────────────────────────────

_rd_atm_ce_ltp    = near_ce.get(float(_rd_use_atm), 0)
_rd_lo            = _rd_atm_ce_ltp * 0.40
_rd_hi            = _rd_atm_ce_ltp * 0.50
_rd_far_ce_strike = int(_rd_use_atm)
_rd_far_ce_ltp    = 0.0
_rd_in_range      = False

if _rd_atm_ce_ltp > 0:
    for _rdi in range(1, 35):
        _rds = _rd_use_atm + _rdi * STEP
        _rdl = far_ce.get(float(_rds), 0)
        if _rdl <= 0:
            continue
        if _rdl <= _rd_hi:          # first OTM far-CE at ≤50% of sold premium
            _rd_far_ce_strike = int(_rds)
            _rd_far_ce_ltp    = _rdl
            _rd_in_range      = _rd_lo <= _rdl <= _rd_hi
            break

_rd_ratio_pct  = (_rd_far_ce_ltp / _rd_atm_ce_ltp * 100) if _rd_atm_ce_ltp else 0
_rd_net        = _rd_atm_ce_ltp - 2 * _rd_far_ce_ltp   # +ve = net credit, -ve = net debit
_rd_net_lbl    = "NET CREDIT" if _rd_net >= 0 else "NET DEBIT"
_rd_net_col    = "var(--bull)" if _rd_net >= 0 else "var(--bear)"

# ── Position sizing: capital slider → lot count capped by 1% daily-loss rule ──
_rd_capital        = st.session_state.get("rd_capital", 500_000)   # default ₹5L
# Local T and sigma — _T_near_std / _T_far_std / _sigma_std defined much later in file
_rd_sigma     = (_eff_vix / 100.0) if _vix_ok else 0.15
_rd_T_near    = max(_days_to_exp, 1) / 365.0
_rd_T_far     = max((datetime.strptime(far_exp, "%Y-%m-%d").date() - now.date()).days, 1) / 365.0

# Greeks for 1 unit (short 1 near ATM CE + long 2 far OTM CE)
_rd_near_delta = bs_delta(spot, _rd_use_atm,       _rd_T_near, _rd_sigma, "CE") if spot else 0.50
_rd_far_delta  = bs_delta(spot, _rd_far_ce_strike, _rd_T_far,  _rd_sigma, "CE") if spot else 0.25
_rd_near_gamma = bs_gamma(spot, _rd_use_atm,       _rd_T_near, _rd_sigma)        if spot else 0.0
_rd_far_gamma  = bs_gamma(spot, _rd_far_ce_strike, _rd_T_far,  _rd_sigma)        if spot else 0.0

_rd_net_delta  = -_rd_near_delta + 2 * _rd_far_delta    # net direction per unit
_rd_net_gamma  = -_rd_near_gamma + 2 * _rd_far_gamma    # net gamma per unit (usually negative)

# Worst-case intraday loss for 1 unit — DIRECTIONAL (not abs-based):
# ratio diagonal is net SHORT delta, so UP moves are the risk.
# Use min(P_up, P_down) rather than abs so buying long calls CAN reduce loss.
_rd_daily_move    = _daily_pts if (_daily_pts and _daily_pts > 0) else (spot * 0.01 if spot else 100)
_rd_p_up          =  _rd_net_delta * _rd_daily_move + 0.5 * _rd_net_gamma * _rd_daily_move**2
_rd_p_down        = -_rd_net_delta * _rd_daily_move + 0.5 * _rd_net_gamma * _rd_daily_move**2
_rd_loss_per_unit = max(0.0, -min(_rd_p_up, _rd_p_down)) * LOT_SIZE
_rd_loss_per_unit = max(_rd_loss_per_unit, 1.0)   # guard against divide-by-zero

# Premium-based margin: lot_size × sold_premium × 7
# e.g. 65 × 105 × 7 = ₹47,775/lot → ₹3L / ₹47,775 = 6 lots
# Floor: 2% of notional so margin doesn't collapse when premium is tiny
_rd_margin_per_unit = max(
    LOT_SIZE * _rd_atm_ce_ltp * 7,
    spot * LOT_SIZE * 0.02 if spot else 30_000
)
_rd_margin_per_unit = max(_rd_margin_per_unit, 1.0)

_rd_max_daily_loss   = _rd_capital * 0.01          # 1% of capital
_rd_lots_by_risk     = max(1, int(_rd_max_daily_loss / _rd_loss_per_unit))
_rd_lots_by_capital  = max(1, int(_rd_capital / _rd_margin_per_unit))
# Capital is the primary driver; wing hedge brings loss ≤ 1%
_rd_lots             = _rd_lots_by_capital

# Projected daily loss at chosen lot count
_rd_proj_loss  = _rd_loss_per_unit * _rd_lots
_rd_proj_pct   = (_rd_proj_loss / _rd_capital * 100) if _rd_capital else 0

# ─────────────────────────────────────────────
# MARKET SNAPSHOT
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>📊 Market Snapshot</div>", unsafe_allow_html=True)

# ── Square-of-Square-Root levels (Gann-style pivot grid) ──────────────────────
import math as _sqmath
_sq_base   = int(spot) if spot else 77763
_sq_root   = round(_sqmath.sqrt(_sq_base))          # nearest integer √
_sq_levels = []
for _sq_i in range(-3, 4):
    _sq_n   = _sq_root + _sq_i
    _sq_val = _sq_n * _sq_n
    if _sq_val % 2 == 0:                             # must be odd
        _sq_val += 1
    _sq_levels.append((_sq_n, _sq_val))

# Build horizontal row of value pills only
_sq_pills = ""
for _sq_n, _sq_val in _sq_levels:
    _sq_is_pivot = (_sq_n == _sq_root)
    _sq_is_above = (_sq_val > spot) if spot else False
    if _sq_is_pivot:
        _sq_bord = "rgba(255,201,64,0.8)"; _sq_col = "var(--gold)"; _sq_bg = "rgba(255,201,64,0.15)"
    elif _sq_is_above:
        _sq_bord = "rgba(255,59,48,0.45)"; _sq_col = "var(--bear)"; _sq_bg = "rgba(255,59,48,0.07)"
    else:
        _sq_bord = "rgba(50,215,75,0.45)"; _sq_col = "var(--bull)"; _sq_bg = "rgba(50,215,75,0.07)"
    _sq_pills += (
        f"<span style='display:inline-block;padding:3px 8px;"
        f"background:{_sq_bg};border:1px solid {_sq_bord};border-radius:20px;"
        f"font-family:var(--mono);font-size:13px;font-weight:700;color:{_sq_col};"
        f"{'box-shadow:0 0 6px rgba(255,201,64,0.4);' if _sq_is_pivot else ''}'>"
        f"{_sq_val:,}"
        f"{'&nbsp;◆' if _sq_is_pivot else ''}"
        f"</span>"
    )

# ── End of square-root levels ──────────────────────────────────────────────────

# ── Futures build-up ──────────────────────────────────────────────────────────
# Find current-month and next-month monthly expiry from all_exp
# Monthly expiry = last Thursday of each month → latest expiry date in that calendar month
def _monthly_expiries_from_all(exp_list, n=2):
    _today = datetime.now(IST).date()
    _buckets = {}
    for _e in exp_list:
        try:
            _d = datetime.strptime(_e, "%Y-%m-%d").date()
            if _d >= _today:
                _ym = (_d.year, _d.month)
                if _ym not in _buckets or _d > _buckets[_ym]:
                    _buckets[_ym] = _d
        except Exception:
            pass
    return [str(v) for v in sorted(_buckets.values())[:n]]

_fut_expiries = _monthly_expiries_from_all(all_exp, n=2)
_fut_data, _fut_err = fetch_futures_buildup(token, _fut_expiries)

_BUILDUP_META = {
    "Long Build-up":   ("var(--bull)",  "▲", "rgba(50,215,75,0.10)",  "rgba(50,215,75,0.35)"),
    "Short Covering":  ("var(--bull)",  "↑", "rgba(50,215,75,0.06)",  "rgba(50,215,75,0.25)"),
    "Short Build-up":  ("var(--bear)",  "▼", "rgba(255,59,48,0.10)",  "rgba(255,59,48,0.35)"),
    "Long Unwinding":  ("var(--bear)",  "↓", "rgba(255,59,48,0.06)",  "rgba(255,59,48,0.25)"),
}

_fut_html = ""
if _fut_data:
    _fut_labels = ["CUR MONTH", "NEXT MONTH"]
    for _fi, _frow in enumerate(_fut_data[:2]):
        _fb   = _frow["buildup"]
        _fc, _farrow, _fbg, _fbord = _BUILDUP_META.get(_fb, ("var(--muted)", "·", "transparent", "var(--border)"))
        _fpx  = f"{'+'if _frow['px_chg_pct']>=0 else ''}{_frow['px_chg_pct']:.2f}%"
        _foi  = f"{'+'if _frow['oi_chg_pct']>=0 else ''}{_frow['oi_chg_pct']:.1f}%"
        _fexp = _frow['expiry']
        _fsrc = _frow.get("source", "")
        if _fsrc == "live":
            _src_badge = "<span style='font-size:7px;padding:1px 4px;border-radius:3px;background:rgba(50,215,75,0.18);color:#32d74b;font-weight:700;'>📡 LIVE</span>"
        elif _fsrc == "hist":
            _src_badge = "<span style='font-size:7px;padding:1px 4px;border-radius:3px;background:rgba(255,159,10,0.18);color:#ff9f0a;font-weight:700;'>📅 HIST</span>"
        else:
            _src_badge = ""
        _fut_html += (
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:4px 8px;margin-top:4px;"
            f"background:{_fbg};border:1px solid {_fbord};border-radius:5px;'>"
            f"<div>"
            f"<div style='font-size:8px;color:var(--muted);'>{_frow.get('label', _fut_labels[_fi])} &nbsp;<span style='color:var(--muted);font-size:7px;'>{_fexp}</span> &nbsp;{_src_badge}</div>"
            f"<div style='font-size:11px;font-weight:700;font-family:var(--mono);color:{_fc};'>"
            f"{_farrow} {_fb}</div>"
            f"</div>"
            f"<div style='text-align:right;font-family:var(--mono);font-size:10px;'>"
            f"<div style='color:var(--muted);'>LTP <span style='color:{_fc};font-weight:700;'>₹{_frow['ltp']:,.1f}</span> "
            f"<span style='color:{_fc};font-size:9px;'>({_fpx})</span></div>"
            f"<div style='color:var(--muted);font-size:9px;'>OI chg <span style='color:{_fc};'>{_foi}</span></div>"
            f"</div>"
            f"</div>"
        )
# ── End futures build-up ──────────────────────────────────────────────────────

# Row 1 — Spot + ATM
r1c1, r1c2 = st.columns(2)
with r1c1:
    st.markdown(
        f"<div class='card'>"
        f"<div class='lbl'>NIFTY Spot</div>"
        f"<div class='val-big'>₹{spot:,.2f}</div>"
        # √² levels
        f"<div style='margin-top:8px;border-top:1px solid var(--border);padding-top:7px;'>"
        f"<div style='font-size:8px;color:var(--muted);margin-bottom:5px;'>√² LEVELS &nbsp;·&nbsp; √{_sq_base}={_sq_root} &nbsp;"
        f"<span style='color:var(--bull);'>● sup</span> &nbsp;"
        f"<span style='color:var(--bear);'>● res</span> &nbsp;"
        f"<span style='color:var(--gold);'>◆ pivot</span></div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:4px;'>{_sq_pills}</div>"
        f"</div>"
        # Futures build-up (always show section; show error hint if no data)
        + f"<div style='margin-top:8px;border-top:1px solid var(--border);padding-top:7px;'>"
        + f"<div style='font-size:8px;font-weight:700;letter-spacing:.07em;color:var(--muted);margin-bottom:4px;'>FUTURES BUILD-UP</div>"
        + (
            _fut_html if _fut_html
            else f"<span style='font-size:9px;color:var(--muted);font-style:italic;'>"
                 f"{'—' if not _fut_err else str(_fut_err)[:120]}</span>"
          )
        + f"</div>"
        + f"</div>",
        unsafe_allow_html=True
    )
with r1c2:
    _atm_ce_ltp = near_ce.get(float(atm), 0)
    _atm_pe_ltp = near_pe.get(float(atm), 0)
    def _fmt_v(v): return f"₹{v:.1f}" if v else "—"
    def _fmt_vol(v): return f"{int(v):,}" if v else "—"
    def _ltp_vs_vwap(ltp, vwap):
        if not vwap or not ltp: return ""
        return "<span style='color:var(--bull);'>▲</span>" if ltp > vwap else "<span style='color:var(--bear);'>▼</span>"

    # Straddle sum vs VWAP sum → market regime
    _straddle_ltp  = _atm_ce_ltp + _atm_pe_ltp
    _straddle_vwap = (_atm_ce_vwap + _atm_pe_vwap) if (_atm_ce_vwap and _atm_pe_vwap) else None
    if _straddle_vwap:
        _is_sideways = _straddle_ltp < _straddle_vwap
        if _is_sideways:
            _regime_label = "SIDEWAYS"
            _regime_col   = "var(--gold)"
            _regime_bg    = "var(--gold-dim)"
            _regime_icon  = "↔"
        else:
            # Direction: compare how much each leg has grown above its VWAP
            _ce_mom = ((_atm_ce_ltp - _atm_ce_vwap) / _atm_ce_vwap * 100) if _atm_ce_vwap else 0
            _pe_mom = ((_atm_pe_ltp - _atm_pe_vwap) / _atm_pe_vwap * 100) if _atm_pe_vwap else 0
            if _ce_mom >= _pe_mom:   # CE growing more → market trending UP
                _regime_label = "TRENDING"
                _regime_col   = "var(--bull)"
                _regime_bg    = "rgba(50,215,75,0.12)"
                _regime_icon  = "↗"
            else:                    # PE growing more → market trending DOWN
                _regime_label = "TRENDING"
                _regime_col   = "var(--bear)"
                _regime_bg    = "var(--bear-dim)"
                _regime_icon  = "↘"
    else:
        pass

    st.markdown(
        f"<div class='card card-gold'>"
        f"<div class='lbl'>ATM Strike</div>"
        f"<div class='val-big val-gold' style='margin-bottom:6px;'>{atm}</div>"
        f"<div style='display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:12px;'>"
        # CE column
        f"<div style='flex:1;'>"
        f"<div style='font-size:10px;color:var(--ce);letter-spacing:1px;font-weight:700;margin-bottom:3px;'>CE</div>"
        f"<div style='color:var(--ce);font-size:14px;font-weight:700;'>₹{_atm_ce_ltp:.1f} {_ltp_vs_vwap(_atm_ce_ltp, _atm_ce_vwap)}</div>"
        f"<div style='color:var(--muted);font-size:10px;'>VWAP {_fmt_v(_atm_ce_vwap)}</div>"
        f"<div style='color:var(--muted);font-size:10px;'>Vol {_fmt_vol(_atm_ce_vol)}</div>"
        f"</div>"
        # Centre regime badge
        + (
            f"<div style='text-align:center;padding:4px 6px;border-radius:6px;"
            f"background:{_regime_bg};border:1px solid {_regime_col};min-width:64px;'>"
            f"<div style='color:{_regime_col};font-size:14px;line-height:1;'>{_regime_icon}</div>"
            f"<div style='color:{_regime_col};font-size:9px;font-weight:700;letter-spacing:1px;'>{_regime_label}</div>"
            f"<div style='color:var(--muted);font-size:8px;margin-top:2px;'>₹{_straddle_ltp:.0f} vs ₹{_straddle_vwap:.0f}</div>"
            f"</div>"
            if _straddle_vwap else
            f"<div style='min-width:64px;text-align:center;color:var(--muted);font-size:10px;'>—</div>"
        )
        # PE column
        + f"<div style='flex:1;text-align:right;'>"
        f"<div style='font-size:10px;color:var(--pe);letter-spacing:1px;font-weight:700;margin-bottom:3px;'>PE</div>"
        f"<div style='color:var(--pe);font-size:14px;font-weight:700;'>₹{_atm_pe_ltp:.1f} {_ltp_vs_vwap(_atm_pe_ltp, _atm_pe_vwap)}</div>"
        f"<div style='color:var(--muted);font-size:10px;'>VWAP {_fmt_v(_atm_pe_vwap)}</div>"
        f"<div style='color:var(--muted);font-size:10px;'>Vol {_fmt_vol(_atm_pe_vol)}</div>"
        f"</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True
    )

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

# Far chain PCR (no SPCL/VIX adjustment needed)
try:
    _far_pcr, _far_pcr_chg, _far_tot_ce_oi, _far_tot_pe_oi, _, _far_atm_ce, _far_atm_pe, (_far_sent_lbl, _far_sent_col) = \
        calc_pcr_spcl(far_ce, far_pe, far_ce_oi, far_pe_oi,
                      far_ce_oi_chg, far_pe_oi_chg, atm)
except Exception:
    _far_pcr = _far_pcr_chg = _far_tot_ce_oi = _far_tot_pe_oi = _far_atm_ce = _far_atm_pe = 0.0
    _far_sent_lbl, _far_sent_col = "N/A", "var(--muted)"

_prev_pcr = st.session_state.get("prev_pcr", _pcr)
st.session_state["prev_pcr"] = _pcr
_pcr_delta = _pcr - _prev_pcr
_pcr_has_oi = _tot_ce_oi > 0

# ATM-specific OI (single strike)
_atm_ce_oi     = near_ce_oi.get(float(atm), 0)
_atm_pe_oi     = near_pe_oi.get(float(atm), 0)
_atm_pcr       = (_atm_pe_oi / _atm_ce_oi) if _atm_ce_oi > 0 else 0.0
_atm_has_oi    = _atm_ce_oi > 0
_far_atm_ce_oi = far_ce_oi.get(float(atm), 0)
_far_atm_pe_oi = far_pe_oi.get(float(atm), 0)
_far_atm_pcr   = (_far_atm_pe_oi / _far_atm_ce_oi) if _far_atm_ce_oi > 0 else 0.0

# ── OI Buildup / Short Covering classification ────────────────────────────
# Uses intraday spot direction vs NIFTY day open + net OI change across range
_spot_chg       = (spot - _nifty_day_open) if (_nifty_day_open and spot) else 0.0
_spot_up        = _spot_chg >  20   # +20pt threshold to filter noise
_spot_dn        = _spot_chg < -20
_spot_flat      = not _spot_up and not _spot_dn

# Net OI change across ATM±4 strikes (session-tracked: current - day-start baseline)
_net_ce_oi_chg  = sum(_intra_ce_oi_chg.get(float(atm + i*STEP), 0) for i in range(0, 5))
_net_pe_oi_chg  = sum(_intra_pe_oi_chg.get(float(atm - i*STEP), 0) for i in range(0, 5))

# ATM-specific net OI change
_atm_ce_oi_chg  = _intra_ce_oi_chg.get(float(atm), 0)
_atm_pe_oi_chg  = _intra_pe_oi_chg.get(float(atm), 0)

def _oi_signal(oi_chg, opt_type, spot_up, spot_dn):
    """
    Returns (label, color) using OI direction × spot direction.
    CE: price moves WITH spot. PE: price moves AGAINST spot.
    OI↑ + price↑ → Long Buildup (buyers dominant)
    OI↑ + price↓ → Short Buildup (writers dominant)
    OI↓ + price↑ → Short Covering (shorts buying back)
    OI↓ + price↓ → Long Unwinding (longs exiting)
    """
    if not spot_up and not spot_dn:
        return ("—", "var(--muted)")
    oi_up = oi_chg > 0
    oi_dn = oi_chg < 0
    if opt_type == "CE":
        price_up = spot_up
    else:          # PE price moves inverse to spot
        price_up = spot_dn
    if oi_up and price_up:  return ("Long Buildup",   "#00e676")
    if oi_up and not price_up: return ("Short Buildup",  "#ff5252")
    if oi_dn and price_up:  return ("Short Covering", "#69f0ae")
    return                         ("Long Unwinding",  "#ff8a65")

_ce_signal_lbl, _ce_signal_col = _oi_signal(_net_ce_oi_chg, "CE", _spot_up, _spot_dn)
_pe_signal_lbl, _pe_signal_col = _oi_signal(_net_pe_oi_chg, "PE", _spot_up, _spot_dn)
_atm_ce_sig_lbl, _atm_ce_sig_col = _oi_signal(_atm_ce_oi_chg, "CE", _spot_up, _spot_dn)
_atm_pe_sig_lbl, _atm_pe_sig_col = _oi_signal(_atm_pe_oi_chg, "PE", _spot_up, _spot_dn)

# SPP (UIP concept) — computed ONCE per calendar day per instrument+expiry.
# Cache is THREE-LEVEL: session_state → GitHub JSON → local disk fallback.
# Key: "YYYY-MM-DD|INSTRUMENT|expiry"  — all historical entries preserved in GitHub.
_today_str  = now.date().isoformat()

# ① Bootstrap session_state cache from GitHub (or disk fallback) on first page load
if "spp_cache_loaded" not in st.session_state:
    _gh_store, _gh_spp_sha = _spp_gh_get(_gh_tok_early)
    if _gh_store:
        st.session_state["spp_cache"] = _gh_store
    else:
        # GitHub unavailable — fall back to local disk
        st.session_state["spp_cache"] = _spp_load_disk()
    st.session_state["spp_gh_sha"] = _gh_spp_sha   # sha needed for updates
    st.session_state["spp_cache_loaded"] = True

_spp_store  = st.session_state["spp_cache"]          # live reference
_spp_key    = f"{_today_str}|{_inst_choice}|{near_exp}"
_spp_cached = _spp_store.get(_spp_key, {})

# Invalidate cache if it was computed before 09:05 IST and market has since opened
_spp_open_today = now.replace(hour=9, minute=5, second=0, microsecond=0)
if _spp_cached:
    try:
        _spp_cached_dt = datetime.fromisoformat(_spp_cached.get("ts", "")).replace(tzinfo=IST)
    except Exception:
        _spp_cached_dt = None
    if _spp_cached_dt is None or (_spp_cached_dt < _spp_open_today and now >= _spp_open_today):
        del _spp_store[_spp_key]
        _spp_cached = {}

if _spp_cached:
    # Hit — use cached value (no API call, no spinner)
    _spp        = _spp_cached["spp"]
    _spp_atm    = _spp_cached["atm"]
    _spp_ce_h   = _spp_cached["ce_h"]
    _spp_ce_l   = _spp_cached["ce_l"]
    _spp_pe_h   = _spp_cached["pe_h"]
    _spp_pe_l   = _spp_cached["pe_l"]
    _spp_ce_oi_L= _spp_cached["ce_oi_L"]
    _spp_pe_oi_L= _spp_cached["pe_oi_L"]
    _spp_src    = _spp_cached["src"]
else:
    # Miss — compute once for this instrument+expiry today
    _spp_atm = _open_atm if _open_atm else atm
    with st.spinner(f"Computing SPP for {_inst_choice} (open ATM={_spp_atm})…"):
        _spp, _spp_ce_h, _spp_ce_l, _spp_pe_h, _spp_pe_l, _spp_ce_oi_L, _spp_pe_oi_L, _spp_src = \
            calc_spp(near_exp, _spp_atm, tok=token, chain_data=near_raw)
    if _spp is not None:
        _entry = {
            "spp": _spp, "atm": _spp_atm,
            "ce_h": _spp_ce_h, "ce_l": _spp_ce_l,
            "pe_h": _spp_pe_h, "pe_l": _spp_pe_l,
            "ce_oi_L": _spp_ce_oi_L, "pe_oi_L": _spp_pe_oi_L,
            "src": _spp_src,
            "ts": now.isoformat(),
        }
        # ② Store in session_state (fast path for subsequent refreshes this session)
        _spp_store[_spp_key] = _entry
        # ③ Persist to GitHub (survives cloud restarts; accumulates historical data)
        _cur_sha = st.session_state.get("spp_gh_sha")
        _ok = _spp_gh_put(_gh_tok_early, _spp_store, _cur_sha)
        if _ok:
            # Re-fetch sha so next write doesn't conflict
            _, _new_sha = _spp_gh_get(_gh_tok_early)
            st.session_state["spp_gh_sha"] = _new_sha
        else:
            # GitHub write failed — fall back to disk
            _spp_save_disk(_spp_store)

# ── PCR logging to GitHub CSV (throttled: market hours, once per refresh interval) ─────
_gh_tok = _gh_tok_early   # already read at top of main body

_pcr_log_ok = (
    _gh_tok
    and mkt_open
    and _pcr_has_oi
    and (time.time() - st.session_state.get("_pcr_last_write", 0) > PCR_LOG_INTERVAL)
)
if _pcr_log_ok:
    _ts_str   = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    _date_str = datetime.now(IST).strftime("%Y-%m-%d")
    _pcr_rows = [
        {
            "timestamp":   _ts_str,
            "date":        _date_str,
            "expiry_type": "near",
            "expiry":      near_exp,
            "spot":        f"{spot:.2f}",
            "atm":         atm,
            "pcr_range":   f"{_pcr:.4f}",
            "pcr_atm":     f"{_atm_pcr:.4f}",
            "ce_oi_L":     f"{_tot_ce_oi/1e5:.3f}",
            "pe_oi_L":     f"{_tot_pe_oi/1e5:.3f}",
            "atm_ce_oi_L": f"{_atm_ce_oi/1e5:.3f}",
            "atm_pe_oi_L": f"{_atm_pe_oi/1e5:.3f}",
            "pcr_chg":     f"{_pcr_chg:.4f}",
            "vix_open":    f"{_open_vix:.2f}" if _vix_ok else "",
            "vix_curr":    f"{_curr_vix:.2f}" if _vix_ok else "",
            "spcl":        f"{_spcl:.4f}" if _spcl else "",
        },
        {
            "timestamp":   _ts_str,
            "date":        _date_str,
            "expiry_type": "far",
            "expiry":      far_exp,
            "spot":        f"{spot:.2f}",
            "atm":         atm,
            "pcr_range":   f"{_far_pcr:.4f}",
            "pcr_atm":     f"{_far_atm_pcr:.4f}",
            "ce_oi_L":     f"{_far_tot_ce_oi/1e5:.3f}",
            "pe_oi_L":     f"{_far_tot_pe_oi/1e5:.3f}",
            "atm_ce_oi_L": f"{_far_atm_ce_oi/1e5:.3f}",
            "atm_pe_oi_L": f"{_far_atm_pe_oi/1e5:.3f}",
            "pcr_chg":     f"{_far_pcr_chg:.4f}",
            "vix_open":    f"{_open_vix:.2f}" if _vix_ok else "",
            "vix_curr":    f"{_curr_vix:.2f}" if _vix_ok else "",
            "spcl":        "",
        },
    ]
    if append_pcr_log(_gh_tok, _pcr_rows):
        st.session_state["_pcr_last_write"] = time.time()

# Load PCR history into session cache early (used by mini-table below)
if _gh_tok:
    _hist_age = time.time() - st.session_state.get("_pcr_hist_ts", 0)
    if _hist_age > 900 or "pcr_hist_rows" not in st.session_state:
        st.session_state["pcr_hist_rows"] = load_pcr_history(_gh_tok)
        st.session_state["_pcr_hist_ts"]  = time.time()

pb1, pb2, pb3, pb4 = st.columns(4)
with pb1:
    if _pcr_has_oi:
        _pcr_dir_col = "var(--bull)" if _pcr_delta > 0.01 else ("var(--bear)" if _pcr_delta < -0.01 else "var(--muted)")
        _pcr_dir_sym = "↑" if _pcr_delta > 0.01 else ("↓" if _pcr_delta < -0.01 else "→")
        # ATM PCR pill
        _atm_pcr_str = f"{_atm_pcr:.2f}" if _atm_has_oi else "—"
        _atm_pcr_col = "var(--bull)" if _atm_pcr >= 1.1 else ("var(--bear)" if _atm_pcr < 0.9 and _atm_has_oi else "var(--gold)")
        st.markdown(
            f"<div class='card' style='border-left:4px solid {_sent_col};'>"
            f"<div class='lbl'>PCR OI &nbsp;·&nbsp; ATM±4 strikes</div>"
            f"<div style='display:flex;align-items:baseline;gap:10px;margin:.25rem 0;'>"
            f"<span class='val-big' style='color:{_sent_col};'>{_pcr:.2f}</span>"
            f"<span style='font-family:var(--mono);font-size:11px;font-weight:700;"
            f"background:{_sent_col};color:var(--text-inv);border-radius:3px;padding:2px 7px;'>{_sent_lbl}</span>"
            f"</div>"
            f"<div class='lbl'>"
            f"<span style='color:{_pcr_dir_col};font-weight:700;'>{_pcr_chg:.2f}{_pcr_dir_sym}{_pcr:.2f}</span>"
            f" &nbsp;·&nbsp; CE:ATM+4 | PE:ATM-4<br>"
            f"CE OI <b>{_tot_ce_oi/1e5:.1f}L</b> "
            f"<span style='font-size:9px;font-weight:700;color:{_ce_signal_col};'>[{_ce_signal_lbl}]</span>"
            f" &nbsp;·&nbsp; PE OI <b>{_tot_pe_oi/1e5:.1f}L</b> "
            f"<span style='font-size:9px;font-weight:700;color:{_pe_signal_col};'>[{_pe_signal_lbl}]</span>"
            f"</div>"
            f"<div style='margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--border);'>"
            f"<span class='lbl'>ATM <span class='strike-pill-ce'>{atm}</span> PCR &nbsp;</span>"
            f"<span style='font-family:var(--mono);font-size:14px;font-weight:700;color:{_atm_pcr_col};'>{_atm_pcr_str}</span>"
            f"<span class='lbl'> &nbsp;CE {_atm_ce_oi/1e5:.1f}L "
            f"<span style='font-size:9px;font-weight:700;color:{_atm_ce_sig_col};'>[{_atm_ce_sig_lbl}]</span>"
            f" / PE {_atm_pe_oi/1e5:.1f}L "
            f"<span style='font-size:9px;font-weight:700;color:{_atm_pe_sig_col};'>[{_atm_pe_sig_lbl}]</span>"
            f"</span>"
            f"</div></div>",
            unsafe_allow_html=True)

        # ── Last 10 PCR mini-table ────────────────────────────────────────
        _mini_rows = [
            r for r in st.session_state.get("pcr_hist_rows", [])
            if r.get("expiry_type") == "near"
        ]
        _mini_rows = sorted(_mini_rows, key=lambda r: r.get("timestamp", ""), reverse=True)[:10]
        if _mini_rows:
            _tbl_html = (
                "<div style='margin-top:.6rem;padding-top:.5rem;border-top:1px solid var(--border);'>"
                "<div class='lbl' style='margin-bottom:.3rem;'>🕐 Last 10 PCR snapshots (near)</div>"
                "<table style='width:100%;border-collapse:collapse;font-family:var(--mono);font-size:10px;'>"
                "<tr style='color:var(--muted);text-align:right;'>"
                "<th style='text-align:left;font-weight:500;'>Time</th>"
                "<th>PCR</th><th>ATM PCR</th><th>Spot</th></tr>"
            )
            for _mr in _mini_rows:
                try:
                    _mr_pcr     = float(_mr.get("pcr_range", 0))
                    _mr_atm_pcr = float(_mr.get("pcr_atm", 0))
                    _mr_spot    = float(_mr.get("spot", 0))
                    _mr_time    = _mr.get("timestamp", "")[-5:]   # HH:MM
                    _mr_col     = "var(--bull)" if _mr_pcr >= 1.1 else ("var(--bear)" if _mr_pcr < 0.9 else "var(--gold)")
                    _tbl_html += (
                        f"<tr style='text-align:right;border-top:1px solid var(--border);'>"
                        f"<td style='text-align:left;color:var(--muted);'>{_mr_time}</td>"
                        f"<td style='color:{_mr_col};font-weight:700;'>{_mr_pcr:.2f}</td>"
                        f"<td style='color:var(--muted);'>{_mr_atm_pcr:.2f}</td>"
                        f"<td style='color:var(--muted);'>{_mr_spot:,.0f}</td>"
                        f"</tr>"
                    )
                except Exception:
                    continue
            _tbl_html += "</table></div>"
            st.markdown(_tbl_html, unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div class='card'><div class='lbl'>PCR OI</div>"
            f"<div class='val-big' style='color:var(--muted);'>N/A</div>"
            f"<div class='lbl'>OI not available in feed</div></div>",
            unsafe_allow_html=True)
with pb2:
    # √CE vs √PE signal — sum of 3 strikes each side, then √
    # CE: ATM, ATM+1, ATM+2  |  PE: ATM, ATM-1, ATM-2
    # Direction: √PE > √CE → BEARISH  |  √CE > √PE → BULLISH
    # Threshold: VIX per-day expected move = VIX / √252
    # If diff% >= vix_daily_expected% → EXPLOSIVE move, else NORMAL
    _ce_sum   = sum(near_ce.get(float(atm + i * STEP), 0) for i in range(3))
    _pe_sum   = sum(near_pe.get(float(atm - i * STEP), 0) for i in range(3))
    _sqrt_ce  = math.sqrt(_ce_sum) if _ce_sum > 0 else 0
    _sqrt_pe  = math.sqrt(_pe_sum) if _pe_sum > 0 else 0

    # VIX per-day expected % move  (annualised VIX / √252 trading days)
    _vix_daily_exp = (
        (_curr_vix / math.sqrt(252))
        if (_curr_vix and _curr_vix > 0)
        else 1.0
    )
    # % difference between √PE and √CE relative to the smaller value
    _sqrt_base     = min(_sqrt_ce, _sqrt_pe) if min(_sqrt_ce, _sqrt_pe) > 0 else 1
    _sqrt_diff_pct = abs(_sqrt_pe - _sqrt_ce) / _sqrt_base * 100

    # Direction
    if _sqrt_pe > _sqrt_ce:
        _sqrt_sig = "BEARISH"
    elif _sqrt_ce > _sqrt_pe:
        _sqrt_sig = "BULLISH"
    else:
        _sqrt_sig = "NEUTRAL"

    # Explosive vs Normal qualifier
    _is_explosive  = _sqrt_diff_pct >= _vix_daily_exp
    _move_tag      = "💥 EXPLOSIVE" if _is_explosive else "NORMAL"
    _move_tag_col  = ("var(--bear)" if _sqrt_sig == "BEARISH"
                      else "var(--bull)" if _sqrt_sig == "BULLISH"
                      else "var(--muted)")

    _sqrt_arrow = "▼" if _sqrt_sig == "BEARISH" else ("▲" if _sqrt_sig == "BULLISH" else "→")
    _sqrt_col   = "var(--bear)" if _sqrt_sig == "BEARISH" else ("var(--bull)" if _sqrt_sig == "BULLISH" else "var(--muted)")
    _sqrt_expr  = (
        f"√PE {_sqrt_pe:.2f} &gt; √CE {_sqrt_ce:.2f} · Δ{_sqrt_diff_pct:.1f}% vs VIX/day {_vix_daily_exp:.1f}%"
        if _sqrt_sig == "BEARISH"
        else f"√CE {_sqrt_ce:.2f} &gt; √PE {_sqrt_pe:.2f} · Δ{_sqrt_diff_pct:.1f}% vs VIX/day {_vix_daily_exp:.1f}%"
        if _sqrt_sig == "BULLISH"
        else f"√PE {_sqrt_pe:.2f} = √CE {_sqrt_ce:.2f}"
    )

    if _spcl is not None:
        st.markdown(
            f"<div class='card card-gold'>"
            f"<div class='lbl'>SPCL VAL &nbsp;·&nbsp; (√(CE+PE)×π/2 adj VIX)</div>"
            f"<div class='val-big val-gold'>{_spcl:.2f}</div>"
            f"<div class='lbl'>"
            f"ATM CE <b style='color:var(--ce);'>₹{_atm_ce:.2f}</b> &nbsp;+&nbsp; "
            f"ATM PE <b style='color:var(--pe);'>₹{_atm_pe:.2f}</b> &nbsp;·&nbsp; "
            f"<span class='strike-pill-ce'>{atm}</span>"
            f"</div>"
            f"<div style='margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--border);'>"
            f"<span style='font-family:var(--mono);font-size:12px;font-weight:700;color:{_sqrt_col};'>"
            f"{_sqrt_arrow} {_sqrt_sig}</span>"
            f"<span style='font-family:var(--mono);font-size:10px;font-weight:700;color:{_move_tag_col};margin-left:6px;'>{_move_tag}</span>"
            f"<div style='font-family:var(--mono);font-size:9px;color:var(--muted);margin-top:2px;'>{_sqrt_expr}</div>"
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
            f"</div>"
            f"<div style='margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--border);'>"
            f"<span style='font-family:var(--mono);font-size:12px;font-weight:700;color:{_sqrt_col};'>"
            f"{_sqrt_arrow} {_sqrt_sig}</span>"
            f"<span style='font-family:var(--mono);font-size:10px;font-weight:700;color:{_move_tag_col};margin-left:6px;'>{_move_tag}</span>"
            f"<div style='font-family:var(--mono);font-size:9px;color:var(--muted);margin-top:2px;'>{_sqrt_expr}</div>"
            f"</div></div>",
            unsafe_allow_html=True)
with pb3:
    _sell_ce_ltp2 = near_ce.get(float(sell_ce_strike), 0)
    _sell_pe_ltp2 = near_pe.get(float(sell_pe_strike), 0)
    _strangle_val = _sell_ce_ltp2 + _sell_pe_ltp2

    # ── Method 1: 1σ Range strangle ──────────────────────────────────────────
    _range_strangle_val = ((_ltp_hi_1s or 0) + (_ltp_lo_1s or 0)) if _range_hi_1s else None

    # ── Method 2: VIX premium strangle (current sell strikes) ─────────────────
    if _vix_ok and _vp_tgt_l:
        _vix_strangle_lo = _vp_tgt_l * 2
        _vix_strangle_hi = (_vp_tgt_h * 2) if _vp_tgt_h else None
        _vix_str_label   = f"₹{_vix_strangle_lo:.0f}–{_vix_strangle_hi:.0f}" if _vix_strangle_hi else f"₹{_vix_strangle_lo:.0f}+"
        _in_range = _vix_strangle_lo <= _strangle_val <= (_vix_strangle_hi or float("inf"))
        _above    = _strangle_val > (_vix_strangle_hi or _vix_strangle_lo)
        _tgt_col  = "var(--bull)" if _in_range else ("var(--bear)" if _above else "var(--gold)")
        _tgt_icon = "✓" if _in_range else ("↑" if _above else "↓")
    else:
        _vix_str_label = _tgt_col = _tgt_icon = None

    def _pill_ce(s): return f"<span class='strike-pill-ce'>{s}</span>"
    def _pill_pe(s): return f"<span class='strike-pill'>{s}</span>"

    # ── Pre-compute colour/text vars for diagonal ticket ─────────────────────
    if _3lot_sell_total:
        _buy_val_col  = "var(--bull)" if _buy_ok else "var(--bear)"
        _buy_chk_col  = "var(--bull)" if _buy_ok else "var(--bear)"
        if _buy_ok:
            _buy_status = "✓ 80–140% of sold"
        elif _far_atm_straddle > _far_tgt_hi:
            _buy_status = "↑ above 140% · nearest to sold"
        elif _far_atm_straddle > 0:
            _buy_status = "↓ below 80% · nearest to sold"
        else:
            _buy_status = "✗ no far data"
        _ratio_txt    = f"{_buy_ratio_pct:.0f}%" if _buy_ratio_pct else "—"
        _net_debit    = _far_atm_straddle - _3lot_sell_total
        _3lot_ce_total = 3 * _3lot_ce_ltp
        _3lot_pe_total = 3 * _3lot_pe_ltp
        _diag_ok = True
    else:
        _diag_ok = False

    # ── Reference info bar (small, top of card) ───────────────────────────────
    _ref_bar = ""
    if _range_strangle_val:
        _ref_bar += (
            f"<span style='color:var(--muted);'>1σ ref:</span> "
            f"CE {_pill_ce(_range_hi_1s)} + PE {_pill_pe(_range_lo_1s)} "
            f"<span style='font-family:var(--mono);'>₹{_range_strangle_val:.0f}</span>"
        )
    if _vix_str_label:
        _ref_bar += (
            f"&nbsp;&nbsp;|&nbsp;&nbsp;"
            f"<span style='color:var(--muted);'>VIX target:</span> "
            f"<span style='font-family:var(--mono);color:{_tgt_col};'>{_vix_str_label} {_tgt_icon}</span>"
            f" at CE {_pill_ce(sell_ce_strike)} + PE {_pill_pe(sell_pe_strike)}"
            f" <span style='font-family:var(--mono);'>₹{_strangle_val:.0f}</span>"
        )

    # ── Diagonal ticket HTML ──────────────────────────────────────────────────
    if _diag_ok:
        _diag_ticket = (f"""
<div style='margin-top:8px;padding-top:8px;border-top:1px solid var(--border);'>
  <!-- SELL | BUY grid -->
  <div style='display:grid;grid-template-columns:1fr 28px 1fr;gap:4px;align-items:start;'>

    <!-- SELL side -->
    <div style='background:rgba(255,59,48,0.06);border:1px solid rgba(255,59,48,0.25);
                border-radius:6px;padding:8px 10px;'>
      <div style='font-size:9px;font-weight:700;letter-spacing:.1em;color:var(--bear);margin-bottom:6px;'>
        SELL · {near_exp} · 3 LOTS EACH
      </div>
      <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;'>
        <span style='font-size:11px;'>CALL {_pill_ce(_3lot_ce_strike)}</span>
        <span style='font-family:var(--mono);font-size:11px;'>₹{_3lot_ce_ltp:.2f} × 3 = ₹{_3lot_ce_total:.2f}</span>
      </div>
      <div style='display:flex;justify-content:space-between;align-items:center;'>
        <span style='font-size:11px;'>PUT &nbsp;{_pill_pe(_3lot_pe_strike)}</span>
        <span style='font-family:var(--mono);font-size:11px;'>₹{_3lot_pe_ltp:.2f} × 3 = ₹{_3lot_pe_total:.2f}</span>
      </div>
      <div style='border-top:1px solid rgba(255,59,48,0.2);margin-top:6px;padding-top:5px;
                  display:flex;justify-content:space-between;align-items:baseline;'>
        <span style='font-size:9px;color:var(--muted);'>PREMIUM IN</span>
        <span style='font-family:var(--mono);font-size:17px;font-weight:700;color:var(--bear);'>
          ₹{_3lot_sell_total:.2f}
        </span>
      </div>
      <div style='font-size:9px;color:var(--muted);margin-top:2px;'>
        Target/lot ≈ ₹{_3lot_sell_total/3:.0f} &nbsp;·&nbsp; VIX range {_vix_str_label}/3
      </div>
    </div>

    <!-- Arrow -->
    <div style='display:flex;align-items:center;justify-content:center;
                color:var(--muted);font-size:16px;padding-top:32px;'>→</div>

    <!-- BUY side -->
    <div style='background:rgba(52,199,89,0.06);border:1px solid rgba(52,199,89,0.25);
                border-radius:6px;padding:8px 10px;'>
      <div style='font-size:9px;font-weight:700;letter-spacing:.1em;color:var(--bull);margin-bottom:6px;'>
        BUY · FAR {_diag_far_exp} · 1 LOT EACH · 80–140% of sold
      </div>
      <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;'>
        <span style='font-size:11px;'>CALL {_pill_ce(_far_atm_ce_strike)}</span>
        <span style='font-family:var(--mono);font-size:11px;font-weight:700;'>₹{_far_atm_ce_ltp:.2f}</span>
      </div>
      <div style='display:flex;justify-content:space-between;align-items:center;'>
        <span style='font-size:11px;'>PUT &nbsp;{_pill_pe(_far_atm_pe_strike)}</span>
        <span style='font-family:var(--mono);font-size:11px;font-weight:700;'>₹{_far_atm_pe_ltp:.2f}</span>
      </div>
      <div style='border-top:1px solid rgba(52,199,89,0.2);margin-top:6px;padding-top:5px;
                  display:flex;justify-content:space-between;align-items:baseline;'>
        <span style='font-size:9px;color:var(--muted);'>PREMIUM OUT</span>
        <span style='font-family:var(--mono);font-size:17px;font-weight:700;color:{_buy_val_col};'>
          ₹{_far_atm_straddle:.2f}
        </span>
      </div>
      <div style='font-size:9px;color:{_buy_chk_col};font-weight:700;margin-top:2px;'>
        {_ratio_txt} of sold premium &nbsp;·&nbsp; {_buy_status}
      </div>
    </div>
  </div>

  <!-- Net debit row -->
  <div style='margin-top:6px;padding:6px 10px;background:var(--surface);border-radius:5px;
              display:flex;justify-content:space-between;align-items:center;'>
    <span style='font-size:10px;color:var(--muted);'>NET DEBIT (cost to put on this trade)</span>
    <span style='font-family:var(--mono);font-size:14px;font-weight:700;'>₹{_net_debit:.2f}</span>
  </div>
</div>
""").replace("\n", " ")
    else:
        _diag_ticket = ""

    # ── Expiry scan log ────────────────────────────────────────────────────────
    if _diag_scan_log:
        # Sold leg row first
        _near_sell_txt = ""
        if _3lot_ce_strike and _3lot_pe_strike and _3lot_ce_ltp and _3lot_pe_ltp:
            _near_sell_txt = f"CE{_3lot_ce_strike}/PE{_3lot_pe_strike} ₹{_3lot_ce_ltp:.0f}+₹{_3lot_pe_ltp:.0f} × 3"
        _scan_rows = (
            f"<div style='display:flex;justify-content:space-between;padding:1px 4px;"
            f"background:rgba(255,59,48,0.10);border:1px solid rgba(255,59,48,0.35);border-radius:3px;margin-bottom:2px;'>"
            f"<span style='color:var(--bear);font-size:8px;font-weight:700;'>SELL · {near_exp}</span>"
            f"<span style='font-size:8px;color:var(--bear);font-family:var(--mono);'>{_near_sell_txt}</span>"
            f"</div>"
        )
        for _sl in _diag_scan_log:
            _sl_exp, _sl_ce, _sl_pe, _sl_tot, _sl_inband, _sl_flag = _sl
            _is_chosen = (_sl_exp == _diag_far_exp)
            _bg   = "rgba(52,199,89,0.12)"  if _is_chosen else "transparent"
            _bord = "1px solid rgba(52,199,89,0.4)" if _is_chosen else "1px solid transparent"
            _flag_col = "var(--bull)" if _sl_inband else ("var(--muted)" if _sl_flag in ("same week as near", "chain err", "no LTP data") else "var(--bear)")
            if _sl_tot is not None and _sl_tot > 0:
                _pct = f"{_sl_tot / _3lot_sell_total * 100:.0f}%" if _3lot_sell_total else "—"
                _strike_txt = f"CE{_sl_ce}/PE{_sl_pe} ₹{_sl_tot:.0f} ({_pct})"
            else:
                _strike_txt = str(_sl_flag)
            _chosen_tag = " ★" if _is_chosen else ""
            _scan_rows += (
                f"<div style='display:flex;justify-content:space-between;padding:1px 4px;"
                f"background:{_bg};border:{_bord};border-radius:3px;'>"
                f"<span style='color:var(--muted);font-size:8px;'>{_sl_exp}{_chosen_tag}</span>"
                f"<span style='font-size:8px;color:{_flag_col};font-family:var(--mono);'>{_sl_flag} &nbsp;{_strike_txt}</span>"
                f"</div>"
            )
        _diag_scan_html = (
            f"<div style='margin-top:6px;border-top:1px solid var(--border);padding-top:5px;'>"
            f"<div style='font-size:7px;font-weight:700;letter-spacing:.08em;color:var(--muted);margin-bottom:3px;'>EXPIRY SCAN · BUY target {_far_tgt_lo:.0f}–{_far_tgt_hi:.0f} (80–140% of sold ₹{_3lot_sell_total:.0f})</div>"
            f"{_scan_rows}</div>"
        )
    else:
        _diag_scan_html = ""

    st.markdown(
        f"<div class='card' style='border-left:4px solid var(--bear);'>"
        f"<div style='font-size:9px;font-weight:600;letter-spacing:.08em;color:var(--bear);margin-bottom:4px;'>"
        f"DIAGONAL SPREAD &nbsp;·&nbsp; <span style='color:var(--gold);'>{_vp_tgt_band}</span>"
        f"</div>"
        + (f"<div style='font-size:10px;color:var(--text);line-height:1.6;'>{_ref_bar}</div>" if _ref_bar else "")
        + _diag_ticket
        + _diag_scan_html
        + f"</div>",
        unsafe_allow_html=True)
# ── Ideal Premium crossover calculation ───────────────────────────────────────
# Find last strike where CE LTP > PE LTP, and first where PE LTP > CE LTP
_ip_cross_low  = None   # last  CE > PE  (e.g. 23950)
_ip_cross_high = None   # first PE > CE  (e.g. 24000)
_ip_val        = None
_ip_lows       = {}
try:
    _ip_strikes = sorted(s for s in set(near_ce) | set(near_pe)
                         if near_ce.get(s, 0) > 0 and near_pe.get(s, 0) > 0)
    _ip_found_cross = False
    for _s in _ip_strikes:
        _ce_l = near_ce.get(_s, 0)
        _pe_l = near_pe.get(_s, 0)
        if _ce_l > _pe_l:
            _ip_cross_low   = int(_s)
            _ip_found_cross = False      # reset — keep updating as long as CE>PE
        elif _pe_l > _ce_l and _ip_cross_low is not None and not _ip_found_cross:
            _ip_cross_high  = int(_s)
            _ip_found_cross = True
            break
    if _ip_cross_low and _ip_cross_high:
        _ip_val, _ip_lows = fetch_ideal_premium(near_exp, _ip_cross_low, _ip_cross_high)
except Exception:
    pass

with pb4:
    if _spp is not None:
        # Find strike where CE LTP is nearest to SPP
        _ce_spp_strike, _ce_spp_ltp, _ce_spp_diff = None, None, float("inf")
        for _s, _ltp in near_ce.items():
            if _ltp > 0:
                _d = abs(_ltp - _spp)
                if _d < _ce_spp_diff:
                    _ce_spp_diff, _ce_spp_strike, _ce_spp_ltp = _d, int(_s), _ltp
        # Find strike where PE LTP is nearest to SPP
        _pe_spp_strike, _pe_spp_ltp, _pe_spp_diff = None, None, float("inf")
        for _s, _ltp in near_pe.items():
            if _ltp > 0:
                _d = abs(_ltp - _spp)
                if _d < _pe_spp_diff:
                    _pe_spp_diff, _pe_spp_strike, _pe_spp_ltp = _d, int(_s), _ltp

        # Spot vs Strike_Near_SPP (the reference strike, not raw SPP premium)
        _ref_strike = _ce_spp_strike or _pe_spp_strike
        if _ref_strike:
            _vs_ref = spot - _ref_strike
            _ref_col = "var(--bull)" if _vs_ref > 0 else ("var(--bear)" if _vs_ref < 0 else "var(--muted)")
            _ref_lbl = f"Spot above ref strike ↑" if _vs_ref > 0 else (f"Spot below ref strike ↓" if _vs_ref < 0 else "At ref strike")
        else:
            _vs_ref, _ref_col, _ref_lbl = None, "var(--muted)", ""
        st.markdown(
            f"<div class='card' style='border-left:4px solid var(--gold);'>"
            f"<div class='lbl'>SPP &nbsp;·&nbsp; UIP Reference <span style='font-size:9px;color:var(--muted);'>"
            f"(prev {_spp_src} · ATM {_spp_atm} locked)</span></div>"
            f"<div style='display:flex;align-items:baseline;gap:14px;'>"
            f"<div>"
            f"<div style='font-size:8px;color:var(--muted);letter-spacing:.06em;'>SPP</div>"
            f"<div class='val-big val-gold'>₹{_spp:,.2f}</div>"
            f"</div>"
            + (
                f"<div style='border-left:1px solid var(--border);padding-left:12px;'>"
                f"<div style='font-size:8px;color:var(--muted);letter-spacing:.06em;'>IDEAL PREMIUM"
                + (f" · <span class='strike-pill-ce'>{_ip_cross_low}</span>→<span class='strike-pill'>{_ip_cross_high}</span>" if _ip_cross_low else "")
                + f"</div>"
                f"<div style='font-family:var(--mono);font-size:20px;font-weight:700;color:var(--gold);'>"
                + (f"₹{_ip_val:.2f}" if _ip_val is not None else "<span style='color:var(--muted);font-size:12px;'>pending</span>")
                + f"</div>"
                + (
                    f"<div style='font-size:8px;color:var(--muted);'>"
                    f"{_ip_cross_low}CE:{_ip_lows.get(str(_ip_cross_low)+'_CE', 0):.0f} "
                    f"{_ip_cross_low}PE:{_ip_lows.get(str(_ip_cross_low)+'_PE', 0):.0f} "
                    f"{_ip_cross_high}CE:{_ip_lows.get(str(_ip_cross_high)+'_CE', 0):.0f} "
                    f"{_ip_cross_high}PE:{_ip_lows.get(str(_ip_cross_high)+'_PE', 0):.0f}"
                    f"</div>"
                    if _ip_val is not None else ""
                )
                + f"</div>"
                if (_ip_cross_low or _ip_val is not None) else ""
            )
            + f"</div>"
            + (
                f"<div style='display:flex;align-items:baseline;gap:8px;margin:.2rem 0;'>"
                f"<span style='font-family:var(--mono);font-size:12px;font-weight:700;color:{_ref_col};'>"
                f"Spot {'+' if _vs_ref > 0 else ''}{_vs_ref:,.0f} vs {_ref_strike}</span>"
                f"<span style='font-size:9px;color:var(--muted);'>{_ref_lbl}</span>"
                f"</div>"
                if _vs_ref is not None else ""
            )
            # Strikes nearest to SPP
            + f"<div style='margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--border);'>"
            f"<div class='lbl' style='margin-bottom:.2rem;'>Strikes nearest to SPP</div>"
            + (
                f"<div style='display:flex;justify-content:space-between;margin:.15rem 0;'>"
                f"<span class='lbl'>CE <span class='strike-pill-ce'>{_ce_spp_strike}</span></span>"
                f"<span style='font-family:var(--mono);font-size:12px;color:var(--ce);font-weight:700;'>₹{_ce_spp_ltp:.2f}</span>"
                f"<span style='font-size:9px;color:var(--muted);'>Δ{_ce_spp_diff:.1f}</span>"
                f"</div>"
                if _ce_spp_strike else ""
            )
            + (
                f"<div style='display:flex;justify-content:space-between;margin:.15rem 0;'>"
                f"<span class='lbl'>PE <span class='strike-pill'>{_pe_spp_strike}</span></span>"
                f"<span style='font-family:var(--mono);font-size:12px;color:var(--pe);font-weight:700;'>₹{_pe_spp_ltp:.2f}</span>"
                f"<span style='font-size:9px;color:var(--muted);'>Δ{_pe_spp_diff:.1f}</span>"
                f"</div>"
                if _pe_spp_strike else ""
            )
            + f"</div>"
            # Prev day data used
            f"<div style='margin-top:.3rem;padding-top:.3rem;border-top:1px solid var(--border);'>"
            f"<span class='lbl'>ATM {_spp_atm} prev-day: "
            f"CE H:{_spp_ce_h:.0f}/L:{_spp_ce_l:.0f} OI:{_spp_ce_oi_L:.1f}L &nbsp;·&nbsp; "
            f"PE H:{_spp_pe_h:.0f}/L:{_spp_pe_l:.0f} OI:{_spp_pe_oi_L:.1f}L</span>"
            f"</div>"
            + f"</div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='card'><div class='lbl'>SPP · UIP Reference</div>"
            "<div class='val-big' style='color:var(--muted);'>N/A</div>"
            "<div class='lbl'>H/L data not yet available</div></div>",
            unsafe_allow_html=True)

# ── Ratio Diagonal CE card ────────────────────────────────────────────────────
if _rd_atm_ce_ltp > 0:
    st.markdown("<div class='sec-hdr'>📐 Ratio Diagonal CE &nbsp;·&nbsp; Sell 1 ATM : Buy 2 OTM Far</div>",
                unsafe_allow_html=True)

    # Capital slider
    _rd_capital = st.slider(
        "Deployed Capital",
        min_value=200_000, max_value=10_000_000, step=100_000,
        value=st.session_state.get("rd_capital", 500_000),
        key="rd_capital",
        format="₹%d",
        help="Minimum ₹2L. Lot count is sized so that worst intraday loss ≤ 1% of this capital.",
    )
    # Recompute with live slider value (premium-based margin)
    _rd_max_daily_loss  = _rd_capital * 0.01
    _rd_margin_per_unit = max(
        LOT_SIZE * _rd_atm_ce_ltp * 7,
        spot * LOT_SIZE * 0.02 if spot else 30_000,
        1.0
    )
    _rd_lots_by_capital = max(1, int(_rd_capital / _rd_margin_per_unit))
    _rd_lots_by_risk    = max(1, int(_rd_max_daily_loss / _rd_loss_per_unit))
    _rd_lots            = _rd_lots_by_capital   # capital is primary; wing manages risk
    _rd_proj_loss       = _rd_loss_per_unit * _rd_lots
    _rd_proj_pct        = (_rd_proj_loss / _rd_capital * 100) if _rd_capital else 0

    # ── Wing hedge: if daily loss > 1%, buy near OTM CE to cap gamma risk ──────
    _rd_wing_strike = _rd_wing_ltp = _rd_wing_lots = None
    _rd_wing_new_loss = _rd_proj_loss
    _rd_wing_new_pct  = _rd_proj_pct

    if _rd_proj_pct > 1.0 and _rd_lots > 0:
        # Wing rule: SELL a far OTM same-expiry CE to collect premium that covers
        # the projected intraday loss.  Lots = ceil(proj_loss / (lot_size × wing_LTP))
        # so that premium collected ≥ projected 1σ daily loss → blue line ≤ 1%.
        import math as _math
        _wing_ltp_max = _rd_atm_ce_ltp * 0.10   # only strikes ≤ 10% of sold premium
        _found_wing   = False
        for _wi in range(1, 25):                  # scan ATM+1 … ATM+24 steps
            _ws = _rd_use_atm + _wi * STEP
            _wl = near_ce.get(float(_ws), 0)
            if _wl <= 0 or _wl > _wing_ltp_max:
                continue
            # Sell enough lots so collected premium ≥ projected loss
            _rd_wing_lots_t  = max(1, _math.ceil(_rd_proj_loss / max(LOT_SIZE * _wl, 1)))
            _wing_collected  = _rd_wing_lots_t * LOT_SIZE * _wl
            # Net loss after wing sale = projected loss − premium collected (floor 0)
            _rd_wing_strike   = int(_ws)
            _rd_wing_ltp      = _wl
            _rd_wing_lots     = _rd_wing_lots_t
            _rd_wing_new_loss = max(0.0, _rd_proj_loss - _wing_collected)
            _rd_wing_new_pct  = (_rd_wing_new_loss / _rd_capital * 100) if _rd_capital else 0
            _found_wing       = True
            break

    _rd_status_col = "var(--bull)" if _rd_in_range else "var(--gold)"
    _rd_status_txt = (f"✓ {_rd_ratio_pct:.0f}% — in 40–50% band"
                      if _rd_in_range else f"↑ {_rd_ratio_pct:.0f}% — above 50% band")
    _rd_pill_ce    = lambda s: f"<span class='strike-pill-ce'>{s}</span>"
    _loss_col      = "var(--bull)" if _rd_proj_pct <= 1.0 else "var(--bear)"

    # Wing HTML block (empty string if no wing needed)
    if _rd_wing_strike and _rd_proj_pct > 1.0:
        _wing_collected_total = _rd_wing_lots * LOT_SIZE * _rd_wing_ltp
        _wing_new_col  = "var(--bull)" if _rd_wing_new_pct <= 1.0 else "var(--gold)"
        _rd_wing_html  = (
            f"<div style='margin-top:6px;padding:8px 10px;"
            f"background:rgba(255,201,64,0.07);border:1px solid rgba(255,201,64,0.3);"
            f"border-radius:6px;'>"
            f"<div style='font-size:9px;font-weight:700;letter-spacing:.08em;"
            f"color:var(--gold);margin-bottom:5px;'>⚡ SELL WING — proj loss &gt;1%, sell same-expiry OTM CE to collect premium</div>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;'>"
            f"<span style='font-size:11px;'>SELL {_rd_wing_lots} lot{'s' if _rd_wing_lots>1 else ''} "
            f"near CE {_rd_pill_ce(_rd_wing_strike)} &nbsp;<span style='font-size:9px;color:var(--muted);'>(same expiry)</span></span>"
            f"<span style='font-family:var(--mono);font-size:12px;font-weight:700;color:var(--bull);'>+₹{_rd_wing_ltp:.2f} × {_rd_wing_lots} lots × {LOT_SIZE} = ₹{_wing_collected_total:,.0f} collected</span>"
            f"</div>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-size:9px;color:var(--muted);'>Residual daily loss after wing (1σ)</span>"
            f"<span style='font-family:var(--mono);font-size:12px;font-weight:700;color:{_wing_new_col};'>"
            f"₹{_rd_wing_new_loss:,.0f} &nbsp;({_rd_wing_new_pct:.2f}%)"
            f"</span>"
            f"</div>"
            f"</div>"
        ).replace("\n", " ")
    else:
        _rd_wing_html = ""

    # Lock status badge for card header
    if _rd_locked:
        _rd_lock_mm = _rd_lock_remaining // 60
        _rd_lock_ss = _rd_lock_remaining % 60
        _rd_lock_badge = (
            f"<span style='font-size:9px;font-family:var(--mono);"
            f"background:rgba(255,201,64,0.15);color:var(--gold);"
            f"padding:2px 6px;border-radius:4px;border:1px solid rgba(255,201,64,0.4);'>"
            f"🔒 LOCKED {_rd_use_atm} &nbsp;·&nbsp; resets in {_rd_lock_mm}m {_rd_lock_ss:02d}s"
            f"</span>"
        )
    else:
        _rd_lock_badge = (
            f"<span style='font-size:9px;font-family:var(--mono);"
            f"background:rgba(50,215,75,0.10);color:var(--bull);"
            f"padding:2px 6px;border-radius:4px;border:1px solid rgba(50,215,75,0.3);'>"
            f"{'🟢 LIVE ATM' if mkt_open else '⭕ MKT CLOSED'}"
            f"</span>"
        )

    _rd_card = (
        f"<div class='card' style='border-left:4px solid var(--ce);'>"
        # Header row: position sizing summary
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;'>"
        f"<div style='font-size:9px;font-weight:700;letter-spacing:.08em;color:var(--ce);'>"
        f"RATIO DIAGONAL CE &nbsp;·&nbsp; {_vp_tgt_band} &nbsp; {_rd_lock_badge}"
        f"</div>"
        f"<div style='font-size:10px;font-family:var(--mono);color:var(--muted);'>"
        f"Capital ₹{_rd_capital/1e5:.1f}L &nbsp;·&nbsp; "
        f"<span style='color:var(--ce);font-weight:700;'>Sell {_rd_lots}L &nbsp;Buy {_rd_lots*2}L</span>"
        f"</div>"
        f"</div>"
        # SELL | → | BUY grid
        f"<div style='display:grid;grid-template-columns:1fr 24px 1fr;gap:4px;align-items:start;'>"
        # SELL
        f"<div style='background:rgba(255,59,48,0.06);border:1px solid rgba(255,59,48,0.25);border-radius:6px;padding:8px 10px;'>"
        f"<div style='font-size:9px;font-weight:700;letter-spacing:.1em;color:var(--bear);margin-bottom:5px;'>SELL · NEAR · {_rd_lots} LOT{'S' if _rd_lots>1 else ''}</div>"
        f"<div style='display:flex;justify-content:space-between;'>"
        f"<span style='font-size:11px;'>ATM CALL {_rd_pill_ce(_rd_use_atm)}</span>"
        f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;'>₹{_rd_atm_ce_ltp:.2f}</span>"
        f"</div>"
        f"<div style='border-top:1px solid rgba(255,59,48,0.2);margin-top:5px;padding-top:4px;"
        f"display:flex;justify-content:space-between;align-items:baseline;'>"
        f"<span style='font-size:9px;color:var(--muted);'>TOTAL IN</span>"
        f"<span style='font-family:var(--mono);font-size:15px;font-weight:700;color:var(--bear);'>₹{_rd_atm_ce_ltp*_rd_lots:.2f}</span>"
        f"</div>"
        f"<div style='font-size:9px;color:var(--muted);margin-top:2px;'>Target buy = ₹{_rd_lo:.0f}–₹{_rd_hi:.0f}</div>"
        f"</div>"
        # Arrow
        f"<div style='display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:16px;padding-top:26px;'>→</div>"
        # BUY
        f"<div style='background:rgba(52,199,89,0.06);border:1px solid rgba(52,199,89,0.25);border-radius:6px;padding:8px 10px;'>"
        f"<div style='font-size:9px;font-weight:700;letter-spacing:.1em;color:var(--bull);margin-bottom:5px;'>BUY · FAR {far_exp} · {_rd_lots*2} LOTS</div>"
        f"<div style='display:flex;justify-content:space-between;'>"
        f"<span style='font-size:11px;'>OTM CALL {_rd_pill_ce(_rd_far_ce_strike)}</span>"
        f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;'>₹{_rd_far_ce_ltp:.2f} × {_rd_lots*2}</span>"
        f"</div>"
        f"<div style='border-top:1px solid rgba(52,199,89,0.2);margin-top:5px;padding-top:4px;"
        f"display:flex;justify-content:space-between;align-items:baseline;'>"
        f"<span style='font-size:9px;color:var(--muted);'>TOTAL OUT</span>"
        f"<span style='font-family:var(--mono);font-size:15px;font-weight:700;color:var(--bull);'>₹{_rd_far_ce_ltp*_rd_lots*2:.2f}</span>"
        f"</div>"
        f"<div style='font-size:9px;color:{_rd_status_col};font-weight:700;margin-top:2px;'>{_rd_status_txt}</div>"
        f"</div>"
        f"</div>"
        # Summary row: net + daily risk
        f"<div style='margin-top:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px;'>"
        f"<div style='padding:5px 10px;background:var(--surface);border-radius:5px;"
        f"display:flex;justify-content:space-between;align-items:center;'>"
        f"<span style='font-size:10px;color:var(--muted);'>{_rd_net_lbl} (per lot)</span>"
        f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:{_rd_net_col};'>₹{abs(_rd_net):.2f}</span>"
        f"</div>"
        f"<div style='padding:5px 10px;background:var(--surface);border-radius:5px;"
        f"display:flex;justify-content:space-between;align-items:center;'>"
        f"<span style='font-size:10px;color:var(--muted);'>Max daily loss (1σ)</span>"
        f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:{_loss_col};'>"
        f"₹{_rd_proj_loss:,.0f} &nbsp;<span style='font-size:9px;'>({_rd_proj_pct:.2f}% of ₹{_rd_capital/1e5:.1f}L)</span>"
        f"</span>"
        f"</div>"
        f"</div>"
        + _rd_wing_html
        + f"</div>"
    ).replace("\n", " ")
    st.markdown(_rd_card, unsafe_allow_html=True)

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
            f"<div class='card card-gold'><div class='lbl'>Effective VIX (avg of open + current)</div>"
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

_T_near_std = max(_days_to_exp, 1) / 365.0
_far_days   = max((datetime.strptime(far_exp, "%Y-%m-%d").date() - now.date()).days, 1)
_T_far_std  = _far_days / 365.0
_sigma_std  = (_eff_vix / 100.0) if _vix_ok else 0.15

# ── Wing hedge legs (using FAR EXPIRY for gamma taper) ────────────────────
# Standard ±500 wings (still near expiry)
_wing_ce_strike = int(round((sell_ce_strike + WING_OFFSET) / STEP) * STEP)
_wing_pe_strike = int(round((sell_pe_strike - WING_OFFSET) / STEP) * STEP)
_wing_ce_ltp    = near_ce.get(float(_wing_ce_strike), 0)
_wing_pe_ltp    = near_pe.get(float(_wing_pe_strike), 0)
_wing_ce_lots   = BUY_LOTS   # 1L per side — user spec: 2L sell, 1L wing buy, 1L far buy
_wing_pe_lots   = BUY_LOTS

# ── Deep OTM wings — USING FAR LEGS (Long expiry) for gamma taper ──────────
# Jointly solves CE and PE deep OTM lots so net gamma is equal on both sides.
# This flattens the blue line by adding gamma from the far expiry.

_deep_ce_strike, _deep_ce_ltp = find_deep_otm_strike(
    far_ce, sell_ltp=sell_ce_ltp, pct_lo=0.05, pct_hi=0.10,
    min_strike=sell_ce_strike + DEEP_OTM_OFFSET)  # Far OTM CE
_deep_pe_strike, _deep_pe_ltp = find_deep_otm_strike(
    far_pe, sell_ltp=sell_pe_ltp, pct_lo=0.05, pct_hi=0.10,
    max_strike=sell_pe_strike - DEEP_OTM_OFFSET)  # Far OTM PE

# All pre-wing legs — CE + PE combined for total net gamma calculation
_all_pre_legs = [
    {"strike":sell_ce_strike, "lots":sell_lots,    "is_sell":True,  "T":_T_near_std, "api_gamma": near_ce_gamma.get(float(sell_ce_strike), 0)},
    {"strike":sell_pe_strike, "lots":sell_lots,    "is_sell":True,  "T":_T_near_std, "api_gamma": near_pe_gamma.get(float(sell_pe_strike), 0)},
    {"strike":buy_ce_strike,  "lots":BUY_LOTS,     "is_sell":False, "T":_T_far_std,  "api_gamma": far_ce_gamma.get(float(buy_ce_strike), 0)},
    {"strike":buy_pe_strike,  "lots":BUY_LOTS,     "is_sell":False, "T":_T_far_std,  "api_gamma": far_pe_gamma.get(float(buy_pe_strike), 0)},
    {"strike":_wing_ce_strike,"lots":_wing_ce_lots,"is_sell":False, "T":_T_near_std, "api_gamma": near_ce_gamma.get(float(_wing_ce_strike), 0)},
    {"strike":_wing_pe_strike,"lots":_wing_pe_lots,"is_sell":False, "T":_T_near_std, "api_gamma": near_pe_gamma.get(float(_wing_pe_strike), 0)},
]

# Solve symmetric wing lots: zero out total net gamma of entire position
_deep_ce_lots, _deep_pe_lots = solve_wing_lots_total_gamma(
    spot, _sigma_std,
    _all_pre_legs,
    _deep_ce_strike, far_ce_gamma.get(float(_deep_ce_strike), 0),
    _deep_pe_strike, far_pe_gamma.get(float(_deep_pe_strike), 0),
    wing_T=_T_far_std,
    min_lots=1, max_lots=sell_lots * 6,
)

# Assemble final legs
legs = [
    # Core diagonal — short near, long far
    {"opt_type":"CE","strike":sell_ce_strike, "ltp":sell_ce_ltp, "lots":sell_lots,     "is_sell":True, "is_near":True,  "T":_T_near_std, "label":"SELL near CE"},
    {"opt_type":"PE","strike":sell_pe_strike, "ltp":sell_pe_ltp, "lots":sell_lots,     "is_sell":True, "is_near":True,  "T":_T_near_std, "label":"SELL near PE"},
    {"opt_type":"CE","strike":buy_ce_strike,  "ltp":buy_ce_ltp,  "lots":BUY_LOTS,      "is_sell":False,"is_near":False, "T":_T_far_std,  "label":"BUY far CE"},
    {"opt_type":"PE","strike":buy_pe_strike,  "ltp":buy_pe_ltp,  "lots":BUY_LOTS,      "is_sell":False,"is_near":False, "T":_T_far_std,  "label":"BUY far PE"},
    # Near ±500 wings
    {"opt_type":"CE","strike":_wing_ce_strike,"ltp":_wing_ce_ltp,"lots":_wing_ce_lots, "is_sell":False,"is_near":True,  "T":_T_near_std, "label":f"BUY wing CE +{WING_OFFSET}"},
    {"opt_type":"PE","strike":_wing_pe_strike,"ltp":_wing_pe_ltp,"lots":_wing_pe_lots, "is_sell":False,"is_near":True,  "T":_T_near_std, "label":f"BUY wing PE -{WING_OFFSET}"},
    # Deep OTM wings (γ-taper) — FAR EXPIRY (Long leg taper)
    {"opt_type":"CE","strike":_deep_ce_strike,"ltp":_deep_ce_ltp,"lots":_deep_ce_lots,"is_sell":False,"is_near":False,"T":_T_far_std,"label":f"BUY deep CE {_deep_ce_lots}L (far) γ-solved"},
    {"opt_type":"PE","strike":_deep_pe_strike,"ltp":_deep_pe_ltp,"lots":_deep_pe_lots,"is_sell":False,"is_near":False,"T":_T_far_std,"label":f"BUY deep PE {_deep_pe_lots}L (far) γ-solved"},
]

# Deployed capital: gross premium of all legs × lot_size (margin proxy)
_deployed_cap = sum(abs(leg["ltp"]) * leg["lots"] * LOT_SIZE for leg in legs)

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
    _wing_cost = (
        _wing_ce_ltp  * _wing_ce_lots  + _wing_pe_ltp  * _wing_pe_lots
        + _deep_ce_ltp * _deep_ce_lots + _deep_pe_ltp  * _deep_pe_lots
    ) * LOT_SIZE
    st.markdown(
        f"<div class='card'><div class='lbl'>Premium Paid</div>"
        f"<div class='val-big val-bear'>₹{total_buy + _wing_cost:,.0f}</div>"
        f"<div class='lbl'>{BUY_LOTS}L far CE+PE + all wings ₹{_wing_cost:,.0f}</div></div>",
        unsafe_allow_html=True)
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
# Wing hedge summary
st.markdown(
    f"<div class='card' style='border-left:4px solid #4d9fff;margin-top:.3rem;'>"
    f"<div class='lbl' style='color:#4d9fff;font-weight:700;letter-spacing:1px;'>🪽 WING HEDGES — Far Expiry (flatten intraday gamma)</div>"
    f"<div style='display:flex;gap:2rem;margin-top:.4rem;flex-wrap:wrap;'>"
    # Near ±500
    f"<div><span class='lbl'>BUY {_wing_ce_lots}L CE</span> "
    f"<span class='strike-pill-buy'>{_wing_ce_strike}</span> "
    f"<span style='font-family:var(--mono);font-size:13px;color:var(--ce);font-weight:700;'>₹{_wing_ce_ltp:.2f}</span>"
    f"<span style='font-size:9px;color:var(--muted);'> &nbsp;+{WING_OFFSET}</span></div>"
    f"<div><span class='lbl'>BUY {_wing_pe_lots}L PE</span> "
    f"<span class='strike-pill'>{_wing_pe_strike}</span> "
    f"<span style='font-family:var(--mono);font-size:13px;color:var(--pe);font-weight:700;'>₹{_wing_pe_ltp:.2f}</span>"
    f"<span style='font-size:9px;color:var(--muted);'> &nbsp;−{WING_OFFSET}</span></div>"
    # Deep OTM γ-taper (Far expiry)
    f"<div style='border-left:2px solid #4d9fff;padding-left:.5rem;'>"
    f"<span class='lbl' style='color:#4d9fff;'>BUY {_deep_ce_lots}L CE</span> "
    f"<span class='strike-pill-buy'>{_deep_ce_strike}</span> "
    f"<span style='font-family:var(--mono);font-size:13px;color:var(--ce);font-weight:700;'>₹{_deep_ce_ltp:.2f}</span>"
    f"<span style='font-size:9px;color:#4d9fff;'> &nbsp;+{DEEP_OTM_OFFSET} γ-solved · {_deep_ce_lots}L (far)</span></div>"
    f"<div style='border-left:2px solid #4d9fff;padding-left:.5rem;'>"
    f"<span class='lbl' style='color:#4d9fff;'>BUY {_deep_pe_lots}L PE</span> "
    f"<span class='strike-pill'>{_deep_pe_strike}</span> "
    f"<span style='font-family:var(--mono);font-size:13px;color:var(--pe);font-weight:700;'>₹{_deep_pe_ltp:.2f}</span>"
    f"<span style='font-size:9px;color:#4d9fff;'> &nbsp;−{DEEP_OTM_OFFSET} γ-solved · {_deep_pe_lots}L (far)</span></div>"
    f"</div>"
    f"<div style='margin-top:.3rem;font-size:9px;color:var(--muted);'>"
    f"These legs cap intraday gamma — the blue dashed line in the chart should stay flat within the 1σ daily band.</div>"
    f"</div>",
    unsafe_allow_html=True,
)

st.markdown("<div class='sec-hdr'>📈 Payoff — Expiry (green) vs Intraday/Current (blue dashed)</div>",
            unsafe_allow_html=True)
st.markdown(make_payoff_svg(
    legs, atm, LOT_SIZE, sell_ce_strike, sell_pe_strike,
    sigma=_sigma_std, spot=spot, deployed_cap=_deployed_cap, cap_pct=1.6,
), unsafe_allow_html=True)
st.caption(
    f"🟢 Green solid = P&L at near expiry &nbsp;│&nbsp; "
    f"🔵 Blue dashed = Intraday P&L now (BS-priced, should stay flat) &nbsp;│&nbsp; "
    f"🔴 Red dashed = 1.6% deployed capital loss cap (₹{abs(int(_deployed_cap*0.016)):,}) &nbsp;│&nbsp; "
    f"Short: CE {sell_ce_strike} / PE {sell_pe_strike} &nbsp;│&nbsp; Far long: CE {buy_ce_strike} / PE {buy_pe_strike} &nbsp;│&nbsp; Wing: BUY {_wing_ce_lots}L CE {_wing_ce_strike} + BUY {_wing_pe_lots}L PE {_wing_pe_strike}"
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
# HIGH-VIX STRATEGY  (VIX > 15)
# ─────────────────────────────────────────────
if _vix_ok and _eff_vix >= 15.0:
    st.markdown(
        f"<div class='sec-hdr' style='color:var(--bear);border-color:var(--bear);'>"
        f"⚡ High VIX Strategy &nbsp;·&nbsp; VIX {_eff_vix:.2f} &gt; 15 "
        f"&nbsp;·&nbsp; Delta-based Ratio Spread</div>",
        unsafe_allow_html=True,
    )

    # Auto-select sell expiry: must have DTE > 5
    _hv_sell_exp = None
    for _exp in sorted(all_exp):
        _exp_dte = (datetime.strptime(_exp, "%Y-%m-%d").date() - now.date()).days
        if _exp_dte > 5:
            _hv_sell_exp = _exp
            _hv_sell_dte = _exp_dte
            break
    if _hv_sell_exp is None:
        st.warning("⚠️ No expiry with DTE > 5 found. Cannot build High-VIX strategy.")
        _hv_sell_exp = near_exp
        _hv_sell_dte = _days_to_exp

    # Fetch chain for sell expiry (reuse near chain if same)
    if _hv_sell_exp == near_exp:
        _hv_sell_ce, _hv_sell_pe = near_ce, near_pe
        _hv_sell_ce_gamma, _hv_sell_pe_gamma = near_ce_gamma, near_pe_gamma
    else:
        with st.spinner(f"Loading sell chain {_hv_sell_exp}…"):
            _hv_sell_raw, _hv_sell_err = fetch_chain(token, _hv_sell_exp)
        if _hv_sell_raw:
            _, _, _hv_sell_ce, _hv_sell_pe, _, _, _, _, _hv_sell_ce_gamma, _hv_sell_pe_gamma = parse_chain(_hv_sell_raw)
        else:
            st.warning(f"⚠️ Could not load chain for {_hv_sell_exp}: {_hv_sell_err}")
            _hv_sell_ce, _hv_sell_pe = near_ce, near_pe
            _hv_sell_ce_gamma, _hv_sell_pe_gamma = near_ce_gamma, near_pe_gamma

    _T_near  = max(_hv_sell_dte, 1) / 365.0
    _sigma   = _eff_vix / 100.0

    _hv_ce_cands = find_delta_strikes(_hv_sell_ce, spot, _T_near, _sigma, "CE", 0.18, 0.21)
    _hv_pe_cands = find_delta_strikes(_hv_sell_pe, spot, _T_near, _sigma, "PE", 0.18, 0.21)

    if not _hv_ce_cands or not _hv_pe_cands:
        st.warning(
            f"⚠️ No NIFTY strikes found with delta 12–18 for VIX={_eff_vix:.1f} "
            f"and DTE={_days_to_exp}d. Try a later near expiry or check VIX data."
        )
    else:
        _hv_ce  = _hv_ce_cands[0]   # primary CE sell
        _hv_pe  = _hv_pe_cands[0]   # primary PE sell

        # Near wing: CE +500 / PE -500
        _hv_ce2_strike = int(round((_hv_ce["strike"] + WING_OFFSET) / STEP) * STEP)
        _hv_pe2_strike = int(round((_hv_pe["strike"] - WING_OFFSET) / STEP) * STEP)
        _hv_ce2_ltp    = _hv_sell_ce.get(float(_hv_ce2_strike), 0)
        _hv_pe2_ltp    = _hv_sell_pe.get(float(_hv_pe2_strike), 0)

        _T_hv = max(_hv_sell_dte, 1) / 365.0
        _hv_sell_lots = 2       # HV always sells 2 lots

        # ── Far expiry — resolve FIRST so deep OTM wings use far chain ──────
        _hv_far_exp = select_hv_far_expiry(all_exp, _hv_sell_exp, _hv_sell_dte)
        _hv_far_dte = (
            (datetime.strptime(_hv_far_exp, "%Y-%m-%d").date() - now.date()).days
            if _hv_far_exp else 0
        )
        _T_hv_far = max(_hv_far_dte, 1) / 365.0

        # Fetch far chain — reuse existing if same expiry, else fetch fresh
        if _hv_far_exp and _hv_far_exp == far_exp:
            _hv_far_ce, _hv_far_pe = far_ce, far_pe
            _hv_far_ce_gamma, _hv_far_pe_gamma = far_ce_gamma, far_pe_gamma
        elif _hv_far_exp:
            with st.spinner(f"Loading far chain {_hv_far_exp}…"):
                _hv_far_raw, _hv_far_err = fetch_chain(token, _hv_far_exp)
            if _hv_far_raw:
                _, _, _hv_far_ce, _hv_far_pe, _, _, _, _, _hv_far_ce_gamma, _hv_far_pe_gamma = parse_chain(_hv_far_raw)
            else:
                _hv_far_ce, _hv_far_pe = {}, {}
                _hv_far_ce_gamma, _hv_far_pe_gamma = {}, {}
        else:
            _hv_far_ce, _hv_far_pe = {}, {}
            _hv_far_ce_gamma, _hv_far_pe_gamma = {}, {}

        # ── Deep OTM wings — FAR chain, gamma solved against far DTE ────────
        # CE wing must be strictly above sell CE (extreme far OTM calls)
        # PE wing must be strictly below sell PE (extreme far OTM puts)
        _hv_deep_ce_strike, _hv_deep_ce_ltp = find_deep_otm_strike(
            _hv_far_ce, sell_ltp=_hv_ce["ltp"], pct_lo=0.04, pct_hi=0.12,
            min_strike=_hv_ce["strike"] + DEEP_OTM_OFFSET)
        _hv_deep_pe_strike, _hv_deep_pe_ltp = find_deep_otm_strike(
            _hv_far_pe, sell_ltp=_hv_pe["ltp"], pct_lo=0.04, pct_hi=0.12,
            max_strike=_hv_pe["strike"] - DEEP_OTM_OFFSET)

        # All pre-wing legs (CE + PE combined) — far buy included for correct total gamma
        _hv_ce_buy_strike = float(_hv_ce["strike"])
        _hv_pe_buy_strike = float(_hv_pe["strike"])
        _hv_all_pre_legs = [
            {"strike":_hv_ce["strike"], "lots":_hv_sell_lots, "is_sell":True,  "T":_T_hv,    "api_gamma": _hv_sell_ce_gamma.get(_hv_ce_buy_strike, 0)},
            {"strike":_hv_pe["strike"], "lots":_hv_sell_lots, "is_sell":True,  "T":_T_hv,    "api_gamma": _hv_sell_pe_gamma.get(_hv_pe_buy_strike, 0)},
            {"strike":_hv_ce2_strike,   "lots":1,             "is_sell":False, "T":_T_hv,    "api_gamma": _hv_sell_ce_gamma.get(float(_hv_ce2_strike), 0)},
            {"strike":_hv_pe2_strike,   "lots":1,             "is_sell":False, "T":_T_hv,    "api_gamma": _hv_sell_pe_gamma.get(float(_hv_pe2_strike), 0)},
            {"strike":_hv_ce["strike"], "lots":BUY_LOTS,      "is_sell":False, "T":_T_hv_far,"api_gamma": _hv_far_ce_gamma.get(_hv_ce_buy_strike, 0)},
            {"strike":_hv_pe["strike"], "lots":BUY_LOTS,      "is_sell":False, "T":_T_hv_far,"api_gamma": _hv_far_pe_gamma.get(_hv_pe_buy_strike, 0)},
        ]

        # Solve symmetric lots: zero out total net gamma of entire HV position
        _hv_deep_ce_lots, _hv_deep_pe_lots = solve_wing_lots_total_gamma(
            spot, _sigma,
            _hv_all_pre_legs,
            _hv_deep_ce_strike, _hv_far_ce_gamma.get(float(_hv_deep_ce_strike), 0),
            _hv_deep_pe_strike, _hv_far_pe_gamma.get(float(_hv_deep_pe_strike), 0),
            wing_T=_T_hv_far,
            min_lots=1, max_lots=_hv_sell_lots * 6,
        )

        # Buy LTPs (same strike, far expiry)
        _hv_ce_buy_ltp = _hv_far_ce.get(float(_hv_ce["strike"]), 0)
        _hv_pe_buy_ltp = _hv_far_pe.get(float(_hv_pe["strike"]), 0)

        # Net premium (deep OTM wings on BOTH sides):
        _hv_ce_collect = (_hv_ce["ltp"] * _hv_sell_lots
                          - _hv_ce2_ltp * 1
                          - _hv_deep_ce_ltp * _hv_deep_ce_lots
                          - _hv_ce_buy_ltp  * BUY_LOTS) * LOT_SIZE
        _hv_pe_collect = (_hv_pe["ltp"] * _hv_sell_lots
                          - _hv_pe2_ltp * 1
                          - _hv_deep_pe_ltp * _hv_deep_pe_lots
                          - _hv_pe_buy_ltp  * BUY_LOTS) * LOT_SIZE
        _hv_net        = _hv_ce_collect + _hv_pe_collect

        # ── Display ────────────────────────────────────────────────────────
        hv_c1, hv_c2 = st.columns(2)

        with hv_c1:
            st.markdown(
                f"<div class='card card-ce'>"
                f"<div class='lbl'>📅 <span class='date-pill'>{_hv_sell_exp}</span> &nbsp; CE SIDE</div>"
                f"<div style='margin-top:.5rem;'>"
                # Primary sell
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;'>"
                f"<span class='lbl'>SELL 2L &nbsp;<span class='strike-pill-ce'>{_hv_ce['strike']}</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--ce);'>₹{_hv_ce['ltp']:.2f}</span>"
                f"<span style='font-size:10px;color:var(--muted);'>δ {_hv_ce['delta']:.3f}</span>"
                f"</div>"
                # Near +500 hedge
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;'>"
                f"<span class='lbl'>BUY 1L &nbsp;<span class='strike-pill-buy'>{_hv_ce2_strike}</span> <span style='color:var(--muted);font-size:9px;'>(+{WING_OFFSET} hedge)</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--bull);'>₹{_hv_ce2_ltp:.2f}</span>"
                f"</div>"
                # Deep OTM CE wing (γ-taper)
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;background:rgba(77,159,255,0.07);border-radius:4px;padding:2px 4px;'>"
                f"<span class='lbl'>BUY {_hv_deep_ce_lots}L &nbsp;<span class='strike-pill-buy'>{_hv_deep_ce_strike}</span>"
                f" <span style='color:#4d9fff;font-size:9px;font-weight:700;'>🪽 DEEP OTM γ-TAPER</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:#4d9fff;'>₹{_hv_deep_ce_ltp:.2f}</span>"
                f"</div>"
                # Far buy
                f"<div style='display:flex;justify-content:space-between;margin:.3rem 0;padding-top:.3rem;border-top:1px solid var(--border);'>"
                f"<span class='lbl'>BUY {BUY_LOTS}L &nbsp;<span class='strike-pill-buy'>{_hv_ce['strike']}</span> &nbsp;"
                f"<span class='date-pill' style='background:var(--bull-dim);color:var(--bull);border-color:var(--bull);'>📅 {_hv_far_exp or 'N/A'}</span>"
                f"&nbsp;<span style='color:var(--muted);font-size:9px;'>DTE {_hv_far_dte}d</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--bull);'>₹{_hv_ce_buy_ltp:.2f}</span>"
                f"</div>"
                f"</div>"
                f"<div style='margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--border);'>"
                f"<span class='lbl'>CE net: </span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:{'var(--bull)' if _hv_ce_collect>=0 else 'var(--bear)'};'>"
                f"{'Credit' if _hv_ce_collect>=0 else 'Debit'} ₹{abs(_hv_ce_collect):,.0f}</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

        with hv_c2:
            st.markdown(
                f"<div class='card card-pe'>"
                f"<div class='lbl'>📅 <span class='date-pill' style='border-color:var(--pe);color:var(--pe);'>{_hv_sell_exp}</span> &nbsp; PE SIDE</div>"
                f"<div style='margin-top:.5rem;'>"
                # Primary sell
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;'>"
                f"<span class='lbl'>SELL 2L &nbsp;<span class='strike-pill'>{_hv_pe['strike']}</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--pe);'>₹{_hv_pe['ltp']:.2f}</span>"
                f"<span style='font-size:10px;color:var(--muted);'>δ {_hv_pe['delta']:.3f}</span>"
                f"</div>"
                # Near -500 hedge
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;'>"
                f"<span class='lbl'>BUY 1L &nbsp;<span class='strike-pill-buy'>{_hv_pe2_strike}</span> <span style='color:var(--muted);font-size:9px;'>(-{WING_OFFSET} hedge)</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--bull);'>₹{_hv_pe2_ltp:.2f}</span>"
                f"</div>"
                # Deep OTM PE wing (γ-taper)
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;background:rgba(77,159,255,0.07);border-radius:4px;padding:2px 4px;'>"
                f"<span class='lbl'>BUY {_hv_deep_pe_lots}L &nbsp;<span class='strike-pill'>{_hv_deep_pe_strike}</span>"
                f" <span style='color:#4d9fff;font-size:9px;font-weight:700;'>🪽 DEEP OTM γ-TAPER</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:#4d9fff;'>₹{_hv_deep_pe_ltp:.2f}</span>"
                f"</div>"
                # Far buy
                f"<div style='display:flex;justify-content:space-between;margin:.3rem 0;padding-top:.3rem;border-top:1px solid var(--border);'>"
                f"<span class='lbl'>BUY {BUY_LOTS}L &nbsp;<span class='strike-pill-buy'>{_hv_pe['strike']}</span> &nbsp;"
                f"<span class='date-pill' style='background:var(--bull-dim);color:var(--bull);border-color:var(--bull);'>📅 {_hv_far_exp or 'N/A'}</span>"
                f"&nbsp;<span style='color:var(--muted);font-size:9px;'>DTE {_hv_far_dte}d</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--bull);'>₹{_hv_pe_buy_ltp:.2f}</span>"
                f"</div>"
                f"</div>"
                f"<div style='margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--border);'>"
                f"<span class='lbl'>PE net: </span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:{'var(--bull)' if _hv_pe_collect>=0 else 'var(--bear)'};'>"
                f"{'Credit' if _hv_pe_collect>=0 else 'Debit'} ₹{abs(_hv_pe_collect):,.0f}</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

        # Net summary row
        _hv_ce2_bs_delta = bs_delta(spot, _hv_ce2_strike, _T_near, _sigma, "CE")
        _hv_pe2_bs_delta = bs_delta(spot, _hv_pe2_strike, _T_near, _sigma, "PE")
        st.markdown(
            f"<div class='card' style='border-left:4px solid {'var(--bull)' if _hv_net>=0 else 'var(--bear)'};margin-top:.3rem;'>"
            f"<div style='display:flex;align-items:center;gap:16px;flex-wrap:wrap;'>"
            f"<div><span class='lbl'>Total Net Premium</span><br>"
            f"<span class='val-big' style='color:{'var(--bull)' if _hv_net>=0 else 'var(--bear)'};"
            f"'>{'Credit' if _hv_net>=0 else 'Debit'} ₹{abs(_hv_net):,.0f}</span></div>"
            f"<div><span class='lbl'>"
            f"SELL: CE {_hv_ce['strike']}×2L + PE {_hv_pe['strike']}×2L @ {_hv_sell_exp} (DTE {_hv_sell_dte}d)"
            f"&nbsp;·&nbsp; BUY hedge: CE {_hv_ce2_strike} (+{WING_OFFSET}) + PE {_hv_pe2_strike} (-{WING_OFFSET}) @ {_hv_sell_exp}"
            f"&nbsp;·&nbsp; 🪽 deep OTM: CE {_hv_deep_ce_strike}×{_hv_deep_ce_lots}L ₹{_hv_deep_ce_ltp:.2f} + PE {_hv_deep_pe_strike}×{_hv_deep_pe_lots}L ₹{_hv_deep_pe_ltp:.2f} (γ-taper)"
            f"&nbsp;·&nbsp; BUY monthly: CE {_hv_ce['strike']} + PE {_hv_pe['strike']} @ {_hv_far_exp or 'N/A'} (DTE {_hv_far_dte}d ≥ {_hv_sell_dte*3}d needed)</span><br>"
            f"<span style='font-family:var(--mono);font-size:10px;color:var(--muted);'>"
            f"δ: CE sell {_hv_ce['delta']:.3f} · CE+{WING_OFFSET} {_hv_ce2_bs_delta:.3f} &nbsp;|&nbsp; "
            f"PE sell {_hv_pe['delta']:.3f} · PE-{WING_OFFSET} {_hv_pe2_bs_delta:.3f}"
            f"</span></div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────
# PCR HISTORY
# ─────────────────────────────────────────────
st.markdown("<div class='sec-hdr'>📈 PCR History</div>", unsafe_allow_html=True)

if not _gh_tok:
    st.info("💡 Add `[github] token` to Streamlit secrets to enable PCR logging and history.")
else:
    # History already loaded into session cache earlier in the page
    _hist_rows = st.session_state.get("pcr_hist_rows", [])

    _today_str = datetime.now(IST).strftime("%Y-%m-%d")
    _near_hist = [r for r in _hist_rows
                  if r.get("date") == _today_str and r.get("expiry") == near_exp
                  and r.get("expiry_type") == "near"]
    _far_hist  = [r for r in _hist_rows
                  if r.get("date") == _today_str and r.get("expiry") == far_exp
                  and r.get("expiry_type") == "far"]

    # ── Intraday SVG chart ────────────────────────────────────────────────
    def _pcr_svg(near_rows, far_rows, width=900, height=200):
        all_rows   = near_rows + far_rows
        if not all_rows:
            return None
        times_str  = sorted(set(r["timestamp"] for r in all_rows))
        # Map timestamps to x positions
        n          = len(times_str)
        if n == 0:
            return None
        t_idx      = {t: i for i, t in enumerate(times_str)}
        mg         = {"l": 48, "r": 16, "t": 24, "b": 36}
        pw         = width  - mg["l"] - mg["r"]
        ph         = height - mg["t"] - mg["b"]

        def safe_f(v):
            try: return float(v)
            except: return None

        def _pts(rows):
            pts = []
            for r in sorted(rows, key=lambda x: x["timestamp"]):
                v = safe_f(r.get("pcr_range"))
                if v is not None:
                    pts.append((r["timestamp"], v))
            return pts

        near_pts = _pts(near_rows)
        far_pts  = _pts(far_rows)
        all_vals = [v for _, v in near_pts + far_pts]
        if not all_vals:
            return None

        ymin = max(0, min(all_vals) - 0.15)
        ymax = max(all_vals) + 0.15

        def tx(ts): return mg["l"] + (t_idx[ts] / max(n - 1, 1)) * pw
        def ty(v):  return mg["t"] + ph - ((v - ymin) / max(ymax - ymin, 0.01)) * ph

        svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
               f'style="width:100%;height:{height}px;background:#0a0e1a;border-radius:8px;'
               f'border:1px solid #1c2840;">']

        # Grid lines at PCR 1.0 and 1.3
        for ref_v, ref_col, ref_lbl in [(1.0, "#ffc940", "1.0"), (1.3, "#00e676", "1.3")]:
            if ymin <= ref_v <= ymax:
                ry = ty(ref_v)
                svg.append(f'<line x1="{mg["l"]}" y1="{ry}" x2="{width-mg["r"]}" y2="{ry}" '
                           f'stroke="{ref_col}" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>')
                svg.append(f'<text x="{mg["l"]-4}" y="{ry+4}" font-size="9" fill="{ref_col}" '
                           f'text-anchor="end">{ref_lbl}</text>')

        # Y-axis label
        svg.append(f'<text x="12" y="{mg["t"] + ph//2}" font-size="9" fill="#5a7090" '
                   f'text-anchor="middle" transform="rotate(-90,12,{mg["t"]+ph//2})">PCR</text>')

        # X-axis ticks (every ~5th label to avoid crowding)
        step = max(1, n // 8)
        for i, t in enumerate(times_str):
            if i % step == 0:
                x = mg["l"] + (i / max(n - 1, 1)) * pw
                lbl = t[11:16] if len(t) > 11 else t
                svg.append(f'<text x="{x}" y="{height - 6}" font-size="8" fill="#4a6080" '
                           f'text-anchor="middle">{lbl}</text>')

        def _draw_line(pts, col, label):
            if len(pts) < 2:
                return
            coords = " ".join(f"{tx(t)},{ty(v)}" for t, v in pts)
            svg.append(f'<polyline points="{coords}" fill="none" stroke="{col}" '
                       f'stroke-width="2" opacity="0.9"/>')
            # Last point dot + label
            last_t, last_v = pts[-1]
            lx, ly = tx(last_t), ty(last_v)
            svg.append(f'<circle cx="{lx}" cy="{ly}" r="3" fill="{col}"/>')
            svg.append(f'<text x="{lx+5}" y="{ly+4}" font-size="9" fill="{col}" '
                       f'font-weight="700">{last_v:.2f}</text>')

        _draw_line(near_pts, "#4d9fff", f"Near {near_exp}")
        _draw_line(far_pts,  "#cc66ff", f"Far  {far_exp}")

        # Legend
        svg.append(f'<circle cx="{mg["l"]+10}" cy="{mg["t"]+8}" r="4" fill="#4d9fff"/>')
        svg.append(f'<text x="{mg["l"]+18}" y="{mg["t"]+12}" font-size="9" fill="#4d9fff">Near {near_exp}</text>')
        svg.append(f'<circle cx="{mg["l"]+130}" cy="{mg["t"]+8}" r="4" fill="#cc66ff"/>')
        svg.append(f'<text x="{mg["l"]+138}" y="{mg["t"]+12}" font-size="9" fill="#cc66ff">Far {far_exp}</text>')

        svg.append("</svg>")
        return "\n".join(svg)

    _chart = _pcr_svg(_near_hist, _far_hist)
    if _chart:
        st.markdown(_chart, unsafe_allow_html=True)
    else:
        st.caption(f"No intraday data yet — PCR is recorded every {_refresh_mins} min during market hours.")

    # ── Recent readings table (last 20 near + last 20 far) ────────────────
    _ph1, _ph2 = st.columns(2)
    def _pcr_col(v):
        if v >= 1.1: return "var(--bull)"
        if v < 0.9:  return "var(--bear)"
        return "var(--gold)"

    def _hist_table(rows, title, expiry, sent_col):
        last20 = sorted(rows, key=lambda r: r.get("timestamp", ""), reverse=True)[:20]
        if not last20:
            return f"<div class='card'><div class='lbl'>{title}</div><div class='lbl'>No data</div></div>"
        row_parts = []
        for r in last20:
            t_lbl   = r.get("timestamp", "")[-5:] if len(r.get("timestamp","")) >= 5 else r.get("timestamp","")
            pcr_v   = float(r.get("pcr_range", 0) or 0)
            atm_v   = float(r.get("pcr_atm",   0) or 0)
            ce_v    = float(r.get("ce_oi_L",    0) or 0)
            pe_v    = float(r.get("pe_oi_L",    0) or 0)
            pcr_c   = _pcr_col(pcr_v)
            row_parts.append(
                f"<tr>"
                f"<td style='padding:2px 6px;font-family:var(--mono);font-size:11px;color:var(--muted);'>{t_lbl}</td>"
                f"<td style='padding:2px 6px;font-family:var(--mono);font-size:12px;font-weight:700;color:{pcr_c};'>{pcr_v:.2f}</td>"
                f"<td style='padding:2px 6px;font-family:var(--mono);font-size:11px;color:var(--ce);'>{atm_v:.2f}</td>"
                f"<td style='padding:2px 6px;font-family:var(--mono);font-size:10px;color:var(--muted);'>{ce_v:.1f}L</td>"
                f"<td style='padding:2px 6px;font-family:var(--mono);font-size:10px;color:var(--pe);'>{pe_v:.1f}L</td>"
                f"</tr>"
            )
        rows_html = "".join(row_parts)
        return (
            f"<div class='card' style='border-left:4px solid {sent_col};'>"
            f"<div class='lbl'>{title} · <span class='date-pill'>{expiry}</span></div>"
            f"<table style='width:100%;border-collapse:collapse;margin-top:.4rem;'>"
            f"<tr>"
            f"<th style='font-size:9px;color:var(--muted);text-align:left;padding:2px 6px;'>TIME</th>"
            f"<th style='font-size:9px;color:var(--muted);text-align:left;padding:2px 6px;'>PCR±10</th>"
            f"<th style='font-size:9px;color:var(--muted);text-align:left;padding:2px 6px;'>ATM PCR</th>"
            f"<th style='font-size:9px;color:var(--muted);text-align:left;padding:2px 6px;'>CE OI</th>"
            f"<th style='font-size:9px;color:var(--muted);text-align:left;padding:2px 6px;'>PE OI</th>"
            f"</tr>"
            f"{rows_html}"
            f"</table></div>"
        )

    with _ph1:
        st.markdown(_hist_table(_near_hist, "NEAR EXPIRY", near_exp, "var(--ce)"),
                    unsafe_allow_html=True)
    with _ph2:
        st.markdown(_hist_table(_far_hist, "FAR EXPIRY", far_exp, "var(--pe)"),
                    unsafe_allow_html=True)

    # Multi-day historical chart (last 5 days)
    with st.expander("📅 Historical PCR (last 5 days)", expanded=False):
        _hist5_near = [r for r in _hist_rows
                       if r.get("expiry_type") == "near" and r.get("expiry") == near_exp]
        _hist5_far  = [r for r in _hist_rows
                       if r.get("expiry_type") == "far"  and r.get("expiry") == far_exp]
        _hist5_chart = _pcr_svg(_hist5_near[-200:], _hist5_far[-200:], width=900, height=240)
        if _hist5_chart:
            st.markdown(_hist5_chart, unsafe_allow_html=True)
        else:
            st.caption("No historical data available yet.")

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
        st.metric("VIX (avg)", f"{_eff_vix:.2f}",
                  f"open {_open_vix:.2f} · cur {_curr_vix:.2f}")
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
