# Spec: Registration

## Overview
Turn the existing static `/register` page into a working sign-up flow. A visitor
submits their name, email, and password; the app validates the input, rejects
duplicate emails, hashes the password with werkzeug, and inserts a new row into
the `users` table created in Step 1. On success the user is redirected to the
login page with a confirmation message. This is the first feature that writes
user-supplied data to the database and is the prerequisite for login/logout
(Step 3) and every logged-in feature after it.

## Depends on
- Step 1 — Database setup (`get_db()`, `init_db()`, `users` table with
  `UNIQUE` email constraint)

## Routes
- `GET /register` — render the registration form — public
- `POST /register` — validate input, create the user, redirect to `/login` on
  success or re-render the form with an error on failure — public

Both are handled by the existing `register` view function in `app.py`
(update it to accept `methods=["GET", "POST"]`; do not add a parallel route).

## Database changes
No database changes. The existing `users` table (`id`, `name`, `email UNIQUE`,
`password_hash`, `created_at`) already supports registration.

Add helper functions to `database/db.py`:
- `get_user_by_email(email)` — returns the matching `sqlite3.Row` or `None`
- `create_user(name, email, password_hash)` — inserts a user and returns the
  new `id`

## Templates
- **Create:** none
- **Modify:**
  - `templates/register.html` — keep submitted `name` and `email` values in the
    inputs when re-rendering after an error (never re-fill the password); add
    `minlength="8"` to the password input; use `url_for('register')` for the
    form action instead of the hard-coded `/register`; add a "Confirm password"
    input (`name="confirm_password"`, `minlength="8"`, `required`) below the
    password field, never re-filled after an error
  - `templates/login.html` — render flashed messages (e.g. "Account created —
    please sign in") above the login form

## Files to change
- `app.py` — import `request`, `redirect`, `url_for`, `flash`; set
  `app.secret_key`; implement GET/POST logic in `register()`
- `database/db.py` — add `get_user_by_email()` and `create_user()`
- `templates/register.html` — preserve input values, `minlength`, `url_for` action,
  confirm password field
- `templates/login.html` — display flashed success messages
- `static/css/style.css` — add an `.auth-success` style next to `.auth-error`

## Files to create
- None

## New dependencies
No new dependencies. Use `werkzeug.security.generate_password_hash` (already
installed with Flask) and the standard-library `sqlite3`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never build SQL with string formatting
- Passwords hashed with werkzeug (`generate_password_hash`); never store or log
  the plain-text password
- Use CSS variables — never hardcode hex values (`.auth-success` should use
  `var(--accent-light)` / `var(--accent)`)
- All templates extend `base.html`
- Server-side validation is required even though the form has HTML `required`
  attributes:
  - `name` — required, stripped, not empty
  - `email` — required, stripped, lowercased, must contain `@` and `.`
  - `password` — required, at least 8 characters
  - `confirm_password` — must exactly match `password`
- Normalise email to lowercase before checking for duplicates and inserting
- Check for an existing email before inserting, and also catch
  `sqlite3.IntegrityError` as a fallback for the `UNIQUE` constraint
- Always close the DB connection (use `try/finally` or a context manager)
- On error, re-render `register.html` with an `error` message and the submitted
  `name`/`email`; on success, `flash()` a message and `redirect(url_for('login'))`
- Read `app.secret_key` from the `SECRET_KEY` environment variable, with a
  dev-only fallback string
- Do not log the user in automatically — sessions belong to Step 3

## Definition of done
- [ ] `GET /register` shows the registration form
- [ ] Submitting valid details creates a new row in `users` with a hashed
      password (the `password_hash` column does not contain the plain password)
- [ ] After successful registration the browser lands on `/login` and shows a
      success message
- [ ] Registering with an email that already exists (e.g. `demo@spendly.com`)
      shows "An account with this email already exists" and creates no new row
- [ ] Email uniqueness is case-insensitive (`DEMO@spendly.com` is rejected)
- [ ] A password shorter than 8 characters shows an error and creates no row
- [ ] Mismatched password and confirm password shows "Passwords do not match"
      and creates no row
- [ ] Submitting a blank name (whitespace only) shows an error
- [ ] After an error, the name and email fields keep their values; both password
      fields are empty
- [ ] No hex colours were added to CSS; new styles use existing variables
- [ ] App starts without errors and all other pages still render
