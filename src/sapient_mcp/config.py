"""
Configuration for SAPient MCP Server.
All options are readable from:
  1. CLI arguments (via __main__.py)
  2. Environment variables (prefixed SAPIENT_MCP_)
  3. .env file in working directory
  4. JSON config file (--config path/to/config.json)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RoboSAPiensMCPConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SAPIENT_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── SAP Connection ────────────────────────────────────────────────────────
    saplogon_path: str = Field(
        default=r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe",
        description="Full path to saplogon.exe",
    )
    sap_server: Optional[str] = Field(
        default=None,
        description="SAP server description from SAP Logon (auto-connect on startup)",
    )
    sap_client: Optional[str] = Field(
        default=None,
        description="SAP client number (e.g. '100')",
    )
    sap_user: Optional[str] = Field(
        default=None,
        description="SAP username for auto-login",
    )
    sap_password: Optional[str] = Field(
        default=None,
        description="SAP password for auto-login (never logged)",
    )

    # ── Server transport ──────────────────────────────────────────────────────
    port: Optional[int] = Field(
        default=None,
        description="Port for SSE/HTTP transport. If None, stdio is used.",
    )
    host: str = Field(
        default="localhost",
        description="Host to bind to when using SSE transport",
    )

    # ── Capabilities (opt-in feature sets) ────────────────────────────────────
    caps: list[str] = Field(
        default_factory=list,
        description="Extra capability sets: screenshot, codegen, advanced",
    )

    # ── Behaviour ─────────────────────────────────────────────────────────────
    screenshot_on_error: bool = Field(
        default=True,
        description="Automatically capture screenshot on tool failure",
    )
    output_dir: str = Field(
        default="./sap_output",
        description="Directory for screenshots and generated scripts",
    )
    log_file: str = Field(
        default="sapient_mcp.log",
        description="Log file path (relative to output_dir)",
    )
    # codegen language
    codegen_language: Literal["robot", "none"] = Field(
        default="robot",
        description="Language for code generation output",
    )

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("caps", mode="before")
    @classmethod
    def parse_caps(cls, v):
        """
        Accept any of these formats from env vars or config files:
          - comma string : "screenshot,codegen,advanced"
          - JSON array   : ["screenshot","codegen","advanced"]
          - Python list  : already a list
        """
        if isinstance(v, list):
            return [c.strip() for c in v if c.strip()]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            # Try JSON array first e.g. '["screenshot","codegen"]'
            if v.startswith("["):
                import json
                try:
                    parsed = json.loads(v)
                    return [c.strip() for c in parsed if c.strip()]
                except json.JSONDecodeError:
                    pass
            # Fall back to comma-separated string
            return [c.strip() for c in v.split(",") if c.strip()]
        return v

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def cap_screenshot(self) -> bool:
        return "screenshot" in self.caps

    @property
    def cap_codegen(self) -> bool:
        return "codegen" in self.caps

    @property
    def cap_advanced(self) -> bool:
        return "advanced" in self.caps

    def resolved_output_dir(self) -> Path:
        p = Path(self.output_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolved_log_file(self) -> Path:
        return self.resolved_output_dir() / self.log_file


def load_config(config_file: Optional[str] = None, **overrides) -> RoboSAPiensMCPConfig:
    """
    Load config from env/defaults, then overlay JSON file values,
    then overlay any explicit CLI overrides passed as kwargs.
    """
    base = RoboSAPiensMCPConfig()

    if config_file:
        path = Path(config_file)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        with open(path) as f:
            file_data = json.load(f)
        # Re-instantiate with file values merged
        base = RoboSAPiensMCPConfig(**{**base.model_dump(), **file_data})

    if overrides:
        base = RoboSAPiensMCPConfig(**{**base.model_dump(), **overrides})

    return base