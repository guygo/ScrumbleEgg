# Scrumbleeggs — User Guide

Scrumbleeggs is a lightweight Jira-like project management tool built with FastAPI, SQLite, Alpine.js, and Tailwind CSS.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Board View](#board-view)
3. [List View](#list-view)
4. [Ticket Detail Panel](#ticket-detail-panel)
5. [Filtering with JQL](#filtering-with-jql)
6. [Sprints](#sprints)
7. [Projects](#projects)
8. [Comments and @mentions](#comments-and-mentions)
9. [Due Dates](#due-dates)
10. [Template Tickets](#template-tickets)
11. [Relations and Linking](#relations-and-linking)
12. [Time Logging](#time-logging)
13. [Activity Log](#activity-log)
14. [Swimlanes](#swimlanes)
15. [WIP Limits](#wip-limits)
16. [Quick Actions on Cards](#quick-actions-on-cards)
17. [Bulk Actions](#bulk-actions)
18. [Export](#export)
19. [Admin Mode](#admin-mode)
20. [Custom Fields](#custom-fields)
21. [Keyboard Shortcuts](#keyboard-shortcuts)
22. [Performance Dashboard](#performance-dashboard)
23. [Plugin System](#plugin-system)
24. [Test Planning Plugin](#test-planning-plugin)

---

## Getting Started

### Running the server

```bash
# Standard start
python -m uvicorn scrumbleeggs.web.app:app --port 8000

# With auth disabled (local dev / testing only)
SBE_AUTH_DISABLED=1 python -m uvicorn scrumbleeggs.web.app:app --port 8000
```

Open `http://localhost:8000` in your browser.

### First login

On first run, an **admin** account is bootstrapped automatically. Check the server logs for the generated password, then log in at `/login`.

### Creating your first ticket

1. Click **New ticket** (top-right toolbar) or press `N`.
2. Fill in the title, type, priority, and any role-specific fields.
3. Click **Create**.

---

## Board View

The board is the default view. Tickets are grouped into four columns:

| Column | Meaning |
|---|---|
| Backlog | Not started |
| In Progress | Actively being worked on |
| Review | Awaiting code review / QA |
| Done | Complete |

### Moving tickets

**Drag and drop** a card to a different column to change its status. The card snaps into place and a PATCH request is sent automatically.

Alternatively, open a ticket's detail panel and change the **Status** dropdown.

### Collapsing columns

Click the **«** button in a column header to collapse it to a narrow strip. Click the strip (or the **»** icon) to expand it again. Collapse state is saved in `localStorage` and persists across page reloads.

---

## List View

Switch to the list view using the view toggle in the toolbar. List view shows all tickets in a sortable table and supports the same JQL filter bar as the board.

---

## Ticket Detail Panel

Click any ticket card to open the detail panel on the right side of the screen. Double-click (or press the `⋯` card action) to open the ticket in a full browser tab.

### Fields

| Field | Notes |
|---|---|
| Title | Always editable (click to edit inline) |
| Status | Dropdown — changes the board column |
| Priority | Critical / High / Medium / Low |
| Type | Story / Bug / Task |
| Assignee | Free-text name |
| Sprint | Free-text sprint name |
| Points | Story point estimate |
| Due date | ISO date — shows colored badge and overdue glow |
| Template | Toggle — marks this ticket as a spawn template |

### Description (markdown preview)

The description section has a **Preview / Edit** pill toggle in its header.

- **Preview** — renders the markdown (default).
- **Edit** — opens a monospace textarea. Click **Save** or **Cancel**.
- Clicking "No description — click to add one." also switches to edit mode.

All standard markdown is supported: headings, bold, italic, code blocks, lists, tables.

---

## Filtering with JQL

The filter bar at the top accepts a simple query language. Filters combine with AND logic.

### Syntax

```
key:value  key:"multi word value"  "title search"  bare word search
```

### Supported keys

| Key | Aliases | Example |
|---|---|---|
| `priority` | `pri` | `priority:high` |
| `assignee` | `a` | `assignee:alice` |
| `type` | — | `type:bug` |
| `status` | — | `status:in_progress` |
| `sprint` | `s` | `sprint:"Sprint 3"` |
| `project` | `proj` | `project:"Backend"` |
| `role` | `r` | `role:developer` |
| `pts` / `points` | — | `pts:>=5` `pts:<3` |
| `due` | — | `due:overdue` `due:this-week` `due:today` `due:2025-06-01` |

### Examples

```
priority:high assignee:alice
type:bug status:backlog "login"
due:overdue assignee:bob
pts:>=3 sprint:"Sprint 4"
```

### Saved filters

Click the bookmark icon in the toolbar to save the current filter. Saved filters appear in the dropdown and are persisted in `localStorage`.

---

## Sprints

Navigate to **Planning → Sprints** from the toolbar. You can:

- Create a sprint with a name, goal, start date, and end date.
- View sprint progress (completion %, story points done vs total).
- Close a sprint — moves all non-done tickets to Backlog.
- Delete a sprint.

Click **View tickets** on a sprint to filter the board to that sprint.

The **Roadmap** view shows a Gantt-style bar chart of sprint timelines with a "today" marker.

---

## Projects

The **Projects** view lets you group tickets under named projects with a color label.

- Click a project card to filter the board to that project.
- Each project shows total ticket count and a done/total progress bar.
- Projects have lifecycle states: Active, Paused, Completed.

---

## Comments and @mentions

Open a ticket's detail panel and scroll to the **Comments** section.

### Posting a comment

1. Optionally enter your name in the author field.
2. Type your comment. Markdown is supported.
3. Click **Post comment** or press Enter (in the button).

### @mentions

While typing in the comment box, type `@` followed by letters to trigger the mention autocomplete dropdown. Up to 8 matching usernames are shown.

- **Arrow Up / Down** — navigate the list.
- **Enter** or **Tab** — insert the selected username.
- **Escape** — dismiss the dropdown.

Inserted mentions appear as `@username` in the comment text. When the comment is saved and displayed, every `@username` token is rendered as a highlighted indigo chip.

---

## Due Dates

Set a due date on any ticket from the detail panel (in Admin mode: **Admin** toggle on).

### Visual indicators

| State | Card badge color | Card border |
|---|---|---|
| > 3 days away | Green | None |
| 1–3 days away | Amber | None |
| Overdue (past due, not Done) | Red | Red left glow |

### JQL filters for due dates

```
due:overdue       — past due, not done
due:today         — due today
due:this-week     — due within the next 7 days
due:2025-06-15    — exact date match
```

---

## Template Tickets

Any ticket can be marked as a **template** — a reusable starting point for recurring work (standups, weekly reports, release checklists, etc.).

### Marking a ticket as a template

1. Open the ticket detail panel.
2. Enable **Admin mode** (cog icon in the toolbar).
3. Toggle the **Template** switch in the property rows.

The ticket will show a yellow `tmpl` badge on the board card.

### Spawning a copy from a template

1. Open a template ticket.
2. Optionally type a title in the **Spawn copy** input field.
3. Click **Spawn**.

A new ticket is created with all fields copied (description, type, priority, checklists, custom fields, etc.) and:

- Status is reset to **Backlog**.
- Assignee is cleared.
- `is_template` is set to `false`.
- Title defaults to `[Copy] <original title>` if left blank.

The spawned ticket appears immediately on the board.

---

## Relations and Linking

Tickets can be linked to each other with typed relations.

### From the detail panel

1. Open a ticket.
2. Scroll to **Relations**.
3. Click **Add relation**, enter the target ticket key, and choose a relation type.

### From the board by dragging

Hold **Shift** and drag a card onto another card. When the target card shows a purple ring, release to drop. A dialog appears to choose the relation type:

- **relates to** — general connection
- **blocks** — this ticket must be resolved before the target
- **blocked by** — this ticket cannot proceed until the target is resolved
- **duplicate of** — duplicate ticket

Click **Create link** to save. The relation appears in both tickets' detail panels.

---

## Time Logging

Open a ticket and scroll to **Time logged**.

- Enter minutes and an optional note, then click **Log time**.
- Total logged time is shown.
- Individual entries can be deleted.

Time logging is also recorded in the Activity Log.

---

## Activity Log

Every ticket maintains an immutable audit trail visible in its detail panel under **Activity**.

Events logged automatically:

| Event | Trigger |
|---|---|
| `created` | Ticket created |
| `status_changed` | Status moved (drag or dropdown) |
| `field_changed` | Any metadata field updated (title, priority, assignee, etc.) |
| `comment_added` | New comment posted |
| `subtask_added` | Subtask created |
| `time_logged` | Time entry added |

Each entry shows: actor name, relative timestamp, and a description with old/new values where applicable.

---

## Swimlanes

Click the **Lanes** button in the toolbar to enable swimlanes. Cycles through:

- **None** — standard columns
- **Assignee** — one horizontal lane per assignee
- **Priority** — one lane per priority level

Swimlane state is not persisted — it resets on reload.

---

## WIP Limits

Click the **WIP** button in the toolbar to set work-in-progress limits per column.

| Indicator | Meaning |
|---|---|
| Green count | Under limit |
| Amber count | At 80 % of limit |
| Red pulsing count (bold) | Over limit — column gets a subtle red background tint |

Limits are saved in `localStorage`.

---

## Quick Actions on Cards

Hover over any board card to reveal the action bar (top-right corner of the card):

| Button | Action |
|---|---|
| `→` | Move ticket to the next status |
| Person icon / Avatar | Open the **quick assign** dropdown — pick a user or unassign. Shows a person silhouette when unassigned, avatar initials when assigned. |
| `⋯` | Open the full detail panel |

---

## Bulk Actions

Click **Bulk** in the toolbar to enter bulk selection mode. Click cards to select them (highlighted with an accent ring). Then use the bulk action bar at the bottom to:

- Move all selected tickets to a status.
- Delete all selected tickets.

Click **Bulk** again or press Escape to exit.

---

## Export

Click the **Export** button in the toolbar to download the current filtered ticket set as:

- **CSV** — comma-separated, includes key, title, status, priority, type, assignee, sprint, project, story points, created date.
- **JSON** — full ticket objects as a JSON array.

Exports respect the current JQL filter.

---

## Admin Mode

Toggle **Admin mode** with the cog/shield icon in the toolbar (or press `A` when the keyboard shortcut panel is open). Admin mode:

- Reveals editable dropdowns for Priority and Status in the detail panel.
- Shows the Assignee, Sprint, and Points input fields.
- Reveals the Due date picker.
- Shows the Template toggle and Spawn input.
- Enables custom field editing on tickets.
- Unlocks the admin panel (User management, Custom fields).

Admin mode preference is saved in `localStorage`.

---

## Custom Fields

In Admin mode, navigate to **Admin > Custom Fields** to define extra fields that appear on every ticket.

### Field types

| Type | Description |
|---|---|
| Text | Single-line text input |
| Number | Numeric input |
| Select | Dropdown — define options as a comma-separated list |
| Checkbox | Boolean toggle |

Custom field values are stored per-ticket in a JSON blob and are exportable.

---

## Keyboard Shortcuts

Press `?` or click the keyboard icon in the toolbar to open the shortcuts panel.

| Shortcut | Action |
|---|---|
| `N` | New ticket |
| `B` | Board view |
| `L` | List view |
| `/` | Focus filter bar |
| `Escape` | Close panel / modal |
| `?` | Toggle shortcuts panel |

---

## Performance Dashboard

Navigate to `/perf` to open the live performance dashboard. It shows:

- Request rate and latency timeseries.
- HTTP status code breakdown.
- Database diagnostics (PRAGMA values, table row counts, WAL mode status, DB file size).
- SQLAlchemy connection pool status.

The dashboard polls automatically every few seconds.

---

## Plugin System

Scrumbleeggs supports a lightweight plugin system. Plugins are Python sub-packages inside `scrumbleeggs/plugins/` that are auto-discovered at startup — no changes to the core app required.

### Plugin structure

```
scrumbleeggs/plugins/
└── my_plugin/
    ├── manifest.json   ← id, name, version, nav label + icon
    ├── __init__.py     ← exports router, configure(db), models list
    ├── routes.py       ← FastAPI APIRouter
    ├── models.py       ← SQLAlchemy ORM models
    └── template.html   ← Alpine.js UI fragment (rendered inside the SPA)
```

### What a plugin gets

- **Nav button** — automatically added to the toolbar with the icon and label from `manifest.json`. Highlighted when the plugin view is active.
- **API routes** — mounted at `/api/plugins/<plugin_id>/...`, protected by the same session auth as the rest of the app.
- **DB tables** — created automatically on startup (`CREATE TABLE IF NOT EXISTS`).
- **UI view** — the HTML fragment in `template.html` is rendered server-side (Jinja2) inside a `<main x-show="view==='plugin_<id>'">` section of the SPA.

### manifest.json format

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "What this plugin does.",
  "nav": {
    "label": "My Plugin",
    "icon_svg": "<svg ...></svg>"
  }
}
```

### __init__.py contract

```python
from .routes import configure, router
from .models import MyModel

models = [MyModel]          # tables to create
__all__ = ["router", "configure", "models"]
```

`configure(db)` is called by the loader to inject the `Database` instance before any routes are served.

---

## Test Planning Plugin

The built-in **Test Planning** plugin (`plugins/test_plan`) adds a full test plan management view to Scrumbleeggs.

Navigate to **Test Plans** in the toolbar.

### Test plans

A test plan groups related test cases, optionally linked to a sprint.

| Field | Notes |
|---|---|
| Name | Required |
| Sprint | Optional — links the plan to a sprint name |
| Status | Draft / Active / Closed |

### Test cases

Each plan contains test cases with:

| Field | Notes |
|---|---|
| Title | What is being tested |
| Steps | Step-by-step instructions (plain text, newlines supported) |
| Expected result | What a passing run looks like |
| Linked ticket | Optional `SBE-XXX` key — links the case to a board ticket |
| Result | Pending / Pass ✓ / Fail ✗ / Blocked ⚠ |

### Progress tracking

The plan header shows live counts (pass / fail / blocked / pending) and a green progress bar representing `% passed`.

### Filtering cases

Use the filter bar above the case table to view only cases with a specific result: All, Pending, Pass, Fail, or Blocked.

### API

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/api/plugins/test_plan/plans` | List / create test plans |
| `GET/PATCH/DELETE` | `/api/plugins/test_plan/plans/{id}` | Get / update / delete a plan |
| `GET/POST` | `/api/plugins/test_plan/plans/{id}/cases` | List / add test cases |
| `PATCH/DELETE` | `/api/plugins/test_plan/plans/{id}/cases/{case_id}` | Update / delete a case |
| `GET` | `/api/plugins/test_plan/plans/{id}/stats` | Pass/fail/blocked counts |

---

## API Reference (brief)

All API routes are under `/api/`. The server returns JSON. Auth is enforced via session cookie (`sbe_session`).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/board` | Board data grouped by status |
| `GET/POST` | `/api/tickets` | List / create tickets |
| `GET/PATCH/DELETE` | `/api/tickets/{key}` | Get / update / delete a ticket |
| `POST` | `/api/tickets/{key}/move` | Change ticket status |
| `POST` | `/api/tickets/{key}/spawn` | Spawn a copy from a template ticket |
| `GET/POST` | `/api/tickets/{key}/comments` | List / add comments |
| `GET/POST` | `/api/tickets/{key}/relations` | List / add relations |
| `GET/POST` | `/api/tickets/{key}/time` | List / log time entries |
| `GET` | `/api/tickets/{key}/activity` | Activity log (newest first) |
| `GET/POST` | `/api/tickets/{key}/subtasks` | List / create subtasks |
| `GET/POST/PATCH/DELETE` | `/api/sprints` | Sprint management |
| `GET` | `/api/sprints/{id}/stats` | Sprint progress stats |
| `GET` | `/api/sprints/{id}/burndown` | Burndown chart data |
| `GET/POST/PATCH/DELETE` | `/api/projects` | Project management |
| `GET` | `/api/search` | Full-text ticket search |
| `GET` | `/api/stats` | Ticket count summary |
| `GET` | `/api/workload` | Per-assignee workload breakdown |
| `GET` | `/api/users/usernames` | Active usernames (for @mention autocomplete) |
| `GET/POST/PATCH/DELETE` | `/api/admin/fields` | Custom field definitions (admin only) |
| `GET` | `/api/export/csv` | CSV export |
| `GET` | `/api/export/json` | JSON export |

---

## Data Storage

Scrumbleeggs uses SQLite by default. The database file is created at the path configured in your environment (default: `scrumbleeggs.db` in the working directory).

To switch to PostgreSQL or another database, set the `DATABASE_URL` environment variable to any SQLAlchemy-compatible connection string. The rest of the application is backend-agnostic.

SQLite is configured with WAL mode, 64 MB page cache, and 256 MB memory-mapped I/O for good read performance under concurrent load.
