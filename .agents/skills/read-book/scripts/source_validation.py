"""Shared, stdlib-only source checks. Never extract or copy private sources."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote
import zipfile


@dataclass(frozen=True)
class Issue:
    level: str
    location: str
    message: str


class SourceError(ValueError):
    pass


PRIVATE_PATH = re.compile(
    r"file://|^[\\/](?!/)|(?<![A-Za-z0-9_/])/(?:Users|home|private|Volumes|tmp|var|mnt)/|(?<![A-Za-z0-9_])[A-Za-z]:[\\/]",
    re.I,
)


def inspect_private_paths(value, pointer, issues):
    """Shared by map and course checks, including paths embedded in Chinese prose."""
    if isinstance(value, dict):
        for key, child in value.items():
            if PRIVATE_PATH.search(key):
                issues.append(Issue("ERROR", pointer, "字段名含私有绝对路径"))
            inspect_private_paths(child, f"{pointer}.{key}", issues)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            inspect_private_paths(child, f"{pointer}[{index}]", issues)
    elif isinstance(value, str) and PRIVATE_PATH.search(value):
        issues.append(Issue("ERROR", pointer, "含私有绝对路径或 file:// 链接"))


def normalize(text: str) -> str:
    """Only HTML entities and Unicode whitespace; punctuation stays significant."""
    return re.sub(r"\s+", "", html.unescape(text))


def walk_objects(value: object, location: str = "$"):
    if isinstance(value, dict):
        yield location, value
        for key, child in value.items():
            yield from walk_objects(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_objects(child, f"{location}[{index}]")


def nonempty(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(nonempty(child) for child in value.values())
    if isinstance(value, list):
        return any(nonempty(child) for child in value)
    return value is not None and value is not False


class SourceHTMLParser(HTMLParser):
    """Text, nonempty p paragraphs, and nonempty h1-h6/p blocks, in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocks = []
        self.paragraphs = []
        self.active = []
        self.skipped = 0
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in {"head", "script", "style"}:
            self.skipped += 1
        if self.skipped:
            return
        if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.active.append((tag, []))
        if tag == "br":
            self.handle_data("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in {"head", "script", "style"} and self.skipped:
            self.skipped -= 1
            return
        if self.skipped:
            return
        if self.active and self.active[-1][0] == tag:
            _, parts = self.active.pop()
            text = "".join(parts)
            if normalize(text):
                self.blocks.append(text)
                if tag == "p":
                    self.paragraphs.append(text)
        self.parts.append("\n" if tag in {"p", "div", "li"} else "")

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if not self.skipped:
            self.parts.append(data)
            for _, parts in self.active:
                parts.append(data)


def decode_text(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise SourceError("原书不是有效的 UTF-8 或 GB18030 文本")


class SourceDocument:
    def __init__(self, path: Path):
        self.archive = None
        self.cache = {}
        self.lines = []
        self.encoding = None
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            self.sha256 = digest.hexdigest()
            self.format = "epub" if path.suffix.lower() == ".epub" else "text"
            if self.format == "epub":
                self.archive = zipfile.ZipFile(path)
                self.members = set(self.archive.namelist())
            elif path.suffix.lower() in {".txt", ".md", ".markdown"}:
                text, self.encoding = decode_text(path.read_bytes())
                self.lines = text.splitlines()
                self.members = set()
            else:
                raise SourceError("仅支持 TXT、Markdown 和 EPUB 原书")
        except (OSError, zipfile.BadZipFile) as exc:
            self.close()
            raise SourceError(f"无法读取原书：{type(exc).__name__}") from exc

    def close(self):
        if self.archive is not None:
            self.archive.close()

    def document(self, member: str) -> SourceHTMLParser:
        member = unquote(member.split("#", 1)[0])
        if member not in self.members:
            raise SourceError(f"EPUB 内部路径不存在：{member}")
        if member not in self.cache:
            try:
                raw = self.archive.read(member)
                text, _ = decode_text(raw)
                parser = SourceHTMLParser()
                parser.feed(text)
                parser.close()
                self.cache[member] = parser
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise SourceError(f"无法读取 EPUB 成员 {member}：{type(exc).__name__}") from exc
        return self.cache[member]

    def credible_bounds(self, metadata: dict) -> tuple[int, int]:
        limits = metadata.get("credible_range", {})
        if not isinstance(limits, dict):
            raise SourceError("source.credible_range 必须是对象")
        start, end = limits.get("start_line", 1), limits.get("end_line", len(self.lines))
        if (type(start) is not int or type(end) is not int
                or not 1 <= start <= end <= len(self.lines)):
            raise SourceError("source.credible_range 超出原书行数或起止顺序无效")
        return start, end

    def text_at(self, locator: dict, metadata: dict) -> str:
        if self.format == "text":
            lower, upper = self.credible_bounds(metadata)
            start, end = locator.get("start_line", lower), locator.get("end_line", upper)
            if (type(start) is not int or type(end) is not int
                    or not lower <= start <= end <= upper):
                raise SourceError(f"行号必须落在 credible_range {lower}–{upper} 内且起止有序")
            return "\n".join(self.lines[start - 1:end])
        member = locator.get("epub_path")
        if not isinstance(member, str) or not member:
            raise SourceError("缺少可解析的 EPUB 内部路径")
        document = self.document(member)
        if "paragraph" in locator:
            indexes = parse_indexes(locator["paragraph"])
            texts = document.paragraphs
        elif "blocks" in locator:
            indexes = parse_indexes(locator["blocks"])
            texts = document.blocks
            # Some existing modules explicitly count the XHTML <title> as block 1.
            if re.search(r"块\s*1\s*为.*书名", str(metadata.get("locator_method", ""))):
                title = "".join(document.title_parts)
                if normalize(title):
                    texts = [title] + texts
        else:
            return "".join(document.parts)
        if not indexes or max(indexes) > len(texts):
            raise SourceError(f"EPUB 段落或文本块序号越界：{member}")
        # Keep nonadjacent selections separate so a quote cannot bridge skipped text.
        parts = []
        for previous, index in zip([0] + indexes, indexes):
            parts.append(("\n" if index == previous + 1 else "\n\x00\n") + texts[index - 1])
        return "".join(parts)

    def contains_anywhere(self, needle: str, metadata: dict) -> bool:
        if self.format == "text":
            lower, upper = self.credible_bounds(metadata)
            excluded = metadata.get("excluded_ranges", [])
            if not isinstance(excluded, list):
                raise SourceError("source.excluded_ranges 必须是数组")
            ranges = []
            for item in excluded:
                if not isinstance(item, dict):
                    raise SourceError("source.excluded_ranges 每项必须含有效起止行号")
                start, end = item.get("start_line"), item.get("end_line")
                if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(self.lines):
                    raise SourceError("source.excluded_ranges 行号越界或起止顺序无效")
                if start <= upper and end >= lower:
                    ranges.append((max(lower, start), min(upper, end)))
            cursor = lower
            # Search contiguous allowed spans separately; never bridge an excluded gap.
            for start, end in sorted(ranges):
                if cursor < start and needle in normalize("\n".join(self.lines[cursor - 1:start - 1])):
                    return True
                cursor = max(cursor, end + 1)
            return cursor <= upper and needle in normalize("\n".join(self.lines[cursor - 1:upper]))
        return any(
            needle in normalize("".join(self.document(member).parts))
            for member in sorted(self.members)
            if PurePosixPath(member).suffix.lower() in {".xhtml", ".html", ".htm"}
        )


def parse_indexes(value: object) -> list[int]:
    if type(value) is int:
        if value < 1:
            raise SourceError("段落或文本块序号须从 1 开始")
        return [value]
    if not isinstance(value, str):
        raise SourceError("段落或文本块序号格式无效")
    indexes = []
    for part in re.split(r"[,，、]", value):
        match = re.fullmatch(r"\s*(\d+)(?:\s*[-–—至]\s*(\d+))?\s*", part)
        if not match:
            raise SourceError(f"段落或文本块序号格式无效：{value}")
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end or end - start > 100000:
            raise SourceError(f"段落或文本块序号范围无效：{value}")
        indexes.extend(range(start, end + 1))
    return indexes


def source_metadata(data: dict, inherited: dict) -> dict:
    result = dict(inherited)
    for key in ("source_book", "source"):
        if isinstance(data.get(key), dict):
            result.update(data[key])
    return result


EPUB_REFERENCE = re.compile(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:xhtml|html|htm|ncx)", re.I)
EPUB_RANGE = re.compile(r"((?:[\w.-]+/)*)([A-Za-z_-]+)(\d+)(\.(?:xhtml|html|htm))?\s*[–—]\s*([A-Za-z_-]+)(\d+)(\.(?:xhtml|html|htm))", re.I)


def expand_member_range(value: str) -> list[str]:
    match = EPUB_RANGE.fullmatch(value)
    if not match:
        return [value]
    directory, stem, start, extension, end_stem, end, end_extension = match.groups()
    if stem != end_stem or (extension and extension != end_extension) or not 0 <= int(end) - int(start) <= 10000:
        raise SourceError(f"EPUB 路径范围无效：{value}")
    return [f"{directory}{stem}{index:0{len(start)}d}{end_extension}" for index in range(int(start), int(end) + 1)]


def string_locators(value: str, source: SourceDocument) -> list[dict]:
    if source.format == "text":
        match = re.fullmatch(r"\s*(\d+)\s*[-–—至]\s*(\d+)\s*", value)
        return [{"start_line": int(match[1]), "end_line": int(match[2])}] if match else []
    results = []
    members = [member for match in EPUB_RANGE.finditer(value) for member in expand_member_range(match[0])]
    members.extend(EPUB_REFERENCE.findall(EPUB_RANGE.sub("", value)))
    for member in members:
        if "/" not in member and member not in source.members:
            matches = [name for name in source.members if PurePosixPath(name).name == member]
            if len(matches) == 1:
                member = matches[0]
        results.append({"epub_path": member})
    return results


def resolve_locators(record: dict, data: dict, source: SourceDocument) -> list[dict]:
    metadata = source_metadata(data, {})
    raw = record.get("locators", record.get("source_refs", record.get("locator")))
    if raw is None:
        raw = [record]
    if not isinstance(raw, list):
        raw = [raw]
    results = []
    for item in raw:
        if isinstance(item, str):
            results.extend(string_locators(item, source))
            continue
        if not isinstance(item, dict):
            continue
        locator = {key: item[key] for key in ("epub_path", "start_line", "end_line", "blocks", "paragraph") if key in item}
        if source.format == "text":
            if "start_line" in locator or "end_line" in locator:
                results.append(locator)
            continue
        paths = item.get("epub_paths")
        if not paths:
            paths = [locator["epub_path"]] if locator.get("epub_path") else []
        article = item.get("article", record.get("article"))
        if not paths and article:
            articles = metadata.get("articles", [])
            if isinstance(articles, list):
                paths = [entry["epub_path"] for entry in articles
                         if isinstance(entry, dict) and entry.get("title") == article and entry.get("epub_path")]
        if not paths:
            default = metadata.get("epub_path")
            if not default and isinstance(metadata.get("article"), dict):
                default = metadata["article"].get("epub_path")
            paths = [default] if default else metadata.get("epub_paths", [])
        if isinstance(paths, list):
            results.extend(dict(locator, epub_path=member) for path in paths if isinstance(path, str)
                           for member in expand_member_range(path))
    return results


def inspect_locators(data: dict, source: SourceDocument, metadata: dict, file: Path, issues: list[Issue]):
    """Check structured source references, excluding explicitly excluded TXT ranges."""
    for pointer, record in walk_objects(data):
        if pointer.startswith(("$.source.excluded_ranges", "$.source.archive_validation")) or pointer == "$.source.credible_range":
            continue
        if source.format == "text" and ("start_line" in record or "end_line" in record):
            try:
                source.text_at(record, metadata)
            except SourceError as exc:
                issues.append(Issue("ERROR", f"{file}:{pointer}", str(exc)))
        for key, value in record.items():
            if key in {"locator", "source_locators"}:
                values = value if isinstance(value, list) else [value]
                for text in values:
                    if not isinstance(text, str):
                        continue
                    try:
                        locators = string_locators(text, source)
                    except SourceError as exc:
                        issues.append(Issue("ERROR", f"{file}:{pointer}.{key}", str(exc)))
                        continue
                    if not locators:
                        issues.append(Issue("WARNING", f"{file}:{pointer}.{key}", "定位仅含描述，未做机械定位核对"))
                    for locator in locators:
                        try:
                            source.text_at(locator, metadata)
                        except SourceError as exc:
                            issues.append(Issue("ERROR", f"{file}:{pointer}.{key}", str(exc)))
            if source.format != "epub":
                continue
            if key in {"epub_path", "epub_paths", "next_work_start"} or key.endswith(("_xhtml", "_xhtml_inclusive")):
                values = value if isinstance(value, list) else [value]
                for member in values:
                    if member is None:
                        continue
                    try:
                        members = expand_member_range(member) if isinstance(member, str) else [member]
                        for expanded in members:
                            if not isinstance(expanded, str) or unquote(expanded.split("#", 1)[0]) not in source.members:
                                issues.append(Issue("ERROR", f"{file}:{pointer}.{key}", f"EPUB 内部路径不存在：{expanded}"))
                    except SourceError as exc:
                        issues.append(Issue("ERROR", f"{file}:{pointer}.{key}", str(exc)))


QUOTE_FIELDS = {"quote", "short_quote", "excerpt"}
QUOTE_LABELS = {"作者原话", "author_quote", "direct_quote", "original_quote"}


def quote_records(data: dict):
    for pointer, record in walk_objects(data):
        fields = QUOTE_FIELDS & record.keys()
        if any(record.get(key) in QUOTE_LABELS for key in ("type", "kind", "label") if isinstance(record.get(key), str)):
            fields |= {"text", "statement", "content"} & record.keys()
        for field in sorted(fields):
            yield f"{pointer}.{field}", record[field], record


def check_text(text: str, record: dict, data: dict, source: SourceDocument, metadata: dict) -> tuple[bool, bool]:
    """Return (matched, had locator). Explicit locators never silently fall back."""
    needle = normalize(text)
    locators = resolve_locators(record, data, source)
    if not locators:
        return source.contains_anywhere(needle, metadata), False
    texts = [source.text_at(locator, metadata) for locator in locators]
    return any(needle in normalize(part) for part in texts), True


def inspect_source(data: dict, file: Path, source: SourceDocument, inherited: dict, issues: list[Issue], audit: dict):
    metadata = source_metadata(data, inherited)
    expected = metadata.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        issues.append(Issue("ERROR", f"{file}:$.source.sha256", "缺少有效 SHA-256；停止来源核对"))
        return
    if expected.lower() != source.sha256:
        issues.append(Issue("ERROR", f"{file}:$.source.sha256", f"SHA-256 不符：expected={expected}, actual={source.sha256}；停止来源核对"))
        return
    if source.format == "text":
        try:
            source.credible_bounds(metadata)
        except SourceError as exc:
            issues.append(Issue("ERROR", f"{file}:$.source.credible_range", str(exc)))
            return
    inspect_locators(data, source, metadata, file, issues)
    doc_audit = {"file": str(file), "quotes_checked": 0, "quotes_matched": 0, "hints_checked": 0}
    audit.setdefault("documents", []).append(doc_audit)
    for pointer, text, record in quote_records(data):
        doc_audit["quotes_checked"] += 1
        if not isinstance(text, str) or not normalize(text):
            issues.append(Issue("ERROR", f"{file}:{pointer}", "引文须为非空字符串"))
            continue
        try:
            matched, located = check_text(text, record, data, source, metadata)
            if not located:
                issues.append(Issue("WARNING", f"{file}:{pointer}", "引文无可解析定位，仅在可信原书范围中检索"))
            if not matched:
                issues.append(Issue("ERROR", f"{file}:{pointer}", "引文在所标定位处未逐字找到" if located else "引文在原书中未逐字找到"))
            else:
                doc_audit["quotes_matched"] += 1
        except SourceError as exc:
            issues.append(Issue("ERROR", f"{file}:{pointer}", str(exc)))
    for pointer, record in walk_objects(data):
        if "search_text" not in record:
            continue
        doc_audit["hints_checked"] += 1
        hint = record["search_text"]
        try:
            if not isinstance(hint, str) or not normalize(hint) or not check_text(hint, record, data, source, metadata)[0]:
                issues.append(Issue("ERROR", f"{file}:{pointer}.search_text", "搜索提示在所标定位或原书中未逐字找到"))
        except SourceError as exc:
            issues.append(Issue("ERROR", f"{file}:{pointer}.search_text", str(exc)))
