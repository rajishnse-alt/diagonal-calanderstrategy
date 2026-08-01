"""
NiftyAI-Pro — prediction module configuration.

SCOPE: the probability engine only, not the full platform. It answers one
question — given a CE/PE leg, what is the probability its premium reaches a
target within the horizon?

═══════════════════════════════════════════════════════════════════════════
MEASURED API BEHAVIOUR (probed 2026-08-01 — do not assume otherwise)
═══════════════════════════════════════════════════════════════════════════
Max span of ONE request, by unit. Exceeding it returns HTTP 400 UDAPI1148
("Invalid date range"), NOT a truncated result — so backfill must chunk:
    minutes/5   28d works, 35d fails
    hours/1     90d works, 100d fails
    days/1      2000d works (returned 1,358 bars back to 2021-02)

History depth, walking backwards in chunks:
    INDEX 5-min   available at least 24 months back (1,425 bars at the
                  24-month mark) -> 2 years of intraday IS reachable
    INDEX daily   back to 2021
    OPTION        starts at the contract's LISTING date, nothing earlier.
                  Near weeklies have ~1 month (NSE_FO|65852 listed 2026-07-01).
                  Long-dated contracts carry far more: the 2027-06-29 expiry
                  was listed ~2024-11-01 with 364 daily bars.

EXPIRED contracts are dropped from the instrument dump entirely, so their
history becomes unreachable. That is why the archive exists.
═══════════════════════════════════════════════════════════════════════════
"""

# ── Instruments ──────────────────────────────────────────────────────────────
# Verified live 2026-08-01. Note SENSEX options are on BSE_FO, not NSE_FO —
# a single hardcoded segment silently returns ZERO contracts for it.
INSTRUMENTS = {
    "NIFTY": {
        "underlying_key": "NSE_INDEX|Nifty 50",
        "segment":        "NSE_FO",
        "strike_step":    50,
        "max_strike_dist": 600,      # +/-12 strikes
        "expiries":       2,
    },
    "BANKNIFTY": {
        "underlying_key": "NSE_INDEX|Nifty Bank",
        "segment":        "NSE_FO",
        "strike_step":    100,
        "max_strike_dist": 1200,     # +/-12 strikes
        # No weeklies — nearest expiry is monthly. Fewer independent contract
        # lifecycles per month than NIFTY/SENSEX, so take every live expiry and
        # let the DAILY archive accumulate breadth over time instead.
        "expiries":       6,
    },
    "SENSEX": {
        "underlying_key": "BSE_INDEX|SENSEX",
        "segment":        "BSE_FO",
        "strike_step":    100,
        "max_strike_dist": 1200,     # +/-12 strikes
        "expiries":       2,
    },
}
DEFAULT_INSTRUMENT = "NIFTY"

# ── Prediction problem ───────────────────────────────────────────────────────
BAR_MINUTES   = 5
HORIZON_BARS  = 75          # one session (09:15-15:30)
TARGET_PCT    = 0.2611      # the Tg uplift on the card (reporting default only)

MIN_PREMIUM   = 5.0         # below this a +26% move is tick noise
MIN_BARS_PER_CONTRACT = 120

# ── Harvest / cache ──────────────────────────────────────────────────────────
MAX_SPAN_DAYS = {"minutes": 28, "hours": 90, "days": 2000}   # measured above
INDEX_HISTORY_DAYS  = 730    # 2 years of 5-min index history
OPTION_HISTORY_DAYS = 730    # capped by each contract's listing date anyway
EXPIRIES_TO_SCAN    = 2      # per-instrument override in INSTRUMENTS["expiries"]

# ARCHIVE SIZE IS THE BINDING CONSTRAINT, not runtime.
# Measured: month-partitioned parquet costs ~63 KB per contract-month. The
# original scope (+/-1500-3000 points, 6 expiries = 3,736 contracts) projected
# to ~228 MB/month, i.e. ~2.7 GB/year committed to git — past GitHub's 1 GB
# soft limit inside five months, and git history never shrinks.
# Bounded to strikes that a 75-bar intraday horizon can actually reach and to
# the nearest expiries, which cuts both the archive and the request count.

# Archive is partitioned by month so a closed month's file never changes again;
# git then stores it once instead of a new blob on every append.
ARCHIVE_DIR = "niftyai/datasets/candles"
ARCHIVE_FMT = "parquet"

# ── Model ────────────────────────────────────────────────────────────────────
# One model PER INSTRUMENT, not one shared model with an instrument flag. The
# two strongest features are f_dte and f_dow, and the expiry cycles genuinely
# differ: NIFTY expires weekly (2026-08-04, 08-11), SENSEX weekly on a
# different weekday (08-06, 08-13), BANKNIFTY has no weeklies at all — its
# nearest expiry is monthly (2026-08-25). Sharing one model would force three
# conflicting cycles through the same splits.
LGBM_PARAMS = {
    "objective":        "binary",
    "learning_rate":    0.05,
    "num_leaves":       63,
    "min_child_samples": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq":     1,
    "verbosity":        -1,
    "n_jobs":           -1,
}
NUM_BOOST_ROUND = 400
EARLY_STOPPING  = 40
VALID_FRACTION  = 0.25       # time-ordered, validation strictly later


def paths(instrument: str) -> dict:
    """Per-instrument artefact paths — nothing is shared between instruments."""
    i = instrument.upper()
    return {
        "archive":  f"{ARCHIVE_DIR}/{i}",
        "dataset":  f"niftyai/datasets/{i}_train.parquet",
        "model":    f"niftyai/models_saved/{i}_hit_lgbm.txt",
        "meta":     f"niftyai/models_saved/{i}_hit_lgbm_meta.json",
        "pred":     f"niftyai/prediction/{i}_latest.json",
    }


def cfg(instrument: str) -> dict:
    i = instrument.upper()
    if i not in INSTRUMENTS:
        raise SystemExit(f"unknown instrument {instrument!r}; "
                         f"known: {', '.join(INSTRUMENTS)}")
    return INSTRUMENTS[i]
