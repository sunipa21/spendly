"""Tests for Spendly Step 6: date-range filter on the profile page.

Based on .claude/specs/06-date-filter-profile-page.md plus two agreed refinements:
  1. One-sided ranges are supported (only date_from -> date >= from,
     only date_to -> date <= to, both -> inclusive at both ends).
  2. "This Month" spans the 1st to the last day of the current calendar month;
     "Last 3/6 Months" end today and start on the same day-of-month 3/6 months
     earlier, clamped to that month's last day.

DB isolation: importing ``app`` runs init_db()/seed_db() at import time, so
DB_PATH is pointed at a throwaway temp file BEFORE the import. Each test then
gets its own fresh temp DB through the ``fresh_db`` fixture. The real
expense_tracker.db is never opened.
"""
import calendar
import html as html_lib
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

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
from database.queries import (  # noqa: E402
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
)

flask_app = app_module.app

MALFORMED_DATES = ["not-a-date", "2026-13-45", "2026-02-30", "20260101", "01-01-2026"]


# --------------------------------------------------------------------------- #
# Independent date helpers (deliberately NOT reusing app code)                #
# --------------------------------------------------------------------------- #

def month_start(d):
    return d.replace(day=1)


def month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def months_before(d, n):
    idx = d.year * 12 + (d.month - 1) - n
    year, month0 = divmod(idx, 12)
    month = month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite file."""
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


def add_expense(uid, amount, category, when, description):
    iso = when.isoformat() if isinstance(when, date) else when
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, amount, category, iso, description),
        )
        conn.commit()
    finally:
        conn.close()


def profile_url():
    with flask_app.test_request_context():
        from flask import url_for
        return url_for("profile")


def login_url():
    with flask_app.test_request_context():
        from flask import url_for
        return url_for("login")


def get_profile(client, **params):
    return client.get(profile_url(), query_string=params)


# --------------------------------------------------------------------------- #
# HTML scraping helpers                                                       #
# --------------------------------------------------------------------------- #

def text_of(resp):
    return resp.get_data(as_text=True)


def parse_presets(page):
    anchors = re.findall(
        r'<a\b[^>]*class="[^"]*pf-filter-preset[^"]*"[^>]*>.*?</a>', page, re.S
    )
    presets = {}
    for a in anchors:
        href = html_lib.unescape(re.search(r'href="([^"]*)"', a).group(1))
        classes = re.search(r'class="([^"]*)"', a).group(1).split()
        label = re.sub(r"<[^>]+>", "", a).strip()
        presets[label] = {"href": href, "active": "is-active" in classes}
    return presets


def form_is_active(page):
    m = re.search(r'<form\b[^>]*class="([^"]*pf-filter-form[^"]*)"', page)
    assert m, "custom range form (pf-filter-form) not found"
    return "is-active" in m.group(1).split()


def input_value(page, name):
    m = re.search(r'<input\b[^>]*name="%s"[^>]*>' % name, page)
    assert m, "input named %s not found" % name
    v = re.search(r'value="([^"]*)"', m.group(0))
    return v.group(1) if v else ""


def stat_values(page):
    """[total_spent, transaction_count, top_category] as displayed."""
    vals = re.findall(r'pf-stat-value">([^<]*)<', page)
    assert len(vals) == 3, "expected 3 summary stat values, got %r" % vals
    return [html_lib.unescape(v.strip()) for v in vals]


def category_names(page):
    return [html_lib.unescape(n) for n in re.findall(r'pf-cat-name">([^<]*)<', page)]


def query_of(href):
    return {k: v[0] for k, v in parse_qs(urlparse(href).query).items()}


# --------------------------------------------------------------------------- #
# Query helpers                                                               #
# --------------------------------------------------------------------------- #

@pytest.fixture
def seeded(user_id):
    """Four expenses at fixed absolute dates (calendar independent)."""
    add_expense(user_id, 10.00, "Food", "2025-01-10", "jan food")
    add_expense(user_id, 20.00, "Transport", "2025-02-10", "feb transport")
    add_expense(user_id, 30.00, "Food", "2025-03-10", "mar food")
    add_expense(user_id, 35.00, "Bills", "2025-04-10", "apr bills")
    return user_id


class TestQueryHelpersUnfiltered:
    def test_summary_stats_with_only_user_id_covers_all_expenses(self, seeded):
        stats = get_summary_stats(seeded)
        assert stats["total_spent"] == pytest.approx(95.00)
        assert stats["transaction_count"] == 4
        assert stats["top_category"] == "Food"

    def test_summary_stats_explicit_none_equals_no_filter(self, seeded):
        assert get_summary_stats(seeded, date_from=None, date_to=None) == get_summary_stats(seeded)

    def test_recent_transactions_with_only_user_id_returns_all_newest_first(self, seeded):
        txs = get_recent_transactions(seeded)
        assert [t["date"] for t in txs] == [
            "2025-04-10", "2025-03-10", "2025-02-10", "2025-01-10"
        ]

    def test_recent_transactions_default_limit_is_ten(self, user_id):
        for i in range(12):
            add_expense(user_id, 1.0, "Food", date(2025, 1, 1) + timedelta(days=i), "d%d" % i)
        assert len(get_recent_transactions(user_id)) == 10

    def test_category_breakdown_with_only_user_id_covers_all(self, seeded):
        cats = get_category_breakdown(seeded)
        assert {c["name"]: c["amount"] for c in cats} == {
            "Food": pytest.approx(40.0),
            "Bills": pytest.approx(35.0),
            "Transport": pytest.approx(20.0),
        }
        assert sum(c["pct"] for c in cats) == 100


class TestQueryHelpersFiltered:
    def test_summary_stats_both_bounds_are_inclusive(self, seeded):
        stats = get_summary_stats(seeded, date_from="2025-02-10", date_to="2025-03-10")
        assert stats["total_spent"] == pytest.approx(50.00)
        assert stats["transaction_count"] == 2
        assert stats["top_category"] == "Food"

    def test_summary_stats_excludes_rows_just_outside_range(self, seeded):
        stats = get_summary_stats(seeded, date_from="2025-02-11", date_to="2025-03-09")
        assert stats["transaction_count"] == 0

    def test_summary_stats_only_date_from_is_open_ended_upward(self, seeded):
        stats = get_summary_stats(seeded, date_from="2025-03-10")
        assert stats["transaction_count"] == 2
        assert stats["total_spent"] == pytest.approx(65.00)
        assert stats["top_category"] == "Bills"

    def test_summary_stats_only_date_to_is_open_ended_downward(self, seeded):
        stats = get_summary_stats(seeded, date_to="2025-02-10")
        assert stats["transaction_count"] == 2
        assert stats["total_spent"] == pytest.approx(30.00)
        assert stats["top_category"] == "Transport"

    def test_summary_stats_single_day_range(self, seeded):
        stats = get_summary_stats(seeded, date_from="2025-03-10", date_to="2025-03-10")
        assert stats["transaction_count"] == 1
        assert stats["total_spent"] == pytest.approx(30.00)

    def test_recent_transactions_filtered_inclusive_and_ordered(self, seeded):
        txs = get_recent_transactions(seeded, date_from="2025-02-10", date_to="2025-03-10")
        assert [t["date"] for t in txs] == ["2025-03-10", "2025-02-10"]
        assert [t["description"] for t in txs] == ["mar food", "feb transport"]

    def test_recent_transactions_only_date_from(self, seeded):
        txs = get_recent_transactions(seeded, date_from="2025-03-10")
        assert [t["date"] for t in txs] == ["2025-04-10", "2025-03-10"]

    def test_recent_transactions_only_date_to(self, seeded):
        txs = get_recent_transactions(seeded, date_to="2025-02-10")
        assert [t["date"] for t in txs] == ["2025-02-10", "2025-01-10"]

    def test_recent_transactions_limit_applies_within_filtered_set(self, user_id):
        for i in range(12):
            add_expense(user_id, 1.0, "Food", date(2025, 6, 1) + timedelta(days=i), "in%d" % i)
        add_expense(user_id, 1.0, "Food", "2025-01-01", "outside")
        txs = get_recent_transactions(user_id, limit=3, date_from="2025-06-01", date_to="2025-06-30")
        assert len(txs) == 3
        assert [t["date"] for t in txs] == ["2025-06-12", "2025-06-11", "2025-06-10"]
        default = get_recent_transactions(user_id, date_from="2025-06-01", date_to="2025-06-30")
        assert len(default) == 10

    def test_category_breakdown_filtered_amounts(self, seeded):
        cats = get_category_breakdown(seeded, date_from="2025-02-10", date_to="2025-03-10")
        assert [c["name"] for c in cats] == ["Food", "Transport"]
        assert [c["amount"] for c in cats] == [pytest.approx(30.0), pytest.approx(20.0)]

    def test_category_breakdown_only_date_from(self, seeded):
        cats = get_category_breakdown(seeded, date_from="2025-04-01")
        assert [c["name"] for c in cats] == ["Bills"]
        assert cats[0]["pct"] == 100

    def test_category_breakdown_pct_sums_to_100_in_filtered_set(self, seeded):
        cats = get_category_breakdown(seeded, date_from="2025-01-01", date_to="2025-03-31")
        assert sum(c["pct"] for c in cats) == 100

    def test_category_breakdown_pct_sums_to_100_with_awkward_thirds(self, user_id):
        for cat in ("Food", "Transport", "Bills"):
            add_expense(user_id, 10.0, cat, "2025-05-05", cat)
        add_expense(user_id, 999.0, "Health", "2024-01-01", "outside")
        cats = get_category_breakdown(user_id, date_from="2025-05-01", date_to="2025-05-31")
        assert len(cats) == 3
        assert sum(c["pct"] for c in cats) == 100

    def test_helpers_only_return_the_requested_users_rows(self, seeded, other_user_id):
        add_expense(other_user_id, 500.0, "Shopping", "2025-02-15", "other's purchase")
        stats = get_summary_stats(seeded, date_from="2025-02-01", date_to="2025-02-28")
        assert stats["total_spent"] == pytest.approx(20.00)
        assert all(
            t["description"] != "other's purchase"
            for t in get_recent_transactions(seeded, date_from="2025-02-01", date_to="2025-02-28")
        )
        assert "Shopping" not in [
            c["name"] for c in get_category_breakdown(seeded, date_from="2025-02-01", date_to="2025-02-28")
        ]


class TestQueryHelpersEmptyRange:
    def test_summary_stats_empty_range_is_zeroed(self, seeded):
        stats = get_summary_stats(seeded, date_from="2030-01-01", date_to="2030-12-31")
        assert stats["total_spent"] == 0
        assert stats["transaction_count"] == 0
        assert stats["top_category"] == "—"

    def test_recent_transactions_empty_range_is_empty_list(self, seeded):
        assert get_recent_transactions(seeded, date_from="2030-01-01", date_to="2030-12-31") == []

    def test_category_breakdown_empty_range_is_empty_list(self, seeded):
        assert get_category_breakdown(seeded, date_from="2030-01-01", date_to="2030-12-31") == []

    def test_user_with_no_expenses_is_empty_without_filter(self, user_id):
        assert get_summary_stats(user_id)["transaction_count"] == 0
        assert get_recent_transactions(user_id) == []
        assert get_category_breakdown(user_id) == []


class TestQueryHelpersSqlSafety:
    @pytest.mark.parametrize("payload", [
        "2025-01-01'; DROP TABLE expenses; --",
        "' OR '1'='1",
    ])
    def test_date_values_are_parameterised_not_interpolated(self, seeded, payload):
        # Must not raise and must not damage the table.
        get_summary_stats(seeded, date_from=payload, date_to=payload)
        get_recent_transactions(seeded, date_from=payload)
        get_category_breakdown(seeded, date_to=payload)
        assert get_summary_stats(seeded)["transaction_count"] == 4


# --------------------------------------------------------------------------- #
# GET /profile: auth                                                          #
# --------------------------------------------------------------------------- #

class TestProfileAuthGuard:
    @pytest.mark.parametrize("params", [
        {},
        {"date_from": "2025-01-01", "date_to": "2025-12-31"},
        {"date_from": "not-a-date"},
        {"date_from": "2025-12-31", "date_to": "2025-01-01"},
    ])
    def test_logged_out_user_is_redirected_to_login(self, anon_client, params):
        resp = get_profile(anon_client, **params)
        assert resp.status_code == 302, "expected redirect, got %s" % resp.status_code
        assert urlparse(resp.headers["Location"]).path == login_url()

    def test_logged_out_user_sees_no_profile_data(self, anon_client, user_id):
        add_expense(user_id, 12.5, "Food", date.today(), "secret-lunch")
        resp = get_profile(anon_client, date_from=date.today().isoformat())
        assert b"secret-lunch" not in resp.data


# --------------------------------------------------------------------------- #
# GET /profile: filtering behaviour                                           #
# --------------------------------------------------------------------------- #

@pytest.fixture
def around_today(user_id):
    """Expenses placed around today / this month / 3 and 6 month boundaries."""
    today = date.today()
    ms, me = month_start(today), month_end(today)
    m3, m6 = months_before(today, 3), months_before(today, 6)
    rows = [
        # (amount, category, date, description)
        (11.00, "Food", ms, "zz-month-start"),
        (22.00, "Transport", me, "zz-month-end"),
        (33.00, "Bills", ms - timedelta(days=1), "zz-before-month"),
        (44.00, "Health", me + timedelta(days=1), "zz-after-month"),
        (55.00, "Shopping", m3, "zz-m3-boundary"),
        (66.00, "Other", m3 - timedelta(days=1), "zz-before-m3"),
        (77.00, "Entertainment", m6, "zz-m6-boundary"),
        (88.00, "Food", m6 - timedelta(days=1), "zz-before-m6"),
        (99.00, "Bills", today, "zz-today"),
        (13.00, "Other", today + timedelta(days=1), "zz-tomorrow"),
    ]
    for amount, cat, d, desc in rows:
        add_expense(user_id, amount, cat, d, desc)
    return {"today": today, "ms": ms, "me": me, "m3": m3, "m6": m6}


ALL_DESCS = [
    "zz-month-start", "zz-month-end", "zz-before-month", "zz-after-month",
    "zz-m3-boundary", "zz-before-m3", "zz-m6-boundary", "zz-before-m6",
    "zz-today", "zz-tomorrow",
]


def assert_visible(page, visible):
    for desc in ALL_DESCS:
        if desc in visible:
            assert desc in page, "%s should be shown" % desc
        else:
            assert desc not in page, "%s should NOT be shown" % desc


class TestProfileUnfiltered:
    def test_no_params_returns_200_and_filter_bar(self, auth_client):
        resp = get_profile(auth_client)
        assert resp.status_code == 200
        assert "pf-filter" in text_of(resp)

    def test_no_params_shows_all_expenses_like_step_5(self, auth_client, around_today):
        page = text_of(get_profile(auth_client))
        assert_visible(page, set(ALL_DESCS))

    def test_no_params_summary_covers_every_expense(self, auth_client, around_today):
        total = 11 + 22 + 33 + 44 + 55 + 66 + 77 + 88 + 99 + 13
        total_txt, count_txt, _ = stat_values(text_of(get_profile(auth_client)))
        assert total_txt == "₹%.2f" % total
        assert count_txt == "10"


class TestProfilePresetFiltering:
    def test_this_month_covers_whole_calendar_month(self, auth_client, around_today):
        d = around_today
        page = text_of(get_profile(auth_client, date_from=d["ms"].isoformat(), date_to=d["me"].isoformat()))
        for desc in ("zz-month-start", "zz-month-end", "zz-today"):
            assert desc in page, "%s should be in This Month" % desc
        for desc in ("zz-before-month", "zz-after-month", "zz-m3-boundary",
                     "zz-before-m3", "zz-m6-boundary", "zz-before-m6"):
            assert desc not in page, "%s should be excluded from This Month" % desc

    def test_this_month_applies_to_all_three_sections(self, auth_client, user_id):
        today = date.today()
        ms, me = month_start(today), month_end(today)
        add_expense(user_id, 40.0, "Food", ms, "in-1")
        add_expense(user_id, 60.0, "Transport", me, "in-2")
        add_expense(user_id, 500.0, "Health", ms - timedelta(days=1), "out-1")
        add_expense(user_id, 700.0, "Shopping", me + timedelta(days=1), "out-2")
        page = text_of(get_profile(auth_client, date_from=ms.isoformat(), date_to=me.isoformat()))
        total_txt, count_txt, top = stat_values(page)
        assert total_txt == "₹100.00"
        assert count_txt == "2"
        assert top == "Transport"
        assert sorted(category_names(page)) == ["Food", "Transport"]
        assert "in-1" in page and "in-2" in page
        assert "out-1" not in page and "out-2" not in page

    def test_last_3_months_window_ends_today_and_is_inclusive(self, auth_client, around_today):
        d = around_today
        page = text_of(get_profile(auth_client, date_from=d["m3"].isoformat(), date_to=d["today"].isoformat()))
        assert "zz-m3-boundary" in page
        assert "zz-today" in page
        assert "zz-before-m3" not in page
        assert "zz-tomorrow" not in page
        assert "zz-before-m6" not in page

    def test_last_6_months_window_ends_today_and_is_inclusive(self, auth_client, around_today):
        d = around_today
        page = text_of(get_profile(auth_client, date_from=d["m6"].isoformat(), date_to=d["today"].isoformat()))
        assert "zz-m6-boundary" in page
        assert "zz-m3-boundary" in page
        assert "zz-today" in page
        assert "zz-before-m6" not in page
        assert "zz-tomorrow" not in page

    def test_preset_links_from_page_filter_correctly(self, auth_client, around_today):
        presets = parse_presets(text_of(get_profile(auth_client)))
        page = text_of(auth_client.get(presets["Last 3 Months"]["href"]))
        assert "zz-m3-boundary" in page and "zz-before-m3" not in page
        page = text_of(auth_client.get(presets["Last 6 Months"]["href"]))
        assert "zz-m6-boundary" in page and "zz-before-m6" not in page
        page = text_of(auth_client.get(presets["This Month"]["href"]))
        assert "zz-month-start" in page and "zz-before-month" not in page
        page = text_of(auth_client.get(presets["All Time"]["href"]))
        assert_visible(page, set(ALL_DESCS))


class TestProfileCustomRange:
    def test_both_bounds_inclusive_in_all_sections(self, auth_client, user_id):
        today = date.today()
        lo, hi = today - timedelta(days=20), today - timedelta(days=10)
        add_expense(user_id, 10.0, "Food", lo, "edge-lo")
        add_expense(user_id, 20.0, "Transport", hi, "edge-hi")
        add_expense(user_id, 30.0, "Food", lo - timedelta(days=1), "just-before")
        add_expense(user_id, 40.0, "Health", hi + timedelta(days=1), "just-after")
        page = text_of(get_profile(auth_client, date_from=lo.isoformat(), date_to=hi.isoformat()))
        assert "edge-lo" in page and "edge-hi" in page
        assert "just-before" not in page and "just-after" not in page
        total_txt, count_txt, top = stat_values(page)
        assert (total_txt, count_txt, top) == ("₹30.00", "2", "Transport")
        assert sorted(category_names(page)) == ["Food", "Transport"]

    def test_single_day_range_where_from_equals_to_is_valid(self, auth_client, user_id):
        day = date.today() - timedelta(days=7)
        add_expense(user_id, 9.0, "Food", day, "that-day")
        add_expense(user_id, 9.0, "Food", day + timedelta(days=1), "next-day")
        page = text_of(get_profile(auth_client, date_from=day.isoformat(), date_to=day.isoformat()))
        assert "Start date must be before end date." not in page
        assert "that-day" in page and "next-day" not in page

    def test_only_date_from_filters_lower_bound(self, auth_client, user_id):
        today = date.today()
        cut = today - timedelta(days=30)
        add_expense(user_id, 1.0, "Food", cut, "on-cut")
        add_expense(user_id, 2.0, "Food", cut - timedelta(days=1), "before-cut")
        add_expense(user_id, 3.0, "Food", today + timedelta(days=60), "far-future")
        page = text_of(get_profile(auth_client, date_from=cut.isoformat()))
        assert "on-cut" in page and "far-future" in page
        assert "before-cut" not in page

    def test_only_date_to_filters_upper_bound(self, auth_client, user_id):
        today = date.today()
        cut = today - timedelta(days=30)
        add_expense(user_id, 1.0, "Food", cut, "on-cut")
        add_expense(user_id, 2.0, "Food", cut + timedelta(days=1), "after-cut")
        add_expense(user_id, 3.0, "Food", cut - timedelta(days=400), "long-ago")
        page = text_of(get_profile(auth_client, date_to=cut.isoformat()))
        assert "on-cut" in page and "long-ago" in page
        assert "after-cut" not in page

    def test_valid_from_with_malformed_to_applies_one_sided_filter(self, auth_client, user_id):
        today = date.today()
        cut = today - timedelta(days=30)
        add_expense(user_id, 1.0, "Food", cut, "kept")
        add_expense(user_id, 2.0, "Food", cut - timedelta(days=1), "dropped")
        resp = get_profile(auth_client, date_from=cut.isoformat(), date_to="not-a-date")
        page = text_of(resp)
        assert resp.status_code == 200
        assert "kept" in page and "dropped" not in page
        assert input_value(page, "date_from") == cut.isoformat()
        assert input_value(page, "date_to") == ""

    def test_other_users_expenses_never_appear_when_filtered(self, auth_client, other_user_id):
        today = date.today()
        add_expense(other_user_id, 1234.0, "Shopping", today, "not-mine")
        page = text_of(get_profile(auth_client, date_from=today.isoformat(), date_to=today.isoformat()))
        assert "not-mine" not in page
        assert stat_values(page)[0] == "₹0.00"


class TestProfileEmptyRange:
    def test_range_with_no_expenses_shows_zero_state_without_error(self, auth_client, around_today):
        resp = get_profile(auth_client, date_from="2000-01-01", date_to="2000-01-31")
        page = text_of(resp)
        assert resp.status_code == 200
        total_txt, count_txt, top = stat_values(page)
        assert total_txt == "₹0.00"
        assert count_txt == "0"
        assert top == "—"
        assert category_names(page) == []
        for desc in ALL_DESCS:
            assert desc not in page

    def test_user_with_no_expenses_at_all_gets_zero_state(self, auth_client):
        resp = get_profile(auth_client, date_from="2020-01-01", date_to="2020-12-31")
        assert resp.status_code == 200
        assert stat_values(text_of(resp))[0] == "₹0.00"


# --------------------------------------------------------------------------- #
# GET /profile: invalid input                                                 #
# --------------------------------------------------------------------------- #

class TestProfileInvalidInput:
    @pytest.mark.parametrize("bad", MALFORMED_DATES)
    @pytest.mark.parametrize("param", ["date_from", "date_to"])
    def test_single_malformed_date_gives_200_and_unfiltered_view(
        self, auth_client, around_today, bad, param
    ):
        resp = get_profile(auth_client, **{param: bad})
        assert resp.status_code == 200, "malformed %s=%r must not crash" % (param, bad)
        assert_visible(text_of(resp), set(ALL_DESCS))

    @pytest.mark.parametrize("bad", MALFORMED_DATES)
    def test_both_dates_malformed_gives_unfiltered_view(self, auth_client, around_today, bad):
        resp = get_profile(auth_client, date_from=bad, date_to=bad)
        assert resp.status_code == 200
        assert_visible(text_of(resp), set(ALL_DESCS))

    @pytest.mark.parametrize("bad", MALFORMED_DATES)
    def test_malformed_date_does_not_flash_range_error(self, auth_client, bad):
        page = text_of(get_profile(auth_client, date_from=bad))
        assert "Start date must be before end date." not in page

    def test_malformed_date_leaves_inputs_empty_and_all_time_active(self, auth_client):
        page = text_of(get_profile(auth_client, date_from="not-a-date", date_to="2026-13-45"))
        assert input_value(page, "date_from") == ""
        assert input_value(page, "date_to") == ""
        presets = parse_presets(page)
        assert presets["All Time"]["active"]
        assert not form_is_active(page)

    def test_empty_string_params_behave_as_absent(self, auth_client, around_today):
        resp = get_profile(auth_client, date_from="", date_to="")
        assert resp.status_code == 200
        assert_visible(text_of(resp), set(ALL_DESCS))

    def test_sql_injection_in_date_params_is_harmless(self, auth_client, around_today):
        payload = "2025-01-01'; DROP TABLE expenses; --"
        resp = get_profile(auth_client, date_from=payload, date_to=payload)
        assert resp.status_code == 200
        assert_visible(text_of(resp), set(ALL_DESCS))
        conn = get_db()
        try:
            count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        finally:
            conn.close()
        assert count == len(ALL_DESCS), "expenses table must be intact"

    def test_from_after_to_flashes_error(self, auth_client):
        today = date.today()
        resp = get_profile(
            auth_client,
            date_from=today.isoformat(),
            date_to=(today - timedelta(days=5)).isoformat(),
        )
        assert resp.status_code == 200
        assert "Start date must be before end date." in text_of(resp)

    def test_from_after_to_falls_back_to_unfiltered_view(self, auth_client, around_today):
        d = around_today
        page = text_of(get_profile(
            auth_client, date_from=d["today"].isoformat(), date_to=d["m6"].isoformat()
        ))
        assert_visible(page, set(ALL_DESCS))
        assert stat_values(page)[1] == str(len(ALL_DESCS))

    def test_from_after_to_clears_inputs_and_marks_all_time(self, auth_client):
        today = date.today()
        page = text_of(get_profile(
            auth_client,
            date_from=today.isoformat(),
            date_to=(today - timedelta(days=5)).isoformat(),
        ))
        assert input_value(page, "date_from") == ""
        assert input_value(page, "date_to") == ""
        assert parse_presets(page)["All Time"]["active"]
        assert not form_is_active(page)

    def test_valid_range_does_not_show_error_flash(self, auth_client):
        today = date.today()
        page = text_of(get_profile(auth_client, date_from=(today - timedelta(days=3)).isoformat(),
                                   date_to=today.isoformat()))
        assert "Start date must be before end date." not in page


# --------------------------------------------------------------------------- #
# Filter bar                                                                  #
# --------------------------------------------------------------------------- #

class TestFilterBar:
    def test_four_presets_are_shown(self, auth_client):
        presets = parse_presets(text_of(get_profile(auth_client)))
        assert set(presets) == {"This Month", "Last 3 Months", "Last 6 Months", "All Time"}

    def test_all_time_link_is_bare_profile_url(self, auth_client):
        href = parse_presets(text_of(get_profile(auth_client)))["All Time"]["href"]
        assert href == profile_url()
        assert "?" not in href, "All Time must carry no query string"

    def test_all_time_link_is_bare_even_when_a_filter_is_active(self, auth_client):
        today = date.today()
        page = text_of(get_profile(auth_client, date_from=(today - timedelta(days=3)).isoformat()))
        assert parse_presets(page)["All Time"]["href"] == profile_url()

    def test_preset_links_carry_expected_date_params(self, auth_client):
        today = date.today()
        presets = parse_presets(text_of(get_profile(auth_client)))
        expected = {
            "This Month": (month_start(today), month_end(today)),
            "Last 3 Months": (months_before(today, 3), today),
            "Last 6 Months": (months_before(today, 6), today),
        }
        for label, (lo, hi) in expected.items():
            href = presets[label]["href"]
            assert urlparse(href).path == profile_url()
            assert query_of(href) == {"date_from": lo.isoformat(), "date_to": hi.isoformat()}, label

    def test_custom_form_has_named_date_inputs_and_apply_button(self, auth_client):
        page = text_of(get_profile(auth_client))
        assert re.search(r'<input\b[^>]*type="date"[^>]*name="date_from"', page) or \
            re.search(r'<input\b[^>]*name="date_from"[^>]*type="date"', page)
        assert re.search(r'<input\b[^>]*type="date"[^>]*name="date_to"', page) or \
            re.search(r'<input\b[^>]*name="date_to"[^>]*type="date"', page)
        assert "Apply" in page
        assert re.search(r'<form\b[^>]*method="get"', page, re.I), "filter form must use GET"

    def test_no_filter_marks_only_all_time_active(self, auth_client):
        page = text_of(get_profile(auth_client))
        presets = parse_presets(page)
        assert [k for k, v in presets.items() if v["active"]] == ["All Time"]
        assert not form_is_active(page)
        assert input_value(page, "date_from") == ""
        assert input_value(page, "date_to") == ""

    @pytest.mark.parametrize("label", ["This Month", "Last 3 Months", "Last 6 Months"])
    def test_applying_a_preset_marks_only_that_preset_active(self, auth_client, label):
        href = parse_presets(text_of(get_profile(auth_client)))[label]["href"]
        page = text_of(auth_client.get(href))
        presets = parse_presets(page)
        assert [k for k, v in presets.items() if v["active"]] == [label]
        assert not form_is_active(page), "custom form must not be active for a preset"

    @pytest.mark.parametrize("label", ["This Month", "Last 3 Months", "Last 6 Months"])
    def test_applying_a_preset_prefills_date_inputs(self, auth_client, label):
        href = parse_presets(text_of(get_profile(auth_client)))[label]["href"]
        q = query_of(href)
        page = text_of(auth_client.get(href))
        assert input_value(page, "date_from") == q["date_from"]
        assert input_value(page, "date_to") == q["date_to"]

    def test_all_time_active_after_clicking_it_from_a_filtered_view(self, auth_client):
        today = date.today()
        filtered = text_of(get_profile(auth_client, date_from=(today - timedelta(days=2)).isoformat(),
                                       date_to=today.isoformat()))
        href = parse_presets(filtered)["All Time"]["href"]
        page = text_of(auth_client.get(href))
        assert parse_presets(page)["All Time"]["active"]

    def test_custom_range_marks_form_active_and_no_preset(self, auth_client):
        today = date.today()
        lo, hi = today - timedelta(days=5), today - timedelta(days=2)
        page = text_of(get_profile(auth_client, date_from=lo.isoformat(), date_to=hi.isoformat()))
        assert form_is_active(page)
        assert not any(p["active"] for p in parse_presets(page).values())

    def test_custom_range_prefills_inputs(self, auth_client):
        today = date.today()
        lo, hi = today - timedelta(days=5), today - timedelta(days=2)
        page = text_of(get_profile(auth_client, date_from=lo.isoformat(), date_to=hi.isoformat()))
        assert input_value(page, "date_from") == lo.isoformat()
        assert input_value(page, "date_to") == hi.isoformat()

    def test_one_sided_custom_range_marks_form_active_and_prefills(self, auth_client):
        today = date.today()
        lo = today - timedelta(days=9)
        page = text_of(get_profile(auth_client, date_from=lo.isoformat()))
        assert form_is_active(page)
        assert not any(p["active"] for p in parse_presets(page).values())
        assert input_value(page, "date_from") == lo.isoformat()
        assert input_value(page, "date_to") == ""

    def test_only_date_to_prefills_only_date_to(self, auth_client):
        hi = date.today() - timedelta(days=9)
        page = text_of(get_profile(auth_client, date_to=hi.isoformat()))
        assert form_is_active(page)
        assert input_value(page, "date_from") == ""
        assert input_value(page, "date_to") == hi.isoformat()


# --------------------------------------------------------------------------- #
# Preset date arithmetic with a frozen "today"                                #
# --------------------------------------------------------------------------- #

@pytest.fixture
def freeze_today(monkeypatch):
    """Freeze date.today() as seen by app.py (it does `from datetime import date`)."""
    if not hasattr(app_module, "date"):
        pytest.skip("app module does not expose `date`; cannot freeze today")

    def _freeze(fixed):
        class FakeDate(date):
            @classmethod
            def today(cls):
                return fixed
        monkeypatch.setattr(app_module, "date", FakeDate)

    return _freeze


PRESET_CASES = [
    # today, this_from, this_to, last3_from, last6_from
    (date(2026, 10, 6), date(2026, 10, 1), date(2026, 10, 31), date(2026, 7, 6), date(2026, 4, 6)),
    (date(2026, 12, 15), date(2026, 12, 1), date(2026, 12, 31), date(2026, 9, 15), date(2026, 6, 15)),
    # month-length clamping
    (date(2026, 8, 31), date(2026, 8, 1), date(2026, 8, 31), date(2026, 5, 31), date(2026, 2, 28)),
    (date(2026, 5, 31), date(2026, 5, 1), date(2026, 5, 31), date(2026, 2, 28), date(2025, 11, 30)),
    # leap year handling
    (date(2028, 8, 31), date(2028, 8, 1), date(2028, 8, 31), date(2028, 5, 31), date(2028, 2, 29)),
    (date(2028, 2, 10), date(2028, 2, 1), date(2028, 2, 29), date(2027, 11, 10), date(2027, 8, 10)),
    # non-leap February end and year wrap
    (date(2026, 2, 15), date(2026, 2, 1), date(2026, 2, 28), date(2025, 11, 15), date(2025, 8, 15)),
]


class TestPresetDateArithmetic:
    @pytest.mark.parametrize("today,this_from,this_to,l3,l6", PRESET_CASES)
    def test_preset_links_for_fixed_today(self, auth_client, freeze_today, today, this_from, this_to, l3, l6):
        freeze_today(today)
        presets = parse_presets(text_of(get_profile(auth_client)))
        assert query_of(presets["This Month"]["href"]) == {
            "date_from": this_from.isoformat(), "date_to": this_to.isoformat()}
        assert query_of(presets["Last 3 Months"]["href"]) == {
            "date_from": l3.isoformat(), "date_to": today.isoformat()}
        assert query_of(presets["Last 6 Months"]["href"]) == {
            "date_from": l6.isoformat(), "date_to": today.isoformat()}

    def test_this_month_end_is_last_day_even_when_today_is_mid_month(self, auth_client, freeze_today):
        freeze_today(date(2026, 4, 3))
        href = parse_presets(text_of(get_profile(auth_client)))["This Month"]["href"]
        assert query_of(href)["date_to"] == "2026-04-30"

    def test_last_months_end_today_not_month_end(self, auth_client, freeze_today):
        freeze_today(date(2026, 4, 3))
        presets = parse_presets(text_of(get_profile(auth_client)))
        assert query_of(presets["Last 3 Months"]["href"])["date_to"] == "2026-04-03"
        assert query_of(presets["Last 6 Months"]["href"])["date_to"] == "2026-04-03"

    def test_requesting_frozen_this_month_range_marks_preset_active(self, auth_client, freeze_today):
        freeze_today(date(2026, 2, 10))
        page = text_of(get_profile(auth_client, date_from="2026-02-01", date_to="2026-02-28"))
        assert [k for k, v in parse_presets(page).items() if v["active"]] == ["This Month"]

    def test_this_month_includes_future_days_of_current_month(self, auth_client, user_id, freeze_today):
        freeze_today(date(2026, 4, 3))
        add_expense(user_id, 5.0, "Food", "2026-04-30", "month-end-row")
        add_expense(user_id, 5.0, "Food", "2026-05-01", "next-month-row")
        href = parse_presets(text_of(get_profile(auth_client)))["This Month"]["href"]
        page = text_of(auth_client.get(href))
        assert "month-end-row" in page
        assert "next-month-row" not in page


# --------------------------------------------------------------------------- #
# Currency                                                                    #
# --------------------------------------------------------------------------- #

class TestRupeeSymbol:
    @pytest.mark.parametrize("params_factory", [
        lambda d: {},
        lambda d: {"date_from": d["ms"].isoformat(), "date_to": d["me"].isoformat()},
        lambda d: {"date_from": d["m3"].isoformat(), "date_to": d["today"].isoformat()},
        lambda d: {"date_from": "2000-01-01", "date_to": "2000-01-02"},
        lambda d: {"date_from": "not-a-date"},
    ])
    def test_amounts_use_rupee_symbol_for_every_filter(self, auth_client, around_today, params_factory):
        page = text_of(get_profile(auth_client, **params_factory(around_today)))
        assert "₹" in page
        assert not re.search(r"[$£€]\s?\d", page), "no other currency symbol expected"
        # Every money value (stat total, transaction amounts, category amounts)
        # rendered as N.NN must be prefixed with the rupee sign.
        money = re.findall(r'(?:pf-stat-value|pf-amount|pf-cat-amount)">\s*([^<]*)<', page)
        money = [m.strip() for m in money if re.search(r"\d+\.\d{2}", m)]
        assert money, "expected at least one monetary value"
        assert all(m.startswith("₹") for m in money), money

    def test_filtered_transaction_and_category_amounts_have_rupee(self, auth_client, user_id):
        today = date.today()
        add_expense(user_id, 12.5, "Food", today, "rupee-check")
        page = text_of(get_profile(auth_client, date_from=today.isoformat(), date_to=today.isoformat()))
        assert page.count("₹12.50") >= 3, "total, transaction row and category all show ₹12.50"

    def test_empty_range_shows_rupee_zero_total(self, auth_client):
        page = text_of(get_profile(auth_client, date_from="2000-01-01", date_to="2000-01-02"))
        assert "₹0.00" in page
