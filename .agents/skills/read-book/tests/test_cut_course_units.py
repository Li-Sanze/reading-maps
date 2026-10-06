"""Cut course units from a synthetic EPUB. No real book text is used."""

import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPO = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CUTTER = SCRIPTS / "cut-course-units.py"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
SKIP_PNG = b"\x89PNG\r\n\x1a\nnot-a-real-book-image"
COURSE_COUNTING_METHOD = (
    "word_count 按所列 EPUB 正文中的非空白字符计，含标题、段落、图题、图注、标点、数字与注号，"
    "不含图片内文字、扩展阅读及参考文献；带 blocks 的文件只计所标范围。"
    "blocks 从正文第一个非空 h1–h6 或 p 文本块起按1编号，不计 head/title。"
)
INCLUDED = [
    "甲节标题",
    "起点在这一句里出现。",
    "中段补上几句 占位说明①。",
    "图题是一朵纸上的云。",
    "回到正文",
    "结束就停在这一句。",
]
EXCLUDED_SENTENCES = [
    "标题之前的导语不该进入单元。",
    "导航文件里的句子不该进入单元。",
    "自定义排除段不该出现。",
    "被排除的附注不该出现在单元里。",
    "文献条目不该进入字数。",
    "结束之后的尾巴不该出现。",
    "下一单元的开头不该混进来。",
    "ANSWER_KEY_SENTINEL_不应出现",
    "CRITIQUE_SENTINEL_不应出现",
    "REVIEW_SENTINEL_不应出现",
]


def visible_count(parts) -> int:
    return len(re.sub(r"\s+", "", "".join(parts)))


def xhtml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>占位</title></head><body>\n'
        f"{body}\n</body></html>\n"
    )


def build_epub(path: Path) -> None:
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>占位笔记</dc:title>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="a-nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>
    <item id="img" href="images/dot.png" media-type="image/png"/>
    <item id="skip" href="images/skip.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
  </spine>
