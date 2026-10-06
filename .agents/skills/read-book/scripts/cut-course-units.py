#!/usr/bin/env python3
"""Cut course units from an EPUB into self-contained HTML outside any git worktree.

navigation[0] locates the chapter in spine order. The excerpt starts at
start_hint. When that hint begins a block, or is itself a heading, the
contiguous headings immediately before it are included, back through the
anchor when nothing but headings lies between them. A hint inside a paragraph
drops the earlier text of that paragraph and does not pull headings. The
excerpt stops at the end of end_hint. Word counts are non-whitespace
characters. A mismatch fails; nothing here adjusts the count.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile


CANONICAL_COUNTING_METHOD = "去空白后的字符数"
COUNTING_MARKERS = (
    "非空白字符",
    "含标题",
    "段落",
    "图题",
    "图注",
    "标点",
    "数字",
    "注号",
    "不含图片内文字",
    "扩展阅读",
    "参考文献",
)
ALWAYS_EXCLUDED_HEADINGS = ("扩展阅读", "参考文献")
QUOTE_RE = re.compile(r"[“「『\"‘']([^”」』\"’']+)[”」』\"’']")
WHITESPACE_RE = re.compile(r"\s+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IGNORE_TAGS = {"script", "style", "head", "svg", "nav"}
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "figcaption", "pre", "td", "th"}
MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

PAGE_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
html, body {
  margin: 0;
  background: #f8f5ef;
  color: #293947;
}
body {
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
  font-size: 17px;
  line-height: 1.95;
}
main {
  box-sizing: border-box;
  width: min(700px, 100%);
  margin: 0 auto;
  padding: 1.25rem 16px 3rem;
}
h1, h2, h3, h4, h5, h6 {
  font-family: "Songti SC", STSong, "Noto Serif CJK SC", serif;
  line-height: 1.4;
  color: #293947;
}
.meta, footer, .why, figcaption { color: #697575; }
hr { border: 0; border-top: 1px solid #deded3; margin: 1.4em 0; }
.prep h2, .concept { color: #526960; }
article p, article li, article blockquote { margin: 0 0 1em; }
img, svg { max-width: 100%; height: auto; }
figure { margin: 1.2em 0; }
""".strip()


class CutError(Exception):
    def __init__(self, message: str, rank: int = 0):
        super().__init__(message)
        self.rank = rank


@dataclass
class Block:
    kind: str
    level: int
    text: str
    alt: str = ""
    src: str = ""
    member: str = ""
    tag: str = "p"


@dataclass
class UnitDraft:
    unit_id: str
    expected_count: int | None
    expected_titles: list[str]
    found_titles: list[str] = field(default_factory=list)
    actual_count: int | None = None
    html: str | None = None
    error: str | None = None


def normalize(text: str) -> str:
    return WHITESPACE_RE.sub("", html.unescape(text or ""))


def visible_count(text: str) -> int:
    return len(WHITESPACE_RE.sub("", text))


def hint_span(raw: str, hint: str) -> tuple[int, int] | None:
    needle = normalize(hint)
    if not needle:
        return None
    kept = []
    indexes = []
    for index, char in enumerate(raw):
        if WHITESPACE_RE.match(char):
            continue
        kept.append(char)
        indexes.append(index)
    found = "".join(kept).find(needle)
    if found < 0:
        return None
    return indexes[found], indexes[found + len(needle) - 1] + 1


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xml(raw: bytes) -> ET.Element:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise CutError(f"无法解析 EPUB XML：{exc}") from exc


def zip_join(base_member: str, href: str) -> str:
    cleaned = unquote(href.strip())
    cleaned = cleaned.split("#", 1)[0].split("?", 1)[0]
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", cleaned):
        raise CutError(f"图片不是 EPUB 内部文件：{href}")
    if cleaned.startswith("/"):
        parts = list(PurePosixPath(cleaned).parts[1:])
    else:
        parts = list((PurePosixPath(base_member).parent / cleaned).parts)
    stack = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise CutError(f"图片路径越界：{href}")
            stack.pop()
            continue
        stack.append(part)
    return "/".join(stack)


