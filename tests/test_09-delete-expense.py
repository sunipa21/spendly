"""Tests for Spendly Step 9: Delete Expense (.claude/specs/09-delete-expense.md).

DB isolation: importing ``app`` runs init_db()/seed_db() at import time, so
DB_PATH is pointed at a throwaway temp file BEFORE the import. Each test then
gets its own fresh temp DB via the autouse ``fresh_db`` fixture. The real
expense_tracker.db is never opened.
"""
import os
import sys
import tempfile
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
from database.db import create_user, get_db, init_db  # noqa: E402
from database.queries import delete_expense, insert_expense  # noqa: E402

flask_app = app_module.app


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
def expense_id(user_id):
    return insert_expense(user_id, 50.0, "Food", "2026-03-20", "Lunch")


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


def _url(endpoint, **values):
    with flask_app.test_request_context():
        from flask import url_for
        return url_for(endpoint, **values)


def delete_url(id):
    return _url("delete_expense", id=id)


def expense_exists(id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT 1 FROM expenses WHERE id = ?", (id,)
        ).fetchone() is not None
    finally:
        conn.close()


def count_expenses():
    conn = get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Unit tests: delete_expense                                                  #
# --------------------------------------------------------------------------- #

class TestDeleteExpenseHelper:
    def test_correct_user_removes_row(self, user_id, expense_id):
        assert delete_expense(expense_id, user_id) == 1
        assert not expense_exists(expense_id)

    def test_wrong_user_leaves_row(self, expense_id, other_user_id):
        assert delete_expense(expense_id, other_user_id) == 0
        assert expense_exists(expense_id)

    def test_nonexistent_id_is_noop(self, user_id, expense_id):
        assert delete_expense(99999, user_id) == 0
        assert count_expenses() == 1


# --------------------------------------------------------------------------- #
# Route tests                                                                 #
# --------------------------------------------------------------------------- #

class TestDeleteRoute:
    def test_logged_out_redirects_to_login(self, anon_client, expense_id):
        resp = anon_client.post(delete_url(expense_id))
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == _url("login")
        assert expense_exists(expense_id)

    def test_own_expense_deleted_and_redirects_to_profile(self, auth_client, expense_id):
        resp = auth_client.post(delete_url(expense_id))
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == _url("profile")
        assert not expense_exists(expense_id)

    def test_other_users_expense_returns_404(self, auth_client, other_user_id):
        theirs = insert_expense(other_user_id, 20.0, "Bills", "2026-03-20", "Rent")
        resp = auth_client.post(delete_url(theirs))
        assert resp.status_code == 404
        assert expense_exists(theirs)

    def test_nonexistent_id_returns_404(self, auth_client):
        assert auth_client.post(delete_url(99999)).status_code == 404

    def test_get_returns_405(self, auth_client, expense_id):
        assert auth_client.get(delete_url(expense_id)).status_code == 405
        assert expense_exists(expense_id)

    def test_get_logged_out_returns_405(self, anon_client, expense_id):
        assert anon_client.get(delete_url(expense_id)).status_code == 405


# --------------------------------------------------------------------------- #
# Profile page                                                                #
# --------------------------------------------------------------------------- #

class TestProfileDeleteButton:
    def test_each_row_has_edit_and_delete(self, auth_client, user_id, expense_id):
        second = insert_expense(user_id, 10.0, "Transport", "2026-03-21", "Bus")
        html = auth_client.get(_url("profile")).get_data(as_text=True)
        for id in (expense_id, second):
            assert f'action="{delete_url(id)}"' in html
            assert f'href="{_url("edit_expense", id=id)}"' in html
        assert html.count('class="btn-delete"') == 2
        assert "confirm(" in html

    def test_deleted_expense_disappears_from_profile(self, auth_client, expense_id):
        resp = auth_client.post(delete_url(expense_id), follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Lunch" not in html
        assert delete_url(expense_id) not in html
