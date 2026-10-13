"""Tests for Spendly Step 7: Add Expense (.claude/specs/07-add-expense.md).

DB isolation: importing ``app`` runs init_db()/seed_db() at import time, so
DB_PATH is pointed at a throwaway temp file BEFORE the import. Each test then
gets its own fresh temp DB via the autouse ``fresh_db`` fixture. The real
expense_tracker.db is never opened.
"""
import os
import re
import sys
import tempfile
from datetime import date
from urllib.parse import urlparse

import pytest
from werkzeug.security import generate_password_hash

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database.db as db_module  # noqa: E402

# Redirect BEFORE importing app (import-time init_db/seed_db).
_IMPORT_TIME_DIR = tempfile.mkdtemp(prefix="spendly-import-")
db_module.DB_PATH = os.path.join(_IMPORT_TIME_DIR, "import_time.db")

import app as app_module  # noqa: E402
from database.db import CATEGORIES, create_user, get_db, init_db  # noqa: E402
from database.queries import insert_expense  # noqa: E402

flask_app = app_module.app

EXPECTED_CATEGORIES = [
    "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other",
]
ERROR_WORDS = ("error", "invalid", "must", "please", "required", "greater", "valid")


# --------------------------------------------------------------------------- #
# Fixtures and helpers                                                        #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test_spendly.db"))
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        init_db()
    yield


def _make_user(name, email):
    return create_user(name, email, generate_password_hash("password123"))


@pytest.fixture
def user_id():
    return _make_user("Test User", "tester@example.com")


@pytest.fixture
def other_user_id():
    return _make_user("Other Person", "other@example.com")


@pytest.fixture
def anon_client():
    return flask_app.test_client()


@pytest.fixture
def auth_client(user_id):
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return client


def _url(endpoint):
    with flask_app.test_request_context():
        from flask import url_for
        return url_for(endpoint)


def add_url():
    return _url("add_expense")


def profile_url():
    return _url("profile")


def login_url():
    return _url("login")


def valid_form(**overrides):
    data = {
        "amount": "50.0",
        "category": "Food",
        "date": "2026-03-20",
        "description": "Lunch",
    }
    data.update(overrides)
    return data


