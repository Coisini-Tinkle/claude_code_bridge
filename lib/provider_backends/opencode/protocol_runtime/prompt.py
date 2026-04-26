from __future__ import annotations

from provider_backends.opencode.protocol_runtime.skills import load_opencode_skills


def build_opencode_prompt_body(message: str) -> str:
    rendered = (message or '').rstrip()
    skills = load_opencode_skills()
    if skills:
        rendered = f'{skills}\n\n{rendered}'.strip()
    return rendered
