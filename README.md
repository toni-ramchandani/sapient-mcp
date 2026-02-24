# SAPient MCP

> **Intelligent SAP GUI automation for AI agents**

A **production-ready Model Context Protocol (MCP) server** that enables LLMs (Claude, Copilot, Cursor, etc.) to automate **SAP GUI** using the [RoboSAPiens](https://github.com/imbus/robotframework-robosapiens) library.

### Compatible MCP Clients

| Client | Mode | Notes |
|---|---|---|
| **Claude Desktop** | stdio | Full support |
| **Claude Code** | stdio | Full support |
| **Cursor** | stdio or SSE | Full support |
| **VS Code (GitHub Copilot)** | stdio or SSE | Requires Copilot agent mode |
| **Windsurf** | stdio or SSE | Full support |
| **Any MCP client** | SSE/HTTP | Via `--port` flag |

---

## Prerequisites

| Requirement | Details |
|---|---|
| **OS** | Windows 10/11 only (SAP GUI is Windows-only) |
| **Python** | 3.10 or newer |
| **SAP GUI** | SAP GUI for Windows installed |
| **SAP Scripting** | Must be enabled on server (RZ11: `sapgui/user_scripting=TRUE`) AND in SAP Logon client settings |

### Enable SAP GUI Scripting (one-time setup)

1. Open SAP Logon → `Customize Local Layout (Alt+F12)` → `Options`
2. Go to `Accessibility & Scripting` → `Scripting`
3. ✅ Enable scripting
4. ❌ Disable "Notify when a script attaches to a running SAP GUI session"
5. ❌ Disable "Notify when a script opens a connection"
6. Ask BASIS admin to run transaction `RZ11` → set `sapgui/user_scripting` = `TRUE`

---

## Installation

```bash
# Clone the repo
git clone https://github.com/yourorg/sapient-mcp.git
cd sapient-mcp

# Install (using pip or uv)
pip install -e .

# Or with uv (recommended)
uv pip install -e .
```

---

## Quick Start

### Option A — stdio mode (local clients)

SAPient MCP works with **any MCP-compatible client**. Pick yours below.

---

#### Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sapient": {
      "command": "python",
      "args": ["-m", "sapient_mcp"],
      "env": {
        "SAPIENT_MCP_SAPLOGON_PATH": "C:\\Program Files (x86)\\SAP\\FrontEnd\\SAPgui\\saplogon.exe",
        "SAPIENT_MCP_CAPS": "screenshot,codegen,advanced",
        "SAPIENT_MCP_OUTPUT_DIR": "C:\\sapient_output"
      }
    }
  }
}
```

---

#### Claude Code (CLI)

```bash
claude mcp add sapient python -m sapient_mcp \
  -- --caps screenshot,codegen,advanced
```

Or edit `~/.claude/mcp.json` / `.claude/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "sapient": {
      "command": "python",
      "args": ["-m", "sapient_mcp", "--caps", "screenshot,codegen,advanced"],
      "env": {
        "SAPIENT_MCP_SAPLOGON_PATH": "C:\\Program Files (x86)\\SAP\\FrontEnd\\SAPgui\\saplogon.exe",
        "SAPIENT_MCP_OUTPUT_DIR": "C:\\sapient_output"
      }
    }
  }
}
```

---

#### Cursor

Go to `Cursor Settings` → `MCP` → `Add new MCP Server` → type `command`, then enter:

```
python -m sapient_mcp --caps screenshot,codegen,advanced
```

Or edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "sapient": {
      "command": "python",
      "args": ["-m", "sapient_mcp", "--caps", "screenshot,codegen,advanced"],
      "env": {
        "SAPIENT_MCP_SAPLOGON_PATH": "C:\\Program Files (x86)\\SAP\\FrontEnd\\SAPgui\\saplogon.exe",
        "SAPIENT_MCP_OUTPUT_DIR": "C:\\sapient_output"
      }
    }
  }
}
```

---

#### VS Code (GitHub Copilot)

Install the MCP server via VS Code CLI:

```bash
code --add-mcp '{"name":"sapient","command":"python","args":["-m","sapient_mcp","--caps","screenshot,codegen,advanced"]}'
```

Or add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "sapient": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "sapient_mcp", "--caps", "screenshot,codegen,advanced"],
      "env": {
        "SAPIENT_MCP_SAPLOGON_PATH": "C:\\Program Files (x86)\\SAP\\FrontEnd\\SAPgui\\saplogon.exe",
        "SAPIENT_MCP_OUTPUT_DIR": "C:\\sapient_output"
      }
    }
  }
}
```

---

#### Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "sapient": {
      "command": "python",
      "args": ["-m", "sapient_mcp", "--caps", "screenshot,codegen,advanced"],
      "env": {
        "SAPIENT_MCP_SAPLOGON_PATH": "C:\\Program Files (x86)\\SAP\\FrontEnd\\SAPgui\\saplogon.exe",
        "SAPIENT_MCP_OUTPUT_DIR": "C:\\sapient_output"
      }
    }
  }
}
```

---

> **Note:** In stdio mode, SAPient MCP **never writes to stdout or stderr** — all logs go to the log file only. This is required for clean JSON-RPC communication across all clients.

### Option B — SSE/HTTP mode (remote / CI / multi-user)

