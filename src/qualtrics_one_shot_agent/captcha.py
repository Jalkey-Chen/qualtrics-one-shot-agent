from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from openai import OpenAI
from playwright.sync_api import Frame, Locator, Page, TimeoutError as PlaywrightTimeoutError

from .schemas import CaptchaConfig


CaptchaStatus = Literal["not_present", "skipped", "solved", "failed", "unsupported"]


@dataclass
class CaptchaResult:
    status: CaptchaStatus
    message: str
    actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    llm_calls: int = 0


class ChatGPTCaptchaClient:
    def __init__(self, model: str) -> None:
        self.model = model
        self.client = OpenAI()
        self.total_calls = 0

    def read_text(self, image_path: Path, numeric_only: bool = False) -> str:
        if numeric_only:
            prompt = (
                "Solve the simple math CAPTCHA in this image. Return only the final answer as Arabic numeral digits, "
                "for example 5. Do not spell the number as a word. Do not return the equation. Do not include any "
                "explanation, punctuation, spaces, or extra text."
            )
        else:
            prompt = "Read the CAPTCHA text in this image. Return only the CAPTCHA text, with no explanation or extra text."
        return self._ask_image(prompt, image_path, temperature=0, max_tokens=512).strip()

    def puzzle_distance(self, image_path: Path) -> int | None:
        prompt = """
Analyze this slider puzzle CAPTCHA image. Identify the slider handle and the empty target slot.
Return only the horizontal pixel distance the handle should move to the right so the handle center aligns with the slot center.
Use an integer only, no units or explanation. If already aligned, return 0. Cap the value at 260.
"""
        return _first_int(self._ask_image(prompt, image_path, temperature=0, max_tokens=50), minimum=0, maximum=260)

    def puzzle_correction(self, image_path: Path) -> int | None:
        prompt = """
Analyze this slider puzzle after an attempted move. Return only the final horizontal pixel correction needed:
positive means move right, negative means move left, 0 means already aligned. Use an integer only.
"""
        return _first_int(self._ask_image(prompt, image_path, temperature=0, max_tokens=50), minimum=-80, maximum=80)

    def recaptcha_target(self, image_path: Path) -> str:
        prompt = """
Read the reCAPTCHA instruction. Return only the object category the user is asked to select.
For example, "Select all squares with bicycles" should return "bicycles". If it says skip, return "skip".
"""
        return self._ask_image(prompt, image_path, temperature=0, max_tokens=50).strip().lower()

    def tile_contains(self, image_path: Path, target: str) -> bool:
        prompt = (
            f"Does this image clearly contain a {target} or a recognizable part of a {target}? "
            "Return only true or false. Return false if uncertain."
        )
        answer = self._ask_image(prompt, image_path, temperature=0, max_tokens=10).strip().lower()
        return answer.startswith("true")

    def _ask_image(self, prompt: str, image_path: Path, temperature: float, max_tokens: int) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt.strip()},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{_image_to_base64(image_path)}"},
                        },
                    ],
                }
            ],
            "temperature": temperature,
            "max_completion_tokens": max(256, max_tokens),
        }
        response = self._create_chat_completion(request)
        choices = getattr(response, "choices", []) or []
        if not choices:
            raise RuntimeError("ChatGPT CAPTCHA response did not contain choices")
        content = getattr(choices[0].message, "content", "")
        if not isinstance(content, str):
            raise RuntimeError("ChatGPT CAPTCHA response did not contain text")
        return content

    def _create_chat_completion(self, request: dict[str, Any]) -> Any:
        self.total_calls += 1
        try:
            return self.client.chat.completions.create(**request)
        except Exception as exc:
            if not _is_temperature_rejection(exc):
                raise
            retry_request = dict(request)
            retry_request.pop("temperature", None)
            self.total_calls += 1
            return self.client.chat.completions.create(**retry_request)


