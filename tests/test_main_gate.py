from qualtrics_one_shot_agent.captcha import CaptchaResult
from qualtrics_one_shot_agent.main import (
    _parsed_page_is_continue_gate,
    _parsed_page_is_solved_captcha_gate,
    _parsed_page_looks_loading_or_empty,
)
from qualtrics_one_shot_agent.schemas import ParsedPage


def test_continue_gate_is_detected_with_arrow_button_candidate() -> None:
    parsed = ParsedPage(
        url="https://example.qualtrics.test/jfe/form/example",
        visible_text="Click the button to continue to the survey.",
        fields=[{"tag": "button", "type": "button", "text": "→"}],
        groups=[],
        next_button_candidates=[{"tag": "button", "type": "button", "text": "→"}],
        matrices=[],
    )

    assert _parsed_page_is_continue_gate(parsed)


def test_spinner_page_is_treated_as_loading_or_empty() -> None:
    parsed = ParsedPage(
        url="https://example.qualtrics.test/jfe/form/example",
        visible_text="Powered by Qualtrics",
        fields=[],
        groups=[],
        next_button_candidates=[],
        matrices=[],
    )

    assert _parsed_page_looks_loading_or_empty(parsed)


def test_solved_captcha_gate_can_continue_without_llm_decision() -> None:
    parsed = ParsedPage(
        url="https://example.qualtrics.test/jfe/form/example",
        visible_text="I'm not a robot reCAPTCHA Powered by Qualtrics",
        fields=[{"tag": "input", "type": "button", "text": "Next | →"}],
        groups=[],
        next_button_candidates=[{"tag": "input", "type": "button", "text": "Next | →"}],
        matrices=[],
    )

    assert _parsed_page_is_solved_captcha_gate(
        parsed,
        CaptchaResult(status="solved", message="Solved reCAPTCHA checkbox challenge"),
    )
