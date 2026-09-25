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
    # 用户显式指定的 Skill（章节 skill_ids / author_style / 作品默认风格）。
    # 合并阶段的长度上限不得把它们整段省略——显式选择优先于关键词启发式命中。
    explicit_ids: frozenset[str] = frozenset()

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
        "纯爱": ("novel-romance-settings",),
        "现言": ("novel-urban-romance", "novel-urban-subgenres"),
        "总裁": ("novel-urban-romance", "novel-urban-subgenres"),
        "女强": ("novel-urban-romance",),
        "悬疑": ("novel-mystery",),
        "推理": ("novel-mystery",),
        "刑侦": ("novel-mystery",),
        "末世": ("novel-apocalypse",),
        "灾难": ("novel-apocalypse",),
        "奇幻": ("novel-fantasy",),
        "幻想": ("novel-fantasy",),
        "科幻": ("novel-sci-fi",),
        "校园": ("novel-light-novel",),
        "轻小说": ("novel-light-novel",),
        "历史": ("novel-historical-politics",),
        "古言": ("novel-historical-politics",),
        "宫斗": ("novel-historical-politics",),
        "宅斗": ("novel-historical-politics",),
        "清穿": ("novel-historical-politics",),
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

    # 「只有标签、没有内容」的设定行（如标准设定模板里的 "世界观设定："、"剧情发展路线："）。
    # 这类空标签会命中别名/元数据触发器，把和本章正文无关的 Skill 拖进来——历史实测：
    # 设定模板固定带的 "剧情发展路线：" 命中了 novel-outline 的触发器，
    # 于是每章正文都注入了一份"章节概要规划"规则。
    _EMPTY_LABEL_RE = re.compile(r"^\s*[^：:\s]{1,16}[：:]\s*$", re.MULTILINE)

    # 规划/设计类 Skill：只在各自规划流程里用（章节概要规划由
    # ChapterService.generate_outline_with_ai 直接走提示词，不经过本选择器），
    # 注入正文生成只会污染写作规则。
    _BODY_EXCLUDED = frozenset({"novel-outline"})

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
            value.strip() for value in (
                genre, summary, self._content_only(settings), character_text)
            if value
        )
        selected: dict[str, SkillDocument] = {}
        reasons: dict[str, list[str]] = {}

        def add(skill_id: str, reason: str) -> None:
            document = documents.get(skill_id)
            if document is None or (document.layer == "quality" and not include_quality):
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

        explicit_choices = self._normalize_explicit(explicit, documents)
        for skill_id in explicit_choices:
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
            (document for skill_id, document in selected.items()
             if skill_id not in self._BODY_EXCLUDED),
            key=lambda doc: (doc.layer != "base", doc.priority, doc.skill_id),
        )
        kept = {document.skill_id for document in ordered}
        return SkillSelection(
            tuple(ordered),
            {key: tuple(value) for key, value in reasons.items() if key in kept},
            frozenset(skill_id for skill_id in explicit_choices if skill_id in kept),
        )

    @classmethod
    def _content_only(cls, settings: str) -> str:
        """剔除"只有标签没有内容"的设定行后再参与关键词匹配。

        取值不为空的标签行原样保留（其内容仍可作为题材线索）。
        """
        if not settings:
            return ""
        return cls._EMPTY_LABEL_RE.sub("", settings)

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
