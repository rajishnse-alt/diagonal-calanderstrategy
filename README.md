# diagonal-calanderstrategy

NIFTY Diagonal / Calendar Spread Builder — Streamlit + Upstox API

## Strategy

| Leg | Action | Strike | Expiry | Lots |
|-----|--------|--------|--------|------|
| Short | SELL CE | ATM + 6 steps (ATM+300) | Current week | N |
| Short | SELL PE | ATM − 6 steps (ATM−300) | Current week | N |
| Long  | BUY  CE | Far strike @ ~50% of sold LTP | 5+ weeks out | 2 |
| Long  | BUY  PE | Far strike @ ~50% of sold LTP | 5+ weeks out | 2 |

The long legs provide tail protection while the weekly short premium funds them.

## Setup

```bash
pip install streamlit requests pytz scipy
streamlit run diagonal_strategy.py
```

## Secrets

Create `.streamlit/secrets.toml`:

```toml
[upstox]
api_key      = "your_api_key"
api_secret   = "your_api_secret"
redirect_uri = "http://localhost:8501"
# Optional — skip daily OAuth login:
# access_token = "your_access_token"
```

## Features

- Live NIFTY option chain (Upstox API, cached 2 min)
- Combined near + far expiry chain table with LTP ratio % shown inline
- Auto-ranks far strikes by proximity to target LTP %
- Adjustable OTM steps (default 6 = 300 pts) and LTP ratio % slider
- Net credit/debit, breakevens, payoff SVG at near expiry
- Sidebar summary with all legs + metrics
