"""
Insura - Enrollment persistence module.

Public API:
    save_enrollment(name, age, phone, email, policy) -> bool
        Appends a new row to customer_enrollments.xlsx.
        Returns True on success, False on failure.
"""

import logging
import os

import pandas as pd

logger = logging.getLogger("insura.enrollment")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENROLLMENT_FILE = os.path.join(BASE_DIR, "customer_enrollments.xlsx")

# Column order in the workbook
COLUMNS = ["Name", "Age", "Phone", "Email", "Policy"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_enrollment(
    name: str,
    age: str,
    phone: str,
    email: str,
    policy: str,
) -> bool:
    """
    Append one enrollment record to the Excel workbook.

    If the file does not exist it is created fresh.
    Returns True on success, False if writing fails.
    """
    new_record = pd.DataFrame(
        [{"Name": name, "Age": age, "Phone": phone, "Email": email, "Policy": policy}],
        columns=COLUMNS,
    )

    try:
        if os.path.exists(ENROLLMENT_FILE):
            existing = pd.read_excel(ENROLLMENT_FILE)
            # Ensure consistent columns even if file was created manually
            for col in COLUMNS:
                if col not in existing.columns:
                    existing[col] = ""
            updated = pd.concat(
                [existing[COLUMNS], new_record],
                ignore_index=True,
            )
        else:
            updated = new_record

        updated.to_excel(ENROLLMENT_FILE, index=False)
        logger.info(
            "Enrollment saved — Name: %s | Phone: %s | Policy: %s",
            name, phone, policy,
        )
        return True

    except Exception as exc:
        logger.exception("Failed to save enrollment for %s: %s", name, exc)
        return False
