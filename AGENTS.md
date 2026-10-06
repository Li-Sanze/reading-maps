# reading-maps：Agent 工作入口

本仓库把中文书籍整理为可回到原文的渐进式阅读地图。公开产物在 `books/<书名>/`；先读对应 Skill，再依据已核实的完整来源工作。

## 硬边界

- GitHub Pages 以 legacy 模式从 `main` 根目录发布。进入 `main` 的任何文件都可能被公开下载。
- EPUB、PDF、MOBI、AZW3、DJVU、TXT 等原书和 `sources/` 目录绝不放入本仓库工作树、Git index 或提交；私有原书仅在仓库外的临时位置读取。不要推送 `main`。
- README 只介绍书架、用法、产物与公开内容边界；不写原书下载链接、不放原书正文。
- 公开内容仅含原创结构、评论、图示、必要短引文和来源定位。引文须回原书逐字核对；版本与材料限制须写明。
- 不改已有书籍产物或发布内容，除非任务明确授权。未经授权，不提交、推送或发布阅读地图。

## 任务路由

| 任务 | 必读 Skill | 约束 |
| --- | --- | --- |
| 主地图、深挖、最小修订、课程 | `.agents/skills/read-book/SKILL.md` | 遵守其来源审计、内容标型和产物契约 |
| 机制图 | `.agents/skills/fireworks-tech-graph/SKILL.md` | 可选能力；只有确实降低理解成本才使用；使用前运行 `python3 -c "import cairosvg"` 自检，不可用时只输出内嵌 SVG，并在回执中注明 |
| 全书一图 | `.agents/skills/doc-to-sketch/SKILL.md` | 每本最多一张，可选。Cloud Agent 等无人值守任务：环境未设置 `DOC_TO_SKETCH_UNATTENDED` 时只交付 Path C 提示词，不得使用宿主原生生图；已设置时按该 Skill 的 Unattended mode 执行（只走 Path B） |

Skill 真源是 `.agents/skills/`。`skills/read-book` 是兼容旧命令的链接；`.claude/skills/` 链接到同一份 Skill。宿主发现路径：[Cursor](https://cursor.com/docs/skills)、[Codex](https://developers.openai.com/codex/skills)、[Claude Code](https://code.claude.com/docs/en/skills)。Cursor 也读取 `.claude/skills/`，可能重复显示同名 Skill；任务中明确使用上述真源路径。

## 停车条件

- 原书 SHA-256 与任务给定值不符：停止生成并报告实测值。
- 只有目录、样章、节选或旧笔记等局部来源：不生成全书主地图或课程。
- 版本、译本或材料冲突会改变理解：暂停并列出冲突，不自行选定版本。
- 无人值守全书一图任务若当前固定版本未提供可执行的 Unattended mode：暂停该图，报告限制。
- 不截取原书插图放上公开页面；机制图、数据图用 fireworks 重绘为内嵌 SVG，并注明“据原书图 X-X 重绘”和数据来源。

## 必跑校验

- `course.json` 改动后，必须运行 `python3 scripts/build-course-toc.py` 重新生成课程目录页。

```sh
bash scripts/check-no-sources.sh
git submodule status
for book in books/*/; do
  [ -d "$book" ] || continue
  python3 .agents/skills/read-book/scripts/validate-reading-map.py "$book"
done
python3 skills/read-book/scripts/validate-reading-map.py 'books/置身事内/'
if [ -d .agents/skills/read-book/tests ]; then
  python3 -m unittest discover -s .agents/skills/read-book/tests -v
fi
# 有原书的生成或修订任务：原书须留在仓库外
python3 .agents/skills/read-book/scripts/validate-reading-map.py 'books/<书名>/' --source '<仓库外原书>'
# 仅新书：在上条命令后加 --strict-sections，旧书缺项只报 WARNING
# 课程文件存在时运行；有原书时追加 --source '<仓库外原书>'
python3 .agents/skills/read-book/scripts/validate-course.py 'books/<书名>/course/course.json'
```

`--source` 会核对 SHA-256、逐字引文和定位；不带它的校验不能证明来源一致。字段覆盖与文字匹配不能替代内容复审。页面修改需目视检查桌面和手机布局，做不到就在回执中标为未验证。

## PR 与回执

PR 描述写明目标与实际修改、原书版本及 SHA-256、`git submodule status` 原样输出、上述校验命令及输出、截图或视觉检查结果、未验证项和风险。submodule 升级单独说明原因。只在任务明确授权后开 PR；不推送 `main`。
