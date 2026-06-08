from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from .schemas import RunConfig


def write_run_report(
    run_dir: Path,
    summary: dict[str, Any],
    config: RunConfig | None,
    config_path: str | Path,
    screenshot_dir: Path,
    trace_path: Path,
) -> None:
    report = [
        "# Run Report",
        "",
        f"- Run name: {summary.get('run_name')}",
        f"- URL kind: {summary.get('url_kind')}",
        f"- Provider/model: {summary.get('provider')} / {summary.get('model')}",
        f"- Start time: {summary.get('start_time')}",
        f"- End time: {summary.get('end_time')}",
        f"- Status: {summary.get('status')}",
        f"- Total pages: {summary.get('total_pages')}",
        f"- Total LLM calls: {summary.get('total_llm_calls')}",
        f"- Total CAPTCHA LLM calls: {summary.get('total_captcha_llm_calls')}",
        f"- Stuck reason: {summary.get('stuck_reason')}",
        f"- Screenshots path: {screenshot_dir}",
        f"- Trace path: {trace_path}",
        f"- Config hash: {_file_hash(config_path)}",
        f"- Git commit: {_git_commit()}",
        f"- Python version: {sys.version.split()[0]}",
        f"- OS: {platform.platform()}",
        f"- Dependencies: pyproject.toml + uv.lock",
        "",
        "## Pacing",
        "",
        f"- Pacing enabled: {config.pacing.enabled if config else None}",
        "- Settings:",
        "",
        "```yaml",
        yaml.safe_dump(config.pacing.model_dump(), sort_keys=True).strip() if config else "unavailable",
        "```",
        "",
        "## CAPTCHA",
        "",
        f"- Enabled: {config.captcha.enabled if config else None}",
        f"- Model: {config.captcha.model if config else None}",
        f"- Max attempts: {config.captcha.max_attempts if config else None}",
        "",
        "## Reproducibility Notes",
        "",
        "- LLM outputs are nondeterministic even with a fixed respondent card and config.",
        "- API keys and official survey URLs are not stored in the repository.",
        "- This artifact does not include proxying, stealth, device spoofing, or hidden-field manipulation.",
    ]
    (run_dir / "run_report.md").write_text("\n".join(report), encoding="utf-8")


def _file_hash(path: str | Path) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return None
