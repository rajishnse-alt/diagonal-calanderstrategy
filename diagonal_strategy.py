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
PCR_LOG_INTERVAL= 300  # seconds between writes (5 min)
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


def fetch_prev_day_candle(tok, instrument_key):
    """
    Fetch the most recent completed trading day's OHLC + OI candle for an option.
    Upstox historical-candle returns [ts, open, high, low, close, volume, oi].
    Returns dict {open, high, low, close, oi} or None on failure.
    """
    try:
        today     = datetime.now(IST).date()
        from_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        to_date   = today.strftime("%Y-%m-%d")
        enc_key   = urllib.parse.quote(instrument_key, safe="")
        url = (f"https://api.upstox.com/v2/historical-candle/"
               f"{enc_key}/day/{to_date}/{from_date}")
        r = requests.get(url, headers={"Accept": "application/json",
                                        "Authorization": f"Bearer {tok}"}, timeout=10)
        candles = (r.json().get("data") or {}).get("candles") or []
        # candle = [ts, open, high, low, close, volume, oi]
        today_str = today.isoformat()
        prev = sorted(
            [c for c in candles if str(c[0])[:10] < today_str],
            key=lambda c: c[0], reverse=True
        )
        if not prev:
            return None
        c = prev[0]
        return {
            "date":  str(c[0])[:10],
            "open":  float(c[1]),
            "high":  float(c[2]),
            "low":   float(c[3]),
            "close": float(c[4]),
            "oi":    float(c[6]) if len(c) > 6 else 0.0,
        }
    except Exception:
        return None


def get_atm_instrument_keys(chain_data, atm_strike):
    """Extract CE and PE instrument keys for the ATM strike from chain data."""
    for row in chain_data:
        if int(float(row.get("strike_price", 0))) == int(atm_strike):
            ce_key = (row.get("call_options") or {}).get("instrument_key")
            pe_key = (row.get("put_options")  or {}).get("instrument_key")
            return ce_key, pe_key
    return None, None


def calc_spp(tok, chain_data, atm_strike):
    """
    SPP (UIP concept) — matches reference methodology exactly:
      1. Previous trading day's H, L, OI for ATM CE and PE (via Upstox historical candle)
      2. ce_median = (ce_high + ce_low) / 2
         pe_median = (pe_high + pe_low) / 2
         spp = (ce_median × ce_oi + pe_median × pe_oi) / (ce_oi + pe_oi)

    Returns: (spp, ce_h, ce_l, pe_h, pe_l, ce_oi_L, pe_oi_L, date_used) or all-None on failure.
    """
    ce_key, pe_key = get_atm_instrument_keys(chain_data, atm_strike)
    if not ce_key or not pe_key:
        return None, None, None, None, None, None, None, None

    ce_can = fetch_prev_day_candle(tok, ce_key)
    pe_can = fetch_prev_day_candle(tok, pe_key)
    if not ce_can or not pe_can:
        return None, None, None, None, None, None, None, None

    ce_h, ce_l, ce_oi = ce_can["high"], ce_can["low"], ce_can["oi"]
    pe_h, pe_l, pe_oi = pe_can["high"], pe_can["low"], pe_can["oi"]

    ce_oi_L = ce_oi / 1e5
    pe_oi_L = pe_oi / 1e5

    ce_med = (ce_h + ce_l) / 2
    pe_med = (pe_h + pe_l) / 2
    tot_oi = ce_oi + pe_oi
    spp = (ce_med * ce_oi + pe_med * pe_oi) / tot_oi if tot_oi > 0 else (ce_med + pe_med) / 2

    return round(spp, 2), ce_h, ce_l, pe_h, pe_l, round(ce_oi_L, 2), round(pe_oi_L, 2), ce_can["date"]


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

# ── VIX (early fetch — needed for strategy banner) ──────────────────────────
_open_vix, _curr_vix, _vix_err_early = fetch_vix(token)
if _vix_err_early == "token_expired":
    del st.session_state["access_token"]; st.rerun()

if _open_vix and _curr_vix:
    _eff_vix   = (_open_vix + _curr_vix) / 2
    _vix_ok    = True
else:
    _eff_vix   = 0.0
    _vix_ok    = False

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
_,    _,   far_ce,  far_pe,  far_ce_oi,  far_pe_oi,  far_ce_oi_chg,  far_pe_oi_chg  = parse_chain(far_raw)

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

