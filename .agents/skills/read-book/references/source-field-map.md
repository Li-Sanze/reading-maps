# 现有地图的引文与字段映射

本表对应仓库的 6 本主地图和 15 个模块。`--source` 使用下列映射；未显式标为原话的 `claims[].statement/text` 是转述，不能当成逐字引文。引文计数按 JSON 字段出现次数计，同一原句在两个字段中出现会核对两次。

| 书籍或模块结构 | 原话字段 | 定位 | 来源 SHA-256 |
| --- | --- | --- | --- |
| 如何阅读一本书 | `excerpts[].quote`（4 条） | 同项 `start_line/end_line`；以 `source.credible_range` 限定可信正文 | `source.sha256` |
| 乌合之众 | `claims[].short_quote`（1 条） | 同项 `locators[].epub_path`，另存 anchor/section | `source.sha256` |
| 月亮与六便士 | `claims[].short_quote`（3 条） | 同项 `locators[].epub_path`；`epub_paths` 中的数字文件范围展开后检查 | `source.sha256` |
| 毛选主地图 | `excerpts[].quote`（5 条） | 同项 `epub_path` | `source.sha256` |
| 毛选：实践与矛盾 | `excerpts[].quote`（6 条）、`original_reading_selections[].excerpt`（6 条） | `article` 对应 `source.articles[].title/epub_path`；或直接 `epub_path`，按 `blocks` 缩小范围 | `source.sha256` |
| 毛选：论持久战 | `original_reading_selections[].excerpt`（6 条） | 同项 `epub_path/blocks`；也支持 `source.article.epub_path` 默认路径 | `source.sha256` |
| 毛选：一号作战 | `original_reading_selections[].excerpt`（3 条） | 默认 `source_book.epub_path` + 同项 `blocks` | `source_book.sha256` |
| 毛选：星星之火、新民主主义、治理关系 | `original_reading_selections[].excerpt`（5、7、9 条） | 同项 `epub_path/paragraph`，`paragraph` 为非空正文 p 的 1 起始序号 | `source_book.sha256` |
| 置身事内主地图 | `claims[].short_quote`（9 条） | 同项 `locators[].epub_path` | `source.sha256` |
| 置身事内六模块 | `claims[].short_quote`（29 条）、`excerpts[].quote`（31 条） | 同项 `locators[].epub_path/blocks` 或 `epub_path/blocks` | 各模块 `source.sha256` |
| 阿加莎主地图 | 无独立原话字段；`claims[].text` 是转述 | 字符串 `locator` 中的内部文件名检查存在性；纯文字定位给 WARNING | `source.sha256` |
| 阿加莎三模块 | `original_reading_selections[].excerpt`（8、7、4 条） | 同项 `epub_path`；`source_work` 提供作品级范围和版权页路径 | 继承主地图 `source.sha256` |

此外，递归覆盖显式 `type/kind/label` 为 `作者原话`、`author_quote`、`direct_quote`、`original_quote` 的 `text/statement/content`；`search_text` 作为独立定位提示核对，不计入引文条数。

## 定位与匹配规则

- TXT/Markdown 按 UTF-8（可含 BOM）或 GB18030 解码，行号从 1 开始且两端包含。无精确定位时在 `credible_range` 中检索并排除 `excluded_ranges`，不跨排除行拼接匹配；`excluded_ranges` 不被误当作引文定位。
- EPUB 使用 `zipfile` 原位读取，不解包。段落为非空 p；文本块为非空 h1–h6/p。旧模块若在 `locator_method` 明示“块 1 为书名行”，则把 XHTML 的 title 计为块 1。连续块可以跨块匹配，跳过的块不会被拼成一条假引文。
- 路径必须存在；数字文件范围（如 `part0002.xhtml–part0004.xhtml`）逐个展开。自由文本定位里省略目录的文件名仅在 ZIP 内唯一时解析；不凭猜测选文件。
- 只解码 HTML 实体和消除空白差异。不改标点、引号、繁简字、脚注或省略号，不做模糊匹配。
- 有明确定位时须在该范围找到；没有可解析定位时搜索可信原书，并给 WARNING。SHA-256 不符时停止该来源核对。出现 ERROR 只报告，不自动改地图。

## 七项主页面字段覆盖

以下为结构覆盖检查，不证明正文语义或引文忠实度；默认缺项为 WARNING，`--strict-sections` 改为 ERROR，仅用于新书。

| 项目 | 已支持字段与别名 |
| --- | --- |
| 身份、版本和材料边界 | `book` + `source`，以及 `scope/source.credible_range/source.metadata_limitations/version_boundary` 之一 |
| 问题与展开 | `book.one_sentence_model/whole_book_model.question/central_question`，以及 `whole_book_model/coverage/volumes/works/core_route/generation_audit.whole_book_identity` 之一 |
| 观点与依据 | `claims[].statement/text`，以及 `locators/locator/source_excerpt_ids/derived_from/supports` |
| 关键关系 | `relationships/characters/conceptual_roles/themes/concepts/whole_book_model.stages/works[].series` |
| 内容标型 | `claims[].type/kind/label` |
| 回原文路线 | `core_route/deep_read_list/source_return_route/reading_route/original_reading_route` |
| 阅读决策 | `verdict/reading_decision/read_decision/next_steps` |
