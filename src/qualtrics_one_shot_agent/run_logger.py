from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def visible_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return safe.strip("._") or "run"


class RunLogger:
    def __init__(self, run_name: str, runs_root: str | Path = "runs") -> None:
        self.run_name = run_name
        self.start_time = utc_now_iso()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = Path(runs_root) / f"{stamp}_{_safe_name(run_name)}"
        self.screenshot_dir = self.run_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=False)
        self.steps_path = self.run_dir / "steps.jsonl"
        self.summary_path = self.run_dir / "summary.json"
        self.final_state_path = self.run_dir / "final_state.txt"
        self.trace_path = self.run_dir / "trace.zip"

    def screenshot_path(self, page_index: int, phase: str) -> Path:
        return self.screenshot_dir / f"page_{page_index:03d}_{phase}.png"

    def write_step(self, step: dict[str, Any]) -> None:
        with self.steps_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(step, ensure_ascii=False, default=str) + "\n")

    def write_final_state(self, status: str, reason: str | None = None) -> None:
        text = status if not reason else f"{status}\n{reason}"
        self.final_state_path.write_text(text, encoding="utf-8")

    def write_summary(self, summary: dict[str, Any]) -> None:
        self.summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
