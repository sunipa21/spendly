from datetime import datetime

from database.db import get_db


def get_user_by_id(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    return {
        "name": row["name"],
        "email": row["email"],
        "member_since": created.strftime("%B %Y"),
    }


def _date_filter(date_from=None, date_to=None):
    """Return an SQL fragment and params restricting expenses.date to the
    inclusive range. Either bound may be None for an open-ended range."""
    sql, params = "", ()
    if date_from:
        sql += " AND date >= ?"
        params += (date_from,)
    if date_to:
        sql += " AND date <= ?"
        params += (date_to,)
    return sql, params


# === Transaction history (Subagent 1) ===
def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    date_sql, date_params = _date_filter(date_from, date_to)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT date, description, category, amount FROM expenses "
            f"WHERE user_id = ?{date_sql} ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, *date_params, limit),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "date": row["date"],
            "description": row["description"] or "",
            "category": row["category"],
            "amount": float(row["amount"]),
        }
        for row in rows
    ]
# === end Transaction history ===


# === Summary stats (Subagent 2) ===
def get_summary_stats(user_id, date_from=None, date_to=None):
    date_sql, date_params = _date_filter(date_from, date_to)
    conn = get_db()
    try:
        totals = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count "
            f"FROM expenses WHERE user_id = ?{date_sql}",
            (user_id, *date_params),
        ).fetchone()
        top = conn.execute(
            f"SELECT category FROM expenses WHERE user_id = ?{date_sql} "
            "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            (user_id, *date_params),
        ).fetchone()
    finally:
        conn.close()

    return {
        "total_spent": round(float(totals["total"]), 2),
        "transaction_count": int(totals["count"]),
        "top_category": top["category"] if top else "—",
    }
# === end Summary stats ===


# === Category breakdown (Subagent 3) ===
def get_category_breakdown(user_id, date_from=None, date_to=None):
    date_sql, date_params = _date_filter(date_from, date_to)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category, SUM(amount) AS amount FROM expenses "
            f"WHERE user_id = ?{date_sql} GROUP BY category ORDER BY amount DESC",
            (user_id, *date_params),
        ).fetchall()
    finally:
        conn.close()

    total = sum(float(row["amount"]) for row in rows)
    if total <= 0:
        return []

    categories = [
        {
            "name": row["category"],
            "amount": round(float(row["amount"]), 2),
            "pct": int(round(float(row["amount"]) / total * 100)),
        }
        for row in rows
    ]
    categories[0]["pct"] += 100 - sum(c["pct"] for c in categories)
    return categories
# === end Category breakdown ===
