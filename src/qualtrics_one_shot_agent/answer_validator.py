from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schemas import ParsedPage, SurveyAnswer, SurveyPlan


@dataclass
class PlanValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_plan(plan: SurveyPlan, parsed_page: ParsedPage) -> PlanValidationResult:
    errors: list[str] = []
    visible_options = _visible_options(parsed_page)
    visible_text = _norm(parsed_page.visible_text)
    text_lower = parsed_page.visible_text.lower()
    has_unexpanded_select = any(
        group.get("kind") in {"select", "custom_select"} and not group.get("options")
        for group in parsed_page.groups
    )

    for answer in plan.answers:
        if answer.answer_type in {"single_choice", "select"}:
            _validate_option(answer, visible_options, visible_text, has_unexpanded_select, errors)
        elif answer.answer_type == "multi_choice":
            _validate_multi_choice(answer, visible_options, visible_text, text_lower, errors)
        elif answer.answer_type == "matrix":
            _validate_matrix(answer, parsed_page, errors)
        elif answer.answer_type in {"number", "slider"}:
            _validate_number(answer, parsed_page, errors)
        elif answer.answer_type == "rank":
            _validate_rank(answer, errors)
        elif answer.answer_type == "text":
            _validate_text(answer, parsed_page, errors)

    return PlanValidationResult(valid=not errors, errors=errors)


def _visible_options(parsed_page: ParsedPage) -> set[str]:
    options: set[str] = set()
    for group in parsed_page.groups:
        for option in group.get("options", []) or []:
            if isinstance(option, dict):
                text = option.get("text") or option.get("value")
            else:
                text = option
            if text:
                options.add(_norm(str(text)))
    for field in parsed_page.fields:
        text = field.get("text")
        if text and len(str(text)) <= 120:
            options.add(_norm(str(text)))
    return options


def _validate_option(
    answer: SurveyAnswer,
    options: set[str],
    visible_text: str,
    has_unexpanded_select: bool,
    errors: list[str],
) -> None:
    if not options and not visible_text:
        return
    wanted = _norm(str(answer.answer))
    if _matches_visible(wanted, options) or _appears_in_visible_text(wanted, visible_text):
        return
    # Closed Qualtrics-style dropdowns often expose only "Select one" until clicked.
    # Let the executor open and choose from them instead of forcing an early STUCK.
    if answer.answer_type == "select" and has_unexpanded_select:
        return
    if answer.answer_type == "single_choice" and has_unexpanded_select and _looks_like_select_answer(str(answer.answer)):
        return
    if options:
        errors.append(f"Answer option not visible for '{answer.question_id_or_text}': {answer.answer}")


def _validate_multi_choice(
    answer: SurveyAnswer,
    options: set[str],
    visible_text: str,
    text_lower: str,
    errors: list[str],
) -> None:
    if not isinstance(answer.answer, list) or not answer.answer:
        errors.append(f"multi_choice requires a non-empty list for '{answer.question_id_or_text}'")
        return
    exact_two = any(phrase in text_lower for phrase in ["select exactly two", "choose exactly two", "pick exactly two"])
    if exact_two and len(answer.answer) != 2:
        errors.append(f"Instruction requires exactly two choices for '{answer.question_id_or_text}'")
    if options:
        for item in answer.answer:
            wanted = _norm(str(item))
            if not _matches_visible(wanted, options) and not _appears_in_visible_text(wanted, visible_text):
                errors.append(f"multi_choice option not visible for '{answer.question_id_or_text}': {item}")


def _validate_matrix(answer: SurveyAnswer, parsed_page: ParsedPage, errors: list[str]) -> None:
    if not isinstance(answer.answer, dict):
        errors.append(f"matrix answer must be an object for '{answer.question_id_or_text}'")
        return
    rows = []
    for matrix in parsed_page.matrices:
        rows.extend(row for row in matrix.get("rows", []) if row and row.lower() not in {"statement", "institution"})
    if rows:
        answered = {_norm(key) for key in answer.answer.keys()}
        for row in rows:
            if not any(_norm(row) == item or _norm(row) in item or item in _norm(row) for item in answered):
                errors.append(f"matrix missing row answer: {row}")


def _validate_number(answer: SurveyAnswer, parsed_page: ParsedPage, errors: list[str]) -> None:
    values = _number_values(answer.answer)
    if not values:
        errors.append(f"number answer has no numeric value for '{answer.question_id_or_text}'")
        return
    text = parsed_page.visible_text.lower()
    if ("100 points" in text or "allocate" in text) and isinstance(answer.answer, dict):
        total = sum(value for key, value in answer.answer.items() if str(key).strip().lower() != "total" for value in [_to_number(value)] if value is not None)
        if round(total, 6) != 100:
            errors.append(f"constant-sum answer must total 100 for '{answer.question_id_or_text}', got {total}")
    ranges = [(group.get("min"), group.get("max")) for group in parsed_page.groups if group.get("kind") in {"number_input", "range_slider"}]
    for value in values:
        for raw_min, raw_max in ranges:
            min_value = _to_number(raw_min)
            max_value = _to_number(raw_max)
            if min_value is not None and value < min_value:
                errors.append(f"numeric answer below min {min_value}: {value}")
            if max_value is not None and value > max_value:
                errors.append(f"numeric answer above max {max_value}: {value}")


def _validate_rank(answer: SurveyAnswer, errors: list[str]) -> None:
    items = answer.answer if isinstance(answer.answer, list) else list(answer.answer.keys()) if isinstance(answer.answer, dict) else []
    normalized = [_norm(str(item)) for item in items]
    if not normalized:
        errors.append(f"rank answer requires ordered items for '{answer.question_id_or_text}'")
    if len(normalized) != len(set(normalized)):
        errors.append(f"rank answer contains repeated items for '{answer.question_id_or_text}'")


def _validate_text(answer: SurveyAnswer, parsed_page: ParsedPage, errors: list[str]) -> None:
    text = str(answer.answer).strip()
    if not text:
        errors.append(f"text answer is empty for '{answer.question_id_or_text}'")
    exact = re.search(r'(?:enter|type|input)\s+(?:the\s+)?(?:word|text|phrase)\s+"([^"]+)"', parsed_page.visible_text, re.IGNORECASE)
    if exact and text != exact.group(1):
        errors.append(f"text answer must exactly match requested text: {exact.group(1)}")


def _number_values(value: Any) -> list[float]:
    if isinstance(value, dict):
        return [number for key, item in value.items() if str(key).strip().lower() != "total" for number in [_to_number(item)] if number is not None]
    if isinstance(value, list):
        return [number for item in value for number in [_to_number(item)] if number is not None]
    number = _to_number(value)
    return [number] if number is not None else []


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _matches_visible(wanted: str, candidates: set[str]) -> bool:
    return any(wanted == option or wanted in option or option in wanted for option in candidates)


def _appears_in_visible_text(wanted: str, visible_text: str) -> bool:
    if not wanted or not visible_text:
        return False
    if len(wanted) <= 3:
        return re.search(rf"(?<![\w-]){re.escape(wanted)}(?![\w-])", visible_text) is not None
    return wanted in visible_text


def _looks_like_select_answer(value: str) -> bool:
    text = _norm(value)
    select_like_markers = [
        "degree",
        "college",
        "school",
        "employed",
        "worker",
        "student",
        "retired",
        "self-employed",
        "full-time",
        "part-time",
    ]
    return any(marker in text for marker in select_like_markers)
