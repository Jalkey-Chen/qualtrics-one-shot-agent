from qualtrics_one_shot_agent.answer_validator import validate_plan
from qualtrics_one_shot_agent.pacing import compute_page_delay
from qualtrics_one_shot_agent.schemas import PacingConfig, ParsedPage, SurveyPlan


def test_validator_rejects_invisible_single_choice_option() -> None:
    parsed = ParsedPage(
        url="https://example.test",
        visible_text="Choose one option",
        fields=[],
        groups=[
            {
                "kind": "radio_group",
                "options": [{"text": "Agree"}, {"text": "Disagree"}],
            }
        ],
        next_button_candidates=[],
        matrices=[],
    )
    plan = SurveyPlan(
        status="answer",
        stuck_reason=None,
        answers=[{"question_id_or_text": "Choose one option", "answer_type": "single_choice", "answer": "Not visible"}],
        next="click_next",
        memory_update=[],
    )

    result = validate_plan(plan, parsed)

    assert not result.valid
    assert "Answer option not visible" in result.errors[0]


def test_validator_accepts_complete_matrix_plan() -> None:
    parsed = ParsedPage(
        url="https://example.test",
        visible_text="Please answer every row",
        fields=[],
        groups=[],
        next_button_candidates=[],
        matrices=[{"rows": ["Scientists", "Courts"], "columns": ["None", "A great deal"]}],
    )
    plan = SurveyPlan(
        status="answer",
        stuck_reason=None,
        answers=[
            {
                "question_id_or_text": "Trust matrix",
                "answer_type": "matrix",
                "answer": {"Scientists": "A great deal", "Courts": "A great deal"},
            }
        ],
        next="click_next",
        memory_update=[],
    )

    assert validate_plan(plan, parsed).valid


def test_pacing_records_delay_reason() -> None:
    parsed = ParsedPage(
        url="file:///mock.html",
        visible_text=" ".join(["word"] * 120) + "?",
        fields=[],
        groups=[{"kind": "text_input"}],
        next_button_candidates=[],
        matrices=[{"rows": ["Row one", "Row two"], "columns": ["Agree"]}],
    )

    decision = compute_page_delay(parsed, PacingConfig(), validation_retry_count=1)

    assert decision.delay_seconds > 0
    assert "validation_retry=1" in decision.reason


def test_validator_rejects_slider_outside_range() -> None:
    parsed = ParsedPage(
        url="https://example.test",
        visible_text="Choose a value from 0 to 10",
        fields=[],
        groups=[{"kind": "range_slider", "min": 0, "max": 10}],
        next_button_candidates=[],
        matrices=[],
    )
    plan = SurveyPlan(
        status="answer",
        stuck_reason=None,
        answers=[{"question_id_or_text": "Difficulty", "answer_type": "slider", "answer": 11}],
        next="click_next",
        memory_update=[],
    )

    result = validate_plan(plan, parsed)

    assert not result.valid
    assert any("above max" in error for error in result.errors)


def test_validator_accepts_option_visible_only_in_page_text() -> None:
    parsed = ParsedPage(
        url="https://example.test",
        visible_text="What is your age group? 18-24 25-34 35-44",
        fields=[{"tag": "button", "type": "button", "text": "Next page"}],
        groups=[],
        next_button_candidates=[],
        matrices=[],
    )
    plan = SurveyPlan(
        status="answer",
        stuck_reason=None,
        answers=[{"question_id_or_text": "What is your age group?", "answer_type": "single_choice", "answer": "25-34"}],
        next="click_next",
        memory_update=[],
    )

    assert validate_plan(plan, parsed).valid


def test_validator_allows_closed_dropdown_without_exposed_options() -> None:
    parsed = ParsedPage(
        url="https://example.test",
        visible_text="What is the highest level of education you have completed? Select one",
        fields=[{"tag": "div", "role": "combobox", "text": "Select one", "options": []}],
        groups=[{"kind": "custom_select", "name": "Select one", "text": "Select one", "options": []}],
        next_button_candidates=[],
        matrices=[],
    )
    plan = SurveyPlan(
        status="answer",
        stuck_reason=None,
        answers=[
            {
                "question_id_or_text": "What is the highest level of education you have completed?",
                "answer_type": "single_choice",
                "answer": "Bachelor's degree",
            }
        ],
        next="click_next",
        memory_update=[],
    )

    assert validate_plan(plan, parsed).valid
