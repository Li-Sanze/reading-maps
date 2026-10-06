"""Behavior checks using only the original, fictional text in fixtures/source.md."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maps = load_script("validate-reading-map")
courses = load_script("validate-course")


class ValidationCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "original.txt"
        self.source.write_bytes((FIXTURES / "source.md").read_bytes())
        self.course = json.loads((FIXTURES / "course.valid.json").read_text())
        self.course_path = self.root / "course.json"
        self.book_dir = self.root / "book"
        self.book_dir.mkdir()
        (self.book_dir / "reading.html").write_text('<html lang="zh-CN"><body><h1 id="book">小城花园</h1></body></html>')
        self.map = {
            "schema_version": "read-book.dogfood.v1",
            "artifact_kind": "rapid-reading-map",
            "book": {"title_zh": "小城花园观察记", "one_sentence_model": "居民从观察出发维护花园。"},
            "source": copy.deepcopy(self.course["source"]),
            "scope": {"included": "全部自写文本"},
            "reading_contract": {"progressive_depth": ["先读地图再回原文"], "completion_definition": ["能分辨观察和猜想"]},
            "whole_book_model": {"question": "如何谨慎判断一次改造？", "stages": ["观察", "复查"]},
            "claims": [{"id": "observation", "type": "author_position", "statement": "居民先看水流，再做改造。",
                        "short_quote": "小城把空地改成了一座花园。", "locators": [{"start_line": 2, "end_line": 3}]}],
            "core_route": [{"title": "小城的雨水", "why": "检查依据", "start_line": 2, "end_line": 3}],
            "critical_audit": {"limits": ["不能外推其他季节"]},
            "verdict": {"decision": "选读并回到原文"},
            "module_policy": {"generation": "on_demand_only"}, "modules": [],
        }

    def run_map(self, source=True, strict=False, audit=None):
        (self.book_dir / "reading.json").write_text(json.dumps(self.map, ensure_ascii=False))
        return maps.inspect_book(self.book_dir, self.source if source else None, strict, audit)

    def run_course(self, source=True):
        self.course_path.write_text(json.dumps(self.course, ensure_ascii=False))
        return courses.inspect_course(self.course_path, self.source if source else None)

    def assert_clean(self, issues):
        self.assertEqual([], [issue for issue in issues if issue.level == "ERROR"])

    def assert_error(self, issues, pointer):
        self.assertTrue(any(issue.level == "ERROR" and pointer in issue.location for issue in issues), issues)

    def use_epub(self, body, quote, locator, extra_members=None):
        self.source = self.root / "original.epub"
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("OEBPS/chapter001.xhtml", body)
            for member, text in (extra_members or {}).items():
                archive.writestr(member, text)
        self.map["source"] = {"sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(), "format": "EPUB"}
        self.map["claims"][0]["short_quote"] = quote
        self.map["claims"][0]["locators"] = [locator]
        self.map["core_route"] = [{"title": "自写故事", "why": "核对文字"}]


class MapValidationTests(ValidationCase):
    def test_map_positive_and_strict_sections(self):
        audit = {}
        self.assert_clean(self.run_map(strict=True, audit=audit))
        self.assertEqual(audit["documents"][0]["quotes_matched"], 1)

    def test_bad_quote_reports_json_pointer(self):
        self.map["claims"][0]["short_quote"] = "原书没有写过这句话。"
        self.assert_error(self.run_map(), "$.claims[0].short_quote")

    def test_sha_mismatch_stops_quote_checks(self):
        self.map["source"]["sha256"] = "0" * 64
        audit = {}
        self.assert_error(self.run_map(audit=audit), "$.source.sha256")
        self.assertEqual(audit["documents"], [])

    def test_gb18030_source(self):
        self.source.write_bytes((FIXTURES / "source.md").read_text().encode("gb18030"))
        self.map["source"]["sha256"] = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assert_clean(self.run_map())

    def test_line_outside_credible_range(self):
        self.map["claims"][0]["locators"] = [{"start_line": 2, "end_line": 7}]
        self.assert_error(self.run_map(), "$.claims[0]")

    def test_correct_quote_wrong_line_is_rejected(self):
        self.map["claims"][0]["locators"] = [{"start_line": 5, "end_line": 6}]
        self.assert_error(self.run_map(), "$.claims[0].short_quote")

    def test_unlocated_quote_does_not_search_excluded_text(self):
        self.source.write_text(self.source.read_text() + "此行是排除的测试内容。\n")
        self.map["source"]["sha256"] = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.map["source"]["excluded_ranges"] = [{"start_line": 7, "end_line": 7}]
        self.map["claims"][0].pop("locators")
        self.map["claims"][0]["short_quote"] = "此行是排除的测试内容。"
        self.assert_error(self.run_map(), "$.claims[0].short_quote")

    def test_unlocated_quote_excludes_ranges_inside_credible_range(self):
        self.map["source"]["excluded_ranges"] = [{"start_line": 2, "end_line": 2}]
        self.map["claims"][0].pop("locators")
        self.assert_error(self.run_map(), "$.claims[0].short_quote")

    def test_unlocated_quote_cannot_bridge_excluded_lines(self):
        self.source.write_text("前半\n排除的内容\n后半\n")
        self.map["source"].update(sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
                                   credible_range={"start_line": 1, "end_line": 3},
                                   excluded_ranges=[{"start_line": 2, "end_line": 2}])
        self.map["claims"][0].pop("locators")
        self.map["claims"][0]["short_quote"] = "前半后半"
        self.assert_error(self.run_map(), "$.claims[0].short_quote")

    def test_unlocated_quote_keeps_allowed_spans(self):
        self.map["source"]["excluded_ranges"] = [{"start_line": 4, "end_line": 5}, {"start_line": 5, "end_line": 6}]
        self.map["claims"][0].pop("locators")
        self.assert_clean(self.run_map())

    def test_private_paths_inside_prose_match_course_checks(self):
        for private_path in ("/Users/example/book.epub", "/home/example/book.epub", "file:///tmp/book.epub", r"C:\Books\book.epub", "D:/Books/book.epub"):
            with self.subTest(private_path=private_path):
                value = "原书位于" + private_path
                self.map["claims"][0]["statement"] = value
                self.course["units"][0]["position"] = value
                self.assert_error(self.run_map(source=False), "$.claims[0].statement")
                self.assert_error(self.run_course(source=False), "$.units[0].position")

    def test_public_urls_and_relative_paths_remain_valid(self):
        for value in ("https://example.org/home/page", "OEBPS/Text/chapter.xhtml", "books/小城/reading.json"):
            with self.subTest(value=value):
                self.map["claims"][0]["statement"] = value
                self.course["units"][0]["position"] = value
                self.assert_clean(self.run_map(source=False))
                self.assert_clean(self.run_course(source=False))

    def test_marked_author_quote_text_is_checked(self):
        self.map["claims"].append({"id": "explicit", "type": "作者原话", "text": "错误的新句子", "locators": [{"start_line": 2, "end_line": 3}]})
        self.assert_error(self.run_map(), "$.claims[1].text")

    def test_epub_entities_whitespace_only(self):
        self.use_epub('<html><body><p>水 &amp; 土，\n共同养活花朵。</p></body></html>',
                      "水&amp;土，共同养活花朵。", {"epub_path": "OEBPS/chapter001.xhtml"})
        self.assert_clean(self.run_map())
        self.map["claims"][0]["short_quote"] = "水&土,共同养活花朵。"
        self.assert_error(self.run_map(), "$.claims[0].short_quote")

    def test_missing_epub_member(self):
        self.use_epub('<p>第一句。</p>', "第一句。", {"epub_path": "OEBPS/missing.xhtml"})
        self.assert_error(self.run_map(), "$.claims[0].locators[0].epub_path")

    def test_epub_range_and_consecutive_title_blocks(self):
        self.use_epub('<html><head><title>书名</title></head><body><h1>章节</h1><p>第一句。</p><p>第二句。</p></body></html>',
                      "第一句。第二句。", {"epub_path": "OEBPS/chapter001.xhtml", "blocks": "3–4"},
                      {"OEBPS/chapter002.xhtml": "<p>结束。</p>"})
        self.map["source"]["locator_method"] = "块 1 为该书名行；其余为标题和段落。"
        self.map["core_route"][0]["epub_paths"] = ["OEBPS/chapter001.xhtml–chapter002.xhtml"]
        self.assert_clean(self.run_map())

    def test_skipped_blocks_cannot_be_concatenated(self):
        self.use_epub('<p>第一句。</p><p>中间句。</p><p>第三句。</p>', "第一句。第三句。",
                      {"epub_path": "OEBPS/chapter001.xhtml", "blocks": "1,3"})
        self.assert_error(self.run_map(), "$.claims[0].short_quote")

    def test_module_source_book_default_and_inherited_hash(self):
        self.use_epub('<h1>章节</h1><p>第一句。</p>', "第一句。", {"epub_path": "OEBPS/chapter001.xhtml"})
        module = self.book_dir / "modules" / "sample"
        module.mkdir(parents=True)
        (module / "reading.html").write_text('<html lang="zh-CN"><p>模块</p></html>')
        module_data = {"artifact_kind": "deep-dive", "source_book": {"epub_path": "OEBPS/chapter001.xhtml"},
                       "original_reading_selections": [{"excerpt": "第一句。", "paragraph": 1}]}
        (module / "reading.json").write_text(json.dumps(module_data, ensure_ascii=False))
        self.map["modules"] = [{"id": "sample", "status": "generated", "href": "modules/sample/reading.html", "data": "modules/sample/reading.json"}]
        audit = {}
        self.assert_clean(self.run_map(audit=audit))
        self.assertEqual(sum(item["quotes_checked"] for item in audit["documents"]), 2)
        module_data["original_reading_selections"][0]["excerpt"] = "坏掉的模块引文。"
        (module / "reading.json").write_text(json.dumps(module_data, ensure_ascii=False))
        self.assert_error(self.run_map(), "$.original_reading_selections[0].excerpt")

    def test_missing_section_is_warning_unless_strict(self):
        self.map.pop("verdict")
        issues = self.run_map(source=False)
        self.assert_clean(issues)
        self.assertTrue(any(issue.level == "WARNING" and "第 7 项" in issue.message for issue in issues))
        self.assert_error(self.run_map(source=False, strict=True), ":$")


class CourseValidationTests(ValidationCase):
    def test_course_positive(self):
        self.assert_clean(self.run_course())

    def test_bad_start_hint(self):
        self.course["units"][0]["locate"]["start_hint"] = "这里有一片沙漠。"
        self.assert_error(self.run_course(), "$.units[0].locate.start_hint")

    def test_bad_end_hint(self):
        self.course["units"][0]["locate"]["end_hint"] = "这不是原文的结尾。"
        self.assert_error(self.run_course(), "$.units[0].locate.end_hint")

    def test_forward_review(self):
        self.course["units"][0]["review_questions"] = [{"unit_ids": ["care"], "question": "回想后面的章节？", "answer_key": ["尚未学到"]}]
        self.assert_error(self.run_course(), "$.units[0].review_questions[0].unit_ids")

    def test_unsourced_critique(self):
        self.course["units"][0]["critique"][0].pop("sources")
        self.assert_error(self.run_course(), "$.units[0].critique[0].sources")

    def test_long_hint(self):
        self.course["units"][0]["locate"]["start_hint"] = "字" * 21
        self.assert_error(self.run_course(source=False), ".locate.start_hint")

    def test_index_only_needs_no_full_content(self):
        self.course["units"][1] = {key: self.course["units"][1][key] for key in ("id", "order", "status", "locate", "position")}
        self.course["units"][1]["status"] = "index_only"
        self.course["units"][1]["locate"].pop("word_count")
        self.course["units"][1]["locate"].pop("estimated_minutes")
        self.assert_clean(self.run_course())

    def test_duplicate_ids_and_noncontinuous_order(self):
        self.course["units"][1]["id"] = "rain"
        self.course["units"][1]["order"] = 3
        issues = self.run_course(source=False)
        self.assertTrue(any("id 重复" in issue.message for issue in issues))
        self.assertTrue(any("order 必须" in issue.message for issue in issues))

    def test_budget_and_minutes(self):
        self.course["units"][0]["locate"]["estimated_minutes"] = 20
        self.assert_error(self.run_course(source=False), ".locate.estimated_minutes")
        self.course["budget"]["target_minutes"] = float("nan")
        self.assert_error(self.run_course(source=False), "$.budget")

    def test_pre_question_kinds_and_answer_key(self):
        self.course["units"][0]["pre_questions"][0]["kind"] = "self"
        self.course["units"][0]["answer_key"] = {"retelling_points": []}
        issues = self.run_course(source=False)
        self.assert_error(issues, ".pre_questions")
        self.assert_error(issues, ".answer_key")

    def test_private_path_inside_prose(self):
        self.course["units"][0]["position"] = "来源留在 /Users/example/private-book.epub"
        self.assert_error(self.run_course(source=False), ".position")

    def test_course_sha_mismatch(self):
        self.course["source"]["sha256"] = "0" * 64
        self.assert_error(self.run_course(), "$.source.sha256")

    def test_course_sha_matches_same_book_map_without_source(self):
        self.course_path = self.book_dir / "course" / "course.json"
        self.course_path.parent.mkdir()
        (self.book_dir / "reading.json").write_text(json.dumps(self.map, ensure_ascii=False))
        self.assert_clean(self.run_course(source=False))

    def test_course_sha_differs_from_same_book_map_without_source(self):
        self.course_path = self.book_dir / "course" / "course.json"
        self.course_path.parent.mkdir()
        self.map["source"]["sha256"] = "0" * 64
        (self.book_dir / "reading.json").write_text(json.dumps(self.map, ensure_ascii=False))
        self.assert_error(self.run_course(source=False), "$.source.sha256")

    def test_unreadable_same_book_map_is_reported(self):
        (self.root / "reading.json").write_text("not JSON")
        self.assert_error(self.run_course(source=False), "$.source.sha256")

    def test_cli_positive_and_error_exit_codes(self):
        self.run_course()
        command = [sys.executable, str(SCRIPTS / "validate-course.py"), str(self.course_path), "--source", str(self.source)]
        good = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn("PASSED", good.stdout)
        self.course["units"][0]["locate"]["start_hint"] = "没有写过的句子。"
        self.run_course()
        bad = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("$.units[0].locate.start_hint", bad.stdout)


if __name__ == "__main__":
    unittest.main()
