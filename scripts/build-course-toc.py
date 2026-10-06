#!/usr/bin/env python3
"""Build the spoiler-light course directory using explicit display fields only."""

import argparse
from html import escape
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COURSE = ROOT / "books/置身事内/course/course.json"

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="《置身事内》课程目录：按单元定位原文，带着问题阅读。">
  <title>置身事内 · 课程目录</title>
  <style>
    :root {
      color-scheme: light;
      --paper: #f7f4ed;
      --surface: #fffdf8;
      --ink: #243431;
      --muted: #61706c;
      --line: #d8ded9;
      --accent: #345f55;
      --accent-soft: #e5eee9;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: ui-serif, "Noto Serif SC", "Source Han Serif SC", "Songti SC", Georgia, serif;
      line-height: 1.75;
      overflow-wrap: anywhere;
    }
    a { color: var(--accent); text-underline-offset: 0.2em; }
    a:focus-visible { outline: 3px solid var(--accent); outline-offset: 4px; border-radius: 6px; }
    .shell { width: min(100% - 32px, 880px); margin-inline: auto; }
    .skip-link { position: fixed; z-index: 10; top: 12px; left: 12px; padding: 10px 14px; background: var(--ink); color: white; transform: translateY(-160%); }
    .skip-link:focus { transform: translateY(0); }
    header { padding: 40px 0 28px; }
    nav { display: flex; flex-wrap: wrap; gap: 8px 24px; font-family: ui-sans-serif, system-ui, sans-serif; }
    nav a { display: inline-flex; align-items: center; min-height: 44px; }
    .eyebrow { margin: 28px 0 12px; color: var(--accent); font: 700 0.82rem/1.75 ui-sans-serif, system-ui, sans-serif; letter-spacing: 0.1em; }
    h1 { margin: 0; font-size: clamp(1.9rem, 5vw, 3rem); line-height: 1.25; }
    .intro { margin-top: 24px; padding-left: 20px; border-left: 3px solid var(--accent); color: var(--muted); }
    .intro p { margin: 8px 0; }
    main { padding-bottom: 48px; }
    .units { list-style: none; margin: 0; padding: 0; display: grid; gap: 24px; }
    .unit { padding: clamp(20px, 4vw, 36px); border: 1px solid var(--line); border-radius: 20px; background: var(--surface); }
    .unit-head { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
    h2 { margin: 0; font-size: 1.4rem; }
    .status { padding: 2px 12px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font: 600 0.85rem/1.75 ui-sans-serif, system-ui, sans-serif; }
    .pending { background: var(--paper); color: var(--muted); }
    dl { margin: 20px 0; }
    dl > div { display: grid; grid-template-columns: 4em minmax(0, 1fr); gap: 12px; margin-top: 8px; }
    dt { color: var(--muted); }
    dd { margin: 0; }
    h3 { margin: 24px 0 8px; font-size: 1.05rem; }
    .questions { margin: 0; padding-left: 1.5em; }
    .questions li + li { margin-top: 12px; }
    .watch { margin: 20px 0 0; color: var(--accent); }
    footer { padding: 24px 0 36px; border-top: 1px solid var(--line); }
    @media (max-width: 720px) { header { padding-top: 24px; } }
  </style>
</head>
<body>
  <a class="skip-link" href="#units">跳到单元目录</a>
  <header class="shell">
    <nav aria-label="页面导航">
      <a href="../../../index.html">回到首页</a>
      <a href="../reading.html">全书地图</a>
    </nav>
    <p class="eyebrow">READING MAPS · 课程目录</p>
    <h1>置身事内 · 课程目录</h1>
    <div class="intro">
      <p>答案和批判由学伴在你尝试之后揭示。</p>
      <p>course.json 是公开的，本页只是不主动展示答案。</p>
      <p>定位按上海人民出版社 2021 年版，请核对你手上的版本。</p>
    </div>
  </header>
  <main id="units" class="shell">
    <ol class="units" aria-label="阅读单元" role="list">
__UNITS__
    </ol>
  </main>
  <footer class="shell">
    <nav aria-label="页尾导航">
      <a href="../../../index.html">回到首页</a>
      <a href="../reading.html">全书地图</a>
    </nav>
  </footer>
</body>
</html>
"""


def text(value):
    """Escape display values; never serialize source objects into the page."""
    return escape(str(value), quote=True)


def render_unit(unit):
    order = int(unit["order"])
    status = {"full": "已备课", "index_only": "待备课"}[unit["status"]]
    status_class = "status" if unit["status"] == "full" else "status pending"
    locate = unit["locate"]
    rows = [(label, locate[key]) for key, label in (
        ("part", "部"), ("chapter", "章"), ("section", "节"),
        ("start_hint", "起始提示"), ("end_hint", "结束提示"),
    ) if locate.get(key)]
    if locate.get("estimated_minutes") is not None:
        rows.append(("预计阅读", f'{locate["estimated_minutes"]} 分钟'))
    details = "\n".join(
        f"            <div><dt>{label}</dt><dd>{text(value)}</dd></div>"
        for label, value in rows
    )
    preparation = ""
    if unit["status"] == "full":
        questions = unit["pre_questions"]
        if len(questions) != 3:
            raise ValueError(f"单元 {order} 必须有三道预习题")
        items = "\n".join(
            f'            <li>{text(question["question"])}</li>'
            for question in questions
        )
        preparation = f"""
          <h3>带着三个问题读</h3>
          <ol class="questions">
{items}
          </ol>
          <p class="watch">留意概念：{text(unit["watch"]["concept"])}</p>"""
    return f"""      <li id="unit-{order:02d}" class="unit">
        <article aria-labelledby="unit-{order:02d}-title">
          <div class="unit-head">
            <h2 id="unit-{order:02d}-title">第 {order:02d} 单元</h2>
            <span class="{status_class}">{status}</span>
          </div>
          <dl>
{details}
          </dl>{preparation}
        </article>
      </li>"""


def render(course):
    units = sorted(course["units"], key=lambda unit: unit["order"])
    return PAGE.replace("__UNITS__", "\n".join(render_unit(unit) for unit in units))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("course", nargs="?", type=Path, default=DEFAULT_COURSE)
    parser.add_argument("--output", type=Path, help="默认写入 course.json 同目录的 index.html")
    args = parser.parse_args()
    course = json.loads(args.course.read_text(encoding="utf-8"))
    output = args.output or args.course.with_name("index.html")
    output.write_text(render(course), encoding="utf-8", newline="\n")
    print(f"Generated: {output}")


if __name__ == "__main__":
    main()
