from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .agent import DecisionAgent, LLMDecisionError
from .answer_validator import validate_plan
from .browser import BrowserSession
from .captcha import CaptchaResult, solve_captcha_if_present
from .executor import execute_plan
from .memory_ledger import create_initial_ledger, load_respondent_card, merge_memory_patch
from .page_parser import parse_page
from .pacing import action_interval, compute_page_delay, sleep_for_pacing
from .preflight import run_preflight
from .run_logger import RunLogger, utc_now_iso, visible_text_hash
from .run_report import write_run_report
from .schemas import ExecutionResult, RunConfig, SurveyPlan
from .survey_skills import select_skills


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an authorized one-shot Qualtrics-like survey agent.")
    parser.add_argument("--url", required=True, help="Survey URL. Do not commit official survey URLs.")
    parser.add_argument("--run-name", required=True, help="Name for this run, used in the runs/ directory.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml.")
    parser.add_argument(
        "--run-mode",
        choices=["debug", "practice", "official"],
        default=None,
        help="Optional override for config run_mode.",
    )
    return parser.parse_args(argv)


def load_config(path: str | Path) -> RunConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return RunConfig.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()

    logger = RunLogger(args.run_name)
    status = "error"
    stuck_reason: str | None = None
    final_url: str | None = None
    total_pages = 0
    total_captcha_llm_calls = 0
    agent: DecisionAgent | None = None
    config: RunConfig | None = None
    url_kind = _url_kind(args.url)
    preflight_warnings: list[str] = []

    try:
        config = load_config(args.config)
        if args.run_mode:
            config.run_mode = args.run_mode
        preflight_warnings = run_preflight(config, args.config, args.url)
        respondent_card = load_respondent_card(config.respondent_card_path)
        memory_ledger = create_initial_ledger(respondent_card)
        agent = DecisionAgent(config)

        with BrowserSession(config, logger.trace_path) as browser:
            if browser.page is None:
                raise RuntimeError("Browser page was not initialized")
            page = browser.page
            page.goto(args.url, wait_until="domcontentloaded", timeout=config.page_timeout_ms)
            page.wait_for_load_state("domcontentloaded")
            _wait_for_visible_survey_content(page, config.page_timeout_ms)

            validation_retry_count = 0
            for page_index in range(1, config.max_pages + 1):
                total_pages = page_index
                before_path = logger.screenshot_path(page_index, "before")
                after_path = logger.screenshot_path(page_index, "after")
                errors: list[str] = []
                llm_plan: dict[str, Any] | None = None
                plan_validation_errors: list[str] = []
                pacing_decision = None
                captcha_result = CaptchaResult(status="not_present", message="No CAPTCHA checked")

                _wait_for_visible_survey_content(page, config.page_timeout_ms)
                captcha_result = solve_captcha_if_present(page, config.captcha, logger.screenshot_dir, page_index)
                total_captcha_llm_calls += captcha_result.llm_calls
                if captcha_result.status == "solved":
                    _wait_for_visible_survey_content(page, config.page_timeout_ms)
                parsed = _parse_page_when_ready(page, config.page_timeout_ms)
                page.screenshot(path=str(before_path), full_page=True)
                final_url = parsed.url
                has_validation = bool(parsed.validation_messages or parsed.dialogs)
                validation_retry_count = validation_retry_count + 1 if has_validation else 0
                pacing_decision = compute_page_delay(parsed, config.pacing, validation_retry_count)
                sleep_for_pacing(pacing_decision)
                skills = select_skills(parsed)

                if captcha_result.status in {"failed", "unsupported"}:
                    stuck_reason = captcha_result.message
                    result = ExecutionResult(
                        status="stuck",
                        message=stuck_reason,
                        errors=captcha_result.errors or [stuck_reason],
                    )
                    plan = SurveyPlan(
                        status="stuck",
                        stuck_reason=stuck_reason,
                        answers=[],
                        next="stop",
                        memory_update=[],
                    )
                    errors.extend(result.errors)
                    llm_plan = plan.model_dump()
                elif _parsed_page_is_solved_captcha_gate(parsed, captcha_result):
                    plan = SurveyPlan(
                        status="answer",
                        stuck_reason=None,
                        answers=[],
                        next="click_next",
                        memory_update=[],
                        memory_patch={},
                    )
                    llm_plan = plan.model_dump()
                    result = execute_plan(page, plan, parsed, action_interval(config.pacing))
                    if result.errors:
                        errors.extend(result.errors)
                elif _parsed_page_is_continue_gate(parsed):
                    plan = SurveyPlan(
                        status="answer",
                        stuck_reason=None,
                        answers=[],
                        next="click_next",
                        memory_update=[],
                        memory_patch={},
                    )
                    llm_plan = plan.model_dump()
                    result = execute_plan(page, plan, parsed, action_interval(config.pacing))
                    if result.errors:
                        errors.extend(result.errors)
                elif validation_retry_count > 2:
                    stuck_reason = "Validation recovery exceeded retry limit"
                    result = ExecutionResult(status="stuck", message=stuck_reason, errors=[stuck_reason])
                    plan = SurveyPlan(status="stuck", stuck_reason=stuck_reason, answers=[], next="stop", memory_update=[])
                    errors.append(stuck_reason)
                    llm_plan = plan.model_dump()
                else:
                    try:
                        plan = agent.decide(parsed, memory_ledger, respondent_card, skills)
                        validation = validate_plan(plan, parsed)
                        if not validation.valid:
                            plan_validation_errors = validation.errors
                            plan = agent.repair_plan(
                                parsed,
                                plan,
                                validation.errors,
                                memory_ledger,
                                respondent_card,
                                skills,
                            )
                            validation = validate_plan(plan, parsed)
                            if not validation.valid:
                                plan_validation_errors = validation.errors
                                raise LLMDecisionError(
                                    "LLM plan failed validation after repair: "
                                    + "; ".join(validation.errors)
                                )
                        llm_plan = plan.model_dump()
                    except LLMDecisionError as exc:
                        stuck_reason = str(exc)
                        result = ExecutionResult(status="stuck", message=stuck_reason, errors=[stuck_reason])
                        plan = SurveyPlan(
                            status="stuck",
                            stuck_reason=stuck_reason,
                            answers=[],
                            next="stop",
                            memory_update=[],
                        )
                        errors.append(stuck_reason)
                    else:
                        result = execute_plan(page, plan, parsed, action_interval(config.pacing))
                        merge_memory_patch(memory_ledger, plan.memory_patch, plan.memory_update)
                        if result.errors:
                            errors.extend(result.errors)

                try:
                    page.screenshot(path=str(after_path), full_page=True)
                except Exception as exc:
                    errors.append(f"after screenshot failed: {exc}")

                logger.write_step(
                    {
                        "page_index": page_index,
                        "timestamp": utc_now_iso(),
                        "url": parsed.url,
                        "url_kind": url_kind,
                        "visible_text_hash": visible_text_hash(parsed.visible_text),
                        "parsed_fields": {
                            "fields": parsed.fields,
                            "groups": parsed.groups,
                            "next_button_candidates": parsed.next_button_candidates,
                            "validation_messages": parsed.validation_messages,
                            "dialogs": parsed.dialogs,
                            "matrices": parsed.matrices,
                        },
                        "run_mode": config.run_mode,
                        "pacing": {
                            "delay_seconds": pacing_decision.delay_seconds if pacing_decision else 0,
                            "reason": pacing_decision.reason if pacing_decision else "not computed",
                            "action_interval_seconds": action_interval(config.pacing),
                        },
                        "selected_skills": sorted(skills.keys()),
                        "validation_retry_count": validation_retry_count,
                        "captcha": {
                            "status": captcha_result.status,
                            "message": captcha_result.message,
                            "actions": captcha_result.actions,
                            "errors": captcha_result.errors,
                            "screenshots": captcha_result.screenshots,
                            "llm_calls": captcha_result.llm_calls,
                        },
                        "plan_validation_errors": plan_validation_errors,
                        "memory_ledger": memory_ledger,
                        "llm_plan": llm_plan,
                        "execution_result": result.model_dump(),
                        "errors": errors,
                        "screenshot_paths": {
                            "before": str(before_path),
                            "after": str(after_path),
                        },
                    }
                )

                if plan.status == "finished" or result.status == "finished":
                    status = "finished"
                    stuck_reason = None
                    final_url = page.url
                    break
                if plan.status == "stuck" or result.status == "stuck":
                    status = "stuck"
                    stuck_reason = plan.stuck_reason or result.message
                    final_url = page.url
                    break
            else:
                status = "stuck"
                stuck_reason = f"Reached max_pages={config.max_pages}"
                final_url = page.url

    except (ValidationError, OSError, RuntimeError, Exception) as exc:
        status = "error"
        stuck_reason = str(exc)
    finally:
        end_time = utc_now_iso()
        provider = config.provider if config else None
        model = config.model if config else None
        logger.write_final_state(status, stuck_reason)
        summary = {
            "run_name": args.run_name,
            "start_time": logger.start_time,
            "end_time": end_time,
            "status": status,
            "model": model,
            "provider": provider,
            "run_mode": config.run_mode if config else None,
            "total_pages": total_pages,
            "total_llm_calls": agent.total_llm_calls if agent else 0,
            "total_captcha_llm_calls": total_captcha_llm_calls,
            "estimated_cost_usd": None,
            "stuck_reason": stuck_reason,
            "final_url": final_url,
            "url_kind": url_kind,
            "pacing_enabled": config.pacing.enabled if config else None,
            "respondent_card_path": config.respondent_card_path if config else None,
            "preflight_warnings": preflight_warnings,
            "notes": "Authorized research run. API keys and official survey URLs are not stored in config.",
        }
        logger.write_summary(summary)
        write_run_report(
            logger.run_dir,
            summary,
            config,
            args.config,
            logger.screenshot_dir,
            logger.trace_path,
        )

    print(json.dumps({"status": status, "run_dir": str(logger.run_dir), "stuck_reason": stuck_reason}, indent=2))
    return 0 if status == "finished" else 1


