from pathlib import Path
import unittest

from app.skills.loader import SkillLoader
from app.skills.merger import SkillMerger
from app.skills.selector import SkillSelector


def _write_skill(root: Path, folder: str, content: str) -> None:
    path = root / folder
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(content, encoding="utf-8")


class SkillRuntimeTests(unittest.TestCase):
    def test_loader_reads_version_and_hash(self):
        with self.subTest("version"):
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                _write_skill(
                    tmp_path,
                    "novel-general",
                    "---\nname: 通用\nversion: 1.2.3\nlayer: base\n---\n\n通用规则",
                )
                document = SkillLoader(tmp_path).get("novel-general")
                self.assertIsNotNone(document)
                self.assertEqual(document.version, "1.2.3")
                self.assertTrue(document.content_hash)
                self.assertEqual(document.versioned_id, "novel-general@1.2.3")

    def test_selector_combines_explicit_and_context_skills(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            _write_skill(
                tmp_path,
                "novel-general",
                "---\nname: 通用\nversion: 1.0.0\nlayer: base\n---\n\n通用规则",
            )
            _write_skill(
                tmp_path,
                "novel-xuanhuan",
                "---\nname: 玄幻\nversion: 2.0.0\nlayer: genre\n---\n\n玄幻规则",
            )
            _write_skill(
                tmp_path,
                "novel-world-settings",
                "---\nname: 世界设定\nversion: 1.0.0\nlayer: capability\n---\n\n世界规则",
            )
            selection = SkillSelector(SkillLoader(tmp_path)).select(
                genre="玄幻",
                settings="世界观：宗门",
                explicit="novel-world-settings",
            )
            self.assertEqual(
                selection.ids,
                ["novel-general", "novel-xuanhuan", "novel-world-settings"],
            )
            self.assertIn(
                "用户明确指定",
                selection.reasons["novel-world-settings"],
            )

    def test_merger_deduplicates_and_keeps_version(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            _write_skill(
                tmp_path,
                "a",
                "---\nname: A\nversion: 1.0.0\nlayer: base\n---\n\n共同规则\nA规则",
            )
            _write_skill(
                tmp_path,
                "b",
                "---\nname: B\nversion: 1.1.0\nlayer: capability\n---\n\n共同规则\nB规则",
            )
            selection = SkillSelector(SkillLoader(tmp_path)).select(explicit="a,b")
            merged = SkillMerger().merge(selection)
            self.assertEqual(merged.prompt.count("共同规则"), 1)
            self.assertEqual(merged.versions, {"a": "1.0.0", "b": "1.1.0"})


if __name__ == "__main__":
    unittest.main()
