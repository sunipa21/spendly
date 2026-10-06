# Spec: Profile Page Design

## Overview
Replace the Step 3 placeholder at `/profile` with the full visual design of the
logged-in user's profile page. The page has four sections: a user info card
(avatar initials, name, email, member-since date), a row of summary stat cards
(total spent, number of transactions, top category), a recent transactions
table, and a spending-by-category breakdown. This step is **design only**: the
`profile()` view passes hardcoded sample data to the template so the layout,
styling, and template structure can be built and reviewed without database
work. Step 5 will swap the hardcoded data for real queries, so the template
must take all of its content from context variables and must not contain
hardcoded figures itself.

## Depends on
- Step 1 — Database setup (`CATEGORIES` list, which defines the category names
  used in the sample data)
- Step 3 — Login and Logout (`session["user_id"]` / `session["user_name"]`, the
  logged-out redirect in `profile()`, the existing `templates/profile.html`
  placeholder, and the session-aware navbar)

## Routes
No new routes. The existing `GET /profile` view in `app.py` is updated to:
- keep its current guard (redirect to `/login` when `session.user_id` is not
  set) — logged-in
- build hardcoded `user`, `stats`, `transactions`, and `categories` context
  values and pass them to `render_template("profile.html", ...)`

Do not add a parallel route.

## Database changes
No database changes. Nothing is read from or written to the database in this
step. (Verified against `database/db.py`: the existing `users` and `expenses`
tables already hold everything Step 5 will need for this page.)

## Templates
- **Create:** none
- **Modify:**
  - `templates/profile.html` — replace the placeholder greeting with the full
    profile layout. Keep `{% extends "base.html" %}` and the `title` block; add
    a `head` block that loads `css/profile.css`. Sections, top to bottom:
    1. **User info card** — circular avatar showing the user's initials, the
       user's name (display font), email, and "Member since <Month YYYY>"
    2. **Summary stats** — three stat cards: Total spent (`₹` amount, two
       decimals), Transactions (count), Top category (name)
    3. **Recent transactions** — a table with Date, Description, Category, and
       Amount columns; category shown as a pill/badge; amounts right-aligned
       with `₹` and two decimals; an empty-state message when the list is empty
    4. **Spending by category** — one row per category with name, amount, and a
       horizontal bar whose width is the category's percentage of the total
       (set via an inline `style="width: {{ pct }}%"`)

    All values come from context variables. Use Jinja `format` (e.g.
    `"%.2f"|format(amount)`) for money; do not compute values in the template
    beyond formatting.

## Files to change
- `app.py` — update `profile()` to build and pass the hardcoded sample data
- `templates/profile.html` — full profile page markup

## Files to create
- `static/css/profile.css` — page-specific styles for the profile page, using a
  `pf-` class prefix (mirroring the `lp-` prefix used for landing styles)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (no queries are expected in this step; any added
  later must follow this rule)
- Passwords hashed with werkzeug (no password handling in this step)
- Use CSS variables — never hardcode hex values; use the existing tokens in
  `static/css/style.css` (`--ink*`, `--paper*`, `--accent*`, `--accent-2*`,
  `--border*`, `--radius-*`, `--font-*`). Do not copy the hardcoded hex
  colours used by `.mock-bar-3` / `.mock-bar-4` on the landing page
- All templates extend `base.html`
- Page-specific CSS lives in `static/css/profile.css`, loaded through the
  `head` block — do not add profile styles to `style.css`
- Prefix every new profile class with `pf-`
- The sample data lives in `profile()` (or a small helper in `app.py`), never in
  the template. Use this context shape so Step 5 can replace it without
  touching the template:
  - `user` — dict with `name`, `email`, `initials`, `member_since`
  - `stats` — dict with `total_spent` (float), `transaction_count` (int),
    `top_category` (str)
  - `transactions` — list of dicts with `date` (`YYYY-MM-DD`), `description`,
    `category`, `amount` (float), newest first, 5–8 rows
  - `categories` — list of dicts with `name`, `amount` (float), `pct` (int
    0–100), sorted by amount descending
- Take `user.name` from `session["user_name"]` so the logged-in user's real name
  appears; the email and other values may be sample values
- Sample categories must come from the `CATEGORIES` list in `database/db.py`
- Sample numbers must be internally consistent: `stats.total_spent` equals the
  sum of `categories[*].amount`, `pct` values add up to roughly 100, and
  `stats.top_category` is the first entry in `categories`
- Use the `₹` currency symbol, matching the footer's "Track every rupee" copy
- Layout must be responsive: stat cards and the two lower sections stack into a
  single column below ~768px; the transactions table must not overflow the
  viewport on mobile (allow horizontal scroll inside its card)
- No JavaScript is required for this step

## Definition of done
- [ ] Visiting `/profile` while logged out still redirects to `/login`
- [ ] Signing in as `demo@spendly.com` / `demo123` lands on `/profile` and shows
      the new design, not the "coming in Step 4" placeholder
- [ ] The user info card shows initials in a circular avatar, the logged-in
      user's name, an email, and a "Member since" date
- [ ] Three stat cards show total spent (₹, two decimals), transaction count,
      and top category
- [ ] The recent transactions table shows 5–8 rows with date, description,
      category badge, and right-aligned ₹ amount
- [ ] The category breakdown shows a bar per category whose widths match the
      percentages, sorted largest first
- [ ] Total spent equals the sum of the category amounts shown on the page
- [ ] Signing in as a newly registered user shows that user's name on the page
- [ ] `templates/profile.html` contains no hardcoded amounts, names, or dates
      (all come from context variables)
- [ ] `static/css/profile.css` is loaded only on the profile page, and its
      classes use the `pf-` prefix
- [ ] No hex colours were added to any CSS file; new styles use existing
      variables
- [ ] At ~375px browser width the page stacks into a single column with no
      horizontal page scroll
- [ ] Navbar still shows the user's name and "Sign out", and signing out works
- [ ] App starts without errors and all other pages still render
