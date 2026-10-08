# 阅读课程契约

课程从已有完整来源的主地图生成，保存到 `books/<书名>/course/course.json`。沿用主地图的书籍身份、原书 SHA-256、版本与纳入范围；目录或样章不足以建课。

## 学习回路

晨卡只呈现定位、全书位置、三个预习问题、留意概念和到期复习题。读者先读原文，再交三句复述、回答和一个质疑；点评先对照答案要点，之后才揭示批判。不打卡不推进、不叠加新单元。个人打卡与掌握记录保留在 Bot，不能写进公开课程。

历史、传记、地理、心理学的三类预习题参照[书类审计与课程指引](genre-audits.md)中的题型指引，仍使用 `structure`、`argument`、`self`。

## JSON 字段

| 字段 | 类型与要求 |
| --- | --- |
| `book` | 非空对象；复制主地图的书籍身份与版本信息 |
| `source` | 非空对象；至少含 `sha256`，其余版本、格式、范围与主地图一致；TXT 保留 `credible_range` |
| `edition_check` | `pending`、`matched` 或 `mismatched`；微信读书目录尚未核对时用 `pending` |
| `budget` | `min_minutes`、`target_minutes`、`max_minutes`，均为正数且按此顺序递增或相等 |
| `units` | 非空数组；每单元 `id` 唯一，`order` 从 1 开始连续，`status` 为 `full` 或 `index_only` |
| `units[].locate` | 至少有一个部/章/节标题（`part`、`chapter`、`section`）；`start_hint`、`end_hint` 是原文中逐字可查的起止句提示，各 1–20 字；完整单元另含 `word_count` 正整数和预算范围内的 `estimated_minutes` |
| `units[].locate.source_refs` | 可选审计定位数组；TXT 用 `{start_line, end_line}`，EPUB 用 `{epub_path}`，也可加 `blocks` 或 `paragraph`；不要填机器上的原书路径 |
| `units[].position` | 一句话说明本单元在全书论证中的位置 |
| `units[].pre_questions` | 完整单元恰好 3 个 `{kind, question}`；`kind` 为 `structure`、`argument`、`self` 各一道 |
| `units[].watch` | 完整单元的 `{concept, why}`；只选一个概念并解释留意理由 |
| `units[].answer_key` | 完整单元的非空答案要点；推荐含 `retelling_points`、`author_claim`、`reasons`、`evidence`、`common_misreadings`；给要点，不给照抄范文 |
| `units[].critique` | 完整单元的数组；每项 `{type, text, sources}`，`type` 只能为 `批判审计` 或 `外部背景`；`sources` 是非空来源数组，每项为定位字符串，或含 `locator`、`url`、`ref` 之一的对象；没有可核准的批判时可留空数组 |
| `units[].review_questions` | 完整单元的数组；每项 `{unit_ids, question, answer_key}`；`unit_ids` 非空且只能指向 `order` 更小的已学单元；没有到期复习题时用空数组 |
| `units[].cards` | 完整单元的数组；每项 `{concept, definition, unit_ids}`；用自己的话转述作者定义，关联已有单元；不需要卡片时用空数组 |

`index_only` 除 `id/order/status` 外只要求 `locate` 和 `position`，不要求题目、答案、批判、复习题、卡片、字数或分钟数；若提前填了分钟数或引用，仍须合法。句提示的长度按 HTML 实体解码后的字符数计，包含标点，忽略两端空白。

## 切分与公开边界

- 按论证边界切分，不按章号机械分配。超预算在小节边界拆开，相邻短小节可以合并；每单元说明“删掉它，后面哪一步会读不懂”。以每分钟约 300–400 字估时，再考虑难度，分钟数须落入预算。
- 默认原文约 25 分钟、回复约 5 分钟；具体上下限写进 `budget`，不把估算当成所有读者的阅读速度保证。
- 先建完整索引，只写满任务授权的少量单元。以后按真实学习进度增量补齐；不改写已经审过的其他单元或主地图。
- 批判优先复用主地图的 `critical_audit` 与已审计深挖模块，并保留具体来源定位；新引入的外部背景需要来源。
- 课程公开；题目、答案、批判和定义都用自己的话写，定位提示每条不超过 20 字，不收长引文，不放原书、私有绝对路径或打卡记录。
- 校验器只能检查结构与文字匹配，不能判断观点忠实度、题目质量或总体版权边界；仍须内容复审。

## 校验

```sh
python3 .agents/skills/read-book/scripts/validate-course.py 'books/<书名>/course/course.json'
python3 .agents/skills/read-book/scripts/validate-course.py 'books/<书名>/course/course.json' --source '<仓库外原书>'
```

同书 `reading.json` 存在时，即使不带 `--source`，也会核对主地图与课程的 `source.sha256` 一致；标准路径为 `<书>/course/course.json` 对应 `<书>/reading.json`，独立样例也支持两文件放在同一目录。

带 `--source` 时先核对 SHA-256，再逐字检查起止提示；只归一化空白与 HTML 实体，有明确定位时不能用别处的相同文字掩盖定位错误。示例在 `../tests/fixtures/course.valid.json`，配套 `source.md` 是专为测试自写的虚构文本。
