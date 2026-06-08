#!/usr/bin/env bash
set -euo pipefail

echo "This script only prints commands because each run calls the OpenAI API."
echo "First start the local server in another terminal:"
echo "  cd mock_surveys && python -m http.server 8000"
echo
echo "Run OpinionQA-style mock:"
echo "uv run python -m qualtrics_one_shot_agent.main --url http://localhost:8000/opinionqa_style.html --run-name mock_opinionqa --config config.yaml"
echo
echo "Run WVS/GSS-style mock:"
echo "uv run python -m qualtrics_one_shot_agent.main --url http://localhost:8000/wvs_gss_style.html --run-name mock_wvs_gss --config config.yaml"
echo
echo "Run PolyPersona-style mock:"
echo "uv run python -m qualtrics_one_shot_agent.main --url http://localhost:8000/polypersona_style.html --run-name mock_polypersona --config config.yaml"
echo
echo "Run Qualtrics-like mixed mock:"
echo "uv run python -m qualtrics_one_shot_agent.main --url http://localhost:8000/qualtrics_like_mixed.html --run-name mock_mixed --config config.yaml"
echo
echo "Run difficult-components mock:"
echo "uv run python -m qualtrics_one_shot_agent.main --url http://localhost:8000/difficult_components.html --run-name mock_difficult --config config.yaml"
