from __future__ import annotations

import time
from dataclasses import dataclass

from .schemas import ParsedPage, PacingConfig


@dataclass
class PacingDecision:
    delay_seconds: float
    reason: str


def compute_page_delay(parsed_page: ParsedPage, config: PacingConfig, validation_retry_count: int = 0) -> PacingDecision:
    if not config.enabled:
        return PacingDecision(0.0, "pacing disabled")
    word_count = len(parsed_page.visible_text.split())
    question_count = _estimate_question_count(parsed_page)
    matrix_rows = sum(len(matrix.get("rows", [])) for matrix in parsed_page.matrices)
    open_ended = sum(1 for group in parsed_page.groups if group.get("kind") in {"text_input", "number_input"})
    delay = config.base_page_delay_seconds
    delay += (word_count / 100.0) * config.per_100_words_delay_seconds
    delay += question_count * config.per_question_delay_seconds
    delay += matrix_rows * config.matrix_row_delay_seconds
    delay += open_ended * config.open_ended_delay_seconds
    if validation_retry_count:
        delay += config.validation_recovery_delay_seconds
    delay = min(delay, config.max_page_delay_seconds)
    reason = (
        f"transparent cognitive pacing: words={word_count}, questions={question_count}, "
        f"matrix_rows={matrix_rows}, open_ended={open_ended}, validation_retry={validation_retry_count}"
    )
    return PacingDecision(round(delay, 3), reason)


def sleep_for_pacing(decision: PacingDecision) -> None:
    if decision.delay_seconds > 0:
        time.sleep(decision.delay_seconds)


def action_interval(config: PacingConfig) -> float:
    return config.action_interval_seconds if config.enabled else 0.0


def _estimate_question_count(parsed_page: ParsedPage) -> int:
    group_count = len(parsed_page.groups)
    matrix_count = len(parsed_page.matrices)
    question_marks = parsed_page.visible_text.count("?")
    return max(group_count + matrix_count, question_marks)

