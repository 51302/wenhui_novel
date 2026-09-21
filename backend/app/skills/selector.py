"""Select writing skills from explicit choices and novel/chapter context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.skills.loader import SkillDocument, SkillLoader


@dataclass(frozen=True)
class SkillSelection:
    documents: tuple[SkillDocument, ...]
    reasons: dict[str, tuple[str, ...]]

    @property
    def ids(self) -> list[str]:
        return [doc.skill_id for doc in self.documents]

    @property
    def versions(self) -> dict[str, str]:
        return {doc.skill_id: doc.version for doc in self.documents}


class SkillSelector:
    """Deterministic selector; explicit user choices always win over heuristics."""

    _ALIASES = {
        "玄幻": ("novel-xuanhuan",),
        "修仙": ("novel-xuanhuan", "novel-xuanhuan-subgenres"),
        "仙侠": ("novel-xuanhuan", "novel-xuanhuan-subgenres"),
        "都市": ("novel-urban-romance", "novel-urban-subgenres"),
        "言情": ("novel-urban-romance", "novel-romance-settings"),
        "恋爱": ("novel-romance-settings",),
        "悬疑": ("novel-mystery",),
        "推理": ("novel-mystery",),
        "刑侦": ("novel-mystery",),
        "末世": ("novel-apocalypse",),
        "灾难": ("novel-apocalypse",),
        "奇幻": ("novel-fantasy",),
        "科幻": ("novel-sci-fi",),
        "校园": ("novel-light-novel",),
        "游戏": ("novel-game",),
        "网游": ("novel-game",),
        "无限流": ("novel-infinite-flow",),
        "系统": ("novel-cheat-system",),
        "金手指": ("novel-cheat-system",),
        "外挂": ("novel-cheat-system",),
        "世界观": ("novel-world-settings",),
        "世界设定": ("novel-world-settings",),
        "文风": ("novel-writing-styles",),
        "语言风格": ("novel-writing-styles",),
        "军事": ("novel-military",),
        "战争": ("novel-military",),
        "武侠": ("novel-wuxia",),
        "江湖": ("novel-wuxia",),
        "体育": ("novel-sports",),
        "竞技": ("novel-sports",),
        "灵异": ("novel-supernatural",),
        "恐怖": ("novel-supernatural",),
    }

    def __init__(self, loader: SkillLoader | None = None):
        self.loader = loader or SkillLoader()

    def select(
        self,
        *,
        genre: str = "",
        summary: str = "",
        settings: str = "",
        character_text: str = "",
        explicit: str | Iterable[str] | None = None,
        include_quality: bool = True,
    ) -> SkillSelection:
        try:
            documents = self.loader.load_all()
        except (OSError, ValueError):
            # Skill files are optional prompt extensions. A malformed or
            # duplicated file must not take down chapter generation.
            return SkillSelection((), {})
        if not documents:
            return SkillSelection((), {})

        context = " ".join(
            value.strip() for value in (genre, summary, settings, character_text)
            if value
        )
        selected: dict[str, SkillDocument] = {}
        reasons: dict[str, list[str]] = {}

        def add(skill_id: str, reason: str) -> None:
            document = documents.get(skill_id)
            if document is None:
                return
            selected[skill_id] = document
            reasons.setdefault(skill_id, []).append(reason)

        # The generic skill is the stable fallback for all chapter generation.
        if "novel-general" in documents:
            add("novel-general", "默认基础 Skill")

        # Quality/anti-AI skills apply to every generation regardless of genre,
        # unless the caller opts out (e.g. chapter-level "反AI检测" toggle off).
        if include_quality:
            for skill_id, document in documents.items():
                if document.layer == "quality":
                    add(skill_id, "质量控制 Skill（全量注入）")

        explicit_ids = self._normalize_explicit(explicit, documents)
        for skill_id in explicit_ids:
            add(skill_id, "用户明确指定")

        for keyword, skill_ids in self._ALIASES.items():
            if keyword in context:
                for skill_id in skill_ids:
                    add(skill_id, f"上下文命中关键词：{keyword}")

        # Use the document metadata as a secondary route for future skills that
        # declare their own trigger list, without hard-coding every new skill.
        for document in documents.values():
            triggers = document.metadata.get("triggers") or []
            if isinstance(triggers, str):
                triggers = [triggers]
            for trigger in triggers:
                if trigger and str(trigger) in context:
                    add(document.skill_id, f"Skill 元数据命中：{trigger}")
                    break

        ordered = sorted(
            selected.values(),
            key=lambda doc: (doc.layer != "base", doc.priority, doc.skill_id),
        )
        return SkillSelection(
            tuple(ordered),
            {key: tuple(value) for key, value in reasons.items()},
        )

    @staticmethod
    def _normalize_explicit(
        explicit: str | Iterable[str] | None,
        documents: dict[str, SkillDocument],
    ) -> list[str]:
        if not explicit:
            return []
        values = [explicit] if isinstance(explicit, str) else list(explicit)
        result: list[str] = []
        by_name = {doc.name: doc.skill_id for doc in documents.values()}
        # Legacy compatibility: writer skills keep the old author_style id in
        # frontmatter (author_style_id: chendong), and the作品 writing_style_id
        # may store either "chendong" or "writer-chendong".
        by_author_style = {
            str(doc.metadata.get("author_style_id")): doc.skill_id
            for doc in documents.values()
            if doc.metadata.get("author_style_id")
        }
        for value in values:
            for item in re.split(r"[,，\s]+", str(value).strip()):
                if not item:
                    continue
                skill_id = (
                    item if item in documents
                    else by_name.get(item)
                    or by_author_style.get(item)
                    or (f"writer-{item}" if f"writer-{item}" in documents else None)
                )
                if skill_id and skill_id not in result:
                    result.append(skill_id)
        return result
