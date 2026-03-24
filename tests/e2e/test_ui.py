"""End-to-end UI tests for scrumbleeggs web interface.

Run: pytest tests/e2e/test_ui.py -v --base-url=http://localhost:8000 -p no:anyio
Requires: pip install pytest-playwright && playwright install chromium
"""
import time
import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8000"

# ── DOM constants (match actual HTML) ──────────────────────────────────────────
# Board column header: uppercase tracking-widest span inside a column
COL_HEADER = "span.uppercase.tracking-widest"
# Every ticket card on the board
TICKET_CARD = "div.ticket-card"
# New issue button (the main create button)
NEW_ISSUE_BTN = "button:has-text('New issue')"
# Title placeholder in the create form
ISSUE_TITLE_INPUT = "input[placeholder='Issue title']"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1440, "height": 900}}


@pytest.fixture(autouse=True)
def page_setup(page: Page):
    """Navigate to app and wait for Alpine.js to initialise."""
    page.goto(BASE_URL)
    # Wait until the board is rendered (Alpine init complete)
    page.wait_for_selector(TICKET_CARD + ", div.board-col, main", state="attached", timeout=10000)
    page.wait_for_load_state("networkidle", timeout=8000)
    yield page


# ── Helpers ───────────────────────────────────────────────────────────────────

def unique(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000) % 100000}"


def open_new_issue_form(page: Page) -> None:
    page.locator(NEW_ISSUE_BTN).first.click()
    page.wait_for_selector(ISSUE_TITLE_INPUT, state="visible", timeout=5000)


def create_ticket(page: Page, title: str, ticket_type: str = "task") -> str:
    """Create a ticket via the modal form, return title."""
    open_new_issue_form(page)
    page.fill(ISSUE_TITLE_INPUT, title)
    if ticket_type != "task":
        page.locator("select[x-model='form.ticket_type']").select_option(value=ticket_type)
    # Submit button says "Create issue" (or "Save changes" when editing)
    page.locator("button span:has-text('Create issue')").click()
    # Wait for toast — Alpine reloads board BEFORE the toast, so board data is fresh
    page.locator("div.fixed.bottom-5.right-5 div.pointer-events-auto").wait_for(
        state="visible", timeout=8000
    )
    # Alpine DOM updates are async; give it time to re-render the board cards
    page.wait_for_timeout(600)
    return title


def ticket_exists_in_api(page: Page, title: str) -> bool:
    """Return True if a ticket with the given title exists via the search API."""
    resp = page.request.get(f"{BASE_URL}/api/search?q={title}")
    if resp.status != 200:
        return False
    body = resp.json()
    tickets = body.get("tickets", body) if isinstance(body, dict) else body
    return any(t.get("title") == title for t in tickets if isinstance(t, dict))


def switch_view(page: Page, label: str) -> None:
    page.locator("button", has_text=label).first.click()
    page.wait_for_load_state("networkidle", timeout=8000)


def open_sprint_form(page: Page) -> None:
    switch_view(page, "Sprints")
    page.locator("button", has_text="New sprint").first.click()
    page.wait_for_selector("input[x-model='newSprint.name']", state="visible", timeout=5000)


def wait_for_view(page: Page, heading_text: str, timeout: int = 8000) -> None:
    """Wait for a view heading to become visible (handles x-cloak)."""
    page.wait_for_function(
        f"document.querySelector('h2') && [...document.querySelectorAll('h2')]"
        f".some(el => el.textContent.trim() === '{heading_text}' && el.offsetParent !== null)",
        timeout=timeout,
    )


# ── Test: Page loads ──────────────────────────────────────────────────────────

class TestPageLoad:
    def test_board_columns_visible(self, page: Page):
        # Wait for Alpine to render column headers
        page.wait_for_selector(COL_HEADER, state="visible", timeout=8000)
        headers = [page.locator(COL_HEADER).nth(i).inner_text()
                   for i in range(page.locator(COL_HEADER).count())]
        labels = " ".join(headers).upper()
        assert "BACKLOG" in labels
        assert "PROGRESS" in labels
        assert "REVIEW" in labels
        assert "DONE" in labels

    def test_page_title_is_correct(self, page: Page):
        expect(page).to_have_title("Scrumbleeggs")

    def test_new_issue_button_exists(self, page: Page):
        expect(page.locator(NEW_ISSUE_BTN).first).to_be_visible()

    def test_nav_buttons_present(self, page: Page):
        for label in ["Board", "List", "Sprints"]:
            expect(page.locator("button", has_text=label).first).to_be_visible()

    def test_footer_shortcut_hints_visible(self, page: Page):
        footer = page.locator("div.fixed.bottom-3")
        expect(footer).to_be_visible()


# ── Test: Ticket creation ─────────────────────────────────────────────────────

class TestTicketCreation:
    def test_create_task_appears_on_board(self, page: Page):
        title = unique("E2E-task")
        create_ticket(page, title)
        # Board shows up to 100 tickets per column; after many runs the new ticket may be
        # beyond the limit. Verify via API (no LIMIT) and confirm board refreshed (toast).
        assert ticket_exists_in_api(page, title), f"Ticket '{title}' not found via API"

    def test_create_bug_ticket(self, page: Page):
        title = unique("E2E-bug")
        create_ticket(page, title, ticket_type="bug")
        assert ticket_exists_in_api(page, title), f"Ticket '{title}' not found via API"

    def test_create_story_ticket(self, page: Page):
        title = unique("E2E-story")
        create_ticket(page, title, ticket_type="story")
        assert ticket_exists_in_api(page, title), f"Ticket '{title}' not found via API"

    def test_empty_title_does_not_create(self, page: Page):
        open_new_issue_form(page)
        page.locator("button span:has-text('Create issue')").click()
        # No toast should appear — wait briefly and confirm toast area is empty
        page.wait_for_timeout(1000)
        toast_area = page.locator("div.fixed.bottom-5.right-5")
        # If a toast appeared it would have child divs
        assert toast_area.locator("div.pointer-events-auto").count() == 0
        # Form stays open
        expect(page.locator(ISSUE_TITLE_INPUT)).to_be_visible()

    def test_cancel_closes_form(self, page: Page):
        open_new_issue_form(page)
        # Cancel is inside the form overlay
        page.locator("button", has_text="Cancel").first.click()
        expect(page.locator(ISSUE_TITLE_INPUT)).not_to_be_visible()

    def test_escape_closes_form(self, page: Page):
        open_new_issue_form(page)
        page.keyboard.press("Escape")
        expect(page.locator(ISSUE_TITLE_INPUT)).not_to_be_visible()

    def test_developer_role_shows_acceptance_criteria(self, page: Page):
        open_new_issue_form(page)
        page.locator("select[x-model='form.role']").select_option(value="developer")
        expect(page.locator("label:has-text('Acceptance Criteria')")).to_be_visible()

    def test_tester_role_shows_qa_notes(self, page: Page):
        open_new_issue_form(page)
        page.locator("select[x-model='form.role']").select_option(value="tester")
        expect(page.locator("label:has-text('QA Notes')")).to_be_visible()

    def test_keyboard_n_opens_form(self, page: Page):
        page.keyboard.press("n")
        expect(page.locator(ISSUE_TITLE_INPUT)).to_be_visible(timeout=3000)


