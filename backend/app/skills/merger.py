"""Merge selected skills into a compact, deterministic prompt block."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.skills.loader import SkillDocument
from app.skills.selector import SkillSelection


@dataclass(frozen=True)
class SkillMergeResult:
    prompt: str
    skill_ids: tuple[str, ...]          # 选择器选中的全部 Skill（含未注入进 prompt 的）
    versions: dict[str, str]
    content_hashes: dict[str, str]
    # 真正拼进 prompt 的 Skill：selected 里被长度上限省略掉的那些不在此列。
    # 日志/接口必须报这个，不能只报 skill_ids（否则会出现"日志说反AI生效、prompt 里没有"）。
    effective_ids: tuple[str, ...] = ()
    dropped_ids: tuple[str, ...] = ()


class SkillMerger:
    """按层合并 Skill，保证 base / quality / 用户显式指定 的 Skill 永不被长度上限整段裁掉。

    Skill 选择顺序按 (layer!=base, priority, skill_id)，即 base(10) → genre(50)
    → style(70) → capability(80) → quality(95)。若直接对整段 prompt 做尾部截断，
    最先被砍掉的恰好是排最后的 quality 层——也就是每章必需的反 AI 去味 Skill，
    历史实测：日志显示 novel-anti-ai 已选中，实际 prompt 里一个字都没有。

    因此这里先把必需层（base/quality）与用户显式指定的 Skill 的预算扣掉，
    剩下的额度按优先级顺序分配给启发式命中的可选层；额度不够的可选层整段省略
    （不做半截 Skill，避免规则被切断），并在末尾注明被省略的 id。
    """

    # 每章必需：base 是故事引擎地基，quality 是反AI 质量层。
    _RESERVED_LAYERS = ("base", "quality")

    def __init__(self, max_chars: int = 8000):
        self.max_chars = max_chars

    def merge(self, selection: SkillSelection) -> SkillMergeResult:
        explicit_ids = getattr(selection, "explicit_ids", frozenset())

        def _is_reserved(document: SkillDocument) -> bool:
            # 必需层（base/quality）+ 用户显式指定的 Skill：长度不够时不省略它们，
            # 只在启发式命中的可选层里淘汰。
            return document.layer in self._RESERVED_LAYERS or \
                document.skill_id in explicit_ids

        seen: set[str] = set()
        entries: list[tuple[SkillDocument, str]] = []
        dropped: list[str] = []
        used = 0
        documents = sorted(selection.documents, key=lambda doc: not _is_reserved(doc))
        for document in documents:
            candidate_seen = seen.copy()
            body = self._dedupe_lines(document.body, candidate_seen)
            if not body:
                continue
            block = (f"【Skill：{document.name} | id={document.skill_id} "
                     f"| version={document.version}】\n{body}")
            cost = len(block) + (2 if entries else 0)
            if not _is_reserved(document) and used + cost > self.max_chars:
                dropped.append(document.skill_id)
                continue
            entries.append((document, block))
            seen = candidate_seen
            used += cost
        order = {doc.skill_id: index for index, doc in enumerate(selection.documents)}
        entries.sort(key=lambda entry: order[entry[0].skill_id])
        prompt = "\n\n".join(block for _, block in entries)

        return SkillMergeResult(
            prompt=prompt,
            skill_ids=tuple(document.skill_id for document in selection.documents),
            versions=selection.versions,
            content_hashes={
                document.skill_id: document.content_hash
                for document in selection.documents
            },
            effective_ids=tuple(doc.skill_id for doc, _ in entries),
            dropped_ids=tuple(dropped),
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