# SPP (UIP concept) — computed ONCE per calendar day, keyed ONLY by date.
# ATM used is whatever it is on first computation (open/premarket ATM).
# Never recomputed intraday even if spot crosses a strike boundary.
_today_str = now.date().isoformat()
_spp_cache = st.session_state.get("spp_cache", {})
if _spp_cache.get("date") == _today_str:
    # Locked for the day — restore cached values
    _spp        = _spp_cache["spp"]
    _spp_atm    = _spp_cache["atm"]
    _spp_ce_h   = _spp_cache["ce_h"]
    _spp_ce_l   = _spp_cache["ce_l"]
    _spp_pe_h   = _spp_cache["pe_h"]
    _spp_pe_l   = _spp_cache["pe_l"]
    _spp_ce_oi_L= _spp_cache["ce_oi_L"]
    _spp_pe_oi_L= _spp_cache["pe_oi_L"]
    _spp_src    = _spp_cache["src"]
else:
    # First call of the day — compute and lock
    with st.spinner("Computing SPP…"):
        _spp, _spp_ce_h, _spp_ce_l, _spp_pe_h, _spp_pe_l, _spp_ce_oi_L, _spp_pe_oi_L, _spp_src = \
            calc_spp(token, near_raw, atm)
    _spp_atm = atm  # record the ATM used (open-price ATM)
    if _spp is not None:
        st.session_state["spp_cache"] = {
            "date": _today_str, "atm": _spp_atm,
            "spp": _spp, "ce_h": _spp_ce_h, "ce_l": _spp_ce_l,
            "pe_h": _spp_pe_h, "pe_l": _spp_pe_l,
            "ce_oi_L": _spp_ce_oi_L, "pe_oi_L": _spp_pe_oi_L,
            "src": _spp_src,
        }

# ── PCR logging to GitHub CSV (throttled: market hours, once per 5 min) ─────
_gh_tok = None
try:
    _gh_tok = st.secrets["github"]["token"]
