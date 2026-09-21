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

    # ------------------------------------------------------------------
    # 长度上限：base / quality / 用户显式指定 不得被整段省略
    # ------------------------------------------------------------------

    @staticmethod
    def _write_sized_skill(root: Path, folder: str, meta: str, body_len: int) -> None:
        # 正文首行带上 folder 名，避免多个 Skill 因内容逐行相同被合并去重（真实 Skill 不会这样）
        body = folder + "本" * max(body_len - len(folder), 1)
        _write_skill(
            root, folder,
            f"---\n{meta}\nversion: 1.0.0\n---\n\n{body}")

    def test_merger_never_drops_base_or_quality_over_budget(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            self._write_sized_skill(
                tmp_path, "novel-general", "name: 通用\nlayer: base", 200)
            self._write_sized_skill(
                tmp_path, "novel-anti-ai", "name: 反AI\nlayer: quality", 200)
            self._write_sized_skill(
                tmp_path, "novel-xuanhuan", "name: 玄幻\nlayer: genre", 600)

            selection = SkillSelector(SkillLoader(tmp_path)).select(genre="玄幻")
            self.assertIn("novel-xuanhuan", selection.ids)

            # 预算只够必需层 → 可选层整体省略，但 base/quality 必须保留
            merged = SkillMerger(max_chars=600).merge(selection)
            self.assertIn("novel-general", merged.effective_ids)
            self.assertIn("novel-anti-ai", merged.effective_ids)
            self.assertEqual(merged.dropped_ids, ("novel-xuanhuan",))
            self.assertIn("novel-anti-ai", merged.prompt)
            self.assertNotIn("【Skill：玄幻", merged.prompt)

            # 预算充足 → 不省略任何 Skill
            merged_big = SkillMerger(max_chars=8000).merge(selection)
            self.assertEqual(merged_big.dropped_ids, ())
            self.assertIn("novel-xuanhuan", merged_big.effective_ids)

    def test_merger_protects_explicitly_selected_skill(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            self._write_sized_skill(
                tmp_path, "novel-general", "name: 通用\nlayer: base", 200)
            self._write_sized_skill(
                tmp_path, "writer-chendong",
                "name: 辰东\nlayer: style\nauthor_style_id: chendong", 300)
            self._write_sized_skill(
                tmp_path, "novel-xuanhuan", "name: 玄幻\nlayer: genre", 400)

            selection = SkillSelector(SkillLoader(tmp_path)).select(
                genre="玄幻", explicit="chendong")
            self.assertEqual(selection.explicit_ids, frozenset({"writer-chendong"}))

            merged = SkillMerger(max_chars=800).merge(selection)
            # 用户明确选的作家风格优先于关键词命中的题材
            self.assertIn("writer-chendong", merged.effective_ids)
            self.assertNotIn("novel-xuanhuan", merged.effective_ids)
            self.assertEqual(merged.dropped_ids, ("novel-xuanhuan",))

    # ------------------------------------------------------------------
    # 选择：空标签噪音 / 题材别名 / 正文排除规划类 Skill
    # ------------------------------------------------------------------

    def test_selector_ignores_settings_template_empty_labels(self):
        """设定模板里的"世界观设定：""剧情发展路线："只是空标签，不该命中 Skill。"""
        selection = SkillSelector().select(
            genre="修仙,玄幻",
            summary="主角在宗门修炼。",
            settings="作品名称：aaa\n世界观设定：\n标签：修仙,玄幻\n剧情发展路线：无\n",
            include_quality=True,
        )
        ids = selection.ids
        self.assertNotIn("novel-world-settings", ids)
        self.assertNotIn("novel-outline", ids)
        self.assertIn("novel-xuanhuan", ids)

    def test_selector_excludes_planning_skill_from_body_writing(self):
        """novel-outline 属概要规划（规划流程不走选择器），不得注入正文生成。"""
        selection = SkillSelector().select(
            genre="玄幻",
            summary="本章继续推进。",
            settings="章节概要：主角夺宝。\n剧情发展路线：主角一路升级。",
            include_quality=True,
        )
        self.assertNotIn("novel-outline", selection.ids)

    def test_selector_routes_frontend_genres(self):
        expected = {
            "历史": "novel-historical-politics",
            "古言": "novel-historical-politics",
            "宫斗": "novel-historical-politics",
            "轻小说": "novel-light-novel",
            "现言": "novel-urban-romance",
            "总裁": "novel-urban-romance",
        }
        for genre, skill_id in expected.items():
            with self.subTest(genre=genre):
                ids = SkillSelector().select(genre=genre, include_quality=False).ids
                self.assertIn(skill_id, ids)


if __name__ == "__main__":
    unittest.main()
