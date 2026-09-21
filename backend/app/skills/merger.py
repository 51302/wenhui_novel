"""Merge selected skills into a compact, deterministic prompt block."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.skills.loader import SkillDocument
from app.skills.selector import SkillSelection


@dataclass(frozen=True)
class SkillMergeResult:
    prompt: str
    skill_ids: tuple[str, ...]
    versions: dict[str, str]
    content_hashes: dict[str, str]


class SkillMerger:
    def __init__(self, max_chars: int = 8000):
        self.max_chars = max_chars

    def merge(self, selection: SkillSelection) -> SkillMergeResult:
        seen: set[str] = set()
        blocks: list[str] = []
        for document in selection.documents:
            body = self._dedupe_lines(document.body, seen)
            if not body:
                continue
            blocks.append(
                f"【Skill：{document.name} | id={document.skill_id} "
                f"| version={document.version}】\n{body}"
            )

        prompt = "\n\n".join(blocks)
        if len(prompt) > self.max_chars:
            prompt = prompt[: self.max_chars].rsplit("\n", 1)[0].rstrip()
            prompt += "\n\n【Skill 注入已按长度上限截断，优先保留前置规则】"

        return SkillMergeResult(
            prompt=prompt,
            skill_ids=tuple(document.skill_id for document in selection.documents),
            versions=selection.versions,
            content_hashes={
                document.skill_id: document.content_hash
                for document in selection.documents
            },
        )

    @staticmethod
    def _dedupe_lines(body: str, seen: set[str]) -> str:
        result: list[str] = []
        for line in body.splitlines():
            normalized = re.sub(r"\s+", " ", line.strip())
            if not normalized:
                if result and result[-1] != "":
                    result.append("")
                continue
            # Keep headings, but remove repeated boilerplate/rules shared by
            # multiple skills. This makes compositional prompts much smaller.
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(line.rstrip())
        while result and result[-1] == "":
            result.pop()
        return "\n".join(result)