def solve_captcha_if_present(
    page: Page,
    config: CaptchaConfig,
    screenshot_dir: Path,
    page_index: int,
) -> CaptchaResult:
    if not config.enabled:
        return CaptchaResult(status="skipped", message="CAPTCHA solver is disabled")

    captcha_dir = screenshot_dir / "captcha"
    captcha_dir.mkdir(parents=True, exist_ok=True)
    client = ChatGPTCaptchaClient(config.model)

    try:
        if _has_geetest(page):
            result = _solve_geetest(page, client, captcha_dir, page_index, config.max_attempts, config.solve_timeout_ms)
        elif _has_recaptcha(page):
            result = _solve_recaptcha_v2(page, client, captcha_dir, page_index, config.max_attempts)
        elif _has_text_captcha(page):
            result = _solve_text_captcha(page, client, captcha_dir, page_index, config.max_attempts)
        elif _has_hcaptcha(page):
            result = CaptchaResult(status="unsupported", message="hCaptcha was detected but no Playwright integration is available")
        else:
            result = CaptchaResult(status="not_present", message="No CAPTCHA detected")
        result.llm_calls = client.total_calls
        return result
    except Exception as exc:
        result = CaptchaResult(status="failed", message=f"CAPTCHA solve failed: {exc}", errors=[str(exc)])
        result.llm_calls = client.total_calls
        return result


