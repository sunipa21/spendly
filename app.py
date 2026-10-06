import calendar
import os
import sqlite3
from datetime import date, datetime

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    create_user,
    get_db,
    get_user_by_email,
    init_db,
    seed_db,
)
from database.queries import (
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_id,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _parse_date(value):
    """Parse a YYYY-MM-DD string; return None if missing or malformed."""
    if not value or len(value) > 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_date_range(args):
    """Read the profile date filter from query args.

    Returns (date_from, date_to, error). Malformed dates are dropped silently;
    a reversed range drops both and returns an error message.
    """
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if date_from and date_to and date_from > date_to:
        return None, None, "Start date must be before end date."
    return date_from, date_to, None


def _last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]


def _months_ago(d, months):
    """Same day `months` calendar months before `d`, clamped to month end."""
    month_index = d.year * 12 + d.month - 1 - months
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(d.day, _last_day_of_month(year, month)))


def _date_presets(today, date_from, date_to):
    """Quick-select ranges for the profile filter bar, with the active one marked."""
    month_start = today.replace(day=1)
    month_end = today.replace(day=_last_day_of_month(today.year, today.month))
    ranges = [
        ("This Month", month_start, month_end),
        ("Last 3 Months", _months_ago(today, 3), today),
        ("Last 6 Months", _months_ago(today, 6), today),
        ("All Time", None, None),
    ]

    presets = []
    for label, start, end in ranges:
        if start is None:
            url = url_for("profile")
        else:
            url = url_for("profile", date_from=start.isoformat(), date_to=end.isoformat())
        presets.append({
            "label": label,
            "url": url,
            "is_active": (start, end) == (date_from, date_to),
        })
    return presets


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    error = None
    if not name:
        error = "Please enter your name."
    elif not email or "@" not in email or "." not in email:
        error = "Please enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != confirm_password:
        error = "Passwords do not match."
    elif get_user_by_email(email):
        error = "An account with this email already exists."
    else:
        try:
            create_user(name, email, generate_password_hash(password))
        except sqlite3.IntegrityError:
            error = "An account with this email already exists."

    if error:
        return render_template("register.html", error=error, name=name, email=email)

    flash("Account created — please sign in.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    user = get_user_by_email(email) if email and password else None
    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html", error="Invalid email or password.", email=email
        )

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = get_user_by_id(session["user_id"])
    if user is None:
        session.clear()
        return redirect(url_for("login"))
    user["initials"] = "".join(word[0] for word in user["name"].split()[:2]).upper()

    # === Date filter ===
    date_from, date_to, filter_error = _resolve_date_range(request.args)
    presets = _date_presets(date.today(), date_from, date_to)
    # Custom = a filter is applied but it doesn't match any preset's range.
    is_custom_range = bool(date_from or date_to) and not any(
        p["is_active"] for p in presets
    )
    # ISO strings, converted once, for the query helpers and the date inputs.
    date_range = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
    }
    # === end Date filter ===

    # === Transaction history (Subagent 1) ===
    transactions = get_recent_transactions(session["user_id"], **date_range)
    # === end Transaction history ===

    # === Summary stats (Subagent 2) ===
    stats = get_summary_stats(session["user_id"], **date_range)
    # === end Summary stats ===

    # === Category breakdown (Subagent 3) ===
    categories = get_category_breakdown(session["user_id"], **date_range)
    # === end Category breakdown ===

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        presets=presets,
        date_from=date_range["date_from"] or "",
        date_to=date_range["date_to"] or "",
        is_custom_range=is_custom_range,
        filter_error=filter_error,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
