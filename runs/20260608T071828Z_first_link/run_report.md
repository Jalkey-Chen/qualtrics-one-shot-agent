# Run Report

- Run name: first_link
- URL kind: external
- Provider/model: openai / gpt-5.5
- Start time: 2026-06-08T07:18:28.650644+00:00
- End time: 2026-06-08T07:22:29.282736+00:00
- Status: stuck
- Total pages: 10
- Total LLM calls: 7
- Total CAPTCHA LLM calls: 22
- Stuck reason: Validation recovery exceeded retry limit
- Screenshots path: runs\20260608T071828Z_first_link\screenshots
- Trace path: runs\20260608T071828Z_first_link\trace.zip
- Config hash: 39e5ca2e43c890a22b3b555aea986c18e75db07ead75cdfe8160b625e306d3eb
- Git commit: 3656944b187ea806cb55f63ef895aa1aabbdca26
- Python version: 3.12.10
- OS: Windows-11-10.0.26200-SP0
- Dependencies: pyproject.toml + uv.lock

## Pacing

- Pacing enabled: True
- Settings:

```yaml
action_interval_seconds: 0.35
base_page_delay_seconds: 1.0
enabled: true
matrix_row_delay_seconds: 0.25
max_page_delay_seconds: 12.0
open_ended_delay_seconds: 2.0
per_100_words_delay_seconds: 1.5
per_question_delay_seconds: 0.6
validation_recovery_delay_seconds: 1.5
```

## CAPTCHA

- Enabled: True
- Model: gpt-5.5
- Max attempts: 3

## Reproducibility Notes

- LLM outputs are nondeterministic even with a fixed respondent card and config.
- API keys and official survey URLs are not stored in the repository.
- This artifact does not include proxying, stealth, device spoofing, or hidden-field manipulation.