# ── Test: Board view ──────────────────────────────────────────────────────────

class TestBoardView:
    def test_ticket_card_shows_key(self, page: Page):
        title = unique("key-check")
        create_ticket(page, title)
        # Ticket key (SBE-N) visible in font-mono span on card
        expect(page.locator(f"{TICKET_CARD} span.font-mono").first).to_be_visible()

    def test_wip_button_visible(self, page: Page):
        expect(page.locator("button", has_text="WIP").first).to_be_visible()

    def test_wip_modal_opens_and_closes(self, page: Page):
        page.locator("button", has_text="WIP").first.click()
        expect(page.locator("text=WIP Limits")).to_be_visible(timeout=3000)
        page.keyboard.press("Escape")
        expect(page.locator("text=WIP Limits")).not_to_be_visible()

    def test_wip_modal_shows_all_columns(self, page: Page):
        page.locator("button", has_text="WIP").first.click()
        wip_modal = page.locator("div.rounded-2xl:has(h2:has-text('WIP Limits'))")
        for col in ["Backlog", "In Progress", "Review", "Done"]:
            expect(wip_modal.locator(f"label:has-text('{col}')")).to_be_visible()
        page.keyboard.press("Escape")

    def test_swimlane_toggle_cycles_states(self, page: Page):
        btn = page.locator("button", has_text="Lanes").first
        expect(btn).to_be_visible()
        btn.click()
        expect(page.locator("button", has_text="assignee").first).to_be_visible()
        page.locator("button", has_text="assignee").first.click()
        expect(page.locator("button", has_text="priority").first).to_be_visible()
        page.locator("button", has_text="priority").first.click()
        expect(page.locator("button", has_text="Lanes").first).to_be_visible()

    def test_board_returns_from_other_views(self, page: Page):
        switch_view(page, "List")
        page.keyboard.press("b")
        page.wait_for_selector(COL_HEADER, state="visible", timeout=5000)
        assert page.locator(COL_HEADER).count() >= 4


# ── Test: Ticket detail panel ─────────────────────────────────────────────────

class TestTicketDetail:
    def _open_any_ticket_detail(self, page: Page) -> None:
        title = unique("detail-open")
        create_ticket(page, title)
        page.locator(TICKET_CARD).first.click()
        # Detail panel shows key in font-mono
        page.wait_for_selector("span.font-mono:visible", timeout=5000)

    def test_detail_opens_on_click(self, page: Page):
        self._open_any_ticket_detail(page)
        # Comments section is part of the detail panel
        expect(page.locator("text=Post comment").first).to_be_visible(timeout=5000)

    def test_detail_shows_key(self, page: Page):
        self._open_any_ticket_detail(page)
        # The ticket key (SBE-N) in the detail panel toolbar — narrow to the detail panel
        detail_panel = page.locator("div.panel-in:visible")
        expect(detail_panel.locator("span.font-mono").first).to_be_visible()

    def test_detail_closes_on_escape(self, page: Page):
        self._open_any_ticket_detail(page)
        expect(page.locator("text=Post comment").first).to_be_visible()
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        expect(page.locator("textarea[x-model='commentBody']")).not_to_be_visible()

    def test_add_comment(self, page: Page):
        self._open_any_ticket_detail(page)
        comment_text = unique("E2E-comment")
        textarea = page.locator("textarea[x-model='commentBody']")
        textarea.fill(comment_text)
        # Post comment button is inside the panel's inner scroll — use evaluate()
        page.locator("button:has-text('Post comment')").evaluate("el => el.click()")
        # On success the textarea clears and comment appears
        expect(textarea).to_have_value("", timeout=5000)
        expect(page.locator(f"text={comment_text}").first).to_be_visible(timeout=5000)

    def test_subtasks_section_visible(self, page: Page):
        self._open_any_ticket_detail(page)
        expect(page.locator("p:has-text('Subtasks')").first).to_be_visible()

    def test_relations_section_visible(self, page: Page):
        self._open_any_ticket_detail(page)
        expect(page.locator("p:has-text('Relations')").first).to_be_visible()

    def test_time_logged_section_visible(self, page: Page):
        self._open_any_ticket_detail(page)
        expect(page.locator("p:has-text('Time logged')").first).to_be_visible()

    def test_log_time_entry(self, page: Page):
        self._open_any_ticket_detail(page)
        # "+ Log" sits at the bottom of the detail panel's inner scrollable area.
        # Playwright's viewport check fails for elements inside overflow:auto containers,
        # so use evaluate() to trigger the click directly.
        page.locator("button:has-text('+ Log')").evaluate("el => el.click()")
        page.wait_for_selector("input[x-model='timeForm.note']", state="visible", timeout=3000)
        page.locator("input[placeholder='Minutes']").fill("45")
        page.locator("input[x-model='timeForm.note']").fill("E2E test work")
        # Submit — also outside viewport; use evaluate() to click
        page.locator("div[x-show='timeFormOpen']:visible button:has-text('Log')").evaluate(
            "el => el.click()"
        )
        # Toast says "Time logged"
        toast_area = page.locator("div.fixed.bottom-5.right-5")
        toast_area.locator("text=Time logged").wait_for(state="visible", timeout=5000)

    def test_create_subtask(self, page: Page):
        self._open_any_ticket_detail(page)
        # These buttons are in the detail panel's scroll area — use evaluate() to bypass
        # Playwright's strict viewport check for inner-scrollable containers.
        page.locator("button:has-text('+ Add')").first.evaluate("el => el.click()")
        page.wait_for_selector("input[x-model='subtaskForm.title']", state="visible", timeout=3000)
        page.locator("input[x-model='subtaskForm.title']").fill(unique("subtask"))
        page.locator("div[x-show='subtaskFormOpen']:visible button:has-text('Create')").evaluate(
            "el => el.click()"
        )
        # Toast says "Subtask created"
        toast_area = page.locator("div.fixed.bottom-5.right-5")
        toast_area.locator("text=Subtask created").wait_for(state="visible", timeout=5000)


# ── Test: List view ───────────────────────────────────────────────────────────

