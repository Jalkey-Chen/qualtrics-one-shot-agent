from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .schemas import RunConfig


def run_preflight(config: RunConfig, config_path: str | Path, official_url: str | None = None) -> list[str]:
    warnings: list[str] = []
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    if not Path(config_path).exists():
        raise RuntimeError(f"Config file does not exist: {config_path}")
    for prompt in ["prompts/system_prompt.txt", "prompts/page_prompt_template.txt"]:
        if not Path(prompt).exists():
            raise RuntimeError(f"Prompt file missing: {prompt}")
    if not Path(config.respondent_card_path).exists():
        raise RuntimeError(f"Respondent card missing: {config.respondent_card_path}")
    runs_dir = Path("runs")
    runs_dir.mkdir(exist_ok=True)
    probe = runs_dir / ".write_test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except PlaywrightError as exc:
        raise RuntimeError(f"Playwright Chromium is not installed or cannot launch: {exc}") from exc
    try:
        OpenAI().models.retrieve(config.model)
    except Exception as exc:
        warnings.append(f"Could not verify model availability for {config.model}: {exc}")
    if config.captcha.enabled and config.captcha.model != config.model:
        try:
            OpenAI().models.retrieve(config.captcha.model)
        except Exception as exc:
            warnings.append(f"Could not verify CAPTCHA model availability for {config.captcha.model}: {exc}")
    if config.run_mode == "official":
        warnings.append("Official mode: do not use official one-shot links for debugging; use the exact fixed config and preserve logs.")
        if official_url and ("localhost" in official_url or official_url.startswith("file:")):
            warnings.append("Official mode is set while URL appears local/mock.")
    return warnings
