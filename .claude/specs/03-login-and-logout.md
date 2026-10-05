# Spec: Login and Logout

## Overview
Turn the static `/login` page into a working sign-in flow and replace the
`/logout` placeholder with a real logout. A registered user submits their email
and password; the app looks the user up, verifies the password hash with
werkzeug, and stores the user's id and name in Flask's signed `session` cookie.
Logging out clears the session. The navbar becomes session-aware, showing
"Sign in / Get started" to visitors and the user's name plus "Sign out" to
logged-in users. This step introduces the notion of a current user, which every
logged-in feature that follows (profile in Step 4, expense CRUD in Steps 7–9)
depends on.

## Depends on
- Step 1 — Database setup (`get_db()`, `users` table, seeded demo user
  `demo@spendly.com` / `demo123`)
- Step 2 — Registration (`get_user_by_email()`, `app.secret_key`, flash message
  rendering in `login.html`, `.auth-success` style)

## Routes
- `GET /login` — render the sign-in form; if already logged in, redirect to
  `/profile` — public
- `POST /login` — validate credentials, set the session, redirect to `/profile`
  on success or re-render the form with an error on failure — public
- `GET /register` — if already logged in, redirect to `/profile` (existing
  view; add the guard before any GET/POST handling) — public
- `GET /profile` — minimal placeholder page rendered through `base.html` so the
  navbar (user name + "Sign out") is visible after login; redirects to
  `/login` when logged out. Step 4 replaces the content — logged-in
- `GET /logout` — clear the session, flash "You have been signed out.", and
  redirect to `/` (landing) — public (safe to hit while logged out)

`/login` is handled by the existing `login` view (update it to accept
`methods=["GET", "POST"]`). `/logout` replaces the body of the existing
`logout` placeholder. Do not add parallel routes.

`/profile` is the post-login redirect target. Its body is only a placeholder
until Step 4, but it must extend `base.html` — a bare string has no navbar, so
the user would have no way to sign out.

## Database changes
No database changes. The existing `users` table and the `get_user_by_email()`
helper from Step 2 already return `id`, `name`, `email`, and `password_hash`.

## Templates
- **Create:**
  - `templates/profile.html` — placeholder extending `base.html` with a
    greeting ("Hi, <name>") and a note that the profile arrives in Step 4
- **Modify:**
  - `templates/login.html` — use `url_for('login')` for the form action instead
    of the hard-coded `/login`; re-fill the submitted `email` after an error
    (never re-fill the password)
  - `templates/base.html` — make the navbar session-aware: when
    `session.user_id` is set, show the user's name (`session.user_name`) and a
    "Sign out" link to `url_for('logout')`; otherwise keep the existing
    "Sign in" / "Get started" links
  - `templates/landing.html` — render flashed messages (e.g. "You have been
    signed out.") so the logout confirmation is visible after the redirect

## Files to change
- `app.py` — import `session` and `check_password_hash`; implement GET/POST
  logic in `login()`; implement `logout()`; redirect logged-in users away from
  `/register`; render `profile.html` from `profile()`
- `templates/login.html` — `url_for` action, preserve email on error
- `templates/base.html` — session-aware navbar links
- `templates/landing.html` — display flashed messages
- `static/css/style.css` — style for the navbar user name (e.g. `.nav-user`),
  and a flash container on the landing page if needed, using existing variables

## Files to create
- `templates/profile.html`

## New dependencies
No new dependencies. Use Flask's built-in `session` and
`werkzeug.security.check_password_hash` (already installed with Flask).

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never build SQL with string formatting
- Passwords hashed with werkzeug — verify with `check_password_hash`; never
  compare plain-text passwords, never log or store the submitted password
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Normalise the submitted email (strip + lowercase) before lookup, matching
  Step 2's registration behaviour
- Server-side validation: email and password must both be non-empty
- Use one generic error message — "Invalid email or password." — for both an
  unknown email and a wrong password, so the form does not reveal which emails
  are registered
- On success: call `session.clear()` first, then set `session["user_id"]` and
  `session["user_name"]`; never put the password hash in the session
- On failure: re-render `login.html` with `error` and the submitted `email`
  (HTTP 200 is fine; do not flash the error)
- `logout()` must call `session.clear()` and redirect; it must not error when
  no one is logged in
- Logout via GET is acceptable for this course step (the placeholder route is
  GET); do not add CSRF tooling in this step
- Do not implement a `login_required` decorator yet; a simple
  `session.get("user_id")` check in `profile()` is enough for this step

## Definition of done
- [ ] `GET /login` shows the sign-in form
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects to `/profile`
      and the navbar shows "Demo User" and a "Sign out" link
- [ ] Signing in with an uppercase email (`DEMO@spendly.com`) also succeeds
- [ ] A wrong password shows "Invalid email or password.", keeps the email in
      the field, leaves the password field empty, and does not log the user in
- [ ] An unregistered email shows the same "Invalid email or password." message
- [ ] A newly registered account (via `/register`) can sign in immediately
- [ ] Visiting `/login` or `/register` while logged in redirects to `/profile`
- [ ] `/profile` shows the navbar with the user's name and "Sign out"
- [ ] Visiting `/profile` while logged out redirects to `/login`
- [ ] Clicking "Sign out" lands on `/`, shows "You have been signed out.", and
      the navbar returns to "Sign in" / "Get started"
- [ ] Visiting `/logout` while already logged out redirects to `/` without error
- [ ] The session cookie does not contain the password or password hash
- [ ] No hex colours were added to CSS; new styles use existing variables
- [ ] App starts without errors and all other pages still render