except Exception:
    pass

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
    _ce_sum = sum(near_ce.get(float(atm + i * STEP), 0) for i in range(3))
    _pe_sum = sum(near_pe.get(float(atm - i * STEP), 0) for i in range(3))
    _sqrt_ce  = math.sqrt(_ce_sum) if _ce_sum > 0 else 0
    _sqrt_pe  = math.sqrt(_pe_sum) if _pe_sum > 0 else 0
    _sqrt_sig = "BEARISH" if _sqrt_ce > _sqrt_pe else ("BULLISH" if _sqrt_pe > _sqrt_ce else "NEUTRAL")
    _sqrt_arrow = "▼" if _sqrt_sig == "BEARISH" else ("▲" if _sqrt_sig == "BULLISH" else "→")
    _sqrt_col   = "var(--bear)" if _sqrt_sig == "BEARISH" else ("var(--bull)" if _sqrt_sig == "BULLISH" else "var(--muted)")
    _sqrt_expr  = (
        f"√CE {_sqrt_ce:.2f} &gt; √PE {_sqrt_pe:.2f}" if _sqrt_sig == "BEARISH"
        else f"√PE {_sqrt_pe:.2f} &gt; √CE {_sqrt_ce:.2f}" if _sqrt_sig == "BULLISH"
        else f"√CE {_sqrt_ce:.2f} = √PE {_sqrt_pe:.2f}"
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
            f"<span style='font-family:var(--mono);font-size:10px;color:var(--muted);margin-left:6px;'>{_sqrt_expr}</span>"
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
            f"<span style='font-family:var(--mono);font-size:10px;color:var(--muted);margin-left:6px;'>{_sqrt_expr}</span>"
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
            f"<div class='val-big val-gold'>₹{_spp:,.2f}</div>"
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
            f"</div></div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='card'><div class='lbl'>SPP · UIP Reference</div>"
            "<div class='val-big' style='color:var(--muted);'>N/A</div>"
            "<div class='lbl'>H/L data not yet available</div></div>",
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
    else:
        with st.spinner(f"Loading sell chain {_hv_sell_exp}…"):
            _hv_sell_raw, _hv_sell_err = fetch_chain(token, _hv_sell_exp)
        if _hv_sell_raw:
            _, _, _hv_sell_ce, _hv_sell_pe, _, _, _, _ = parse_chain(_hv_sell_raw)
        else:
            st.warning(f"⚠️ Could not load chain for {_hv_sell_exp}: {_hv_sell_err}")
            _hv_sell_ce, _hv_sell_pe = near_ce, near_pe

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

        # Extra OTM BUY legs  +500 / -500
        _hv_ce2_strike = int(round((_hv_ce["strike"] + 500) / STEP) * STEP)
        _hv_pe2_strike = int(round((_hv_pe["strike"] - 500) / STEP) * STEP)
        _hv_ce2_ltp    = _hv_sell_ce.get(float(_hv_ce2_strike), 0)
        _hv_pe2_ltp    = _hv_sell_pe.get(float(_hv_pe2_strike), 0)

        # Far expiry selection: DTE >= 2 × sell_DTE
        _hv_far_exp = select_hv_far_expiry(all_exp, _hv_sell_exp, _hv_sell_dte)
        _hv_far_dte = (
            (datetime.strptime(_hv_far_exp, "%Y-%m-%d").date() - now.date()).days
            if _hv_far_exp else 0
        )

        # Fetch far chain — reuse existing if same expiry, else fetch fresh
        if _hv_far_exp and _hv_far_exp == far_exp:
            _hv_far_ce, _hv_far_pe = far_ce, far_pe
        elif _hv_far_exp:
            with st.spinner(f"Loading far chain {_hv_far_exp}…"):
                _hv_far_raw, _hv_far_err = fetch_chain(token, _hv_far_exp)
            if _hv_far_raw:
                _, _, _hv_far_ce, _hv_far_pe, _, _, _, _ = parse_chain(_hv_far_raw)
            else:
                _hv_far_ce, _hv_far_pe = {}, {}
        else:
            _hv_far_ce, _hv_far_pe = {}, {}

        # Buy LTPs (same strike, far expiry)
        _hv_ce_buy_ltp = _hv_far_ce.get(float(_hv_ce["strike"]), 0)
        _hv_pe_buy_ltp = _hv_far_pe.get(float(_hv_pe["strike"]), 0)

        # Net premium: sell 2L primary; BUY 1L ±500 + BUY 1L far monthly (all buys are costs)
        # CE: +collect(2L primary) - pay(1L +500 buy) - pay(1L far buy)
        # PE: +collect(2L primary) - pay(1L -500 buy) - pay(1L far buy)
        _hv_ce_collect = (_hv_ce["ltp"] * 2 - _hv_ce2_ltp * 1 - _hv_ce_buy_ltp * 1) * LOT_SIZE
        _hv_pe_collect = (_hv_pe["ltp"] * 2 - _hv_pe2_ltp * 1 - _hv_pe_buy_ltp * 1) * LOT_SIZE
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
                # Extra OTM buy (+300)
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;'>"
                f"<span class='lbl'>BUY 1L &nbsp;<span class='strike-pill-buy'>{_hv_ce2_strike}</span> <span style='color:var(--muted);font-size:9px;'>(+500 hedge)</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--bull);'>₹{_hv_ce2_ltp:.2f}</span>"
                f"</div>"
                # Far buy
                f"<div style='display:flex;justify-content:space-between;margin:.3rem 0;padding-top:.3rem;border-top:1px solid var(--border);'>"
                f"<span class='lbl'>BUY 1L &nbsp;<span class='strike-pill-buy'>{_hv_ce['strike']}</span> &nbsp;"
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
                # Extra OTM buy (-300)
                f"<div style='display:flex;justify-content:space-between;margin:.2rem 0;'>"
                f"<span class='lbl'>BUY 1L &nbsp;<span class='strike-pill-buy'>{_hv_pe2_strike}</span> <span style='color:var(--muted);font-size:9px;'>(-500 hedge)</span></span>"
                f"<span style='font-family:var(--mono);font-size:13px;font-weight:700;color:var(--bull);'>₹{_hv_pe2_ltp:.2f}</span>"
                f"</div>"
                # Far buy
                f"<div style='display:flex;justify-content:space-between;margin:.3rem 0;padding-top:.3rem;border-top:1px solid var(--border);'>"
                f"<span class='lbl'>BUY 1L &nbsp;<span class='strike-pill-buy'>{_hv_pe['strike']}</span> &nbsp;"
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
            f"&nbsp;·&nbsp; BUY hedge: CE {_hv_ce2_strike} + PE {_hv_pe2_strike} (±500) @ {_hv_sell_exp}"
            f"&nbsp;·&nbsp; BUY monthly: CE {_hv_ce['strike']} + PE {_hv_pe['strike']} @ {_hv_far_exp or 'N/A'} (DTE {_hv_far_dte}d ≥ {_hv_sell_dte*3}d needed)</span><br>"
            f"<span style='font-family:var(--mono);font-size:10px;color:var(--muted);'>"
            f"δ: CE sell {_hv_ce['delta']:.3f} · CE+500 {_hv_ce2_bs_delta:.3f} &nbsp;|&nbsp; "
            f"PE sell {_hv_pe['delta']:.3f} · PE-500 {_hv_pe2_bs_delta:.3f}"
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
        st.caption("No intraday data yet — PCR is recorded every 5 min during market hours.")

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