def _url_kind(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return "mock_file"
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return "mock_local_http"
    return "external"


def _wait_for_visible_survey_content(page: Any, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const hasHiddenAncestor = (el) => {
                for (let node = el; node && node.nodeType === Node.ELEMENT_NODE; node = node.parentElement) {
                  if (node.getAttribute("aria-hidden") === "true") return true;
                  const style = window.getComputedStyle(node);
                  if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return true;
                }
                return false;
              };
              const visible = (el) => {
                if (!el || hasHiddenAncestor(el)) return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };
              const text = (document.body && document.body.innerText || "").replace(/\\s+/g, " ").trim();
              const controls = document.querySelectorAll("button,input,textarea,select,[role='button'],[role='radio'],[role='checkbox'],[role='combobox'],[aria-haspopup='listbox']");
              return text.length > 0 || [...controls].some(visible);
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass


def _parse_page_when_ready(page: Any, timeout_ms: int) -> Any:
    attempts = max(1, min(60, timeout_ms // 1000))
    parsed = parse_page(page)
    for _ in range(attempts):
        if not _parsed_page_looks_loading_or_empty(parsed):
            return parsed
        try:
            page.wait_for_load_state("domcontentloaded", timeout=1000)
        except PlaywrightTimeoutError:
            pass
        try:
            page.wait_for_timeout(1000)
        except Exception:
            pass
        parsed = parse_page(page)
    return parsed


def _parsed_page_looks_loading_or_empty(parsed: Any) -> bool:
    control_count = (
        len(parsed.fields)
        + len(parsed.groups)
        + len(parsed.next_button_candidates)
        + len(parsed.matrices)
        + len(parsed.validation_messages)
        + len(parsed.dialogs)
    )
    if control_count:
        return False
    text = " ".join((parsed.visible_text or "").lower().split())
    if not text:
        return True
    loading_markers = [
        "loading",
        "powered by qualtrics",
        "please wait",
    ]
    if len(text) < 40 and any(marker in text for marker in loading_markers):
        return True
    return False


def _parsed_page_is_continue_gate(parsed: Any) -> bool:
    text = " ".join((parsed.visible_text or "").lower().split())
    if not any(
        marker in text
        for marker in [
            "click the button to continue",
            "continue to the survey",
            "begin the survey",
            "start the survey",
        ]
    ):
        return False
    if parsed.next_button_candidates:
        return True
    for field in parsed.fields:
        field_text = str(field.get("text") or "").strip()
        if field.get("tag") == "button" and field_text in {"→", "➜", "➔", "›", ">"}:
            return True
    return False


def _parsed_page_is_solved_captcha_gate(parsed: Any, captcha_result: CaptchaResult) -> bool:
    if captcha_result.status != "solved":
        return False
    text = " ".join((parsed.visible_text or "").lower().split())
    if not any(marker in text for marker in ["captcha", "not a robot", "robot"]):
        return False
    if not parsed.next_button_candidates:
        return False
    if parsed.groups or parsed.matrices:
        return False
    for field in parsed.fields:
        field_type = str(field.get("type") or "").lower()
        tag = str(field.get("tag") or "").lower()
        if tag == "button" or field_type in {"button", "submit"}:
            continue
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