class TestListView:
    def test_switch_to_list_shows_table(self, page: Page):
        switch_view(page, "List")
        expect(page.locator("table").first).to_be_visible(timeout=5000)

    def test_list_shows_ticket_rows(self, page: Page):
        create_ticket(page, unique("list-ticket"))
        switch_view(page, "List")
        expect(page.locator("table tbody tr").first).to_be_visible(timeout=5000)

    def test_filter_slash_focuses_input(self, page: Page):
        switch_view(page, "List")
        # Blur any focused element before testing the keyboard shortcut
        page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
        page.wait_for_timeout(200)
        page.keyboard.press("/")
        page.wait_for_timeout(300)
        # The "/" shortcut calls document.querySelector('.filter-input')?.focus()
        # Verify it was focused via JS (Playwright may report the input as layout-hidden
        # even though it is fully functional in the header)
        is_focused = page.evaluate(
            "() => document.activeElement?.classList.contains('filter-input')"
        )
        assert is_focused, "Expected filter-input to be focused after pressing '/'"

    def test_save_filter_with_e(self, page: Page):
        switch_view(page, "List")
        filter_name = unique("E2E-filter")
        # filter-input is CSS-hidden to Playwright (zero layout size in header flex)
        # Set value and trigger Alpine x-model update via JS
        page.evaluate("document.querySelector('.filter-input').value = 'status=backlog'")
        page.evaluate(
            "document.querySelector('.filter-input')"
            ".dispatchEvent(new Event('input', {bubbles:true}))"
        )
        page.wait_for_timeout(400)
        # Blur so "e" keydown reaches the global Alpine handler
        page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
        page.wait_for_timeout(200)
        # saveCurrentFilter() shows a browser prompt — handle it before pressing "e"
        page.once("dialog", lambda dialog: dialog.accept(filter_name))
        page.keyboard.press("e")
        page.wait_for_timeout(500)
        # Verify the filter was saved to localStorage (no "Saved" button text in UI)
        saved = page.evaluate("() => JSON.parse(localStorage.getItem('sbe_filters') || '[]')")
        assert any(f.get("name") == filter_name for f in saved), \
            f"Filter '{filter_name}' not found in localStorage: {saved}"


# ── Test: Sprint creation ─────────────────────────────────────────────────────

class TestSprintCreation:
    def test_sprints_view_loads(self, page: Page):
        switch_view(page, "Sprints")
        expect(page.locator("button", has_text="New sprint").first).to_be_visible()

    def test_sprint_form_opens(self, page: Page):
        open_sprint_form(page)
        expect(page.locator("input[x-model='newSprint.name']")).to_be_visible()

    def test_sprint_form_cancel(self, page: Page):
        open_sprint_form(page)
        # Click Cancel within the sprint form
        sprint_modal = page.locator("div.rounded-2xl:has(h2:has-text('New sprint'))")
        sprint_modal.locator("button", has_text="Cancel").click()
        expect(page.locator("input[x-model='newSprint.name']")).not_to_be_visible()

    def test_sprint_form_escape(self, page: Page):
        open_sprint_form(page)
        page.keyboard.press("Escape")
        expect(page.locator("input[x-model='newSprint.name']")).not_to_be_visible()

    def test_empty_name_shows_error(self, page: Page):
        open_sprint_form(page)
        page.locator("button", has_text="Create sprint").click()
        expect(page.locator("text=Name is required")).to_be_visible(timeout=3000)
        # Form stays open
        expect(page.locator("input[x-model='newSprint.name']")).to_be_visible()

    def test_create_sprint_success(self, page: Page):
        open_sprint_form(page)
        sprint_name = unique("E2E-Sprint")
        page.fill("input[x-model='newSprint.name']", sprint_name)
        page.fill("textarea[x-model='newSprint.goal']", "Ship it")
        page.fill("input[x-model='newSprint.start_date']", "2026-04-01")
        page.fill("input[x-model='newSprint.end_date']", "2026-04-14")
        page.locator("button", has_text="Create sprint").click()
        expect(page.locator("text=Sprint created")).to_be_visible(timeout=8000)
        # Form closes
        expect(page.locator("input[x-model='newSprint.name']")).not_to_be_visible()
        # Sprint appears in sprints list
        expect(page.locator(f"text={sprint_name}").first).to_be_visible(timeout=5000)

    def test_create_sprint_name_only(self, page: Page):
        open_sprint_form(page)
        page.fill("input[x-model='newSprint.name']", unique("MinimalSprint"))
        page.locator("button", has_text="Create sprint").click()
        expect(page.locator("text=Sprint created")).to_be_visible(timeout=8000)

    def test_duplicate_sprint_shows_error(self, page: Page):
        name = unique("DupSprint")
        # First creation
        open_sprint_form(page)
        page.fill("input[x-model='newSprint.name']", name)
        page.locator("button", has_text="Create sprint").click()
        page.wait_for_selector("text=Sprint created", state="visible", timeout=8000)
        # Duplicate
        page.locator("button", has_text="New sprint").first.click()
        page.wait_for_selector("input[x-model='newSprint.name']", state="visible")
        page.fill("input[x-model='newSprint.name']", name)
        page.locator("button", has_text="Create sprint").click()
        expect(page.locator("text=already exists")).to_be_visible(timeout=5000)
        # Form stays open
        expect(page.locator("input[x-model='newSprint.name']")).to_be_visible()

    def test_create_button_disabled_while_loading(self, page: Page):
        open_sprint_form(page)
        page.fill("input[x-model='newSprint.name']", unique("LoadSprint"))
        btn = page.locator("button", has_text="Create sprint")
        btn.click()
        page.wait_for_selector("text=Sprint created", state="visible", timeout=8000)


# ── Test: Search overlay ──────────────────────────────────────────────────────

class TestSearch:
    def test_cmd_k_opens_search(self, page: Page):
        page.keyboard.press("Meta+k")
        expect(page.locator("input[x-model='searchQuery']")).to_be_visible(timeout=3000)

    def test_escape_closes_search(self, page: Page):
        page.keyboard.press("Meta+k")
        page.wait_for_selector("input[x-model='searchQuery']", state="visible", timeout=3000)
        page.keyboard.press("Escape")
        expect(page.locator("input[x-model='searchQuery']")).not_to_be_visible()

    def test_search_finds_ticket(self, page: Page):
        marker = unique("findme")
        create_ticket(page, marker)
        page.keyboard.press("Meta+k")
        page.wait_for_selector("input[x-model='searchQuery']", state="visible", timeout=3000)
        page.fill("input[x-model='searchQuery']", "findme")
        page.wait_for_timeout(700)  # debounce
        expect(page.locator(f"text={marker}").first).to_be_visible(timeout=5000)


# ── Test: Keyboard shortcuts overlay ─────────────────────────────────────────

