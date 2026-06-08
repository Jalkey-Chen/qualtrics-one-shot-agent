# Local Mock Surveys

These local HTML surveys are for debugging the parser, executor, LLM decision loop, logging, screenshots, and stuck handling in this repository. They do not submit real data and do not contact any external survey platform.

## Surveys

- `opinionqa_style.html`: public opinion single-choice questions and open-ended responses.
- `wvs_gss_style.html`: values, trust, life satisfaction, dropdowns, and Likert matrices.
- `polypersona_style.html`: persona consistency across technology, health, work, consumer, and social domains.
- `qualtrics_like_mixed.html`: display logic, mixed components, side-by-side dropdowns, validation, and slider.
- `difficult_components.html`: long matrix, ranking constraints, slider/number consistency, and stuck-handling behavior.

## Run With A File URL

Use an absolute path:

```bash
uv run python -m qualtrics_one_shot_agent.main --url "file:///ABSOLUTE/PATH/TO/mock_surveys/opinionqa_style.html" --run-name "mock_opinionqa" --config config.yaml
```

On Windows, the URL will look similar to:

```text
file:///C:/Users/you/path/to/qualtrics-one-shot-agent/mock_surveys/opinionqa_style.html
```

## Run With A Local HTTP Server

If the browser has trouble with file URLs, serve the directory locally:

```bash
cd mock_surveys
python -m http.server 8000
```

From the project root, run:

```bash
uv run python -m qualtrics_one_shot_agent.main --url "http://localhost:8000/opinionqa_style.html" --run-name "mock_opinionqa" --config config.yaml
```

## Suggested Debug Order

Start with `opinionqa_style.html`, then try `wvs_gss_style.html`, then `qualtrics_like_mixed.html`, and finally `difficult_components.html`.

After each run, inspect:

- `runs/<timestamp>_<run_name>/steps.jsonl`
- `runs/<timestamp>_<run_name>/summary.json`
- `runs/<timestamp>_<run_name>/screenshots/`
- `runs/<timestamp>_<run_name>/final_state.txt`

## Ethics

These mock surveys are local test artifacts. They should not be used as a reason to repeatedly automate real public research surveys. Official one-shot links should not be used for debugging, and official URLs should never be committed.
