#!/usr/bin/env python3
"""Validate a read-book V1 book artifact directory using only stdlib."""

from __future__ import annotations

import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

from source_validation import Issue, SourceDocument, SourceError, inspect_source, nonempty
from source_validation import inspect_private_paths as inspect_shared_private_paths


PRIVATE_SOURCE_SUFFIXES = {
    ".epub",
    ".pdf",
    ".mobi",
    ".azw",
    ".azw3",
    ".txt",
    ".md",
    ".markdown",
    ".docx",
}
ACCEPTED_SCHEMA_VERSIONS = {"read-book.v1", "read-book.dogfood.v1"}
V1_REQUIRED_FIELDS = {
    "schema_version",
    "artifact_kind",
    "book",
    "source",
    "scope",
    "reading_contract",
    "claims",
    "critical_audit",
    "module_policy",
    "modules",
    "generation_audit",
}
REMOTE_SCHEMES = {"http", "https"}
SAFE_LINK_SCHEMES = REMOTE_SCHEMES | {"mailto", "tel", "data"}


class ArtifactHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.external_resources: list[tuple[str, str]] = []
        self.svg_count = 0
        self.svg_without_viewbox = 0
        self.lang: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "html":
            self.lang = values.get("lang")
        if tag == "a" and values.get("href"):
            self.links.append((tag, values["href"]))
        if tag in {"script", "img", "source", "audio", "video", "iframe"} and values.get("src"):
            self.external_resources.append((tag, values["src"]))
        if tag == "video" and values.get("poster"):
            self.external_resources.append((tag, values["poster"]))
        if tag == "link" and values.get("href"):
            rel = set(values.get("rel", "").lower().split())
            if rel & {"stylesheet", "icon", "preload", "modulepreload"}:
                self.external_resources.append((tag, values["href"]))
        if tag == "image":
            resource = values.get("href") or values.get("xlink:href")
            if resource:
                self.external_resources.append((tag, resource))
        if tag == "svg":
            self.svg_count += 1
            if not values.get("viewbox"):
                self.svg_without_viewbox += 1


def load_json(path: Path, issues: list[Issue]) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        issues.append(Issue("ERROR", str(path), "缺少 JSON 文件"))
    except UnicodeDecodeError as exc:
        issues.append(Issue("ERROR", str(path), f"不是 UTF-8：{exc}"))
    except json.JSONDecodeError as exc:
        issues.append(Issue("ERROR", str(path), f"JSON 无效：{exc}"))
    return None


def local_target(base: Path, href: str) -> Path | None:
    split = urlsplit(href)
    if split.scheme or split.netloc:
        return None
    if href.startswith("#") or not split.path:
        return None
    return (base / unquote(split.path)).resolve()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def local_reference_issue(
    base: Path,
    href: str,
    allowed_root: Path,
    *,
    require_local: bool = False,
) -> str | None:
    split = urlsplit(href)
    if split.scheme == "file":
        return f"禁止 file:// 链接：{href}"
    if split.scheme and split.scheme not in SAFE_LINK_SCHEMES:
        return f"不支持链接协议：{href}"
    if split.scheme in SAFE_LINK_SCHEMES or split.netloc:
        return f"必须使用 OUTPUT_ROOT 内的相对路径：{href}" if require_local else None

    target = local_target(base, href)
    if target is None:
        return "必须使用 OUTPUT_ROOT 内的相对文件路径" if require_local else None
    if not is_within(target, allowed_root):
        return f"本地链接越出 OUTPUT_ROOT：{href}"
    if not target.exists():
        return f"本地链接不存在：{href}"
    return None


def inspect_private_paths(data: object, path: Path, issues: list[Issue]) -> None:
    inspect_shared_private_paths(data, f"{path}:$", issues)


def inspect_record_ids(
    records: object,
    label: str,
    path: Path,
    issues: list[Issue],
) -> None:
    if not isinstance(records, list):
        return
    ids: list[str] = []
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            issues.append(Issue("ERROR", str(path), f"{label}[{index}] 必须是对象"))
            continue
        record_id = item.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            issues.append(Issue("ERROR", str(path), f"{label}[{index}] 缺少稳定 ID"))
            continue
        ids.append(record_id)
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        issues.append(Issue("ERROR", str(path), f"{label} 存在重复 ID：{', '.join(duplicates)}"))