def inside_git_worktree(path: Path) -> bool:
    current = path.expanduser().resolve(strict=False)
    for candidate in (current, *current.parents):
        git_entry = candidate / ".git"
        if git_entry.is_dir() or git_entry.is_file():
            return True
    return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_counting_method(text: str | None) -> str:
    if text is None or not text.strip():
        return CANONICAL_COUNTING_METHOD
    stripped = text.strip()
    if stripped == CANONICAL_COUNTING_METHOD:
        return CANONICAL_COUNTING_METHOD
    if "不含标点" in stripped or "不计标点" in stripped:
        raise CutError(f"未知计数口径：{stripped}")
    if all(marker in stripped for marker in COUNTING_MARKERS):
        return CANONICAL_COUNTING_METHOD
    raise CutError(f"未知计数口径：{stripped}")


def exclusion_labels(entries) -> set[str]:
    labels = {normalize(title) for title in ALWAYS_EXCLUDED_HEADINGS}
    for entry in entries:
        if isinstance(entry, str):
            label = normalize(entry)
            if label:
                labels.add(label)
            continue
        if not isinstance(entry, dict):
            raise CutError("scope.excluded 每项须为字符串或含 scope 的对象")
        text = entry.get("scope", entry.get("title"))
        if not isinstance(text, str) or not text.strip():
            raise CutError("scope.excluded 缺少 scope 文字")
        whole = normalize(text)
        if whole:
            labels.add(whole)
        for quoted in QUOTE_RE.findall(text):
            label = normalize(quoted)
            if label:
                labels.add(label)
        for part in re.split(r"[、,，]", text):
            part = re.sub(r"^(各章|每章|章末|书末)", "", part.strip())
            part = part.strip("“”「」『』\"'‘’ ")
            label = normalize(part)
            if label:
                labels.add(label)
    labels.discard("")
    return labels