</package>
"""
    nav = xhtml(
        "<h1>甲节标题</h1><p>起点在这一句里出现。</p><p>结束就停在这一句。</p>"
        "<p>导航文件里的句子不该进入单元。</p>"
    )
    chapter_one = xhtml(
        "<p>标题之前的导语不该进入单元。</p>"
        "<h1>甲节标题</h1>"
        "<p>起点在这一句里出现。</p>"
        "<p>中段补上几句 占位说明①。</p>"
        '<figure><img src="images/dot.png" alt="占位小图"/>'
        "<figcaption>图题是一朵纸上的云。</figcaption></figure>"
    )
    chapter_two = xhtml(
        "<h2>附注</h2><p>自定义排除段不该出现。</p>"
        "<h2>扩展阅读</h2><p>被排除的附注不该出现在单元里。</p>"
        '<img src="images/skip.png" alt="排除图"/>'
        "<h2>参考文献</h2><p>文献条目不该进入字数。</p>"
        "<h2>回到正文</h2>"
        "<p>结束就停在这一句。结束之后的尾巴不该出现。</p>"
        "<p>下一单元的开头不该混进来。</p>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/a-nav.xhtml", nav)
        archive.writestr("OEBPS/c1.xhtml", chapter_one)
        archive.writestr("OEBPS/c2.xhtml", chapter_two)
        archive.writestr("OEBPS/images/dot.png", PNG)
        archive.writestr("OEBPS/images/skip.png", SKIP_PNG)


def course_payload(sha256: str, word_count: int, counting_method="去空白后的字符数", excluded=None,
                   start_hint="起点在这一句里出现。", end_hint="结束就停在这一句。"):
    if excluded is None:
        excluded = [{"scope": "各章“附注”", "reason": "占位排除，不进入单元。"}]
    return {
        "book": {"title_zh": "占位笔记"},
        "source": {"sha256": sha256, "format": "EPUB"},
        "scope": {"excluded": excluded},
        "reading_notes": {"counting_method": counting_method} if counting_method is not None else None,
        "units": [
            {"id": "zs-u01", "order": 1},
            {
                "id": "zs-u02",
                "order": 2,
                "locate": {
                    "navigation": ["甲节标题"],
                    "chapter": "甲节",
                    "start_hint": start_hint,
                    "end_hint": end_hint,
                    "word_count": word_count,
                    "estimated_minutes": 8,
                },
                "pre_questions": [
                    {"kind": "structure", "question": "这一节从哪一句开始？"},
                    {"kind": "argument", "question": "占位说明承担什么作用？"},
                    {"kind": "self", "question": "你会把哪一句留到复习？"},
                ],
                "watch": {"concept": "占位边界", "why": "用来核对切分是否停在结束提示。"},
                "answer_key": {"retelling_points": ["ANSWER_KEY_SENTINEL_不应出现"]},
                "critique": [{"text": "CRITIQUE_SENTINEL_不应出现"}],
                "review_questions": [{"question": "REVIEW_SENTINEL_不应出现"}],
            },
        ],
    }


class CutCourseUnitsTests(unittest.TestCase):
    expected_count = visible_count(INCLUDED)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.epub = self.root / "placeholder.epub"
        build_epub(self.epub)
        self.sha = hashlib.sha256(self.epub.read_bytes()).hexdigest()

    def write_course(self, **kwargs):
        word_count = kwargs.pop("word_count", self.expected_count)
        payload = course_payload(self.sha, word_count, **kwargs)
        if payload.get("reading_notes") is None:
            payload.pop("reading_notes")
        path = self.root / "course.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def run_cut(self, course, out, units="zs-u02", extra=None, cwd=None):
        command = [
            sys.executable, str(CUTTER),
            "--source", str(self.epub),
            "--course", str(course),
            "--out", str(out),
            "--units", units,
        ]
        if extra:
            command.extend(extra)
        return subprocess.run(command, capture_output=True, text=True, cwd=cwd)

    def test_cuts_across_files_includes_title_skips_excluded_sections_and_embeds_image(self):
        course = self.write_course()
        out = self.root / "out"
        result = self.run_cut(course, out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        html_path = out / "zs-u02.html"
        manifest_path = out / "manifest.json"
        self.assertEqual(sorted(path.name for path in out.iterdir()), ["manifest.json", "zs-u02.html"])
        page = html_path.read_text(encoding="utf-8")
        self.assertIn("占位笔记 · 第 2/2 单元 · 甲节 · 约 8 分钟", page)
        self.assertIn("<h2>带着读</h2>", page)
        self.assertLess(page.index("这一节从哪一句开始？"), page.index("占位说明承担什么作用？"))
        self.assertLess(page.index("占位说明承担什么作用？"), page.index("你会把哪一句留到复习？"))
        self.assertIn("留意概念：<span class=\"concept\">占位边界</span>", page)
        self.assertIn("用来核对切分是否停在结束提示。", page)
        self.assertIn("读完回学伴：三句复述＋三个问题的回答＋一个质疑", page)
        self.assertIn("仅供 Sanze 个人阅读，请勿转发", page)
        for part in INCLUDED:
            self.assertIn(part, page)
        for sentence in EXCLUDED_SENTENCES:
            self.assertNotIn(sentence, page)
        self.assertNotIn(">附注<", page)
        self.assertNotIn(">扩展阅读<", page)
        self.assertNotIn(">参考文献<", page)
        encoded = base64.standard_b64encode(PNG).decode("ascii")
        skipped = base64.standard_b64encode(SKIP_PNG).decode("ascii")
        self.assertIn(encoded, page)
        self.assertNotIn(skipped, page)
        self.assertRegex(
            page,
            r'<figure><img src="data:image/png;base64,[^"]+" alt="占位小图"><figcaption>图题是一朵纸上的云。</figcaption></figure>',
        )
        self.assertNotIn('src="images/', page)
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("<link", page.lower())
        self.assertNotIn("@import", page.lower())
        self.assertNotIn("fonts.google", page.lower())
        for token in ("#f8f5ef", "#293947", "#697575", "#deded3", "#526960",
                      "Songti SC", "STSong", "Noto Serif CJK SC", "17px", "1.95", "700px", "16px"):
            self.assertIn(token, page)
        self.assertLess(page.index("带着读"), page.index("<article>"))
        self.assertLess(page.index("<article>"), page.index("读完回学伴"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_sha256"], self.sha)
        self.assertEqual(manifest["course_sha256"], self.sha)
        self.assertEqual(manifest["counting_method"], "去空白后的字符数")
        self.assertEqual(len(manifest["units"]), 1)
        unit = manifest["units"][0]
        self.assertEqual(unit["id"], "zs-u02")
        self.assertEqual(unit["word_count"], self.expected_count)
        self.assertEqual(unit["source_sha256"], self.sha)
        self.assertEqual(unit["sha256"], hashlib.sha256(html_path.read_bytes()).hexdigest())
        self.assertNotIn("占位小图", re.sub(r"\s+", "", "".join(INCLUDED)))

    def test_string_exclusion_label_skips_section(self):
        course = self.write_course(excluded=["附注"])
        out = self.root / "string-out"
        result = self.run_cut(course, out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        page = (out / "zs-u02.html").read_text(encoding="utf-8")
        self.assertNotIn("自定义排除段不该出现。", page)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["word_count"], self.expected_count)

    def test_missing_end_hint_fails_without_output(self):
        course = self.write_course(end_hint="这里没有这句话。")
        out = self.root / "missing-end"
        result = self.run_cut(course, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("找不到结束提示", result.stdout)
        self.assertIn("这里没有这句话。", result.stdout)
        self.assertFalse(out.exists())

    def test_missing_start_hint_fails_without_output(self):
        course = self.write_course(start_hint="起点并不存在。")
        out = self.root / "missing-start"
        result = self.run_cut(course, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("找不到起始提示", result.stdout)
        self.assertIn("起点并不存在。", result.stdout)
        self.assertFalse(out.exists())

    def test_word_count_mismatch_fails_without_output(self):
        course = self.write_course(word_count=self.expected_count + 3)
        out = self.root / "bad-count"
        result = self.run_cut(course, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"字数不符：zs-u02：actual={self.expected_count} expected={self.expected_count + 3}",
            result.stdout,
        )
        self.assertIn("counting_method=去空白后的字符数", result.stdout)
        self.assertFalse(out.exists())

    def test_output_inside_repository_is_refused(self):
        course = self.write_course()
        relative = "cut-out-should-not-exist"
        result = self.run_cut(course, relative, cwd=REPO)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git 工作树", result.stdout)
        self.assertFalse((REPO / relative).exists())
        nested = REPO / "books" / "cut-out-should-not-exist"
        absolute = self.run_cut(course, nested)
        self.assertNotEqual(absolute.returncode, 0)
        self.assertIn("git 工作树", absolute.stdout)
        self.assertFalse(nested.exists())

    def test_script_imports_stdlib_only(self):
        tree = ast.parse(CUTTER.read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(node.level, "relative import")
                modules.append((node.module or "").split(".")[0])
        self.assertTrue(modules)
        for name in modules:
            self.assertIn(name, sys.stdlib_module_names, name)

    def test_default_counting_method_matches_non_whitespace_chars(self):
        course = self.write_course(counting_method=None)
        out = self.root / "default-count"
        result = self.run_cut(course, out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counting_method"], "去空白后的字符数")
        self.assertEqual(manifest["units"][0]["word_count"], self.expected_count)
        self.assertNotEqual(self.expected_count, visible_count(INCLUDED) + INCLUDED[2].count(" "))

    def test_course_counting_method_text_is_accepted(self):
        course = self.write_course(counting_method=COURSE_COUNTING_METHOD)
        out = self.root / "long-method"
        result = self.run_cut(course, out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counting_method"], COURSE_COUNTING_METHOD)
        self.assertEqual(manifest["units"][0]["word_count"], self.expected_count)

    def test_unknown_counting_method_fails(self):
        course = self.write_course(counting_method="按词计数，忽略标点")
        out = self.root / "unknown-method"
        result = self.run_cut(course, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未知计数口径", result.stdout)
        self.assertFalse(out.exists())

    def test_edition_mismatch_reports_and_writes_nothing(self):
        payload = course_payload(self.sha, self.expected_count)
        payload["source"]["sha256"] = "0" * 64
        course = self.root / "edition-course.json"
        course.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        out = self.root / "edition-out"
        result = self.run_cut(course, out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("异版", result.stdout)
        self.assertIn(f"expected={'0' * 64}", result.stdout)
        self.assertIn(f"actual={self.sha}", result.stdout)
        self.assertIn(f"字数 actual={self.expected_count} expected={self.expected_count}", result.stdout)
        self.assertIn("标题差异", result.stdout)
        self.assertIn("多出 回到正文", result.stdout)
        self.assertIn("未写入输出", result.stdout)
        self.assertFalse(out.exists())

    def test_accept_edition_requires_matching_word_count(self):
        payload = course_payload(self.sha, self.expected_count)
        payload["source"]["sha256"] = "0" * 64
        course = self.root / "accept-course.json"
        course.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        accepted = self.root / "accepted"
        ok = self.run_cut(course, accepted, extra=["--accept-edition"])
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue((accepted / "zs-u02.html").is_file())
        manifest = json.loads((accepted / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_sha256"], self.sha)
        self.assertEqual(manifest["course_sha256"], "0" * 64)
        self.assertEqual(manifest["units"][0]["word_count"], self.expected_count)

        payload["units"][1]["locate"]["word_count"] = self.expected_count + 1
        rejected_course = self.root / "accept-bad.json"
        rejected_course.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        rejected = self.root / "accepted-bad"
        bad = self.run_cut(rejected_course, rejected, extra=["--accept-edition"])
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("字数不符", bad.stdout)
        self.assertFalse(rejected.exists())


if __name__ == "__main__":
    unittest.main()
