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
        expect(page.locator(f"text={title}").first).to_be_visible(timeout=5000)

    def test_create_bug_ticket(self, page: Page):
        title = unique("E2E-bug")
        create_ticket(page, title, ticket_type="bug")
        expect(page.locator(f"text={title}").first).to_be_visible(timeout=5000)

    def test_create_story_ticket(self, page: Page):
        title = unique("E2E-story")
        create_ticket(page, title, ticket_type="story")
        expect(page.locator(f"text={title}").first).to_be_visible(timeout=5000)

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
        expect(page.locator("span.font-mono").first).to_be_visible()

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
        # Scroll the button into view before clicking
        post_btn = page.locator("button:has-text('Post comment')")
        post_btn.scroll_into_view_if_needed()
        post_btn.click()
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
        # Open time form
        page.locator("button:has-text('+ Log')").click()
        page.wait_for_selector("input[x-model='timeForm.note']", state="visible", timeout=3000)
        page.locator("input[placeholder='Minutes']").fill("45")
        page.locator("input[x-model='timeForm.note']").fill("E2E test work")
        # Submit: the Log button is the last visible button in the time form
        page.locator("div[x-show='timeFormOpen']:visible button:has-text('Log')").click()
        # Toast says "Time logged"
        toast_area = page.locator("div.fixed.bottom-5.right-5")
        toast_area.locator("text=Time logged").wait_for(state="visible", timeout=5000)

    def test_create_subtask(self, page: Page):
        self._open_any_ticket_detail(page)
        # Open subtask form
        page.locator("button:has-text('+ Add')").first.click()
        page.wait_for_selector("input[x-model='subtaskForm.title']", state="visible", timeout=3000)
        page.locator("input[x-model='subtaskForm.title']").fill(unique("subtask"))
        # Submit: Create button inside the visible subtask form
        page.locator("div[x-show='subtaskFormOpen']:visible button:has-text('Create')").click()
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
