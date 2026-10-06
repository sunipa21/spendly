import os
import sqlite3

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    CATEGORIES,
    create_user,
    get_db,
    get_user_by_email,
    init_db,
    seed_db,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

with app.app_context():
    init_db()
    seed_db()


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

    # Hardcoded sample data for the Step 4 design — Step 5 replaces it with
    # real queries using the same context shape.
    name = session["user_name"]
    user = {
        "name": name,
        "initials": "".join(word[0] for word in name.split()[:2]).upper(),
        "email": "demo@spendly.com",
        "member_since": "January 2026",
    }

    transactions = [
        {"date": "2026-09-25", "description": "Weekly groceries", "category": CATEGORIES[0], "amount": 54.30},
        {"date": "2026-09-20", "description": "Gift wrapping", "category": CATEGORIES[6], "amount": 8.75},
        {"date": "2026-09-15", "description": "New shoes", "category": CATEGORIES[5], "amount": 60.25},
        {"date": "2026-09-12", "description": "Movie tickets", "category": CATEGORIES[4], "amount": 15.00},
        {"date": "2026-09-08", "description": "Pharmacy", "category": CATEGORIES[3], "amount": 25.00},
        {"date": "2026-09-05", "description": "Electricity bill", "category": CATEGORIES[2], "amount": 89.99},
        {"date": "2026-09-03", "description": "Monthly bus pass top-up", "category": CATEGORIES[1], "amount": 45.00},
        {"date": "2026-09-01", "description": "Lunch at cafe", "category": CATEGORIES[0], "amount": 12.50},
    ]

    categories = [
        {"name": CATEGORIES[2], "amount": 89.99, "pct": 29},
        {"name": CATEGORIES[0], "amount": 66.80, "pct": 21},
        {"name": CATEGORIES[5], "amount": 60.25, "pct": 19},
        {"name": CATEGORIES[1], "amount": 45.00, "pct": 14},
        {"name": CATEGORIES[3], "amount": 25.00, "pct": 8},
        {"name": CATEGORIES[4], "amount": 15.00, "pct": 5},
        {"name": CATEGORIES[6], "amount": 8.75, "pct": 3},
    ]

    stats = {
        "total_spent": round(sum(c["amount"] for c in categories), 2),
        "transaction_count": len(transactions),
        "top_category": categories[0]["name"],
    }

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
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
