from __future__ import annotations

from pathlib import Path

from .schemas import ParsedPage


SKILL_DIR = Path("skills")


def select_skills(parsed_page: ParsedPage) -> dict[str, str]:
    text = parsed_page.visible_text.lower()
    kinds = {group.get("kind", "") for group in parsed_page.groups}
    selected: set[str] = {"instruction_following_skill.txt", "consistency_skill.txt"}

    if parsed_page.matrices or "matrix" in text or "each row" in text or "for each" in text:
        selected.add("matrix_skill.txt")
    if "textarea" in kinds or any(group.get("kind") == "text_input" for group in parsed_page.groups):
        selected.add("open_ended_skill.txt")
    if "100 points" in text or "allocate" in text or "total" in text:
        selected.add("constant_sum_skill.txt")
    if "rank" in text or "most important to least" in text:
        selected.add("rank_order_skill.txt")
    if parsed_page.validation_messages or parsed_page.dialogs:
        selected.add("validation_recovery_skill.txt")
    if any(word in text for word in ["signature", "captcha", "file upload", "login", "payment"]):
        selected.add("unsupported_component_skill.txt")

    skills: dict[str, str] = {}
    for filename in sorted(selected):
        path = SKILL_DIR / filename
        if path.exists():
            skills[filename.removesuffix(".txt")] = path.read_text(encoding="utf-8").strip()
    return skills

