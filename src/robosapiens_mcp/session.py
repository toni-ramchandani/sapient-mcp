"""
SAP Session Manager — the stateful core of SAPient MCP.

A single instance of this class is held for the lifetime of the MCP server
process. All tools operate on this shared session (mirrors how Playwright MCP
keeps one browser context alive across all tool calls).
"""
from __future__ import annotations

import base64
import logging
import textwrap
import threading
import time
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("sapient_mcp.session")


class SessionState(Enum):
    DISCONNECTED = auto()
    SAP_OPEN = auto()       # saplogon.exe launched, not yet connected
    CONNECTED = auto()      # Connected to server, at login screen
    LOGGED_IN = auto()      # Fully logged in, in SAP application


class SAPError(Exception):
    """Wrapper for SAP-level errors with structured info for LLM responses."""
    def __init__(self, message: str, hint: str = "", keyword: str = ""):
        super().__init__(message)
        self.hint = hint
        self.keyword = keyword

    def to_dict(self) -> dict:
        d = {"error": str(self), "keyword": self.keyword}
        if self.hint:
            d["hint"] = self.hint
        return d


class SAPSessionManager:
    """
    Singleton that owns the live RoboSAPiens library instance.

    Usage:
        session = SAPSessionManager.instance()
        session.execute("Fill Text Field", "User", "my_user")
    """

    _singleton: Optional["SAPSessionManager"] = None
    _lock = threading.Lock()

    def __init__(self, output_dir: Path):
        self._lib = None          # RoboSAPiens library instance (lazy)
        self._state = SessionState.DISCONNECTED
        self._server_description: Optional[str] = None
        self._output_dir = output_dir
        self._script_lines: list[str] = []   # For code generation
        self._script_lock = threading.Lock()

    # ── Singleton ─────────────────────────────────────────────────────────────
    @classmethod
    def instance(cls) -> "SAPSessionManager":
        if cls._singleton is None:
            raise RuntimeError("SAPSessionManager not initialised. Call SAPSessionManager.create() first.")
        return cls._singleton

    @classmethod
    def create(cls, output_dir: Path) -> "SAPSessionManager":
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls(output_dir)
                log.info("SAPSessionManager created, output_dir=%s", output_dir)
        return cls._singleton

    # ── Library access ────────────────────────────────────────────────────────
    def _get_lib(self):
        """Lazy-initialise the RoboSAPiens library instance."""
        if self._lib is None:
            try:
                from RoboSAPiens import RoboSAPiens  # noqa: PLC0415
                self._lib = RoboSAPiens()
                log.info("RoboSAPiens library instantiated")
            except ImportError as e:
                raise SAPError(
                    "RoboSAPiens library not found",
                    hint="Run: pip install robotframework-robosapiens",
                    keyword="import",
                ) from e
        return self._lib

    # ── Core executor ─────────────────────────────────────────────────────────
    def execute(self, keyword: str, *args: Any) -> Any:
        """
        Execute a RoboSAPiens keyword by its Python method name (snake_case).

        RoboSAPiens keyword "Fill Text Field" → method fill_text_field
        All exceptions are caught and re-raised as SAPError with context.
        """
        lib = self._get_lib()
        method_name = keyword.lower().replace(" ", "_")
        method = getattr(lib, method_name, None)
        if method is None:
            raise SAPError(
                f"Unknown RoboSAPiens keyword: '{keyword}'",
                hint=f"No method '{method_name}' on RoboSAPiens library.",
                keyword=keyword,
            )
        log.debug("EXEC  %-35s  args=%s", keyword, args)
        try:
            result = method(*args)
            log.debug("DONE  %-35s  result=%s", keyword, str(result)[:120])
            return result
        except Exception as exc:
            err_msg = str(exc)
            hint = _extract_hint(err_msg)
            log.warning("FAIL  %-35s  error=%s", keyword, err_msg)
            raise SAPError(err_msg, hint=hint, keyword=keyword) from exc

    # ── State helpers ─────────────────────────────────────────────────────────
    @property
    def state(self) -> SessionState:
        return self._state

    def set_state(self, state: SessionState) -> None:
        log.info("State transition: %s → %s", self._state.name, state.name)
        self._state = state

    def is_connected(self) -> bool:
        return self._state in (SessionState.CONNECTED, SessionState.LOGGED_IN)

    def is_logged_in(self) -> bool:
        return self._state == SessionState.LOGGED_IN

    def require_connected(self) -> None:
        if not self.is_connected():
            raise SAPError(
                "No active SAP connection",
                hint="Call sap_open → sap_connect_to_server (or sap_connect_to_running) first.",
            )

    def require_logged_in(self) -> None:
        if not self.is_logged_in():
            raise SAPError(
                "Not logged in to SAP",
                hint="Complete login with sap_fill_text_field / sap_push_button, then the session auto-detects login.",
            )

    # ── Screenshot ────────────────────────────────────────────────────────────
    def take_screenshot(self, label: str = "screenshot") -> Optional[str]:
        """Capture SAP window screenshot; returns base64 PNG or None on failure."""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = self._output_dir / f"{label}_{ts}.png"
            self.execute("Save Screenshot", str(fname))
            data = fname.read_bytes()
            log.debug("Screenshot saved: %s (%d bytes)", fname, len(data))
            return base64.b64encode(data).decode()
        except Exception as exc:
            log.warning("Screenshot failed: %s", exc)
            return None

    # ── Code generation ───────────────────────────────────────────────────────
    def record(self, keyword: str, *args: Any) -> None:
        """Append an action to the generated Robot Framework script."""
        arg_str = "    ".join(str(a) for a in args)
        line = f"    {keyword}    {arg_str}" if arg_str else f"    {keyword}"
        with self._script_lock:
            self._script_lines.append(line)

    def get_script(self) -> str:
        """Return the accumulated Robot Framework test script."""
        with self._script_lock:
            if not self._script_lines:
                return "# No actions recorded yet."
            body = "\n".join(self._script_lines)
        return textwrap.dedent(f"""\
            *** Settings ***
            Library    RoboSAPiens

            *** Test Cases ***
            Generated SAP Automation
            {body}
        """)

    def clear_script(self) -> None:
        with self._script_lock:
            self._script_lines.clear()

    # ── Snapshot (element inspection) ─────────────────────────────────────────
    def get_snapshot(self) -> dict:
        """
        Build a structured JSON snapshot of the current SAP window.
        Gives the LLM visibility into what's on-screen before acting.
        Returns a dict with: window_title, fields, buttons, tabs, status_bar.
        """
        self.require_logged_in()
        snapshot: dict[str, Any] = {
            "window_title": None,
            "fields": [],
            "buttons": [],
            "tabs": [],
            "status_bar": None,
            "state": self._state.name,
        }
        # Window title
        try:
            snapshot["window_title"] = self.execute("Get Window Title")
        except SAPError:
            pass

        # Status bar
        try:
            snapshot["status_bar"] = self.execute("Read Status Bar")
        except SAPError:
            pass

        # NOTE: RoboSAPiens does not expose a direct "list all elements" API.
        # The snapshot above gives essential context. For full element listing,
        # the 'advanced' cap would need a deeper integration with the SAP COM
        # session object directly. This base snapshot is sufficient for LLM
        # decision-making in most cases.
        return snapshot


# ── Private helpers ────────────────────────────────────────────────────────────

def _extract_hint(error_msg: str) -> str:
    """Parse common RoboSAPiens error messages into actionable hints."""
    msg = error_msg.lower()
    if "not found" in msg:
        return (
            "Element not found. Check: (1) spelling of the label, "
            "(2) the correct tab is active, "
            "(3) call sap_get_window_title to confirm you are on the right screen."
        )
    if "scripting" in msg:
        return (
            "SAP GUI scripting is not enabled. "
            "Enable it in SAP Logon → Customize Local Layout (Alt+F12) → Options → Scripting, "
            "AND ask BASIS to set sapgui/user_scripting=TRUE via RZ11."
        )
    if "connection" in msg or "server" in msg:
        return (
            "Connection failed. Check: (1) SAP Logon is open, "
            "(2) the server description matches exactly what appears in SAP Logon list, "
            "(3) network connectivity to SAP."
        )
    if "password" in msg or "login" in msg:
        return "Login failed. Verify credentials. Check for password expiry or account lock."
    return ""
