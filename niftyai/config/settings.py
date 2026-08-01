"""
NiftyAI-Pro — prediction module configuration.

SCOPE NOTE: this is the probability engine only, not the full platform. It
answers one question: given the CE and PE legs on the SPCL card, what is the
probability each one's premium reaches its Tg target within the horizon?

DATA REALITY (measured 2026-08-01, do not assume otherwise):
  • An option's 5-min history begins at its LISTING date, not N days back.
    NSE_FO|65852 (24350 CE, exp 2026-08-04) has daily candles from 2026-07-01
    only; June and May return HTTP 200 with zero candles.
  • v3 range requests are capped at ~1 month — beyond that the API returns
    UDAPI1148 "Invalid date range". Harvest in <=30 day chunks.
  • EXPIRED contracts are dropped from the instrument dump, so their history
    becomes unreachable. The archive step exists to outlive that.
"""

# ── Underlying ───────────────────────────────────────────────────────────────
UNDERLYING_KEY = "NSE_INDEX|Nifty 50"
SEGMENT        = "NSE_FO"
STRIKE_STEP    = 50

# ── Prediction problem ───────────────────────────────────────────────────────
# Label: did the option's HIGH reach entry_price * (1 + TARGET_PCT) within
# HORIZON_BARS 5-min bars? A touch, not a close-above — matches how a Tg is hit.
BAR_MINUTES   = 5
HORIZON_BARS  = 75          # one full session (09:15-15:30)
TARGET_PCT    = 0.2611      # the Tg uplift used on the card

# Training rows are dropped when the premium is too small for the move to be
# meaningful — a 2.00 -> 2.52 tick is noise, not a signal.
MIN_PREMIUM   = 5.0
MIN_BARS_PER_CONTRACT = 120

# ── Harvest ──────────────────────────────────────────────────────────────────
MAX_RANGE_DAYS   = 28       # under the ~1 month API cap
EXPIRIES_TO_SCAN = 4        # nearest N expiries
MAX_STRIKE_DIST  = 1500     # ignore deep wings: illiquid, stale candles

# ── Model ────────────────────────────────────────────────────────────────────
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

# Time-ordered split: the validation set is strictly LATER than training, so
# the score reflects forecasting rather than interpolation.
VALID_FRACTION = 0.25

# ── Paths ────────────────────────────────────────────────────────────────────
ARCHIVE_DIR = "niftyai/datasets/candles"
MODEL_PATH  = "niftyai/models_saved/hit_lgbm.txt"
META_PATH   = "niftyai/models_saved/hit_lgbm_meta.json"
PRED_PATH   = "niftyai/prediction/latest.json"