def _solve_geetest(
    page: Page,
    client: ChatGPTCaptchaClient,
    captcha_dir: Path,
    page_index: int,
    max_attempts: int,
    timeout_ms: int,
) -> CaptchaResult:
    actions: list[str] = []
    screenshots: list[str] = []
    _click_if_visible(page.locator(".geetest_radar_tip, .geetest_radar_tip_content").first, timeout_ms=3000)

    for attempt in range(1, max_attempts + 1):
        window = page.locator(".geetest_window").first
        try:
            window.wait_for(state="visible", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            return CaptchaResult(status="failed", message="Geetest window did not become visible", actions=actions)

        initial = captcha_dir / f"page_{page_index:03d}_geetest_{attempt}_initial.png"
        window.screenshot(path=str(initial))
        screenshots.append(str(initial))
        distance = client.puzzle_distance(initial)
        if distance is None:
            actions.append(f"Attempt {attempt}: ChatGPT did not return a puzzle distance")
            _refresh_geetest(page)
            continue

        actions.append(f"Attempt {attempt}: moved Geetest slider by {distance}px")
        _drag_geetest_slider(page, distance)
        page.wait_for_timeout(1200)
        if _geetest_success(page):
            return CaptchaResult(status="solved", message="Solved Geetest puzzle CAPTCHA", actions=actions, screenshots=screenshots)

        correction_image = captcha_dir / f"page_{page_index:03d}_geetest_{attempt}_correction.png"
        window.screenshot(path=str(correction_image))
        screenshots.append(str(correction_image))
        correction = client.puzzle_correction(correction_image)
        if correction:
            final_distance = max(0, min(260, distance + correction))
            actions.append(f"Attempt {attempt}: retrying Geetest slider with corrected distance {final_distance}px")
            _refresh_geetest(page)
            page.wait_for_timeout(1000)
            _drag_geetest_slider(page, final_distance)
            page.wait_for_timeout(1200)
            if _geetest_success(page):
                return CaptchaResult(status="solved", message="Solved Geetest puzzle CAPTCHA after correction", actions=actions, screenshots=screenshots)

        if attempt < max_attempts:
            _refresh_geetest(page)
            page.wait_for_timeout(1000)

    return CaptchaResult(status="failed", message="Geetest puzzle CAPTCHA was not solved", actions=actions, screenshots=screenshots)


def _solve_text_captcha(
    page: Page,
    client: ChatGPTCaptchaClient,
    captcha_dir: Path,
    page_index: int,
    max_attempts: int,
) -> CaptchaResult:
    actions: list[str] = []
    screenshots: list[str] = []
    for attempt in range(1, max_attempts + 1):
        frame, image = _find_text_captcha_image(page)
        if image is None:
            return CaptchaResult(status="not_present", message="Text CAPTCHA is no longer visible", actions=actions, screenshots=screenshots)
        numeric_only = _page_requests_numeric_captcha_answer(page)

        image_path = captcha_dir / f"page_{page_index:03d}_text_{attempt}.png"
        _screenshot_locator(page, image, image_path)
        screenshots.append(str(image_path))
        text = _clean_captcha_text(client.read_text(image_path, numeric_only=numeric_only), numeric_only=numeric_only)
        if not text:
            actions.append(f"Attempt {attempt}: ChatGPT returned an empty CAPTCHA transcription")
            continue

        filled = _fill_first_visible_text_input(frame, text)
        if not filled and frame is not page:
            filled = _fill_first_visible_text_input(page, text)
        if not filled:
            if not _page_requests_numeric_captcha_answer(page):
                return CaptchaResult(status="solved", message="Text CAPTCHA no longer appears after submission", actions=actions, screenshots=screenshots)
            return CaptchaResult(status="failed", message="Could not find a visible text input for CAPTCHA answer", actions=actions, screenshots=screenshots)
        actions.append(f"Attempt {attempt}: filled text CAPTCHA answer")
        clicked_submit = _click_first_matching_button(frame, ["check", "verify", "submit", "continue", "next", "→", ">"])
        if not clicked_submit and frame is not page:
            clicked_submit = _click_first_matching_button(page, ["check", "verify", "submit", "continue", "next", "→", ">"])
        if clicked_submit:
            actions.append(f"Attempt {attempt}: submitted text CAPTCHA answer")
        page.wait_for_timeout(1500)
        if numeric_only and not _page_requests_numeric_captcha_answer(page):
            return CaptchaResult(status="solved", message="Solved text CAPTCHA", actions=actions, screenshots=screenshots)
        if not _has_text_captcha(page):
            return CaptchaResult(status="solved", message="Solved text CAPTCHA", actions=actions, screenshots=screenshots)

    return CaptchaResult(status="failed", message="Text CAPTCHA was not solved", actions=actions, screenshots=screenshots)


def _solve_recaptcha_v2(
    page: Page,
    client: ChatGPTCaptchaClient,
    captcha_dir: Path,
    page_index: int,
    max_attempts: int,
) -> CaptchaResult:
    actions: list[str] = []
    screenshots: list[str] = []
    checkbox_frame = _recaptcha_checkbox_frame(page)
    if checkbox_frame is None:
        return CaptchaResult(status="failed", message="Could not access reCAPTCHA checkbox frame")

    _click_if_visible(checkbox_frame.locator(".recaptcha-checkbox-border, #recaptcha-anchor, [role='checkbox']").first, timeout_ms=5000)
    actions.append("Clicked reCAPTCHA checkbox")
    page.wait_for_timeout(1500)
    if _recaptcha_checked(checkbox_frame):
        return CaptchaResult(status="solved", message="Solved reCAPTCHA checkbox challenge", actions=actions)

    clicked_tiles: set[int] = set()
    last_target = ""
    for attempt in range(1, max_attempts + 1):
        challenge_frame = _recaptcha_challenge_frame(page)
        if challenge_frame is None:
            if _recaptcha_checked(checkbox_frame):
                return CaptchaResult(status="solved", message="Solved reCAPTCHA challenge", actions=actions, screenshots=screenshots)
            return CaptchaResult(status="failed", message="reCAPTCHA challenge frame was not accessible", actions=actions, screenshots=screenshots)

        instructions = challenge_frame.locator(".rc-imageselect-instructions").first
        instruction_path = captcha_dir / f"page_{page_index:03d}_recaptcha_{attempt}_instructions.png"
        _screenshot_locator(page, instructions, instruction_path)
        screenshots.append(str(instruction_path))
        target = client.recaptcha_target(instruction_path)
        if target == "skip":
            _click_first_matching_button(challenge_frame, ["skip"])
            actions.append("Clicked reCAPTCHA skip")
            page.wait_for_timeout(1500)
            continue
        if target != last_target:
            clicked_tiles.clear()
            last_target = target

        tiles = _recaptcha_tile_locator(challenge_frame)
        count = tiles.count()
        if count == 0:
            return CaptchaResult(status="failed", message="No reCAPTCHA image tiles found", actions=actions, screenshots=screenshots)

        tiles_to_click: list[int] = []
        for index in range(count):
            if index in clicked_tiles:
                continue
            tile_path = captcha_dir / f"page_{page_index:03d}_recaptcha_{attempt}_tile_{index}.png"
            _screenshot_locator(page, tiles.nth(index), tile_path)
            screenshots.append(str(tile_path))
            if client.tile_contains(tile_path, target):
                tiles_to_click.append(index)

        for index in tiles_to_click:
            tiles.nth(index).click(timeout=3000)
            clicked_tiles.add(index)
            page.wait_for_timeout(250)
        actions.append(f"Attempt {attempt}: clicked {len(tiles_to_click)} reCAPTCHA tiles for {target}")
        _click_first_matching_button(challenge_frame, ["verify"])
        page.wait_for_timeout(2000)
        if _recaptcha_checked(checkbox_frame):
            return CaptchaResult(status="solved", message="Solved reCAPTCHA image challenge", actions=actions, screenshots=screenshots)

    return CaptchaResult(status="failed", message="reCAPTCHA image challenge was not solved", actions=actions, screenshots=screenshots)


def _has_geetest(page: Page) -> bool:
    return _locator_visible(page.locator(".geetest_radar_tip, .geetest_window, .geetest_slider_button").first)


def _has_recaptcha(page: Page) -> bool:
    if _recaptcha_checkbox_frame(page) is not None:
        return True
    return _any_locator_visible(page, "iframe[title*='recaptcha' i], iframe[src*='recaptcha' i], .g-recaptcha, [data-sitekey]")


def _has_hcaptcha(page: Page) -> bool:
    return _locator_visible(page.locator("iframe[src*='hcaptcha'], [class*='hcaptcha'], [data-hcaptcha-widget-id]").first)


def _has_text_captcha(page: Page) -> bool:
    if not _page_looks_like_text_captcha(page):
        return False
    _, image = _find_text_captcha_image(page)
    return image is not None


def _find_text_captcha_image(page: Page) -> tuple[Page | Frame, Locator | None]:
    contexts: list[Page | Frame] = [page, *page.frames]
    selector = (
        "img[alt*='captcha' i], img[src*='captcha' i], "
        "canvas[id*='captcha' i], canvas[class*='captcha' i], "
        "[id*='captcha' i] img, [class*='captcha' i] img"
    )
    for context in contexts:
        locator = context.locator(selector)
        try:
            for index in range(min(locator.count(), 8)):
                candidate = locator.nth(index)
                if candidate.is_visible():
                    return context, candidate
        except Exception:
            continue
    return page, None


def _page_looks_like_text_captcha(page: Page) -> bool:
    try:
        text = page.evaluate("() => (document.body && document.body.innerText || '').toLowerCase()")
    except Exception:
        return False
    markers = [
        "captcha",
        "math problem",
        "valid number",
        "solve the",
        "enter your answer below",
    ]
    return any(marker in text for marker in markers)


def _fill_first_visible_text_input(context: Page | Frame, text: str) -> bool:
    locator = context.locator("input, textarea")
    try:
        count = locator.count()
    except Exception:
        return False
    for index in range(count):
        candidate = locator.nth(index)
        try:
            tag = str(candidate.evaluate("el => el.tagName.toLowerCase()"))
            input_type = str(candidate.evaluate("el => (el.getAttribute('type') || '').toLowerCase()"))
            if tag == "input" and input_type in {"button", "submit", "reset", "hidden", "radio", "checkbox", "file"}:
                continue
            if not candidate.is_visible() or not candidate.is_enabled():
                continue
            candidate.click(timeout=3000)
            candidate.fill("")
            try:
                candidate.type(text, delay=35)
            except Exception:
                candidate.fill(text)
            candidate.evaluate(
                """
                el => {
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  el.dispatchEvent(new Event('blur', { bubbles: true }));
                }
                """
            )
            try:
                if candidate.input_value().strip() != text:
                    native_set = """
                    (el, value) => {
                      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                      if (setter) setter.call(el, value);
                      else el.value = value;
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                      el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }
                    """
                    candidate.evaluate(native_set, text)
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def _click_first_matching_button(context: Page | Frame, names: list[str]) -> bool:
    pattern = re.compile("|".join(re.escape(name) for name in names), re.IGNORECASE)
    candidates = [
        context.get_by_role("button", name=pattern),
        context.locator("button,input[type='submit'],input[type='button'],[role='button']").filter(has_text=pattern),
        context.locator("#NextButton,input[name='NextButton']"),
    ]
    for locator in candidates:
        try:
            for index in range(locator.count()):
                button = locator.nth(index)
                if button.is_visible() and button.is_enabled():
                    button.click(timeout=3000)
                    return True
        except Exception:
            continue
    return False


def _drag_geetest_slider(page: Page, offset: int) -> None:
    slider = page.locator(".geetest_slider_button").first
    slider.wait_for(state="visible", timeout=5000)
    box = slider.bounding_box()
    if box is None:
        raise RuntimeError("Could not locate Geetest slider box")
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + max(0, offset), y, steps=12)
    page.mouse.up()