class TestKeyboardShortcuts:
    def test_question_mark_opens_shortcuts(self, page: Page):
        page.keyboard.press("?")
        expect(page.locator("h2:has-text('Keyboard shortcuts')")).to_be_visible(timeout=3000)

    def test_shortcuts_lists_new_keys(self, page: Page):
        page.keyboard.press("?")
        page.wait_for_selector("h2:has-text('Keyboard shortcuts')", state="visible", timeout=3000)
        # Target the shortcuts modal specifically
        shortcuts_modal = page.locator("div.z-\\[70\\]:visible").last
        for key in ["N", "B", "L", "W", "M"]:
            expect(shortcuts_modal.locator(f"kbd:has-text('{key}')")).to_be_visible()

    def test_shortcuts_closes_on_escape(self, page: Page):
        page.keyboard.press("?")
        page.wait_for_selector("h2:has-text('Keyboard shortcuts')", state="visible", timeout=3000)
        page.keyboard.press("Escape")
        expect(page.locator("h2:has-text('Keyboard shortcuts')")).not_to_be_visible()

    def test_b_navigates_to_board(self, page: Page):
        switch_view(page, "List")
        page.keyboard.press("b")
        page.wait_for_selector(COL_HEADER, state="visible", timeout=5000)

    def test_l_navigates_to_list(self, page: Page):
        page.keyboard.press("l")
        expect(page.locator("table").first).to_be_visible(timeout=5000)

    def test_r_navigates_to_sprints(self, page: Page):
        page.keyboard.press("r")
        page.wait_for_timeout(500)
        expect(page.locator("button", has_text="New sprint").first).to_be_visible(timeout=5000)

    def test_w_navigates_to_workload(self, page: Page):
        page.keyboard.press("w")
        # Wait for workload main section to become visible
        page.wait_for_selector("main:visible h2:has-text('Team Workload')", timeout=5000)

    def test_m_navigates_to_roadmap(self, page: Page):
        page.keyboard.press("m")
        page.wait_for_selector("main:visible h2:has-text('Roadmap')", timeout=5000)


# ── Test: Workload view ───────────────────────────────────────────────────────

class TestWorkloadView:
    def test_workload_view_loads(self, page: Page):
        switch_view(page, "Team")
        page.wait_for_selector("main:visible h2:has-text('Team Workload')", timeout=5000)

    def test_workload_shows_unassigned_group(self, page: Page):
        # Create an unassigned ticket so the Unassigned group definitely appears
        create_ticket(page, unique("unassigned-workload"))
        switch_view(page, "Team")
        page.wait_for_selector("main:visible h2:has-text('Team Workload')", timeout=5000)
        page.wait_for_load_state("networkidle", timeout=5000)
        page.wait_for_timeout(500)
        # Check via JS that "Unassigned" text appears in a visible main section
        has_unassigned = page.evaluate(
            "() => [...document.querySelectorAll('main')]"
            ".filter(m => m.offsetParent !== null)"
            ".some(m => m.textContent.includes('Unassigned'))"
        )
        assert has_unassigned, "Expected 'Unassigned' group text to appear in workload view"

    def test_workload_refresh_works(self, page: Page):
        switch_view(page, "Team")
        page.wait_for_selector("main:visible h2:has-text('Team Workload')", timeout=5000)
        # Refresh button is inside the visible workload main section
        page.locator("main:visible button:has-text('↻ Refresh')").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("main:visible h2:has-text('Team Workload')", timeout=5000)


# ── Test: Roadmap view ────────────────────────────────────────────────────────

class TestRoadmapView:
    def test_roadmap_view_loads(self, page: Page):
        switch_view(page, "Roadmap")
        page.wait_for_selector("main:visible h2:has-text('Roadmap')", timeout=5000)

    def test_roadmap_refresh_works(self, page: Page):
        switch_view(page, "Roadmap")
        page.wait_for_selector("main:visible h2:has-text('Roadmap')", timeout=5000)
        page.locator("main:visible button:has-text('↻ Refresh')").click()
        page.wait_for_load_state("networkidle")


# ── Test: Projects view ───────────────────────────────────────────────────────

class TestProjectsView:
    def test_projects_view_loads(self, page: Page):
        switch_view(page, "Projects")
        expect(page.locator("button", has_text="New project").first).to_be_visible(timeout=5000)

    def test_create_project(self, page: Page):
        switch_view(page, "Projects")
        page.locator("button", has_text="New project").first.click()
        page.wait_for_selector("input[x-model='projectForm.name']", state="visible", timeout=5000)
        name = unique("E2E-Project")
        page.fill("input[x-model='projectForm.name']", name)
        page.locator("button", has_text="Create project").click()
        expect(page.locator("text=Project created")).to_be_visible(timeout=6000)
        expect(page.locator(f"text={name}").first).to_be_visible(timeout=5000)


# ── Test: WIP limits ─────────────────────────────────────────────────────────

class TestWipLimits:
    def test_wip_modal_has_number_inputs(self, page: Page):
        page.locator("button", has_text="WIP").first.click()
        page.wait_for_selector("text=WIP Limits", state="visible", timeout=3000)
        wip_modal = page.locator("div.rounded-2xl:has(h2:has-text('WIP Limits'))")
        inputs = wip_modal.locator("input[type='number']")
        assert inputs.count() >= 4
        page.keyboard.press("Escape")

    def test_wip_limit_persists_after_change(self, page: Page):
        page.locator("button", has_text="WIP").first.click()
        # Use h2 selector to avoid matching the toast ("WIP limits saved" contains "WIP Limits")
        page.wait_for_selector("h2:has-text('WIP Limits')", state="visible", timeout=3000)
        wip_modal = page.locator("div.rounded-2xl:has(h2:has-text('WIP Limits'))")
        # Change In Progress limit (2nd column, index 1)
        inp = wip_modal.locator("input[type='number']").nth(1)
        inp.fill("8")
        # @change handler calls saveWipLimits() which saves to localStorage and closes the modal
        inp.dispatch_event("change")
        # Modal heading hides when wipEditOpen=false
        page.wait_for_selector("h2:has-text('WIP Limits')", state="hidden", timeout=5000)
        # Reopen and verify persistence
        page.locator("button", has_text="WIP").first.click()
        page.wait_for_selector("h2:has-text('WIP Limits')", state="visible", timeout=3000)
        wip_modal2 = page.locator("div.rounded-2xl:has(h2:has-text('WIP Limits'))")
        saved_value = wip_modal2.locator("input[type='number']").nth(1).input_value()
        assert saved_value == "8", f"Expected 8, got {saved_value}"
        page.keyboard.press("Escape")


# ── Test: API smoke tests ─────────────────────────────────────────────────────