def fetch_expenses(uid=None):
    conn = get_db()
    try:
        if uid is None:
            rows = conn.execute("SELECT * FROM expenses ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE user_id = ? ORDER BY id", (uid,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def body(resp):
    return resp.get_data(as_text=True)


def shows_error(post_resp, baseline_resp):
    """An error is shown if any error keyword appears more often than on a clean GET."""
    post_text, base_text = body(post_resp).lower(), body(baseline_resp).lower()
    return any(post_text.count(w) > base_text.count(w) for w in ERROR_WORDS)


# --------------------------------------------------------------------------- #
# Unit tests: insert_expense                                                  #
# --------------------------------------------------------------------------- #

class TestInsertExpense:
    def test_insert_expense_valid_data_inserts_row(self, user_id):
        new_id = insert_expense(user_id, 50.0, "Food", "2026-03-20", "Lunch")
        rows = fetch_expenses(user_id)
        assert len(rows) == 1, "Expected exactly one row to be inserted"
        row = rows[0]
        assert row["id"] == new_id, "Return value should be the new row id"
        assert row["user_id"] == user_id
        assert row["amount"] == 50.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_insert_expense_none_description_stores_null(self, user_id):
        new_id = insert_expense(user_id, 12.5, "Bills", "2026-03-21", None)
        rows = fetch_expenses(user_id)
        assert len(rows) == 1
        assert rows[0]["id"] == new_id
        assert rows[0]["description"] is None, "description=None must be stored as NULL"

    def test_insert_expense_multiple_calls_return_distinct_ids(self, user_id):
        a = insert_expense(user_id, 1.0, "Food", "2026-03-20", "a")
        b = insert_expense(user_id, 2.0, "Food", "2026-03-20", "b")
        assert a != b, "Each insert should return a unique id"
        assert len(fetch_expenses(user_id)) == 2

    def test_insert_expense_sql_injection_text_is_stored_literally(self, user_id):
        evil = "x'); DROP TABLE expenses; --"
        insert_expense(user_id, 5.0, "Other", "2026-03-20", evil)
        rows = fetch_expenses(user_id)
        assert len(rows) == 1, "expenses table must survive injection attempt"
        assert rows[0]["description"] == evil


def test_categories_constant_has_the_seven_fixed_categories():
    assert list(CATEGORIES) == EXPECTED_CATEGORIES


# --------------------------------------------------------------------------- #
# Auth guards                                                                 #
# --------------------------------------------------------------------------- #

class TestAuthGuard:
    def test_get_logged_out_redirects_to_login(self, anon_client):
        resp = anon_client.get(add_url())
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == login_url()

    def test_post_logged_out_redirects_to_login(self, anon_client):
        resp = anon_client.post(add_url(), data=valid_form())
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == login_url()

    def test_post_logged_out_inserts_nothing(self, anon_client):
        anon_client.post(add_url(), data=valid_form())
        assert fetch_expenses() == [], "Logged-out POST must not create an expense"


# --------------------------------------------------------------------------- #
# GET form                                                                    #
# --------------------------------------------------------------------------- #

class TestGetForm:
    def test_get_logged_in_returns_200(self, auth_client):
        assert auth_client.get(add_url()).status_code == 200

    def test_get_contains_post_form(self, auth_client):
        text = body(auth_client.get(add_url()))
        assert "<form" in text, "Expected a <form> element"
        assert re.search(r'<form[^>]*method=["\']post["\']', text, re.I), \
            "Form must use method POST"

    def test_get_form_has_all_four_fields(self, auth_client):
        text = body(auth_client.get(add_url()))
        for field in ("amount", "category", "date", "description"):
            assert re.search(r'name=["\']%s["\']' % field, text), \
                "Missing form field: %s" % field

    def test_get_has_category_select(self, auth_client):
        text = body(auth_client.get(add_url()))
        assert re.search(r"<select[^>]*name=[\"']category[\"']", text), \
            "Expected a <select name=category>"

    @pytest.mark.parametrize("category", EXPECTED_CATEGORIES)
    def test_get_select_contains_each_category_option(self, auth_client, category):
        text = body(auth_client.get(add_url()))
        select = re.search(r"<select[^>]*category.*?</select>", text, re.S | re.I)
        assert select, "category <select> not found"
        assert re.search(r"<option[^>]*>\s*%s\s*</option>" % category, select.group(0)), \
            "Missing option: %s" % category

    def test_get_select_has_exactly_seven_options(self, auth_client):
        text = body(auth_client.get(add_url()))
        select = re.search(r"<select[^>]*category.*?</select>", text, re.S | re.I).group(0)
        # Only selectable options count; a disabled empty-value placeholder is allowed.
        options = re.findall(r'<option\b[^>]*value="[^"]+"', select)
        assert len(options) == 7, "Expected exactly 7 options, got %d" % len(options)

    def test_get_date_defaults_to_today(self, auth_client):
        text = body(auth_client.get(add_url()))
        assert date.today().isoformat() in text, "Date should default to today"

    def test_get_has_save_button_and_cancel_link_to_profile(self, auth_client):
        text = body(auth_client.get(add_url()))
        assert "Save Expense" in text
        assert 'href="%s"' % profile_url() in text, "Expected cancel link to /profile"


# --------------------------------------------------------------------------- #
# Navigation links                                                            #
# --------------------------------------------------------------------------- #

class TestAddExpenseLinks:
    def test_profile_page_has_add_expense_link(self, auth_client):
        text = body(auth_client.get(profile_url()))
        assert "Add Expense" in text
        assert 'href="%s"' % add_url() in text

    def test_navbar_shows_add_expense_when_logged_in(self, auth_client):
        # /terms is a public page rendered through base.html only.
        text = body(auth_client.get(_url("terms")))
        assert 'href="%s"' % add_url() in text, "Navbar should link to Add Expense"
        assert "Add Expense" in text

    def test_navbar_hides_add_expense_when_logged_out(self, anon_client):
        text = body(anon_client.get(_url("terms")))
        assert add_url() not in text, "Navbar link must be hidden when logged out"

    def test_landing_page_hides_add_expense_when_logged_out(self, anon_client):
        text = body(anon_client.get("/"))
        assert add_url() not in text


# --------------------------------------------------------------------------- #
# POST: success                                                               #
# --------------------------------------------------------------------------- #

class TestPostValid:
    def test_valid_post_redirects_to_profile(self, auth_client):
        resp = auth_client.post(add_url(), data=valid_form())
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == profile_url()

    def test_valid_post_inserts_row_for_session_user(self, auth_client, user_id):
        auth_client.post(add_url(), data=valid_form())
        rows = fetch_expenses(user_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["amount"] == 50.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_valid_post_expense_appears_on_profile(self, auth_client):
        auth_client.post(add_url(), data=valid_form(description="UniqueLunchMarker"))
        resp = auth_client.get(profile_url())
        assert resp.status_code == 200
        assert "UniqueLunchMarker" in body(resp), "New expense should be listed"

    def test_follow_redirect_lands_on_profile_200(self, auth_client):
        resp = auth_client.post(add_url(), data=valid_form(), follow_redirects=True)
        assert resp.status_code == 200
        assert "UniqueLunchMarker" not in body(resp)  # sanity: page rendered
        assert resp.request.path == profile_url()

    @pytest.mark.parametrize("category", EXPECTED_CATEGORIES)
    def test_every_fixed_category_is_accepted(self, auth_client, user_id, category):
        resp = auth_client.post(add_url(), data=valid_form(category=category))
        assert resp.status_code == 302
        assert fetch_expenses(user_id)[0]["category"] == category

    def test_decimal_amount_is_stored(self, auth_client, user_id):
        auth_client.post(add_url(), data=valid_form(amount="12.34"))
        assert fetch_expenses(user_id)[0]["amount"] == pytest.approx(12.34)

    def test_minimum_amount_is_accepted(self, auth_client, user_id):
        resp = auth_client.post(add_url(), data=valid_form(amount="0.01"))
        assert resp.status_code == 302
        assert fetch_expenses(user_id)[0]["amount"] == pytest.approx(0.01)

    def test_description_is_stripped(self, auth_client, user_id):
        auth_client.post(add_url(), data=valid_form(description="   Lunch   "))
        assert fetch_expenses(user_id)[0]["description"] == "Lunch"

    def test_sql_injection_in_description_is_stored_literally(self, auth_client, user_id):
        evil = "'); DROP TABLE expenses; --"
        resp = auth_client.post(add_url(), data=valid_form(description=evil))
        assert resp.status_code == 302
        rows = fetch_expenses(user_id)
        assert len(rows) == 1 and rows[0]["description"] == evil

    def test_user_id_form_field_cannot_spoof_owner(self, auth_client, user_id, other_user_id):
        auth_client.post(add_url(), data=valid_form(user_id=str(other_user_id)))
        assert len(fetch_expenses(user_id)) == 1
        assert fetch_expenses(other_user_id) == [], "Expense must belong to session user"


# --------------------------------------------------------------------------- #
# POST: optional description                                                  #
# --------------------------------------------------------------------------- #

class TestDescriptionOptional:
    def test_missing_description_field_redirects_and_stores_null(self, auth_client, user_id):
        data = valid_form()
        del data["description"]
        resp = auth_client.post(add_url(), data=data)
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == profile_url()
        rows = fetch_expenses(user_id)
        assert len(rows) == 1 and rows[0]["description"] is None

    @pytest.mark.parametrize("blank", ["", " ", "     ", "\t", "  \t  "])
    def test_blank_or_whitespace_description_stores_null(self, auth_client, user_id, blank):
        resp = auth_client.post(add_url(), data=valid_form(description=blank))
        assert resp.status_code == 302
        rows = fetch_expenses(user_id)
        assert len(rows) == 1
        assert rows[0]["description"] is None, "Blank description must be NULL, not ''"


# --------------------------------------------------------------------------- #
# POST: validation errors                                                     #
# --------------------------------------------------------------------------- #

class TestValidationErrors:
    def _post_invalid(self, client, **overrides):
        baseline = client.get(add_url())
        resp = client.post(add_url(), data=valid_form(**overrides))
        return resp, baseline

    def _drop(self, client, field):
        baseline = client.get(add_url())
        data = valid_form()
        del data[field]
        return client.post(add_url(), data=data), baseline

    @pytest.mark.parametrize("amount", ["", "   ", "0", "0.0", "-5", "-0.01", "abc", "12abc", "1,5"])
    def test_bad_amount_rerenders_form_with_error_and_no_insert(self, auth_client, amount):
        resp, baseline = self._post_invalid(auth_client, amount=amount)
        assert resp.status_code == 200, "Invalid amount %r should re-render form" % amount
        assert "<form" in body(resp)
        assert shows_error(resp, baseline), "Expected an error message for %r" % amount
        assert fetch_expenses() == [], "Nothing must be inserted for %r" % amount

    def test_missing_amount_field_rerenders_with_error(self, auth_client):
        resp, baseline = self._drop(auth_client, "amount")
        assert resp.status_code == 200
        assert shows_error(resp, baseline)
        assert fetch_expenses() == []

    @pytest.mark.parametrize("amount", ["nan", "inf", "-inf"])
    def test_non_finite_amount_is_not_stored(self, auth_client, amount):
        resp = auth_client.post(add_url(), data=valid_form(amount=amount))
        assert resp.status_code == 200, "Non-finite amount %r should be rejected" % amount
        assert fetch_expenses() == []

    @pytest.mark.parametrize("category", ["Groceries", "food", "", "   ", "FOOD", "'; DROP TABLE expenses; --"])
    def test_invalid_category_rerenders_with_error_and_no_insert(self, auth_client, category):
        resp, baseline = self._post_invalid(auth_client, category=category)
        assert resp.status_code == 200
        assert shows_error(resp, baseline), "Expected an error for category %r" % category
        assert fetch_expenses() == []

    def test_missing_category_field_rerenders_with_error(self, auth_client):
        resp, baseline = self._drop(auth_client, "category")
        assert resp.status_code == 200
        assert shows_error(resp, baseline)
        assert fetch_expenses() == []

    @pytest.mark.parametrize(
        "bad_date",
        ["not-a-date", "2026-13-45", "2026-02-30", "20260320", "03-20-2026", "2026/03/20", "", "   "],
    )
    def test_invalid_or_empty_date_rerenders_with_error_and_no_insert(self, auth_client, bad_date):
        resp, baseline = self._post_invalid(auth_client, date=bad_date)
        assert resp.status_code == 200, "Date %r should re-render form" % bad_date
        assert shows_error(resp, baseline), "Expected an error for date %r" % bad_date
        assert fetch_expenses() == []

    def test_missing_date_field_rerenders_with_error(self, auth_client):
        resp, baseline = self._drop(auth_client, "date")
        assert resp.status_code == 200
        assert shows_error(resp, baseline)
        assert fetch_expenses() == []

    def test_invalid_amount_retains_other_submitted_values(self, auth_client):
        resp = auth_client.post(
            add_url(),
            data=valid_form(amount="0", description="KeepMeDescription", date="2026-04-05", category="Health"),
        )
        text = body(resp)
        assert resp.status_code == 200
        assert "KeepMeDescription" in text, "Description should be retained"
        assert "2026-04-05" in text, "Date should be retained"
        option = re.search(r"<option[^>]*value=[\"']Health[\"'][^>]*>", text)
        assert option and "selected" in option.group(0), "Category should stay selected"

    def test_non_numeric_amount_value_is_retained(self, auth_client):
        resp = auth_client.post(add_url(), data=valid_form(amount="abc"))
        assert resp.status_code == 200
        assert "abc" in body(resp), "Submitted amount should be re-populated"

    def test_zero_amount_value_is_retained(self, auth_client):
        resp = auth_client.post(add_url(), data=valid_form(amount="0", description="ZeroCase"))
        text = body(resp)
        assert re.search(r"name=[\"']amount[\"'][^>]*value=[\"']0[\"']|value=[\"']0[\"'][^>]*name=[\"']amount[\"']", text), \
            "Submitted amount 0 should be re-populated"

    def test_invalid_category_retains_other_submitted_values(self, auth_client):
        resp = auth_client.post(
            add_url(),
            data=valid_form(category="Bogus", amount="77.5", description="KeepMe2", date="2026-05-06"),
        )
        text = body(resp)
        assert resp.status_code == 200
        assert "77.5" in text and "KeepMe2" in text and "2026-05-06" in text

    def test_invalid_date_retains_other_submitted_values(self, auth_client):
        resp = auth_client.post(
            add_url(),
            data=valid_form(date="2026-02-30", amount="88.25", description="KeepMe3"),
        )
        text = body(resp)
        assert resp.status_code == 200
        assert "88.25" in text and "KeepMe3" in text
        assert "2026-02-30" in text, "Submitted date should be retained"

    def test_validation_error_does_not_redirect(self, auth_client):
        resp = auth_client.post(add_url(), data=valid_form(amount="-1"))
        assert "Location" not in resp.headers


# --------------------------------------------------------------------------- #
# Data isolation between users                                                #
# --------------------------------------------------------------------------- #

class TestUserIsolation:
    def test_expense_not_visible_to_other_user(self, auth_client, other_user_id):
        auth_client.post(add_url(), data=valid_form(description="PrivateMarkerXYZ"))

        other = flask_app.test_client()
        with other.session_transaction() as sess:
            sess["user_id"] = other_user_id
            sess["user_name"] = "Other Person"
        resp = other.get(profile_url())
        assert resp.status_code == 200
        assert "PrivateMarkerXYZ" not in body(resp), "Other user must not see this expense"

    def test_expense_is_stored_only_under_session_user(self, auth_client, user_id, other_user_id):
        auth_client.post(add_url(), data=valid_form())
        assert len(fetch_expenses(user_id)) == 1
        assert fetch_expenses(other_user_id) == []

    def test_login_via_post_then_add_expense_works(self, anon_client, user_id):
        resp = anon_client.post(
            login_url(), data={"email": "tester@example.com", "password": "password123"}
        )
        assert resp.status_code in (302, 303), "Login should redirect"
        resp = anon_client.post(add_url(), data=valid_form())
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == profile_url()
        assert len(fetch_expenses(user_id)) == 1
