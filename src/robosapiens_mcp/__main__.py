"""
Entry point for SAPient MCP Server.

Usage examples:
    # stdio (default, for Claude Desktop / Claude Code)
    python -m sapient_mcp

    # SSE/HTTP mode (for remote control, e.g. from non-Windows machine)
    python -m sapient_mcp --port 8765

    # With config file
    python -m sapient_mcp --config C:\\sap_config.json

    # With capabilities and auto-connect
    python -m sapient_mcp --caps screenshot,codegen --sap-server "My Dev System"

    # As installed script
    sapient-mcp --port 8765 --caps screenshot,codegen,advanced
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _setup_logging(log_file: Path) -> None:
    """
    In stdio mode ALL stdout/stderr must be clean JSON-RPC.
    Therefore logs go to a file only.
    In SSE mode logs can also go to stderr — we handle both.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    # Only add stderr handler in non-stdio (HTTP/SSE) mode
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    for noisy in ("asyncio", "mcp", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sapient-mcp",
        description="SAPient MCP Server — Intelligent SAP GUI automation for AI agents",
    )
    p.add_argument("--config", metavar="PATH", help="Path to JSON config file")
    p.add_argument("--port", type=int, metavar="N", help="Port for SSE/HTTP transport (default: stdio)")
    p.add_argument("--host", default=None, metavar="HOST", help="Host to bind to (default: localhost)")
    p.add_argument(
        "--caps",
        default=None,
        metavar="CAPS",
        help="Comma-separated capabilities: screenshot,codegen,advanced",
    )
    p.add_argument("--saplogon-path", default=None, metavar="PATH", help="Path to saplogon.exe")
    p.add_argument("--sap-server", default=None, metavar="DESC", help="SAP server description for auto-connect")
    p.add_argument("--output-dir", default=None, metavar="DIR", help="Directory for screenshots and logs")
    p.add_argument("--no-screenshot-on-error", action="store_true", help="Disable auto-screenshot on tool failure")
    p.add_argument("--version", action="version", version="sapient-mcp 1.0.0")
    return p


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    # ── Build overrides dict from CLI args ────────────────────────────────────
    overrides: dict = {}
    if args.port is not None:
        overrides["port"] = args.port
    if args.host is not None:
        overrides["host"] = args.host
    if args.caps is not None:
        overrides["caps"] = [c.strip() for c in args.caps.split(",") if c.strip()]
    if args.saplogon_path is not None:
        overrides["saplogon_path"] = args.saplogon_path
    if args.sap_server is not None:
        overrides["sap_server"] = args.sap_server
    if args.output_dir is not None:
        overrides["output_dir"] = args.output_dir
    if args.no_screenshot_on_error:
        overrides["screenshot_on_error"] = False

    # ── Load config ───────────────────────────────────────────────────────────
    from .config import load_config  # noqa: PLC0415
    try:
        config = load_config(config_file=args.config, **overrides)
    except FileNotFoundError as exc:
        print(f"[sapient-mcp] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(config.resolved_log_file())
    log = logging.getLogger("sapient_mcp")

    # Add stderr handler if we're in SSE mode (port is set)
    if config.port:
        logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))

    log.info("=" * 60)
    log.info("SAPient MCP Server starting")
    log.info("  Transport : %s", f"SSE/HTTP :{config.port}" if config.port else "stdio")
    log.info("  Caps      : %s", config.caps or "(core only)")
    log.info("  Output    : %s", config.resolved_output_dir())
    log.info("  SAP path  : %s", config.saplogon_path)
    if config.sap_server:
        log.info("  Auto-connect server: %s", config.sap_server)
    log.info("=" * 60)

    # ── Initialise session manager ────────────────────────────────────────────
    from .session import SAPSessionManager  # noqa: PLC0415
    SAPSessionManager.create(config.resolved_output_dir())

    from .server import build_server  # noqa: PLC0415
    mcp = build_server(config)

    # ── Auto-connect if configured ────────────────────────────────────────────
    if config.sap_server:
        _auto_connect(config, log)

    # ── Run ───────────────────────────────────────────────────────────────────
    if config.port:
        log.info("Starting SSE server on %s:%d", config.host, config.port)
        mcp.run(transport="sse", host=config.host, port=config.port)
    else:
        log.info("Starting stdio server")
        mcp.run(transport="stdio")


def _auto_connect(config, log) -> None:
    """
    Optionally auto-open SAP and connect if sap_server is configured.
    Failures here are logged as warnings — the server still starts.
    """
    from .session import SAPError, SAPSessionManager, SessionState  # noqa: PLC0415
    session = SAPSessionManager.instance()
    try:
        log.info("Auto-connecting to SAP server: %s", config.sap_server)
        session.execute("Open SAP", config.saplogon_path)
        session.set_state(SessionState.SAP_OPEN)
        session.execute("Connect To Server", config.sap_server)
        session.set_state(SessionState.CONNECTED)
        log.info("Auto-connect successful. SAP login screen is ready.")

        # Auto-login if credentials are provided
        if config.sap_client and config.sap_user and config.sap_password:
            session.execute("Fill Text Field", "Client", config.sap_client)
            session.execute("Fill Text Field", "User", config.sap_user)
            session.execute("Fill Text Field", "Password", config.sap_password)
            session.execute("Send SAP Keys", "Enter")
            session.set_state(SessionState.LOGGED_IN)
            log.info("Auto-login completed as user '%s'.", config.sap_user)

    except SAPError as exc:
        log.warning("Server is still running — use sap_open / sap_connect_to_server tools manually.")


if __name__ == "__main__":
    main()
