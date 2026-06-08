from qualtrics_one_shot_agent.executor import _extract_number, _extract_rank_items, _matrix_answer_is_na, _parsed_page_has_unanswered_dialog
from qualtrics_one_shot_agent.schemas import ParsedPage


def test_extract_number_from_slider_answers() -> None:
    assert _extract_number("50") == 50
    assert _extract_number("navigate to 50.") == 50
    assert _extract_number({"value": "75"}) == 75
    assert _extract_number(True) is None
    assert _extract_number("no number") is None


def test_extract_rank_items_from_common_shapes() -> None:
    assert _extract_rank_items(["A", "B", "C"]) == ["A", "B", "C"]
    assert _extract_rank_items("A, B, C") == ["A", "B", "C"]
    assert _extract_rank_items({"order": ["B", "A"]}) == ["B", "A"]
    assert _extract_rank_items({"A": 2, "B": 1}) == ["B", "A"]


def test_matrix_na_answer_detection() -> None:
    assert _matrix_answer_is_na("NA")
    assert _matrix_answer_is_na("N/A")
    assert _matrix_answer_is_na("NA - have not heard of the brand")
    assert _matrix_answer_is_na("not applicable")
    assert not _matrix_answer_is_na("5 - Weakly like")
    assert not _matrix_answer_is_na("6 - Somewhat like")


def test_unanswered_dialog_detection() -> None:
    parsed = ParsedPage(
        url="https://example.test",
        visible_text="",
        fields=[],
        next_button_candidates=[],
        dialogs=[{"text": "You have unanswered questions. Continue without answering?", "buttons": ["Continue", "Go back"]}],
    )
    assert _parsed_page_has_unanswered_dialog(parsed)