def require_text(value, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CutError(message)
    return value.strip()


def navigation_titles(locate: dict) -> list[str]:
    navigation = locate.get("navigation")
    if navigation is None:
        titles = [locate.get(key) for key in ("part", "chapter", "section")]
        titles = [title.strip() for title in titles if isinstance(title, str) and title.strip()]
    else:
        if not isinstance(navigation, list) or not navigation:
            raise CutError("locate.navigation 须为非空标题数组")
        titles = []
        for title in navigation:
            if not isinstance(title, str) or not title.strip():
                raise CutError("locate.navigation 的标题须为非空字符串")
            titles.append(title.strip())
    if not titles:
        raise CutError("缺少 locate.navigation 或部章节标题")
    return titles


def chapter_label(locate: dict, titles: list[str]) -> str:
    parts = []
    for key in ("chapter", "section", "part"):
        value = locate.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in parts:
            parts.append(value.strip())
        if key == "section" and parts:
            break
    if not parts:
        parts.append(titles[-1])
    return " · ".join(parts[:2])


def format_minutes(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CutError("locate.estimated_minutes 须为正数")
    if isinstance(value, float) and not value.is_integer():
        rendered = str(value)
    else:
        rendered = str(int(value))
    if float(value) <= 0:
        raise CutError("locate.estimated_minutes 须为正数")
    return rendered


def questions_of(unit: dict) -> list[str]:
    questions = unit.get("pre_questions")
    if not isinstance(questions, list) or len(questions) != 3:
        raise CutError(f"单元 {unit.get('id')} 缺少三个问题，无法生成带着读")
    rendered = []
    for question in questions:
        if not isinstance(question, dict):
            raise CutError(f"单元 {unit.get('id')} 的问题须为对象")
        rendered.append(require_text(question.get("question"), f"单元 {unit.get('id')} 的问题为空"))
    return rendered


def concept_of(unit: dict) -> tuple[str, str]:
    watch = unit.get("watch")
    if not isinstance(watch, dict):
        raise CutError(f"单元 {unit.get('id')} 缺少留意概念")
    concept = require_text(watch.get("concept"), f"单元 {unit.get('id')} 缺少留意概念")
    why = watch.get("why")
    if why is None:
        why = ""
    elif not isinstance(why, str):
        raise CutError(f"单元 {unit.get('id')} 的 watch.why 须为字符串")
    return concept, why.strip()


def expected_word_count(unit: dict) -> int:
    locate = unit["locate"]
    value = locate.get("word_count", unit.get("word_count"))
    if type(value) is not int or value < 1:
        raise CutError(f"单元 {unit.get('id')} 的 word_count 须为正整数")
    return value


def load_course(path: Path) -> tuple[dict, str, str, set[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CutError(f"无法读取课程 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise CutError("课程须为对象")
    source = data.get("source")
    if not isinstance(source, dict):
        raise CutError("课程缺少 source 对象")
    expected = source.get("sha256")
    if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected.strip().lower()):
        raise CutError("source.sha256 须为 64 位 SHA-256")
    notes = data.get("reading_notes")
    method_text = None
    if notes is not None:
        if not isinstance(notes, dict):
            raise CutError("reading_notes 须为对象")
        method_text = notes.get("counting_method")
        if method_text is not None and not isinstance(method_text, str):
            raise CutError("reading_notes.counting_method 须为字符串")
    resolve_counting_method(method_text)
    scope = data.get("scope")
    excluded = []
    if scope is not None:
        if not isinstance(scope, dict):
            raise CutError("scope 须为对象")
        excluded = scope.get("excluded") or []
        if not isinstance(excluded, list):
            raise CutError("scope.excluded 须为数组")
    recorded = method_text.strip() if isinstance(method_text, str) and method_text.strip() else CANONICAL_COUNTING_METHOD
    return data, expected.strip().lower(), recorded, exclusion_labels(excluded)


def decode_xml(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CutError("EPUB 文本不是有效的 UTF-8 或 GB18030")


class ChapterParser(HTMLParser):
    def __init__(self, member: str):
        super().__init__(convert_charrefs=True)
        self.member = member
        self.blocks = []
        self.ignore = 0
        self.stack = []
        self.buffer = []
        self.loose = []

    def _flush_loose(self):
        text = "".join(self.loose)
        self.loose = []
        if normalize(text):
            self.blocks.append(Block("text", 0, text, member=self.member, tag="p"))

    def _emit_open_text(self):
        if not self.stack:
            return
        text = "".join(self.buffer)
        self.buffer = []
        if not normalize(text):
            return
        tag = self.stack[-1]
        if tag.startswith("h") and tag[1:].isdigit():
            kind, level = "heading", int(tag[1:])
        elif tag == "figcaption":
            kind, level = "caption", 0
        else:
            kind, level = "text", 0
        self.blocks.append(Block(kind, level, text, member=self.member, tag=tag))

    def handle_starttag(self, tag, attrs):
        if self.ignore:
            if tag in IGNORE_TAGS:
                self.ignore += 1
            return
        if tag in IGNORE_TAGS:
            self.ignore += 1
            return
        if tag == "br":
            if self.stack:
                self.buffer.append("\n")
            else:
                self.loose.append("\n")
            return
        if tag == "img":
            self._flush_loose()
            self._emit_open_text()
            attr = {key.lower(): value or "" for key, value in attrs}
            self.blocks.append(Block(
                "image", 0, "", alt=attr.get("alt", ""), src=attr.get("src", ""), member=self.member, tag="img",
            ))
            return
        if tag in BLOCK_TAGS:
            self._flush_loose()
            self._emit_open_text()
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in IGNORE_TAGS and self.ignore:
            self.ignore -= 1
            return
        if self.ignore:
            return
        if self.stack and self.stack[-1] == tag:
            self._emit_open_text()
            self.stack.pop()

    def handle_data(self, data):
        if self.ignore:
            return
        if self.stack:
            self.buffer.append(data)
        else:
            self.loose.append(data)

    def close(self):
        super().close()
        self._emit_open_text()
        self.stack.clear()
        self._flush_loose()


def read_spine(archive: zipfile.ZipFile) -> tuple[list[Block], dict[str, str]]:
    try:
        container = parse_xml(archive.read("META-INF/container.xml"))
    except KeyError as exc:
        raise CutError("EPUB 缺少 META-INF/container.xml") from exc
    rootfile = next((node for node in container.iter() if local_name(node.tag) == "rootfile"), None)
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise CutError("EPUB 缺少 OPF 路径")
    opf_path = unquote(rootfile.attrib["full-path"])
    try:
        opf = parse_xml(archive.read(opf_path))
    except KeyError as exc:
        raise CutError(f"EPUB 缺少 OPF：{opf_path}") from exc
    manifest_el = next((node for node in opf if local_name(node.tag) == "manifest"), None)
    spine_el = next((node for node in opf if local_name(node.tag) == "spine"), None)
    if manifest_el is None or spine_el is None:
        raise CutError("EPUB 的 OPF 缺少 manifest 或 spine")
    manifest = {}
    media_types = {}
    for item in manifest_el:
        if local_name(item.tag) != "item":
            continue
        href = item.attrib.get("href")
        item_id = item.attrib.get("id")
        if not href or not item_id:
            continue
        full_path = zip_join(opf_path, href)
        media = item.attrib.get("media-type", "").split(";", 1)[0].strip().lower()
        properties = item.attrib.get("properties", "").split()
        manifest[item_id] = (full_path, media, "nav" in properties)
        media_types[full_path] = media
    blocks = []
    for itemref in spine_el:
        if local_name(itemref.tag) != "itemref":
            continue
        if itemref.attrib.get("linear", "yes") == "no":
            continue
        item = manifest.get(itemref.attrib.get("idref", ""))
        if item is None:
            raise CutError(f"spine 引用了不存在的 manifest 项：{itemref.attrib.get('idref')}")
        full_path, media, is_nav = item
        if is_nav:
            continue
        suffix = PurePosixPath(full_path).suffix.lower()
        if media not in {"application/xhtml+xml", "text/html", "application/html+xml"} and suffix not in {".xhtml", ".html", ".htm"}:
            continue
        try:
            raw = archive.read(full_path)
        except KeyError as exc:
            raise CutError(f"EPUB 缺少 spine 文件：{full_path}") from exc
        parser = ChapterParser(full_path)
        parser.feed(decode_xml(raw))
        parser.close()
        blocks.extend(parser.blocks)
    if not blocks:
        raise CutError("EPUB spine 中没有可切分的正文")
    return blocks, media_types


def heading_run_before(indexed: list[Block], start_at: tuple[int, int]) -> int:
    """Include headings that touch the start block, stopping at the anchor."""
    position, start_index = start_at
    block = indexed[position]
    if block.kind != "heading" and visible_count(block.text[:start_index]) > 0:
        return position
    while position > 0 and indexed[position - 1].kind == "heading":
        position -= 1
    return position


def navigation_order(headings: list[str], titles: list[str]) -> None:
    """Headings from the chapter anchor through end_hint must follow navigation."""
    seen = [normalize(heading) for heading in headings]
    position = 0
    for title in titles:
        wanted = normalize(title)
        while position < len(seen) and seen[position] != wanted:
            position += 1
        if position >= len(seen):
            raise CutError(f"范围内标题与导航顺序不一致：{title}", rank=4)
        position += 1


def locate_unit(blocks: list[Block], titles: list[str], start_hint: str, end_hint: str, labels: set[str]):
    first = normalize(titles[0])
    candidates = [index for index, block in enumerate(blocks) if block.kind == "heading" and normalize(block.text) == first]
    if not candidates:
        raise CutError(f"找不到导航标题：{titles[0]}", rank=1)
    best = None
    for anchor in candidates:
        try:
            return cut_after_anchor(blocks, anchor, titles, start_hint, end_hint, labels)
        except CutError as exc:
            if best is None or exc.rank >= best.rank:
                best = exc
    raise best


def cut_after_anchor(blocks, anchor, titles, start_hint, end_hint, labels):
    indexed = []
    window_headings = []
    start_at = None
    end_at = None
    skipping = None
    for offset, block in enumerate(blocks[anchor:]):
        if skipping is not None:
            if block.kind == "heading" and block.level <= skipping:
                skipping = None
            else:
                continue
        if offset != 0 and block.kind == "heading" and normalize(block.text) in labels:
            skipping = block.level
            continue
        position = len(indexed)
        indexed.append(block)
        if block.kind == "heading":
            window_headings.append(block.text)
        if block.kind == "image":
            continue
        if start_at is None:
            span = hint_span(block.text, start_hint)
            if span:
                start_at = (position, span[0])
        if start_at is not None:
            espan = hint_span(block.text, end_hint)
            if espan and not (start_at[0] == position and espan[0] < start_at[1]):
                end_at = (position, espan[1])
                break
    if start_at is None:
        raise CutError(f"找不到起始提示：{start_hint}", rank=2)
    if end_at is None:
        raise CutError(f"找不到结束提示：{end_hint}", rank=3)
    navigation_order(window_headings, titles)
    lead = heading_run_before(indexed, start_at)
    segments = []
    output_headings = []
    for position in range(lead, end_at[0] + 1):
        block = indexed[position]
        if position == start_at[0] and position == end_at[0]:
            text = block.text[start_at[1]:end_at[1]]
        elif position == start_at[0]:
            text = block.text[start_at[1]:]
        elif position == end_at[0]:
            text = block.text[:end_at[1]]
        else:
            text = block.text
        if block.kind != "image" and visible_count(text) == 0:
            continue
        segments.append((block, text))
        if block.kind == "heading":
            output_headings.append(text)
    if not segments:
        raise CutError(f"找不到起始提示：{start_hint}", rank=2)
    return segments, output_headings


def count_segments(segments) -> int:
    return visible_count("".join(text for block, text in segments if block.kind != "image"))


def embed_image(block: Block, archive: zipfile.ZipFile, media_types: dict[str, str]) -> str:
    if block.src.startswith("data:"):
        return block.src
    if not block.src:
        raise CutError("图片缺少 src")
    path = zip_join(block.member, block.src)
    try:
        payload = archive.read(path)
    except KeyError as exc:
        raise CutError(f"EPUB 缺少图片：{path}") from exc
    media = media_types.get(path) or MIME_BY_SUFFIX.get(PurePosixPath(path).suffix.lower())
    if not media:
        raise CutError(f"无法判断图片类型：{path}")
    encoded = base64.standard_b64encode(payload).decode("ascii")
    return f"data:{media};base64,{encoded}"


def render_article(segments, archive, media_types) -> str:
    parts = []
    index = 0
    while index < len(segments):
        block, text = segments[index]
        if block.kind == "image":
            caption = ""
            if index + 1 < len(segments) and segments[index + 1][0].kind == "caption":
                caption = f"<figcaption>{html.escape(segments[index + 1][1])}</figcaption>"
                index += 1
            src = html.escape(embed_image(block, archive, media_types), quote=True)
            alt = html.escape(block.alt, quote=True)
            parts.append(f'<figure><img src="{src}" alt="{alt}">{caption}</figure>')
        elif block.kind == "heading":
            level = min(6, max(1, block.level or 2))
            parts.append(f"<h{level}>{html.escape(text)}</h{level}>")
        elif block.kind == "caption":
            parts.append(f"<figcaption>{html.escape(text)}</figcaption>")
        elif block.tag == "blockquote":
            parts.append(f"<blockquote>{html.escape(text)}</blockquote>")
        else:
            parts.append(f"<p>{html.escape(text)}</p>")
        index += 1
    return "\n".join(parts)


def render_page(book_title, order, total, chapter, minutes, questions, concept, why, article) -> str:
    question_items = "\n".join(f"      <li>{html.escape(question)}</li>" for question in questions)
    why_html = f'\n    <p class="why">{html.escape(why)}</p>' if why else ""
    header = f"{book_title} · 第 {order}/{total} 单元 · {chapter} · 约 {minutes} 分钟"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(header)}</title>
  <style>
{PAGE_STYLE}
  </style>
</head>
<body>
  <main>
    <p class="meta">{html.escape(header)}</p>
    <hr>
    <section class="prep">
      <h2>带着读</h2>
      <ol>
{question_items}
      </ol>
      <p class="watch">留意概念：<span class="concept">{html.escape(concept)}</span></p>{why_html}
    </section>
    <hr>
    <article>
{article}
    </article>
    <hr>
    <footer>
      <p>读完回学伴：三句复述＋三个问题的回答＋一个质疑</p>
      <p>仅供 Sanze 个人阅读，请勿转发</p>
    </footer>
  </main>
</body>
</html>
"""


def title_diff_line(draft: UnitDraft) -> str:
    found_norm = {normalize(title) for title in draft.found_titles}
    expected_norm = {normalize(title) for title in draft.expected_titles}
    missing = [title for title in draft.expected_titles if normalize(title) not in found_norm]
    extra = [title for title in draft.found_titles if normalize(title) not in expected_norm]
    missing_text = "、".join(missing) if missing else "无"
    extra_text = "、".join(extra) if extra else "无"
    found_text = "、".join(draft.found_titles) if draft.found_titles else "无"
    return f"单元 {draft.unit_id}：标题差异：缺失 {missing_text}；多出 {extra_text}；范围内标题 {found_text}"


def word_line(draft: UnitDraft) -> str:
    actual = "未定位" if draft.actual_count is None else str(draft.actual_count)
    return f"单元 {draft.unit_id}：字数 actual={actual} expected={draft.expected_count}"


def draft_unit(unit, blocks, labels, book_title, total, archive, media_types) -> UnitDraft:
    unit_id = require_text(unit.get("id"), "单元缺少 id")
    locate = unit.get("locate")
    if not isinstance(locate, dict):
        raise CutError(f"单元 {unit_id} 缺少 locate")
    titles = navigation_titles(locate)
    draft = UnitDraft(unit_id, expected_word_count(unit), titles)
    start_hint = require_text(locate.get("start_hint"), f"单元 {unit_id} 缺少 start_hint")
    end_hint = require_text(locate.get("end_hint"), f"单元 {unit_id} 缺少 end_hint")
    if not normalize(start_hint) or not normalize(end_hint):
        raise CutError(f"单元 {unit_id} 的起止提示为空")
    try:
        segments, headings = locate_unit(blocks, titles, start_hint, end_hint, labels)
    except CutError as exc:
        draft.error = f"{unit_id}：{exc}"
        return draft
    draft.found_titles = headings
    draft.actual_count = count_segments(segments)
    if type(unit.get("order")) is not int or unit["order"] < 1:
        raise CutError(f"单元 {unit_id} 的 order 须为从 1 开始的整数")
    book = data_book_title(book_title)
    article = render_article(segments, archive, media_types)
    draft.html = render_page(
        book,
        unit["order"],
        total,
        chapter_label(locate, titles),
        format_minutes(locate.get("estimated_minutes")),
        questions_of(unit),
        *concept_of(unit),
        article,
    )
    return draft


def data_book_title(book) -> str:
    if not isinstance(book, dict):
        raise CutError("课程缺少 book 对象")
    return require_text(book.get("title_zh") or book.get("title"), "课程缺少 book.title_zh")


def safe_unit_id(unit_id: str) -> str:
    if unit_id in {".", ".."} or any(char in unit_id for char in "/\\\x00"):
        raise CutError(f"单元 id 不能作为文件名：{unit_id}")
    return unit_id


def build_report(drafts, expected_sha, actual_sha, sha_matches, accept_edition) -> tuple[str, bool]:
    lines = []
    if not sha_matches:
        lines.extend([
            "异版：原书 SHA-256 与 course.json 的 source.sha256 不一致",
            f"expected={expected_sha}",
            f"actual={actual_sha}",
        ])
        for draft in drafts:
            lines.append(word_line(draft))
            lines.append(title_diff_line(draft))
            if draft.error:
                lines.append(f"单元 {draft.error}")
    failures = []
    for draft in drafts:
        if draft.error:
            failures.append(draft.error if draft.error.startswith(draft.unit_id) else f"{draft.unit_id}：{draft.error}")
        elif draft.actual_count != draft.expected_count:
            failures.append(
                f"字数不符：{draft.unit_id}：actual={draft.actual_count} expected={draft.expected_count} "
                f"counting_method={CANONICAL_COUNTING_METHOD}"
            )
    if failures:
        lines.extend(failures)
        lines.append("未写入输出。")
        return "\n".join(lines), False
    if not sha_matches and not accept_edition:
        lines.append("未写入输出。确认后可加 --accept-edition 重跑。")
        return "\n".join(lines), False
    return "\n".join(lines), True


def write_output(out: Path, drafts, actual_sha, course_sha, counting_method) -> None:
    out.mkdir(parents=True, exist_ok=True)
    units = []
    for draft in drafts:
        filename = safe_unit_id(draft.unit_id) + ".html"
        payload = draft.html.encode("utf-8")
        (out / filename).write_bytes(payload)
        units.append({
            "id": draft.unit_id,
            "word_count": draft.actual_count,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source_sha256": actual_sha,
        })
    manifest = {
        "source_sha256": actual_sha,
        "course_sha256": course_sha,
        "counting_method": counting_method,
        "units": units,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def requested_units(course: dict, raw_units: str) -> list[dict]:
    units = course.get("units")
    if not isinstance(units, list) or not units:
        raise CutError("课程缺少 units")
    by_id = {}
    for unit in units:
        if not isinstance(unit, dict):
            raise CutError("单元须为对象")
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise CutError("单元缺少 id")
        if unit_id in by_id:
            raise CutError(f"单元 id 重复：{unit_id}")
        by_id[unit_id] = unit
    selected = [part.strip() for part in raw_units.split(",") if part.strip()]
    if not selected:
        raise CutError("必须用 --units 指定至少一个单元 id")
    if len(selected) != len(set(selected)):
        raise CutError("命令行中的单元 id 重复")
    missing = [unit_id for unit_id in selected if unit_id not in by_id]
    if missing:
        raise CutError("未知单元：" + "、".join(missing))
    for unit_id in selected:
        safe_unit_id(unit_id)
    return [by_id[unit_id] for unit_id in selected]


def run(source: Path, course_path: Path, out: Path, units: str, accept_edition: bool) -> int:
    if inside_git_worktree(out):
        print(f"拒绝：输出目录位于 git 工作树内：{out.expanduser().resolve(strict=False)}")
        return 1
    if out.exists() and not out.is_dir():
        print(f"拒绝：输出路径不是目录：{out}")
        return 1
    course, expected_sha, counting_method, labels = load_course(course_path)
    if source.suffix.lower() != ".epub":
        raise CutError("仅支持 EPUB 原书")
    if not source.is_file():
        raise CutError(f"找不到原书：{source}")
    actual_sha = file_sha256(source)
    selected = requested_units(course, units)
    book_title = course.get("book")
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CutError(f"无法读取 EPUB：{exc}") from exc
    try:
        blocks, media_types = read_spine(archive)
        drafts = [
            draft_unit(unit, blocks, labels, book_title, len(course["units"]), archive, media_types)
            for unit in selected
        ]
        report, ok = build_report(drafts, expected_sha, actual_sha, actual_sha == expected_sha, accept_edition)
        if report:
            print(report)
        if not ok:
            return 1
        write_output(out, drafts, actual_sha, expected_sha, counting_method)
    finally:
        archive.close()
    if actual_sha != expected_sha:
        print(f"已接受异版并写入：{out}")
    else:
        print(f"已写入：{out}")
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description="按课程定位把 EPUB 单元切成仓库外的自包含 HTML")
    parser.add_argument("--source", required=True, type=Path, help="仓库外的 EPUB 原书")
    parser.add_argument("--course", required=True, type=Path, help="course.json")
    parser.add_argument("--out", required=True, type=Path, help="仓库外的输出目录")
    parser.add_argument("--units", required=True, help="单元 id，逗号分隔，例如 zs-u02,zs-u03")
    parser.add_argument("--accept-edition", action="store_true", help="原书 SHA-256 与课程不一致但字数和定位已确认时写入")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run(args.source.expanduser(), args.course.expanduser(), args.out.expanduser(), args.units, args.accept_edition)
    except CutError as exc:
        print(str(exc))
        print("未写入输出。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
