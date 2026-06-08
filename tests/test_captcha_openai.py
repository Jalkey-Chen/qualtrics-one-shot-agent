from qualtrics_one_shot_agent.captcha import ChatGPTCaptchaClient, _clean_captcha_text


class FakeCaptchaCompletions:
    def __init__(self) -> None:
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if "temperature" in kwargs:
            raise RuntimeError(
                "Unsupported value: 'temperature' does not support 0 with this model. "
                "Only the default (1) value is supported."
            )
        message = type("FakeMessage", (), {"content": "123"})()
        choice = type("FakeChoice", (), {"message": message})()
        return type("FakeResponse", (), {"choices": [choice]})()


class FakeCaptchaClient:
    def __init__(self) -> None:
        self.chat = type("FakeChat", (), {"completions": FakeCaptchaCompletions()})()


def test_captcha_client_retries_without_temperature_when_model_rejects_non_default_value(tmp_path) -> None:
    image = tmp_path / "captcha.png"
    image.write_bytes(b"not-really-a-png-but-enough-for-base64")
    client = ChatGPTCaptchaClient("gpt-5.5")
    client.client = FakeCaptchaClient()

    text = client._ask_image("read it", image, temperature=0, max_tokens=10)

    requests = client.client.chat.completions.requests
    assert text == "123"
    assert len(requests) == 2
    assert "temperature" in requests[0]
    assert "temperature" not in requests[1]
    assert "max_tokens" not in requests[0]
    assert requests[0]["max_completion_tokens"] == 256
    assert client.total_calls == 2


def test_numeric_captcha_cleaning_prefers_digits() -> None:
    assert _clean_captcha_text("The answer is 5.", numeric_only=True) == "5"
    assert _clean_captcha_text("five", numeric_only=True) == ""
    assert _clean_captcha_text("2 + 3 = 5", numeric_only=True) == "5"
