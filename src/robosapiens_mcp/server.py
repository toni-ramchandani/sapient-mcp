"""
SAPient MCP Server — all tools registered here.

Tool naming: sap_{verb}_{noun}
Read-only tools: only observe / return data, never mutate SAP state.
Mutating tools: change SAP state (fill fields, click buttons, etc.)
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .config import RoboSAPiensMCPConfig
from .session import SAPError, SAPSessionManager, SessionState

log = logging.getLogger("sapient_mcp.server")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ok(msg: str, **extra) -> str:
    """Standard success response — plain text for LLM."""
    if extra:
        return f"{msg}\n{json.dumps(extra, indent=2)}"
    return msg


def _err(exc: SAPError, screenshot_b64: Optional[str] = None) -> str:
    """Format a SAPError as a rich text response the LLM can act on."""
    parts = [f"ERROR: {exc}"]
    if exc.keyword:
        parts.append(f"Keyword: {exc.keyword}")
    if exc.hint:
        parts.append(f"Hint: {exc.hint}")
    if screenshot_b64:
        parts.append("[Screenshot captured — see image content below]")
    return "\n".join(parts)


def _run(
    session: SAPSessionManager,
    config: RoboSAPiensMCPConfig,
    keyword: str,
    *args: Any,
    record: bool = True,
) -> tuple[Any, Optional[str]]:
    """
    Execute a keyword, capturing screenshot on failure.
    Returns (result, screenshot_b64_or_None).
    Raises SAPError on failure (caller decides how to surface).
    """
    try:
        result = session.execute(keyword, *args)
        if record and config.cap_codegen:
            session.record(keyword, *args)
        return result, None
    except SAPError as exc:
        ss = session.take_screenshot("error") if config.screenshot_on_error else None
        raise exc from exc.__cause__  # re-raise; caller will attach ss


# ── Server factory ─────────────────────────────────────────────────────────────

def build_server(config: RoboSAPiensMCPConfig) -> FastMCP:
    mcp = FastMCP(
        "sapient",
        instructions=(
            "SAPient MCP lets you automate SAP GUI using natural language. "
            "Always call sap_get_window_title or sap_get_snapshot (if available) "
            "to understand the current state before performing actions. "
            "Use sap_read_status_bar after Save/Post operations to confirm success."
        ),
    )
    session = SAPSessionManager.instance()

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 1 — SESSION MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="sap_open",
        description=(
            "Launch SAP Logon (saplogon.exe). Must be called before sap_connect_to_server. "
            "Defaults to the configured saplogon_path if no path provided."
        ),
    )
    def sap_open(
        saplogon_path: Annotated[
            Optional[str],
            Field(description="Full path to saplogon.exe. Uses server default if omitted."),
        ] = None,
    ) -> str:
        path = saplogon_path or config.saplogon_path
        try:
            session.execute("Open SAP", path)
            session.set_state(SessionState.SAP_OPEN)
            return _ok(f"SAP Logon opened from: {path}")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_connect_to_server",
        description=(
            "Connect to an SAP server using the description shown in the SAP Logon list. "
            "Use the DESCRIPTION (not SID). SAP Logon must already be open (sap_open). "
            "After connecting, the SAP login screen appears."
        ),
    )
    def sap_connect_to_server(
        server_description: Annotated[
            str,
            Field(description="Exact server description from SAP Logon list (case-sensitive, watch for extra spaces)"),
        ],
    ) -> str:
        try:
            session.execute("Connect To Server", server_description)
            session.set_state(SessionState.CONNECTED)
            session._server_description = server_description
            if config.cap_codegen:
                session.record("Connect To Server", server_description)
            return _ok(f"Connected to SAP server: '{server_description}'. Login screen should now be visible.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_connect_to_running",
        description=(
            "Attach to an already-running SAP GUI session. "
            "Use when SAP is pre-launched (e.g. SSO environments) or when "
            "you want to take control of an existing session."
        ),
    )
    def sap_connect_to_running() -> str:
        try:
            session.execute("Connect To Running SAP")
            session.set_state(SessionState.LOGGED_IN)
            if config.cap_codegen:
                session.record("Connect To Running SAP")
            return _ok("Attached to running SAP session.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_get_session_info",
        description="Return current session state, window title, and connection info. Read-only — safe to call anytime.",
    )
    def sap_get_session_info() -> str:
        info: dict[str, Any] = {
            "state": session.state.name,
            "server": session._server_description,
            "connected": session.is_connected(),
            "logged_in": session.is_logged_in(),
        }
        if session.is_connected():
            try:
                info["window_title"] = session.execute("Get Window Title")
            except SAPError:
                info["window_title"] = "unavailable"
        return json.dumps(info, indent=2)

    @mcp.tool(
        name="sap_close",
        description="Close the SAP GUI application. Ends the SAP session.",
    )
    def sap_close() -> str:
        try:
            session.execute("Close SAP")
            session.set_state(SessionState.DISCONNECTED)
            session._server_description = None
            if config.cap_codegen:
                session.record("Close SAP")
            return _ok("SAP GUI closed.")
        except SAPError as exc:
            return _err(exc)

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 2 — NAVIGATION
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="sap_execute_transaction",
        description=(
            "Execute a SAP transaction code. "
            "Use /n prefix to navigate to a new transaction from anywhere (e.g. /nME21N). "
            "Use /o prefix to open in a new session window."
        ),
    )
    def sap_execute_transaction(
        transaction_code: Annotated[
            str,
            Field(description="Transaction code, e.g. 'ME21N', '/nSE16', '/nMB52'"),
        ],
    ) -> str:
        session.require_logged_in()
        try:
            result, _ = _run(session, config, "Execute Transaction", transaction_code)
            title = session.execute("Get Window Title")
            return _ok(f"Transaction '{transaction_code}' executed.", window_title=title)
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_activate_tab",
        description="Click on a tab in the current SAP screen by its visible label text.",
    )
    def sap_activate_tab(
        tab_label: Annotated[str, Field(description="The visible text label of the tab")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Activate Tab", tab_label)
            return _ok(f"Tab '{tab_label}' activated.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_get_window_title",
        description="Return the title of the current SAP window. Read-only. Use to confirm navigation.",
    )
    def sap_get_window_title() -> str:
        try:
            title = session.execute("Get Window Title", record=False) if False else session.execute("Get Window Title")
            return title or "(empty title)"
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_select_menu_item",
        description=(
            "Navigate the SAP menu bar. Provide the full path as separate arguments, "
            "e.g. path=['Goto', 'Back'] or path=['Edit', 'Select All']."
        ),
    )
    def sap_select_menu_item(
        path: Annotated[
            list[str],
            Field(description="Menu path as a list of labels, e.g. ['Edit', 'Select All']"),
        ],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Select Menu Item", *path)
            return _ok(f"Menu item selected: {' → '.join(path)}")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_send_key",
        description=(
            "Send a SAP GUI keyboard key. "
            "Common values: Enter, F1–F12, F3 (Back), F8 (Execute), "
            "PageDown, PageUp, Tab, Escape, Save (Ctrl+S equivalent)."
        ),
    )
    def sap_send_key(
        key: Annotated[str, Field(description="Key name: Enter, F3, F8, PageDown, PageUp, Tab, Escape, Save")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Send SAP Keys", key)
            return _ok(f"Key sent: {key}")
        except SAPError as exc:
            return _err(exc)

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 3 — FORM INPUT
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="sap_fill_text_field",
        description=(
            "Fill a text input field in SAP GUI identified by its visible label. "
            "The label is the text shown next to or above the field on screen. "
            "Password fields are automatically masked in logs."
        ),
    )
    def sap_fill_text_field(
        label: Annotated[str, Field(description="Visible label of the text field as shown in SAP")],
        value: Annotated[str, Field(description="Value to enter into the field")],
    ) -> str:
        session.require_connected()
        ss = None
        try:
            session.execute("Fill Text Field", label, value)
            # Redact password from codegen script
            record_value = "***" if label.lower() in ("password", "passwort", "kennwort") else value
            if config.cap_codegen:
                session.record("Fill Text Field", label, record_value)
            return _ok(f"Field '{label}' filled.")
        except SAPError as exc:
            if config.screenshot_on_error:
                ss = session.take_screenshot("fill_error")
            return _err(exc, ss)

    @mcp.tool(
        name="sap_clear_text_field",
        description="Clear the contents of a text field identified by its visible label.",
    )
    def sap_clear_text_field(
        label: Annotated[str, Field(description="Visible label of the text field")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Clear Text Field", label)
            return _ok(f"Field '{label}' cleared.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_set_checkbox",
        description="Check (tick) a checkbox in SAP GUI identified by its visible label.",
    )
    def sap_set_checkbox(
        label: Annotated[str, Field(description="Visible label of the checkbox")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Set Checkbox", label)
            return _ok(f"Checkbox '{label}' checked.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_unset_checkbox",
        description="Uncheck a checkbox in SAP GUI identified by its visible label.",
    )
    def sap_unset_checkbox(
        label: Annotated[str, Field(description="Visible label of the checkbox")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Unset Checkbox", label)
            return _ok(f"Checkbox '{label}' unchecked.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_select_radio_button",
        description="Select a radio button in SAP GUI identified by its visible label.",
    )
    def sap_select_radio_button(
        label: Annotated[str, Field(description="Visible label of the radio button")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Select Radio Button", label)
            return _ok(f"Radio button '{label}' selected.")
        except SAPError as exc:
            return _err(exc)

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 4 — ACTIONS (Buttons)
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="sap_push_button",
        description=(
            "Click a button in SAP GUI identified by its visible label or tooltip. "
            "Common buttons: Save, Enter, Back, Cancel, Execute, Yes, No, Continue."
        ),
    )
    def sap_push_button(
        label: Annotated[str, Field(description="Visible label or tooltip of the button")],
    ) -> str:
        session.require_connected()
        try:
            _run(session, config, "Push Button", label)
            return _ok(f"Button '{label}' clicked.")
        except SAPError as exc:
            ss = session.take_screenshot("button_error") if config.screenshot_on_error else None
            return _err(exc, ss)

    @mcp.tool(
        name="sap_button_exists",
        description=(
            "Check whether a button with the given label exists on the current screen. "
            "Returns true/false. Use this for conditional logic before pushing buttons."
        ),
    )
    def sap_button_exists(
        label: Annotated[str, Field(description="Visible label or tooltip of the button to check")],
    ) -> str:
        session.require_logged_in()
        try:
            session.execute("Highlight Button", label)
            return json.dumps({"exists": True, "label": label})
        except SAPError:
            return json.dumps({"exists": False, "label": label})

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 5 — READ / INSPECT (read-only)
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="sap_read_text_field",
        description=(
            "Read the current value of a text field identified by its visible label. "
            "Read-only — does not modify SAP state."
        ),
    )
    def sap_read_text_field(
        label: Annotated[str, Field(description="Visible label of the text field")],
    ) -> str:
        session.require_logged_in()
        try:
            value = session.execute("Read Text Field", label)
            return json.dumps({"label": label, "value": value})
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_read_text",
        description="Read the text content of any SAP element (label, status message, etc.) by its identifier.",
    )
    def sap_read_text(
        locator: Annotated[str, Field(description="Label or identifier of the SAP text element")],
    ) -> str:
        session.require_logged_in()
        try:
            value = session.execute("Read Text", locator)
            return json.dumps({"locator": locator, "value": value})
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_read_status_bar",
        description=(
            "Read the SAP status bar message at the bottom of the window. "
            "Always call this after Save/Post operations to confirm success or get error details. "
            "Read-only."
        ),
    )
    def sap_read_status_bar() -> str:
        session.require_logged_in()
        try:
            msg = session.execute("Read Status Bar")
            return json.dumps({"status_bar": msg or "(empty)"})
        except SAPError as exc:
            return _err(exc)

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 6 — TABLE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="sap_count_table_rows",
        description="Return the total number of rows in the currently visible table. Read-only.",
    )
    def sap_count_table_rows() -> str:
        session.require_logged_in()
        try:
            count = session.execute("Count Table Rows")
            return json.dumps({"row_count": count})
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_select_table_row",
        description=(
            "Select a row in the SAP table. "
            "Identify by row number (1-based integer) or by a cell value in that row."
        ),
    )
    def sap_select_table_row(
        row_locator: Annotated[
            str,
            Field(description="Row number as string (e.g. '1') or cell value in that row (e.g. 'P.O.-12345')"),
        ],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Select Table Row", row_locator)
            return _ok(f"Table row '{row_locator}' selected.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_read_table_cell",
        description="Read the value of a specific table cell. Identify row by number or cell value; column by its header.",
    )
    def sap_read_table_cell(
        row_locator: Annotated[str, Field(description="Row number or a cell value in that row")],
        column_name: Annotated[str, Field(description="Column header title")],
    ) -> str:
        session.require_logged_in()
        try:
            value = session.execute("Read Table Cell", row_locator, column_name)
            return json.dumps({"row": row_locator, "column": column_name, "value": value})
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_fill_cell",
        description="Fill a table cell with a value. Identify by row locator and column name.",
    )
    def sap_fill_cell(
        row_locator: Annotated[str, Field(description="Row number or a cell value in that row")],
        column_name: Annotated[str, Field(description="Column header title")],
        value: Annotated[str, Field(description="Value to enter in the cell")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Fill Cell", row_locator, column_name, value)
            return _ok(f"Cell [{row_locator}, {column_name}] filled with '{value}'.")
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_double_click_cell",
        description="Double-click a table cell to open detail / trigger drill-down.",
    )
    def sap_double_click_cell(
        row_locator: Annotated[str, Field(description="Row number or a cell value in that row")],
        column_name: Annotated[str, Field(description="Column header title")],
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Double Click Cell", row_locator, column_name)
            title = session.execute("Get Window Title")
            return _ok(f"Double-clicked cell [{row_locator}, {column_name}].", window_title=title)
        except SAPError as exc:
            return _err(exc)

    @mcp.tool(
        name="sap_scroll_table",
        description="Scroll the SAP table up or down by a number of rows.",
    )
    def sap_scroll_table(
        direction: Annotated[Literal["down", "up"], Field(description="Scroll direction")],
        rows: Annotated[int, Field(default=1, ge=1, description="Number of rows to scroll")] = 1,
    ) -> str:
        session.require_logged_in()
        try:
            _run(session, config, "Scroll Table", direction, str(rows))
            return _ok(f"Table scrolled {direction} by {rows} row(s).")
        except SAPError as exc:
            return _err(exc)

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 7 — SCREENSHOT (opt-in: --caps screenshot)
    # ═══════════════════════════════════════════════════════════════════════════

    if config.cap_screenshot:

        @mcp.tool(
            name="sap_take_screenshot",
            description=(
                "Capture a screenshot of the current SAP window. "
                "Returns the image as base64 PNG and saves it to the output directory. "
                "Read-only — does not change SAP state."
            ),
        )
        def sap_take_screenshot(
            label: Annotated[
                str,
                Field(default="screenshot", description="Label prefix for the saved file"),
            ] = "screenshot",
        ) -> str:
            b64 = session.take_screenshot(label)
            if b64 is None:
                return "ERROR: Screenshot capture failed."
            out_dir = config.resolved_output_dir()
            return _ok(f"Screenshot captured and saved to {out_dir}.", base64_length=len(b64))

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 8 — CODE GENERATION (opt-in: --caps codegen)
    # ═══════════════════════════════════════════════════════════════════════════

    if config.cap_codegen:

        @mcp.tool(
            name="sap_get_generated_script",
            description=(
                "Return the Robot Framework test script accumulated from all actions "
                "performed so far in this session. Read-only."
            ),
        )
        def sap_get_generated_script() -> str:
            return session.get_script()

        @mcp.tool(
            name="sap_clear_script",
            description="Clear the accumulated Robot Framework script and start fresh.",
        )
        def sap_clear_script() -> str:
            session.clear_script()
            return _ok("Script buffer cleared.")

    # ═══════════════════════════════════════════════════════════════════════════
    # CATEGORY 9 — ADVANCED SNAPSHOT (opt-in: --caps advanced)
    # ═══════════════════════════════════════════════════════════════════════════

    if config.cap_advanced:

        @mcp.tool(
            name="sap_get_snapshot",
            description=(
                "Return a structured JSON snapshot of the current SAP window: "
                "window title, status bar, state. "
                "Use this to understand what's on screen before performing actions. "
                "Analogous to Playwright's browser_snapshot. Read-only."
            ),
        )
        def sap_get_snapshot() -> str:
            try:
                snap = session.get_snapshot()
                return json.dumps(snap, indent=2)
            except SAPError as exc:
                return _err(exc)

    return mcp
