# Spec: Edit Expense

## Overview
Step 8 lets a logged-in user correct an expense they have already recorded.
The `/expenses/<int:id>/edit` route already exists as a placeholder string
("coming in Step 8"); this step upgrades it to a full GET + POST handler. GET
loads the expense — only if it belongs to the current user — and renders a form
pre-filled with its current values. POST validates the submitted values with the
same rules as Step 7 (reusing `_validate_expense_form`), updates the row, and
redirects back to the profile page. Each row in the profile page's transaction
table gains an "Edit" link so users can reach the form.

## Depends on
- Step 1: Database setup (`expenses` table with `id`, `user_id`, `amount`, `category`, `date`, `description`)
- Step 3: Login / Logout (`session["user_id"]` is set and checked)
- Step 5: Backend routes for profile page (`get_recent_transactions` feeds the transaction table)
- Step 7: Add expense (`_validate_expense_form`, `_parse_amount`, `MAX_AMOUNT`, `MAX_DESCRIPTION_LENGTH`, and the expense form markup/styling)

## Routes
- `GET /expenses/<int:id>/edit` — render the edit form pre-filled with the expense's current values — logged-in only
- `POST /expenses/<int:id>/edit` — validate and save changes to the expense — logged-in only

Both replace the existing placeholder `edit_expense(id)` in `app.py`; do not add a
parallel route.

## Database changes
No database changes. The `expenses` table already has every column needed.
Updates touch only `amount`, `category`, `date`, `description`; `user_id`,
`id`, and `created_at` are never modified.

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`; mirrors the layout and classes of `add_expense.html` (`auth-section`, `auth-card`, `form-group`, `form-input`, `btn-submit`)
  - Title "Edit expense"; subtitle e.g. "Update the details of this expense"
  - `<form method="POST" action="{{ url_for('edit_expense', id=expense_id) }}">`
  - Same four fields as the add form (`amount`, `category`, `date`, `description`) with the same constraints (`step="0.01"`, `min="0.01"`, `max`, `maxlength`, 7-option category `<select>`)
  - Fields pre-filled from the stored expense on GET, and from the submitted values on a failed POST
  - Submit button "Save Changes" and a "Cancel" link back to `url_for('profile')`
  - Shows `error` in an `auth-error` block when validation fails
- **Modify:** `templates/profile.html`
  - Add a fifth (actions) column to the transaction table with an "Edit" link per row pointing to `url_for('edit_expense', id=tx.id)`
  - Update the empty-state row's `colspan` from 4 to 5
- **Modify (if needed):** `static/css/profile.css` — styling for the actions column / edit link using `pf-` prefixed classes and CSS variables only

## Files to change
- `app.py` — replace the `edit_expense(id)` placeholder with a GET + POST handler:
  - Redirect to `/login` if not authenticated
  - Load the expense with `get_expense_by_id(id, session["user_id"])`; `abort(404)` if it is `None` (missing **or** owned by another user — do not reveal which)
  - GET: render `edit_expense.html` with the stored values (amount formatted to 2 dp)
  - POST: strip form fields, validate with `_validate_expense_form`; on error re-render with submitted values; on success call `update_expense(...)` and redirect to `url_for("profile")`
  - Import `abort` from flask and the two new query helpers
- `database/queries.py`
  - Add `get_expense_by_id(expense_id, user_id)` — returns a dict (`id`, `amount`, `category`, `date`, `description` with `None` → `""`) or `None`; query filters on **both** `id = ?` and `user_id = ?`
  - Add `update_expense(expense_id, user_id, amount, category, date, description)` — `UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? WHERE id = ? AND user_id = ?`; commits; returns `cursor.rowcount`
  - Update `get_recent_transactions` to also select and return `id` for each row
- `templates/profile.html` — add the Edit link column (see Templates)
- `static/css/profile.css` — only if the new column needs styling

## Files to create
- `templates/edit_expense.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` via `get_db()` only
- Parameterised queries only — never string-format values into SQL
- Passwords hashed with werkzeug (no password handling changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles
- Currency always displays as ₹ — never £ or $
- Ownership is enforced in SQL: both the SELECT and the UPDATE filter on `user_id = ?` using `session["user_id"]` — never trust a user id from the form or URL
- A non-existent expense and another user's expense both return 404 — identical responses
- Reuse `_validate_expense_form` from Step 7 — do not duplicate validation logic
- Blank description is stored as `NULL` (same as add)
- After a successful update, redirect to `url_for("profile")` — do not re-render the form
- `<int:id>` converter stays — non-integer ids 404 via Flask routing

## Definition of done
- [ ] Visiting `/expenses/<id>/edit` while logged out redirects to `/login` (both GET and POST)
- [ ] Each row in the profile page's transaction table has an "Edit" link that opens `/expenses/<id>/edit` for that expense
- [ ] The edit form opens pre-filled with the expense's current amount, category, date, and description
- [ ] Changing values and clicking "Save Changes" redirects to `/profile` and the transaction list, summary stats, and category breakdown reflect the new values
- [ ] Clicking "Cancel" returns to `/profile` without changing the expense
- [ ] Submitting a missing, zero, negative, or non-numeric amount re-renders the form with an error and the submitted values retained; the stored expense is unchanged
- [ ] Submitting an invalid category or invalid date re-renders the form with an error; the stored expense is unchanged
- [ ] Clearing the description and saving stores it as empty (no error), and the row shows no description
- [ ] Visiting `/expenses/99999/edit` (non-existent id) returns 404
- [ ] Logged in as user A, visiting or POSTing to the edit URL of user B's expense returns 404 and user B's expense is unchanged
- [ ] The empty-state row on the profile page still spans the full table width
