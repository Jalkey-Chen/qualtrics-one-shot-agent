from qualtrics_one_shot_agent.agent import DecisionAgent
from qualtrics_one_shot_agent.schemas import ParsedPage, RunConfig


def test_page_prompt_template_allows_literal_json_braces() -> None:
    agent = DecisionAgent.__new__(DecisionAgent)
    agent.config = RunConfig.model_validate(
        {
            "provider": "openai",
            "model": "gpt-5.5",
            "temperature": 0.2,
            "max_pages": 80,
            "headed": True,
            "slow_mo_ms": 100,
            "page_timeout_ms": 30000,
            "respondent_profile": {"location": "United States"},
        }
    )
    agent.page_prompt_template = """
Respondent profile:
{respondent_profile}

Current page visible text:
{visible_text}

Detected fields and options:
{fields_json}

Return a JSON plan:
{
  "status": "answer",
  "answers": []
}

Prior answer memory:
{memory}
"""
    parsed = ParsedPage(
        url="https://example.test",
        visible_text="Visible survey page",
        fields=[],
        next_button_candidates=[],
        matrices=[],
    )

    prompt = agent._render_page_prompt(parsed, {"open_ended_summaries": {"prior": ["memory item"]}}, {}, {})

    assert '"status": "answer"' in prompt
    assert "Visible survey page" in prompt
    assert "memory item" in prompt
