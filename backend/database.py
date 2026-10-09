"""
Insura - SQLite Database Layer (Dashboard Module)

Public API
----------
get_db()                         -> sqlite3.Connection  (thread-local)
init_db()                        -> None  (called once at app startup)
get_or_create_customer(username) -> dict
sync_enrollment_to_db(...)       -> None
save_chat_turn(...)              -> None
save_recommendation(...)         -> None
"""

import logging
import os
import re
import sqlite3
import threading
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger("insura.database")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(BASE_DIR, "insura_dashboard.db")
XLSX_PATH = os.path.join(BASE_DIR, "LIC_Policy_Details.xlsx")

# ---------------------------------------------------------------------------
# Thread-local connection pool
# ---------------------------------------------------------------------------

_local = threading.local()


def get_db() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS customers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL DEFAULT '',
    age           TEXT    NOT NULL DEFAULT '',
    phone         TEXT    NOT NULL DEFAULT '',
    email         TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS policies (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id       INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    policy_number     TEXT    NOT NULL,
    policy_name       TEXT    NOT NULL,
    enrollment_date   TEXT    NOT NULL DEFAULT (date('now')),
    status            TEXT    NOT NULL DEFAULT 'Active',
    premium_amount    REAL    NOT NULL DEFAULT 0.0,
    min_sum_assured   TEXT    NOT NULL DEFAULT '',
    payment_frequency TEXT    NOT NULL DEFAULT '',
    next_due_date     TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recommendations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    policy_name      TEXT    NOT NULL,
    reason           TEXT    NOT NULL DEFAULT '',
    recommended_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    session_id   TEXT    NOT NULL DEFAULT '',
    role         TEXT    NOT NULL CHECK(role IN ('user','assistant')),
    message      TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_customer ON chat_history(customer_id);
CREATE INDEX IF NOT EXISTS idx_chat_session  ON chat_history(session_id);

CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    body         TEXT    NOT NULL DEFAULT '',
    type         TEXT    NOT NULL DEFAULT 'info',
    is_read      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    filename     TEXT    NOT NULL,
    label        TEXT    NOT NULL DEFAULT '',
    file_path    TEXT    NOT NULL DEFAULT '',
    uploaded_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db() -> None:
    conn = get_db()
    conn.executescript(_DDL)
    conn.commit()
    logger.info("Dashboard SQLite DB initialised at: %s", DB_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row) if row else {}


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Policy lookup — reads LIC_Policy_Details.xlsx
# ---------------------------------------------------------------------------

# Cache so we only parse the file once per process
_policy_cache: dict | None = None


def _load_policy_index() -> dict:
    """
    Build a lookup dict from the INDEX sheet:
        canonical_name_lower -> {
            "policy_name":    "LIC's New Jeevan Anand",
            "plan_number":    "715",
            "sheet_name":     "New Jeevan Anand",
            "policy_type":    "Endowment",
        }
    Also stores the Excel sheet names mapped to their display names.
    """
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache

    _policy_cache = {}

    if not os.path.exists(XLSX_PATH):
        logger.warning("LIC_Policy_Details.xlsx not found — policy lookup disabled.")
        return _policy_cache

    try:
        xl   = pd.ExcelFile(XLSX_PATH)
        idx  = pd.read_excel(XLSX_PATH, sheet_name="INDEX", header=None)

        # INDEX columns after row 0 header:
        #   col0=Sr, col1=Policy Name, col2=Plan No., col3=UIN, col4=Policy Type
        # Row 0 is the real header row (values like 'Sr.', 'Policy Name', ...)
        # Rows with NaN in col1 are category headers — skip them.

        sheet_names = xl.sheet_names

        for _, row in idx.iterrows():
            raw_name = row.iloc[1] if len(row) > 1 else None
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue

            plan_no   = str(row.iloc[2]).strip() if len(row) > 2 else ""
            pol_type  = str(row.iloc[4]).strip() if len(row) > 4 else ""

            # Find the matching sheet (partial match since sheet names are truncated)
            # Strip the "LIC's " prefix for matching
            clean = raw_name.replace("LIC's ", "").replace("LIC's", "").strip()
            matched_sheet = ""
            for s in sheet_names:
                if s.lower().startswith(clean[:12].lower()):
                    matched_sheet = s
                    break
                # Also try first-word match
                if clean.split()[0].lower() in s.lower():
                    matched_sheet = s

            entry = {
                "policy_name": raw_name.strip(),
                "plan_number": plan_no if plan_no != "nan" else "",
                "sheet_name":  matched_sheet,
                "policy_type": pol_type if pol_type != "nan" else "",
            }

            # Key by lowercased full name and also short name without "LIC's"
            _policy_cache[raw_name.strip().lower()] = entry
            _policy_cache[clean.lower()]            = entry

        logger.info("Loaded %d policies from INDEX sheet.", len(_policy_cache) // 2)

    except Exception as exc:
        logger.exception("Failed to load policy index: %s", exc)

    return _policy_cache


def _get_sheet_details(sheet_name: str) -> dict:
    """
    Parse a policy sheet and extract:
        min_sum_assured, payment_frequency
    Returns a dict with those two keys (both strings).
    """
    result = {"min_sum_assured": "", "payment_frequency": ""}

    if not sheet_name or not os.path.exists(XLSX_PATH):
        return result

    try:
        df = pd.read_excel(XLSX_PATH, sheet_name=sheet_name, header=None)

        for _, row in df.iterrows():
            key = str(row.iloc[0]).strip() if len(row) > 0 else ""
            val = str(row.iloc[1]).strip() if len(row) > 1 else ""

            if val in ("nan", "NaN", ""):
                val = ""

            if "minimum sum assured" in key.lower() and val:
                result["min_sum_assured"] = val

            if "premium payment options" in key.lower() and val:
                result["payment_frequency"] = val

    except Exception as exc:
        logger.warning("Could not read sheet '%s': %s", sheet_name, exc)

    return result


def _parse_frequency_label(payment_options: str) -> str:
    """
    Convert the verbose payment options string to a short display label.
    Examples:
      "Regular Premium (Yearly / Half-Yearly / Quarterly / Monthly)" -> "Yearly / Monthly"
      "Single Premium"                                                -> "Single Premium"
      "Limited Premium (10 / 15 years PPT)"                          -> "Limited Premium"
    """
    if not payment_options:
        return "As per policy"

    p = payment_options.lower()

    if "single premium" in p:
        return "Single Premium"
    if "limited premium" in p:
        return "Limited Premium"

    # Regular premium — list available modes
    modes = []
    for mode in ["yearly", "half-yearly", "quarterly", "monthly"]:
        if mode in p:
            modes.append(mode.capitalize())

    if modes:
        return " / ".join(modes)

    return payment_options  # fallback: return as-is


def _next_due_date(payment_options: str) -> str:
    """
    Calculate next due date based on payment frequency:
    - Yearly       -> 1 year from today
    - Half-Yearly  -> 6 months
    - Quarterly    -> 3 months
    - Monthly      -> 1 month
    - Single       -> policy term end (approximate 1 year)
    """
    p = payment_options.lower()
    today = date.today()

    if "single" in p:
        return (today.replace(year=today.year + 1)).isoformat()
    if "monthly" in p:
        return (today + timedelta(days=30)).isoformat()
    if "quarterly" in p:
        return (today + timedelta(days=91)).isoformat()
    if "half-yearly" in p or "half yearly" in p:
        return (today + timedelta(days=182)).isoformat()
    if "yearly" in p or "annual" in p:
        return (today.replace(year=today.year + 1)).isoformat()

    # Limited premium — due yearly
    return (today.replace(year=today.year + 1)).isoformat()


def lookup_policy(user_text: str) -> dict:
    """
    Given a raw user utterance (e.g. "I want to enroll in Jeevan Anand"),
    find the best matching LIC policy and return its full details.
    """
    index = _load_policy_index()

    # Normalise: lowercase, strip punctuation, collapse spaces
    raw   = re.sub(r"[^\w\s]", " ", user_text.lower())
    raw   = re.sub(r"\s+", " ", raw).strip()
    words = raw.split()

    # Also build a "squished" version for merged words like "jeevansathi"
    squished = raw.replace(" ", "")

    best_match = None
    best_score = 0

    for key, entry in index.items():
        key_clean   = re.sub(r"[^\w\s]", " ", key.lower())
        key_squish  = key_clean.replace(" ", "")
        key_words   = key_clean.split()

        # Score 1: word overlap (skip tiny words)
        score = sum(1 for w in key_words if len(w) > 3 and w in words)

        # Score 2: squished substring match (catches "jeevansathi" -> "jeevan sathi")
        if len(key_squish) > 5 and key_squish in squished:
            score += 3

        # Score 3: any key word appears as substring of the input
        for w in key_words:
            if len(w) > 4 and w in raw:
                score += 1

        if score > best_score:
            best_score = score
            best_match = entry

    if not best_match or best_score == 0:
        logger.warning("No policy match found for: %s", user_text)
        return {
            "policy_name":       user_text.strip(),
            "plan_number":       "",
            "policy_type":       "",
            "min_sum_assured":   "As per policy",
            "payment_frequency": "As per policy",
            "frequency_label":   "As per policy",
            "next_due_date":     (date.today() + timedelta(days=365)).isoformat(),
            "matched":           False,
        }

    sheet_details = _get_sheet_details(best_match["sheet_name"])
    freq_label    = _parse_frequency_label(sheet_details["payment_frequency"])
    next_due      = _next_due_date(sheet_details["payment_frequency"])

    logger.info(
        "Policy matched: '%s' (score=%d) min_sum='%s' freq='%s'",
        best_match["policy_name"], best_score,
        sheet_details["min_sum_assured"],
        sheet_details["payment_frequency"],
    )

    return {
        "policy_name":       best_match["policy_name"],
        "plan_number":       best_match["plan_number"],
        "policy_type":       best_match["policy_type"],
        "min_sum_assured":   sheet_details["min_sum_assured"] or "As per policy",
        "payment_frequency": sheet_details["payment_frequency"] or "As per policy",
        "frequency_label":   freq_label,
        "next_due_date":     next_due,
        "matched":           True,
    }


# ---------------------------------------------------------------------------
# Customer helpers
# ---------------------------------------------------------------------------


def get_or_create_customer(username: str) -> dict:
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM customers WHERE username = ?", (username,)
    ).fetchone()

    if row:
        return row_to_dict(row)

    conn.execute("INSERT INTO customers (username) VALUES (?)", (username,))
    conn.commit()
    logger.info("Created dashboard customer for username='%s'", username)

    row = conn.execute(
        "SELECT * FROM customers WHERE username = ?", (username,)
    ).fetchone()
    return row_to_dict(row)


def sync_enrollment_to_db(
    username: str,
    name: str,
    age: str,
    phone: str,
    email: str,
    policy_raw: str,          # raw user sentence e.g. "I want to enroll in Jeevan Anand"
) -> None:
    """
    Called by app.py after a successful enrollment.
    Looks up the real policy name + premium details from the Excel file,
    then inserts the policy row and notifications.
    """
    conn = get_db()

    # 1. Upsert customer profile
    conn.execute(
        """
        INSERT INTO customers (username, name, age, phone, email)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            name       = excluded.name,
            age        = excluded.age,
            phone      = excluded.phone,
            email      = excluded.email,
            updated_at = datetime('now')
        """,
        (username, name, age, phone, email),
    )
    conn.commit()

    customer = get_or_create_customer(username)
    cid      = customer["id"]

    # 2. Look up real policy details from Excel
    policy_info = lookup_policy(policy_raw)
    clean_name  = policy_info["policy_name"]
    min_sum     = policy_info["min_sum_assured"]     # e.g. "₹1,00,000"
    freq_label  = policy_info["frequency_label"]     # e.g. "Yearly / Monthly"
    next_due    = policy_info["next_due_date"]       # ISO date string

    # 3. Generate policy number
    year  = date.today().year
    count = conn.execute(
        "SELECT COUNT(*) FROM policies WHERE customer_id = ?", (cid,)
    ).fetchone()[0]
    policy_number = f"LIC-{year}-{count + 1:04d}"

    # 4. Insert policy row
    # premium_amount stores 0.0 (no fixed amount in Excel — min_sum_assured
    # is the insured amount, not the premium; use min_sum_assured text column)
    conn.execute(
        """
        INSERT INTO policies
            (customer_id, policy_number, policy_name, premium_amount,
             min_sum_assured, payment_frequency, next_due_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (cid, policy_number, clean_name, 0.0,
         min_sum, freq_label, next_due),
    )

    # 5. Enrollment notification
    conn.execute(
        """
        INSERT INTO notifications (customer_id, title, body, type)
        VALUES (?, ?, ?, ?)
        """,
        (
            cid,
            "Enrollment Confirmed ✅",
            f"You have successfully enrolled in {clean_name}. "
            f"Your policy number is {policy_number}.",
            "success",
        ),
    )

    # 6. Premium reminder notification
    conn.execute(
        """
        INSERT INTO notifications (customer_id, title, body, type)
        VALUES (?, ?, ?, ?)
        """,
        (
            cid,
            "Premium Information",
            f"Policy: {clean_name} | Min. Sum Assured: {min_sum} | "
            f"Payment: {freq_label} | Next due: {next_due}.",
            "warning",
        ),
    )

    conn.commit()
    logger.info(
        "Enrollment synced — user=%s policy='%s' number=%s min_sum=%s freq=%s",
        username, clean_name, policy_number, min_sum, freq_label,
    )


def save_chat_turn(
    username: str,
    session_id: str,
    role: str,
    message: str,
) -> None:
    customer = get_or_create_customer(username)
    cid      = customer["id"]
    conn     = get_db()
    conn.execute(
        "INSERT INTO chat_history (customer_id, session_id, role, message) VALUES (?, ?, ?, ?)",
        (cid, session_id, role, message),
    )
    conn.commit()


def save_recommendation(
    username: str,
    policy_name: str,
    reason: str,
) -> None:
    customer = get_or_create_customer(username)
    cid      = customer["id"]
    conn     = get_db()
    conn.execute(
        "INSERT INTO recommendations (customer_id, policy_name, reason) VALUES (?, ?, ?)",
        (cid, policy_name, reason),
    )
    conn.commit()
