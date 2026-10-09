"""
Insura - Dashboard API Blueprint

All routes are mounted under  /dashboard/*
They are completely additive — no existing route is changed.

Authentication
--------------
Every endpoint reads  X-Username  from the request header (set by dashboard.js
from localStorage).  This keeps the auth model consistent with how home.html /
login.html already work (localStorage username).

Endpoints
---------
GET  /dashboard/profile                -> customer profile
PUT  /dashboard/profile                -> update profile fields
GET  /dashboard/policies               -> enrolled policies list
GET  /dashboard/recommendations        -> AI recommendation list
GET  /dashboard/chat-history           -> paginated chat turns
GET  /dashboard/notifications          -> notifications list
PUT  /dashboard/notifications/<id>/read -> mark one notification read
PUT  /dashboard/notifications/read-all -> mark all read
GET  /dashboard/documents              -> document list
GET  /dashboard/stats                  -> summary card numbers
POST /dashboard/chat/save              -> persist a conversation turn
POST /dashboard/recommendations/save   -> persist an AI recommendation
"""

import logging

from flask import Blueprint, jsonify, request

from database import (
    get_db,
    get_or_create_customer,
    rows_to_list,
    row_to_dict,
    save_chat_turn,
    save_recommendation,
)

logger = logging.getLogger("insura.dashboard")

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _username() -> str | None:
    """Extract and validate the X-Username header."""
    return (request.headers.get("X-Username") or "").strip() or None


def _require_user():
    """
    Return (customer_dict, None) on success or (None, error_response) on failure.
    Callers pattern:  customer, err = _require_user(); if err: return err
    """
    username = _username()
    if not username:
        return None, (jsonify({"error": "X-Username header missing"}), 401)
    try:
        customer = get_or_create_customer(username)
        return customer, None
    except Exception as exc:
        logger.exception("DB error for username=%s: %s", username, exc)
        return None, (jsonify({"error": "Database error"}), 500)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@dashboard_bp.route("/profile", methods=["GET"])
def get_profile():
    """Return the customer profile for the logged-in user."""
    customer, err = _require_user()
    if err:
        return err

    return jsonify({
        "id":       customer["id"],
        "username": customer["username"],
        "name":     customer["name"],
        "age":      customer["age"],
        "phone":    customer["phone"],
        "email":    customer["email"],
    })


@dashboard_bp.route("/profile", methods=["PUT"])
def update_profile():
    """Update editable profile fields (name, age, phone, email)."""
    customer, err = _require_user()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    allowed = ("name", "age", "phone", "email")
    updates = {k: str(v).strip() for k, v in data.items() if k in allowed}

    if not updates:
        return jsonify({"error": "No valid fields provided"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values     = list(updates.values()) + [customer["id"]]

    conn = get_db()
    conn.execute(
        f"UPDATE customers SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    conn.commit()
    logger.info("Profile updated for customer_id=%s fields=%s", customer["id"], list(updates.keys()))

    updated = row_to_dict(
        conn.execute("SELECT * FROM customers WHERE id = ?", (customer["id"],)).fetchone()
    )
    return jsonify({
        "username": updated["username"],
        "name":     updated["name"],
        "age":      updated["age"],
        "phone":    updated["phone"],
        "email":    updated["email"],
    })


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


@dashboard_bp.route("/policies", methods=["GET"])
def get_policies():
    """Return all policies enrolled by this customer."""
    customer, err = _require_user()
    if err:
        return err

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, policy_number, policy_name, enrollment_date,
               status, premium_amount, min_sum_assured,
               payment_frequency, next_due_date
        FROM   policies
        WHERE  customer_id = ?
        ORDER  BY enrollment_date DESC
        """,
        (customer["id"],),
    ).fetchall()

    return jsonify(rows_to_list(rows))


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


@dashboard_bp.route("/recommendations", methods=["GET"])
def get_recommendations():
    """Return AI-generated policy recommendations for this customer."""
    customer, err = _require_user()
    if err:
        return err

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, policy_name, reason, recommended_at
        FROM   recommendations
        WHERE  customer_id = ?
        ORDER  BY recommended_at DESC
        """,
        (customer["id"],),
    ).fetchall()

    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/recommendations/save", methods=["POST"])
def save_recommendation_endpoint():
    """
    Persist an AI recommendation (called by agent.html after a recommendation response).
    Body: { "policy_name": "...", "reason": "..." }
    """
    customer, err = _require_user()
    if err:
        return err

    data        = request.get_json(silent=True) or {}
    policy_name = data.get("policy_name", "").strip()
    reason      = data.get("reason", "").strip()

    if not policy_name:
        return jsonify({"error": "policy_name is required"}), 400

    try:
        save_recommendation(customer["username"], policy_name, reason)
        return jsonify({"status": "saved"})
    except Exception as exc:
        logger.exception("Failed to save recommendation: %s", exc)
        return jsonify({"error": "Could not save recommendation"}), 500


# ---------------------------------------------------------------------------
# Chat History
# ---------------------------------------------------------------------------


@dashboard_bp.route("/chat-history", methods=["GET"])
def get_chat_history():
    """
    Return chat history with optional search and pagination.
    Query params:
        q       — search term (matches message text)
        page    — page number (1-indexed, default 1)
        per_page — rows per page (default 30, max 100)
    """
    customer, err = _require_user()
    if err:
        return err

    q        = (request.args.get("q") or "").strip()
    try:
        page     = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 30))))
    except ValueError:
        page, per_page = 1, 30

    offset = (page - 1) * per_page
    conn   = get_db()

    if q:
        total = conn.execute(
            "SELECT COUNT(*) FROM chat_history WHERE customer_id = ? AND message LIKE ?",
            (customer["id"], f"%{q}%"),
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT id, session_id, role, message, created_at
            FROM   chat_history
            WHERE  customer_id = ? AND message LIKE ?
            ORDER  BY created_at DESC
            LIMIT  ? OFFSET ?
            """,
            (customer["id"], f"%{q}%", per_page, offset),
        ).fetchall()
    else:
        total = conn.execute(
            "SELECT COUNT(*) FROM chat_history WHERE customer_id = ?",
            (customer["id"],),
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT id, session_id, role, message, created_at
            FROM   chat_history
            WHERE  customer_id = ?
            ORDER  BY created_at DESC
            LIMIT  ? OFFSET ?
            """,
            (customer["id"], per_page, offset),
        ).fetchall()

    return jsonify({
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "items":    rows_to_list(rows),
    })