def inspect_html(
    path: Path,
    issues: list[Issue],
    allowed_root: Path,
) -> ArtifactHTMLParser | None:
    try:
        html = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        issues.append(Issue("ERROR", str(path), "缺少 HTML 文件"))
        return None
    except UnicodeDecodeError as exc:
        issues.append(Issue("ERROR", str(path), f"不是 UTF-8：{exc}"))
        return None

    parser = ArtifactHTMLParser()
    parser.feed(html)
    duplicate_ids = sorted(key for key, count in Counter(parser.ids).items() if count > 1)
    if duplicate_ids:
        issues.append(Issue("ERROR", str(path), f"重复 ID：{', '.join(duplicate_ids)}"))

    known_ids = set(parser.ids)
    for _, href in parser.links:
        split = urlsplit(href)
        reference_issue = local_reference_issue(path.parent, href, allowed_root)
        if reference_issue:
            issues.append(Issue("ERROR", str(path), reference_issue))
        if split.fragment and not split.path and split.fragment not in known_ids:
            issues.append(Issue("ERROR", str(path), f"内部锚点不存在：#{split.fragment}"))

    for tag, resource in parser.external_resources:
        split = urlsplit(resource)
        if not resource.startswith("#") and split.scheme != "data":
            issues.append(Issue("ERROR", str(path), f"存在外部页面资源：<{tag}> {resource}"))

    if parser.lang not in {"zh", "zh-CN", "zh-Hans"}:
        issues.append(Issue("WARNING", str(path), f"页面语言不是明确的简体中文：{parser.lang!r}"))
    if parser.svg_without_viewbox:
        issues.append(Issue("ERROR", str(path), f"有 {parser.svg_without_viewbox} 个 SVG 缺少 viewBox"))

    marker_refs = set(re.findall(r"url\(#([A-Za-z_][\w:.-]*)\)", html))
    missing_markers = sorted(marker_refs - known_ids)
    if missing_markers:
        issues.append(Issue("ERROR", str(path), f"SVG 引用不存在：{', '.join(missing_markers)}"))
    return parser


