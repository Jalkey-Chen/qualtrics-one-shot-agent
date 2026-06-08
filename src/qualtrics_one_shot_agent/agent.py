from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI
from pydantic import ValidationError

from .schemas import ParsedPage, RunConfig, SurveyPlan


class LLMDecisionError(Exception):
    pass


class DecisionAgent:
    def __init__(
        self,
        config: RunConfig,
        system_prompt_path: str | Path = "prompts/system_prompt.txt",
        page_prompt_template_path: str | Path = "prompts/page_prompt_template.txt",
    ) -> None:
        self.config = config
        self.client = OpenAI()
        self.system_prompt = Path(system_prompt_path).read_text(encoding="utf-8")
        self.page_prompt_template = Path(page_prompt_template_path).read_text(encoding="utf-8")
        self.total_llm_calls = 0

    def decide(
        self,
        parsed_page: ParsedPage,
        memory: dict[str, Any],
        respondent_card: dict[str, Any] | None = None,
        skills: dict[str, str] | None = None,
    ) -> SurveyPlan:
        prompt = self._render_page_prompt(parsed_page, memory, respondent_card or {}, skills or {})
        raw = self._call(prompt)
        try:
            return SurveyPlan.model_validate_json(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
            repair_prompt = (
                "Repair the JSON to match the schema. Return only valid JSON. "
                "Do not add markdown or explanation.\n\n"
                f"Schema example:\n{self._schema_example()}\n\n"
                f"Invalid JSON or invalid object:\n{raw}\n\n"
                f"Validation error:\n{first_error}"
            )
            repaired = self._call(repair_prompt)
            try:
                return SurveyPlan.model_validate_json(repaired)
            except (ValidationError, ValueError, json.JSONDecodeError) as second_error:
                raise LLMDecisionError(f"LLM returned invalid JSON after repair: {second_error}") from second_error

    def repair_plan(
        self,
        parsed_page: ParsedPage,
        invalid_plan: SurveyPlan,
        validation_errors: list[str],
        memory: dict[str, Any],
        respondent_card: dict[str, Any] | None = None,
        skills: dict[str, str] | None = None,
    ) -> SurveyPlan:
        prompt = (
            "Repair the JSON survey plan so it satisfies the validator errors. "
            "Return only valid JSON in the same schema. Preserve good answers when possible.\n\n"
            f"Validator errors:\n{json.dumps(validation_errors, ensure_ascii=False, indent=2)}\n\n"
            f"Current invalid plan:\n{invalid_plan.model_dump_json(indent=2)}\n\n"
            f"Page context:\n{self._render_page_prompt(parsed_page, memory, respondent_card or {}, skills or {})}"
        )
        raw = self._call(prompt)
        try:
            return SurveyPlan.model_validate_json(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise LLMDecisionError(f"LLM returned invalid repaired plan: {exc}") from exc

    def _call(self, user_prompt: str) -> str:
        try:
            response = self._create_chat_completion(user_prompt, include_temperature=True)
        except Exception as exc:
            if _is_temperature_rejection(exc):
                try:
                    response = self._create_chat_completion(user_prompt, include_temperature=False)
                except Exception as retry_exc:
                    raise LLMDecisionError(f"OpenAI API error: {retry_exc}") from retry_exc
            else:
                raise LLMDecisionError(f"OpenAI API error: {exc}") from exc

        return self._extract_chat_text(response).strip()

    def _create_chat_completion(self, user_prompt: str, include_temperature: bool) -> Any:
        self.total_llm_calls += 1
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if include_temperature:
            request["temperature"] = self.config.temperature
        return self.client.chat.completions.create(**request)

    @staticmethod
    def _extract_chat_text(response: Any) -> str:
        choices = getattr(response, "choices", []) or []
        if choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                chunks = [
                    str(part.get("text"))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
                ]
                if chunks:
                    return "\n".join(chunks)
        raise LLMDecisionError("OpenAI chat completion did not contain text output")

    def _render_page_prompt(
        self,
        parsed_page: ParsedPage,
        memory: dict[str, Any],
        respondent_card: dict[str, Any],
        skills: dict[str, str],
    ) -> str:
        fields_json = json.dumps(
                {
                    "fields": parsed_page.fields,
                    "groups": parsed_page.groups,
                    "next_button_candidates": parsed_page.next_button_candidates,
                    "validation_messages": parsed_page.validation_messages,
                    "dialogs": parsed_page.dialogs,
                    "matrices": parsed_page.matrices,
                    "current_url": parsed_page.url,
                },
            ensure_ascii=False,
            indent=2,
        )[:30000]
        replacements = {
            "{respondent_profile}": yaml.safe_dump(self.config.respondent_profile, sort_keys=False),
            "{respondent_card}": yaml.safe_dump(respondent_card, sort_keys=False),
            "{memory}": json.dumps(memory, ensure_ascii=False, indent=2),
            "{skills}": yaml.safe_dump(skills, sort_keys=False),
            "{visible_text}": parsed_page.visible_text[:20000],
            "{fields_json}": fields_json,
        }
        rendered = self.page_prompt_template
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)
        return rendered

    @staticmethod
    def _schema_example() -> str:
        return json.dumps(
            {
                "status": "answer",
                "stuck_reason": None,
                "answers": [
                    {
                        "question_id_or_text": "question text",
                        "answer_type": "single_choice",
                        "answer": "selected answer",
                    }
                ],
                "next": "click_next",
                "memory_update": ["short memory item"],
                "memory_patch": {
                    "demographics": {},
                    "preferences": {},
                    "attitudes": {},
                    "examples_given": {},
                    "numeric_answers": {},
                    "open_ended_summaries": {},
                    "uncertainties": {},
                },
            },
            indent=2,
        )


def _is_temperature_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return "temperature" in text and (
        "unsupported parameter" in text
        or "unsupported value" in text
        or "only the default" in text
    )