Best when the SAP machine is separate from where the AI client runs, or when
multiple developers want to share one SAPient instance.

Run the server on your Windows SAP machine:
```bash
python -m sapient_mcp --port 8765 --caps screenshot,codegen,advanced
```

Then point **any MCP client** at the HTTP endpoint:

```json
{
  "mcpServers": {
    "sapient": {
      "url": "http://sap-windows-machine:8765/mcp"
    }
  }
}
```

This works identically in Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, and any other MCP-compatible client.

### Option C — Config file

```bash
python -m sapient_mcp --config C:\sap_config.json
```

---

## Environment Variables

All settings can be provided as env vars with the `ROBOSAP_MCP_` prefix:

| Variable | Default | Description |
|---|---|---|
| `ROBOSAP_MCP_SAPLOGON_PATH` | `C:\...\saplogon.exe` | Path to SAP Logon executable |
| `ROBOSAP_MCP_SAP_SERVER` | `null` | Server description for auto-connect |
| `ROBOSAP_MCP_SAP_CLIENT` | `null` | SAP client for auto-login |
| `ROBOSAP_MCP_SAP_USER` | `null` | SAP user for auto-login |
| `ROBOSAP_MCP_SAP_PASSWORD` | `null` | SAP password (never logged) |
| `ROBOSAP_MCP_PORT` | `null` (stdio) | Port for SSE mode |
| `ROBOSAP_MCP_CAPS` | `""` | Comma-separated caps: screenshot,codegen,advanced |
| `ROBOSAP_MCP_OUTPUT_DIR` | `./sap_output` | Screenshots and logs directory |
| `ROBOSAP_MCP_SCREENSHOT_ON_ERROR` | `true` | Auto-screenshot on tool failures |

---

## Available Tools

### Core (always loaded)

| Tool | Description |
|---|---|
| `sap_open` | Launch SAP Logon |
| `sap_connect_to_server` | Connect to SAP server |
| `sap_connect_to_running` | Attach to running SAP session |
| `sap_get_session_info` | Read-only: current state & title |
| `sap_close` | Close SAP |
| `sap_execute_transaction` | Run a transaction code |
| `sap_activate_tab` | Click a tab by label |
| `sap_get_window_title` | Read-only: current window title |
| `sap_select_menu_item` | Navigate menu bar |
| `sap_send_key` | Send keyboard key (Enter, F3, etc.) |
| `sap_fill_text_field` | Fill a field by its label |
| `sap_clear_text_field` | Clear a field |
| `sap_set_checkbox` | Check a checkbox |
| `sap_unset_checkbox` | Uncheck a checkbox |
| `sap_select_radio_button` | Select a radio button |
| `sap_push_button` | Click a button by label |
| `sap_button_exists` | Read-only: check if button exists |
| `sap_read_text_field` | Read-only: read field value |
| `sap_read_text` | Read-only: read any text element |
| `sap_read_status_bar` | Read-only: SAP status bar message |
| `sap_count_table_rows` | Read-only: table row count |
| `sap_select_table_row` | Select a table row |
| `sap_read_table_cell` | Read-only: read a cell value |
| `sap_fill_cell` | Fill a table cell |
| `sap_double_click_cell` | Double-click a table cell |
| `sap_scroll_table` | Scroll table up/down |

### `--caps screenshot`

| Tool | Description |
|---|---|
| `sap_take_screenshot` | Capture SAP window screenshot |

### `--caps codegen`

| Tool | Description |
|---|---|
| `sap_get_generated_script` | Get accumulated Robot Framework script |
| `sap_clear_script` | Clear script buffer |

### `--caps advanced`

| Tool | Description |
|---|---|
| `sap_get_snapshot` | Structured JSON snapshot of current window |

---

## Example LLM Conversation

> **You:** Create a purchase order for vendor 100001, company code 1000, with 50 units of material ABC-001

SAPient will guide the LLM to:
1. Call `sap_execute_transaction("/nME21N")`
2. Call `sap_get_window_title()` → "Create Purchase Order"
3. Call `sap_fill_text_field("Vendor", "100001")`
4. Call `sap_fill_text_field("Company Code", "1000")`
5. Call `sap_send_key("Enter")` to accept header
6. Call `sap_activate_tab("Item Overview")`
7. Call `sap_fill_cell("1", "Material", "ABC-001")`
8. Call `sap_fill_cell("1", "Quantity", "50")`
9. Call `sap_push_button("Save")`
10. Call `sap_read_status_bar()` → "Purchase order 4500001234 created"

---

## Project Structure

```
sapient-mcp/
├── pyproject.toml
├── README.md
├── sap_config.json              # Example config file
├── claude_desktop_config.json   # Example Claude Desktop config
└── src/
    └── sapient_mcp/
        ├── __init__.py
        ├── __main__.py          # Entry point + CLI arg parsing
        ├── config.py            # Pydantic settings (env/file/CLI)
        ├── session.py           # SAPSessionManager singleton
        └── server.py            # FastMCP server + all 27 tool definitions
```

---

## Logs

Logs are written to `{output_dir}/sapient_mcp.log`.

In **stdio mode**, logs never go to stdout/stderr (would break JSON-RPC).
In **SSE mode**, logs also appear on stderr.