@dashboard_bp.route("/chat/save", methods=["POST"])
def save_chat_endpoint():
    """
    Persist one conversation turn (called by agent.html on every exchange).
    Body: { "session_id": "...", "role": "user|assistant", "message": "..." }
    """
    customer, err = _require_user()
    if err:
        return err

    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "").strip()
    role       = data.get("role", "").strip()
    message    = data.get("message", "").strip()

    if not role or not message:
        return jsonify({"error": "role and message are required"}), 400
    if role not in ("user", "assistant"):
        return jsonify({"error": "role must be 'user' or 'assistant'"}), 400

    try:
        save_chat_turn(customer["username"], session_id, role, message)
        return jsonify({"status": "saved"})
    except Exception as exc:
        logger.exception("Failed to save chat turn: %s", exc)
        return jsonify({"error": "Could not save chat turn"}), 500


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@dashboard_bp.route("/notifications", methods=["GET"])
def get_notifications():
    """Return all notifications for this customer (newest first)."""
    customer, err = _require_user()
    if err:
        return err

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, title, body, type, is_read, created_at
        FROM   notifications
        WHERE  customer_id = ?
        ORDER  BY created_at DESC
        """,
        (customer["id"],),
    ).fetchall()

    items = rows_to_list(rows)
    unread = sum(1 for r in items if not r["is_read"])

    return jsonify({"unread": unread, "items": items})


@dashboard_bp.route("/notifications/<int:notif_id>/read", methods=["PUT"])
def mark_notification_read(notif_id: int):
    """Mark a single notification as read."""
    customer, err = _require_user()
    if err:
        return err

    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND customer_id = ?",
        (notif_id, customer["id"]),
    )
    conn.commit()
    return jsonify({"status": "ok"})


@dashboard_bp.route("/notifications/read-all", methods=["PUT"])
def mark_all_notifications_read():
    """Mark every notification for this customer as read."""
    customer, err = _require_user()
    if err:
        return err

    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE customer_id = ?",
        (customer["id"],),
    )
    conn.commit()
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


@dashboard_bp.route("/documents", methods=["GET"])
def get_documents():
    """Return policy document metadata for this customer."""
    customer, err = _require_user()
    if err:
        return err

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, filename, label, file_path, uploaded_at
        FROM   documents
        WHERE  customer_id = ?
        ORDER  BY uploaded_at DESC
        """,
        (customer["id"],),
    ).fetchall()

    return jsonify(rows_to_list(rows))


# ---------------------------------------------------------------------------
# Stats  (summary cards for the dashboard home)
# ---------------------------------------------------------------------------


@dashboard_bp.route("/stats", methods=["GET"])
def get_stats():
    """
    Return aggregated numbers used by the four summary cards:
        total_policies, active_policies, premium_due, recommendations_count,
        unread_notifications
    """
    customer, err = _require_user()
    if err:
        return err

    cid  = customer["id"]
    conn = get_db()

    total_policies = conn.execute(
        "SELECT COUNT(*) FROM policies WHERE customer_id = ?", (cid,)
    ).fetchone()[0]

    active_policies = conn.execute(
        "SELECT COUNT(*) FROM policies WHERE customer_id = ? AND status = 'Active'", (cid,)
    ).fetchone()[0]

    # Policies with upcoming premium due (within 30 days)
    due_soon = conn.execute(
        """
        SELECT COUNT(*) FROM policies
        WHERE customer_id = ? AND status = 'Active'
          AND next_due_date <= date('now', '+30 days')
        """,
        (cid,),
    ).fetchone()[0]

    recommendations_count = conn.execute(
        "SELECT COUNT(*) FROM recommendations WHERE customer_id = ?", (cid,)
    ).fetchone()[0]

    unread_notifications = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE customer_id = ? AND is_read = 0", (cid,)
    ).fetchone()[0]

    chat_count = conn.execute(
        "SELECT COUNT(*) FROM chat_history WHERE customer_id = ?", (cid,)
    ).fetchone()[0]

    return jsonify({
        "total_policies":        total_policies,
        "active_policies":       active_policies,
        "premium_due":           due_soon,
        "recommendations_count": recommendations_count,
        "unread_notifications":  unread_notifications,
        "chat_count":            chat_count,
        "customer_name":         customer["name"] or customer["username"],
    })
