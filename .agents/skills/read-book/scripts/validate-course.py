#!/usr/bin/env python3
"""Validate a public reading course and optional private source using stdlib."""

from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import math
from pathlib import Path
import re
import sys

from source_validation import (
    Issue, SourceDocument, SourceError, check_text, inspect_locators,
    inspect_private_paths, nonempty,
)


def positive_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def inspect_course(path: Path, source_path: Path | None = None, audit: dict | None = None) -> list[Issue]:
    issues = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [Issue("ERROR", str(path), f"无法读取课程 JSON：{type(exc).__name__}")]

    def error(pointer, message):
        issues.append(Issue("ERROR", f"{path}:{pointer}", message))

    if not isinstance(data, dict):
        return [Issue("ERROR", str(path), "课程须为对象")]
    inspect_private_paths(data, f"{path}:$", issues)
    for key in ("book", "source", "budget"):
        if not isinstance(data.get(key), dict) or not nonempty(data[key]):
            error(f"$.{key}", "必须是非空对象")
    metadata = data.get("source") if isinstance(data.get("source"), dict) else {}
    expected = metadata.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        error("$.source.sha256", "必须是 64 位 SHA-256")
    book_dir = path.parent.parent if path.parent.name == "course" else path.parent
    main_map = book_dir / "reading.json"
    if main_map.exists():
        try:
            main_data = json.loads(main_map.read_text(encoding="utf-8"))
            main_source = main_data.get("source") if isinstance(main_data, dict) else None
            main_sha = main_source.get("sha256") if isinstance(main_source, dict) else None
            if not isinstance(main_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", main_sha):
                error("$.source.sha256", "同书 reading.json 缺少有效 source.sha256")
            elif not isinstance(expected, str) or main_sha.lower() != expected.lower():
                error("$.source.sha256", f"与同书 reading.json 的 source.sha256 不一致：map={main_sha}, course={expected}")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            error("$.source.sha256", f"无法读取同书 reading.json：{type(exc).__name__}")
    if data.get("edition_check") not in ("pending", "matched", "mismatched"):
        error("$.edition_check", "必须为 pending、matched 或 mismatched")
    budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    minimum, target, maximum = (budget.get(key) for key in ("min_minutes", "target_minutes", "max_minutes"))
    budget_ok = all(positive_number(value) for value in (minimum, target, maximum))
    if not budget_ok or not minimum <= target <= maximum:
        error("$.budget", "须有正数 min_minutes ≤ target_minutes ≤ max_minutes")
        budget_ok = False
    units = data.get("units")
    if not isinstance(units, list) or not units:
        error("$.units", "必须是非空数组")
        return issues

    ids = [unit.get("id") for unit in units if isinstance(unit, dict) and isinstance(unit.get("id"), str)]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        error("$.units", f"id 重复：{', '.join(duplicates)}")
    orders = [unit.get("order") for unit in units if isinstance(unit, dict) and type(unit.get("order")) is int]
    if len(orders) != len(units) or sorted(orders) != list(range(1, len(units) + 1)):
        error("$.units", "order 必须从 1 开始连续且不重复")
    id_to_order = {unit["id"]: unit.get("order") for unit in units
                   if isinstance(unit, dict) and isinstance(unit.get("id"), str)}

    for index, unit in enumerate(units):
        pointer = f"$.units[{index}]"
        if not isinstance(unit, dict):
            error(pointer, "单元须为对象")
            continue
        if not isinstance(unit.get("id"), str) or not unit["id"].strip():
            error(pointer + ".id", "必须是非空字符串")
        status = unit.get("status")
        if status not in ("full", "index_only"):
            error(pointer + ".status", "必须为 full 或 index_only")
        if not isinstance(unit.get("position"), str) or not unit["position"].strip():
            error(pointer + ".position", "必须说明本单元在全书中的位置")
        locate = unit.get("locate")
        if not isinstance(locate, dict):
            error(pointer + ".locate", "须为对象")
            locate = {}
        if not any(isinstance(locate.get(key), str) and locate[key].strip() for key in ("part", "chapter", "section")):
            error(pointer + ".locate", "至少给出部、章或节标题")
        for key in ("start_hint", "end_hint"):
            hint = locate.get(key)
            if not isinstance(hint, str) or not hint.strip() or len(html.unescape(hint).strip()) > 20:
                error(pointer + ".locate." + key, "起止句提示须为 1–20 字（含标点）的字符串")
        if "source_refs" in locate and (not isinstance(locate["source_refs"], list) or not locate["source_refs"]):
            error(pointer + ".locate.source_refs", "如提供，须为非空定位数组")
        elif isinstance(locate.get("source_refs"), list):
            for ri, ref in enumerate(locate["source_refs"]):
                if not isinstance(ref, dict) or not (
                    isinstance(ref.get("epub_path"), str) and ref["epub_path"].strip()
                    or type(ref.get("start_line")) is int and type(ref.get("end_line")) is int
                ):
                    error(pointer + f".locate.source_refs[{ri}]", "须给出 epub_path 或起止行号")
        if status == "full" or "estimated_minutes" in locate:
            minutes = locate.get("estimated_minutes")
            if not positive_number(minutes) or (budget_ok and not minimum <= minutes <= maximum):
                error(pointer + ".locate.estimated_minutes", "预计分钟数必须为正数且落在 budget 范围内")
        if status == "full" or "word_count" in locate:
            if type(locate.get("word_count")) is not int or locate["word_count"] < 1:
                error(pointer + ".locate.word_count", "字数须为正整数")

        if status == "full":
            questions = unit.get("pre_questions")
            if (not isinstance(questions, list) or len(questions) != 3
                    or not all(isinstance(q, dict) for q in questions)
                    or sorted(str(q.get("kind")) for q in questions) != ["argument", "self", "structure"]):
                error(pointer + ".pre_questions", "须恰有 3 题，kind 为 structure、argument、self 各一道")
            elif any(not isinstance(q.get("question"), str) or not q["question"].strip() for q in questions):
                error(pointer + ".pre_questions", "每道题的 question 必须非空")
            if not nonempty(unit.get("answer_key")) or not isinstance(unit.get("answer_key"), (str, list, dict)):
                error(pointer + ".answer_key", "答案要点不得为空")
            watch = unit.get("watch")
            if not isinstance(watch, dict) or not all(isinstance(watch.get(key), str) and watch[key].strip() for key in ("concept", "why")):
                error(pointer + ".watch", "须给出一个 concept 和 why")
            if not isinstance(unit.get("critique"), list):
                error(pointer + ".critique", "须为数组；没有可核准的批判时使用空数组")

        if "critique" in unit and isinstance(unit["critique"], list):
            for ci, critique in enumerate(unit["critique"]):
                cp = pointer + f".critique[{ci}]"
                if not isinstance(critique, dict):
                    error(cp, "须为对象")
                    continue
                if critique.get("type") not in ("批判审计", "外部背景"):
                    error(cp + ".type", "须标为批判审计或外部背景")
                if not isinstance(critique.get("text"), str) or not critique["text"].strip():
                    error(cp + ".text", "批判内容不得为空")
                sources = critique.get("sources")
                if (not isinstance(sources, list) or not sources
                        or any(not (isinstance(ref, str) and ref.strip()
                                    or isinstance(ref, dict) and any(isinstance(ref.get(key), str) and ref[key].strip()
                                                                     for key in ("locator", "url", "ref"))) for ref in sources)):
                    error(cp + ".sources", "每条批判都须附非空来源定位或 URL")

        for key in ("review_questions", "cards"):
            items = unit.get(key, [])
            if not isinstance(items, list) or (status == "full" and key not in unit):
                error(pointer + "." + key, "须为数组")
                continue
            for ri, item in enumerate(items):
                rp = pointer + f".{key}[{ri}]"
                if not isinstance(item, dict):
                    error(rp, "须为对象")
                    continue
                refs = item.get("unit_ids")
                if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and ref in id_to_order for ref in refs):
                    error(rp + ".unit_ids", "须引用已定义的单元 id")
                elif key == "review_questions":
                    current = unit.get("order")
                    if type(current) is not int or any(type(id_to_order[ref]) is not int or id_to_order[ref] >= current for ref in refs):
                        error(rp + ".unit_ids", "复习题只能引用 order 更小的已学单元")
                required = ("question", "answer_key") if key == "review_questions" else ("concept", "definition")
                for field in required:
                    if not nonempty(item.get(field)):
                        error(rp + "." + field, "不得为空")

    if source_path is not None:
        source = None
        try:
            source = SourceDocument(source_path)
            if audit is not None:
                audit.update(sha256=source.sha256, expected_sha256=expected, hints_checked=0)
            if not isinstance(expected, str) or source.sha256 != expected.lower():
                error("$.source.sha256", f"SHA-256 不符：actual={source.sha256}；停止来源核对")
                return issues
            if source.format == "text":
                source.credible_bounds(metadata)
            inspect_locators(data, source, metadata, path, issues)
            for index, unit in enumerate(units):
                locate = unit.get("locate") if isinstance(unit, dict) else None
                if not isinstance(locate, dict):
                    continue
                for key in ("start_hint", "end_hint"):
                    hint = locate.get(key)
                    if not isinstance(hint, str) or not hint.strip():
                        continue
                    if audit is not None:
                        audit["hints_checked"] += 1
                    pointer = f"$.units[{index}].locate.{key}"
                    try:
                        matched, located = check_text(hint, locate, data, source, metadata)
                        if not matched:
                            error(pointer, "起止句提示在所标定位或原书中未逐字找到")
                        if not located:
                            issues.append(Issue("WARNING", f"{path}:{pointer}", "未提供可解析 source_refs，仅在可信原书范围中检索"))
                    except SourceError as exc:
                        error(pointer, str(exc))
        except SourceError as exc:
            error("$.source", str(exc))
        finally:
            if source is not None:
                source.close()
    return issues


def main():
    parser = argparse.ArgumentParser(description="验证公开阅读课程 course.json")
    parser.add_argument("course_json", type=Path)
    parser.add_argument("--source", type=Path, help="仓库外的 TXT、Markdown 或 EPUB 原书")
    args = parser.parse_args()
    audit = {}
    issues = inspect_course(args.course_json.expanduser(), args.source.expanduser() if args.source else None, audit)
    if audit:
        print(f"SOURCE: sha256={audit['sha256']}; hints_checked={audit['hints_checked']}")
    for issue in issues:
        print(f"{issue.level}: {issue.location}: {issue.message}")
    errors = sum(issue.level == "ERROR" for issue in issues)
    warnings = sum(issue.level == "WARNING" for issue in issues)
    print(f"{'FAILED' if errors else 'PASSED'}: {errors} error(s), {warnings} warning(s)")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
