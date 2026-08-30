"""Configuration.

Model IDs are resolved at runtime rather than hardcoded: a wrong model string
fails at call time, not import time, which is a miserable way to discover a
typo thirty seconds into a live demo.
"""

import os
import tempfile
import time
import uuid
from datetime import date

from dotenv import load_dotenv

load_dotenv()

def _api_key() -> str | None:
    """The key, from wherever this deployment keeps it.

    Locally that is a .env file. On Streamlit Community Cloud there is no .env
    -- the key is typed into the app's Secrets box, which arrives as
    st.secrets. Reading only the environment there gives "GEMINI_API_KEY is not
    set" on a deployment where the key is, in fact, set, which is a miserable
    thing to debug from a hosting dashboard.
    """
    from_env = os.getenv("GEMINI_API_KEY")
    if from_env:
        return from_env
    try:
        import streamlit as st
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        # No Streamlit, no secrets file, or no such key. All mean "not set",
        # and the caller says so in words the reader can act on.
        return None


GEMINI_API_KEY = _api_key()

# Optional pins. Leave unset and the client picks the best available model
# from the preference lists in llm.py.
MODEL_EXTRACT_PIN = os.getenv("RFX_MODEL_EXTRACT")
MODEL_ANALYST_PIN = os.getenv("RFX_MODEL_ANALYST")

# Which branch of the family each job wants. Reading documents is a fast,
# high-volume job and goes to Flash; the analyst reasons over a whole
# comparison and goes to Pro. Neither is a hard requirement -- if the key
# cannot see one, the other is used.
#
# There is deliberately no hardcoded list of version numbers here. There was,
# and it aged badly twice in one afternoon: the list still named 2.5-pro, which
# Google now refuses to serve to new keys, while the model it recommends
# instead -- 3.1-pro-preview -- was not on the list at all, so it was never
# tried. Versions are read out of the live model names and the newest wins.
EXTRACT_FAMILY = os.getenv("RFX_EXTRACT_FAMILY", "flash")
ANALYST_FAMILY = os.getenv("RFX_ANALYST_FAMILY", "pro")

DB_PATH = os.getenv("RFX_DB", "rfx.db")

# One database per browser session, not one per server.
#
# Everything else in this application is careful to keep one buyer's work out
# of another's -- the item list, the draft and the rate date all live in
# session state, with comments saying why. The database did not: every session
# wrote to the same rfx.db. Two people on one deployed link is the ordinary
# case for a shared demo, and there the second person's upload dropped and
# recreated the tables under the first person's feet, so their analyst answered
# questions about someone else's suppliers -- or hit "database is locked" while
# both wrote at once. Neither is visible on screen, which is what makes it bad.
SESSION_DB_DIR = os.getenv(
    "RFX_DB_DIR", os.path.join(tempfile.gettempdir(), "rfx_sessions"))
SESSION_DB_MAX_AGE_HOURS = float(os.getenv("RFX_DB_MAX_AGE_HOURS", "12"))


def _sweep_session_dbs() -> None:
    """Delete databases from sessions that ended long ago.

    Best-effort on purpose: a file that cannot be removed (still open, or
    another process's) must never stop the caller from getting a path.
    """
    cutoff = time.time() - SESSION_DB_MAX_AGE_HOURS * 3600
    try:
        names = os.listdir(SESSION_DB_DIR)
    except OSError:
        return
    for name in names:
        if not name.endswith(".db"):
            continue
        path = os.path.join(SESSION_DB_DIR, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def new_session_db_path() -> str:
    """A private database path for one browser session."""
    try:
        os.makedirs(SESSION_DB_DIR, exist_ok=True)
        _sweep_session_dbs()
        return os.path.join(SESSION_DB_DIR, f"rfx_{uuid.uuid4().hex}.db")
    except OSError:
        # No writable temp directory (a locked-down container). Sharing one
        # file is worse than isolation but far better than no application.
        return DB_PATH

# --- money -----------------------------------------------------------------
BASE_CURRENCY = os.getenv("RFX_BASE_CURRENCY", "INR")
# Deliberately a fixed, dated table rather than a live feed. A procurement
# comparison must be reproducible: the same files must give the same answer
# tomorrow. The rate and its date are printed next to every converted number.
#
# The RATES are fixed. The DATE they are taken to hold on is today, because a
# date written into the file ages: three weeks after it was set, the sidebar was
# telling every visitor their rates were 21 days old and to confirm before
# awarding -- alarming, unactionable, and a fact about this file rather than
# about their data. RFX_FX_DATE still pins it when a comparison has to be
# reproduced against one specific day's rate, which is what .env.example
# documents; the buyer can also set the date on screen. Whichever date applies
# is stamped on every converted figure and carried into the audit export.
FX_DATE = os.getenv("RFX_FX_DATE") or date.today().isoformat()
FX_TO_BASE: dict[str, float] = {
    "INR": 1.0,
    "USD": float(os.getenv("RFX_USD_INR", "87.50")),
    "EUR": float(os.getenv("RFX_EUR_INR", "94.20")),
    "GBP": float(os.getenv("RFX_GBP_INR", "111.40")),
}

# --- extraction limits -----------------------------------------------------
MAX_DOC_CHARS = int(os.getenv("RFX_MAX_DOC_CHARS", "180000"))

# --- test-only -------------------------------------------------------------
# Replays recorded extractions instead of calling the model. Used ONLY by the
# offline test suite so the matcher/normaliser can be verified without network.
# The demo path never sets this; see README.
OFFLINE_FIXTURES = os.getenv("RFX_OFFLINE_FIXTURES", "0") == "1"
FIXTURE_DIR = os.getenv("RFX_FIXTURE_DIR", "tests/fixtures")


def require_api_key() -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError(
            'GEMINI_API_KEY is not set.\n\n'
            'Running on your own machine: copy .env.example to .env and put '
            'your key in it.\n\n'
            'Deployed on Streamlit Community Cloud: open the app menu (top '
            'right), then Settings, then Secrets, and add this one line:\n'
            '    GEMINI_API_KEY = "your-key-here"'
        )
    return GEMINI_API_KEY
