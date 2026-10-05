# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Spendly — a Flask expense tracker built as a step-by-step course project. Much of the app is intentionally scaffolded: placeholder routes and stub files are labeled with the course step that implements them (e.g. "coming in Step 3"). When implementing a feature, look for the matching placeholder rather than adding a parallel route/file.

## Commands

```bash
python3 -m venv venv && source venv/bin/activate   # venv/ is gitignored
pip install -r requirements.txt
python3 app.py                                     # dev server on http://127.0.0.1:5001 (debug mode)
pytest                                             # pytest + pytest-flask; no tests exist yet
pytest path/to/test_file.py::test_name             # single test
```

The dev server runs in the foreground and never exits — run it in the background when launching from a tool.

## Architecture

- `app.py` — the entire Flask app (no blueprints or app factory). Public pages (`/`, `/login`, `/register`, `/terms`, `/privacy`) render templates; auth, profile, and expense CRUD routes (`/logout`, `/profile`, `/expenses/add`, `/expenses/<id>/edit`, `/expenses/<id>/delete`) currently return placeholder strings.
- `database/db.py` — stub to be implemented in Step 1: `get_db()` (SQLite connection with `row_factory` and foreign keys enabled), `init_db()` (`CREATE TABLE IF NOT EXISTS`), `seed_db()` (dev sample data). The DB file `expense_tracker.db` is gitignored.
- `templates/` — all pages extend `base.html`, which provides the navbar, footer, Google Fonts (DM Serif Display / DM Sans), global `static/css/style.css`, and `static/js/main.js`. Blocks: `title`, `head` (page-specific CSS, e.g. `landing.html` loads `css/landing.css`), `content`, `scripts`. Links use `url_for(<view function name>)`.
- `static/` — plain CSS/JS, no build step. Landing-page styles use an `lp-` class prefix.
- `design/` — reference mockups (e.g. `hero_section.png`) for UI work.

`file.txt` is a pasted terminal session log, not project source.

## Conventions

Commit messages are prefixed with the area, e.g. `landing: add privacy policy page and route`.