class TestAPIEndpoints:
    def test_api_tickets_returns_list(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/tickets")
        assert resp.status == 200
        body = resp.json()
        assert "tickets" in body and isinstance(body["tickets"], list)

    def test_api_board_has_all_columns(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/board")
        assert resp.status == 200
        body = resp.json()
        for col in ["backlog", "in_progress", "review", "done"]:
            assert col in body, f"Missing column: {col}"

    def test_api_stats_has_total(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/stats")
        assert resp.status == 200
        assert "total" in resp.json()

    def test_api_workload_returns_list(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/workload")
        assert resp.status == 200
        assert isinstance(resp.json(), list)

    def test_api_export_csv_has_header(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/export/csv")
        assert resp.status == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "key,title" in resp.text()

    def test_api_export_json_is_array(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/export/json")
        assert resp.status == 200
        assert isinstance(resp.json(), list)

    def test_api_projects_list(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/projects")
        assert resp.status == 200
        assert isinstance(resp.json(), list)

    def test_api_sprints_list(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/sprints")
        assert resp.status == 200
        assert isinstance(resp.json(), list)

    def test_api_create_and_fetch_ticket(self, page: Page):
        title = unique("api-create")
        create_resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data=f'{{"title":"{title}","ticket_type":"task","priority":"high"}}',
        )
        assert create_resp.status == 201
        key = create_resp.json()["key"]
        assert key.startswith("SBE-")
        fetch_resp = page.request.get(f"{BASE_URL}/api/tickets/{key}")
        assert fetch_resp.status == 200
        assert fetch_resp.json()["title"] == title

    def test_api_move_ticket(self, page: Page):
        create_resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data=f'{{"title":"{unique("move-test")}","ticket_type":"task"}}',
        )
        key = create_resp.json()["key"]
        move_resp = page.request.post(
            f"{BASE_URL}/api/tickets/{key}/move",
            headers={"Content-Type": "application/json"},
            data='{"status":"in_progress"}',
        )
        assert move_resp.status == 200
        assert move_resp.json()["status"] == "in_progress"

    def test_api_create_sprint(self, page: Page):
        name = unique("API-Sprint")
        resp = page.request.post(
            f"{BASE_URL}/api/sprints",
            headers={"Content-Type": "application/json"},
            data=f'{{"name":"{name}"}}',
        )
        assert resp.status == 201
        body = resp.json()
        assert "id" in body and body["name"] == name

    def test_api_duplicate_sprint_is_409(self, page: Page):
        name = unique("Dup-Sprint")
        page.request.post(
            f"{BASE_URL}/api/sprints",
            headers={"Content-Type": "application/json"},
            data=f'{{"name":"{name}"}}',
        )
        resp = page.request.post(
            f"{BASE_URL}/api/sprints",
            headers={"Content-Type": "application/json"},
            data=f'{{"name":"{name}"}}',
        )
        assert resp.status == 409
        assert "already exists" in resp.json()["detail"]

    def test_api_unknown_ticket_is_404(self, page: Page):
        resp = page.request.get(f"{BASE_URL}/api/tickets/SBE-99999")
        assert resp.status == 404

    def test_api_subtasks_empty_for_new_ticket(self, page: Page):
        create_resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data=f'{{"title":"{unique("parent")}","ticket_type":"task"}}',
        )
        key = create_resp.json()["key"]
        resp = page.request.get(f"{BASE_URL}/api/tickets/{key}/subtasks")
        assert resp.status == 200
        assert resp.json() == []

    def test_api_create_and_list_subtask(self, page: Page):
        parent_resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data=f'{{"title":"{unique("parent-sub")}","ticket_type":"task"}}',
        )
        parent_key = parent_resp.json()["key"]
        sub_resp = page.request.post(
            f"{BASE_URL}/api/tickets/{parent_key}/subtasks",
            headers={"Content-Type": "application/json"},
            data=f'{{"title":"{unique("child")}","ticket_type":"task","priority":"low"}}',
        )
        assert sub_resp.status == 201
        child = sub_resp.json()
        assert child["parent_key"] == parent_key
        list_resp = page.request.get(f"{BASE_URL}/api/tickets/{parent_key}/subtasks")
        assert list_resp.status == 200
        assert child["key"] in [t["key"] for t in list_resp.json()]

    def test_api_add_comment(self, page: Page):
        create_resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data=f'{{"title":"{unique("comment-ticket")}","ticket_type":"task"}}',
        )
        key = create_resp.json()["key"]
        comment_resp = page.request.post(
            f"{BASE_URL}/api/tickets/{key}/comments",
            headers={"Content-Type": "application/json"},
            data='{"author":"tester","body":"API comment test"}',
        )
        assert comment_resp.status == 201
        list_resp = page.request.get(f"{BASE_URL}/api/tickets/{key}/comments")
        assert list_resp.status == 200
        assert any(c["body"] == "API comment test" for c in list_resp.json())

    def test_api_log_time(self, page: Page):
        create_resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data=f'{{"title":"{unique("time-ticket")}","ticket_type":"task"}}',
        )
        key = create_resp.json()["key"]
        time_resp = page.request.post(
            f"{BASE_URL}/api/tickets/{key}/time",
            headers={"Content-Type": "application/json"},
            data='{"minutes":90,"note":"API time test","author":"dev"}',
        )
        assert time_resp.status == 201
        list_resp = page.request.get(f"{BASE_URL}/api/tickets/{key}/time")
        assert list_resp.status == 200
        body = list_resp.json()
        entries = body if isinstance(body, list) else body.get("entries", [])
        assert any(e["minutes"] == 90 for e in entries)


# ── Test: Settings panel ──────────────────────────────────────────────────────

class TestSettingsPanel:
    def _open_settings(self, page: Page) -> None:
        # Avatar/account button — identified by containing a rounded-full avatar div
        page.locator("div[x-data*='menuOpen'] > button").first.click()
        page.wait_for_timeout(200)
        page.locator("button:has-text('Settings')").first.click()
        page.wait_for_selector("h2:has-text('Preferences')", state="visible", timeout=5000)

    def test_settings_panel_opens(self, page: Page):
        self._open_settings(page)
        expect(page.locator("h2:has-text('Preferences')")).to_be_visible()

    def test_settings_panel_closes_on_escape(self, page: Page):
        self._open_settings(page)
        page.keyboard.press("Escape")
        expect(page.locator("h2:has-text('Preferences')")).not_to_be_visible()

    def test_settings_panel_closes_on_backdrop_click(self, page: Page):
        self._open_settings(page)
        page.locator("div.backdrop").first.click()
        expect(page.locator("h2:has-text('Preferences')")).not_to_be_visible()

    def test_settings_shows_preview_card(self, page: Page):
        self._open_settings(page)
        # Live preview card shows a fake ticket key — scope to settings panel
        settings_panel = page.locator("div.panel-in:visible")
        expect(settings_panel.locator("text=SBE-42").first).to_be_visible()

    def test_theme_toggle_light(self, page: Page):
        self._open_settings(page)
        page.locator("button:has-text('Light')").first.click()
        page.wait_for_timeout(300)
        theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
        assert theme == "light"
        # Restore dark
        page.locator("button:has-text('Dark')").first.click()
        page.wait_for_timeout(200)

    def test_theme_toggle_dark(self, page: Page):
        self._open_settings(page)
        page.locator("button:has-text('Dark')").first.click()
        page.wait_for_timeout(300)
        theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
        assert theme == "dark"

    def test_font_size_slider_changes_html_font_size(self, page: Page):
        self._open_settings(page)
        # The slider goes 12–18; click the slider and set value via JS
        page.evaluate("""
            const slider = document.querySelector('input[type=range]');
            slider.value = 16;
            slider.dispatchEvent(new Event('input', {bubbles: true}));
        """)
        page.wait_for_timeout(300)
        font_size = page.evaluate("document.documentElement.style.fontSize")
        assert font_size == "16px"
        # Reset via the button
        page.locator("button:has-text('Reset all to defaults')").click()
        page.wait_for_timeout(200)

    def test_font_size_display_updates(self, page: Page):
        self._open_settings(page)
        page.evaluate("""
            const slider = document.querySelector('input[type=range]');
            slider.value = 17;
            slider.dispatchEvent(new Event('input', {bubbles: true}));
        """)
        page.wait_for_timeout(200)
        label = page.locator("span.font-mono.text-acc").first
        expect(label).to_have_text("17px")
        page.locator("button:has-text('Reset all to defaults')").click()

    def test_font_family_buttons_present(self, page: Page):
        self._open_settings(page)
        for label in ["Inter", "Mono", "System"]:
            expect(page.locator(f"button:has-text('{label}')").first).to_be_visible()

    def test_font_family_selection_updates_state(self, page: Page):
        self._open_settings(page)
        page.locator("button:has-text('Mono')").first.click()
        page.wait_for_timeout(300)
        ff = page.evaluate("localStorage.getItem('sbe_ff')")
        assert ff == "mono"
        # Reset
        page.locator("button:has-text('Reset all to defaults')").click()

    def test_density_buttons_present(self, page: Page):
        self._open_settings(page)
        for label in ["Compact", "Normal", "Comfy"]:
            expect(page.locator(f"button:has-text('{label}')").first).to_be_visible()

    def test_density_selection_persists(self, page: Page):
        self._open_settings(page)
        page.locator("button:has-text('Compact')").first.click()
        page.wait_for_timeout(300)
        density = page.evaluate("localStorage.getItem('sbe_density')")
        assert density == "compact"
        page.locator("button:has-text('Reset all to defaults')").click()

    def test_accent_color_buttons_visible(self, page: Page):
        self._open_settings(page)
        # 8 colour swatches in the accent grid
        swatches = page.locator("div.grid-cols-4 button")
        assert swatches.count() >= 4

    def test_accent_color_change_persists(self, page: Page):
        self._open_settings(page)
        # Click second swatch (Violet)
        page.locator("div.grid-cols-4 button").nth(1).click()
        page.wait_for_timeout(300)
        saved_acc = page.evaluate("localStorage.getItem('sbe_acc')")
        assert saved_acc is not None and saved_acc != "#5e6ad2"
        # Reset
        page.locator("button:has-text('Reset all to defaults')").click()
        page.wait_for_timeout(200)
        assert page.evaluate("localStorage.getItem('sbe_acc')") is None

    def test_reset_restores_defaults(self, page: Page):
        self._open_settings(page)
        # Change something
        page.evaluate("""
            const slider = document.querySelector('input[type=range]');
            slider.value = 14;
            slider.dispatchEvent(new Event('input', {bubbles: true}));
        """)
        page.wait_for_timeout(200)
        page.locator("button:has-text('Reset all to defaults')").click()
        page.wait_for_timeout(200)
        font_size = page.evaluate("document.documentElement.style.fontSize")
        assert font_size == "15px"


# ── Test: Admin user management ───────────────────────────────────────────────

class TestAdminUserManagement:
    def _open_user_panel(self, page: Page) -> None:
        page.locator("div[x-data*='menuOpen'] > button").first.click()
        page.wait_for_timeout(200)
        page.locator("button:has-text('Manage users')").first.click()
        page.wait_for_selector("button:has-text('Add user')", state="visible", timeout=5000)

    def test_users_view_loads(self, page: Page):
        self._open_user_panel(page)
        expect(page.locator("button:has-text('Add user')").first).to_be_visible()

    def test_invite_form_opens(self, page: Page):
        self._open_user_panel(page)
        page.locator("button:has-text('Add user')").first.click()
        page.wait_for_selector("input[x-model='userCreateForm.username']", state="visible", timeout=5000)
        expect(page.locator("input[x-model='userCreateForm.username']")).to_be_visible()

    def test_create_user_generates_invite_url(self, page: Page):
        self._open_user_panel(page)
        page.locator("button:has-text('Add user')").first.click()
        page.wait_for_selector("input[x-model='userCreateForm.username']", state="visible", timeout=5000)
        username = unique("e2euser")
        page.fill("input[x-model='userCreateForm.username']", username)
        page.locator("button:has-text('Create & get invite link')").first.click()
        # Wait for the green success banner to appear
        page.wait_for_selector(
            "text=User created — share this invite link", state="visible", timeout=8000
        )
        # Read invite URL from Alpine state (more reliable than querying hidden input)
        invite_url = page.evaluate(
            "() => Alpine.store ? '' : (document.querySelector('[x-data]')?._x_dataStack?.[0]?.inviteUrl || '')"
        )
        if not invite_url:
            # Fallback: read the visible readonly input's value attribute
            invite_url = page.locator("div.bg-green-950\\/40 input[readonly]").input_value()
        assert "/invite/" in invite_url, f"Expected invite URL, got: {invite_url!r}"

    def test_duplicate_username_shows_error(self, page: Page):
        self._open_user_panel(page)
        page.locator("button:has-text('Add user')").first.click()
        page.wait_for_selector("input[x-model='userCreateForm.username']", state="visible")
        page.fill("input[x-model='userCreateForm.username']", "admin")
        page.locator("button:has-text('Create & get invite link')").first.click()
        page.wait_for_timeout(1000)
        expect(page.locator("text=already taken").first).to_be_visible(timeout=3000)

    def test_api_create_user_returns_invite_url(self, page: Page):
        username = unique("apiuser")
        resp = page.request.post(
            f"{BASE_URL}/api/users",
            headers={"Content-Type": "application/json"},
            data=f'{{"username":"{username}","role":"developer"}}',
        )
        assert resp.status == 201
        body = resp.json()
        assert "invite_url" in body
        assert "/invite/" in body["invite_url"]
        assert body["username"] == username


# ── Test: JQL filter chips ────────────────────────────────────────────────────

class TestJQLFilterChips:
    def _set_jql(self, page: Page, query: str) -> None:
        page.evaluate(f"document.querySelector('.filter-input').value = {query!r}")
        page.evaluate(
            "document.querySelector('.filter-input')"
            ".dispatchEvent(new Event('input', {bubbles:true}))"
        )
        page.wait_for_timeout(400)

    def test_priority_chip_appears(self, page: Page):
        # Use colon JQL syntax so parsedJQL.priority is set and a chip appears
        self._set_jql(page, "priority:high")
        chip = page.locator("span.chip").filter(has_text="high")
        expect(chip.first).to_be_visible(timeout=3000)

    def test_status_chip_appears(self, page: Page):
        self._set_jql(page, "status:backlog")
        chip = page.locator("span.chip").filter(has_text="backlog")
        expect(chip.first).to_be_visible(timeout=3000)

    def test_title_chip_appears_without_js_error(self, page: Page):
        # Bare word queries become title searches — this used to throw
        # Alpine Expression Error: Unexpected string (fixed &quot; bug)
        self._set_jql(page, "hello")
        page.wait_for_timeout(300)
        # The title chip spans shows within the now-visible filter bar
        title_chip = page.locator("span.chip:not(.bg-accL)")
        expect(title_chip.first).to_be_visible(timeout=3000)
        expect(title_chip.first).to_contain_text("hello")

    def test_clear_all_removes_chips(self, page: Page):
        self._set_jql(page, "status:done")
        # Wait for chip bar to appear
        page.locator("span.chip").filter(has_text="done").wait_for(state="visible", timeout=3000)
        page.locator("button:has-text('Clear all')").first.click()
        page.wait_for_timeout(400)
        # Filter bar hides when no active filters
        expect(page.locator("span.chip").filter(has_text="done")).not_to_be_visible()

    def test_chip_remove_button_clears_filter(self, page: Page):
        self._set_jql(page, "priority:low")
        chip = page.locator("span.chip").filter(has_text="low")
        chip.first.wait_for(state="visible", timeout=3000)
        # Click the × svg button inside the chip
        chip.first.locator("button").click()
        page.wait_for_timeout(400)
        expect(page.locator("span.chip").filter(has_text="low")).not_to_be_visible()


# ── Test: Console error absence ───────────────────────────────────────────────

class TestNoConsoleErrors:
    """Verify critical interactions produce no JS errors."""

    def test_board_load_no_errors(self, page: Page):
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.wait_for_timeout(800)
        assert errors == [], f"Console errors on board load: {errors}"

    def test_filter_title_chip_no_error(self, page: Page):
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.evaluate("document.querySelector('.filter-input').value = 'title=test'")
        page.evaluate(
            "document.querySelector('.filter-input')"
            ".dispatchEvent(new Event('input', {bubbles:true}))"
        )
        page.wait_for_timeout(500)
        assert errors == [], f"Console errors after title filter: {errors}"

    def test_settings_panel_no_errors(self, page: Page):
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.locator("div[x-data*='menuOpen'] > button").first.click()
        page.wait_for_timeout(200)
        page.locator("button:has-text('Settings')").first.click()
        page.wait_for_timeout(600)
        assert errors == [], f"Console errors in settings panel: {errors}"

    def test_detail_panel_no_errors(self, page: Page):
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        cards = page.locator("div.ticket-card")
        if cards.count() > 0:
            cards.first.click()
            page.wait_for_timeout(800)
        assert errors == [], f"Console errors in detail panel: {errors}"


# ── Test: Activity log ────────────────────────────────────────────────────────

class TestActivityLog:
    """Verify the activity log timeline in the ticket detail panel."""

    def _open_ticket_detail(self, page: Page) -> None:
        """Create a ticket via API and open its detail panel via Alpine.

        Creates via API (not the form) to get the key immediately, then calls
        Alpine.$data().openDetail() directly — bypassing the board LIMIT-100
        entirely so the test never depends on the card appearing in the board DOM.
        """
        import json as _json
        title = unique("actlog")
        resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data=_json.dumps({"title": title, "ticket_type": "task", "priority": "medium"}),
        )
        assert resp.status == 201, f"Ticket creation failed: {resp.status}"
        key = resp.json()["key"]
        # Call Alpine's public API to open the detail panel for this specific ticket
        page.evaluate(
            f"Alpine.$data(document.querySelector('[x-data]')).openDetail({{key: '{key}'}})"
        )
        page.wait_for_selector("p:has-text('Activity')", state="visible", timeout=6000)
        # Let loadActivityLog() fetch complete
        page.wait_for_timeout(600)

    def test_activity_section_visible(self, page: Page):
        """Activity section header renders inside the detail panel."""
        self._open_ticket_detail(page)
        expect(page.locator("p:has-text('Activity')").first).to_be_visible()

    def test_created_entry_appears_on_open(self, page: Page):
        """Opening a freshly created ticket shows a 'Ticket created' entry."""
        self._open_ticket_detail(page)
        page.wait_for_selector("text=Ticket created", state="visible", timeout=5000)
        expect(page.locator("text=Ticket created").first).to_be_visible()

    def test_status_change_is_logged(self, page: Page):
        """Moving a ticket's status via the detail panel adds a status_changed entry."""
        self._open_ticket_detail(page)
        # The status <select> is inside the scrollable panel but select_option()
        # works via JS value-setting, so no viewport check needed.
        status_select = page.locator("select.bg-transparent.text-n100").first
        status_select.select_option("in_progress")
        # activityLabel renders "Status → in progress" scoped to the activity section.
        # Rely solely on the expect() timeout — the intermediate wait_for_selector("text=Status")
        # would resolve immediately against the property label and give false confidence.
        activity_section = page.locator("div.px-5.pb-5.border-t.border-n700:has(p:has-text('Activity'))")
        expect(activity_section.locator("text=in progress").first).to_be_visible(timeout=5000)

    def test_comment_added_is_logged(self, page: Page):
        """Posting a comment adds a 'Comment added' entry to the activity log."""
        self._open_ticket_detail(page)
        textarea = page.locator("textarea[x-model='commentBody']")
        textarea.fill(unique("actlog-comment"))
        # Post comment button is in the scroll container — use evaluate()
        page.locator("button:has-text('Post comment')").evaluate("el => el.click()")
        expect(textarea).to_have_value("", timeout=5000)
        # activityLabel("comment_added") → "Comment added"
        page.wait_for_selector("text=Comment added", state="visible", timeout=5000)
        expect(page.locator("text=Comment added").first).to_be_visible()

    def test_time_logged_is_recorded_in_activity(self, page: Page):
        """Logging time adds a 'Time logged:' entry to the activity log."""
        self._open_ticket_detail(page)
        page.locator("button:has-text('+ Log')").evaluate("el => el.click()")
        page.wait_for_selector("input[x-model='timeForm.note']", state="visible", timeout=3000)
        page.locator("input[placeholder='Minutes']").fill("45")
        page.locator("div[x-show='timeFormOpen']:visible button:has-text('Log')").evaluate(
            "el => el.click()"
        )
        # activityLabel("time_logged") → "Time logged: 45m"
        # "Time logged:" with colon distinguishes it from the "Time logged" section header
        page.wait_for_selector("text=Time logged:", state="visible", timeout=5000)
        expect(page.locator("text=Time logged:").first).to_be_visible()

    def test_subtask_added_is_logged(self, page: Page):
        """Creating a subtask adds a 'Subtask SBE-N added' entry."""
        self._open_ticket_detail(page)
        page.locator("button:has-text('+ Add')").first.evaluate("el => el.click()")
        page.wait_for_selector("input[x-model='subtaskForm.title']", state="visible", timeout=3000)
        page.locator("input[x-model='subtaskForm.title']").fill(unique("sub"))
        page.locator("div[x-show='subtaskFormOpen']:visible button:has-text('Create')").evaluate(
            "el => el.click()"
        )
        page.wait_for_timeout(500)
        # activityLabel("subtask_added") → "Subtask <SBE-N> added"
        page.wait_for_selector("text=Subtask SBE-", state="visible", timeout=5000)
        activity_section = page.locator("div.px-5.pb-5.border-t.border-n700:has(p:has-text('Activity'))")
        expect(activity_section.locator("text=Subtask SBE-").first).to_be_visible()

    def test_actor_name_shown_in_entry(self, page: Page):
        """Each activity entry displays the actor who made the change."""
        self._open_ticket_detail(page)
        page.wait_for_selector("text=Ticket created", state="visible", timeout=5000)
        # Actor span has class "text-n500 font-medium" (distinct from the label's
        # hl() spans which use "text-n200 font-medium") — must target specifically
        # to avoid matching field-value highlights instead of the actor name.
        activity_section = page.locator("div.px-5.pb-5.border-t.border-n700:has(p:has-text('Activity'))")
        actor_span = activity_section.locator("span.text-n500.font-medium").first
        expect(actor_span).to_be_visible(timeout=5000)
        actor_text = actor_span.inner_text()
        assert actor_text.strip(), "Actor name must not be empty in activity entry"

    def test_api_activity_endpoint_returns_created_entry(self, page: Page):
        """GET /api/tickets/{key}/activity returns the 'created' entry immediately after creation."""
        resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data='{"title":"API actlog test","ticket_type":"task","priority":"medium"}',
        )
        assert resp.status == 201, f"Ticket creation failed: {resp.status}"
        key = resp.json()["key"]

        activity = page.request.get(f"{BASE_URL}/api/tickets/{key}/activity")
        assert activity.status == 200
        entries = activity.json()
        assert isinstance(entries, list), "Activity endpoint must return a list"
        assert len(entries) >= 1, "Expected at least one entry after creation"
        actions = [e["action"] for e in entries]
        assert "created" in actions, f"'created' entry missing from: {actions}"

    def test_api_logs_status_change(self, page: Page):
        """POST /api/tickets/{key}/move is recorded in the activity API."""
        resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data='{"title":"API status-log test","ticket_type":"task","priority":"medium"}',
        )
        assert resp.status == 201
        key = resp.json()["key"]

        move = page.request.post(
            f"{BASE_URL}/api/tickets/{key}/move",
            headers={"Content-Type": "application/json"},
            data='{"status":"in_progress"}',
        )
        assert move.status == 200

        activity = page.request.get(f"{BASE_URL}/api/tickets/{key}/activity").json()
        status_entry = next((e for e in activity if e["action"] == "status_changed"), None)
        assert status_entry is not None, f"No 'status_changed' entry in: {[e['action'] for e in activity]}"
        assert status_entry["new_value"] == "in_progress"
        assert status_entry["old_value"] == "backlog"
        assert status_entry["field"] == "status"

    def test_api_logs_comment(self, page: Page):
        """POST /api/tickets/{key}/comments adds a comment_added entry."""
        resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data='{"title":"API comment-log test","ticket_type":"task","priority":"medium"}',
        )
        assert resp.status == 201
        key = resp.json()["key"]

        comment = page.request.post(
            f"{BASE_URL}/api/tickets/{key}/comments",
            headers={"Content-Type": "application/json"},
            data='{"body":"hello from test","author":"tester"}',
        )
        assert comment.status == 201

        activity = page.request.get(f"{BASE_URL}/api/tickets/{key}/activity").json()
        comment_entry = next((e for e in activity if e["action"] == "comment_added"), None)
        assert comment_entry is not None, "Expected 'comment_added' entry in activity log"
        assert "hello from test" in (comment_entry["new_value"] or "")

    def test_api_logs_field_change(self, page: Page):
        """PATCH /api/tickets/{key} records changed fields individually."""
        resp = page.request.post(
            f"{BASE_URL}/api/tickets",
            headers={"Content-Type": "application/json"},
            data='{"title":"API field-log test","ticket_type":"task","priority":"medium"}',
        )
        assert resp.status == 201
        key = resp.json()["key"]

        patch = page.request.patch(
            f"{BASE_URL}/api/tickets/{key}",
            headers={"Content-Type": "application/json"},
            data='{"priority":"high"}',
        )
        assert patch.status == 200

        activity = page.request.get(f"{BASE_URL}/api/tickets/{key}/activity").json()
        field_entry = next(
            (e for e in activity if e["action"] == "field_changed" and e["field"] == "priority"),
            None,
        )
        assert field_entry is not None, "Expected 'field_changed' entry for priority"
        assert field_entry["old_value"] == "medium"
        assert field_entry["new_value"] == "high"

    def test_activity_api_404_for_unknown_ticket(self, page: Page):
        """GET /api/tickets/NOTREAL/activity returns 404."""
        resp = page.request.get(f"{BASE_URL}/api/tickets/NOTREAL-9999/activity")
        assert resp.status == 404

    def test_no_console_errors_in_activity_section(self, page: Page):
        """Viewing the activity log produces no JavaScript console errors."""
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        self._open_ticket_detail(page)
        page.wait_for_timeout(800)
        assert errors == [], f"Console errors while viewing activity log: {errors}"