def _refresh_geetest(page: Page) -> None:
    if not _click_if_visible(page.locator(".geetest_refresh_1, .geetest_refresh").first, timeout_ms=2000):
        page.reload(wait_until="domcontentloaded")


def _geetest_success(page: Page) -> bool:
    success = page.locator(".geetest_success_radar_tip_content, .geetest_success").first
    if not _locator_visible(success):
        return False
    try:
        return "success" in success.inner_text(timeout=1000).lower()
    except Exception:
        return True


def _recaptcha_challenge_frame(page: Page) -> Frame | None:
    selector = "iframe[title*='recaptcha challenge' i], iframe[src*='bframe']"
    return _content_frame(page.locator(selector).first)


def _recaptcha_tile_locator(frame: Frame) -> Locator:
    selectors = [
        ".rc-imageselect-tile",
        ".rc-image-tile-wrapper",
        "table.rc-imageselect-table td",
        "[role='button'][class*='tile']",
    ]
    for selector in selectors:
        locator = frame.locator(selector)
        try:
            locator.first.wait_for(state="visible", timeout=5000)
            if locator.count() > 0:
                return locator
        except Exception:
            continue
    return frame.locator("table.rc-imageselect-table td")


def _recaptcha_checkbox_frame(page: Page) -> Frame | None:
    selectors = [
        "iframe[src*='api2/anchor']",
        "iframe[title*='recaptcha' i]",
        "iframe[src*='recaptcha' i]",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            for index in range(min(locator.count(), 12)):
                frame = _content_frame(locator.nth(index))
                if frame is None:
                    continue
                checkbox = frame.locator(".recaptcha-checkbox-border, #recaptcha-anchor, [role='checkbox']").first
                if _locator_visible(checkbox):
                    return frame
        except Exception:
            continue
    return None


def _recaptcha_checked(frame: Frame) -> bool:
    checked = frame.locator(".recaptcha-checkbox-checked, #recaptcha-anchor[aria-checked='true'], [aria-checked='true']").first
    return _locator_visible(checked)


def _content_frame(iframe: Locator) -> Frame | None:
    try:
        handle = iframe.element_handle(timeout=3000)
        return handle.content_frame() if handle else None
    except Exception:
        return None


def _click_if_visible(locator: Locator, timeout_ms: int) -> bool:
    try:
        if locator.is_visible(timeout=timeout_ms):
            locator.click(timeout=timeout_ms)
            return True
    except Exception:
        return False
    return False


def _screenshot_locator(page: Page, locator: Locator, path: Path) -> None:
    try:
        locator.screenshot(path=str(path), timeout=5000)
        return
    except Exception:
        pass
    try:
        box = locator.bounding_box(timeout=5000)
        if box is not None and box.get("width", 0) > 0 and box.get("height", 0) > 0:
            page.screenshot(path=str(path), clip=box)
            return
    except Exception:
        pass
    page.screenshot(path=str(path), full_page=True)


def _locator_visible(locator: Locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible(timeout=1000)
    except Exception:
        return False


def _any_locator_visible(page: Page, selector: str) -> bool:
    locator = page.locator(selector)
    try:
        for index in range(min(locator.count(), 12)):
            if _locator_visible(locator.nth(index)):
                return True
    except Exception:
        return False
    return False


def _image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _first_int(text: str, minimum: int, maximum: int) -> int | None:
    match = re.search(r"-?\d+", text or "")
    if not match:
        return None
    value = int(match.group(0))
    return max(minimum, min(maximum, value))


def _clean_captcha_text(text: str, numeric_only: bool = False) -> str:
    raw = text or ""
    if numeric_only:
        stripped = raw.strip()
        if re.fullmatch(r"-?\d+", stripped):
            return stripped
        matches = re.findall(r"-?\d+", raw)
        if matches:
            return matches[-1]
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", raw)


def _page_requests_numeric_captcha_answer(page: Page) -> bool:
    try:
        text = page.evaluate("() => (document.body && document.body.innerText || '').toLowerCase()")
    except Exception:
        return False
    return any(marker in text for marker in ["math problem", "valid number", "numeric answer", "enter your answer below"])




def _is_temperature_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return "temperature" in text and (
        "unsupported parameter" in text
        or "unsupported value" in text
        or "only the default" in text
    )