def module_records(data: dict[str, object]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for value in data.get("modules", []) if isinstance(data.get("modules"), list) else []:
        if isinstance(value, dict):
            records.append(value)
    policy = data.get("module_policy")
    if isinstance(policy, dict):
        candidates = policy.get("candidates")
        if isinstance(candidates, list):
            for value in candidates:
                if isinstance(value, dict) and value.get("status") == "generated":
                    records.append(value)
    return records


def has_field(data: object, path: str) -> bool:
    if isinstance(data, list):
        return any(has_field(item, path) for item in data)
    if not isinstance(data, dict):
        return False
    head, _, tail = path.partition(".")
    value = data.get(head)
    return has_field(value, tail) if tail else nonempty(value)


def inspect_sections(data: dict, path: Path, issues: list[Issue], strict: bool):
    def any_field(*names):
        return any(has_field(data, name) for name in names)

    coverage = [
        ("书籍身份、版本与材料边界", any_field("book") and any_field("source")
         and any_field("scope", "source.credible_range", "source.metadata_limitations", "version_boundary")),
        ("全书问题与展开结构", any_field("book.one_sentence_model", "whole_book_model.question", "central_question")
         and any_field("whole_book_model", "coverage", "volumes", "works", "core_route", "generation_audit.whole_book_identity")),
        ("主要观点与论证依据", any_field("claims.statement", "claims.text")
         and any_field("claims.locators", "claims.locator", "claims.source_excerpt_ids", "claims.derived_from", "claims.supports")),
        ("人物、力量、概念或阶段的关键关系", any_field("relationships", "characters", "conceptual_roles", "themes", "concepts", "whole_book_model.stages", "works.series")),
        ("作者、综合、批判和外部背景的标型", any_field("claims.type", "claims.kind", "claims.label")),
        ("首轮回原文路线与理由", any_field("core_route", "deep_read_list", "source_return_route", "reading_route", "original_reading_route")),
        ("全读、选读、深挖或停止的阅读决策", any_field("verdict", "reading_decision", "read_decision", "next_steps")),
    ]
    for number, (label, present) in enumerate(coverage, 1):
        if not present:
            issues.append(Issue("ERROR" if strict else "WARNING", f"{path}:$", f"主页面第 {number} 项缺少已知字段覆盖：{label}"))


def inspect_book(book_dir: Path, source_path: Path | None = None,
                 strict_sections: bool = False, audit: dict | None = None) -> list[Issue]:
    book_dir = book_dir.resolve()
    issues: list[Issue] = []
    if not book_dir.is_dir():
        return [Issue("ERROR", str(book_dir), "书籍目录不存在")]
    output_root = book_dir.parent.parent.resolve() if book_dir.parent.name == "books" else book_dir

    leaked_sources = sorted(
        path.relative_to(book_dir).as_posix()
        for path in book_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in PRIVATE_SOURCE_SUFFIXES
    )
    if leaked_sources:
        issues.append(Issue("ERROR", str(book_dir), f"目录含疑似私有原书：{', '.join(leaked_sources)}"))

    main_json = book_dir / "reading.json"
    data = load_json(main_json, issues)
    inspect_html(book_dir / "reading.html", issues, output_root)
    if not isinstance(data, dict):
        issues.append(Issue("ERROR", str(main_json), "reading.json 必须是对象"))
        return issues
    inspect_private_paths(data, main_json, issues)
    inspect_sections(data, main_json, issues, strict_sections)

    schema_version = data.get("schema_version")
    if "schema_version" in data and schema_version not in ACCEPTED_SCHEMA_VERSIONS:
        issues.append(Issue("ERROR", str(main_json), f"不支持 schema_version：{schema_version!r}"))
    required = (
        V1_REQUIRED_FIELDS
        if schema_version == "read-book.v1"
        else {"schema_version", "artifact_kind", "reading_contract"}
    )
    missing = sorted(required - data.keys())
    if missing:
        issues.append(Issue("ERROR", str(main_json), f"缺少顶层字段：{', '.join(missing)}"))
    if "artifact_kind" in data and data.get("artifact_kind") != "rapid-reading-map":
        issues.append(Issue("ERROR", str(main_json), "artifact_kind 必须是 rapid-reading-map"))

    contract = data.get("reading_contract")
    if "reading_contract" in data and not isinstance(contract, dict):
        issues.append(Issue("ERROR", str(main_json), "reading_contract 必须是对象"))
    elif isinstance(contract, dict):
        for key in ("progressive_depth", "completion_definition"):
            if not isinstance(contract.get(key), list) or not contract.get(key):
                issues.append(Issue("ERROR", str(main_json), f"reading_contract.{key} 必须是非空数组"))

    claims = data.get("claims")
    if schema_version == "read-book.v1" and "claims" in data and not isinstance(claims, list):
        issues.append(Issue("ERROR", str(main_json), "claims 必须是数组"))
    inspect_record_ids(claims, "claims", main_json, issues)

    raw_modules = data.get("modules")
    if schema_version == "read-book.v1" and "modules" in data and not isinstance(raw_modules, list):
        issues.append(Issue("ERROR", str(main_json), "modules 必须是数组"))
    inspect_record_ids(raw_modules, "modules", main_json, issues)
    if isinstance(raw_modules, list):
        for index, item in enumerate(raw_modules):
            if isinstance(item, dict) and item.get("status") != "generated":
                issues.append(Issue("ERROR", str(main_json), f"modules[{index}] 不是 generated"))

    policy = data.get("module_policy")
    if isinstance(policy, dict):
        if policy.get("generation") != "on_demand_only":
            issues.append(Issue("ERROR", str(main_json), "module_policy.generation 必须是 on_demand_only"))
        inspect_record_ids(policy.get("candidates"), "module_policy.candidates", main_json, issues)
    elif schema_version == "read-book.v1" and "module_policy" in data:
        issues.append(Issue("ERROR", str(main_json), "module_policy 必须是对象"))

    records = module_records(data)
    ids = {str(item.get("id")) for item in records if item.get("id")}
    for item in records:
        module_id = str(item.get("id") or item.get("title") or "<unknown>")
        parent = item.get("parent_module")
        if parent and str(parent) not in ids:
            issues.append(Issue("ERROR", str(main_json), f"模块 {module_id} 的父模块不存在：{parent}"))
        for key in ("href", "data"):
            value = item.get(key)
            if isinstance(value, str):
                reference_issue = local_reference_issue(
                    book_dir,
                    value,
                    output_root,
                    require_local=True,
                )
                if reference_issue:
                    issues.append(Issue("ERROR", str(main_json), f"模块 {module_id} 的 {key}：{reference_issue}"))

    modules_root = book_dir / "modules"
    if modules_root.is_dir():
        referenced_html = {
            unquote(urlsplit(str(item["href"])).path)
            for item in records
            if isinstance(item.get("href"), str)
        }
        for module_dir in sorted(path for path in modules_root.iterdir() if path.is_dir()):
            html_path = module_dir / "reading.html"
            json_path = module_dir / "reading.json"
            inspect_html(html_path, issues, output_root)
            module_data = load_json(json_path, issues)
            relative_html = html_path.relative_to(book_dir).as_posix()
            if relative_html not in referenced_html:
                issues.append(Issue("ERROR", str(module_dir), "模块存在但主 reading.json 未登记"))
            if isinstance(module_data, dict):
                inspect_private_paths(module_data, json_path, issues)
                kind = module_data.get("artifact_kind")
                if not isinstance(kind, str) or "deep-dive" not in kind:
                    issues.append(Issue("ERROR", str(json_path), "模块 artifact_kind 必须包含 deep-dive"))
            else:
                issues.append(Issue("ERROR", str(json_path), "模块 reading.json 必须是对象"))

    if source_path is not None:
        source = None
        audit = audit if audit is not None else {}
        try:
            source = SourceDocument(source_path)
            inherited = data.get("source") if isinstance(data.get("source"), dict) else {}
            audit.update(sha256=source.sha256, expected_sha256=inherited.get("sha256"), documents=[])
            inspect_source(data, main_json, source, {}, issues, audit)
            # A wrong main-source hash is a stop condition for all modules.
            if str(inherited.get("sha256", "")).lower() == source.sha256:
                for json_path in sorted(modules_root.rglob("reading.json")):
                    module_data = load_json(json_path, issues)
                    if isinstance(module_data, dict):
                        inspect_source(module_data, json_path, source, inherited, issues, audit)
        except SourceError as exc:
            issues.append(Issue("ERROR", "--source", str(exc)))
        finally:
            if source is not None:
                source.close()
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="验证渐进式读书地图目录")
    parser.add_argument("book_dir", type=Path, help="books/<中文书名> 目录")
    parser.add_argument("--source", type=Path, help="仓库外的 TXT、Markdown 或 EPUB 原书")
    parser.add_argument("--strict-sections", action="store_true", help="新书：七项字段覆盖缺失视为 ERROR")
    args = parser.parse_args()

    book_dir = args.book_dir.expanduser().resolve()
    audit = {}
    issues = inspect_book(book_dir, args.source.expanduser() if args.source else None,
                          args.strict_sections, audit)
    if audit:
        documents = audit.get("documents", [])
        checked = sum(item["quotes_checked"] for item in documents)
        matched = sum(item["quotes_matched"] for item in documents)
        hints = sum(item["hints_checked"] for item in documents)
        hash_match = str(audit.get("expected_sha256", "")).lower() == audit["sha256"]
        print(f"SOURCE: sha256={audit['sha256']}; match={hash_match}; quotes_checked={checked}; quotes_matched={matched}; hints_checked={hints}")
    for issue in issues:
        print(f"{issue.level}: {issue.location}: {issue.message}")

    errors = sum(issue.level == "ERROR" for issue in issues)
    warnings = sum(issue.level == "WARNING" for issue in issues)
    if errors:
        print(f"FAILED: {errors} error(s), {warnings} warning(s)")
        return 1
    print(f"PASSED: 0 error(s), {warnings} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
