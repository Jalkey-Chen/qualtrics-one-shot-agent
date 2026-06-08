import pytest
from pydantic import ValidationError

from qualtrics_one_shot_agent.schemas import RunConfig, SurveyPlan


def test_valid_sample_json_can_be_parsed() -> None:
    raw = """
    {
      "status": "answer",
      "stuck_reason": null,
      "answers": [
        {
          "question_id_or_text": "question text",
          "answer_type": "single_choice",
          "answer": "selected answer"
        }
      ],
      "next": "click_next",
      "memory_update": ["short memory item"]
    }
    """
    plan = SurveyPlan.model_validate_json(raw)
    assert plan.status == "answer"
    assert plan.answers[0].answer_type == "single_choice"


def test_invalid_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SurveyPlan.model_validate(
            {
                "status": "continue",
                "stuck_reason": None,
                "answers": [],
                "next": "click_next",
                "memory_update": [],
            }
        )


def test_answer_status_allows_empty_answers_for_intro_pages() -> None:
    plan = SurveyPlan.model_validate(
        {
            "status": "answer",
            "stuck_reason": None,
            "answers": [],
            "next": "click_next",
            "memory_update": [],
        }
    )
    assert plan.answers == []


def test_number_and_select_answer_types_are_accepted() -> None:
    plan = SurveyPlan.model_validate(
        {
            "status": "answer",
            "stuck_reason": None,
            "answers": [
                {"question_id_or_text": "Hours", "answer_type": "number", "answer": 7},
                {"question_id_or_text": "Employment", "answer_type": "select", "answer": "Student"},
            ],
            "next": "click_next",
            "memory_update": [],
        }
    )
    assert [answer.answer_type for answer in plan.answers] == ["number", "select"]


def test_missing_required_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SurveyPlan.model_validate(
            {
                "status": "answer",
                "stuck_reason": None,
                "answers": [],
            }
        )


def test_run_config_accepts_captcha_settings() -> None:
    config = RunConfig.model_validate(
        {
            "provider": "openai",
            "model": "gpt-5.5",
            "temperature": 0.2,
            "max_pages": 80,
            "headed": True,
            "slow_mo_ms": 100,
            "page_timeout_ms": 30000,
            "captcha": {
                "enabled": True,
                "model": "gpt-5.5",
                "max_attempts": 2,
                "solve_timeout_ms": 10000,
            },
            "respondent_profile": {"location": "United States"},
        }
    )

    assert config.captcha.enabled
    assert config.captcha.max_attempts == 2
