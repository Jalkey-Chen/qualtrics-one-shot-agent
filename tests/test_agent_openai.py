from qualtrics_one_shot_agent.agent import DecisionAgent
from qualtrics_one_shot_agent.schemas import RunConfig


class FakeResponses:
    def __init__(self, error_message: str = "Unsupported parameter: 'temperature' is not supported with this model.") -> None:
        self.requests = []
        self.error_message = error_message

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if "temperature" in kwargs:
            raise RuntimeError(self.error_message)
        message = type("FakeMessage", (), {"content": '{"status":"finished","stuck_reason":null,"answers":[],"next":"stop","memory_update":[]}'})()
        choice = type("FakeChoice", (), {"message": message})()
        return type("FakeResponse", (), {"choices": [choice]})()


class FakeClient:
    def __init__(self, error_message: str = "Unsupported parameter: 'temperature' is not supported with this model.") -> None:
        self.chat = type("FakeChat", (), {"completions": FakeResponses(error_message)})()


def test_call_retries_without_temperature_when_model_rejects_it() -> None:
    agent = _agent_with_fake_client()

    text = agent._call("user")

    assert '"status":"finished"' in text
    assert len(agent.client.chat.completions.requests) == 2
    assert "temperature" in agent.client.chat.completions.requests[0]
    assert "temperature" not in agent.client.chat.completions.requests[1]


def test_call_retries_without_temperature_when_model_rejects_non_default_value() -> None:
    agent = _agent_with_fake_client(
        "Unsupported value: 'temperature' does not support 0.2 with this model. Only the default (1) value is supported."
    )

    text = agent._call("user")

    assert '"status":"finished"' in text
    assert len(agent.client.chat.completions.requests) == 2
    assert "temperature" in agent.client.chat.completions.requests[0]
    assert "temperature" not in agent.client.chat.completions.requests[1]


def _agent_with_fake_client(error_message: str = "Unsupported parameter: 'temperature' is not supported with this model.") -> DecisionAgent:
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
    agent.system_prompt = "system"
    agent.client = FakeClient(error_message)
    agent.total_llm_calls = 0
    return agent
