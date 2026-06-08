from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Status = Literal["answer", "stuck", "finished"]
AnswerType = Literal["single_choice", "multi_choice", "matrix", "text", "number", "select", "slider", "rank"]
NextAction = Literal["click_next", "stop"]
ExecutionStatus = Literal["ok", "stuck", "finished"]
RunMode = Literal["debug", "practice", "official"]


class RespondentProfile(BaseModel):
    model_config = ConfigDict(extra="allow")


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai"] = "openai"
    model: str = "gpt-5.5"
    temperature: float = 1.0
    max_pages: int = Field(default=80, ge=1)
    headed: bool = True
    slow_mo_ms: int = Field(default=100, ge=0)
    page_timeout_ms: int = Field(default=30000, ge=1000)
    run_mode: RunMode = "practice"
    respondent_card_path: str = "respondent_card.yaml"
    pacing: "PacingConfig" = Field(default_factory=lambda: PacingConfig())
    captcha: "CaptchaConfig" = Field(default_factory=lambda: CaptchaConfig())
    respondent_profile: dict[str, Any]


class PacingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    base_page_delay_seconds: float = Field(default=1.0, ge=0)
    per_100_words_delay_seconds: float = Field(default=1.5, ge=0)
    per_question_delay_seconds: float = Field(default=0.6, ge=0)
    matrix_row_delay_seconds: float = Field(default=0.25, ge=0)
    open_ended_delay_seconds: float = Field(default=2.0, ge=0)
    validation_recovery_delay_seconds: float = Field(default=1.5, ge=0)
    action_interval_seconds: float = Field(default=0.35, ge=0)
    max_page_delay_seconds: float = Field(default=12.0, ge=0)


class CaptchaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    model: str = "gpt-5.5"
    max_attempts: int = Field(default=3, ge=1)
    solve_timeout_ms: int = Field(default=15000, ge=1000)


class SurveyAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id_or_text: str = Field(min_length=1)
    answer_type: AnswerType
    answer: str | int | float | list[Any] | dict[str, Any]


class SurveyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    stuck_reason: str | None
    answers: list[SurveyAnswer]
    next: NextAction
    memory_update: list[str] = Field(default_factory=list)
    memory_patch: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExecutionStatus
    message: str
    actions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ParsedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    visible_text: str
    fields: list[dict[str, Any]]
    groups: list[dict[str, Any]] = Field(default_factory=list)
    next_button_candidates: list[dict[str, Any]]
    validation_messages: list[str] = Field(default_factory=list)
    dialogs: list[dict[str, Any]] = Field(default_factory=list)
    matrices: list[dict[str, Any]] = Field(default_factory=list)
