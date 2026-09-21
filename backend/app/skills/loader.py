"""Load and validate project writing skills.

The loader deliberately has no dependency on FastAPI or the chapter service so it
can be tested in isolation and reused by CLI/admin tooling later.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_DEFAULT_VERSION = "1.0.0"


@dataclass(frozen=True)
class SkillDocument:
    skill_id: str
    name: str
    description: str
    version: str
    layer: str
    priority: int
    body: str
    path: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def versioned_id(self) -> str:
        return f"{self.skill_id}@{self.version}"


class SkillLoader:
    """Discover, parse and validate ``backend/skills/*/SKILL.md`` files."""

    def __init__(self, skills_root: str | Path | None = None):
        self.skills_root = Path(skills_root) if skills_root else (
            Path(__file__).resolve().parents[2] / "skills"
        )
        self._cache: dict[str, SkillDocument] | None = None

    def load_all(self, *, force: bool = False) -> dict[str, SkillDocument]:
        if self._cache is not None and not force:
            return dict(self._cache)

        documents: dict[str, SkillDocument] = {}
        if not self.skills_root.is_dir():
            self._cache = {}
            return {}

        # Support both the original flat layout and grouped skills such as
        # ``writer_skills/<author>/SKILL.md``.
        for skill_file in sorted(self.skills_root.glob("**/SKILL.md")):
            # Skip vendored/reference repos (e.g. cloned humanizer skills under
            # ai_detection_skills). They ship their own SKILL.md but are only
            # reference material — a ``.git`` ancestor marks them as external.
            if self._is_vendored(skill_file):
                continue
            document = self._parse_file(skill_file)
            if document.skill_id in documents:
                previous = documents[document.skill_id]
                raise ValueError(
                    f"duplicate skill id '{document.skill_id}': "
                    f"{previous.path} and {document.path}"
                )
            documents[document.skill_id] = document

        self._cache = documents
        return dict(documents)

    def _is_vendored(self, skill_file: Path) -> bool:
        """True if the skill lives inside a cloned repo (has a ``.git`` ancestor)."""
        for parent in skill_file.parents:
            if parent == self.skills_root:
                break
            if (parent / ".git").exists():
                return True
        return False

    def get(self, skill_id: str) -> SkillDocument | None:
        return self.load_all().get(skill_id)

    def validate(self) -> list[str]:
        """Return validation errors without preventing the app from starting."""
        errors: list[str] = []
        try:
            documents = self.load_all(force=True)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return [str(exc)]

        for skill_id, document in documents.items():
            if not skill_id:
                errors.append(f"{document.path}: missing id")
            if not document.name:
                errors.append(f"{document.path}: missing name")
            if not document.body.strip():
                errors.append(f"{document.path}: empty body")
            if not re.fullmatch(r"\d+\.\d+\.\d+", document.version):
                errors.append(
                    f"{document.path}: invalid version '{document.version}', "
                    "expected MAJOR.MINOR.PATCH"
                )
            if document.layer not in {"base", "genre", "capability", "style", "quality"}:
                errors.append(
                    f"{document.path}: invalid layer '{document.layer}'"
                )
        return errors

    def _parse_file(self, path: Path) -> SkillDocument:
        raw = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(raw)
        if match:
            metadata = yaml.safe_load(match.group(1)) or {}
            body = match.group(2).strip()
        else:
            metadata = {}
            body = raw.strip()

        if not isinstance(metadata, dict):
            raise ValueError(f"{path}: frontmatter must be a mapping")

        skill_id = str(metadata.get("id") or path.parent.name).strip()
        name = str(metadata.get("name") or skill_id).strip()
        description = str(metadata.get("description") or "").strip()
        version = str(metadata.get("version") or _DEFAULT_VERSION).strip()
        layer = str(metadata.get("layer") or self._infer_layer(skill_id)).strip()
        try:
            priority = int(metadata.get("priority", self._default_priority(layer)))
        except (TypeError, ValueError):
            priority = self._default_priority(layer)

        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return SkillDocument(
            skill_id=skill_id,
            name=name,
            description=description,
            version=version,
            layer=layer,
            priority=priority,
            body=body,
            path=str(path),
            content_hash=digest,
            metadata=metadata,
        )

    @staticmethod
    def _infer_layer(skill_id: str) -> str:
        if skill_id.startswith("writer-"):
            return "style"
        if "anti-ai" in skill_id:
            return "quality"
        if skill_id == "novel-general":
            return "base"
        if skill_id in {
            "novel-anime", "novel-apocalypse", "novel-fantasy",
            "novel-general", "novel-historical-politics", "novel-light-novel",
            "novel-military", "novel-mystery", "novel-realism",
            "novel-romance", "novel-sci-fi", "novel-sports",
            "novel-supernatural", "novel-urban-romance", "novel-wuxia",
            "novel-xuanhuan",
        }:
            return "genre"
        return "capability"

    @staticmethod
    def _default_priority(layer: str) -> int:
        return {
            "base": 10, "genre": 50, "capability": 80,
            "style": 70, "quality": 95,
        }.get(layer, 80)
