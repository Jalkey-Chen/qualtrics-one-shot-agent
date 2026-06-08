# qualtrics-one-shot-agent

Minimal, reproducible Python MVP for an authorized AI-agent survey challenge.

This repository implements a general-purpose Qualtrics-like survey completion agent for controlled one-shot survey environments. It is intended for practice-survey debugging and reproducible research artifact creation, not for unauthorized survey automation, mass submission, platform abuse, or evasion.

The same bot, code, and config should be used for both official survey versions. Official survey URLs should be passed only through the CLI and should never be committed.

## What It Does

- Opens a survey URL in Playwright Chromium.
- Runs in headed mode by default for observation and debugging.
- Saves before/after screenshots for each page.
- Detects supported CAPTCHA gates and attempts an authorized ChatGPT-based solve before survey parsing.
- Parses visible text and visible form elements.
- Parses visible validation messages, required-question warnings, and reminder dialogs.
- Sends page state, respondent profile, respondent card, structured memory ledger, and relevant survey skills to the OpenAI API.
- Requires a strict JSON plan from the LLM.
- Validates the plan with Pydantic and a conservative pre-execution answer validator.
- Executes visible page actions best-effort.
- Writes JSONL step logs, a summary file, final state, Playwright trace, and `run_report.md`.

## Supported MVP Page Behaviors

- Supported CAPTCHA gates before survey pages: text/image CAPTCHA, Geetest slider, and reCAPTCHA v2 image challenges best-effort.
- Intro/instruction pages with only a Next button
- Single choice and multiple choice
- Text inputs and textareas
- Matrix questions with table-like rows and columns
- Sliders backed by visible `input[type=range]`
- Rank questions using visible rank dropdowns, with a drag fallback for visible rank items
- Numeric inputs, native selects, custom Qualtrics-like dropdowns, and constant-sum style numeric allocation best-effort
- Qualtrics-like validation and unanswered-question reminders, which are logged and surfaced to the LLM for correction instead of being silently ignored

## Phase 2 Reliability Modules

- `respondent_card.yaml` defines a fixed, richer fictional respondent profile for consistency across pages.
- A structured memory ledger tracks demographics, preferences, attitudes, examples, numeric answers, open-ended summaries, and uncertainties. The LLM returns `memory_patch`, and the runner merges it after each page.
- `skills/` contains small survey-specific instruction modules. The runner dynamically injects relevant skills for matrices, ranking, open-ended answers, constant-sum questions, validation recovery, consistency, and unsupported components.
- `answer_validator.py` checks the LLM plan before execution, including visible option matching, exact-two instructions, strict text instructions, matrix row coverage, constant-sum totals, numeric ranges, rank duplicates, and empty text answers. If validation fails, the LLM gets one repair attempt.
- `pacing.py` provides transparent cognitive pacing and UI stability waits based on page word count, question count, matrix rows, open-ended fields, and validation recovery. This is not mouse trajectory spoofing, behavioral detection evasion, browser stealth, or keystroke simulation.
- `preflight.py` checks required local setup before a run, including API key, prompts, respondent card, Playwright Chromium, config validity, and writable `runs/`.
- `run_report.md` is generated after each run for reproducibility reporting.

## What It Does Not Include

- Proxy support
- Anti-fingerprinting or stealth logic
- Device spoofing
- Mouse trajectory simulation
- Detection-circumvention logic
- Hidden-field manipulation
- Hard-coded logic for specific detection questions

## Install

Requires Python 3.11+ and `uv`.

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

On Windows PowerShell, use:

```powershell
Copy-Item .env.example .env
```

Then put your API key in `.env`:

```text
OPENAI_API_KEY=your_api_key_here
```

## Configure

Edit `config.yaml` to choose the model and browser behavior.

The default model is:

```yaml
model: gpt-5.5
captcha:
  enabled: true
  model: gpt-5.5
```

The survey URL is intentionally not stored in `config.yaml`.

`run_mode` supports:

- `debug`: local development and mock-survey debugging.
- `practice`: default mode for authorized practice surveys.
- `official`: fixed-config one-shot runs. Do not use official links for debugging; preserve the full run directory if anything gets stuck.

You can override it from the CLI:

```bash
uv run python -m qualtrics_one_shot_agent.main --url "<SURVEY_URL>" --run-name "practice_test" --config config.yaml --run-mode practice
```

## Run A Practice Survey

```bash
uv run python -m qualtrics_one_shot_agent.main --url "<PRACTICE_SURVEY_URL>" --run-name "practice_test" --config config.yaml
```

## Run Local Mock Surveys

The `mock_surveys/` directory contains local HTML surveys for debugging parser behavior, executor actions, LLM decision loops, logging, screenshots, and stuck handling. These surveys do not submit real data.

With a file URL, use an absolute path:

```bash
uv run python -m qualtrics_one_shot_agent.main \
  --url "file:///ABSOLUTE/PATH/TO/mock_surveys/opinionqa_style.html" \
  --run-name "mock_opinionqa" \
  --config config.yaml
```

On Windows, the file URL looks like:

```text
file:///C:/Users/you/path/to/qualtrics-one-shot-agent/mock_surveys/opinionqa_style.html
```

If Playwright or the browser has trouble with local file paths, serve the mock survey directory:

```bash
cd mock_surveys
python -m http.server 8000
```

Then run from the project root:

```bash
uv run python -m qualtrics_one_shot_agent.main \
  --url "http://localhost:8000/opinionqa_style.html" \
  --run-name "mock_opinionqa" \
  --config config.yaml
```

The smoke script prints commands only, because each run calls the OpenAI API:

```bash
bash scripts/run_mock_smoke_tests.sh
```

## Official Run Notes

- Do not commit official survey URLs.
- Use the exact same code and config for both official survey versions.
- Do not debug on official links.
- If the run gets stuck, preserve the screenshots, `steps.jsonl`, `summary.json`, `final_state.txt`, and `trace.zip`.

## Outputs

Each run creates:

```text
runs/<timestamp>_<run_name>/
├── screenshots/
│   ├── page_001_before.png
│   ├── page_001_after.png
│   └── ...
├── steps.jsonl
├── summary.json
├── final_state.txt
├── run_report.md
└── trace.zip
```

If the agent gets stuck, start with:

- `final_state.txt` for the status and short reason
- `summary.json` for run-level metadata
- `steps.jsonl` for the parsed fields, LLM plan, execution result, and errors
- `screenshots/` for visual inspection
- `trace.zip` for Playwright trace debugging
- `run_report.md` for run metadata, config hash, git commit, environment, dependency, pacing, and nondeterminism notes

## Reproducibility Notes

Record these when reporting a run:

- Python version
- Operating system
- `uv.lock`
- `config.yaml` model name and parameters
- `config.yaml` CAPTCHA settings and CAPTCHA screenshots, if a CAPTCHA appeared
- `respondent_card.yaml`
- Run directory contents
- Any nondeterminism from LLM output

API keys and official survey URLs are not included in the repository.

## Tests

```bash
uv run pytest
```
